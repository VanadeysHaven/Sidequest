"""Table-driven tests for suspensions (D81–D88) in sidequest.core.recurrence.

A suspension is an inclusive date range, in the rule's zone, on which nothing fires. Covers
skipped occurrences, edge days, touching vs overlapping ranges, sorting, pruning, JSON,
next/between occurrences, the series end, and the helpers that add, remove and inspect them.
"""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sidequest.core.errors import InvalidRule
from sidequest.core.recurrence import (
    END_BEFORE_START,
    DateRange,
    RecurrenceRule,
    anchored,
    from_json,
    next_occurrence,
    occurrences_between,
    pruned,
    suspended_until,
    to_json,
    with_suspension,
    without_suspension,
)

AMS = ZoneInfo("Europe/Amsterdam")
UTC = ZoneInfo("UTC")

Payload = dict[str, Any]
Pair = tuple[str, str]


def utc(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


def rng(start: str, end: str) -> DateRange:
    return DateRange(start=date.fromisoformat(start), end=date.fromisoformat(end))


def susp(*pairs: Pair) -> list[Payload]:
    return [{"start": s, "end": e} for s, e in pairs]


def pairs_of(rule: RecurrenceRule) -> list[Pair]:
    return [(r.start.isoformat(), r.end.isoformat()) for r in rule.suspended]


def daily(times: list[str], **extra: Any) -> Payload:
    return {"type": "daily", "times": times, **extra}


def weekly(weekdays: list[str], times: list[str], **extra: Any) -> Payload:
    return {"type": "weekly", "weekdays": weekdays, "times": times, **extra}


def monthly(week: int, weekday: str, times: list[str], **extra: Any) -> Payload:
    return {"type": "monthly", "week": week, "weekday": weekday, "times": times, **extra}


def monthly_day(day: int, times: list[str], **extra: Any) -> Payload:
    return {"type": "monthly_day", "day": day, "times": times, **extra}


# --- DateRange ---------------------------------------------------------------------------


OVERLAPS = [
    pytest.param(
        ("2026-11-16", "2026-11-18"),
        ("2026-11-19", "2026-11-22"),
        False,
        id="touching-ranges-do-not-overlap",
    ),
    pytest.param(
        ("2026-11-18", "2026-11-22"),
        ("2026-11-16", "2026-11-17"),
        False,
        id="touching-ranges-reversed",
    ),
    pytest.param(
        ("2026-11-16", "2026-11-18"), ("2026-11-18", "2026-11-20"), True, id="shared-day-overlaps"
    ),
    pytest.param(
        ("2026-11-16", "2026-11-22"), ("2026-11-18", "2026-11-19"), True, id="contained-overlaps"
    ),
    pytest.param(
        ("2026-11-16", "2026-11-18"), ("2026-11-16", "2026-11-18"), True, id="identical-overlaps"
    ),
    pytest.param(
        ("2026-11-16", "2026-11-16"), ("2026-11-18", "2026-11-18"), False, id="gap-does-not-overlap"
    ),
]


@pytest.mark.parametrize(("a", "b", "expected"), OVERLAPS)
def test_date_range_overlaps_is_symmetric(a: Pair, b: Pair, expected: bool) -> None:
    first, second = rng(*a), rng(*b)
    assert first.overlaps(second) is expected
    assert second.overlaps(first) is expected


CONTAINS = [
    pytest.param("2026-11-16", True, id="start-inclusive"),
    pytest.param("2026-11-18", True, id="end-inclusive"),
    pytest.param("2026-11-17", True, id="middle"),
    pytest.param("2026-11-15", False, id="day-before"),
    pytest.param("2026-11-19", False, id="day-after"),
]


@pytest.mark.parametrize(("day", "expected"), CONTAINS)
def test_date_range_contains(day: str, expected: bool) -> None:
    assert (date.fromisoformat(day) in rng("2026-11-16", "2026-11-18")) is expected


RANGE_ORDER = [
    pytest.param("2026-11-18", "2026-11-16", END_BEFORE_START, id="end-before-start"),
    pytest.param("2026-11-16", "2026-11-16", None, id="single-day-allowed"),
]


@pytest.mark.parametrize(("start", "end", "message"), RANGE_ORDER)
def test_date_range_end_must_not_be_before_start(start: str, end: str, message: str | None) -> None:
    if message is None:
        assert rng(start, end).start == date.fromisoformat(start)
        return
    with pytest.raises(InvalidRule) as exc:
        rng(start, end)
    assert exc.value.message == message


# --- model validation (every rule type) --------------------------------------------------

SUSPENSION_SETS = [
    pytest.param(
        susp(("2026-11-16", "2026-11-18"), ("2026-11-19", "2026-11-22")),
        None,
        id="touching-accepted",
    ),
    pytest.param(
        susp(("2026-11-16", "2026-11-18"), ("2026-11-18", "2026-11-20")),
        "suspensions overlap",
        id="shared-day-refused",
    ),
    pytest.param(
        susp(("2026-11-16", "2026-11-22"), ("2026-11-18", "2026-11-19")),
        "suspensions overlap",
        id="contained-refused",
    ),
    pytest.param(
        susp(("2026-11-16", "2026-11-18"), ("2026-11-16", "2026-11-18")),
        "suspensions overlap",
        id="identical-refused",
    ),
    pytest.param(
        susp(("2026-11-22", "2026-11-25"), ("2026-11-16", "2026-11-18")),
        None,
        id="unsorted-accepted",
    ),
]

RULE_TYPES = [
    pytest.param(daily(["08:00"]), id="daily"),
    pytest.param(weekly(["mon"], ["12:00"]), id="weekly"),
    pytest.param(monthly(1, "mon", ["12:00"]), id="monthly"),
    pytest.param(monthly_day(30, ["09:00"]), id="monthly_day"),
]


@pytest.mark.parametrize(("suspended", "message"), SUSPENSION_SETS)
def test_model_refuses_overlapping_suspensions(
    suspended: list[Payload], message: str | None
) -> None:
    payload = daily(["08:00"], suspended=suspended)
    if message is None:
        assert len(from_json(payload).suspended) == len(suspended)
        return
    with pytest.raises(InvalidRule) as exc:
        from_json(payload)
    assert message in exc.value.message


@pytest.mark.parametrize("base", RULE_TYPES)
def test_every_rule_type_refuses_overlap(base: Payload) -> None:
    payload = {
        **base,
        "suspended": susp(("2026-11-16", "2026-11-20"), ("2026-11-20", "2026-11-21")),
    }
    with pytest.raises(InvalidRule) as exc:
        from_json(payload)
    assert "suspensions overlap" in exc.value.message


SORTED = [
    pytest.param(
        susp(("2026-11-22", "2026-11-25"), ("2026-11-16", "2026-11-18")),
        [("2026-11-16", "2026-11-18"), ("2026-11-22", "2026-11-25")],
        id="two-out-of-order",
    ),
    pytest.param(
        susp(
            ("2026-12-01", "2026-12-01"), ("2026-11-19", "2026-11-19"), ("2026-11-16", "2026-11-17")
        ),
        [("2026-11-16", "2026-11-17"), ("2026-11-19", "2026-11-19"), ("2026-12-01", "2026-12-01")],
        id="three-reversed",
    ),
]


@pytest.mark.parametrize(("given", "expected"), SORTED)
def test_suspensions_are_sorted_by_start(given: list[Payload], expected: list[Pair]) -> None:
    assert pairs_of(from_json(daily(["08:00"], suspended=given))) == expected


# --- with_suspension ---------------------------------------------------------------------

ADD = [
    pytest.param(
        [], ("2026-11-16", "2026-11-18"), [("2026-11-16", "2026-11-18")], id="first-suspension"
    ),
    pytest.param(
        [("2026-11-16", "2026-11-18")],
        ("2026-11-19", "2026-11-22"),
        [("2026-11-16", "2026-11-18"), ("2026-11-19", "2026-11-22")],
        id="touching-after-accepted",
    ),
    pytest.param(
        [("2026-11-16", "2026-11-18")],
        ("2026-11-10", "2026-11-15"),
        [("2026-11-10", "2026-11-15"), ("2026-11-16", "2026-11-18")],
        id="touching-before-accepted-and-sorted",
    ),
    pytest.param(
        [("2026-11-16", "2026-11-22")],
        ("2026-11-20", "2026-11-25"),
        "That overlaps the suspension from 16-11-2026 to 22-11-2026. "
        "Cancel that one first, or pick other dates.",
        id="overlap-at-end-refused",
    ),
    pytest.param(
        [("2026-11-16", "2026-11-22")],
        ("2026-11-10", "2026-11-16"),
        "That overlaps the suspension from 16-11-2026 to 22-11-2026. "
        "Cancel that one first, or pick other dates.",
        id="overlap-at-start-refused",
    ),
    pytest.param(
        [("2026-11-16", "2026-11-22")],
        ("2026-11-18", "2026-11-19"),
        "That overlaps the suspension from 16-11-2026 to 22-11-2026. "
        "Cancel that one first, or pick other dates.",
        id="inside-existing-refused",
    ),
]


@pytest.mark.parametrize(("existing", "new", "expected"), ADD)
def test_with_suspension(existing: list[Pair], new: Pair, expected: list[Pair] | str) -> None:
    rule = from_json(daily(["08:00"], suspended=susp(*existing)))
    if isinstance(expected, str):
        with pytest.raises(InvalidRule) as exc:
            with_suspension(rule, rng(*new))
        assert exc.value.message == expected
        return
    assert pairs_of(with_suspension(rule, rng(*new))) == expected


# --- pruned ------------------------------------------------------------------------------

PRUNE = [
    pytest.param([("2026-11-10", "2026-11-15")], "2026-11-16", [], id="ended-yesterday-dropped"),
    pytest.param(
        [("2026-11-10", "2026-11-16")],
        "2026-11-16",
        [("2026-11-10", "2026-11-16")],
        id="ends-today-kept",
    ),
    pytest.param(
        [("2026-11-10", "2026-11-13"), ("2026-11-14", "2026-11-15"), ("2026-11-16", "2026-11-20")],
        "2026-11-16",
        [("2026-11-16", "2026-11-20")],
        id="mixed-keeps-only-current",
    ),
    pytest.param(
        [("2026-11-16", "2026-11-20")],
        "2026-11-16",
        [("2026-11-16", "2026-11-20")],
        id="nothing-finished",
    ),
    pytest.param([], "2026-11-16", [], id="none-at-all"),
]


@pytest.mark.parametrize(("existing", "today", "expected"), PRUNE)
def test_pruned_drops_finished_suspensions(
    existing: list[Pair], today: str, expected: list[Pair]
) -> None:
    rule = from_json(daily(["08:00"], suspended=susp(*existing)))
    assert pairs_of(pruned(rule, date.fromisoformat(today))) == expected


def test_pruned_returns_equal_rule_when_nothing_finished() -> None:
    rule = from_json(daily(["08:00"], suspended=susp(("2026-11-16", "2026-11-20"))))
    assert pruned(rule, date(2026, 11, 16)) == rule


# --- JSON --------------------------------------------------------------------------------

ROUND_TRIP = [
    pytest.param(
        daily(["08:00", "20:00"], suspended=susp(("2026-11-16", "2026-11-18"))),
        id="daily-with-suspension",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["12:00"], suspended=susp(("2026-11-16", "2026-11-22"))),
        id="weekly-with-suspension",
    ),
    pytest.param(
        monthly(1, "sun", ["12:00"], suspended=susp(("2026-12-06", "2026-12-06"))),
        id="monthly-with-suspension",
    ),
    pytest.param(
        monthly_day(
            -1,
            ["09:00"],
            suspended=susp(("2026-11-16", "2026-11-18"), ("2026-11-19", "2026-11-22")),
        ),
        id="monthly-day-touching-ranges",
    ),
    pytest.param(
        daily(
            ["08:00"],
            start="2026-11-16",
            end="2026-12-16",
            suspended=susp(("2026-11-20", "2026-11-21")),
        ),
        id="daily-with-start-end-and-suspension",
    ),
]


