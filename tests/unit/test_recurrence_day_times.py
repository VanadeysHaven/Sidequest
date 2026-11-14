"""Table-driven tests for weekly rules with different times per weekday (D90, D91, D96, D97).

A weekly rule may give each chosen weekday its own times (`day_times`). When every chosen day
has the same times it collapses to the plain shape. Covers validation, normalisation, JSON,
`with_week`, occurrences (including DST and `every`/`start`/suspensions), descriptions and the
`/todo edit` and `/todo repeat weekly` option helpers that guard such a week.
"""

from collections.abc import Callable
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sidequest.bot.options import (
    NEED_DAYS_AND_TIMES,
    PREFILL_BOTH,
    daily_rule,
    edited_rule,
    weekly_prefill,
)
from sidequest.core.enums import Weekday
from sidequest.core.errors import InvalidOperation, InvalidRule
from sidequest.core.recurrence import (
    DailyRule,
    RecurrenceRule,
    WeeklyRule,
    describe,
    from_json,
    next_occurrence,
    occurrences_between,
    to_json,
    with_week,
)

AMS = ZoneInfo("Europe/Amsterdam")
UTC = ZoneInfo("UTC")

Payload = dict[str, Any]

MIXED_DAYS: Payload = {
    "mon": ["05:10"],
    "tue": ["07:30"],
    "wed": ["05:10"],
    "thu": ["05:10"],
    "sat": ["09:00", "18:00"],
}
MIXED_TEXT = (
    "Monday, Wednesday and Thursday at 05:10, Tuesday at 07:30 and Saturday at 09:00 and 18:00"
)
ON_OFF_WEEK = 2  # the week of 23 Nov is off for every=2 from 16 Nov


def local(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=AMS)


def wall(occurrences: list[datetime]) -> list[datetime]:
    """Occurrences as naive Amsterdam wall-clock datetimes, to check local times directly."""
    return [o.astimezone(AMS).replace(tzinfo=None) for o in occurrences]


def naive(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm)


def mixed(**extra: Any) -> WeeklyRule:
    rule = from_json({"type": "weekly", "day_times": MIXED_DAYS, **extra})
    assert isinstance(rule, WeeklyRule)
    return rule


def plain(**extra: Any) -> WeeklyRule:
    rule = from_json({"type": "weekly", "weekdays": ["mon", "fri"], "times": ["05:10"], **extra})
    assert isinstance(rule, WeeklyRule)
    return rule


MIXED_WEEK_OF_16 = [
    local(2026, 11, 16, 5, 10),
    local(2026, 11, 17, 7, 30),
    local(2026, 11, 18, 5, 10),
    local(2026, 11, 19, 5, 10),
    local(2026, 11, 21, 9, 0),
    local(2026, 11, 21, 18, 0),
]


# --- construction and normalisation (D90, D91) -------------------------------------------


NORMALISED = [
    pytest.param(
        {"mon": ["05:10"], "tue": ["07:30"]},
        False,
        (Weekday.MON, Weekday.TUE),
        (),
        id="different-times-stay-mixed",
    ),
    pytest.param(
        {"mon": ["05:10"], "fri": ["05:10"]},
        True,
        (Weekday.MON, Weekday.FRI),
        (time(5, 10),),
        id="same-times-collapse-to-plain",
    ),
    pytest.param(
        {"fri": ["05:10"], "mon": ["05:10"], "wed": ["06:00"]},
        False,
        (Weekday.MON, Weekday.WED, Weekday.FRI),
        (),
        id="weekdays-in-monday-first-order",
    ),
    pytest.param(
        {"sun": ["08:00"], "mon": ["08:00"]},
        True,
        (Weekday.MON, Weekday.SUN),
        (time(8, 0),),
        id="sunday-last-collapses",
    ),
]


@pytest.mark.parametrize(("day_times", "collapsed", "weekdays", "times"), NORMALISED)
def test_day_times_normalise(
    day_times: dict[str, list[str]],
    collapsed: bool,
    weekdays: tuple[Weekday, ...],
    times: tuple[time, ...],
) -> None:
    rule = WeeklyRule(day_times=day_times)
    assert rule.has_day_times is not collapsed
    assert (rule.day_times is None) is collapsed
    assert rule.weekdays == weekdays
    assert rule.times == times


