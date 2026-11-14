"""Table-driven tests for the `start` / `end` window of repeat rules in sidequest.core.recurrence.

Covers first and last occurrences, refused and equal start/end, JSON shape, series end, DST edges,
describe suffixes and occurrences_between.
"""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sidequest.core.errors import InvalidRule
from sidequest.core.recurrence import (
    END_BEFORE_START,
    DailyRule,
    MonthlyDayRule,
    MonthlyRule,
    WeeklyRule,
    describe,
    from_json,
    next_occurrence,
    occurrences_between,
    to_json,
)

AMS = ZoneInfo("Europe/Amsterdam")
UTC = ZoneInfo("UTC")

Payload = dict[str, Any]

# Before every window used below, so "first occurrence" means the first one of the series.
AFTER_ALL = datetime(2026, 11, 1, tzinfo=UTC)
FAR_FUTURE = datetime(2030, 1, 1, tzinfo=UTC)


def utc(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


def daily(times: list[str], **extra: Any) -> Payload:
    return {"type": "daily", "times": times, **extra}


def weekly(weekdays: list[str], times: list[str], **extra: Any) -> Payload:
    return {"type": "weekly", "weekdays": weekdays, "times": times, **extra}


def monthly(week: int, weekday: str, times: list[str], **extra: Any) -> Payload:
    return {"type": "monthly", "week": week, "weekday": weekday, "times": times, **extra}


def monthly_day(day: int, times: list[str], **extra: Any) -> Payload:
    return {"type": "monthly_day", "day": day, "times": times, **extra}


# --- first and last occurrence -----------------------------------------------------------
# Winter in Amsterdam is UTC+1, so 08:00 local is 07:00 UTC, 09:00 is 08:00, 12:00 is 11:00.

FIRST_AND_LAST = [
    pytest.param(
        daily(["08:00"], start="2026-11-18"),
        AMS,
        utc(2026, 11, 18, 7, 0),
        None,
        id="daily-start-only",
    ),
    pytest.param(
        daily(["08:00"], end="2026-11-17"),
        AMS,
        utc(2026, 11, 1, 7, 0),
        utc(2026, 11, 17, 7, 0),
        id="daily-end-only",
    ),
    pytest.param(
        daily(["08:00"], start="2026-11-16", end="2026-11-18"),
        AMS,
        utc(2026, 11, 16, 7, 0),
        utc(2026, 11, 18, 7, 0),
        id="daily-start-and-end",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["08:00"], start="2026-11-17"),
        AMS,
        utc(2026, 11, 19, 7, 0),
        None,
        id="weekly-mon-thu-start-only",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["08:00"], end="2026-11-20"),
        AMS,
        utc(2026, 11, 2, 7, 0),
        utc(2026, 11, 19, 7, 0),
        id="weekly-mon-thu-end-only",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["08:00"], start="2026-11-16", end="2026-11-26"),
        AMS,
        utc(2026, 11, 16, 7, 0),
        utc(2026, 11, 26, 7, 0),
        id="weekly-mon-thu-start-and-end",
    ),
    pytest.param(
        monthly(1, "sun", ["12:00"], start="2026-11-10"),
        AMS,
        utc(2026, 12, 6, 11, 0),
        None,
        id="monthly-first-sunday-start-only",
    ),
    pytest.param(
        monthly(1, "sun", ["12:00"], end="2026-12-20"),
        AMS,
        utc(2026, 11, 1, 11, 0),
        utc(2026, 12, 6, 11, 0),
        id="monthly-first-sunday-end-only",
    ),
    pytest.param(
        monthly(1, "sun", ["12:00"], start="2026-11-10", end="2027-01-31"),
        AMS,
        utc(2026, 12, 6, 11, 0),
        utc(2027, 1, 3, 11, 0),
        id="monthly-first-sunday-start-and-end",
    ),
    pytest.param(
        monthly_day(15, ["09:00"], start="2026-11-20"),
        AMS,
        utc(2026, 12, 15, 8, 0),
        None,
        id="monthly-day-15-start-only",
    ),
    pytest.param(
        monthly_day(15, ["09:00"], end="2027-01-20"),
        AMS,
        utc(2026, 11, 15, 8, 0),
        utc(2027, 1, 15, 8, 0),
        id="monthly-day-15-end-only",
    ),
    pytest.param(
        monthly_day(15, ["09:00"], start="2026-11-20", end="2027-02-14"),
        AMS,
        utc(2026, 12, 15, 8, 0),
        utc(2027, 1, 15, 8, 0),
        id="monthly-day-15-start-and-end",
    ),
    pytest.param(
        daily(["08:00"], start="2026-11-16", end="2026-11-17"),
        UTC,
        utc(2026, 11, 16, 8, 0),
        utc(2026, 11, 17, 8, 0),
        id="daily-start-and-end-utc",
    ),
    pytest.param(
        weekly(["mon"], ["08:00"], start="2026-11-16", end="2026-11-30"),
        UTC,
        utc(2026, 11, 16, 8, 0),
        utc(2026, 11, 30, 8, 0),
        id="weekly-mon-start-and-end-utc",
    ),
    # Start and end need not be matching days.
    pytest.param(
        weekly(["mon"], ["08:00"], start="2026-11-18", end="2026-12-06"),
        AMS,
        utc(2026, 11, 23, 7, 0),
        utc(2026, 11, 30, 7, 0),
        id="weekly-mon-start-wed-end-sun",
    ),
    pytest.param(
        monthly_day(15, ["09:00"], start="2026-11-16", end="2027-01-14"),
        AMS,
        utc(2026, 12, 15, 8, 0),
        utc(2026, 12, 15, 8, 0),
        id="monthly-day-15-start-after-15th-end-before-15th",
    ),
    pytest.param(
        monthly(1, "sun", ["12:00"], start="2026-11-02", end="2027-01-04"),
        AMS,
        utc(2026, 12, 6, 11, 0),
        utc(2027, 1, 3, 11, 0),
        id="monthly-first-sunday-start-after-first-end-monday",
    ),
]