@pytest.mark.parametrize("payload", ROUND_TRIP)
def test_json_round_trip_keeps_suspensions(payload: Payload) -> None:
    assert to_json(from_json(payload)) == payload


NO_SUSPENSIONS = [
    pytest.param(daily(["08:00"]), id="daily"),
    pytest.param(weekly(["mon"], ["12:00"]), id="weekly"),
    pytest.param(monthly(2, "fri", ["18:00"]), id="monthly"),
    pytest.param(monthly_day(15, ["09:00"]), id="monthly_day"),
    pytest.param(daily(["08:00"], suspended=[]), id="empty-list-is-omitted"),
]


@pytest.mark.parametrize("payload", NO_SUSPENSIONS)
def test_json_omits_suspended_key_when_empty(payload: Payload) -> None:
    out = to_json(from_json(payload))
    assert "suspended" not in out
    assert from_json(out) == from_json(payload)


def test_json_drops_finished_suspension_on_anchor() -> None:
    # Finished ones are pruned by `anchored`, so the stored JSON has no "suspended" key.
    rule = from_json(daily(["08:00"], suspended=susp(("2026-11-01", "2026-11-05"))))
    out = to_json(anchored(rule, UTC, utc(2026, 11, 14, 12, 0)))
    assert "suspended" not in out


