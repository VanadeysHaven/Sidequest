"""Service-level tests for occurrences: scheduler claims, late and missed reminders, check-off."""

import asyncio
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sidequest.core.enums import OccurrenceStatus, TodoStatus
from sidequest.core.errors import InvalidOperation
from sidequest.core.recurrence import DailyRule
from sidequest.db.models import Occurrence
from sidequest.services import occurrences, settings, todos
from sidequest.services.actor import Actor
from sidequest.services.dto import DueInput
from sidequest.services.effects import DeleteMessage
from sidequest.services.uow import Uow
from tests.support.clock import FixedClock

GUILD_A = 100
OWNER = 1
MANAGER = 9
CHANNEL = 555


def member(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, day, hour, minute, tzinfo=UTC)


async def _occurrences(uow: Uow, todo_id: int) -> list[Occurrence]:
    rows = await uow.session.scalars(
        select(Occurrence).where(Occurrence.todo_id == todo_id).order_by(Occurrence.id)
    )
    return list(rows)


async def _set_channel(uow: Uow) -> None:
    await settings.set_reminder_channel(uow, member(MANAGER, GUILD_A, True), CHANNEL)


async def _daily_todo(uow: Uow) -> int:
    await _set_channel(uow)
    out = await todos.create_recurring(
        uow,
        member(OWNER, GUILD_A),
        title="stretch",
        rule=DailyRule(times=["08:00"]),
    )
    return out.value.id


async def test_once_todo_fires_only_once(uow: Uow, clock: FixedClock) -> None:
    await _set_channel(uow)
    out = await todos.create_once(
        uow,
        member(OWNER, GUILD_A),
        title="x",
        due=DueInput(time=time(10, 0)),
    )
    tid = out.value.id
    clock.set(utc(7, 10))
    first = await occurrences.claim_due(uow, clock.now())
    mine = [r for r in first if r.todo.id == tid]
    assert len(mine) == 1
    assert mine[0].channel_id == CHANNEL
    assert mine[0].effects == []

    clock.set(utc(7, 11))
    second = await occurrences.claim_due(uow, clock.now())
    assert [r for r in second if r.todo.id == tid] == []


async def test_recurring_claim_schedules_next_and_missed_reminder_is_deleted(
    uow: Uow, clock: FixedClock
) -> None:
    tid = await _daily_todo(uow)
    clock.set(utc(8, 8))
    first = await occurrences.claim_due(uow, clock.now())
    sent_id = next(r.occurrence.id for r in first if r.todo.id == tid)
    await occurrences.attach_message(uow, sent_id, CHANNEL, 999)
    statuses = [(o.status, o.due_at) for o in await _occurrences(uow, tid)]
    assert statuses == [
        (OccurrenceStatus.SENT, utc(8, 8)),
        (OccurrenceStatus.PENDING, utc(9, 8)),
    ]

    clock.set(utc(9, 8))
    second = await occurrences.claim_due(uow, clock.now())
    mine = [r for r in second if r.todo.id == tid]
    assert len(mine) == 1
    assert mine[0].effects == [DeleteMessage(channel_id=CHANNEL, message_id=999)]
    old = next(o for o in await _occurrences(uow, tid) if o.id == sent_id)
    assert old.status == OccurrenceStatus.MISSED


async def test_outage_yields_one_late_reminder_and_next_is_in_future(
    uow: Uow, clock: FixedClock
) -> None:
    tid = await _daily_todo(uow)
    now = utc(8, 8) + timedelta(days=3)
    clock.set(now)
    reminders = await occurrences.claim_due(uow, now)
    mine = [r for r in reminders if r.todo.id == tid]
    assert len(mine) == 1
    assert mine[0].occurrence.late is True
    next_view = await todos.get(uow, member(OWNER, GUILD_A), tid)
    assert next_view.next_due_at is not None
    assert next_view.next_due_at > now


async def test_concurrent_claims_split_due_reminders(
    committed_sessions: async_sessionmaker[AsyncSession], clock: FixedClock
) -> None:
    actor = member(OWNER, GUILD_A)
    pending_ids: list[int] = []
    async with committed_sessions() as session:
        uow = Uow(session, clock)
        await _set_channel(uow)
        for i in range(10):
            out = await todos.create_once(
                uow,
                actor,
                title=f"due {i}",
                due=DueInput(time=time(9, 30)),
            )
            assert out.value.pending_occurrence_id is not None
            pending_ids.append(out.value.pending_occurrence_id)
    clock.set(utc(7, 10))

    async def claim() -> list[int]:
        async with committed_sessions() as session:
            reminders = await occurrences.claim_due(Uow(session, clock), clock.now(), limit=10)
        return [r.occurrence.id for r in reminders]

    first, second = await asyncio.gather(claim(), claim())
    assert set(first).isdisjoint(second)
    assert len(first) + len(second) == 10
    assert set(first) | set(second) == set(pending_ids)


async def test_completing_an_already_done_occurrence_is_invalid(uow: Uow) -> None:
    await _set_channel(uow)
    actor = member(OWNER, GUILD_A)
    out = await todos.create_once(uow, actor, title="x", due=DueInput(time=time(10, 0)))
    occ_id = out.value.pending_occurrence_id
    assert occ_id is not None
    done = await occurrences.complete_occurrence(uow, actor, occ_id)
    assert done.value.todo.status == TodoStatus.DONE
    with pytest.raises(InvalidOperation):
        await occurrences.complete_occurrence(uow, actor, occ_id)
