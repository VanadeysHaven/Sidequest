"""Service data models are strict, frozen pydantic (D34)."""

from datetime import time

import pytest
from pydantic import ValidationError

from sidequest.services.actor import Actor
from sidequest.services.dto import DueInput, TodoPatch
from sidequest.services.effects import DeleteMessage, Outcome


def test_actor_rejects_coercion() -> None:
    with pytest.raises(ValidationError):
        Actor(user_id="5", guild_id=None, can_manage_guild=False, origin="discord")  # type: ignore[arg-type]


def test_actor_rejects_unknown_origin() -> None:
    with pytest.raises(ValidationError):
        Actor(user_id=5, guild_id=None, can_manage_guild=False, origin="cli")  # type: ignore[arg-type]


def test_models_are_frozen() -> None:
    actor = Actor.system()
    with pytest.raises(ValidationError):
        actor.user_id = 1  # type: ignore[misc]


def test_models_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DeleteMessage(channel_id=1, message_id=2, guild_id=3)  # type: ignore[call-arg]


def test_due_input_rejects_time_string() -> None:
    with pytest.raises(ValidationError):
        DueInput(time="10:00")  # type: ignore[arg-type]
    assert DueInput(time=time(10, 0)).time == time(10, 0)


def test_patch_counts_only_explicit_fields() -> None:
    assert "details" not in TodoPatch().model_fields_set
    assert "details" in TodoPatch(details=None).model_fields_set
    assert "details" not in TodoPatch(title="x").model_fields_set


def test_outcome_defaults_and_equality() -> None:
    out = Outcome(value=None)
    assert out.effects == []
    assert out.changed_schedule is False
    assert DeleteMessage(channel_id=1, message_id=2) == DeleteMessage(channel_id=1, message_id=2)