# --- next_occurrence ---------------------------------------------------------------------

NEXT_SKIPS = [
    pytest.param(
        daily(["08:00", "20:00"], suspended=susp(("2026-11-16", "2026-11-17"))),
        UTC,
        utc(2026, 11, 15, 21, 0),
        utc(2026, 11, 18, 8, 0),
        id="daily-two-times-skips-range",
    ),
    pytest.param(
        weekly(["mon"], ["12:00"], suspended=susp(("2026-11-16", "2026-11-17"))),
        UTC,
        utc(2026, 11, 15, 12, 0),
        utc(2026, 11, 23, 12, 0),
        id="weekly-skips-monday-in-range",
    ),
    pytest.param(
        monthly(1, "mon", ["12:00"], suspended=susp(("2026-11-02", "2026-11-02"))),
        UTC,
        utc(2026, 11, 1, 12, 0),
        utc(2026, 12, 7, 12, 0),
        id="monthly-skips-first-monday",
    ),
    pytest.param(
        monthly_day(30, ["09:00"], suspended=susp(("2026-11-30", "2026-11-30"))),
        AMS,
        utc(2026, 11, 29, 12, 0),
        utc(2026, 12, 30, 8, 0),
        id="monthly-day-skips-day-in-amsterdam",
    ),
    pytest.param(
        daily(["08:00"], suspended=susp(("2026-11-18", "2026-11-18"))),
        UTC,
        utc(2026, 11, 17, 12, 0),
        utc(2026, 11, 19, 8, 0),
        id="suspension-is-exact-occurrence-day",
    ),
    pytest.param(
        daily(["08:00"], suspended=susp(("2026-11-18", "2026-11-20"))),
        UTC,
        utc(2026, 11, 17, 12, 0),
        utc(2026, 11, 21, 8, 0),
        id="suspension-starts-on-occurrence-day",
    ),
    pytest.param(
        daily(["08:00"], suspended=susp(("2026-11-16", "2026-11-18"))),
        UTC,
        utc(2026, 11, 15, 12, 0),
        utc(2026, 11, 19, 8, 0),
        id="suspension-ends-on-occurrence-day",
    ),
    pytest.param(
        daily(["08:00"], suspended=susp(("2026-11-17", "2026-11-17"))),
        UTC,
        utc(2026, 11, 16, 12, 0),
        utc(2026, 11, 18, 8, 0),
        id="day-before-range-not-skipped-after-it",
    ),
    pytest.param(
        daily(["08:00"], suspended=susp(("2026-11-16", "2026-11-16"))),
        AMS,
        utc(2026, 11, 15, 23, 30),
        utc(2026, 11, 17, 7, 0),
        id="amsterdam-local-date-skipped",
    ),
    pytest.param(
        daily(["08:00"], suspended=susp(("2026-11-16", "2026-11-18"))),
        AMS,
        utc(2026, 11, 17, 12, 0),
        utc(2026, 11, 19, 7, 0),
        id="amsterdam-range-ends-local-day",
    ),
]


