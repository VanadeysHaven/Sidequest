"""Service-level tests for subtasks and the checklist reset of repeating to-dos."""

from datetime import UTC, datetime

import pytest

from sidequest.core.enums import TodoStatus
from sidequest.core.errors import InvalidOperation, LimitExceeded
from sidequest.core.recurrence import DailyRule
from sidequest.services import settings, subtasks, todos
from sidequest.services.actor import Actor
from sidequest.services.uow import Uow

GUILD_A = 100
OWNER = 1
MANAGER = 9
CHANNEL = 555


def member(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, day, hour, minute, tzinfo=UTC)


async def _recurring_todo(uow: Uow) -> int:
    await settings.set_reminder_channel(uow, member(MANAGER, GUILD_A, True), CHANNEL)
    out = await todos.create_recurring(
        uow,
        member(OWNER, GUILD_A),
        title="water plants",
        rule=DailyRule(times=["08:00"]),
    )
    return out.value.id


async def test_completing_recurring_todo_early_resets_subtasks_and_schedules_next(
    uow: Uow,
) -> None:
    actor = member(OWNER, GUILD_A)
    tid = await _recurring_todo(uow)
    added = await subtasks.add(uow, actor, tid, ["soil", "water"])
    first_id, second_id = (s.id for s in added.value.subtasks)
    ticked = await subtasks.toggle(uow, actor, first_id)
    assert [s.done for s in ticked.value.subtasks] == [True, False]
    first_due = ticked.value.next_due_at
    assert first_due == utc(8, 8)

    done = await todos.complete(uow, actor, tid)
    assert done.changed_schedule is True
    assert done.value.todo.status == TodoStatus.OPEN
    assert done.value.todo.next_due_at == utc(9, 8)
    assert done.value.todo.next_due_at > first_due
    assert [s.done for s in done.value.todo.subtasks] == [False, False]
    assert {s.id for s in done.value.todo.subtasks} == {first_id, second_id}


async def test_subtask_list_is_capped_at_50(uow: Uow) -> None:
    actor = member(OWNER, GUILD_A)
    out = await todos.create_once(uow, actor, title="long list")
    tid = out.value.id
    await subtasks.add(uow, actor, tid, [f"step {i}" for i in range(50)])
    with pytest.raises(LimitExceeded):
        await subtasks.add(uow, actor, tid, ["one too many"])


async def test_subtask_title_over_100_characters_is_rejected(uow: Uow) -> None:
    actor = member(OWNER, GUILD_A)
    out = await todos.create_once(uow, actor, title="x")
    with pytest.raises(LimitExceeded):
        await subtasks.add(uow, actor, out.value.id, ["s" * 101])


async def test_adding_only_blank_subtask_titles_is_invalid(uow: Uow) -> None:
    actor = member(OWNER, GUILD_A)
    out = await todos.create_once(uow, actor, title="x")
    with pytest.raises(InvalidOperation):
        await subtasks.add(uow, actor, out.value.id, ["   "])
