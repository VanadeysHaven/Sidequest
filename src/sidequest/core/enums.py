"""String enums shared by every layer. Values are what the database stores."""

from enum import StrEnum


class Scope(StrEnum):
    """Which list a to-do belongs to."""

    SERVER = "server"
    """The shared list of one Discord server; requires a guild_id. Reminders go to the
    server's reminder channel and ping the assignees."""

    PERSONAL = "personal"
    """The owner's own list, the same in every server and in DMs. Reminders arrive as a DM."""


class TodoKind(StrEnum):
    """Whether a to-do happens once or repeats."""

    ONCE = "once"
    """One-time: either untimed (no due_at, no reminder) or timed (due_at set, one reminder)."""

    RECURRING = "recurring"
    """Repeats by a recurrence rule (daily, weekly, monthly); one reminder per occurrence.
    Has a rule and never a due_at."""


class TodoStatus(StrEnum):
    """Lifecycle of a to-do as a whole."""

    OPEN = "open"
    """Active: shown in lists, and reminders are scheduled."""

    DONE = "done"
    """Completed. Kept as history and hidden from lists."""

    CANCELLED = "cancelled"
    """Deleted by a user. Kept as history and hidden from lists."""


class OccurrenceStatus(StrEnum):
    """Lifecycle of one reminder instance of a to-do.

    Flow: pending → sent → done/missed; pending → done (checked off early) or
    cancelled (to-do edited or deleted); sent → failed (posting the reminder failed).
    """

    PENDING = "pending"
    """Scheduled, not yet due. At most one per to-do."""

    SENT = "sent"
    """The reminder message is posted and waiting for Done. At most one per to-do."""

    DONE = "done"
    """Checked off, either from the reminder or early via a command."""

    MISSED = "missed"
    """Not checked off before the next occurrence of a repeating to-do fired; its
    reminder message was deleted."""

    CANCELLED = "cancelled"
    """Dropped because the to-do was edited or deleted before it fired."""

    FAILED = "failed"
    """The reminder could not be posted, e.g. no reminder channel or DMs closed."""
