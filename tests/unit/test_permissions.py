"""Tests for the who-may-do-what rules in sidequest.services.permissions."""

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from sidequest.core.enums import Scope
from sidequest.services.actor import Actor
from sidequest.services.permissions import (
    can_complete,
    can_create,
    can_edit,
    can_manage_guild,
    can_view,
)

GUILD_A = 100
GUILD_B = 200
CREATOR = 1
ASSIGNEE = 2
OTHER = 3
SERVER_ASSIGNEES: frozenset[int] = frozenset({ASSIGNEE})
NO_ASSIGNEES: frozenset[int] = frozenset()
USERS = {"creator": CREATOR, "assignee": ASSIGNEE, "other": OTHER}


@dataclass(frozen=True)
class FakeTodo:
    scope: Scope
    guild_id: int | None
    owner_id: int


SERVER_TODO = FakeTodo(scope=Scope.SERVER, guild_id=GUILD_A, owner_id=CREATOR)
PERSONAL_TODO = FakeTodo(scope=Scope.PERSONAL, guild_id=None, owner_id=CREATOR)
SYSTEM = Actor.system()


def actor(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


# can_view and can_complete share one rule set, so they share these cases.
VIEW_CASES = [
    *[
        pytest.param(SERVER_TODO, actor(uid, GUILD_A), True, id=f"server-{name}-guild-a")
        for name, uid in USERS.items()
    ],
    *[
        pytest.param(SERVER_TODO, actor(uid, GUILD_B), False, id=f"server-{name}-guild-b")
        for name, uid in USERS.items()
    ],
    *[
        pytest.param(SERVER_TODO, actor(uid, None), False, id=f"server-{name}-dm")
        for name, uid in USERS.items()
    ],
    pytest.param(
        SERVER_TODO,
        actor(OTHER, GUILD_B, manage=True),
        False,
        id="server-other-manager-guild-b",
    ),
    pytest.param(PERSONAL_TODO, actor(CREATOR, GUILD_A), True, id="personal-creator-guild-a"),
    pytest.param(PERSONAL_TODO, actor(CREATOR, GUILD_B), True, id="personal-creator-guild-b"),
    pytest.param(PERSONAL_TODO, actor(CREATOR, None), True, id="personal-creator-dm"),
    pytest.param(PERSONAL_TODO, actor(OTHER, GUILD_A), False, id="personal-other-guild-a"),
    pytest.param(PERSONAL_TODO, actor(OTHER, None), False, id="personal-other-dm"),
    pytest.param(
        PERSONAL_TODO,
        actor(OTHER, GUILD_A, manage=True),
        False,
        id="personal-other-manager-guild-a",
    ),
    pytest.param(SERVER_TODO, SYSTEM, True, id="server-system"),
    pytest.param(PERSONAL_TODO, SYSTEM, True, id="personal-system"),
]

EDIT_CASES = [
    pytest.param(
        SERVER_TODO, SERVER_ASSIGNEES, actor(CREATOR, GUILD_A), True, id="server-creator-guild-a"
    ),
    pytest.param(
        SERVER_TODO, SERVER_ASSIGNEES, actor(ASSIGNEE, GUILD_A), True, id="server-assignee-guild-a"
    ),
    pytest.param(
        SERVER_TODO, SERVER_ASSIGNEES, actor(OTHER, GUILD_A), False, id="server-other-guild-a"
    ),
    pytest.param(
        SERVER_TODO,
        SERVER_ASSIGNEES,
        actor(OTHER, GUILD_A, manage=True),
        True,
        id="server-other-manager-guild-a",
    ),
    pytest.param(
        SERVER_TODO, SERVER_ASSIGNEES, actor(CREATOR, GUILD_B), False, id="server-creator-guild-b"
    ),
    pytest.param(
        SERVER_TODO,
        SERVER_ASSIGNEES,
        actor(OTHER, GUILD_B, manage=True),
        False,
        id="server-other-manager-guild-b",
    ),
    pytest.param(
        PERSONAL_TODO, NO_ASSIGNEES, actor(CREATOR, GUILD_A), True, id="personal-creator-guild-a"
    ),
    pytest.param(PERSONAL_TODO, NO_ASSIGNEES, actor(CREATOR, None), True, id="personal-creator-dm"),
    pytest.param(
        PERSONAL_TODO, NO_ASSIGNEES, actor(OTHER, GUILD_A), False, id="personal-other-guild-a"
    ),
    pytest.param(
        PERSONAL_TODO,
        NO_ASSIGNEES,
        actor(OTHER, GUILD_A, manage=True),
        False,
        id="personal-other-manager-guild-a",
    ),
    pytest.param(
        PERSONAL_TODO,
        NO_ASSIGNEES,
        actor(OTHER, GUILD_B, manage=True),
        False,
        id="personal-other-manager-guild-b",
    ),
    pytest.param(PERSONAL_TODO, NO_ASSIGNEES, actor(OTHER, None), False, id="personal-other-dm"),
    pytest.param(SERVER_TODO, SERVER_ASSIGNEES, SYSTEM, True, id="server-system"),
    pytest.param(PERSONAL_TODO, NO_ASSIGNEES, SYSTEM, True, id="personal-system"),
]

CREATE_CASES = [
    pytest.param(actor(CREATOR, GUILD_A), Scope.SERVER, True, id="server-todo-guild-a"),
    pytest.param(actor(CREATOR, None), Scope.SERVER, False, id="server-todo-dm"),
    pytest.param(actor(CREATOR, GUILD_A), Scope.PERSONAL, True, id="personal-todo-guild-a"),
    pytest.param(actor(CREATOR, None), Scope.PERSONAL, True, id="personal-todo-dm"),
    pytest.param(SYSTEM, Scope.SERVER, True, id="server-todo-system"),
]

MANAGE_GUILD_CASES = [
    pytest.param(actor(CREATOR, GUILD_A, manage=True), GUILD_A, True, id="manager-same-guild"),
    pytest.param(actor(CREATOR, GUILD_A, manage=False), GUILD_A, False, id="member-same-guild"),
    pytest.param(actor(CREATOR, GUILD_B, manage=True), GUILD_A, False, id="manager-other-guild"),
    pytest.param(actor(CREATOR, None, manage=True), GUILD_A, False, id="manager-dm"),
    pytest.param(SYSTEM, GUILD_A, True, id="system"),
]


@pytest.mark.parametrize("check", [can_view, can_complete], ids=["can_view", "can_complete"])
@pytest.mark.parametrize(("todo", "who", "expected"), VIEW_CASES)
def test_view_and_complete(
    check: Callable[[Actor, FakeTodo], bool],
    todo: FakeTodo,
    who: Actor,
    expected: bool,
) -> None:
    assert check(who, todo) is expected


@pytest.mark.parametrize(("todo", "assignees", "who", "expected"), EDIT_CASES)
def test_can_edit(
    todo: FakeTodo,
    assignees: frozenset[int],
    who: Actor,
    expected: bool,
) -> None:
    assert can_edit(who, todo, assignees) is expected


@pytest.mark.parametrize(("who", "scope", "expected"), CREATE_CASES)
def test_can_create(who: Actor, scope: Scope, expected: bool) -> None:
    assert can_create(who, scope) is expected


@pytest.mark.parametrize(("who", "guild_id", "expected"), MANAGE_GUILD_CASES)
def test_can_manage_guild(who: Actor, guild_id: int, expected: bool) -> None:
    assert can_manage_guild(who, guild_id) is expected
