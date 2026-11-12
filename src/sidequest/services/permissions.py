"""Who may do what (BRIEF §4.10, S8 D46/D50/D51). Pure functions; services raise the errors.

| Action                                          | Owned list (D50)      | Fallback list (D51) |
|-------------------------------------------------|-----------------------|---------------------|
| see the list and its to-dos                     | any member            | any member          |
| add, edit, details, assign, subtasks, delete,   | owner, collaborators, | any member          |
| move, check off, tick subtasks                  | Manage Server         |                     |
| rename the list                                 | owner, Manage Server  | Manage Server       |
| delete the list, collaborators, transfer        | owner, Manage Server  | nobody              |

"Owned list" = `owner_id` is set; the fallback list ("Default List") is the only ownerless
one. Services raise `NotFound` (not `Forbidden`) when `can_view` fails, so IDs don't leak
across servers. The system actor (scheduler) passes every check except managing the
fallback list, which nobody may do.
"""

from collections.abc import Collection
from typing import Protocol

from sidequest.services.actor import Actor


class TodoAccess(Protocol):
    """The fields of a to-do that visibility depends on (ORM `Todo` fits)."""

    @property
    def guild_id(self) -> int: ...


class ListAccess(Protocol):
    """The fields of a list that permissions depend on (ORM `TodoList` fits)."""

    @property
    def guild_id(self) -> int: ...
    @property
    def owner_id(self) -> int | None: ...
    @property
    def collaborator_ids(self) -> Collection[int]: ...


def can_view(actor: Actor, todo: TodoAccess) -> bool:
    """Every member of the server sees every list and its to-dos."""
    return actor.is_system or actor.guild_id == todo.guild_id


def can_view_list(actor: Actor, lst: ListAccess) -> bool:
    return actor.is_system or actor.guild_id == lst.guild_id


def can_work_on(actor: Actor, lst: ListAccess) -> bool:
    """Add, edit, check off and tick subtasks on the list's to-dos (D50, D51)."""
    if actor.is_system:
        return True
    if actor.guild_id != lst.guild_id:
        return False
    return (
        lst.owner_id is None
        or actor.user_id == lst.owner_id
        or actor.user_id in lst.collaborator_ids
        or actor.can_manage_guild
    )


def can_add(actor: Actor, lst: ListAccess) -> bool:
    """Add a to-do to the list, or move one onto it."""
    return can_work_on(actor, lst)


def can_edit(actor: Actor, lst: ListAccess) -> bool:
    """Edit, set details, assign, add/remove subtasks, delete, move off the list."""
    return can_work_on(actor, lst)


def can_complete(actor: Actor, lst: ListAccess) -> bool:
    """Check off (command, upcoming, reminder Done) and tick subtasks."""
    return can_work_on(actor, lst)


def can_rename_list(actor: Actor, lst: ListAccess) -> bool:
    """Owner or Manage Server; only Manage Server for the fallback list (D51)."""
    if actor.is_system:
        return True
    if actor.guild_id != lst.guild_id:
        return False
    if actor.can_manage_guild:
        return True
    return lst.owner_id is not None and actor.user_id == lst.owner_id


def can_manage_list(actor: Actor, lst: ListAccess) -> bool:
    """Delete the list, set collaborators, transfer. Never on the fallback list (D51)."""
    if lst.owner_id is None:
        return False
    if actor.is_system:
        return True
    if actor.guild_id != lst.guild_id:
        return False
    return actor.can_manage_guild or actor.user_id == lst.owner_id


def can_manage_guild(actor: Actor, guild_id: int) -> bool:
    """Server settings, e.g. the reminder channel."""
    return actor.is_system or (actor.guild_id == guild_id and actor.can_manage_guild)
