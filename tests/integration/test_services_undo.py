"""Service-level tests for undoing a check-off (D60-D66): restores, re-posts, refusals, chains
and subtasks."""

import re
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from sidequest.core.enums import OccurrenceStatus, TodoStatus
from sidequest.core.errors import Forbidden, InvalidOperation, NameTaken, NotFound
from sidequest.core.limits import UNDO_WINDOW
from sidequest.core.recurrence import DailyRule
from sidequest.db.models import Occurrence
from sidequest.services import lists, occurrences, settings, subtasks, todos, undo
from sidequest.services.actor import Actor
from sidequest.services.dto import DueInput, TodoPatch
from sidequest.services.uow import Uow
from tests.support.clock import FixedClock

GUILD = 100
OWNER = 1
OTHER = 2
COLLAB = 3
MANAGER = 9
CHANNEL = 555


def member(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


ACTOR = member(OWNER, GUILD)
OTHER_ACTOR = member(OTHER, GUILD)
COLLAB_ACTOR = member(COLLAB, GUILD)
MANAGER_ACTOR = member(MANAGER, GUILD, True)


def utc(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2030, 1, day, hour, minute, second, tzinfo=UTC)


async def _occurrences(uow: Uow, todo_id: int) -> list[Occurrence]:
    rows = await uow.session.scalars(
        select(Occurrence).where(Occurrence.todo_id == todo_id).order_by(Occurrence.id)
    )
    return list(rows)


async def _set_channel(uow: Uow) -> None:
    await settings.set_reminder_channel(uow, MANAGER_ACTOR, CHANNEL)


async def _create_once(
    uow: Uow, title: str = "milk", due: time | None = None
) -> tuple[int, int | None]:
    """Returns (todo id, pending occurrence id). Untimed when `due` is None."""
    out = await todos.create_once(uow, ACTOR, title=title, due=DueInput(time=due))
    return out.value.id, out.value.pending_occurrence_id


async def _create_daily(
    uow: Uow, title: str = "stretch", times: tuple[str, ...] = ("08:00",)
) -> int:
    out = await todos.create_recurring(uow, ACTOR, title=title, rule=DailyRule(times=list(times)))
    return out.value.id


async def _snapshot(uow: Uow, todo_id: int) -> dict[str, Any]:
    """The state a check-off changes and an undo must bring back."""
    view = await todos.get(uow, ACTOR, todo_id)
    occs = await _occurrences(uow, todo_id)
    return {
        "status": view.status,
        "completed": (view.completed_at, view.completed_by),
        "pending": view.pending_occurrence_id,
        "next_due": view.next_due_at,
        "ticks": [(s.id, s.done_at, s.done_by) for s in view.subtasks],
        "occurrences": [(o.id, o.status, o.due_at, o.completed_at, o.completed_by) for o in occs],
    }


# --- 1. state after undo equals the state before the check-off ---------------------------


async def test_undo_untimed_once_reopens_the_to_do(uow: Uow) -> None:
    todo_id, _ = await _create_once(uow)
    before = await _snapshot(uow, todo_id)

    checked = await todos.complete(uow, ACTOR, todo_id)
    token = checked.value.undo
    assert token.occurrence_id is None
    assert token.previous is None
    assert token.followup_id is None
    assert token.ticks == ()

    undone = await undo.undo(uow, ACTOR, token)
    assert await _snapshot(uow, todo_id) == before
    assert undone.value.repost is None
    assert undone.changed_schedule is False


async def test_undo_early_check_off_of_timed_once_makes_it_pending_again(
    uow: Uow, clock: FixedClock
) -> None:
    await _set_channel(uow)
    todo_id, occ_id = await _create_once(uow, title="water", due=time(10, 0))
    before = await _snapshot(uow, todo_id)

    checked = await occurrences.complete_occurrence(uow, ACTOR, occ_id)
    token = checked.value.undo
    assert token.previous == OccurrenceStatus.PENDING
    assert token.occurrence_id == occ_id
    assert token.followup_id is None

    undone = await undo.undo(uow, ACTOR, token)
    assert await _snapshot(uow, todo_id) == before
    assert undone.value.repost is None
    assert undone.changed_schedule is True

    # The reminder fires at its original time, late when it is caught up after two minutes.
    clock.set(utc(7, 10, 3))
    claimed = await occurrences.claim_due(uow, clock.now())
    [mine] = [r for r in claimed if r.todo.id == todo_id]
    assert mine.occurrence.id == occ_id
    assert mine.occurrence.late is True


async def test_undo_sent_timed_once_restores_sent(uow: Uow, clock: FixedClock) -> None:
    await _set_channel(uow)
    todo_id, occ_id = await _create_once(uow, title="water", due=time(10, 0))
    clock.set(utc(7, 10))
    await occurrences.claim_due(uow, clock.now())
    before = await _snapshot(uow, todo_id)

    checked = await todos.complete(uow, ACTOR, todo_id)
    token = checked.value.undo
    assert token.previous == OccurrenceStatus.SENT
    assert token.occurrence_id == occ_id

    undone = await undo.undo(uow, ACTOR, token)
    assert await _snapshot(uow, todo_id) == before
    assert undone.changed_schedule is False


async def test_undo_repeating_sent_reminder_restores_ticks_and_keeps_follow_up(
    uow: Uow, clock: FixedClock
) -> None:
    await _set_channel(uow)
    clock.set(utc(7, 7))
    todo_id = await _create_daily(uow, times=("08:00", "08:30"))
    out = await subtasks.add(uow, ACTOR, todo_id, ["stretch arms", "touch toes"])
    arms, toes = [s.id for s in out.value.subtasks]

    clock.set(utc(7, 8))
    claimed = await occurrences.claim_due(uow, clock.now())
    [reminder] = [r for r in claimed if r.todo.id == todo_id]
    sent_id = reminder.occurrence.id
    [sent, follow] = await _occurrences(uow, todo_id)
    assert sent.status == OccurrenceStatus.SENT
    assert follow.status == OccurrenceStatus.PENDING

    clock.set(utc(7, 8, 1))
    await subtasks.toggle(uow, ACTOR, arms)
    clock.set(utc(7, 8, 2))
    await subtasks.toggle(uow, ACTOR, toes)
    before = await _snapshot(uow, todo_id)

    clock.set(utc(7, 8, 3))
    checked = await todos.complete(uow, ACTOR, todo_id)
    token = checked.value.undo
    assert token.previous == OccurrenceStatus.SENT
    assert token.occurrence_id == sent_id
    assert token.followup_id == follow.id
    assert [(t.id, t.done_at, t.done_by) for t in token.ticks] == [
        (arms, utc(7, 8, 1), OWNER),
        (toes, utc(7, 8, 2), OWNER),
    ]

    clock.set(utc(7, 8, 4))
    undone = await undo.undo(uow, ACTOR, token)
    assert await _snapshot(uow, todo_id) == before
    assert undone.changed_schedule is False


async def test_undo_repeating_early_check_off_cancels_the_follow_up(
    uow: Uow, clock: FixedClock
) -> None:
    await _set_channel(uow)
    clock.set(utc(7, 7))
    todo_id = await _create_daily(uow, times=("08:00", "08:30"))
    [original] = await _occurrences(uow, todo_id)
    original_id, original_due = original.id, original.due_at

    clock.set(utc(7, 7, 5))
    checked = await occurrences.complete_occurrence(uow, ACTOR, original_id)
    token = checked.value.undo
    assert token.previous == OccurrenceStatus.PENDING
    assert token.occurrence_id == original_id
    assert token.ticks == ()

    [_, follow] = await _occurrences(uow, todo_id)
    assert follow.status == OccurrenceStatus.PENDING
    assert token.followup_id == follow.id

    clock.set(utc(7, 7, 6))
    undone = await undo.undo(uow, ACTOR, token)
    assert undone.changed_schedule is True
    assert undone.value.repost is None

    occs = {o.id: o for o in await _occurrences(uow, todo_id)}
    assert occs[original_id].status == OccurrenceStatus.PENDING
    assert occs[original_id].due_at == original_due
    assert occs[follow.id].status == OccurrenceStatus.CANCELLED
    pending = [o.id for o in occs.values() if o.status == OccurrenceStatus.PENDING]
    assert pending == [original_id]
    view = await todos.get(uow, ACTOR, todo_id)
    assert view.pending_occurrence_id == original_id
    assert view.status == TodoStatus.OPEN


# --- 2. re-post ---------------------------------------------------------------------------


async def test_undone_late_timed_reminder_is_reposted_as_late(uow: Uow, clock: FixedClock) -> None:
    await _set_channel(uow)
    todo_id, occ_id = await _create_once(uow, title="water", due=time(10, 0))
    clock.set(utc(7, 10, 5))  # more than two minutes after the due time
    await occurrences.claim_due(uow, clock.now())
    checked = await todos.complete(uow, ACTOR, todo_id)

    clock.set(utc(7, 10, 7))
    undone = await undo.undo(uow, ACTOR, checked.value.undo)
    repost = undone.value.repost
    assert repost is not None
    assert repost.occurrence.id == occ_id
    assert repost.occurrence.message_id is None
    assert repost.occurrence.sent_at == clock.now()
    assert repost.occurrence.late is True

    unposted = await occurrences.unposted_sent(uow, older_than=clock.now() - timedelta(seconds=60))
    assert occ_id not in [r.occurrence.id for r in unposted]


async def test_undone_repeating_reminder_is_reposted_without_message(
    uow: Uow, clock: FixedClock
) -> None:
    await _set_channel(uow)
    clock.set(utc(7, 7))
    todo_id = await _create_daily(uow, times=("08:00", "08:30"))
    clock.set(utc(7, 8))
    claimed = await occurrences.claim_due(uow, clock.now())
    [reminder] = [r for r in claimed if r.todo.id == todo_id]
    sent_id = reminder.occurrence.id

    clock.set(utc(7, 8, 1))
    checked = await todos.complete(uow, ACTOR, todo_id)
    clock.set(utc(7, 8, 2))
    undone = await undo.undo(uow, ACTOR, checked.value.undo)
    repost = undone.value.repost
    assert repost is not None
    assert repost.occurrence.id == sent_id
    assert repost.occurrence.message_id is None
    assert repost.occurrence.sent_at == clock.now()
    assert repost.occurrence.late is False

    unposted = await occurrences.unposted_sent(uow, older_than=clock.now() - timedelta(seconds=60))
    assert sent_id not in [r.occurrence.id for r in unposted]


# --- 3. refusals (nothing changes) --------------------------------------------------------


async def test_undo_refused_just_after_two_hours(uow: Uow, clock: FixedClock) -> None:
    todo_id, _ = await _create_once(uow)
    checked = await todos.complete(uow, ACTOR, todo_id)
    clock.set(clock.now() + UNDO_WINDOW + timedelta(seconds=1))

    with pytest.raises(InvalidOperation, match=re.escape(undo.TOO_LATE)):
        await undo.undo(uow, ACTOR, checked.value.undo)
    view = await todos.get(uow, ACTOR, todo_id)
    assert view.status == TodoStatus.DONE


async def test_undo_allowed_exactly_two_hours(uow: Uow, clock: FixedClock) -> None:
    todo_id, _ = await _create_once(uow)
    checked = await todos.complete(uow, ACTOR, todo_id)
    clock.set(clock.now() + UNDO_WINDOW)

    undone = await undo.undo(uow, ACTOR, checked.value.undo)
    assert undone.value.todo.status == TodoStatus.OPEN


async def test_undo_twice_is_refused(uow: Uow) -> None:
    todo_id, _ = await _create_once(uow)
    checked = await todos.complete(uow, ACTOR, todo_id)
    await undo.undo(uow, ACTOR, checked.value.undo)

    with pytest.raises(InvalidOperation, match=re.escape(undo.NOT_CHECKED_OFF)):
        await undo.undo(uow, ACTOR, checked.value.undo)
    view = await todos.get(uow, ACTOR, todo_id)
    assert view.status == TodoStatus.OPEN


async def test_another_user_cannot_undo(uow: Uow) -> None:
    # The fallback Default List: any member may check off, but only the one who did may undo.
    todo_id, _ = await _create_once(uow)
    checked = await todos.complete(uow, ACTOR, todo_id)

    with pytest.raises(Forbidden, match=re.escape(undo.NOT_YOURS)):
        await undo.undo(uow, OTHER_ACTOR, checked.value.undo)
    view = await todos.get(uow, ACTOR, todo_id)
    assert view.status == TodoStatus.DONE


async def test_undo_refused_after_losing_collaborator_rights(uow: Uow) -> None:
    lst = await lists.create(uow, ACTOR, "Work")
    await lists.set_collaborators(uow, ACTOR, lst.id, [COLLAB])
    out = await todos.create_once(uow, COLLAB_ACTOR, list_id=lst.id, title="report")
    checked = await todos.complete(uow, COLLAB_ACTOR, out.value.id)

    await lists.set_collaborators(uow, ACTOR, lst.id, [])
    with pytest.raises(Forbidden, match="can check this off"):
        await undo.undo(uow, COLLAB_ACTOR, checked.value.undo)
    view = await todos.get(uow, ACTOR, out.value.id)
    assert view.status == TodoStatus.DONE


async def test_undo_refused_for_a_deleted_to_do(uow: Uow, clock: FixedClock) -> None:
    await _set_channel(uow)
    todo_id = await _create_daily(uow)
    [occ] = await _occurrences(uow, todo_id)
    clock.set(clock.now() + timedelta(minutes=5))
    checked = await occurrences.complete_occurrence(uow, ACTOR, occ.id)
    await todos.delete(uow, ACTOR, todo_id)

    with pytest.raises(NotFound):
        await undo.undo(uow, ACTOR, checked.value.undo)


async def test_undo_refused_once_the_next_reminder_was_sent(uow: Uow, clock: FixedClock) -> None:
    await _set_channel(uow)
    clock.set(utc(7, 7))
    todo_id = await _create_daily(uow, times=("08:00", "08:30"))
    clock.set(utc(7, 8))
    await occurrences.claim_due(uow, clock.now())  # 08:00 reminder is up
    clock.set(utc(7, 8, 5))
    checked = await todos.complete(uow, ACTOR, todo_id)  # check off 08:00 at 08:05

    clock.set(utc(7, 8, 30))
    await occurrences.claim_due(uow, clock.now())  # 08:30 reminder goes out
    clock.set(utc(7, 8, 31))
    with pytest.raises(InvalidOperation, match=re.escape(undo.next_sent("stretch").message)):
        await undo.undo(uow, ACTOR, checked.value.undo)


async def test_undo_refused_once_the_early_follow_up_was_sent(uow: Uow, clock: FixedClock) -> None:
    await _set_channel(uow)
    clock.set(utc(7, 7))
    todo_id = await _create_daily(uow, times=("08:00", "08:30"))
    [occ] = await _occurrences(uow, todo_id)
    clock.set(utc(7, 7, 30))
    checked = await occurrences.complete_occurrence(uow, ACTOR, occ.id)  # follow-up 08:30

    clock.set(utc(7, 8, 30))
    await occurrences.claim_due(uow, clock.now())  # the follow-up is claimed
    with pytest.raises(InvalidOperation, match=re.escape(undo.next_sent("stretch").message)):
        await undo.undo(uow, ACTOR, checked.value.undo)


async def test_undo_refused_after_the_follow_up_was_edited(uow: Uow, clock: FixedClock) -> None:
    await _set_channel(uow)
    clock.set(utc(7, 7))
    todo_id = await _create_daily(uow)
    [occ] = await _occurrences(uow, todo_id)
    clock.set(utc(7, 7, 5))
    checked = await occurrences.complete_occurrence(uow, ACTOR, occ.id)

    await todos.edit(uow, ACTOR, todo_id, TodoPatch(rule=DailyRule(times=["09:30"])))
    with pytest.raises(InvalidOperation, match=re.escape(undo.edited("stretch").message)):
        await undo.undo(uow, ACTOR, checked.value.undo)


async def test_undo_refused_when_the_title_is_taken_again(uow: Uow) -> None:
    todo_id, _ = await _create_once(uow, title="milk")
    checked = await todos.complete(uow, ACTOR, todo_id)
    await todos.create_once(uow, ACTOR, title="Milk")

    with pytest.raises(NameTaken):
        await undo.undo(uow, ACTOR, checked.value.undo)
    view = await todos.get(uow, ACTOR, todo_id)
    assert view.status == TodoStatus.DONE


# --- 4. chains ----------------------------------------------------------------------------


async def test_chain_of_early_check_offs_undoes_latest_first(uow: Uow, clock: FixedClock) -> None:
    await _set_channel(uow)
    todo_id = await _create_daily(uow)
    [a] = await _occurrences(uow, todo_id)
    a_id, a_due = a.id, a.due_at

    checked_a = await occurrences.complete_occurrence(uow, ACTOR, a_id)
    token_a = checked_a.value.undo
    clock.advance(timedelta(minutes=1))
    b_id = token_a.followup_id
    assert b_id is not None
    checked_b = await occurrences.complete_occurrence(uow, ACTOR, b_id)
    token_b = checked_b.value.undo
    c_id = token_b.followup_id
    assert c_id is not None

    with pytest.raises(InvalidOperation, match=re.escape(undo.later_first("stretch").message)):
        await undo.undo(uow, ACTOR, token_a)

    clock.advance(timedelta(minutes=1))
    await undo.undo(uow, ACTOR, token_b)
    await undo.undo(uow, ACTOR, token_a)

    occs = {o.id: o for o in await _occurrences(uow, todo_id)}
    assert occs[a_id].status == OccurrenceStatus.PENDING
    assert occs[a_id].due_at == a_due
    assert occs[b_id].status == OccurrenceStatus.CANCELLED
    assert occs[c_id].status == OccurrenceStatus.CANCELLED
    pending = [o.id for o in occs.values() if o.status == OccurrenceStatus.PENDING]
    assert pending == [a_id]


# --- 5. subtasks --------------------------------------------------------------------------


async def test_subtask_deleted_after_check_off_is_skipped(uow: Uow, clock: FixedClock) -> None:
    await _set_channel(uow)
    clock.set(utc(7, 7))
    todo_id = await _create_daily(uow)
    out = await subtasks.add(uow, ACTOR, todo_id, ["a", "b"])
    a_id, b_id = [s.id for s in out.value.subtasks]
    clock.set(utc(7, 7, 1))
    await subtasks.toggle(uow, ACTOR, a_id)
    await subtasks.toggle(uow, ACTOR, b_id)
    [occ] = await _occurrences(uow, todo_id)
    clock.set(utc(7, 7, 2))
    checked = await occurrences.complete_occurrence(uow, ACTOR, occ.id)

    clock.set(utc(7, 7, 3))
    await subtasks.remove(uow, ACTOR, a_id)
    clock.set(utc(7, 7, 4))
    await undo.undo(uow, ACTOR, checked.value.undo)

    view = await todos.get(uow, ACTOR, todo_id)
    assert [(s.title, s.done, s.done_at) for s in view.subtasks] == [("b", True, utc(7, 7, 1))]


async def test_subtask_ticked_again_after_check_off_keeps_the_new_tick(
    uow: Uow, clock: FixedClock
) -> None:
    await _set_channel(uow)
    clock.set(utc(7, 7))
    todo_id = await _create_daily(uow)
    out = await subtasks.add(uow, ACTOR, todo_id, ["a"])
    [a_id] = [s.id for s in out.value.subtasks]
    clock.set(utc(7, 7, 1))
    await subtasks.toggle(uow, ACTOR, a_id)
    [occ] = await _occurrences(uow, todo_id)
    clock.set(utc(7, 7, 2))
    checked = await occurrences.complete_occurrence(uow, ACTOR, occ.id)

    clock.set(utc(7, 7, 3))
    await subtasks.toggle(uow, OTHER_ACTOR, a_id)  # the reset tick, ticked again by someone else
    clock.set(utc(7, 7, 4))
    await undo.undo(uow, ACTOR, checked.value.undo)

    view = await todos.get(uow, ACTOR, todo_id)
    [sub] = view.subtasks
    assert sub.done_at == utc(7, 7, 3)
    assert sub.done_by == OTHER
