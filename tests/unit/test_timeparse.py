"""Table-driven tests for `sidequest.core.timeparse`."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from sidequest.core.enums import Weekday
from sidequest.core.errors import InPast, InvalidDate, InvalidRule, InvalidTime
from sidequest.core.timeparse import (
    Timed,
    Untimed,
    parse_date,
    parse_month_day,
    parse_time,
    parse_times,
    parse_weekdays,
    resolve_due,
    resolve_local,
)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
NEW_YORK = ZoneInfo("America/New_York")
TODAY = date(2026, 11, 1)

# --- parse_time ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("9:05", time(9, 5), id="single-digit-hour"),
        pytest.param("09:05", time(9, 5), id="two-digit-hour"),
        pytest.param("09.05", time(9, 5), id="dot-separator"),
        pytest.param("23:59", time(23, 59), id="last-minute-of-day"),
        pytest.param("00:00", time(0, 0), id="midnight"),
    ],
)
def test_parse_time_accepts(text: str, expected: time) -> None:
    assert parse_time(text) == expected


@pytest.mark.parametrize(
    ("text", "hint"),
    [
        pytest.param("24:00", None, id="hour-24"),
        pytest.param("9:5", None, id="one-digit-minute"),
        pytest.param("9pm", "24-hour", id="pm-suffix"),
        pytest.param("9:00 AM", "24-hour", id="am-suffix-with-space"),
        pytest.param("", None, id="empty"),
    ],
)
def test_parse_time_rejects(text: str, hint: str | None) -> None:
    with pytest.raises(InvalidTime) as exc_info:
        parse_time(text)
    if hint is not None:
        assert hint in exc_info.value.message


# --- parse_times ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("20:00, 08:00 8:00", [time(8, 0), time(20, 0)], id="dedup-and-sort"),
        pytest.param("12:00", [time(12, 0)], id="single"),
        pytest.param("09.30,10:00", [time(9, 30), time(10, 0)], id="mixed-separators"),
        pytest.param(
            ",".join(f"{h:02d}:00" for h in range(12)),
            [time(h, 0) for h in range(12)],
            id="twelve-allowed",
        ),
    ],
)
def test_parse_times_accepts(text: str, expected: list[time]) -> None:
    assert parse_times(text) == expected


@pytest.mark.parametrize(
    ("text", "hint"),
    [
        pytest.param("", None, id="empty"),
        pytest.param(
            ",".join(f"{h:02d}:00" for h in range(13)),
            "At most 12",
            id="thirteen-distinct-rejected",
        ),
        pytest.param("9pm, 10:00", "24-hour", id="pm-suffix-in-list"),
    ],
)
def test_parse_times_rejects(text: str, hint: str | None) -> None:
    with pytest.raises(InvalidTime) as exc_info:
        parse_times(text)
    if hint is not None:
        assert hint in exc_info.value.message


# --- parse_date ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("2026-11-12", date(2026, 11, 12), id="iso"),
        pytest.param("12-11-2026", date(2026, 11, 12), id="dmy-dash"),
        pytest.param("12/11/2026", date(2026, 11, 12), id="dmy-slash"),
        pytest.param("12.11.2026", date(2026, 11, 12), id="dmy-dot"),
        pytest.param("today", TODAY, id="today"),
        pytest.param("Today", TODAY, id="today-capitalised"),
        pytest.param("tomorrow", date(2026, 11, 2), id="tomorrow"),
    ],
)
def test_parse_date_accepts(text: str, expected: date) -> None:
    assert parse_date(text, TODAY) == expected


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("31-02-2026", id="nonexistent-day"),
        pytest.param("12-11-26", id="two-digit-year"),
        pytest.param("vandaag", id="dutch-today"),
        pytest.param("morgen", id="dutch-tomorrow"),
    ],
)
def test_parse_date_rejects(text: str) -> None:
    with pytest.raises(InvalidDate):
        parse_date(text, TODAY)


# --- parse_weekdays ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("mon,thu", [Weekday.MON, Weekday.THU], id="short-names"),
        pytest.param("Monday Thursday", [Weekday.MON, Weekday.THU], id="full-names"),
        pytest.param(
            "weekdays",
            [Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.FRI],
            id="weekdays-keyword",
        ),
        pytest.param("weekend", [Weekday.SAT, Weekday.SUN], id="weekend-keyword"),
        pytest.param("thu, mon, mon", [Weekday.MON, Weekday.THU], id="dedup-and-monday-first"),
    ],
)
def test_parse_weekdays_accepts(text: str, expected: list[Weekday]) -> None:
    assert parse_weekdays(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("funday", id="unknown-day"),
        pytest.param("", id="empty"),
    ],
)
def test_parse_weekdays_rejects(text: str) -> None:
    with pytest.raises(InvalidRule):
        parse_weekdays(text)


# --- parse_month_day -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("15", 15, id="plain"),
        pytest.param("15th", 15, id="ordinal-th"),
        pytest.param("1st", 1, id="ordinal-st"),
        pytest.param("31", 31, id="last-possible-day"),
        pytest.param("last", -1, id="last-day-of-month"),
    ],
)
def test_parse_month_day_accepts(text: str, expected: int) -> None:
    assert parse_month_day(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("0", id="zero"),
        pytest.param("32", id="above-31"),
        pytest.param("fifteenth", id="spelled-out"),
    ],
)
def test_parse_month_day_rejects(text: str) -> None:
    with pytest.raises(InvalidRule):
        parse_month_day(text)


# --- resolve_local -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("d", "t", "tz", "expected_utc"),
    [
        pytest.param(
            date(2026, 3, 29),
            time(2, 30),
            AMSTERDAM,
            datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
            id="ams-spring-gap-shifts-forward",
        ),
        pytest.param(
            date(2026, 10, 25),
            time(2, 30),
            AMSTERDAM,
            datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
            id="ams-fall-overlap-first-instance",
        ),
        pytest.param(
            date(2026, 3, 28),
            time(12, 0),
            AMSTERDAM,
            datetime(2026, 3, 28, 11, 0, tzinfo=UTC),
            id="ams-before-spring-transition",
        ),
        pytest.param(
            date(2026, 3, 30),
            time(12, 0),
            AMSTERDAM,
            datetime(2026, 3, 30, 10, 0, tzinfo=UTC),
            id="ams-after-spring-transition",
        ),
        pytest.param(
            date(2026, 3, 8),
            time(2, 30),
            NEW_YORK,
            datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
            id="ny-spring-gap-shifts-forward",
        ),
        pytest.param(
            date(2026, 11, 1),
            time(1, 30),
            NEW_YORK,
            datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
            id="ny-fall-overlap-first-instance",
        ),
    ],
)
def test_resolve_local_to_utc(d: date, t: time, tz: ZoneInfo, expected_utc: datetime) -> None:
    result = resolve_local(d, t, tz)
    assert result == expected_utc
    assert result.tzinfo is UTC


def test_resolve_local_rejects_aware_time() -> None:
    with pytest.raises(ValueError, match="without tzinfo"):
        resolve_local(date(2026, 11, 12), time(9, 0, tzinfo=UTC), AMSTERDAM)


# --- resolve_due ---------------------------------------------------------------------------

NOW_2245_UTC = datetime(2026, 11, 12, 22, 45, tzinfo=UTC)  # 23:45 in Amsterdam
NOW_2200_UTC = datetime(2026, 11, 12, 22, 0, tzinfo=UTC)  # 23:00 in Amsterdam


@pytest.mark.parametrize(
    ("d", "t", "now", "expected"),
    [
        pytest.param(
            None,
            time(23, 30),
            NOW_2245_UTC,
            Timed(datetime(2026, 11, 13, 22, 30, tzinfo=UTC)),
            id="time-only-passed-rolls-to-tomorrow",
        ),
        pytest.param(
            None,
            time(23, 30),
            NOW_2200_UTC,
            Timed(datetime(2026, 11, 12, 22, 30, tzinfo=UTC)),
            id="time-only-ahead-stays-today",
        ),
        pytest.param(
            date(2026, 11, 12),
            time(23, 30),
            NOW_2200_UTC,
            Timed(datetime(2026, 11, 12, 22, 30, tzinfo=UTC)),
            id="explicit-date-time-ahead",
        ),
        pytest.param(None, None, NOW_2245_UTC, Untimed(), id="neither-date-nor-time"),
    ],
)
def test_resolve_due_resolves(
    d: date | None, t: time | None, now: datetime, expected: Untimed | Timed
) -> None:
    assert resolve_due(d, t, AMSTERDAM, now) == expected


@pytest.mark.parametrize(
    ("d", "t", "now"),
    [
        pytest.param(date(2026, 11, 12), time(12, 0), NOW_2200_UTC, id="explicit-date-long-past"),
        pytest.param(
            date(2026, 11, 12),
            time(23, 30),
            NOW_2245_UTC,
            id="explicit-date-passed-by-minutes",
        ),
    ],
)
def test_resolve_due_in_past(d: date, t: time, now: datetime) -> None:
    with pytest.raises(InPast):
        resolve_due(d, t, AMSTERDAM, now)


def test_resolve_due_date_without_time_rejected() -> None:
    with pytest.raises(InvalidTime):
        resolve_due(date(2026, 11, 12), None, AMSTERDAM, NOW_2200_UTC)


def test_resolve_due_rejects_naive_now() -> None:
    with pytest.raises(ValueError, match="naive"):
        resolve_due(None, time(23, 30), AMSTERDAM, datetime(2026, 11, 12, 22, 0))
