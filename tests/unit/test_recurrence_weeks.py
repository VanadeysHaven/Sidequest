"""Table-driven tests for weekly rules with `every` and `start` in sidequest.core.recurrence."""

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sidequest.core.errors import InvalidRule
from sidequest.core.recurrence import (
    RecurrenceRule,
    WeeklyRule,
    anchored,
    describe,
    from_json,
    next_occurrence,
    to_json,
)

AMS = ZoneInfo("Europe/Amsterdam")
UTC = ZoneInfo("UTC")

Payload = dict[str, Any]


def local(y: int, m: int, d: int, hh: int, mm: int, tz: ZoneInfo = AMS) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=tz)


def weekly(weekdays: list[str], times: list[str], **extra: Any) -> Payload:
    return {"type": "weekly", "weekdays": weekdays, "times": times, **extra}


def chain_occurrences(rule: RecurrenceRule, after: datetime, count: int) -> list[datetime]:
    result: list[datetime] = []
    at = after
    for _ in range(count):
        at = next_occurrence(rule, AMS, at)
        result.append(at)
    return result


NOW = local(2026, 11, 12, 13, 0)  # Thursday


# --- worked examples: stored start and first occurrences ---------------------------------

WORKED_EXAMPLES = [
    pytest.param(
        weekly(["mon"], ["07:00"], every=2),
        "2026-11-16",
        [local(2026, 11, 16, 7, 0), local(2026, 11, 30, 7, 0), local(2026, 12, 14, 7, 0)],
        id="mon-0700-every-2-anchors-to-next-monday",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["12:00"], every=2),
        "2026-11-16",
        [
            local(2026, 11, 16, 12, 0),
            local(2026, 11, 19, 12, 0),
            local(2026, 11, 30, 12, 0),
            local(2026, 12, 3, 12, 0),
        ],
        id="mon-thu-1200-every-2-anchors-to-next-monday",
    ),
    pytest.param(
        weekly(["tue"], ["07:00"], every=2, start="2026-11-03"),
        "2026-11-03",
        [local(2026, 11, 17, 7, 0), local(2026, 12, 1, 7, 0), local(2026, 12, 15, 7, 0)],
        id="tue-0700-every-2-explicit-start-in-past",
    ),
    pytest.param(
        weekly(["fri"], ["18:00"], every=3, start="2026-12-04"),
        "2026-12-04",
        [local(2026, 12, 4, 18, 0), local(2026, 12, 25, 18, 0), local(2027, 1, 15, 18, 0)],
        id="fri-1800-every-3-explicit-start",
    ),
    pytest.param(
        weekly(["sun", "mon"], ["10:00"], every=2),
        "2026-11-15",
        [
            local(2026, 11, 15, 10, 0),
            local(2026, 11, 23, 10, 0),
            local(2026, 11, 29, 10, 0),
            local(2026, 12, 7, 10, 0),
        ],
        id="sun-mon-1000-every-2-anchors-to-next-sunday",
    ),
    pytest.param(
        weekly(["mon"], ["07:00"], start="2026-11-26"),
        "2026-11-26",
        [local(2026, 11, 30, 7, 0), local(2026, 12, 7, 7, 0), local(2026, 12, 14, 7, 0)],
        id="mon-0700-every-1-explicit-start-skips-earlier-monday",
    ),
    pytest.param(
        weekly(["mon"], ["07:00"]),
        None,
        [local(2026, 11, 16, 7, 0), local(2026, 11, 23, 7, 0)],
        id="mon-0700-every-1-no-start-key",
    ),
]


@pytest.mark.parametrize(("payload", "expected_start", "expected"), WORKED_EXAMPLES)
def test_worked_example_stored_start_and_occurrences(
    payload: Payload, expected_start: str | None, expected: list[datetime]
) -> None:
    rule = anchored(from_json(payload), AMS, NOW)
    data = to_json(rule)
    if expected_start is None:
        assert "start" not in data
    else:
        assert data["start"] == expected_start
    assert chain_occurrences(rule, NOW, len(expected)) == expected


# --- occurrences after anchoring ---------------------------------------------------------

AFTER_ANCHORING = [
    pytest.param(
        weekly(["mon", "thu"], ["12:00"], every=2, start="2026-11-19"),
        [local(2026, 11, 19, 12, 0), local(2026, 11, 30, 12, 0), local(2026, 12, 3, 12, 0)],
        id="start-after-monday-skips-that-monday",
    ),
    pytest.param(
        weekly(["mon", "wed"], ["12:00"], start="2026-11-18"),
        [local(2026, 11, 18, 12, 0), local(2026, 11, 23, 12, 0), local(2026, 11, 25, 12, 0)],
        id="every-1-start-mid-week-skips-earlier-monday",
    ),
    pytest.param(
        weekly(["mon"], ["07:00"], every=2, start="2020-01-06"),
        [local(2026, 11, 16, 7, 0), local(2026, 11, 30, 7, 0), local(2026, 12, 14, 7, 0)],
        id="start-long-in-past-keeps-two-week-phase",
    ),
    pytest.param(
        weekly(["mon"], ["07:00"], every=52),
        [local(2026, 11, 16, 7, 0), local(2027, 11, 15, 7, 0), local(2028, 11, 13, 7, 0)],
        id="every-52-anchored-from-now",
    ),
]