@pytest.mark.parametrize(("payload", "tz", "after", "expected"), NEXT_SKIPS)
def test_next_occurrence_skips_suspended_days(
    payload: Payload, tz: ZoneInfo, after: datetime, expected: datetime
) -> None:
    assert next_occurrence(from_json(payload), tz, after) == expected


NEXT_NONE = [
    pytest.param(
        daily(["08:00"], end="2026-11-18", suspended=susp(("2026-11-16", "2026-11-18"))),
        id="daily-end-covered-by-suspension",
    ),
    pytest.param(
        weekly(["mon"], ["12:00"], end="2026-11-23", suspended=susp(("2026-11-16", "2026-11-23"))),
        id="weekly-both-mondays-suspended",
    ),
]


@pytest.mark.parametrize("payload", NEXT_NONE)
def test_next_occurrence_none_when_suspension_covers_rest_of_series(payload: Payload) -> None:
    assert next_occurrence(from_json(payload), UTC, utc(2026, 11, 15, 12, 0)) is None


def test_next_occurrence_before_end_when_suspension_stops_short() -> None:
    payload = daily(["08:00"], end="2026-11-18", suspended=susp(("2026-11-16", "2026-11-17")))
    assert next_occurrence(from_json(payload), UTC, utc(2026, 11, 15, 12, 0)) == utc(
        2026, 11, 18, 8, 0
    )


