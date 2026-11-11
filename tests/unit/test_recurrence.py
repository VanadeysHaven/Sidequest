"""Table-driven tests for sidequest.core.recurrence."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sidequest.core.errors import InvalidRule
from sidequest.core.recurrence import (
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
NEW_YORK = ZoneInfo("America/New_York")

Payload = dict[str, Any]


def local(y: int, m: int, d: int, hh: int, mm: int, tz: ZoneInfo = AMS) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=tz)


DAILY_TWO_TIMES: Payload = {"type": "daily", "times": ["08:00", "20:00"]}
WEEKLY_MON_THU: Payload = {"type": "weekly", "weekdays": ["mon", "thu"], "times": ["12:00"]}
MONTHLY_FIRST_SUN: Payload = {"type": "monthly", "week": 1, "weekday": "sun", "times": ["12:00"]}
MONTHLY_LAST_SUN: Payload = {"type": "monthly", "week": -1, "weekday": "sun", "times": ["12:00"]}
MONTHLY_DAY_31: Payload = {"type": "monthly_day", "day": 31, "times": ["09:00"]}
MONTHLY_DAY_LAST: Payload = {"type": "monthly_day", "day": -1, "times": ["09:00"]}


# --- next_occurrence ---------------------------------------------------------------------

NEXT_OCCURRENCE_CASES = [
    pytest.param(
        DAILY_TWO_TIMES,
        local(2026, 11, 11, 8, 0),
        local(2026, 11, 11, 20, 0),
        id="daily-after-exact-time-gives-next-time-same-day",
    ),
    pytest.param(
        DAILY_TWO_TIMES,
        local(2026, 11, 11, 21, 0),
        local(2026, 11, 12, 8, 0),
        id="daily-after-last-time-rolls-to-next-day",
    ),
    pytest.param(
        WEEKLY_MON_THU,
        local(2026, 11, 13, 9, 0),
        local(2026, 11, 16, 12, 0),
        id="weekly-from-friday-to-monday",
    ),
    pytest.param(
        WEEKLY_MON_THU,
        local(2026, 11, 16, 11, 59),
        local(2026, 11, 16, 12, 0),
        id="weekly-from-monday-before-time-same-day",
    ),
    pytest.param(
        MONTHLY_FIRST_SUN,
        local(2026, 1, 15, 12, 0),
        local(2026, 2, 1, 12, 0),
        id="monthly-first-sunday-feb-2026-starts-on-sunday",
    ),
    pytest.param(
        MONTHLY_FIRST_SUN,
        local(2026, 3, 2, 0, 0),
        local(2026, 4, 5, 12, 0),
        id="monthly-first-sunday-april-2026",
    ),
    pytest.param(
        MONTHLY_LAST_SUN,
        local(2028, 1, 31, 12, 0),
        local(2028, 2, 27, 12, 0),
        id="monthly-last-sunday-feb-2028-leap-year",
    ),
    pytest.param(
        MONTHLY_LAST_SUN,
        local(2027, 2, 1, 0, 0),
        local(2027, 2, 28, 12, 0),
        id="monthly-last-sunday-feb-2027",
    ),
    pytest.param(
        {"type": "monthly", "week": 4, "weekday": "fri", "times": ["12:00"]},
        local(2027, 1, 1, 0, 0),
        local(2027, 1, 22, 12, 0),
        id="monthly-fourth-friday-jan-2027-with-five-fridays",
    ),
    pytest.param(
        {"type": "monthly", "week": -1, "weekday": "fri", "times": ["12:00"]},
        local(2027, 1, 1, 0, 0),
        local(2027, 1, 29, 12, 0),
        id="monthly-last-friday-jan-2027-with-five-fridays",
    ),
    pytest.param(
        {"type": "monthly_day", "day": 15, "times": ["09:00"]},
        local(2026, 11, 15, 9, 0),
        local(2026, 12, 15, 9, 0),
        id="monthly-day-15-after-exact-time-gives-next-month",
    ),
    pytest.param(
        MONTHLY_DAY_31,
        local(2027, 1, 1, 0, 0),
        local(2027, 1, 31, 9, 0),
        id="monthly-day-31-from-new-year",
    ),
    pytest.param(
        MONTHLY_DAY_31,
        local(2028, 2, 1, 0, 0),
        local(2028, 2, 29, 9, 0),
        id="monthly-day-31-feb-2028-falls-back-to-29",
    ),
    pytest.param(
        {"type": "monthly_day", "day": 30, "times": ["09:00"]},
        local(2027, 2, 1, 0, 0),
        local(2027, 2, 28, 9, 0),
        id="monthly-day-30-in-february-2027-falls-back-to-28",
    ),
    pytest.param(
        {"type": "daily", "times": ["02:30"]},
        datetime(2026, 3, 28, 12, 0, tzinfo=UTC),
        datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
        id="dst-spring-gap-02:30-becomes-03:30",
    ),
    pytest.param(
        {"type": "daily", "times": ["02:30"]},
        datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
        datetime(2026, 3, 30, 0, 30, tzinfo=UTC),
        id="dst-spring-following-day-back-to-02:30",
    ),
    pytest.param(
        {"type": "daily", "times": ["02:30"]},
        datetime(2026, 10, 24, 12, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
        id="dst-fall-repeated-02:30-first-instance",
    ),
    pytest.param(
        {"type": "daily", "times": ["02:30"]},
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
        datetime(2026, 10, 26, 1, 30, tzinfo=UTC),
        id="dst-fall-repeated-02:30-fires-once-on-that-day",
    ),
    pytest.param(
        {"type": "daily", "times": ["12:00"]},
        datetime(2026, 3, 28, 12, 0, tzinfo=UTC),
        datetime(2026, 3, 29, 10, 0, tzinfo=UTC),
        id="dst-spring-noon-local-is-10-utc-after-switch",
    ),
    pytest.param(
        {"type": "daily", "times": ["12:00"]},
        datetime(2026, 10, 24, 12, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 11, 0, tzinfo=UTC),
        id="dst-fall-noon-local-is-11-utc-after-switch",
    ),
]


@pytest.mark.parametrize(("payload", "after", "expected"), NEXT_OCCURRENCE_CASES)
def test_next_occurrence(payload: Payload, after: datetime, expected: datetime) -> None:
    assert next_occurrence(from_json(payload), AMS, after) == expected


def test_next_occurrence_is_aware_utc() -> None:
    rule = from_json(DAILY_TWO_TIMES)
    result = next_occurrence(rule, AMS, local(2026, 11, 11, 8, 0))
    assert result.utcoffset() == timedelta(0)


def test_next_occurrence_new_york_spring_gap() -> None:
    rule = from_json({"type": "daily", "times": ["02:30"]})
    after = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    assert next_occurrence(rule, NEW_YORK, after) == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)


# --- occurrences_between -----------------------------------------------------------------

OCCURRENCES_BETWEEN_CASES = [
    pytest.param(
        MONTHLY_DAY_31,
        AMS,
        local(2027, 1, 1, 0, 0),
        local(2027, 5, 1, 0, 0),
        [
            local(2027, 1, 31, 9, 0),
            local(2027, 2, 28, 9, 0),
            local(2027, 3, 31, 9, 0),
            local(2027, 4, 30, 9, 0),
        ],
        id="monthly-day-31-consecutive-jan-to-apr-2027",
    ),
    pytest.param(
        MONTHLY_DAY_LAST,
        AMS,
        local(2027, 1, 1, 0, 0),
        local(2027, 5, 1, 0, 0),
        [
            local(2027, 1, 31, 9, 0),
            local(2027, 2, 28, 9, 0),
            local(2027, 3, 31, 9, 0),
            local(2027, 4, 30, 9, 0),
        ],
        id="monthly-day-last-consecutive-jan-to-apr-2027",
    ),
    pytest.param(
        {"type": "monthly_day", "day": 30, "times": ["09:00"]},
        AMS,
        local(2027, 2, 1, 0, 0),
        local(2027, 3, 1, 0, 0),
        [local(2027, 2, 28, 9, 0)],
        id="monthly-day-30-february-2027",
    ),
    pytest.param(
        MONTHLY_DAY_31,
        AMS,
        local(2028, 2, 1, 0, 0),
        local(2028, 3, 1, 0, 0),
        [local(2028, 2, 29, 9, 0)],
        id="monthly-day-31-february-2028-leap-year",
    ),
    pytest.param(
        DAILY_TWO_TIMES,
        AMS,
        local(2026, 11, 11, 8, 0),
        local(2026, 11, 11, 20, 0),
        [local(2026, 11, 11, 8, 0)],
        id="range-start-inclusive-end-exclusive",
    ),
    pytest.param(
        {"type": "daily", "times": ["12:00"]},
        AMS,
        local(2026, 3, 26, 0, 0),
        local(2026, 4, 2, 0, 0),
        [
            datetime(2026, 3, 26, 11, 0, tzinfo=UTC),
            datetime(2026, 3, 27, 11, 0, tzinfo=UTC),
            datetime(2026, 3, 28, 11, 0, tzinfo=UTC),
            datetime(2026, 3, 29, 10, 0, tzinfo=UTC),
            datetime(2026, 3, 30, 10, 0, tzinfo=UTC),
            datetime(2026, 3, 31, 10, 0, tzinfo=UTC),
            datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        ],
        id="dst-spring-week-daily-noon-stays-local-noon",
    ),
    pytest.param(
        {"type": "daily", "times": ["12:00"]},
        AMS,
        local(2026, 10, 22, 0, 0),
        local(2026, 10, 29, 0, 0),
        [
            datetime(2026, 10, 22, 10, 0, tzinfo=UTC),
            datetime(2026, 10, 23, 10, 0, tzinfo=UTC),
            datetime(2026, 10, 24, 10, 0, tzinfo=UTC),
            datetime(2026, 10, 25, 11, 0, tzinfo=UTC),
            datetime(2026, 10, 26, 11, 0, tzinfo=UTC),
            datetime(2026, 10, 27, 11, 0, tzinfo=UTC),
            datetime(2026, 10, 28, 11, 0, tzinfo=UTC),
        ],
        id="dst-fall-week-daily-noon-stays-local-noon",
    ),
]


@pytest.mark.parametrize(("payload", "tz", "start", "end", "expected"), OCCURRENCES_BETWEEN_CASES)
def test_occurrences_between(
    payload: Payload,
    tz: ZoneInfo,
    start: datetime,
    end: datetime,
    expected: list[datetime],
) -> None:
    assert occurrences_between(from_json(payload), tz, start, end) == expected


def test_monthly_day_31_fires_exactly_once_per_month_over_two_years() -> None:
    rule = from_json(MONTHLY_DAY_31)
    found = occurrences_between(rule, AMS, local(2027, 1, 1, 0, 0), local(2029, 1, 1, 0, 0))
    months = [(at.astimezone(AMS).year, at.astimezone(AMS).month) for at in found]
    assert len(found) == 24
    assert months == [(y, m) for y in (2027, 2028) for m in range(1, 13)]


# --- describe ----------------------------------------------------------------------------

DESCRIBE_CASES = [
    pytest.param(
        DAILY_TWO_TIMES,
        AMS,
        "Every day at 08:00 and 20:00 (Europe/Amsterdam)",
        id="daily-two-times",
    ),
    pytest.param(
        {"type": "daily", "times": ["08:00", "12:00", "20:00"]},
        AMS,
        "Every day at 08:00, 12:00 and 20:00 (Europe/Amsterdam)",
        id="daily-three-times",
    ),
    pytest.param(
        WEEKLY_MON_THU,
        AMS,
        "Every Monday and Thursday at 12:00 (Europe/Amsterdam)",
        id="weekly-mon-thu",
    ),
    pytest.param(
        MONTHLY_LAST_SUN,
        UTC,
        "Every last Sunday of the month at 12:00 (UTC)",
        id="monthly-last-sunday-utc",
    ),
    pytest.param(
        {"type": "monthly_day", "day": 15, "times": ["09:00"]},
        UTC,
        "Every month on the 15th at 09:00 (UTC)",
        id="monthly-day-15-utc",
    ),
    pytest.param(
        MONTHLY_DAY_LAST,
        UTC,
        "Every month on the last day at 09:00 (UTC)",
        id="monthly-day-last-utc",
    ),
    pytest.param(
        MONTHLY_DAY_31,
        UTC,
        "Every month on the 31st (or the last day of shorter months) at 09:00 (UTC)",
        id="monthly-day-31-utc",
    ),
]


@pytest.mark.parametrize(("payload", "tz", "expected"), DESCRIBE_CASES)
def test_describe(payload: Payload, tz: ZoneInfo, expected: str) -> None:
    assert describe(from_json(payload), tz) == expected


# --- JSON round-trip ---------------------------------------------------------------------

CANONICAL_PAYLOADS = [
    pytest.param(
        {"type": "daily", "times": ["08:00", "20:00"]},
        id="daily",
    ),
    pytest.param(
        {"type": "weekly", "weekdays": ["mon", "thu"], "times": ["12:00"]},
        id="weekly",
    ),
    pytest.param(
        {"type": "monthly", "week": 1, "weekday": "sun", "times": ["12:00"]},
        id="monthly-first-sunday",
    ),
    pytest.param(
        {"type": "monthly", "week": -1, "weekday": "fri", "times": ["09:00", "18:00"]},
        id="monthly-last-friday",
    ),
    pytest.param(
        {"type": "monthly_day", "day": 15, "times": ["09:00"]},
        id="monthly-day-15",
    ),
    pytest.param(
        {"type": "monthly_day", "day": -1, "times": ["23:59"]},
        id="monthly-day-last",
    ),
]


@pytest.mark.parametrize("payload", CANONICAL_PAYLOADS)
def test_to_json_of_from_json_returns_payload(payload: Payload) -> None:
    assert to_json(from_json(payload)) == payload


@pytest.mark.parametrize("payload", CANONICAL_PAYLOADS)
def test_from_json_of_to_json_returns_equal_rule(payload: Payload) -> None:
    rule = from_json(payload)
    assert from_json(to_json(rule)) == rule


NORMALISED_PAYLOADS = [
    pytest.param(
        {"type": "daily", "times": ["20:00", "08:00", "20:00"]},
        {"type": "daily", "times": ["08:00", "20:00"]},
        id="daily-unsorted-duplicate-times",
    ),
    pytest.param(
        {"type": "weekly", "weekdays": ["thu", "mon", "thu"], "times": ["20:00", "08:00"]},
        {"type": "weekly", "weekdays": ["mon", "thu"], "times": ["08:00", "20:00"]},
        id="weekly-unsorted-duplicate-weekdays-and-times",
    ),
    pytest.param(
        {"type": "monthly", "week": 2, "weekday": "wed", "times": ["18:00", "09:00", "18:00"]},
        {"type": "monthly", "week": 2, "weekday": "wed", "times": ["09:00", "18:00"]},
        id="monthly-unsorted-duplicate-times",
    ),
    pytest.param(
        {"type": "monthly_day", "day": 1, "times": ["12:00", "06:00"]},
        {"type": "monthly_day", "day": 1, "times": ["06:00", "12:00"]},
        id="monthly-day-unsorted-times",
    ),
]


@pytest.mark.parametrize(("payload", "expected"), NORMALISED_PAYLOADS)
def test_from_json_sorts_and_deduplicates(payload: Payload, expected: Payload) -> None:
    assert to_json(from_json(payload)) == expected


# --- invalid payloads --------------------------------------------------------------------

INVALID_PAYLOADS = [
    pytest.param(
        {"type": "monthly", "week": 5, "weekday": "sun", "times": ["12:00"]},
        id="week-5",
    ),
    pytest.param(
        {"type": "monthly_day", "day": 0, "times": ["09:00"]},
        id="day-0",
    ),
    pytest.param(
        {"type": "monthly_day", "day": 32, "times": ["09:00"]},
        id="day-32",
    ),
    pytest.param(
        {"type": "daily", "times": []},
        id="empty-times",
    ),
    pytest.param(
        {"type": "daily", "times": [f"{h:02d}:00" for h in range(13)]},
        id="thirteen-times",
    ),
    pytest.param(
        {"type": "weekly", "weekdays": ["xyz"], "times": ["12:00"]},
        id="unknown-weekday",
    ),
    pytest.param(
        {"type": "yearly", "times": ["12:00"]},
        id="unknown-type",
    ),
    pytest.param(
        {"times": ["12:00"]},
        id="missing-type",
    ),
    pytest.param(
        {"type": "daily", "times": ["08:00"], "extra": 1},
        id="extra-key",
    ),
    pytest.param(
        {"type": "daily", "times": ["25:00"]},
        id="time-25:00",
    ),
    pytest.param(
        {"type": "monthly_day", "day": True, "times": ["09:00"]},
        id="day-bool",
    ),
]


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
def test_from_json_rejects_invalid_payload(payload: Payload) -> None:
    with pytest.raises(InvalidRule):
        from_json(payload)


# --- direct construction -----------------------------------------------------------------

INVALID_CONSTRUCTIONS = [
    pytest.param(lambda: DailyRule(times=[]), id="daily-empty-times"),
    pytest.param(lambda: DailyRule(times=["25:00"]), id="daily-time-25:00"),
    pytest.param(
        lambda: WeeklyRule(weekdays=[], times=["12:00"]),
        id="weekly-no-weekdays",
    ),
    pytest.param(
        lambda: WeeklyRule(weekdays=["xyz"], times=["12:00"]),
        id="weekly-unknown-weekday",
    ),
    pytest.param(
        lambda: MonthlyRule(week=5, weekday="sun", times=["12:00"]),
        id="monthly-week-5",
    ),
    pytest.param(
        lambda: MonthlyRule(week=1, weekday="xyz", times=["12:00"]),
        id="monthly-unknown-weekday",
    ),
    pytest.param(
        lambda: MonthlyDayRule(day=0, times=["09:00"]),
        id="monthly-day-0",
    ),
    pytest.param(
        lambda: MonthlyDayRule(day=32, times=["09:00"]),
        id="monthly-day-32",
    ),
]


@pytest.mark.parametrize("build", INVALID_CONSTRUCTIONS)
def test_direct_construction_rejects_invalid_data(build: Callable[[], object]) -> None:
    with pytest.raises(InvalidRule):
        build()
