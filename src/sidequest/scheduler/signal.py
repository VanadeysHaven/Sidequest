"""Wakes the scheduler early after a schedule change (BRIEF §5.5, D14).

In-process for now. A Postgres LISTEN/NOTIFY version can hide behind the same interface
once a second process (the web frontend) changes schedules.
"""

import asyncio


class ScheduleSignal:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def wake(self) -> None:
        """A pending occurrence was added, moved or removed."""
        self._event.set()

    async def wait(self, seconds: float) -> bool:
        """Sleep until woken or `seconds` pass. True if woken."""
        try:
            async with asyncio.timeout(seconds):
                await self._event.wait()
        except TimeoutError:
            return False
        finally:
            self._event.clear()
        return True
