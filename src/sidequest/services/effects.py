"""Side effects services ask the adapter to perform. Services never call Discord (§5.6)."""

from pydantic import Field

from sidequest.services.model import StrictModel


class DeleteMessage(StrictModel):
    """Delete a reminder message. The adapter ignores "message not found"."""

    channel_id: int
    message_id: int


type Effect = DeleteMessage  # grows later (e.g. EditMessage); then a discriminated union


class Outcome[T](StrictModel):
    """Result of a mutating service call."""

    value: T
    effects: list[Effect] = Field(default_factory=list)
    changed_schedule: bool = False
    """A pending occurrence was added, moved or removed: wake the scheduler."""
