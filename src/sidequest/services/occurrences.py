"""Occurrences: upcoming list, checking off, and the scheduler API (BRIEF §5.5)."""

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from sidequest.core.enums import OccurrenceStatus, Scope, TodoKind, TodoStatus
from sidequest.core.errors import InvalidOperation, NotFound
from sidequest.db.models import GuildSettings, Occurrence, Todo, UserSettings
from sidequest.services import _common as c
from sidequest.services.actor import Actor
from sidequest.services.dto import DueReminder, TodoView, UpcomingItem
from sidequest.services.effects import DeleteMessage, Effect, Outcome
from sidequest.services.uow import Uow

LATE_AFTER = timedelta(minutes=2)
"""A reminder posted more than this after its due time is marked late."""

# `mark_failed` reasons. `dm_closed` also warns the user on their next command (D26).
FAILURE_DM_CLOSED = "dm_closed"
FAILURE_NO_CHANNEL = "no_channel"
FAILURE_CHANNEL_UNAVAILABLE = "channel_unavailable"

OCCURRENCE_NOT_FOUND = "That reminder doesn't exist (or isn't on a list you can see here)."
_SYSTEM = Actor.system()


# --- user-facing -------------------------------------------------------------------------


async def list_upcoming(
    uow: Uow, actor: Actor, scope: Scope | None, until: datetime, limit: int = 25
) -> list[UpcomingItem]:
    """Pending occurrences due before `until`, soonest first (scope None: both lists)."""
    rows = (
        await uow.session.execute(
            select(Occurrence, Todo)
            .join(Todo, Todo.id == Occurrence.todo_id)
            .where(
                c.visible(actor, scope),
                Todo.status == TodoStatus.OPEN,
                Occurrence.status == OccurrenceStatus.PENDING,
                Occurrence.due_at <= until,
            )
            .options(selectinload(Todo.assignees), selectinload(Todo.subtasks))
            .order_by(Occurrence.due_at, Occurrence.id)
            .limit(limit)
        )
    ).all()
    occs = await c.open_occurrences(uow, [todo.id for _, todo in rows])
    return [
        UpcomingItem(
            occurrence_id=occ.id,
            due_at=occ.due_at,
            todo=c.todo_view(actor, todo, occs[todo.id]),
        )
        for occ, todo in rows
    ]


async def _lock_occurrence(
    uow: Uow, actor: Actor, occurrence_id: int
) -> tuple[Todo, Occurrence, list[Occurrence]]:
    """Lock the parent to-do, then return it, the fresh occurrence and its open siblings."""
    todo_id = await uow.session.scalar(
        select(Occurrence.todo_id).where(Occurrence.id == occurrence_id)
    )
    if todo_id is None:
        raise NotFound(OCCURRENCE_NOT_FOUND)
    try:
        todo = await c.load_todo(uow, actor, todo_id, lock=True)
    except NotFound:
        raise NotFound(OCCURRENCE_NOT_FOUND) from None
    occ = await uow.session.get(Occurrence, occurrence_id, populate_existing=True)
    if occ is None:
        raise NotFound(OCCURRENCE_NOT_FOUND)
    open_occs = (await c.open_occurrences(uow, [todo.id]))[todo.id]
    return todo, occ, open_occs


async def complete_occurrence(uow: Uow, actor: Actor, occurrence_id: int) -> Outcome[TodoView]:
    """Check off one occurrence (Done button, or early from /todo upcoming).

    pending → done (the reminder is never sent); sent → done + delete its message.
    One-time: the to-do is done. Repeating: subtasks reset, next occurrence scheduled.
    """
    todo, occ, open_occs = await _lock_occurrence(uow, actor, occurrence_id)
    if occ.status not in c.OPEN_OCCURRENCE or todo.status != TodoStatus.OPEN:
        raise InvalidOperation("That one is already checked off.")
    effects, changed = await c.finish_occurrence(uow, actor, todo, occ, open_occs)
    view = await c.view_of(uow, actor, todo)
    await uow.session.commit()
    return Outcome(value=view, effects=effects, changed_schedule=changed)


# --- scheduler ---------------------------------------------------------------------------


async def claim_due(uow: Uow, now: datetime, limit: int = 20) -> list[DueReminder]:
    """Claim due pending occurrences and mark them sent, in one transaction.

    Rows locked by another transaction (a concurrent claim or a user editing the to-do)
    are skipped and picked up next round. Repeating to-dos: the previous unchecked
    reminder becomes missed (its message is returned for deletion, D7), subtasks reset,
    and the next occurrence after `now` is scheduled, so an outage yields one catch-up
    reminder, not a flood.
    """
    rows = (
        await uow.session.execute(
            select(Occurrence, Todo)
            .join(Todo, Todo.id == Occurrence.todo_id)
            .where(
                Occurrence.status == OccurrenceStatus.PENDING,
                Occurrence.due_at <= now,
                Todo.status == TodoStatus.OPEN,
            )
            .order_by(Occurrence.due_at, Occurrence.id)
            .limit(limit)
            .with_for_update(skip_locked=True, of=[Occurrence, Todo])
            .execution_options(populate_existing=True)
        )
    ).all()
    if not rows:
        await uow.session.commit()
        return []

    todos = await _load_todos(uow, [todo.id for _, todo in rows])
    open_occs = await c.open_occurrences(uow, todos.keys())
    claimed: list[tuple[Occurrence, Todo, list[Effect]]] = []
    for occ, _ in rows:
        todo = todos[occ.todo_id]
        effects: list[Effect] = []
        if todo.kind == TodoKind.RECURRING:
            previous = c.find(open_occs[todo.id], OccurrenceStatus.SENT)
            if previous is not None:
                effects = c.close(previous, OccurrenceStatus.MISSED, now)
                c.reset_subtasks(todo)
                await uow.session.flush()  # free the one-sent-per-to-do slot
        occ.status = OccurrenceStatus.SENT
        occ.sent_at = now
        occ.late = now - occ.due_at > LATE_AFTER
        await uow.session.flush()  # free the one-pending-per-to-do slot
        if todo.kind == TodoKind.RECURRING:
            c.add_next_pending(uow, todo, after=now)
        claimed.append((occ, todo, effects))

    await uow.session.flush()
    reminders = await _reminders(uow, claimed)
    await uow.session.commit()
    return reminders