DEDUP_SORT = [
    pytest.param(
        {"mon": ["18:00", "05:10", "05:10"], "tue": ["07:30"]},
        Weekday.MON,
        (time(5, 10), time(18, 0)),
        id="sorted-and-deduplicated",
    ),
    pytest.param(
        {"mon": [time(18, 0), time(5, 10)], "tue": ["07:30"]},
        Weekday.MON,
        (time(5, 10), time(18, 0)),
        id="datetime-time-values",
    ),
    pytest.param(
        {Weekday.MON: ["05:10"], Weekday.TUE: ["07:30"]},
        Weekday.TUE,
        (time(7, 30),),
        id="weekday-enum-keys",
    ),
]


@pytest.mark.parametrize(("day_times", "day", "expected"), DEDUP_SORT)
def test_day_times_sorted_and_unique(
    day_times: dict[Any, Any], day: Weekday, expected: tuple[time, ...]
) -> None:
    rule = WeeklyRule(day_times=day_times)
    assert rule.times_for(day) == expected


INVALID_DAY_TIMES = [
    pytest.param(
        {"day_times": {"mon": [f"{h:02d}:00" for h in range(13)]}},
        id="thirteen-times-on-a-day",
    ),
    pytest.param({"day_times": {"mon": []}}, id="empty-list-for-a-day"),
    pytest.param({"day_times": {"xyz": ["05:10"]}}, id="unknown-weekday-key"),
    pytest.param({"day_times": {}}, id="empty-day-times"),
    pytest.param(
        {"times": ["05:10"], "day_times": {"mon": ["07:30"], "tue": ["07:30"]}},
        id="times-and-day-times-together",
    ),
]


@pytest.mark.parametrize("kwargs", INVALID_DAY_TIMES)
def test_invalid_day_times_raise_invalid_rule(kwargs: dict[str, Any]) -> None:
    with pytest.raises(InvalidRule):
        WeeklyRule(**kwargs)


def test_twelve_times_on_a_day_is_allowed() -> None:
    rule = WeeklyRule(day_times={"mon": [f"{h:02d}:00" for h in range(12)], "tue": ["07:30"]})
    assert len(rule.times_for(Weekday.MON)) == 12


# --- accessors ---------------------------------------------------------------------------


ACCESSORS = [
    pytest.param(mixed(), Weekday.MON, (time(5, 10),), id="mixed-monday"),
    pytest.param(mixed(), Weekday.SAT, (time(9, 0), time(18, 0)), id="mixed-saturday"),
    pytest.param(mixed(), Weekday.SUN, (), id="mixed-not-chosen"),
    pytest.param(plain(), Weekday.FRI, (time(5, 10),), id="plain-chosen-day"),
    pytest.param(plain(), Weekday.TUE, (), id="plain-not-chosen-day"),
]


@pytest.mark.parametrize(("rule", "day", "expected"), ACCESSORS)
def test_times_for(rule: WeeklyRule, day: Weekday, expected: tuple[time, ...]) -> None:
    assert rule.times_for(day) == expected


def test_week_maps_chosen_days_in_weekday_order() -> None:
    week = mixed().week
    assert list(week) == [Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.SAT]
    assert week == {
        Weekday.MON: (time(5, 10),),
        Weekday.TUE: (time(7, 30),),
        Weekday.WED: (time(5, 10),),
        Weekday.THU: (time(5, 10),),
        Weekday.SAT: (time(9, 0), time(18, 0)),
    }


def test_plain_rule_week_and_flags() -> None:
    rule = plain()
    assert rule.has_day_times is False
    assert rule.times == (time(5, 10),)
    assert rule.week == {Weekday.MON: (time(5, 10),), Weekday.FRI: (time(5, 10),)}


