"""What the scheduler needs from whoever delivers reminders (the bot implements it).

The scheduler never imports `discord`: it hands a `DueReminder` to a `Notifier` and records
the `PostResult`.
"""

from collections.abc import Sequence
from typing import Protocol

from sidequest.services.dto import DueReminder
from sidequest.services.effects import Effect
from sidequest.services.model import StrictModel


class Posted(StrictModel):
    """The reminder message exists: where it is, for the Done button and later deletion."""

    channel_id: int
    message_id: int


class Failed(StrictModel):
    """The reminder could not be posted. `reason` is one of the `FAILURE_*` constants in
    `sidequest.services.occurrences`."""

    reason: str


type PostResult = Posted | Failed


class Notifier(Protocol):
    async def post(self, reminder: DueReminder) -> PostResult:
        """Post one reminder. Expected failures (no channel, DMs closed, …) are returned as
        `Failed`; an exception counts as `Failed(FAILURE_ERROR)`."""
        ...

    async def execute(self, effects: Sequence[Effect]) -> None:
        """Carry out effects (delete a replaced reminder, …). Must not raise for a message
        that is already gone."""
        ...
