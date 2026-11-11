"""Internals shared by the service modules: loading, locking, validation, DTO mapping."""

from collections.abc import Iterable, Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Select, and_, false, or_, select
from sqlalchemy.orm import selectinload

from sidequest.core import recurrence
from sidequest.core.enums import OccurrenceStatus, Scope, TodoKind, TodoStatus
from sidequest.core.errors import Forbidden, InvalidOperation, LimitExceeded, NotFound
from sidequest.core.limits import DETAILS_MAX, TITLE_MAX
from sidequest.core.tz import get_zone
from sidequest.db.models import GuildSettings, Occurrence, Todo, UserSettings
from sidequest.services import permissions
from sidequest.services.actor import Actor
from sidequest.services.dto import OccurrenceView, SubtaskView, TodoView
from sidequest.services.effects import DeleteMessage, Effect
from sidequest.services.uow import Uow

OPEN_OCCURRENCE = (OccurrenceStatus.PENDING, OccurrenceStatus.SENT)
NOT_FOUND = "That to-do doesn't exist (or isn't on a list you can see here)."

# --- validation --------------------------------------------------------------------------


def clean_title(title: str) -> str:
    title = title.strip()
    if not title:
        raise InvalidOperation("The title can't be empty.")
    if len(title) > TITLE_MAX:
        raise LimitExceeded(f"The title is too long ({len(title)}/{TITLE_MAX} characters).")
    return title


def clean_details(details: str | None) -> str | None:
    if details is None or not details.strip():
        return None
    details = details.strip("\n").rstrip()
    if len(details) > DETAILS_MAX:
        raise LimitExceeded(f"The details are too long ({len(details)}/{DETAILS_MAX} characters).")
    return details


# --- settings lookups --------------------------------------------------------------------


async def user_timezone(uow: Uow, user_id: int) -> tuple[str, bool]:
    """(IANA name, is_default) for a user."""
    tz = await uow.session.scalar(
        select(UserSettings.timezone).where(UserSettings.user_id == user_id)
    )
    if tz is None:
        return uow.default_timezone, True
    return tz, False


async def effective_zone(uow: Uow, actor: Actor, override: str | None) -> ZoneInfo:
    """Explicit override, else the actor's timezone, else DEFAULT_TIMEZONE (D24, D25)."""
    if override is not None and override.strip():
        return get_zone(override)
    name, _ = await user_timezone(uow, actor.user_id)
    return get_zone(name)


async def reminder_channel(uow: Uow, guild_id: int) -> int | None:
    return await uow.session.scalar(
        select(GuildSettings.reminder_channel_id).where(GuildSettings.guild_id == guild_id)
    )


def visible(actor: Actor, scope: Scope | None) -> ColumnElement[bool]:
    """SQL filter for the to-dos the actor sees in `scope` (None: both lists)."""
    server = (
        and_(Todo.scope == Scope.SERVER, Todo.guild_id == actor.guild_id)
        if actor.guild_id is not None
        else false()
    )
    personal = and_(Todo.scope == Scope.PERSONAL, Todo.owner_id == actor.user_id)
    if scope == Scope.SERVER:
        if actor.guild_id is None:
            raise InvalidOperation("The server list is only available in a server.")
        return server
    if scope == Scope.PERSONAL:
        return personal
    return or_(server, personal)


# --- loading -----------------------------------------------------------------------------


def _todo_query(todo_id: int) -> Select[tuple[Todo]]:
    return (
        select(Todo)
        .where(Todo.id == todo_id)
        .options(selectinload(Todo.assignees), selectinload(Todo.subtasks))
        .execution_options(populate_existing=True)
    )


async def load_todo(uow: Uow, actor: Actor, todo_id: int, *, lock: bool = False) -> Todo:
    """Load a to-do with assignees and subtasks. `NotFound` unless the actor can view it.

    `lock=True` takes the to-do row lock that every write must hold (see package docs).
    """
    query = _todo_query(todo_id)
    if lock:
        query = query.with_for_update()
    todo = await uow.session.scalar(query)
    if todo is None or not permissions.can_view(actor, todo):
        raise NotFound(NOT_FOUND)
    return todo


def assignee_ids(todo: Todo) -> tuple[int, ...]:
    return tuple(sorted(a.user_id for a in todo.assignees))


def require_open(todo: Todo) -> None:
    if todo.status == TodoStatus.DONE:
        raise InvalidOperation("That to-do is already done.")
    if todo.status == TodoStatus.CANCELLED:
        raise NotFound(NOT_FOUND)


def require_edit(actor: Actor, todo: Todo) -> None:
    if not permissions.can_edit(actor, todo, assignee_ids(todo)):
        raise Forbidden(
            "Only the creator, an assignee or someone with Manage Server can change this to-do."
        )


async def open_occurrences(uow: Uow, todo_ids: Iterable[int]) -> dict[int, list[Occurrence]]:
    """Pending and sent occurrences per to-do id (at most one of each)."""
    ids = list(todo_ids)
    result: dict[int, list[Occurrence]] = {todo_id: [] for todo_id in ids}
    if not ids:
        return result
    rows = await uow.session.scalars(
        select(Occurrence)
        .where(Occurrence.todo_id.in_(ids), Occurrence.status.in_(OPEN_OCCURRENCE))
        .execution_options(populate_existing=True)
    )
    for occ in rows:
        result[occ.todo_id].append(occ)
    return result


