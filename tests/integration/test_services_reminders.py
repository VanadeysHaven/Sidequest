"""Service tests for reminder messages: ticking subtasks on a sent reminder, and `is_live`."""

from datetime import UTC, datetime

import pytest

from sidequest.core.enums import OccurrenceStatus
from sidequest.core.errors import InvalidOperation
from sidequest.core.recurrence import DailyRule
from sidequest.db.models import Occurrence
from sidequest.services import occurrences, settings, subtasks, todos
from sidequest.services.actor import Actor
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


async def _set_channel(uow: Uow) -> None:
    await settings.set_reminder_channel(uow, member(MANAGER, GUILD_A, True), CHANNEL)


async def _daily_todo(uow: Uow) -> tuple[int, int]:
    """Server daily 08:00 to-do with three subtasks. Returns (todo id, first occurrence id)."""
    await _set_channel(uow)
    actor = member(OWNER, GUILD_A)
    out = await todos.create_recurring(
        uow,
        actor,
        title="stretch",
        rule=DailyRule(times=["08:00"]),
    )
    tid = out.value.id
    pending = out.value.pending_occurrence_id
    assert pending is not None
    await subtasks.add(uow, actor, tid, ["a", "b", "c"])
    return tid, pending


async def _subtask_ids(uow: Uow, todo_id: int) -> list[int]:
    view = await todos.get(uow, member(OWNER, GUILD_A), todo_id)
    return [s.id for s in view.subtasks]


async def _occurrence(uow: Uow, occurrence_id: int) -> Occurrence:
    occ = await uow.session.get(Occurrence, occurrence_id, populate_existing=True)
    assert occ is not None
    return occ


async def test_tick_subtasks_only_changes_the_subtasks_shown(uow: Uow, clock: FixedClock) -> None:
    actor = member(OWNER, GUILD_A)
    tid, occ_id = await _daily_todo(uow)
    id_a, id_b, id_c = await _subtask_ids(uow, tid)
    clock.set(utc(8, 8))
    await occurrences.claim_due(uow, clock.now())

    # c is ticked beforehand; it is not among the subtasks this select shows.
    await subtasks.set_done(uow, actor, tid, {id_c})

    out = await occurrences.tick_subtasks(uow, actor, occ_id, done_ids={id_a}, within={id_a, id_b})
    assert out.value.reminder is not None
    assert out.value.reminder.id == occ_id
    done = {s.id: s.done for s in out.value.subtasks}
    assert done == {id_a: True, id_b: False, id_c: True}


async def test_tick_subtasks_on_pending_occurrence_is_invalid(uow: Uow) -> None:
    actor = member(OWNER, GUILD_A)
    tid, occ_id = await _daily_todo(uow)
    id_a, id_b, _ = await _subtask_ids(uow, tid)

    with pytest.raises(InvalidOperation):
        await occurrences.tick_subtasks(uow, actor, occ_id, done_ids={id_a}, within={id_a, id_b})


async def test_tick_subtasks_on_missed_occurrence_is_invalid(uow: Uow, clock: FixedClock) -> None:
    actor = member(OWNER, GUILD_A)
    tid, occ_id = await _daily_todo(uow)
    id_a, id_b, _ = await _subtask_ids(uow, tid)

    clock.set(utc(8, 8))
    await occurrences.claim_due(uow, clock.now())
    clock.set(utc(9, 8))
    await occurrences.claim_due(uow, clock.now())  # the first reminder is now missed

    assert (await _occurrence(uow, occ_id)).status == OccurrenceStatus.MISSED
    with pytest.raises(InvalidOperation):
        await occurrences.tick_subtasks(uow, actor, occ_id, done_ids={id_a}, within={id_a, id_b})


async def test_is_live_follows_the_reminder_lifecycle(uow: Uow, clock: FixedClock) -> None:
    actor = member(OWNER, GUILD_A)
    tid, occ_id = await _daily_todo(uow)
    assert await occurrences.is_live(uow, occ_id) is False  # pending, not yet sent

    clock.set(utc(8, 8))
    await occurrences.claim_due(uow, clock.now())
    assert await occurrences.is_live(uow, occ_id) is True

    await occurrences.complete_occurrence(uow, actor, occ_id)
    assert await occurrences.is_live(uow, occ_id) is False


async def test_is_live_is_false_for_missed_reminder(uow: Uow, clock: FixedClock) -> None:
    tid, occ_id = await _daily_todo(uow)
    clock.set(utc(8, 8))
    await occurrences.claim_due(uow, clock.now())
    clock.set(utc(9, 8))
    await occurrences.claim_due(uow, clock.now())

    assert await occurrences.is_live(uow, occ_id) is False


async def test_is_live_is_false_after_the_todo_is_deleted(uow: Uow, clock: FixedClock) -> None:
    actor = member(OWNER, GUILD_A)
    tid, occ_id = await _daily_todo(uow)
    clock.set(utc(8, 8))
    await occurrences.claim_due(uow, clock.now())
    assert await occurrences.is_live(uow, occ_id) is True

    await todos.delete(uow, actor, tid)
    assert await occurrences.is_live(uow, occ_id) is False


async def test_is_live_is_false_for_unknown_occurrence(uow: Uow) -> None:
    assert await occurrences.is_live(uow, 999_999) is False
