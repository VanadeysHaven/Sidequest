"""Tests for the clocks (`SystemClock`, the test `FixedClock`) and `sidequest.core.discord_time`."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from sidequest.core.clock import SystemClock
from sidequest.core.discord_time import Style, ts, ts_due
from tests.support.clock import FixedClock

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
NEW_YORK = ZoneInfo("America/New_York")
START = datetime(2026, 11, 12, 22, 45, tzinfo=UTC)

# --- FixedClock ----------------------------------------------------------------------------


def test_fixed_clock_returns_initial_time() -> None:
    assert FixedClock(START).now() == START


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        pytest.param(timedelta(0), START, id="zero"),
        pytest.param(
            timedelta(hours=1),
            datetime(2026, 11, 12, 23, 45, tzinfo=UTC),
            id="plus-one-hour",
        ),
        pytest.param(
            timedelta(days=-1),
            datetime(2026, 11, 11, 22, 45, tzinfo=UTC),
            id="minus-one-day",
        ),
    ],
)
def test_fixed_clock_advance(delta: timedelta, expected: datetime) -> None:
    clock = FixedClock(START)
    clock.advance(delta)
    assert clock.now() == expected


@pytest.mark.parametrize(
    "new_time",
    [
        pytest.param(datetime(2030, 1, 1, 0, 0, tzinfo=UTC), id="far-future"),
        pytest.param(datetime(2020, 6, 15, 12, 30, tzinfo=UTC), id="past"),
    ],
)
def test_fixed_clock_set_replaces_time(new_time: datetime) -> None:
    clock = FixedClock(START)
    clock.set(new_time)
    assert clock.now() == new_time


@pytest.mark.parametrize(
    "naive",
    [
        pytest.param(datetime(2026, 11, 12, 22, 45), id="naive-init"),
    ],
)
def test_fixed_clock_rejects_naive_on_init(naive: datetime) -> None:
    with pytest.raises(ValueError, match="naive"):
        FixedClock(naive)


@pytest.mark.parametrize(
    "naive",
    [
        pytest.param(datetime(2026, 11, 12, 22, 45), id="naive-set"),
    ],
)
def test_fixed_clock_rejects_naive_on_set(naive: datetime) -> None:
    clock = FixedClock(START)
    with pytest.raises(ValueError, match="naive"):
        clock.set(naive)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        pytest.param(
            datetime(2026, 11, 12, 23, 45, tzinfo=AMSTERDAM),
            datetime(2026, 11, 12, 22, 45, tzinfo=UTC),
            id="amsterdam-normalised",
        ),
        pytest.param(
            datetime(2026, 11, 12, 17, 45, tzinfo=NEW_YORK),
            datetime(2026, 11, 12, 22, 45, tzinfo=UTC),
            id="new-york-normalised",
        ),
    ],
)
def test_fixed_clock_normalises_to_utc(given: datetime, expected: datetime) -> None:
    now = FixedClock(given).now()
    assert now == expected
    assert now.tzinfo is UTC


def test_system_clock_now_is_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


# --- discord_time --------------------------------------------------------------------------

UNIX_DT = datetime(2021, 4, 20, 16, 20, 30, tzinfo=UTC)
UNIX = 1618935630


@pytest.mark.parametrize(
    ("style", "expected"),
    [
        pytest.param("t", f"<t:{UNIX}:t>", id="short-time"),
        pytest.param("T", f"<t:{UNIX}:T>", id="long-time"),
        pytest.param("d", f"<t:{UNIX}:d>", id="short-date"),
        pytest.param("D", f"<t:{UNIX}:D>", id="long-date"),
        pytest.param("f", f"<t:{UNIX}:f>", id="short-date-time"),
        pytest.param("F", f"<t:{UNIX}:F>", id="full-date-time"),
        pytest.param("R", f"<t:{UNIX}:R>", id="relative"),
    ],
)
def test_ts_formats_style(style: Style, expected: str) -> None:
    assert ts(UNIX_DT, style) == expected


def test_ts_default_style_is_f() -> None:
    assert ts(UNIX_DT) == f"<t:{UNIX}:f>"


def test_ts_due_shows_full_then_relative() -> None:
    assert ts_due(UNIX_DT) == f"<t:{UNIX}:F> (<t:{UNIX}:R>)"


@pytest.mark.parametrize(
    "dt",
    [
        pytest.param(datetime(2021, 4, 20, 18, 20, 30, tzinfo=AMSTERDAM), id="amsterdam-offset"),
        pytest.param(datetime(2021, 4, 20, 16, 20, 30, 999999, tzinfo=UTC), id="fraction-floored"),
    ],
)
def test_ts_uses_unix_seconds_of_instant(dt: datetime) -> None:
    assert ts(dt) == f"<t:{UNIX}:f>"


@pytest.mark.parametrize(
    "fn",
    [
        pytest.param(ts, id="ts"),
        pytest.param(ts_due, id="ts_due"),
    ],
)
def test_discord_time_rejects_naive(fn: Callable[[datetime], str]) -> None:
    with pytest.raises(ValueError, match="naive"):
        fn(datetime(2021, 4, 20, 16, 20, 30))