# --- occurrences_between -----------------------------------------------------------------

BETWEEN = [
    pytest.param(
        daily(["08:00", "20:00"], suspended=susp(("2026-11-17", "2026-11-18"))),
        UTC,
        utc(2026, 11, 16, 0, 0),
        utc(2026, 11, 20, 0, 0),
        [
            utc(2026, 11, 16, 8, 0),
            utc(2026, 11, 16, 20, 0),
            utc(2026, 11, 19, 8, 0),
            utc(2026, 11, 19, 20, 0),
        ],
        id="daily-two-times-with-gap",
    ),
    pytest.param(
        weekly(["mon"], ["12:00"], suspended=susp(("2026-11-16", "2026-11-16"))),
        UTC,
        utc(2026, 11, 16, 0, 0),
        utc(2026, 12, 1, 0, 0),
        [utc(2026, 11, 23, 12, 0), utc(2026, 11, 30, 12, 0)],
        id="weekly-first-monday-suspended",
    ),
    pytest.param(
        daily(["08:00"], suspended=susp(("2026-11-17", "2026-11-17"))),
        AMS,
        utc(2026, 11, 16, 0, 0),
        utc(2026, 11, 18, 0, 0),
        [utc(2026, 11, 16, 7, 0)],
        id="amsterdam-window-with-suspended-day",
    ),
]


@pytest.mark.parametrize(("payload", "tz", "start", "end", "expected"), BETWEEN)
def test_occurrences_between_skips_suspended_days(
    payload: Payload, tz: ZoneInfo, start: datetime, end: datetime, expected: list[datetime]
) -> None:
    assert occurrences_between(from_json(payload), tz, start, end) == expected


# --- without_suspension ------------------------------------------------------------------

