"""Read models and inputs of the services (strict, frozen pydantic, D34).

Callers never see ORM objects."""

import datetime as dt
import math
from datetime import datetime
from typing import Literal

from sidequest.core.enums import OccurrenceStatus, TodoKind, TodoStatus
from sidequest.core.recurrence import RecurrenceRule
from sidequest.services.effects import Effect
from sidequest.services.model import StrictModel

type ListFilter = Literal["all", "timed", "untimed"]


class DueInput(StrictModel):
    """Date/time as the user typed it for a one-time to-do (resolved by the service, D17/D18).

    Both None → untimed. Time without date → next occurrence of that time.
    """

    date: dt.date | None = None
    time: dt.time | None = None


class TodoPatch(StrictModel):
    """Fields to change in `todos.edit`. Only fields passed explicitly count
    (`model_fields_set`): `TodoPatch(details=None)` clears the details, `TodoPatch()`
    changes nothing. For title, due, rule and timezone, None also means "keep"."""

    title: str | None = None
    details: str | None = None
    """None or "" clears the details (when passed)."""
    due: DueInput | None = None
    """One-time to-dos only. `DueInput()` makes it untimed."""
    rule: RecurrenceRule | None = None
    """Repeating to-dos only."""
    timezone: str | None = None
    """New timezone. Without a new due/rule, the same wall-clock time is kept."""


class SubtaskView(StrictModel):
    id: int
    position: int
    title: str
    done: bool
    done_at: datetime | None
    done_by: int | None


class OccurrenceView(StrictModel):
    id: int
    todo_id: int
    due_at: datetime
    status: OccurrenceStatus
    late: bool
    sent_at: datetime | None
    channel_id: int | None
    message_id: int | None


class TodoView(StrictModel):
    id: int
    guild_id: int
    list_id: int
    list_name: str
    owner_id: int
    """The creator (no special rights since D50)."""
    title: str
    details: str | None
    kind: TodoKind
    status: TodoStatus
    timezone: str
    due_at: datetime | None
    """One-time timed to-dos only."""
    rule: RecurrenceRule | None
    rule_description: str | None
    next_due_at: datetime | None
    """When the next reminder fires (the pending occurrence), or None."""
    pending_occurrence_id: int | None
    reminder: OccurrenceView | None
    """The reminder that has been sent and is waiting for Done, if any."""
    assignee_ids: tuple[int, ...]
    subtasks: tuple[SubtaskView, ...]
    created_at: datetime
    completed_at: datetime | None
    completed_by: int | None
    can_edit: bool
    """Whether the actor who asked may edit/delete/assign/move (BRIEF §4.10)."""
    can_complete: bool
    """Whether the actor who asked may check it off and tick subtasks (D50)."""

    @property
    def is_timed(self) -> bool:
        return self.kind == TodoKind.RECURRING or self.due_at is not None


class Page[T](StrictModel):
    items: list[T]
    page: int
    """0-based."""
    page_size: int
    total: int

    @property
    def page_count(self) -> int:
        return max(1, math.ceil(self.total / self.page_size))

    @property
    def has_next(self) -> bool:
        return (self.page + 1) * self.page_size < self.total


class UpcomingItem(StrictModel):
    occurrence_id: int
    due_at: datetime
    todo: TodoView


class DueReminder(StrictModel):
    """Everything the scheduler needs to post one reminder."""

    occurrence: OccurrenceView
    todo: TodoView
    channel_id: int | None
    """The guild's reminder channel (None if none is set)."""
    effects: list[Effect]
    """Messages to delete first (the previous reminder, now missed)."""


class SubtaskTick(StrictModel):
    """A subtask tick that a check-off reset (repeating to-dos, D4)."""

    id: int
    done_at: datetime
    done_by: int | None


class UndoToken(StrictModel):
    """What undoing one check-off needs (D63, D66). Kept in the bot's memory only; the
    undo service re-checks all of it against the database."""

    todo_id: int
    occurrence_id: int | None
    """The occurrence that was checked off; None for a one-time to-do checked off without
    an open occurrence (untimed, or its reminder failed)."""
    previous: OccurrenceStatus | None
    """Its status before the check-off (pending or sent)."""
    followup_id: int | None
    """Repeating to-dos: the pending occurrence right after the check-off. Created by the
    check-off when `previous` is pending (undo cancels it); already there when it was sent."""
    ticks: tuple[SubtaskTick, ...]
    """Subtask ticks the check-off reset."""


class CheckedOff(StrictModel):
    todo: TodoView
    undo: UndoToken


class Undone(StrictModel):
    todo: TodoView
    repost: DueReminder | None
    """The reminder to post again (it was up when it was checked off, D64)."""


class GuildSettingsView(StrictModel):
    guild_id: int
    reminder_channel_id: int | None


class ListView(StrictModel):
    """One list of a server, as seen by the actor who asked."""

    id: int
    guild_id: int
    name: str
    owner_id: int | None
    """None for the server's fallback list (open to everyone, D51)."""
    collaborator_ids: tuple[int, ...]
    is_fallback: bool
    """The server's "Default List" (D42): can't be deleted, no owner or collaborators."""
    is_my_default: bool
    """The actor's effective default list here (their setting, else the fallback, D45)."""
    open_count: int
    can_manage: bool
    """May delete it, set collaborators, transfer it (D46; never for the fallback)."""
    can_rename: bool
    can_add: bool
    """May add to-dos to it and work on them (D50/D51)."""


class ListDeletePreview(StrictModel):
    """What `/lists delete` asks about (D47)."""

    list: ListView
    open_count: int
    targets: list[ListView]
    """Lists its open to-dos can be moved to: the server's other lists the actor may add to."""


class ListDeleteResult(StrictModel):
    name: str
    deleted: int
    """Open to-dos that were deleted with the list."""
    moved: int
    moved_to: str | None
    """Name of the list the open to-dos were moved to."""
