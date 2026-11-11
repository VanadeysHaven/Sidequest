"""Read models and inputs of the services (strict, frozen pydantic, D34).

Callers never see ORM objects."""

import datetime as dt
import math
from datetime import datetime
from typing import Literal

from sidequest.core.enums import OccurrenceStatus, Scope, TodoKind, TodoStatus
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
    scope: Scope
    guild_id: int | None
    owner_id: int
    """The creator (server) or owner (personal)."""
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
    """Whether the actor who asked may edit/delete/assign (BRIEF §4.10)."""

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
    """Server to-dos: the guild's reminder channel (None if it was never set)."""
    dm_user_id: int | None
    """Personal to-dos: the owner to DM."""
    effects: list[Effect]
    """Messages to delete first (the previous reminder, now missed)."""


class GuildSettingsView(StrictModel):
    guild_id: int
    reminder_channel_id: int | None
