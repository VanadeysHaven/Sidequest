"""Scheduler loop tests against real PostgreSQL: claims, recovery, failures, wake-ups."""

import asyncio
import contextlib
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sidequest.core.enums import OccurrenceStatus
from sidequest.core.recurrence import DailyRule
from sidequest.db.models import Occurrence
from sidequest.scheduler.loop import Scheduler
from sidequest.scheduler.notifier import Failed, Posted
from sidequest.scheduler.signal import ScheduleSignal
from sidequest.services import occurrences, settings, todos
from sidequest.services.actor import Actor
from sidequest.services.dto import DueInput, DueReminder
from sidequest.services.effects import DeleteMessage
from sidequest.services.uow import UowFactory
from tests.support.clock import FixedClock
from tests.support.notifier import FakeNotifier

GUILD_A = 100
OWNER = 1
MANAGER = 9
CHANNEL = 555


def member(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, day, hour, minute, tzinfo=UTC)


def _scheduler(
    uows: UowFactory,
    notifier: FakeNotifier,
    clock: FixedClock,
    tmp_path: Path,
    signal: ScheduleSignal | None = None,
    max_sleep: float = 60.0,
) -> Scheduler:
    return Scheduler(
        uows,
        notifier,
        signal or ScheduleSignal(),
        clock,
        max_sleep=max_sleep,
        heartbeat=tmp_path / "heartbeat",
    )


async def _set_channel(uows: UowFactory) -> None:
    async with uows() as uow:
        await settings.set_reminder_channel(uow, member(MANAGER, GUILD_A, True), CHANNEL)


async def _create_once(uows: UowFactory, *, title: str, due: time) -> tuple[int, int]:
    """Returns (todo id, pending occurrence id)."""
    async with uows() as uow:
        out = await todos.create_once(
            uow, member(OWNER, GUILD_A), title=title, due=DueInput(time=due)
        )
    assert out.value.pending_occurrence_id is not None
    return out.value.id, out.value.pending_occurrence_id


async def _create_daily(uows: UowFactory, *, title: str) -> int:
    async with uows() as uow:
        out = await todos.create_recurring(
            uow,
            member(OWNER, GUILD_A),
            title=title,
            rule=DailyRule(times=["08:00"]),
        )
    return out.value.id


async def _occurrences(uows: UowFactory, todo_id: int) -> list[Occurrence]:
    async with uows() as uow:
        rows = await uow.session.scalars(
            select(Occurrence).where(Occurrence.todo_id == todo_id).order_by(Occurrence.id)
        )
        return list(rows)


def _mine(posted: list[DueReminder], todo_id: int) -> list[DueReminder]:
    return [r for r in posted if r.todo.id == todo_id]


async def test_once_timed_reminder_posts_once_at_due_time(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock, tmp_path: Path
) -> None:
    uows = UowFactory(committed_sessions, clock)
    notifier = FakeNotifier()
    scheduler = _scheduler(uows, notifier, clock, tmp_path)
    await _set_channel(uows)
    todo_id, occ_id = await _create_once(uows, title="water", due=time(10, 0))

    clock.set(utc(7, 9, 59))
    assert await scheduler.post_due() is False
    assert notifier.posted == []

    clock.set(utc(7, 10))
    assert await scheduler.post_due() is False
    assert len(notifier.posted) == 1
    assert notifier.posted[0].channel_id == CHANNEL

    clock.set(utc(7, 10, 5))
    await scheduler.post_due()
    assert len(notifier.posted) == 1

    [occ] = await _occurrences(uows, todo_id)
    assert occ.id == occ_id
    assert occ.status == OccurrenceStatus.SENT
    assert occ.channel_id == CHANNEL
    # FakeNotifier hands out message ids from 1 on, and this is its first post.
    assert occ.message_id == 1