@pytest.mark.parametrize(("payload", "tz", "expected_first", "expected_last"), FIRST_AND_LAST)
def test_first_and_last_occurrence(
    payload: Payload, tz: ZoneInfo, expected_first: datetime, expected_last: datetime | None
) -> None:
    rule = from_json(payload)

    assert next_occurrence(rule, tz, AFTER_ALL) == expected_first
    if rule.end is None:
        assert expected_last is None
        return
    occurrences = occurrences_between(rule, tz, AFTER_ALL, FAR_FUTURE)
    assert occurrences[-1] == expected_last
    assert next_occurrence(rule, tz, expected_last) is None


# --- end before start is refused, end equal to start is accepted --------------------------

END_BEFORE_START_PAYLOADS = [
    pytest.param(
        daily(["08:00"], start="2026-11-18", end="2026-11-17"),
        id="daily",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["08:00"], start="2026-11-18", end="2026-11-17"),
        id="weekly",
    ),
    pytest.param(
        monthly(1, "sun", ["12:00"], start="2026-11-18", end="2026-11-17"),
        id="monthly",
    ),
    pytest.param(
        monthly_day(15, ["09:00"], start="2026-11-18", end="2026-11-17"),
        id="monthly-day",
    ),
]


@pytest.mark.parametrize("payload", END_BEFORE_START_PAYLOADS)
def test_end_before_start_is_refused(payload: Payload) -> None:
    with pytest.raises(InvalidRule) as exc:
        from_json(payload)

    assert exc.value.message == END_BEFORE_START
    assert exc.value.message == "The end date can't be before the start date."


DIRECT_CONSTRUCTION = [
    pytest.param(DailyRule, {"times": ["08:00"]}, id="daily"),
    pytest.param(WeeklyRule, {"weekdays": ["mon"], "times": ["08:00"]}, id="weekly"),
    pytest.param(MonthlyRule, {"week": 1, "weekday": "sun", "times": ["12:00"]}, id="monthly"),
    pytest.param(MonthlyDayRule, {"day": 15, "times": ["09:00"]}, id="monthly-day"),
]


@pytest.mark.parametrize(("cls", "kwargs"), DIRECT_CONSTRUCTION)
def test_direct_construction_refuses_end_before_start(cls: Any, kwargs: Payload) -> None:
    with pytest.raises(InvalidRule) as exc:
        cls(start=date(2026, 11, 18), end=date(2026, 11, 17), **kwargs)

    assert exc.value.message == END_BEFORE_START