def test_mixed_rule_flags() -> None:
    rule = mixed()
    assert rule.has_day_times is True
    assert rule.times == ()
    assert rule.weekdays == (Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.SAT)


# --- JSON (D88, D91) ---------------------------------------------------------------------


def test_plain_rule_to_json_has_no_day_times_key() -> None:
    assert to_json(plain()) == {"type": "weekly", "weekdays": ["mon", "fri"], "times": ["05:10"]}


def test_mixed_rule_to_json_has_only_day_times() -> None:
    assert to_json(mixed()) == {
        "type": "weekly",
        "day_times": {
            "mon": ["05:10"],
            "tue": ["07:30"],
            "wed": ["05:10"],
            "thu": ["05:10"],
            "sat": ["09:00", "18:00"],
        },
    }


def test_mixed_rule_to_json_keeps_every_window_and_suspensions() -> None:
    rule = mixed(
        every=2,
        start="2026-11-16",
        end="2027-03-01",
        suspended=[{"start": "2026-11-17", "end": "2026-11-18"}],
    )
    assert to_json(rule) == {
        "type": "weekly",
        "day_times": {
            "mon": ["05:10"],
            "tue": ["07:30"],
            "wed": ["05:10"],
            "thu": ["05:10"],
            "sat": ["09:00", "18:00"],
        },
        "every": 2,
        "start": "2026-11-16",
        "end": "2027-03-01",
        "suspended": [{"start": "2026-11-17", "end": "2026-11-18"}],
    }


JSON_ROUND_TRIP = [
    pytest.param(plain(), id="plain"),
    pytest.param(mixed(), id="mixed"),
    pytest.param(mixed(every=3, start="2026-11-16"), id="mixed-every-start"),
    pytest.param(plain(start="2026-11-16", end="2026-12-31"), id="plain-window"),
]


@pytest.mark.parametrize("rule", JSON_ROUND_TRIP)
def test_json_round_trip(rule: WeeklyRule) -> None:
    assert from_json(to_json(rule)) == rule


def test_old_style_row_loads_and_dumps_unchanged() -> None:
    payload: Payload = {"type": "weekly", "weekdays": ["mon"], "times": ["12:00"]}
    rule = from_json(payload)
    assert isinstance(rule, WeeklyRule)
    assert rule.has_day_times is False
    assert to_json(rule) == payload


# --- with_week (D96 and the week builder) ------------------------------------------------


def test_with_week_keeps_every_window_and_suspensions() -> None:
    base = WeeklyRule(
        weekdays=(Weekday.MON,),
        times=(time(12, 0),),
        every=2,
        start=date(2026, 11, 16),
        end=date(2027, 3, 1),
        suspended=[{"start": date(2026, 12, 1), "end": date(2026, 12, 3)}],
    )
    new = with_week(base, {Weekday.TUE: (time(7, 30),), Weekday.SAT: (time(9, 0), time(18, 0))})
    assert new.has_day_times is True
    assert new.week == {Weekday.TUE: (time(7, 30),), Weekday.SAT: (time(9, 0), time(18, 0))}
    assert new.every == 2
    assert new.start == date(2026, 11, 16)
    assert new.end == date(2027, 3, 1)
    assert new.suspended == base.suspended


WITH_WEEK_COLLAPSE = [
    pytest.param(
        {Weekday.MON: (time(5, 10),), Weekday.WED: (time(5, 10),)},
        (Weekday.MON, Weekday.WED),
        (time(5, 10),),
        id="equal-times-collapse",
    ),
    pytest.param(
        {Weekday.MON: (time(5, 10),), Weekday.TUE: (time(6, 0),)},
        (Weekday.MON, Weekday.TUE),
        (),
        id="different-times-stay-mixed",
    ),
]


@pytest.mark.parametrize(("week", "weekdays", "times"), WITH_WEEK_COLLAPSE)
def test_with_week_collapses_when_times_are_equal(
    week: dict[Weekday, tuple[time, ...]], weekdays: tuple[Weekday, ...], times: tuple[time, ...]
) -> None:
    new = with_week(mixed(), week)
    assert new.weekdays == weekdays
    assert new.times == times
    assert new.has_day_times is (not times)


