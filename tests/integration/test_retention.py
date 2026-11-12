"""History cleanup (D8) against real PostgreSQL: which finished rows go, which stay."""

from datetime import datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sidequest.core.enums import OccurrenceStatus
from sidequest.core.recurrence import DailyRule
from sidequest.db.models import Occurrence, Subtask, Todo
from sidequest.scheduler.retention import HistoryPurger
from sidequest.services import retention, settings, subtasks, todos
from sidequest.services.actor import Actor
from sidequest.services.dto import DueInput
from sidequest.services.retention import PurgeResult
from sidequest.services.uow import Uow, UowFactory
from tests.support.clock import FixedClock

GUILD = 100
OWNER = 1
MANAGER = 9
CHANNEL = 555
RETENTION_DAYS = 30


def member(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


def ago(clock: FixedClock, days: int) -> datetime:
    return clock.now() - timedelta(days=days)


def cutoff(clock: FixedClock) -> datetime:
    return ago(clock, RETENTION_DAYS)


async def _setup(uow: Uow) -> None:
    await settings.set_reminder_channel(uow, member(MANAGER, GUILD, True), CHANNEL)


UNTIMED = DueInput()


async def _once(uow: Uow, title: str, due: DueInput = UNTIMED) -> int:
    out = await todos.create_once(uow, member(OWNER, GUILD), title=title, due=due)
    return out.value.id


async def _recurring(uow: Uow, title: str) -> int:
    out = await todos.create_recurring(
        uow,
        member(OWNER, GUILD),
        title=title,
        rule=DailyRule(times=["08:00"]),
    )
    return out.value.id


async def _age_todo(
    uow: Uow, todo_id: int, *, updated_at: datetime, completed_at: datetime | None = None
) -> None:
    await uow.session.execute(
        update(Todo)
        .where(Todo.id == todo_id)
        .values(updated_at=updated_at, completed_at=completed_at)
        .execution_options(synchronize_session=False)
    )
    await uow.session.commit()


async def _add_occurrence(
    uow: Uow, todo_id: int, due_at: datetime, status: OccurrenceStatus
) -> None:
    uow.session.add(Occurrence(todo_id=todo_id, due_at=due_at, status=status))
    await uow.session.flush()


async def _todo_ids(uow: Uow) -> set[int]:
    return set(await uow.session.scalars(select(Todo.id)))


async def _occurrence_statuses(uow: Uow, todo_id: int) -> list[str]:
    rows = await uow.session.scalars(select(Occurrence.status).where(Occurrence.todo_id == todo_id))
    return sorted(rows)


async def _subtask_count(uow: Uow, todo_id: int) -> int:
    count = await uow.session.scalar(
        select(func.count()).select_from(Subtask).where(Subtask.todo_id == todo_id)
    )
    return int(count or 0)


async def test_done_todo_older_than_cutoff_is_deleted_with_children(
    uow: Uow, clock: FixedClock
) -> None:
    await _setup(uow)
    todo_id = await _once(uow, "pay rent", DueInput(time=time(10, 0)))
    await subtasks.add(uow, member(OWNER, GUILD), todo_id, ["bank", "receipt"])
    await todos.complete(uow, member(OWNER, GUILD), todo_id)
    await _age_todo(uow, todo_id, updated_at=ago(clock, 31), completed_at=ago(clock, 31))
    assert await _subtask_count(uow, todo_id) == 2
    assert await _occurrence_statuses(uow, todo_id) == [OccurrenceStatus.DONE]

    result = await retention.purge_history(uow, cutoff(clock))

    assert result == PurgeResult(todos=1, occurrences=0)
    assert todo_id not in await _todo_ids(uow)
    assert await _subtask_count(uow, todo_id) == 0
    assert await _occurrence_statuses(uow, todo_id) == []


async def test_done_todo_completed_within_retention_is_kept(uow: Uow, clock: FixedClock) -> None:
    await _setup(uow)
    todo_id = await _once(uow, "pay rent")
    await todos.complete(uow, member(OWNER, GUILD), todo_id)
    await _age_todo(uow, todo_id, updated_at=ago(clock, 29), completed_at=ago(clock, 29))

    result = await retention.purge_history(uow, cutoff(clock))

    assert result == PurgeResult(todos=0, occurrences=0)
    assert todo_id in await _todo_ids(uow)


async def test_cancelled_todo_older_than_cutoff_is_deleted(uow: Uow, clock: FixedClock) -> None:
    await _setup(uow)
    todo_id = await _once(uow, "abandoned")
    await todos.delete(uow, member(OWNER, GUILD), todo_id)
    await _age_todo(uow, todo_id, updated_at=ago(clock, 31), completed_at=None)

    result = await retention.purge_history(uow, cutoff(clock))

    assert result == PurgeResult(todos=1, occurrences=0)
    assert todo_id not in await _todo_ids(uow)


async def test_cancelled_todo_within_retention_is_kept(uow: Uow, clock: FixedClock) -> None:
    await _setup(uow)
    todo_id = await _once(uow, "abandoned")
    await todos.delete(uow, member(OWNER, GUILD), todo_id)
    await _age_todo(uow, todo_id, updated_at=ago(clock, 29), completed_at=None)

    result = await retention.purge_history(uow, cutoff(clock))

    assert result == PurgeResult(todos=0, occurrences=0)
    assert todo_id in await _todo_ids(uow)


async def test_open_todos_are_never_deleted(uow: Uow, clock: FixedClock) -> None:
    await _setup(uow)
    once_id = await _once(uow, "open one-time")
    recurring_id = await _recurring(uow, "open daily")
    await _age_todo(uow, once_id, updated_at=ago(clock, 31))
    await _age_todo(uow, recurring_id, updated_at=ago(clock, 31))

    result = await retention.purge_history(uow, cutoff(clock))

    assert result == PurgeResult(todos=0, occurrences=0)
    assert {once_id, recurring_id} <= await _todo_ids(uow)


async def test_closed_occurrences_of_open_recurring_todo_older_than_cutoff_are_deleted(
    uow: Uow, clock: FixedClock
) -> None:
    await _setup(uow)
    todo_id = await _recurring(uow, "water plants")
    for status in (
        OccurrenceStatus.DONE,
        OccurrenceStatus.MISSED,
        OccurrenceStatus.FAILED,
        OccurrenceStatus.CANCELLED,
    ):
        await _add_occurrence(uow, todo_id, ago(clock, 31), status)
        await _add_occurrence(uow, todo_id, ago(clock, 29), status)
    await _add_occurrence(uow, todo_id, ago(clock, 31), OccurrenceStatus.SENT)
    await uow.session.commit()

    result = await retention.purge_history(uow, cutoff(clock))

    assert result == PurgeResult(todos=0, occurrences=4)
    assert await _occurrence_statuses(uow, todo_id) == sorted(
        [
            OccurrenceStatus.DONE,
            OccurrenceStatus.MISSED,
            OccurrenceStatus.FAILED,
            OccurrenceStatus.CANCELLED,
            OccurrenceStatus.PENDING,
            OccurrenceStatus.SENT,
        ]
    )


async def test_closed_occurrence_of_open_one_time_todo_is_kept(uow: Uow, clock: FixedClock) -> None:
    await _setup(uow)
    todo_id = await _once(uow, "call back", DueInput(time=time(10, 0)))
    await _add_occurrence(uow, todo_id, ago(clock, 31), OccurrenceStatus.FAILED)
    await uow.session.commit()

    result = await retention.purge_history(uow, cutoff(clock))

    assert result == PurgeResult(todos=0, occurrences=0)
    assert await _occurrence_statuses(uow, todo_id) == [
        OccurrenceStatus.FAILED,
        OccurrenceStatus.PENDING,
    ]


async def test_nothing_old_deletes_nothing(uow: Uow, clock: FixedClock) -> None:
    await _setup(uow)
    finished_id = await _once(uow, "recent")
    await todos.complete(uow, member(OWNER, GUILD), finished_id)
    await _recurring(uow, "still going")

    result = await retention.purge_history(uow, cutoff(clock))

    assert result == PurgeResult(todos=0, occurrences=0)


async def test_history_purger_cuts_off_at_clock_now_minus_days(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock
) -> None:
    uows = UowFactory(committed_sessions, clock)
    async with uows() as uow:
        await _setup(uow)
        old_id = await _once(uow, "old")
        recent_id = await _once(uow, "recent")
        await todos.complete(uow, member(OWNER, GUILD), old_id)
        await todos.complete(uow, member(OWNER, GUILD), recent_id)
        await _age_todo(uow, old_id, updated_at=ago(clock, 31), completed_at=ago(clock, 31))
        await _age_todo(uow, recent_id, updated_at=ago(clock, 29), completed_at=ago(clock, 29))

    result = await HistoryPurger(uows, clock, days=RETENTION_DAYS).run_once()

    assert result == PurgeResult(todos=1, occurrences=0)
    async with uows() as uow:
        remaining = await _todo_ids(uow)
    assert old_id not in remaining
    assert recent_id in remaining
