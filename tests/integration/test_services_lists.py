"""Service-level tests for server lists: create, rename, delete, the fallback list, collaborators,
transfer, and each user's default list."""

import asyncio
from datetime import UTC, datetime, time

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sidequest.core.errors import Forbidden, InvalidOperation, LimitExceeded, NameTaken, NotFound
from sidequest.db.models import TodoList
from sidequest.services import lists, occurrences, settings, todos
from sidequest.services.actor import Actor
from sidequest.services.dto import DueInput, ListDeleteResult
from sidequest.services.effects import DeleteMessage
from sidequest.services.uow import Uow
from tests.integration.conftest import START
from tests.support.clock import FixedClock

GUILD_A = 100
GUILD_B = 200
OWNER = 1
COLLAB = 2
OTHER = 3
MANAGER = 9
CHANNEL = 555
MESSAGE = 777
TEN = datetime(2030, 1, 7, 10, 0, tzinfo=UTC)


def member(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


async def _set_channel(uow: Uow, guild_id: int = GUILD_A) -> None:
    await settings.set_reminder_channel(uow, member(MANAGER, guild_id, True), CHANNEL)


async def _send_reminder(
    uow: Uow, clock: FixedClock, actor: Actor, list_id: int, title: str
) -> int:
    """A timed to-do at 10:00 whose reminder was posted as MESSAGE. Returns the to-do id."""
    out = await todos.create_once(
        uow, actor, list_id=list_id, title=title, due=DueInput(time=time(10, 0))
    )
    clock.set(TEN)
    reminders = await occurrences.claim_due(uow, clock.now())
    occurrence_id = next(r.occurrence.id for r in reminders if r.todo.id == out.value.id)
    await occurrences.attach_message(uow, occurrence_id, CHANNEL, MESSAGE)
    return out.value.id


# --- create ------------------------------------------------------------------------------


async def test_create_makes_the_caller_owner(uow: Uow) -> None:
    view = await lists.create(uow, member(OWNER, GUILD_A), "Groceries")

    assert view.owner_id == OWNER
    assert view.collaborator_ids == ()
    assert view.is_fallback is False
    assert view.can_manage and view.can_rename and view.can_add


async def test_duplicate_list_name_in_any_case_is_taken(uow: Uow) -> None:
    await lists.create(uow, member(OWNER, GUILD_A), "Groceries")

    with pytest.raises(NameTaken, match="groceries"):
        await lists.create(uow, member(COLLAB, GUILD_A), "groceries")


async def test_same_list_name_is_fine_on_another_server(uow: Uow) -> None:
    here = await lists.create(uow, member(OWNER, GUILD_A), "Groceries")
    there = await lists.create(uow, member(OWNER, GUILD_B), "Groceries")

    assert here.guild_id == GUILD_A
    assert there.guild_id == GUILD_B
    assert here.id != there.id


async def test_server_holds_at_most_25_lists_counting_the_fallback(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    for i in range(24):
        await lists.create(uow, owner, f"List {i}")
    assert len(await lists.list_lists(uow, owner)) == 25

    with pytest.raises(LimitExceeded):
        await lists.create(uow, owner, "One too many")


# --- rename ------------------------------------------------------------------------------


async def test_owner_can_rename_their_list(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")

    view = await lists.rename(uow, owner, lst.id, "Errands")

    assert view.name == "Errands"


async def test_manage_server_can_rename_a_list(uow: Uow) -> None:
    lst = await lists.create(uow, member(OWNER, GUILD_A), "Work")

    view = await lists.rename(uow, member(MANAGER, GUILD_A, True), lst.id, "Errands")

    assert view.name == "Errands"


async def test_collaborator_and_other_member_cannot_rename(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")
    await lists.set_collaborators(uow, owner, lst.id, [COLLAB])

    with pytest.raises(Forbidden):
        await lists.rename(uow, member(COLLAB, GUILD_A), lst.id, "Errands")
    with pytest.raises(Forbidden):
        await lists.rename(uow, member(OTHER, GUILD_A), lst.id, "Errands")


async def test_fallback_is_renamed_by_manage_server_only(uow: Uow) -> None:
    fallback = await lists.ensure_guild(uow, GUILD_A)

    view = await lists.rename(uow, member(MANAGER, GUILD_A, True), fallback, "Inbox")

    assert view.name == "Inbox"
    assert view.is_fallback is True
    with pytest.raises(Forbidden):
        await lists.rename(uow, member(OTHER, GUILD_A), fallback, "Mine")
    with pytest.raises(Forbidden):
        await lists.rename(uow, member(OWNER, GUILD_A), fallback, "Mine")


async def test_renaming_another_servers_list_is_not_found(uow: Uow) -> None:
    lst = await lists.create(uow, member(OWNER, GUILD_A), "Work")

    with pytest.raises(NotFound):
        await lists.rename(uow, member(OWNER, GUILD_B), lst.id, "Errands")


# --- delete ------------------------------------------------------------------------------


async def test_fallback_cannot_be_deleted_even_by_manage_server(uow: Uow) -> None:
    fallback = await lists.ensure_guild(uow, GUILD_A)

    with pytest.raises(InvalidOperation):
        await lists.delete(uow, member(MANAGER, GUILD_A, True), fallback, move_to=None)


async def test_fallback_has_no_collaborators_and_no_owner_to_transfer(uow: Uow) -> None:
    fallback = await lists.ensure_guild(uow, GUILD_A)
    manager = member(MANAGER, GUILD_A, True)

    with pytest.raises(InvalidOperation):
        await lists.set_collaborators(uow, manager, fallback, [COLLAB])
    with pytest.raises(InvalidOperation):
        await lists.transfer(uow, manager, fallback, COLLAB)


async def test_deleting_an_empty_list_removes_it(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")

    out = await lists.delete(uow, owner, lst.id, move_to=None)

    assert out.value == ListDeleteResult(name="Work", deleted=0, moved=0, moved_to=None)
    assert out.effects == []
    assert out.changed_schedule is False
    assert lst.id not in [view.id for view in await lists.list_lists(uow, owner)]


async def test_deleting_a_list_cancels_its_todos_and_their_reminders(
    uow: Uow, clock: FixedClock
) -> None:
    owner = member(OWNER, GUILD_A)
    await _set_channel(uow)
    lst = await lists.create(uow, owner, "Work")
    sent_id = await _send_reminder(uow, clock, owner, lst.id, "Sent one")
    untimed = await todos.create_once(uow, owner, list_id=lst.id, title="Untimed")
    pending = await todos.create_once(
        uow, owner, list_id=lst.id, title="Pending", due=DueInput(time=time(11, 0))
    )

    out = await lists.delete(uow, owner, lst.id, move_to=None)

    assert out.value == ListDeleteResult(name="Work", deleted=3, moved=0, moved_to=None)
    assert out.effects == [DeleteMessage(channel_id=CHANNEL, message_id=MESSAGE)]
    assert out.changed_schedule is True
    for todo_id in (sent_id, untimed.value.id, pending.value.id):
        with pytest.raises(NotFound):
            await todos.get(uow, owner, todo_id)


async def test_deleting_with_only_a_sent_reminder_leaves_the_schedule_alone(
    uow: Uow, clock: FixedClock
) -> None:
    owner = member(OWNER, GUILD_A)
    await _set_channel(uow)
    lst = await lists.create(uow, owner, "Work")
    await _send_reminder(uow, clock, owner, lst.id, "Sent one")

    out = await lists.delete(uow, owner, lst.id, move_to=None)

    assert out.value.deleted == 1
    assert out.effects == [DeleteMessage(channel_id=CHANNEL, message_id=MESSAGE)]
    assert out.changed_schedule is False


async def test_move_delete_moves_the_open_todos_to_the_target(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    source = await lists.create(uow, owner, "Source")
    target = await lists.create(uow, owner, "Target")
    first = await todos.create_once(uow, owner, list_id=source.id, title="First")
    second = await todos.create_once(uow, owner, list_id=source.id, title="Second")

    out = await lists.delete(uow, owner, source.id, move_to=target.id)

    assert out.value == ListDeleteResult(name="Source", deleted=0, moved=2, moved_to="Target")
    assert out.effects == []
    for todo_id in (first.value.id, second.value.id):
        assert (await todos.get(uow, owner, todo_id)).list_id == target.id
    assert source.id not in [view.id for view in await lists.list_lists(uow, owner)]


async def test_move_delete_is_refused_on_a_title_clash_and_changes_nothing(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    source = await lists.create(uow, owner, "Source")
    target = await lists.create(uow, owner, "Target")
    moving = await todos.create_once(uow, owner, list_id=source.id, title="Milk")
    await todos.create_once(uow, owner, list_id=target.id, title="milk")

    with pytest.raises(NameTaken, match="Milk"):
        await lists.delete(uow, owner, source.id, move_to=target.id)

    assert source.id in [view.id for view in await lists.list_lists(uow, owner)]
    assert (await todos.get(uow, owner, moving.value.id)).list_id == source.id


async def test_move_delete_needs_add_rights_on_the_target(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    source = await lists.create(uow, owner, "Source")
    target = await lists.create(uow, member(OTHER, GUILD_A), "Theirs")
    await todos.create_once(uow, owner, list_id=source.id, title="Milk")

    with pytest.raises(Forbidden):
        await lists.delete(uow, owner, source.id, move_to=target.id)


async def test_only_owner_or_manage_server_can_delete_a_list(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")
    await lists.set_collaborators(uow, owner, lst.id, [COLLAB])

    with pytest.raises(Forbidden):
        await lists.delete(uow, member(COLLAB, GUILD_A), lst.id, move_to=None)
    with pytest.raises(Forbidden):
        await lists.delete(uow, member(OTHER, GUILD_A), lst.id, move_to=None)


async def test_deleting_a_list_clears_users_defaults_for_it(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")
    await settings.set_default_list(uow, owner, lst.id)

    await lists.delete(uow, owner, lst.id, move_to=None)

    view = await settings.get_default_list(uow, owner)
    assert view.is_fallback is True
    assert await settings.own_default_list_id(uow, owner) is None


# --- ensure_guild ------------------------------------------------------------------------


async def test_ensure_guild_is_idempotent(uow: Uow) -> None:
    first = await lists.ensure_guild(uow, GUILD_A)
    second = await lists.ensure_guild(uow, GUILD_A)

    assert first == second
    all_lists = await lists.list_lists(uow, member(OWNER, GUILD_A))
    assert [view.id for view in all_lists] == [first]
    assert all_lists[0].name == "Default List"
    assert all_lists[0].owner_id is None


async def test_concurrent_ensure_guild_creates_one_fallback(
    committed_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async def fallback_id() -> int:
        async with committed_sessions() as session:
            uow = Uow(session, FixedClock(START))
            list_id = await lists.ensure_guild(uow, GUILD_A)
            await uow.session.commit()
            return list_id

    first, second = await asyncio.gather(fallback_id(), fallback_id())

    assert first == second
    async with committed_sessions() as session:
        count = await session.scalar(
            select(func.count()).select_from(TodoList).where(TodoList.guild_id == GUILD_A)
        )
    assert count == 1


# --- collaborators -----------------------------------------------------------------------


async def test_owner_sets_collaborators(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")

    view = await lists.set_collaborators(uow, owner, lst.id, [COLLAB, OTHER])

    assert view.collaborator_ids == (COLLAB, OTHER)


async def test_manage_server_sets_collaborators(uow: Uow) -> None:
    lst = await lists.create(uow, member(OWNER, GUILD_A), "Work")

    view = await lists.set_collaborators(uow, member(MANAGER, GUILD_A, True), lst.id, [COLLAB])

    assert view.collaborator_ids == (COLLAB,)


async def test_collaborator_and_other_member_cannot_set_collaborators(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")
    await lists.set_collaborators(uow, owner, lst.id, [COLLAB])

    with pytest.raises(Forbidden):
        await lists.set_collaborators(uow, member(COLLAB, GUILD_A), lst.id, [OTHER])
    with pytest.raises(Forbidden):
        await lists.set_collaborators(uow, member(OTHER, GUILD_A), lst.id, [OTHER])


async def test_owner_id_in_the_set_is_dropped(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")

    view = await lists.set_collaborators(uow, owner, lst.id, [OWNER, COLLAB])

    assert view.owner_id == OWNER
    assert view.collaborator_ids == (COLLAB,)


async def test_more_than_25_collaborators_is_refused_and_changes_nothing(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")
    await lists.set_collaborators(uow, owner, lst.id, [COLLAB])

    with pytest.raises(LimitExceeded):
        await lists.set_collaborators(uow, owner, lst.id, [1000 + i for i in range(26)])

    assert (await lists.get(uow, owner, lst.id)).collaborator_ids == (COLLAB,)


async def test_replacing_collaborators_removes_the_ones_left_out(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")
    await lists.set_collaborators(uow, owner, lst.id, [COLLAB, OTHER])

    view = await lists.set_collaborators(uow, owner, lst.id, [OTHER])

    assert view.collaborator_ids == (OTHER,)


# --- transfer ----------------------------------------------------------------------------


async def test_owner_transfers_the_list(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")
    await lists.set_collaborators(uow, owner, lst.id, [COLLAB, OTHER])

    view = await lists.transfer(uow, owner, lst.id, COLLAB)

    assert view.owner_id == COLLAB
    assert COLLAB not in view.collaborator_ids
    assert view.collaborator_ids == (OWNER, OTHER)


async def test_manage_server_transfers_the_list(uow: Uow) -> None:
    lst = await lists.create(uow, member(OWNER, GUILD_A), "Work")

    view = await lists.transfer(uow, member(MANAGER, GUILD_A, True), lst.id, OTHER)

    assert view.owner_id == OTHER
    assert OTHER not in view.collaborator_ids
    assert OWNER in view.collaborator_ids


async def test_transfer_to_the_current_owner_is_invalid(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")

    with pytest.raises(InvalidOperation):
        await lists.transfer(uow, owner, lst.id, OWNER)


async def test_transfer_is_refused_when_the_old_owner_would_exceed_the_limit(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")
    full = [1000 + i for i in range(25)]
    await lists.set_collaborators(uow, owner, lst.id, full)

    with pytest.raises(LimitExceeded):
        await lists.transfer(uow, owner, lst.id, 2000)

    view = await lists.get(uow, owner, lst.id)
    assert view.owner_id == OWNER
    assert view.collaborator_ids == tuple(sorted(full))


async def test_old_owner_keeps_adding_but_cannot_rename_after_transfer(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")
    await lists.transfer(uow, owner, lst.id, COLLAB)

    out = await todos.create_once(uow, owner, list_id=lst.id, title="Still mine")

    assert out.value.list_id == lst.id
    with pytest.raises(Forbidden):
        await lists.rename(uow, owner, lst.id, "Renamed")


# --- default list (settings) -------------------------------------------------------------


async def test_default_list_can_be_set_shown_and_cleared(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    fallback = await lists.ensure_guild(uow, GUILD_A)
    lst = await lists.create(uow, owner, "Work")
    assert await settings.own_default_list_id(uow, owner) is None

    shown = await settings.get_default_list(uow, owner)
    assert shown.id == fallback
    assert shown.is_fallback is True
    assert shown.is_my_default is True

    chosen = await settings.set_default_list(uow, owner, lst.id)
    assert chosen.id == lst.id
    assert chosen.is_my_default is True
    assert chosen.is_fallback is False
    assert (await settings.get_default_list(uow, owner)).id == lst.id
    assert await settings.own_default_list_id(uow, owner) == lst.id

    cleared = await settings.clear_default_list(uow, owner)
    assert cleared.id == fallback
    assert cleared.is_fallback is True
    assert await settings.own_default_list_id(uow, owner) is None


async def test_default_list_from_another_server_is_not_found(uow: Uow) -> None:
    elsewhere = await lists.create(uow, member(OWNER, GUILD_B), "Elsewhere")

    with pytest.raises(NotFound):
        await settings.set_default_list(uow, member(OWNER, GUILD_A), elsewhere.id)


async def test_cannot_pick_a_list_you_cannot_add_to(uow: Uow) -> None:
    lst = await lists.create(uow, member(OWNER, GUILD_A), "Work")
    other = member(OTHER, GUILD_A)

    with pytest.raises(Forbidden, match="Work"):
        await settings.set_default_list(uow, other, lst.id)
    assert await settings.own_default_list_id(uow, other) is None


async def test_losing_rights_on_your_default_blocks_adding_without_a_list(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await lists.create(uow, owner, "Work")
    await lists.set_collaborators(uow, owner, lst.id, [COLLAB])
    await settings.set_default_list(uow, member(COLLAB, GUILD_A), lst.id)
    await lists.set_collaborators(uow, owner, lst.id, [])

    with pytest.raises(Forbidden, match="Work"):
        await todos.create_once(uow, member(COLLAB, GUILD_A), title="Milk")