async def test_recurring_daily_replaces_previous_reminder(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock, tmp_path: Path
) -> None:
    uows = UowFactory(committed_sessions, clock)
    notifier = FakeNotifier()
    scheduler = _scheduler(uows, notifier, clock, tmp_path)
    await _set_channel(uows)
    todo_id = await _create_daily(uows, title="stretch")

    clock.set(utc(8, 8))
    await scheduler.post_due()
    [first, pending] = await _occurrences(uows, todo_id)
    assert first.status == OccurrenceStatus.SENT
    assert pending.status == OccurrenceStatus.PENDING
    assert pending.due_at == utc(9, 8)
    assert first.message_id is not None
    first_occ_id = first.id
    first_message_id = first.message_id
    first_channel = first.channel_id
    assert len(_mine(notifier.posted, todo_id)) == 1

    clock.set(utc(9, 8))
    await scheduler.post_due()
    assert len(_mine(notifier.posted, todo_id)) == 2
    second_occ_id = _mine(notifier.posted, todo_id)[1].occurrence.id

    old = next(o for o in await _occurrences(uows, todo_id) if o.id == first_occ_id)
    assert old.status == OccurrenceStatus.MISSED

    delete = ("execute", DeleteMessage(channel_id=first_channel, message_id=first_message_id))
    assert delete in notifier.calls
    assert notifier.calls.index(delete) < notifier.calls.index(("post", second_occ_id))


async def test_outage_posts_one_late_reminder(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock, tmp_path: Path
) -> None:
    uows = UowFactory(committed_sessions, clock)
    notifier = FakeNotifier()
    scheduler = _scheduler(uows, notifier, clock, tmp_path)
    await _set_channel(uows)
    todo_id = await _create_daily(uows, title="stretch")

    clock.set(utc(11, 8))  # three days past the first due time (Jan 8, 08:00)
    await scheduler.post_due()

    mine = _mine(notifier.posted, todo_id)
    assert len(mine) == 1
    assert mine[0].occurrence.late is True


async def test_early_completion_is_never_posted(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock, tmp_path: Path
) -> None:
    uows = UowFactory(committed_sessions, clock)
    notifier = FakeNotifier()
    scheduler = _scheduler(uows, notifier, clock, tmp_path)
    await _set_channel(uows)
    todo_id, occ_id = await _create_once(uows, title="early", due=time(10, 0))

    async with uows() as uow:
        await occurrences.complete_occurrence(uow, member(OWNER, GUILD_A), occ_id)

    clock.set(utc(7, 11))
    await scheduler.post_due()
    assert _mine(notifier.posted, todo_id) == []


async def test_missing_reminder_channel_marks_occurrence_failed(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock, tmp_path: Path
) -> None:
    uows = UowFactory(committed_sessions, clock)
    notifier = FakeNotifier()
    notifier.respond = lambda _reminder: Failed(reason="no_channel")
    scheduler = _scheduler(uows, notifier, clock, tmp_path)
    await _set_channel(uows)
    todo_id, _ = await _create_once(uows, title="x", due=time(10, 0))

    clock.set(utc(7, 10))
    await scheduler.post_due()

    [occ] = await _occurrences(uows, todo_id)
    assert occ.status == OccurrenceStatus.FAILED
    assert occ.failure_reason == "no_channel"


async def test_crash_recovery_reposts_claimed_but_unposted_reminder(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock, tmp_path: Path
) -> None:
    uows = UowFactory(committed_sessions, clock)
    notifier = FakeNotifier()
    scheduler = _scheduler(uows, notifier, clock, tmp_path)
    await _set_channel(uows)
    todo_id, occ_id = await _create_once(uows, title="crash", due=time(10, 0))

    # Claimed at 10:00 but never posted (the bot "crashed" right after the claim).
    clock.set(utc(7, 10))
    async with uows() as uow:
        claimed = await occurrences.claim_due(uow, clock.now())
    assert [r.occurrence.id for r in claimed] == [occ_id]
    assert notifier.posted == []

    assert await scheduler.recover() == 0
    assert notifier.posted == []

    clock.set(utc(7, 10) + timedelta(seconds=61))
    assert await scheduler.recover() == 1
    assert len(_mine(notifier.posted, todo_id)) == 1
    [occ] = await _occurrences(uows, todo_id)
    assert occ.message_id is not None

    assert await scheduler.recover() == 0
    assert len(_mine(notifier.posted, todo_id)) == 1


