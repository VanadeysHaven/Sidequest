"""Tests for the who-may-do-what rules in sidequest.services.permissions (D50, D51).

The tables follow the module docstring of `sidequest.services.permissions`. Each row gives
(owned list, fallback list) for one kind of actor.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from sidequest.services.actor import Actor
from sidequest.services.permissions import (
    can_add,
    can_complete,
    can_edit,
    can_manage_guild,
    can_manage_list,
    can_rename_list,
    can_view,
    can_work_on,
)

GUILD_A = 100
GUILD_B = 200
OWNER = 1
COLLABORATOR = 2
OTHER = 3
MANAGER = 4
OTHER_GUILD_USER = 5


@dataclass(frozen=True)
class FakeList:
    guild_id: int
    owner_id: int | None
    collaborator_ids: frozenset[int]


OWNED = FakeList(guild_id=GUILD_A, owner_id=OWNER, collaborator_ids=frozenset({COLLABORATOR}))
FALLBACK = FakeList(guild_id=GUILD_A, owner_id=None, collaborator_ids=frozenset())
LISTS = {"owned": OWNED, "fallback": FALLBACK}


def actor(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


ACTORS = {
    "owner": actor(OWNER, GUILD_A),
    "collaborator": actor(COLLABORATOR, GUILD_A),
    "other-member": actor(OTHER, GUILD_A),
    "manage-server": actor(MANAGER, GUILD_A, manage=True),
    "other-guild": actor(OTHER_GUILD_USER, GUILD_B),
    "system": Actor.system(),
}


def rows(spec: dict[str, tuple[bool, bool]]) -> list[Any]:
    """Expand {actor: (owned, fallback)} into one parametrize row per (actor, list)."""
    return [
        pytest.param(ACTORS[who], lst, expected, id=f"{who}-{name}")
        for who, pair in spec.items()
        for (name, lst), expected in zip(LISTS.items(), pair, strict=True)
    ]


# Add, edit, details, assign, subtasks, delete, move, check off, tick subtasks (D50, D51).
WORK_ON = {
    "owner": (True, True),
    "collaborator": (True, True),
    "other-member": (False, True),
    "manage-server": (True, True),
    "other-guild": (False, False),
    "system": (True, True),
}

# Rename: owner or Manage Server; for the fallback list only Manage Server.
RENAME = {
    "owner": (True, False),
    "collaborator": (False, False),
    "other-member": (False, False),
    "manage-server": (True, True),
    "other-guild": (False, False),
    "system": (True, True),
}

# Delete the list, set collaborators, transfer: owner or Manage Server, never the fallback.
MANAGE_LIST = {
    "owner": (True, False),
    "collaborator": (False, False),
    "other-member": (False, False),
    "manage-server": (True, False),
    "other-guild": (False, False),
    "system": (True, False),
}

# Every member of the server sees every list and its to-dos.
VIEW = {
    "owner": (True, True),
    "collaborator": (True, True),
    "other-member": (True, True),
    "manage-server": (True, True),
    "other-guild": (False, False),
    "system": (True, True),
}


@pytest.mark.parametrize(
    "check", [can_work_on, can_add, can_edit, can_complete], ids=lambda f: f.__name__
)
@pytest.mark.parametrize(("who", "lst", "expected"), rows(WORK_ON))
def test_work_on_rules(
    check: Callable[[Actor, FakeList], bool], who: Actor, lst: FakeList, expected: bool
) -> None:
    assert check(who, lst) is expected


@pytest.mark.parametrize(("who", "lst", "expected"), rows(RENAME))
def test_rename_list(who: Actor, lst: FakeList, expected: bool) -> None:
    assert can_rename_list(who, lst) is expected


@pytest.mark.parametrize(("who", "lst", "expected"), rows(MANAGE_LIST))
def test_manage_list(who: Actor, lst: FakeList, expected: bool) -> None:
    assert can_manage_list(who, lst) is expected


@pytest.mark.parametrize(("who", "lst", "expected"), rows(VIEW))
def test_view(who: Actor, lst: FakeList, expected: bool) -> None:
    assert can_view(who, lst) is expected


MANAGE_GUILD_CASES = [
    pytest.param(actor(OWNER, GUILD_A, manage=True), GUILD_A, True, id="manager-same-guild"),
    pytest.param(actor(OWNER, GUILD_A, manage=False), GUILD_A, False, id="member-same-guild"),
    pytest.param(actor(OWNER, GUILD_B, manage=True), GUILD_A, False, id="manager-other-guild"),
    pytest.param(actor(OWNER, None, manage=True), GUILD_A, False, id="manager-dm"),
    pytest.param(Actor.system(), GUILD_A, True, id="system"),
]


@pytest.mark.parametrize(("who", "guild_id", "expected"), MANAGE_GUILD_CASES)
def test_can_manage_guild(who: Actor, guild_id: int, expected: bool) -> None:
    assert can_manage_guild(who, guild_id) is expected