EQUAL_START_AND_END = [
    pytest.param(
        daily(["08:00"], start="2026-11-18", end="2026-11-18"),
        utc(2026, 11, 18, 7, 0),
        id="daily",
    ),
    pytest.param(
        weekly(["mon"], ["08:00"], start="2026-11-16", end="2026-11-16"),
        utc(2026, 11, 16, 7, 0),
        id="weekly-on-its-start-day",
    ),
    pytest.param(
        monthly(1, "sun", ["12:00"], start="2026-12-06", end="2026-12-06"),
        utc(2026, 12, 6, 11, 0),
        id="monthly",
    ),
    pytest.param(
        monthly_day(15, ["09:00"], start="2026-11-15", end="2026-11-15"),
        utc(2026, 11, 15, 8, 0),
        id="monthly-day",
    ),
]


@pytest.mark.parametrize(("payload", "expected"), EQUAL_START_AND_END)
def test_end_equal_to_start_fires_once(payload: Payload, expected: datetime) -> None:
    rule = from_json(payload)

    assert next_occurrence(rule, AMS, AFTER_ALL) == expected
    assert next_occurrence(rule, AMS, expected) is None


# --- JSON round trip ----------------------------------------------------------------------

ROUND_TRIP_WITH_WINDOW = [
    pytest.param(daily(["08:00"], start="2026-11-16", end="2026-11-18"), id="daily"),
    pytest.param(daily(["08:00"], end="2026-11-18"), id="daily-end-only"),
    pytest.param(
        weekly(["mon"], ["07:00"], start="2026-11-16", end="2026-11-30"),
        id="weekly",
    ),
    pytest.param(
        monthly(1, "sun", ["12:00"], start="2026-11-10", end="2027-01-31"),
        id="monthly",
    ),
    pytest.param(monthly_day(15, ["09:00"], end="2027-01-20"), id="monthly-day-end-only"),
]


@pytest.mark.parametrize("payload", ROUND_TRIP_WITH_WINDOW)
def test_round_trip_with_start_and_end(payload: Payload) -> None:
    rule = from_json(payload)

    assert to_json(rule) == payload
    assert from_json(to_json(rule)) == rule


OLD_SHAPES = [
    pytest.param({"type": "daily", "times": ["08:00"]}, id="daily"),
    pytest.param({"type": "daily", "times": ["08:00", "20:00"]}, id="daily-two-times"),
    pytest.param(weekly(["mon", "thu"], ["12:00"]), id="weekly-no-every-or-start"),
    pytest.param(monthly(1, "sun", ["12:00"]), id="monthly"),
    pytest.param(monthly_day(15, ["09:00"]), id="monthly-day"),
]


@pytest.mark.parametrize("payload", OLD_SHAPES)
def test_old_shapes_round_trip_unchanged(payload: Payload) -> None:
    rule = from_json(payload)

    assert to_json(rule) == payload
    assert not {"start", "end"} & set(to_json(rule))


# --- next_occurrence after the series is over ---------------------------------------------

NONE_AFTER_END = [
    pytest.param(
        daily(["08:00"], end="2026-11-18"),
        utc(2026, 11, 18, 7, 0),
        id="daily-after-last",
    ),
    pytest.param(
        daily(["08:00"], end="2026-11-18"),
        utc(2026, 12, 1, 0, 0),
        id="daily-after-end-moment",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["08:00"], end="2026-11-26"),
        utc(2026, 11, 26, 7, 0),
        id="weekly-after-last",
    ),
    pytest.param(
        monthly(1, "sun", ["12:00"], end="2026-12-20"),
        utc(2026, 12, 6, 11, 0),
        id="monthly-after-last",
    ),
    pytest.param(
        monthly(1, "sun", ["12:00"], end="2026-12-20"),
        utc(2027, 3, 1, 0, 0),
        id="monthly-after-end-moment",
    ),
    pytest.param(
        monthly_day(15, ["09:00"], end="2027-01-20"),
        utc(2027, 1, 15, 8, 0),
        id="monthly-day-after-last",
    ),
]


@pytest.mark.parametrize(("payload", "after"), NONE_AFTER_END)
def test_next_occurrence_is_none_after_the_series(payload: Payload, after: datetime) -> None:
    assert next_occurrence(from_json(payload), AMS, after) is None


# --- weekly every = 2 with a window -------------------------------------------------------

