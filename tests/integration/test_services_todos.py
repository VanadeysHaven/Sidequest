"""Service-level tests for to-dos: creation, visibility, completion, editing, validation."""

from datetime import UTC, datetime, time

import pytest
from sqlalchemy import select

from sidequest.core.enums import OccurrenceStatus, Scope, TodoStatus
from sidequest.core.errors import (
    Forbidden,
    InvalidOperation,
    LimitExceeded,
    NotFound,
    ReminderChannelNotSet,
)
from sidequest.core.recurrence import DailyRule
from sidequest.db.models import Occurrence
from sidequest.services import occurrences, settings, todos
from sidequest.services.actor import Actor
from sidequest.services.dto import DueInput, TodoPatch
from sidequest.services.effects import DeleteMessage
from sidequest.services.uow import Uow
from tests.support.clock import FixedClock

GUILD_A = 100
GUILD_B = 200
OWNER = 1
OTHER = 2
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


async def _set_channel(uow: Uow, guild_id: int = GUILD_A) -> None:
    await settings.set_reminder_channel(uow, member(MANAGER, guild_id, True), CHANNEL)


async def test_timed_once_todo_has_one_pending_occurrence_at_due_time(uow: Uow) -> None:
    await _set_channel(uow)
    out = await todos.create_once(
        uow,
        member(OWNER, GUILD_A),
        scope=Scope.SERVER,
        title="x",
        due=DueInput(time=time(10, 0)),
    )
    assert out.changed_schedule is True
    occs = await _occurrences(uow, out.value.id)
    assert [(o.status, o.due_at) for o in occs] == [(OccurrenceStatus.PENDING, utc(7, 10))]


async def test_untimed_once_todo_has_no_occurrences(uow: Uow) -> None:
    out = await todos.create_once(uow, member(OWNER, GUILD_A), scope=Scope.SERVER, title="x")
    assert out.changed_schedule is False
    assert await _occurrences(uow, out.value.id) == []


async def test_server_timed_once_without_reminder_channel_is_rejected(uow: Uow) -> None:
    with pytest.raises(ReminderChannelNotSet):
        await todos.create_once(
            uow,
            member(OWNER, GUILD_A),
            scope=Scope.SERVER,
            title="x",
            due=DueInput(time=time(10, 0)),
        )


async def test_server_recurring_without_reminder_channel_is_rejected(uow: Uow) -> None:
    with pytest.raises(ReminderChannelNotSet):
        await todos.create_recurring(
            uow,
            member(OWNER, GUILD_A),
            scope=Scope.SERVER,
            title="x",
            rule=DailyRule(times=["08:00"]),
        )


async def test_personal_todo_hidden_from_others_but_seen_in_any_context(uow: Uow) -> None:
    out = await todos.create_once(uow, member(OWNER, GUILD_A), scope=Scope.PERSONAL, title="mine")
    tid = out.value.id
    with pytest.raises(NotFound):
        await todos.get(uow, member(OTHER, GUILD_A), tid)
    assert (await todos.get(uow, member(OWNER, GUILD_B), tid)).id == tid
    assert (await todos.get(uow, member(OWNER, None), tid)).id == tid


async def test_server_todo_is_not_visible_from_another_guild(uow: Uow) -> None:
    out = await todos.create_once(uow, member(OWNER, GUILD_A), scope=Scope.SERVER, title="x")
    tid = out.value.id
    with pytest.raises(NotFound):
        await todos.get(uow, member(OWNER, GUILD_B), tid)
    assert (await todos.get(uow, member(OWNER, GUILD_A), tid)).id == tid


async def test_completing_pending_once_todo_early_closes_occurrence(uow: Uow) -> None:
    await _set_channel(uow)
    actor = member(OWNER, GUILD_A)
    out = await todos.create_once(
        uow, actor, scope=Scope.SERVER, title="x", due=DueInput(time=time(10, 0))
    )
    tid = out.value.id
    done = await todos.complete(uow, actor, tid)
    assert done.effects == []
    assert done.value.status == TodoStatus.DONE
    occs = await _occurrences(uow, tid)
    assert [o.status for o in occs] == [OccurrenceStatus.DONE]


async def test_edit_time_of_sent_reminder_cancels_it_and_schedules_new_one(
    uow: Uow, clock: FixedClock
) -> None:
    await _set_channel(uow)
    actor = member(OWNER, GUILD_A)
    out = await todos.create_once(
        uow, actor, scope=Scope.SERVER, title="x", due=DueInput(time=time(10, 0))
    )
    tid = out.value.id
    clock.set(utc(7, 10))
    reminders = await occurrences.claim_due(uow, clock.now())
    occ_id = next(r.occurrence.id for r in reminders if r.todo.id == tid)
    await occurrences.attach_message(uow, occ_id, CHANNEL, 777)

    edited = await todos.edit(uow, actor, tid, TodoPatch(due=DueInput(time=time(11, 0))))
    assert edited.effects == [DeleteMessage(channel_id=CHANNEL, message_id=777)]
    assert edited.changed_schedule is True
    occs = await _occurrences(uow, tid)
    old = next(o for o in occs if o.id == occ_id)
    assert old.status == OccurrenceStatus.CANCELLED
    pending = [o for o in occs if o.status == OccurrenceStatus.PENDING]
    assert [o.due_at for o in pending] == [utc(7, 11)]