WITHOUT = [
    pytest.param(
        [("2026-11-16", "2026-11-18"), ("2026-11-20", "2026-11-22")],
        "2026-11-16",
        [("2026-11-20", "2026-11-22")],
        ("2026-11-16", "2026-11-18"),
        id="removes-first",
    ),
    pytest.param(
        [("2026-11-16", "2026-11-18"), ("2026-11-20", "2026-11-22")],
        "2026-11-20",
        [("2026-11-16", "2026-11-18")],
        ("2026-11-20", "2026-11-22"),
        id="removes-second",
    ),
    pytest.param(
        [("2026-11-16", "2026-11-18"), ("2026-11-20", "2026-11-22")],
        "2026-11-17",
        [("2026-11-16", "2026-11-18"), ("2026-11-20", "2026-11-22")],
        None,
        id="inside-range-not-a-start",
    ),
    pytest.param(
        [("2026-11-16", "2026-11-18")],
        "2026-11-19",
        [("2026-11-16", "2026-11-18")],
        None,
        id="no-suspension-starts-there",
    ),
    pytest.param([], "2026-11-16", [], None, id="no-suspensions"),
]


@pytest.mark.parametrize(("existing", "start", "remaining", "removed"), WITHOUT)
def test_without_suspension(
    existing: list[Pair], start: str, remaining: list[Pair], removed: Pair | None
) -> None:
    rule = from_json(daily(["08:00"], suspended=susp(*existing)))
    new_rule, found = without_suspension(rule, date.fromisoformat(start))
    assert pairs_of(new_rule) == remaining
    if removed is None:
        assert found is None
        assert new_rule == rule
    else:
        assert found is not None
        assert (found.start.isoformat(), found.end.isoformat()) == removed


# --- suspended_until ---------------------------------------------------------------------

# Touching ranges count as one run: [16–18] and [19–22] run 16–22. [25–26] is separate.
CHAIN = [("2026-11-16", "2026-11-18"), ("2026-11-19", "2026-11-22"), ("2026-11-25", "2026-11-26")]

UNTIL = [
    pytest.param("2026-11-15", None, id="day-before-first-run"),
    pytest.param("2026-11-16", "2026-11-22", id="first-day-follows-touching-chain"),
    pytest.param("2026-11-17", "2026-11-22", id="inside-first-range"),
    pytest.param("2026-11-19", "2026-11-22", id="start-of-touching-range"),
    pytest.param("2026-11-22", "2026-11-22", id="last-day-of-chain"),
    pytest.param("2026-11-23", None, id="gap-between-runs"),
    pytest.param("2026-11-24", None, id="gap-day-two"),
    pytest.param("2026-11-25", "2026-11-26", id="second-run-start"),
    pytest.param("2026-11-26", "2026-11-26", id="second-run-end-is-today"),
    pytest.param("2026-11-27", None, id="after-everything"),
]


@pytest.mark.parametrize(("today", "expected"), UNTIL)
def test_suspended_until(today: str, expected: str | None) -> None:
    rule = from_json(daily(["08:00"], suspended=susp(*CHAIN)))
    got = suspended_until(rule, date.fromisoformat(today))
    assert (got.isoformat() if got else None) == expected


def test_suspended_until_none_without_suspensions() -> None:
    assert suspended_until(from_json(daily(["08:00"])), date(2026, 11, 16)) is None


# --- anchored ----------------------------------------------------------------------------

# "Today" in Amsterdam for this clock is 14-11-2026.
ANCHOR_NOW = utc(2026, 11, 14, 12, 0)

ANCHORED = [
    pytest.param([("2026-11-10", "2026-11-13")], [], id="finished-dropped"),
    pytest.param(
        [("2026-11-10", "2026-11-13"), ("2026-11-14", "2026-11-20")],
        [("2026-11-14", "2026-11-20")],
        id="finished-dropped-current-kept",
    ),
    pytest.param(
        [("2026-11-10", "2026-11-14")], [("2026-11-10", "2026-11-14")], id="ends-today-kept"
    ),
    pytest.param([("2026-11-16", "2026-11-20")], [("2026-11-16", "2026-11-20")], id="future-kept"),
]


@pytest.mark.parametrize(("existing", "expected"), ANCHORED)
def test_anchored_drops_finished_suspensions(existing: list[Pair], expected: list[Pair]) -> None:
    rule = anchored(from_json(daily(["08:00"], suspended=susp(*existing))), AMS, ANCHOR_NOW)
    assert pairs_of(rule) == expected