def test_with_week_empty_week_is_invalid() -> None:
    with pytest.raises(InvalidRule):
        with_week(mixed(), {})


# --- occurrences (D90) -------------------------------------------------------------------


NEXT_CASES = [
    pytest.param(local(2026, 11, 16, 5, 10), local(2026, 11, 17, 7, 30), id="mon-to-tue"),
    pytest.param(local(2026, 11, 17, 7, 30), local(2026, 11, 18, 5, 10), id="tue-to-wed"),
    pytest.param(local(2026, 11, 18, 5, 10), local(2026, 11, 19, 5, 10), id="wed-to-thu"),
    pytest.param(local(2026, 11, 19, 5, 10), local(2026, 11, 21, 9, 0), id="thu-to-sat"),
    pytest.param(local(2026, 11, 21, 9, 0), local(2026, 11, 21, 18, 0), id="sat-two-times"),
    pytest.param(local(2026, 11, 21, 18, 0), local(2026, 11, 23, 5, 10), id="sat-to-next-mon"),
    pytest.param(local(2026, 11, 22, 23, 0), local(2026, 11, 23, 5, 10), id="sun-night"),
]


@pytest.mark.parametrize(("after", "expected"), NEXT_CASES)
def test_next_occurrence_uses_each_days_times(after: datetime, expected: datetime) -> None:
    assert next_occurrence(mixed(), AMS, after) == expected


def test_mixed_week_occurrences_in_one_week() -> None:
    found = occurrences_between(mixed(), AMS, local(2026, 11, 16, 0, 0), local(2026, 11, 23, 0, 0))
    assert found == MIXED_WEEK_OF_16
    assert wall(found) == [
        naive(2026, 11, 16, 5, 10),
        naive(2026, 11, 17, 7, 30),
        naive(2026, 11, 18, 5, 10),
        naive(2026, 11, 19, 5, 10),
        naive(2026, 11, 21, 9, 0),
        naive(2026, 11, 21, 18, 0),
    ]


DST_SPRING = [
    pytest.param(
        local(2026, 3, 28, 0, 0),
        local(2026, 3, 30, 0, 0),
        [
            naive(2026, 3, 28, 2, 30),  # Saturday: no gap, stays 02:30
            naive(2026, 3, 29, 3, 30),  # Sunday 02:30 is in the gap: shifts to 03:30
            naive(2026, 3, 29, 12, 0),
        ],
        id="spring-forward-gap",
    ),
]


@pytest.mark.parametrize(("start", "end", "expected_wall"), DST_SPRING)
def test_spring_forward_keeps_gap_entries_forward(
    start: datetime, end: datetime, expected_wall: list[datetime]
) -> None:
    rule = from_json({"type": "weekly", "day_times": {"sat": ["02:30"], "sun": ["02:30", "12:00"]}})
    assert wall(occurrences_between(rule, AMS, start, end)) == expected_wall