EVERY_TWO_WINDOW = [
    pytest.param(
        weekly(["mon", "thu"], ["12:00"], every=2, start="2026-11-16", end="2027-01-14"),
        [
            utc(2026, 11, 16, 11, 0),
            utc(2026, 11, 19, 11, 0),
            utc(2026, 11, 30, 11, 0),
            utc(2026, 12, 3, 11, 0),
            utc(2026, 12, 14, 11, 0),
            utc(2026, 12, 17, 11, 0),
            utc(2026, 12, 28, 11, 0),
            utc(2026, 12, 31, 11, 0),
            utc(2027, 1, 11, 11, 0),
            utc(2027, 1, 14, 11, 0),
        ],
        id="start-and-end-on-week-cadence",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["12:00"], every=2, start="2026-11-16", end="2026-12-02"),
        [utc(2026, 11, 16, 11, 0), utc(2026, 11, 19, 11, 0), utc(2026, 11, 30, 11, 0)],
        id="end-cuts-off-in-the-middle-of-the-week-cadence",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["12:00"], every=2, start="2026-11-18", end="2026-12-03"),
        [utc(2026, 11, 19, 11, 0), utc(2026, 11, 30, 11, 0), utc(2026, 12, 3, 11, 0)],
        id="start-midweek-keeps-that-monday-week",
    ),
]


@pytest.mark.parametrize(("payload", "expected"), EVERY_TWO_WINDOW)
def test_every_two_weeks_with_window(payload: Payload, expected: list[datetime]) -> None:
    rule = from_json(payload)

    assert occurrences_between(rule, AMS, AFTER_ALL, FAR_FUTURE) == expected
    assert next_occurrence(rule, AMS, expected[-1]) is None


# --- DST edges on the last / first day of a window ----------------------------------------

DST_EDGES = [
    pytest.param(
        daily(["02:30"], start="2026-10-24", end="2026-10-25"),
        utc(2026, 10, 24, 0, 0),
        utc(2026, 10, 31, 0, 0),
        [utc(2026, 10, 24, 0, 30), utc(2026, 10, 25, 0, 30)],
        id="fall-back-last-day-fires-once-at-first-instance",
    ),
    pytest.param(
        daily(["02:30"]),
        utc(2026, 10, 25, 0, 0),
        utc(2026, 10, 26, 0, 0),
        [utc(2026, 10, 25, 0, 30)],
        id="fall-back-day-fires-once-without-end",
    ),
    pytest.param(
        daily(["02:30"], start="2026-03-29", end="2026-03-29"),
        utc(2026, 3, 28, 0, 0),
        utc(2026, 3, 31, 0, 0),
        [utc(2026, 3, 29, 1, 30)],
        id="spring-gap-last-day-shifts-to-0330-local",
    ),
    pytest.param(
        daily(["02:30"], start="2026-03-29"),
        utc(2026, 3, 29, 0, 0),
        utc(2026, 3, 31, 0, 0),
        [utc(2026, 3, 29, 1, 30), utc(2026, 3, 30, 0, 30)],
        id="spring-gap-day-then-normal-day-without-end",
    ),
]


@pytest.mark.parametrize(("payload", "window_start", "window_end", "expected"), DST_EDGES)
def test_dst_edges_within_window(
    payload: Payload, window_start: datetime, window_end: datetime, expected: list[datetime]
) -> None:
    rule = from_json(payload)

    assert occurrences_between(rule, AMS, window_start, window_end) == expected


# --- describe: pattern plus from / until suffixes -----------------------------------------

