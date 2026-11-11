"""A controllable `sidequest.core.clock.Clock` for tests."""

from datetime import UTC, datetime, timedelta


class FixedClock:
    """A clock that only moves when told to."""

    def __init__(self, now: datetime) -> None:
        self._now = _as_utc(now)

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = _as_utc(now)

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime; use timezone-aware UTC")
    return dt.astimezone(UTC)