def test_fall_back_keeps_wall_clock_on_both_sides() -> None:
    rule = from_json(
        {
            "type": "weekly",
            "day_times": {"sat": ["09:00"], "sun": ["02:30", "09:00"], "mon": ["09:00"]},
        }
    )
    found = occurrences_between(rule, AMS, local(2026, 10, 24, 0, 0), local(2026, 10, 27, 0, 0))
    assert wall(found) == [
        naive(2026, 10, 24, 9, 0),
        naive(2026, 10, 25, 2, 30),  # ambiguous: fires once, the first instance (CEST)
        naive(2026, 10, 25, 9, 0),
        naive(2026, 10, 26, 9, 0),
    ]
    assert found == [
        datetime(2026, 10, 24, 7, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
        datetime(2026, 10, 25, 8, 0, tzinfo=UTC),
        datetime(2026, 10, 26, 8, 0, tzinfo=UTC),
    ]


# --- every (D54-D59) with a mixed week ---------------------------------------------------


EVERY_TWO_WINDOWS = [
    pytest.param("2026-11-16", "2026-11-23", 6, id="week-of-16-nov-on"),
    pytest.param("2026-11-23", "2026-11-30", 0, id="week-of-23-nov-off"),
    pytest.param("2026-11-30", "2026-12-07", 6, id="week-of-30-nov-on"),
    pytest.param("2026-12-07", "2026-12-14", 0, id="week-of-7-dec-off"),
    pytest.param("2026-12-14", "2026-12-21", 6, id="week-of-14-dec-on"),
]


@pytest.mark.parametrize(("start", "end", "count"), EVERY_TWO_WINDOWS)
def test_every_two_weeks_on_and_off_weeks(start: str, end: str, count: int) -> None:
    rule = mixed(every=ON_OFF_WEEK, start="2026-11-16")
    y1, m1, d1 = (int(p) for p in start.split("-"))
    y2, m2, d2 = (int(p) for p in end.split("-"))
    found = occurrences_between(rule, AMS, local(y1, m1, d1, 0, 0), local(y2, m2, d2, 0, 0))
    assert len(found) == count


def test_every_two_weeks_first_week_matches_the_mixed_week() -> None:
    rule = mixed(every=ON_OFF_WEEK, start="2026-11-16")
    found = occurrences_between(rule, AMS, local(2026, 11, 16, 0, 0), local(2026, 11, 23, 0, 0))
    assert found == MIXED_WEEK_OF_16


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda r: to_json(r), id="to-json"),
        pytest.param(lambda r: next_occurrence(r, AMS, local(2026, 11, 14, 0, 0)), id="next"),
    ],
)
def test_every_two_without_start_must_be_anchored(
    call: Callable[[WeeklyRule], object],
) -> None:
    rule = WeeklyRule(weekdays=(Weekday.MON,), times=(time(12, 0),), every=ON_OFF_WEEK)
    with pytest.raises(ValueError, match="no start"):
        call(rule)


# --- suspensions (D81, D83) on a mixed week ----------------------------------------------


def test_suspension_skips_only_its_days() -> None:
    rule = mixed(suspended=[{"start": "2026-11-17", "end": "2026-11-18"}])
    found = occurrences_between(rule, AMS, local(2026, 11, 16, 0, 0), local(2026, 11, 23, 0, 0))
    assert found == [
        local(2026, 11, 16, 5, 10),
        local(2026, 11, 19, 5, 10),
        local(2026, 11, 21, 9, 0),
        local(2026, 11, 21, 18, 0),
    ]


# --- describe (D97) ----------------------------------------------------------------------


DESCRIBE = [
    pytest.param(
        mixed(),
        AMS,
        None,
        f"Every {MIXED_TEXT} (Europe/Amsterdam)",
        id="mixed-week",
    ),
    pytest.param(
        mixed(every=2, start="2026-11-16"),
        AMS,
        date(2026, 11, 14),
        f"Every 2 weeks on {MIXED_TEXT} (Europe/Amsterdam), from 16-11-2026",
        id="every-two-start-ahead",
    ),
    pytest.param(
        mixed(every=2, start="2026-11-16"),
        AMS,
        date(2026, 11, 16),
        f"Every 2 weeks on {MIXED_TEXT} (Europe/Amsterdam)",
        id="start-today-no-from",
    ),
    pytest.param(
        mixed(every=2, start="2026-11-16", end="2026-12-31"),
        AMS,
        date(2026, 11, 14),
        f"Every 2 weeks on {MIXED_TEXT} (Europe/Amsterdam), from 16-11-2026, until 31-12-2026",
        id="every-two-with-window",
    ),
    pytest.param(
        plain(),
        UTC,
        None,
        "Every Monday and Friday at 05:10 (UTC)",
        id="collapsed-plain-unchanged",
    ),
    pytest.param(
        plain(end="2026-12-31"),
        UTC,
        date(2026, 11, 14),
        "Every Monday and Friday at 05:10 (UTC), until 31-12-2026",
        id="collapsed-with-end",
    ),
]