async def test_notifier_exception_does_not_stop_the_batch(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock, tmp_path: Path
) -> None:
    uows = UowFactory(committed_sessions, clock)
    notifier = FakeNotifier()

    def respond(reminder: DueReminder) -> None:
        if reminder.todo.title == "boom":
            raise RuntimeError("discord is on fire")
        return None

    notifier.respond = respond
    scheduler = _scheduler(uows, notifier, clock, tmp_path)
    await _set_channel(uows)
    boom_id, boom_occ = await _create_once(uows, title="boom", due=time(10, 0))
    ok_id, ok_occ = await _create_once(uows, title="fine", due=time(10, 0))

    clock.set(utc(7, 10))
    await scheduler.post_due()  # must not raise

    [boom] = await _occurrences(uows, boom_id)
    assert boom.id == boom_occ
    assert boom.status == OccurrenceStatus.FAILED
    assert boom.failure_reason == "error"

    [ok] = await _occurrences(uows, ok_id)
    assert ok.id == ok_occ
    assert ok.status == OccurrenceStatus.SENT
    assert ok.message_id is not None


async def test_schedule_signal_wakes_the_loop_early(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock, tmp_path: Path
) -> None:
    uows = UowFactory(committed_sessions, clock)
    notifier = FakeNotifier()
    signal = ScheduleSignal()
    heartbeat = tmp_path / "heartbeat"
    scheduler = _scheduler(uows, notifier, clock, tmp_path, signal=signal, max_sleep=60)
    await _set_channel(uows)

    task = asyncio.create_task(scheduler.run())
    try:
        # Wait until the first iteration is done (heartbeat written), so the loop is asleep.
        for _ in range(500):
            if heartbeat.exists():
                break
            await asyncio.sleep(0.01)
        assert heartbeat.exists(), "the first scheduler iteration never finished"

        todo_id, _ = await _create_once(uows, title="wake me", due=time(10, 0))
        clock.set(utc(7, 10))
        signal.wake()

        await notifier.wait_for_posts(1, seconds=5)
        assert len(_mine(notifier.posted, todo_id)) == 1
        assert heartbeat.exists()
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_stop_ends_a_sleeping_loop_right_away(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock, tmp_path: Path
) -> None:
    uows = UowFactory(committed_sessions, clock)
    heartbeat = tmp_path / "heartbeat"
    heartbeat.write_text("left over from an earlier run", encoding="utf-8")
    scheduler = _scheduler(uows, FakeNotifier(), clock, tmp_path, max_sleep=60)

    task = asyncio.create_task(scheduler.run())
    try:
        # The old heartbeat is removed at start; a new one marks the end of iteration one.
        for _ in range(500):
            if (
                heartbeat.exists()
                and heartbeat.read_text(encoding="utf-8") == clock.now().isoformat()
            ):
                break
            await asyncio.sleep(0.01)
        assert heartbeat.read_text(encoding="utf-8") == clock.now().isoformat()

        scheduler.stop()
        await asyncio.wait_for(task, timeout=2)
        assert not task.cancelled()
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class GatedNotifier(FakeNotifier):
    """Blocks inside `post` until `release` is set, to stop the loop mid-delivery."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def post(self, reminder: DueReminder) -> Posted | Failed:  # type: ignore[override]
        self.entered.set()
        await self.release.wait()
        return await super().post(reminder)  # type: ignore[return-value]


async def test_stop_finishes_the_reminder_being_delivered(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock, tmp_path: Path
) -> None:
    uows = UowFactory(committed_sessions, clock)
    notifier = GatedNotifier()
    scheduler = _scheduler(uows, notifier, clock, tmp_path)
    await _set_channel(uows)
    todo_id, _ = await _create_once(uows, title="in flight", due=time(10, 0))
    clock.set(utc(7, 10))

    task = asyncio.create_task(scheduler.run())
    try:
        await asyncio.wait_for(notifier.entered.wait(), timeout=5)
        scheduler.stop()
        notifier.release.set()
        await asyncio.wait_for(task, timeout=5)
        assert not task.cancelled()
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    [occ] = await _occurrences(uows, todo_id)
    assert occ.status == OccurrenceStatus.SENT
    assert occ.message_id is not None  # recorded, so nothing is re-posted after a restart
