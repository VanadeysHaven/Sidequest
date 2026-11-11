"""The daily history cleanup task (D8), started by the bot when HISTORY_RETENTION_DAYS is set.

It runs `services.retention.purge_history` with a cutoff of `clock.now() - days`, once at
start-up and then once per interval. Failures are logged and retried at the next interval.
"""

import asyncio
import logging
from datetime import timedelta

from sidequest.core.clock import Clock
from sidequest.services import retention
from sidequest.services.retention import PurgeResult
from sidequest.services.uow import UowFactory

log = logging.getLogger(__name__)


class HistoryPurger:
    def __init__(
        self,
        uows: UowFactory,
        clock: Clock,
        days: int,
        *,
        interval: timedelta = timedelta(days=1),
    ) -> None:
        self._uows = uows
        self._clock = clock
        self._days = days
        self._interval = interval

    async def run_once(self) -> PurgeResult:
        cutoff = self._clock.now() - timedelta(days=self._days)
        async with self._uows() as uow:
            result = await retention.purge_history(uow, cutoff)
        if result.todos or result.occurrences:
            log.info(
                "History cleanup: deleted %d to-do(s) and %d reminder record(s) older than %d days",
                result.todos,
                result.occurrences,
                self._days,
            )
        return result

    async def run(self) -> None:
        """Run until cancelled: clean up now, then once per interval."""
        while True:
            try:
                await self.run_once()
            except Exception:
                log.exception("History cleanup failed; retrying in %s", self._interval)
            await asyncio.sleep(self._interval.total_seconds())