async def test_delete_with_sent_reminder_cancels_and_deletes_message(
    uow: Uow, clock: FixedClock
) -> None:
    await _set_channel(uow)
    actor = member(OWNER, GUILD_A)
    out = await todos.create_once(
        uow, actor, scope=Scope.SERVER, title="x", due=DueInput(time=time(10, 0))
    )
    tid = out.value.id
    clock.set(utc(7, 10))
    reminders = await occurrences.claim_due(uow, clock.now())
    occ_id = next(r.occurrence.id for r in reminders if r.todo.id == tid)
    await occurrences.attach_message(uow, occ_id, CHANNEL, 888)

    deleted = await todos.delete(uow, actor, tid)
    assert deleted.effects == [DeleteMessage(channel_id=CHANNEL, message_id=888)]
    assert deleted.value.status == TodoStatus.CANCELLED
    with pytest.raises(NotFound):
        await todos.get(uow, actor, tid)


async def test_non_creator_cannot_edit_but_may_complete(uow: Uow) -> None:
    await _set_channel(uow)
    out = await todos.create_once(uow, member(OWNER, GUILD_A), scope=Scope.SERVER, title="x")
    tid = out.value.id
    other = member(OTHER, GUILD_A)
    with pytest.raises(Forbidden):
        await todos.edit(uow, other, tid, TodoPatch(title="renamed"))
    done = await todos.complete(uow, other, tid)
    assert done.value.status == TodoStatus.DONE


async def test_title_over_200_characters_is_rejected(uow: Uow) -> None:
    with pytest.raises(LimitExceeded):
        await todos.create_once(uow, member(OWNER, GUILD_A), scope=Scope.PERSONAL, title="a" * 201)


async def test_details_over_4000_characters_are_rejected(uow: Uow) -> None:
    with pytest.raises(LimitExceeded):
        await todos.create_once(
            uow, member(OWNER, GUILD_A), scope=Scope.PERSONAL, title="x", details="d" * 4001
        )


async def test_more_than_10_assignees_are_rejected(uow: Uow) -> None:
    with pytest.raises(LimitExceeded):
        await todos.create_once(
            uow,
            member(OWNER, GUILD_A),
            scope=Scope.SERVER,
            title="x",
            assignee_ids=list(range(1, 12)),
        )


async def test_assignees_on_personal_todo_are_rejected_on_create(uow: Uow) -> None:
    with pytest.raises(InvalidOperation):
        await todos.create_once(
            uow,
            member(OWNER, GUILD_A),
            scope=Scope.PERSONAL,
            title="x",
            assignee_ids=[OTHER],
        )


async def test_assignees_on_personal_todo_are_rejected_by_set_assignees(uow: Uow) -> None:
    actor = member(OWNER, GUILD_A)
    out = await todos.create_once(uow, actor, scope=Scope.PERSONAL, title="x")
    with pytest.raises(InvalidOperation):
        await todos.set_assignees(uow, actor, out.value.id, [OTHER])


async def test_new_todo_timezone_follows_user_setting_and_override_wins(uow: Uow) -> None:
    actor = member(OWNER, GUILD_A)
    default = await todos.create_once(uow, actor, scope=Scope.PERSONAL, title="a")
    assert default.value.timezone == "UTC"
    assert await settings.get_user_timezone(uow, OWNER) == ("UTC", True)

    assert await settings.set_user_timezone(uow, actor, "europe/amsterdam") == "Europe/Amsterdam"
    own = await todos.create_once(uow, actor, scope=Scope.PERSONAL, title="b")
    assert own.value.timezone == "Europe/Amsterdam"

    override = await todos.create_once(
        uow, actor, scope=Scope.PERSONAL, title="c", timezone="Asia/Tokyo"
    )
    assert override.value.timezone == "Asia/Tokyo"


async def test_tz_hint_is_shown_exactly_once(uow: Uow) -> None:
    assert await settings.consume_tz_hint(uow, OWNER) is True
    assert await settings.consume_tz_hint(uow, OWNER) is False


async def test_edit_keeps_details_unless_passed_and_none_clears_them(uow: Uow) -> None:
    actor = member(OWNER, GUILD_A)
    out = await todos.create_once(uow, actor, scope=Scope.PERSONAL, title="x", details="notes")
    tid = out.value.id

    renamed = await todos.edit(uow, actor, tid, TodoPatch(title="y"))
    assert renamed.value.title == "y"
    assert renamed.value.details == "notes"

    cleared = await todos.edit(uow, actor, tid, TodoPatch(details=None))
    assert cleared.value.details is None
