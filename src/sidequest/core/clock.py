"""The only source of "now". Swap in a fake in tests."""

from datetime import UTC, datetime


class Clock:
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        return datetime.now(UTC)