DESCRIBE_SUFFIXES = [
    pytest.param(
        daily(["08:00"], start="2026-11-16", end="2026-11-18"),
        UTC,
        date(2026, 11, 14),
        "Every day at 08:00 (UTC), from 16-11-2026, until 18-11-2026",
        id="today-before-start-shows-from-and-until",
    ),
    pytest.param(
        daily(["08:00"], start="2026-11-16", end="2026-11-18"),
        UTC,
        date(2026, 11, 16),
        "Every day at 08:00 (UTC), until 18-11-2026",
        id="today-equal-to-start-hides-from",
    ),
    pytest.param(
        daily(["08:00"], start="2026-11-16", end="2026-11-18"),
        UTC,
        date(2026, 11, 17),
        "Every day at 08:00 (UTC), until 18-11-2026",
        id="today-after-start-hides-from",
    ),
    pytest.param(
        daily(["08:00"], start="2026-11-16", end="2026-11-18"),
        UTC,
        None,
        "Every day at 08:00 (UTC), from 16-11-2026, until 18-11-2026",
        id="no-today-always-shows-from",
    ),
    pytest.param(
        daily(["08:00"], start="2026-11-16"),
        UTC,
        date(2026, 11, 14),
        "Every day at 08:00 (UTC), from 16-11-2026",
        id="start-only-shown-before-start",
    ),
    pytest.param(
        daily(["08:00"], start="2026-11-16"),
        UTC,
        date(2026, 11, 16),
        "Every day at 08:00 (UTC)",
        id="start-only-hidden-on-start-day",
    ),
    pytest.param(
        daily(["08:00"], end="2026-11-18"),
        UTC,
        date(2026, 11, 14),
        "Every day at 08:00 (UTC), until 18-11-2026",
        id="end-only",
    ),
    pytest.param(
        daily(["08:00"]),
        UTC,
        date(2026, 11, 14),
        "Every day at 08:00 (UTC)",
        id="neither-with-today",
    ),
    pytest.param(
        daily(["08:00"]),
        UTC,
        None,
        "Every day at 08:00 (UTC)",
        id="neither-without-today",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["12:00"], start="2026-11-16", end="2026-11-26"),
        AMS,
        date(2026, 11, 14),
        "Every Monday and Thursday at 12:00 (Europe/Amsterdam), from 16-11-2026, until 26-11-2026",
        id="weekly-pattern-with-both-suffixes",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["12:00"], every=2, start="2026-11-16", end="2027-01-14"),
        AMS,
        None,
        "Every 2 weeks on Monday and Thursday at 12:00 (Europe/Amsterdam), "
        "from 16-11-2026, until 14-01-2027",
        id="every-2-pattern-with-both-suffixes",
    ),
    pytest.param(
        monthly(1, "sun", ["12:00"]),
        AMS,
        date(2026, 11, 14),
        "Every first Sunday of the month at 12:00 (Europe/Amsterdam)",
        id="monthly-pattern-no-dates",
    ),
    pytest.param(
        monthly_day(15, ["09:00"], start="2026-11-20", end="2027-01-20"),
        AMS,
        date(2026, 11, 14),
        "Every month on the 15th at 09:00 (Europe/Amsterdam), from 20-11-2026, until 20-01-2027",
        id="monthly-day-pattern-with-both-suffixes",
    ),
]


@pytest.mark.parametrize(("payload", "tz", "today", "expected"), DESCRIBE_SUFFIXES)
def test_describe_from_and_until_suffixes(
    payload: Payload, tz: ZoneInfo, today: date | None, expected: str
) -> None:
    assert describe(from_json(payload), tz, today) == expected


# --- occurrences_between stops at end ------------------------------------------------------

BETWEEN_WITH_END = [
    pytest.param(
        daily(["08:00"], start="2026-11-16", end="2026-11-18"),
        utc(2026, 11, 1, 0, 0),
        utc(2026, 12, 31, 0, 0),
        [utc(2026, 11, 16, 7, 0), utc(2026, 11, 17, 7, 0), utc(2026, 11, 18, 7, 0)],
        id="window-longer-than-series",
    ),
    pytest.param(
        daily(["08:00"], start="2026-11-16", end="2026-11-18"),
        utc(2026, 11, 16, 0, 0),
        utc(2026, 11, 17, 12, 0),
        [utc(2026, 11, 16, 7, 0), utc(2026, 11, 17, 7, 0)],
        id="window-ends-before-series-end",
    ),
    pytest.param(
        daily(["08:00"], start="2026-11-16", end="2026-11-18"),
        utc(2026, 11, 16, 0, 0),
        utc(2026, 11, 18, 7, 0),
        [utc(2026, 11, 16, 7, 0), utc(2026, 11, 17, 7, 0)],
        id="window-end-exclusive-on-last-occurrence",
    ),
    pytest.param(
        daily(["08:00"], start="2026-11-16", end="2026-11-18"),
        utc(2026, 11, 20, 0, 0),
        utc(2026, 11, 30, 0, 0),
        [],
        id="window-entirely-after-end",
    ),
    pytest.param(
        monthly_day(15, ["09:00"], end="2027-01-20"),
        utc(2026, 11, 1, 0, 0),
        utc(2027, 2, 1, 0, 0),
        [utc(2026, 11, 15, 8, 0), utc(2026, 12, 15, 8, 0), utc(2027, 1, 15, 8, 0)],
        id="monthly-day-end-only-window",
    ),
]


@pytest.mark.parametrize(("payload", "window_start", "window_end", "expected"), BETWEEN_WITH_END)
def test_occurrences_between_stops_at_end(
    payload: Payload, window_start: datetime, window_end: datetime, expected: list[datetime]
) -> None:
    rule = from_json(payload)

    assert occurrences_between(rule, AMS, window_start, window_end) == expected
