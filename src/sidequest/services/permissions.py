"""Who may do what (BRIEF §4.10). Pure functions; services raise the errors.

| Action                                   | Server to-do                         | Personal |
|------------------------------------------|--------------------------------------|----------|
| view, tick subtasks, complete            | any member in that server (D3)       | owner    |
| edit, details, assign, subtasks, delete  | creator, assignee, Manage Server (D20)| owner   |

Services raise `NotFound` (not `Forbidden`) when `can_view` fails, so IDs don't leak
across servers. The system actor (scheduler) passes every check.
"""

from collections.abc import Collection
from typing import Protocol

from sidequest.core.enums import Scope
from sidequest.services.actor import Actor


class TodoAccess(Protocol):
    """The fields of a to-do that permissions depend on (ORM `Todo` fits)."""

    @property
    def scope(self) -> Scope: ...
    @property
    def guild_id(self) -> int | None: ...
    @property
    def owner_id(self) -> int: ...


def can_view(actor: Actor, todo: TodoAccess) -> bool:
    if actor.is_system:
        return True
    if todo.scope == Scope.SERVER:
        return todo.guild_id is not None and actor.guild_id == todo.guild_id
    return actor.user_id == todo.owner_id


def can_complete(actor: Actor, todo: TodoAccess) -> bool:
    """Complete the to-do or an occurrence, and tick subtasks (D3)."""
    return can_view(actor, todo)


def can_edit(actor: Actor, todo: TodoAccess, assignee_ids: Collection[int]) -> bool:
    """Edit, set details, assign, add/remove subtasks, delete (D20)."""
    if actor.is_system:
        return True
    if not can_view(actor, todo):
        return False
    if todo.scope == Scope.PERSONAL:
        return True  # can_view already means "is the owner"
    return actor.user_id == todo.owner_id or actor.user_id in assignee_ids or actor.can_manage_guild


def can_create(actor: Actor, scope: Scope) -> bool:
    """Server to-dos need a server context; personal ones work everywhere."""
    return actor.is_system or scope == Scope.PERSONAL or actor.guild_id is not None


def can_manage_guild(actor: Actor, guild_id: int) -> bool:
    """Server settings, e.g. the reminder channel."""
    return actor.is_system or (actor.guild_id == guild_id and actor.can_manage_guild)