async def attach_message(
    uow: Uow, occurrence_id: int, channel_id: int, message_id: int
) -> Outcome[None]:
    """Store where a reminder was posted. If it was checked off or cancelled while being
    posted, the new message is returned for deletion instead."""
    _, occ, _ = await _lock_occurrence(uow, _SYSTEM, occurrence_id)
    if occ.status == OccurrenceStatus.SENT and occ.message_id is None:
        occ.channel_id = channel_id
        occ.message_id = message_id
        await uow.session.commit()
        return Outcome(value=None)
    await uow.session.commit()
    return Outcome(
        value=None, effects=[DeleteMessage(channel_id=channel_id, message_id=message_id)]
    )


async def mark_failed(uow: Uow, occurrence_id: int, reason: str) -> None:
    """The reminder could not be posted. `dm_closed` also flags the owner (D26)."""
    todo, occ, _ = await _lock_occurrence(uow, _SYSTEM, occurrence_id)
    if occ.status != OccurrenceStatus.SENT:
        await uow.session.commit()
        return
    occ.status = OccurrenceStatus.FAILED
    occ.failure_reason = reason[:64]
    if reason == FAILURE_DM_CLOSED:
        now = uow.clock.now()
        stmt = insert(UserSettings).values(user_id=todo.owner_id, dm_failed_at=now)
        stmt = stmt.on_conflict_do_update(
            index_elements=[UserSettings.user_id], set_={"dm_failed_at": now}
        )
        await uow.session.execute(stmt)
    await uow.session.commit()


async def unposted_sent(uow: Uow, older_than: datetime) -> list[DueReminder]:
    """Crash recovery: reminders marked sent before `older_than` but never posted."""
    rows = (
        await uow.session.execute(
            select(Occurrence)
            .join(Todo, Todo.id == Occurrence.todo_id)
            .where(
                Occurrence.status == OccurrenceStatus.SENT,
                Occurrence.message_id.is_(None),
                Occurrence.sent_at <= older_than,
                Todo.status == TodoStatus.OPEN,
            )
            .order_by(Occurrence.due_at, Occurrence.id)
        )
    ).scalars()
    occs = list(rows)
    todos = await _load_todos(uow, {o.todo_id for o in occs})
    return await _reminders(uow, [(o, todos[o.todo_id], []) for o in occs])


async def next_due_at(uow: Uow) -> datetime | None:
    """When the scheduler should next wake up (None: nothing scheduled)."""
    return await uow.session.scalar(
        select(func.min(Occurrence.due_at))
        .join(Todo, Todo.id == Occurrence.todo_id)
        .where(Occurrence.status == OccurrenceStatus.PENDING, Todo.status == TodoStatus.OPEN)
    )


# --- helpers -----------------------------------------------------------------------------


async def _load_todos(uow: Uow, ids: Sequence[int] | set[int]) -> dict[int, Todo]:
    if not ids:
        return {}
    todos = await uow.session.scalars(
        select(Todo)
        .where(Todo.id.in_(list(ids)))
        .options(selectinload(Todo.assignees), selectinload(Todo.subtasks))
        .execution_options(populate_existing=True)
    )
    return {t.id: t for t in todos}


async def _reminders(
    uow: Uow, items: Sequence[tuple[Occurrence, Todo, list[Effect]]]
) -> list[DueReminder]:
    guild_ids = {todo.guild_id for _, todo, _ in items if todo.guild_id is not None}
    channels: dict[int, int | None] = {}
    if guild_ids:
        result = await uow.session.execute(
            select(GuildSettings.guild_id, GuildSettings.reminder_channel_id).where(
                GuildSettings.guild_id.in_(guild_ids)
            )
        )
        channels = {guild_id: channel_id for guild_id, channel_id in result}
    open_occs = await c.open_occurrences(uow, {todo.id for _, todo, _ in items})
    reminders: list[DueReminder] = []
    for occ, todo, effects in items:
        server = todo.scope == Scope.SERVER
        reminders.append(
            DueReminder(
                occurrence=c.occurrence_view(occ),
                todo=c.todo_view(_SYSTEM, todo, open_occs[todo.id]),
                channel_id=channels.get(todo.guild_id) if server and todo.guild_id else None,
                dm_user_id=None if server else todo.owner_id,
                effects=effects,
            )
        )
    return reminders