@pytest.mark.parametrize(("rule", "tz", "today", "expected"), DESCRIBE)
def test_describe(rule: RecurrenceRule, tz: ZoneInfo, today: date | None, expected: str) -> None:
    assert describe(rule, tz, today) == expected


# --- /todo edit guards (D96) -------------------------------------------------------------


def test_mixed_week_rejects_times_with_bold_title() -> None:
    with pytest.raises(InvalidOperation) as info:
        edited_rule(mixed(), times="06:00", title="Gym")
    assert info.value.message == (
        "**Gym** has different times per day; use `custom-times:true` to change its week."
    )


@pytest.mark.parametrize(
    ("options", "title", "expected"),
    [
        pytest.param({"times": "06:00"}, "Gym", "**Gym**", id="times-bold"),
        pytest.param({"days": "mon"}, "Gym", "**Gym**", id="days-bold"),
        pytest.param({"times": "06:00"}, "Gym*", "**Gym\\***", id="markdown-escaped"),
    ],
)
def test_mixed_week_message_names_the_title(
    options: dict[str, str], title: str, expected: str
) -> None:
    with pytest.raises(InvalidOperation) as info:
        edited_rule(mixed(), title=title, **options)
    assert info.value.message == (
        f"{expected} has different times per day; use `custom-times:true` to change its week."
    )


def test_plain_weekly_rule_accepts_times() -> None:
    result = edited_rule(plain(), times="06:00")
    assert isinstance(result, WeeklyRule)
    assert result.times == (time(6, 0),)
    assert result.has_day_times is False


def test_mixed_week_keeps_day_times_when_every_changes() -> None:
    result = edited_rule(mixed(), every=2)
    assert isinstance(result, WeeklyRule)
    assert result.every == 2
    assert result.has_day_times is True
    assert result.week == mixed().week


@pytest.mark.parametrize(
    "rule",
    [pytest.param(mixed(), id="mixed"), pytest.param(plain(), id="plain")],
)
@pytest.mark.parametrize(
    "options",
    [
        pytest.param({"days": "mon"}, id="days"),
        pytest.param({"times": "06:00"}, id="times"),
    ],
)
def test_custom_times_cannot_combine_with_days_or_times(
    rule: WeeklyRule, options: dict[str, str]
) -> None:
    with pytest.raises(InvalidOperation) as info:
        edited_rule(rule, custom_times=True, **options)
    assert info.value.message == "`custom-times` can't be combined with `days` or `times`."


def test_daily_rule_refuses_custom_times() -> None:
    rule = daily_rule("08:00")
    assert isinstance(rule, DailyRule)
    with pytest.raises(InvalidOperation, match="can't be changed"):
        edited_rule(rule, custom_times=True)


# --- /todo repeat weekly prefill (D92, D96) ----------------------------------------------


PREFILL = [
    pytest.param(None, None, False, NEED_DAYS_AND_TIMES, id="nothing-no-builder"),
    pytest.param("mon", None, False, NEED_DAYS_AND_TIMES, id="days-only-no-builder"),
    pytest.param("mon", None, True, PREFILL_BOTH, id="days-only-builder"),
    pytest.param(None, "06:00", True, PREFILL_BOTH, id="times-only-builder"),
    pytest.param(None, None, True, None, id="neither-builder-empty-week"),
]


@pytest.mark.parametrize(("days", "times", "custom", "message"), PREFILL)
def test_weekly_prefill_errors_and_empty_week(
    days: str | None,
    times: str | None,
    custom: bool,
    message: str | None,
) -> None:
    if message is None:
        assert weekly_prefill(days, times, custom_times=custom) is None
        return
    with pytest.raises(InvalidOperation) as info:
        weekly_prefill(days, times, custom_times=custom)
    assert info.value.message == message


def test_weekly_prefill_with_both_builds_a_weekly_rule() -> None:
    for custom in (False, True):
        rule = weekly_prefill("mon,fri", "05:10", custom_times=custom)
        assert isinstance(rule, WeeklyRule)
        assert rule.weekdays == (Weekday.MON, Weekday.FRI)
        assert rule.times == (time(5, 10),)