@pytest.mark.parametrize(("payload", "expected"), AFTER_ANCHORING)
def test_occurrences_after_anchoring(payload: Payload, expected: list[datetime]) -> None:
    rule = anchored(from_json(payload), AMS, NOW)
    assert chain_occurrences(rule, NOW, len(expected)) == expected


# --- DST ---------------------------------------------------------------------------------


def test_occurrences_across_spring_dst_gap() -> None:
    rule = from_json(weekly(["sun"], ["02:30"], every=2, start="2027-03-14"))
    after = local(2027, 3, 14, 12, 0)

    first = next_occurrence(rule, AMS, after)

    # 2027-03-28 02:30 does not exist in Amsterdam; it resolves to 03:30 (+02:00 = 01:30 UTC).
    assert first == datetime(2027, 3, 28, 1, 30, tzinfo=UTC)
    assert first.utcoffset() == timedelta(0)
    assert chain_occurrences(rule, after, 3) == [
        datetime(2027, 3, 28, 1, 30, tzinfo=UTC),
        local(2027, 4, 11, 2, 30),
        local(2027, 4, 25, 2, 30),
    ]


# --- JSON round trip and validation ------------------------------------------------------


def test_round_trip_without_every_or_start() -> None:
    payload = weekly(["mon"], ["07:00"])

    assert to_json(from_json(payload)) == payload
    assert set(to_json(from_json(payload))) == {"type", "weekdays", "times"}


def test_round_trip_with_start_only() -> None:
    payload = weekly(["mon"], ["07:00"], start="2026-11-26")

    assert to_json(from_json(payload)) == payload
    assert set(to_json(from_json(payload))) == {"type", "weekdays", "times", "start"}


def test_round_trip_with_every_and_start() -> None:
    payload = weekly(["tue"], ["07:00"], every=2, start="2026-11-03")
    rule = from_json(payload)

    assert to_json(rule) == payload
    assert from_json(to_json(rule)) == rule


@pytest.mark.parametrize(
    "extras",
    [
        pytest.param({"every": 0}, id="every-0"),
        pytest.param({"every": 53}, id="every-53"),
        pytest.param({"every": True}, id="every-bool"),
        pytest.param({"every": "2"}, id="every-string"),
        pytest.param({"start": "12-11-2026"}, id="start-wrong-format"),
        pytest.param({"foo": 1}, id="unknown-key"),
    ],
)
def test_from_json_rejects_invalid_weekly_fields(extras: dict[str, Any]) -> None:
    with pytest.raises(InvalidRule):
        from_json(weekly(["mon"], ["07:00"], **extras))


# --- unanchored rules --------------------------------------------------------------------


def test_unanchored_rule_cannot_be_serialized_or_scheduled() -> None:
    rule = WeeklyRule(weekdays=["mon"], times=["07:00"], every=2)

    with pytest.raises(ValueError):
        to_json(rule)
    with pytest.raises(ValueError):
        next_occurrence(rule, AMS, NOW)


# --- anchored ----------------------------------------------------------------------------

UNCHANGED_BY_ANCHORED = [
    pytest.param({"type": "daily", "times": ["08:00"]}, id="daily"),
    pytest.param({"type": "monthly_day", "day": 15, "times": ["09:00"]}, id="monthly-day"),
    pytest.param(weekly(["mon"], ["07:00"]), id="weekly-every-1-no-start"),
    pytest.param(weekly(["tue"], ["07:00"], every=2, start="2026-11-03"), id="weekly-anchored"),
]


@pytest.mark.parametrize("payload", UNCHANGED_BY_ANCHORED)
def test_anchored_leaves_other_rules_unchanged(payload: Payload) -> None:
    rule = from_json(payload)

    assert anchored(rule, AMS, NOW) == rule


@pytest.mark.parametrize("every", [1, 2])
def test_anchored_accepts_start_366_days_ahead(every: int) -> None:
    start = NOW.date() + timedelta(days=366)
    rule = WeeklyRule(weekdays=["mon"], times=["07:00"], every=every, start=start)

    assert anchored(rule, AMS, NOW) == rule


@pytest.mark.parametrize("every", [1, 2])
def test_anchored_rejects_start_367_days_ahead(every: int) -> None:
    start: date = NOW.date() + timedelta(days=367)
    rule = WeeklyRule(weekdays=["mon"], times=["07:00"], every=every, start=start)

    with pytest.raises(InvalidRule):
        anchored(rule, AMS, NOW)


# --- describe ----------------------------------------------------------------------------

DESCRIBE_CASES = [
    pytest.param(
        weekly(["mon", "thu"], ["12:00"]),
        "Every Monday and Thursday at 12:00 (Europe/Amsterdam)",
        id="every-1-no-start",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["12:00"], start="2026-11-26"),
        "Every Monday and Thursday at 12:00 (Europe/Amsterdam)",
        id="every-1-with-start",
    ),
    pytest.param(
        weekly(["mon", "thu"], ["12:00"], every=2, start="2026-11-16"),
        "Every 2 weeks on Monday and Thursday at 12:00 (Europe/Amsterdam)",
        id="every-2",
    ),
    pytest.param(
        weekly(["fri"], ["18:00"], every=3, start="2026-12-04"),
        "Every 3 weeks on Friday at 18:00 (Europe/Amsterdam)",
        id="every-3-single-day",
    ),
]


@pytest.mark.parametrize(("payload", "expected"), DESCRIBE_CASES)
def test_describe_weekly(payload: Payload, expected: str) -> None:
    assert describe(from_json(payload), AMS) == expected
