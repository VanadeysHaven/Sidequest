"""Permissions on server lists in practice, and the to-do cases that depend on which list a
to-do is on: default lists, titles per list, moving, and the list-scoped queries."""

from datetime import UTC, datetime, time

import pytest

from sidequest.core.errors import Forbidden, InvalidOperation, NameTaken, NotFound
from sidequest.services import lists, occurrences, settings, subtasks, todos
from sidequest.services.actor import Actor
from sidequest.services.dto import DueInput, ListView, TodoPatch, TodoView
from sidequest.services.uow import Uow

GUILD_A = 100
GUILD_B = 200
OWNER = 1
COLLAB = 2
OTHER = 3
MANAGER = 9
CHANNEL = 555


def member(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


async def _set_channel(uow: Uow, guild_id: int = GUILD_A) -> None:
    await settings.set_reminder_channel(uow, member(MANAGER, guild_id, True), CHANNEL)


async def _owned_list(uow: Uow, name: str = "Work") -> ListView:
    return await lists.create(uow, member(OWNER, GUILD_A), name)


async def _todo(
    uow: Uow, actor: Actor, list_id: int | None = None, title: str = "Milk", timed: bool = False
) -> TodoView:
    """A to-do for `actor`; timed ones get a reminder at 10:00 (the channel is set first)."""
    if timed:
        await _set_channel(uow)
        due = DueInput(time=time(10, 0))
    else:
        due = DueInput()
    out = await todos.create_once(uow, actor, list_id=list_id, title=title, due=due)
    return out.value


# --- permissions on an owned list --------------------------------------------------------


async def test_non_collaborator_cannot_add_to_an_owned_list(uow: Uow) -> None:
    lst = await _owned_list(uow)

    with pytest.raises(Forbidden, match="Work"):
        await todos.create_once(uow, member(OTHER, GUILD_A), list_id=lst.id, title="Milk")


async def test_non_collaborator_cannot_edit_an_owned_todo(uow: Uow) -> None:
    lst = await _owned_list(uow)
    todo = await _todo(uow, member(OWNER, GUILD_A), lst.id)
    other = member(OTHER, GUILD_A)

    with pytest.raises(Forbidden):
        await todos.edit(uow, other, todo.id, TodoPatch(title="Eggs"))
    with pytest.raises(Forbidden):
        await todos.set_details(uow, other, todo.id, "Oat")
    with pytest.raises(Forbidden):
        await todos.set_assignees(uow, other, todo.id, [OTHER])

    assert (await todos.get(uow, other, todo.id)).title == "Milk"


async def test_non_collaborator_cannot_change_subtasks(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    todo = await _todo(uow, owner, lst.id)
    with_subtasks = await subtasks.add(uow, owner, todo.id, ["a", "b"])
    a_id = next(s.id for s in with_subtasks.value.subtasks if s.title == "a")
    other = member(OTHER, GUILD_A)

    with pytest.raises(Forbidden):
        await subtasks.add(uow, other, todo.id, ["c"])
    with pytest.raises(Forbidden):
        await subtasks.remove(uow, other, a_id)
    with pytest.raises(Forbidden):
        await subtasks.set_done(uow, other, todo.id, {a_id})


async def test_non_collaborator_cannot_complete_or_delete_an_owned_todo(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    todo = await _todo(uow, owner, lst.id, timed=True)
    assert todo.pending_occurrence_id is not None
    other = member(OTHER, GUILD_A)

    with pytest.raises(Forbidden):
        await todos.complete(uow, other, todo.id)
    with pytest.raises(Forbidden):
        await occurrences.complete_occurrence(uow, other, todo.pending_occurrence_id)
    with pytest.raises(Forbidden):
        await todos.delete(uow, other, todo.id)


async def test_creator_removed_as_collaborator_cannot_edit_their_todo(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    await lists.set_collaborators(uow, owner, lst.id, [COLLAB])
    creator = member(COLLAB, GUILD_A)
    todo = await _todo(uow, creator, lst.id)
    assert todo.owner_id == COLLAB
    await lists.set_collaborators(uow, owner, lst.id, [])

    with pytest.raises(Forbidden):
        await todos.edit(uow, creator, todo.id, TodoPatch(title="Eggs"))


async def test_assignee_who_is_not_a_collaborator_cannot_complete(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    todo = await _todo(uow, owner, lst.id)

    assigned = await todos.set_assignees(uow, owner, todo.id, [OWNER, OTHER])
    assert assigned.value.assignee_ids == (OWNER, OTHER)

    with pytest.raises(Forbidden):
        await todos.complete(uow, member(OTHER, GUILD_A), todo.id)


async def test_manage_server_may_do_everything_on_an_owned_list(uow: Uow) -> None:
    manager = member(MANAGER, GUILD_A, True)
    lst = await _owned_list(uow)

    timed = await _todo(uow, manager, lst.id, title="Timed", timed=True)
    assert timed.pending_occurrence_id is not None
    await occurrences.complete_occurrence(uow, manager, timed.pending_occurrence_id)

    todo = await _todo(uow, manager, lst.id, title="Bread")
    edited = await todos.edit(uow, manager, todo.id, TodoPatch(title="Rye bread"))
    assert edited.value.title == "Rye bread"
    await todos.set_details(uow, manager, todo.id, "Two loaves")
    await todos.set_assignees(uow, manager, todo.id, [OTHER])
    added = await subtasks.add(uow, manager, todo.id, ["slice"])
    slice_id = added.value.subtasks[0].id
    await subtasks.set_done(uow, manager, todo.id, {slice_id})
    await subtasks.remove(uow, manager, slice_id)
    await todos.complete(uow, manager, todo.id)

    doomed = await _todo(uow, manager, lst.id, title="Doomed")
    await todos.delete(uow, manager, doomed.id)


async def test_can_flags_follow_collaboration(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    await lists.set_collaborators(uow, owner, lst.id, [COLLAB])
    todo = await _todo(uow, owner, lst.id)

    outsider = await todos.get(uow, member(OTHER, GUILD_A), todo.id)
    assert outsider.can_edit is False
    assert outsider.can_complete is False

    collaborator = await todos.get(uow, member(COLLAB, GUILD_A), todo.id)
    assert collaborator.can_edit is True
    assert collaborator.can_complete is True


# --- the fallback list -------------------------------------------------------------------


async def test_on_the_fallback_any_member_may_do_everything(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    other = member(OTHER, GUILD_A)
    fallback = await lists.ensure_guild(uow, GUILD_A)

    timed = await _todo(uow, owner, None, title="Bins", timed=True)
    assert timed.list_id == fallback
    assert timed.pending_occurrence_id is not None

    edited = await todos.edit(uow, other, timed.id, TodoPatch(title="Bin day"))
    assert edited.value.title == "Bin day"
    await todos.set_details(uow, other, timed.id, "Blue bin")
    await todos.set_assignees(uow, other, timed.id, [OTHER])
    added = await subtasks.add(uow, other, timed.id, ["lid"])
    lid_id = added.value.subtasks[0].id
    await subtasks.set_done(uow, other, timed.id, {lid_id})
    await subtasks.remove(uow, other, lid_id)
    await occurrences.complete_occurrence(uow, other, timed.pending_occurrence_id)

    milk = await _todo(uow, owner, None, title="Milk")
    await todos.complete(uow, other, milk.id)

    eggs = await _todo(uow, other, None, title="Eggs")
    await todos.delete(uow, owner, eggs.id)


# --- to-dos and their lists --------------------------------------------------------------


async def test_create_without_a_list_uses_the_users_default(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    await settings.set_default_list(uow, owner, lst.id)

    todo = await _todo(uow, owner, None, title="Milk")

    assert todo.list_id == lst.id


async def test_create_without_a_list_falls_back_to_the_server_default(uow: Uow) -> None:
    fallback = await lists.ensure_guild(uow, GUILD_A)

    todo = await _todo(uow, member(OTHER, GUILD_A), None, title="Milk")

    assert todo.list_id == fallback
    assert todo.list_name == "Default List"


async def test_create_on_another_servers_list_is_not_found(uow: Uow) -> None:
    elsewhere = await lists.create(uow, member(OWNER, GUILD_B), "Elsewhere")

    with pytest.raises(NotFound):
        await todos.create_once(uow, member(OWNER, GUILD_A), list_id=elsewhere.id, title="Milk")


async def test_open_title_must_be_unique_on_a_list_in_any_case(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    await _todo(uow, owner, None, title="Milk")

    with pytest.raises(NameTaken, match="milk"):
        await _todo(uow, owner, None, title="milk")


async def test_same_title_is_allowed_once_the_first_is_done(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    first = await _todo(uow, owner, None, title="Milk")
    await todos.complete(uow, owner, first.id)

    again = await _todo(uow, owner, None, title="Milk")

    assert again.id != first.id


async def test_same_title_is_allowed_on_another_list(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    await _todo(uow, owner, None, title="Milk")

    other = await _todo(uow, owner, lst.id, title="Milk")

    assert other.list_id == lst.id


async def test_editing_a_title_into_a_clash_is_refused(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    await _todo(uow, owner, None, title="Milk")
    bread = await _todo(uow, owner, None, title="Bread")

    with pytest.raises(NameTaken, match="MILK"):
        await todos.edit(uow, owner, bread.id, TodoPatch(title="MILK"))


async def test_move_needs_add_rights_on_the_target(uow: Uow) -> None:
    lst = await _owned_list(uow)
    other = member(OTHER, GUILD_A)
    todo = await _todo(uow, other, None, title="Milk")

    with pytest.raises(Forbidden, match="Work"):
        await todos.move(uow, other, todo.id, lst.id)


async def test_move_is_refused_on_a_title_clash(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    await _todo(uow, owner, lst.id, title="Milk")
    todo = await _todo(uow, owner, None, title="milk")

    with pytest.raises(NameTaken, match="milk"):
        await todos.move(uow, owner, todo.id, lst.id)


async def test_move_to_the_same_list_is_invalid(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    fallback = await lists.ensure_guild(uow, GUILD_A)
    todo = await _todo(uow, owner, None, title="Milk")

    with pytest.raises(InvalidOperation):
        await todos.move(uow, owner, todo.id, fallback)


async def test_move_to_another_servers_list_is_not_found(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    elsewhere = await lists.create(uow, member(OWNER, GUILD_B), "Elsewhere")
    todo = await _todo(uow, owner, None, title="Milk")

    with pytest.raises(NotFound):
        await todos.move(uow, owner, todo.id, elsewhere.id)


async def test_move_keeps_subtasks_assignees_and_the_reminder(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    todo = await _todo(uow, owner, None, title="Bins", timed=True)
    await subtasks.add(uow, owner, todo.id, ["bin", "lid"])
    await todos.set_assignees(uow, owner, todo.id, [OWNER, OTHER])
    before = await todos.get(uow, owner, todo.id)

    moved = await todos.move(uow, owner, todo.id, lst.id)

    view = moved.value
    assert view.list_id == lst.id
    assert view.list_name == "Work"
    assert {s.title for s in view.subtasks} == {"bin", "lid"}
    assert view.assignee_ids == (OWNER, OTHER)
    assert before.pending_occurrence_id is not None
    assert view.pending_occurrence_id == before.pending_occurrence_id


async def test_list_todos_shows_only_the_given_list(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    await _todo(uow, owner, None, title="Milk")
    await _todo(uow, owner, lst.id, title="Bread")

    on_work = await todos.list_todos(uow, owner, lst.id)
    on_default = await todos.list_todos(uow, owner, None)

    assert [t.title for t in on_work.items] == ["Bread"]
    assert [t.title for t in on_default.items] == ["Milk"]


async def test_autocomplete_names_each_todos_list(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    milk = await _todo(uow, owner, None, title="Milk")
    oat = await _todo(uow, owner, lst.id, title="Oat milk")

    results = await todos.autocomplete(uow, owner, "milk")

    assert results == [(milk.id, "Milk", "Default List"), (oat.id, "Oat milk", "Work")]


async def test_list_upcoming_only_returns_the_given_list(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    lst = await _owned_list(uow)
    await _todo(uow, owner, None, title="Bins", timed=True)
    await _todo(uow, owner, lst.id, title="Dentist", timed=True)

    items = await occurrences.list_upcoming(
        uow, owner, lst.id, until=datetime(2030, 1, 8, tzinfo=UTC)
    )

    assert [item.todo.title for item in items] == ["Dentist"]


async def test_own_default_list_id_follows_the_setting(uow: Uow) -> None:
    owner = member(OWNER, GUILD_A)
    assert await settings.own_default_list_id(uow, owner) is None
    lst = await _owned_list(uow)

    await settings.set_default_list(uow, owner, lst.id)
    assert await settings.own_default_list_id(uow, owner) == lst.id

    await lists.delete(uow, owner, lst.id, move_to=None)
    assert await settings.own_default_list_id(uow, owner) is None