def find(occurrences: Sequence[Occurrence], status: OccurrenceStatus) -> Occurrence | None:
    return next((o for o in occurrences if o.status == status), None)


# --- scheduling --------------------------------------------------------------------------


def rule_of(todo: Todo) -> recurrence.RecurrenceRule:
    return recurrence.from_json(todo.recurrence)


def add_pending(uow: Uow, todo: Todo, due_at: datetime) -> Occurrence:
    occ = Occurrence(todo_id=todo.id, due_at=due_at, status=OccurrenceStatus.PENDING)
    uow.session.add(occ)
    return occ


def add_next_pending(uow: Uow, todo: Todo, after: datetime) -> Occurrence:
    """Materialize the recurring to-do's next occurrence strictly after `after`."""
    due = recurrence.next_occurrence(rule_of(todo), get_zone(todo.timezone), after)
    return add_pending(uow, todo, due)


def close(
    occ: Occurrence, status: OccurrenceStatus, now: datetime, by: int | None = None
) -> list[Effect]:
    """Move an open occurrence to a final status; returns the delete for its message."""
    was_sent = occ.status == OccurrenceStatus.SENT
    occ.status = status
    if status == OccurrenceStatus.DONE:
        occ.completed_at = now
        occ.completed_by = by
    if was_sent and occ.channel_id is not None and occ.message_id is not None:
        return [DeleteMessage(channel_id=occ.channel_id, message_id=occ.message_id)]
    return []


def reset_subtasks(todo: Todo) -> None:
    """New occurrence, fresh checklist (D4). Needs `todo.subtasks` loaded."""
    for sub in todo.subtasks:
        sub.done_at = None
        sub.done_by = None


# --- mapping -----------------------------------------------------------------------------


def occurrence_view(occ: Occurrence) -> OccurrenceView:
    return OccurrenceView(
        id=occ.id,
        todo_id=occ.todo_id,
        due_at=occ.due_at,
        status=occ.status,
        late=occ.late,
        sent_at=occ.sent_at,
        channel_id=occ.channel_id,
        message_id=occ.message_id,
    )


def todo_view(actor: Actor, todo: Todo, occurrences: Sequence[Occurrence]) -> TodoView:
    """Map a loaded to-do (assignees + subtasks) and its open occurrences to a view."""
    rule = rule_of(todo) if todo.kind == TodoKind.RECURRING else None
    pending = find(occurrences, OccurrenceStatus.PENDING)
    sent = find(occurrences, OccurrenceStatus.SENT)
    assignees = assignee_ids(todo)
    return TodoView(
        id=todo.id,
        scope=todo.scope,
        guild_id=todo.guild_id,
        owner_id=todo.owner_id,
        title=todo.title,
        details=todo.details,
        kind=todo.kind,
        status=todo.status,
        timezone=todo.timezone,
        due_at=todo.due_at,
        rule=rule,
        rule_description=recurrence.describe(rule, get_zone(todo.timezone)) if rule else None,
        next_due_at=pending.due_at if pending else None,
        pending_occurrence_id=pending.id if pending else None,
        reminder=occurrence_view(sent) if sent else None,
        assignee_ids=assignees if todo.scope == Scope.SERVER else (),
        subtasks=tuple(
            SubtaskView(
                id=s.id,
                position=s.position,
                title=s.title,
                done=s.done_at is not None,
                done_at=s.done_at,
                done_by=s.done_by,
            )
            for s in todo.subtasks
        ),
        created_at=todo.created_at,
        completed_at=todo.completed_at,
        completed_by=todo.completed_by,
        can_edit=permissions.can_edit(actor, todo, assignees),
    )


async def view_of(uow: Uow, actor: Actor, todo: Todo) -> TodoView:
    """Flush pending changes, then build a fresh view of one to-do."""
    await uow.session.flush()
    occs = await open_occurrences(uow, [todo.id])
    return todo_view(actor, todo, occs[todo.id])


# --- completing --------------------------------------------------------------------------


def mark_todo_done(todo: Todo, actor: Actor, now: datetime) -> None:
    todo.status = TodoStatus.DONE
    todo.completed_at = now
    todo.completed_by = actor.user_id


async def finish_occurrence(
    uow: Uow, actor: Actor, todo: Todo, occ: Occurrence, occurrences: Sequence[Occurrence]
) -> tuple[list[Effect], bool]:
    """Check off one open occurrence. Returns (effects, changed_schedule).

    One-time: the to-do is done. Recurring: subtasks reset (D4) and, if the pending slot
    is now free, the next occurrence after this one is materialized.
    """
    now = uow.clock.now()
    was_pending = occ.status == OccurrenceStatus.PENDING
    pending = find(occurrences, OccurrenceStatus.PENDING)
    effects = close(occ, OccurrenceStatus.DONE, now, actor.user_id)
    if todo.kind == TodoKind.ONCE:
        mark_todo_done(todo, actor, now)
        return effects, was_pending
    reset_subtasks(todo)
    if pending is None or pending is occ:
        await uow.session.flush()  # free the one-pending-per-to-do slot first
        add_next_pending(uow, todo, after=max(occ.due_at, now))
        return effects, True
    return effects, False
