"""The reminder loop (BRIEF §5.5, D14): the database is the schedule, this only polls it.

Each iteration:

1. Recovery: re-post reminders that were claimed (marked sent) but never got a message,
   e.g. because the bot crashed between claiming and posting. Only ones claimed more than
   `recover_after` ago, so a post that is still in flight elsewhere isn't doubled.
2. Claim up to `batch` due occurrences and deliver each: delete the replaced reminder
   (D7), post the new one, store where it went (or why it failed).
3. Sleep until the next due time (at most `max_sleep`), or until `ScheduleSignal.wake()`.
   A full batch skips the sleep.

One bad reminder never stops the loop: it is logged and marked failed. A failing iteration
(e.g. the database is down) is logged and retried after `max_sleep`.
"""

import asyncio
import logging
import tempfile
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from sidequest.core.clock import Clock
from sidequest.core.errors import NotFound
from sidequest.scheduler.notifier import Failed, Notifier, Posted, PostResult
from sidequest.scheduler.signal import ScheduleSignal
from sidequest.services import occurrences
from sidequest.services.dto import DueReminder
from sidequest.services.effects import DeleteMessage, Effect
from sidequest.services.uow import UowFactory

log = logging.getLogger(__name__)

HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "sidequest-heartbeat"
"""Rewritten after every successful iteration (ISO timestamp); S7's healthcheck reads it."""

BATCH = 20
MAX_SLEEP = 60.0
MIN_SLEEP = 1.0
"""Floor for the sleep when nothing was claimed, so an occurrence that is due but locked
by a user's edit can't make the loop spin."""
RECOVER_AFTER = timedelta(seconds=60)


class Scheduler:
    def __init__(
        self,
        uows: UowFactory,
        notifier: Notifier,
        signal: ScheduleSignal,
        clock: Clock,
        *,
        batch: int = BATCH,
        max_sleep: float = MAX_SLEEP,
        recover_after: timedelta = RECOVER_AFTER,
        heartbeat: Path | None = HEARTBEAT_FILE,
    ) -> None:
        self._uows = uows
        self._notifier = notifier
        self._signal = signal
        self._clock = clock
        self._batch = batch
        self._max_sleep = max_sleep
        self._recover_after = recover_after
        self._heartbeat = heartbeat
        self._heartbeat_warned = False

    async def run(self) -> None:
        """Run until cancelled."""
        log.info("Scheduler started")
        while True:
            try:
                await self.recover()
                full = await self.post_due()
                delay = 0.0 if full else await self.seconds_until_next()
            except Exception:
                log.exception("Scheduler iteration failed; retrying in %.0f s", self._max_sleep)
                delay = self._max_sleep
            else:
                self._beat()
            if delay > 0:
                await self._signal.wait(delay)
            else:
                await asyncio.sleep(0)  # let interactions run between full batches

    async def recover(self) -> int:
        """Re-post reminders that were claimed but never posted. Returns how many."""
        older_than = self._clock.now() - self._recover_after
        async with self._uows() as uow:
            reminders = await occurrences.unposted_sent(uow, older_than)
        for reminder in reminders:
            log.info("Re-posting reminder %s (never posted)", reminder.occurrence.id)
            await self.deliver(reminder)
        return len(reminders)

    async def post_due(self) -> bool:
        """Claim and deliver due reminders. True if the batch was full (more may be due)."""
        async with self._uows() as uow:
            due = await occurrences.claim_due(uow, self._clock.now(), limit=self._batch)
        for reminder in due:
            await self.deliver(reminder)
        return len(due) >= self._batch

    async def seconds_until_next(self) -> float:
        async with self._uows() as uow:
            next_due = await occurrences.next_due_at(uow)
        if next_due is None:
            return self._max_sleep
        seconds = (next_due - self._clock.now()).total_seconds()
        return min(max(seconds, MIN_SLEEP), self._max_sleep)

    async def deliver(self, reminder: DueReminder) -> None:
        """Delete the replaced reminder, post this one and record the result. Never raises."""
        occurrence_id = reminder.occurrence.id
        await self._execute(reminder.effects)
        result: PostResult
        try:
            result = await self._notifier.post(reminder)
        except Exception:
            log.exception("Posting reminder %s failed", occurrence_id)
            result = Failed(reason=occurrences.FAILURE_ERROR)
        try:
            await self._record(occurrence_id, result)
        except Exception:
            log.exception("Could not record the result of reminder %s", occurrence_id)

    async def _record(self, occurrence_id: int, result: PostResult) -> None:
        match result:
            case Posted(channel_id=channel_id, message_id=message_id):
                try:
                    async with self._uows() as uow:
                        out = await occurrences.attach_message(
                            uow, occurrence_id, channel_id, message_id
                        )
                except NotFound:
                    # The to-do was deleted while the message was being posted.
                    await self._execute(
                        [DeleteMessage(channel_id=channel_id, message_id=message_id)]
                    )
                    return
                await self._execute(out.effects)
            case Failed(reason=reason):
                log.warning("Reminder %s could not be posted: %s", occurrence_id, reason)
                try:
                    async with self._uows() as uow:
                        await occurrences.mark_failed(uow, occurrence_id, reason)
                except NotFound:
                    pass  # deleted meanwhile; nothing to record

    async def _execute(self, effects: Sequence[Effect]) -> None:
        if not effects:
            return
        try:
            await self._notifier.execute(effects)
        except Exception:
            log.exception("Could not carry out %d effect(s)", len(effects))

    def _beat(self) -> None:
        if self._heartbeat is None:
            return
        try:
            self._heartbeat.write_text(self._clock.now().isoformat(), encoding="utf-8")
        except OSError as exc:
            if not self._heartbeat_warned:
                log.warning("Could not write the heartbeat file %s: %s", self._heartbeat, exc)
                self._heartbeat_warned = True
