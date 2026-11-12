"""To-do operations: create, read, list, edit, assign, move, complete, delete, autocomplete."""

from collections.abc import Sequence

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import aliased

from sidequest.core import recurrence
from sidequest.core.enums import OccurrenceStatus, TodoKind, TodoStatus
from sidequest.core.errors import (
    InvalidOperation,
    LimitExceeded,
    NotFound,
    ReminderChannelNotSet,
)
from sidequest.core.limits import ASSIGNEES_MAX
from sidequest.core.recurrence import RecurrenceRule
from sidequest.core.text import bold
from sidequest.core.timeparse import Timed, resolve_due
from sidequest.core.tz import get_zone
from sidequest.db.models import Occurrence, Todo, TodoAssignee, TodoList
from sidequest.services import _common as c
from sidequest.services import lists
from sidequest.services.actor import Actor
from sidequest.services.dto import DueInput, ListFilter, Page, TodoPatch, TodoView
from sidequest.services.effects import Effect, Outcome
from sidequest.services.uow import Uow

NO_CHANNEL = (
    "This server has no reminder channel yet, so timed to-dos can't be added. "
    "Ask someone with Manage Server to run /sidequest channel."
)


UNTIMED = DueInput()


# --- create ------------------------------------------------------------------------------


def _clean_assignees(actor: Actor, user_ids: Sequence[int] | None) -> list[int]:
    if user_ids is None:
        return [actor.user_id]
    unique = list(dict.fromkeys(user_ids))
    if not unique:
        raise InvalidOperation("A to-do needs at least one assignee.")
    if len(unique) > ASSIGNEES_MAX:
        raise LimitExceeded(f"A to-do can have at most {ASSIGNEES_MAX} assignees.")
    return unique


async def _require_channel(uow: Uow, guild_id: int) -> None:
    if await c.reminder_channel(uow, guild_id) is None:
        raise ReminderChannelNotSet(NO_CHANNEL)


async def _target_list(uow: Uow, actor: Actor, list_id: int | None) -> TodoList:
    """The list a new to-do goes on (D45) and the add check (D50, D53: a default the
    actor can no longer add to is refused by name, not silently replaced)."""
    lst = await lists.resolve(uow, actor, list_id)
    c.require_add(actor, lst)
    return lst


async def _new_todo(
    uow: Uow,
    actor: Actor,
    lst: TodoList,
    kind: TodoKind,
    title: str,
    details: str | None,
    timezone: str,
    assignee_ids: Sequence[int] | None,
) -> Todo:
    assignees = _clean_assignees(actor, assignee_ids)
    title = c.clean_title(title)
    await c.require_unique_title(uow, lst, title)
    return Todo(
        list=lst,
        owner_id=actor.user_id,
        title=title,
        details=c.clean_details(details),
        kind=kind,
        timezone=timezone,
        status=TodoStatus.OPEN,
        assignees=[TodoAssignee(user_id=u) for u in assignees],
        subtasks=[],
    )


async def create_once(
    uow: Uow,
    actor: Actor,
    *,
    list_id: int | None = None,
    title: str,
    details: str | None = None,
    due: DueInput = UNTIMED,
    timezone: str | None = None,
    assignee_ids: Sequence[int] | None = None,
) -> Outcome[TodoView]:
    """One-time to-do: untimed, or timed (one pending occurrence at the due moment).
    `list_id` None: the actor's default list (D45)."""
    lst = await _target_list(uow, actor, list_id)
    zone = await c.effective_zone(uow, actor, timezone)
    resolved = resolve_due(due.date, due.time, zone, uow.clock.now())
    todo = await _new_todo(uow, actor, lst, TodoKind.ONCE, title, details, zone.key, assignee_ids)
    timed = isinstance(resolved, Timed)
    if timed:
        await _require_channel(uow, lst.guild_id)
        todo.due_at = resolved.at
    uow.session.add(todo)
    await c.flush_titles(uow, todo.title, lst.name)
    if timed:
        c.add_pending(uow, todo, resolved.at)
    view = await c.view_of(uow, actor, todo)
    await uow.session.commit()
    return Outcome(value=view, changed_schedule=timed)


async def create_recurring(
    uow: Uow,
    actor: Actor,
    *,
    list_id: int | None = None,
    title: str,
    rule: RecurrenceRule,
    details: str | None = None,
    timezone: str | None = None,
    assignee_ids: Sequence[int] | None = None,
) -> Outcome[TodoView]:
    """Repeating to-do with its first pending occurrence."""
    lst = await _target_list(uow, actor, list_id)
    zone = await c.effective_zone(uow, actor, timezone)
    todo = await _new_todo(
        uow, actor, lst, TodoKind.RECURRING, title, details, zone.key, assignee_ids
    )
    todo.recurrence = recurrence.to_json(rule)
    await _require_channel(uow, lst.guild_id)
    uow.session.add(todo)
    await c.flush_titles(uow, todo.title, lst.name)
    c.add_next_pending(uow, todo, after=uow.clock.now())
    view = await c.view_of(uow, actor, todo)
    await uow.session.commit()
    return Outcome(value=view, changed_schedule=True)


# --- read --------------------------------------------------------------------------------


async def get(uow: Uow, actor: Actor, todo_id: int) -> TodoView:
    todo = await c.load_todo(uow, actor, todo_id)
    if todo.status == TodoStatus.CANCELLED:
        raise NotFound(c.NOT_FOUND)
    return await c.view_of(uow, actor, todo)


async def list_todos(
    uow: Uow,
    actor: Actor,
    list_id: int | None,
    filter: ListFilter = "all",
    page: int = 0,
    page_size: int = 10,
) -> Page[TodoView]:
    """Open to-dos of one list (None: the actor's default, D45/D49): timed (incl.
    repeating) first by next due, then untimed by creation."""
    lst = await lists.resolve(uow, actor, list_id)
    where = [Todo.list_id == lst.id, Todo.status == TodoStatus.OPEN]
    if filter == "timed":
        where.append(or_(Todo.kind == TodoKind.RECURRING, Todo.due_at.is_not(None)))
    elif filter == "untimed":
        where.append(and_(Todo.kind == TodoKind.ONCE, Todo.due_at.is_(None)))

    total = await uow.session.scalar(select(func.count()).select_from(Todo).where(*where)) or 0
    page = max(0, page)
    pending = aliased(Occurrence)
    next_due = func.coalesce(pending.due_at, Todo.due_at)
    todos = list(
        await uow.session.scalars(
            select(Todo)
            .outerjoin(
                pending,
                and_(pending.todo_id == Todo.id, pending.status == OccurrenceStatus.PENDING),
            )
            .where(*where)
            .options(*c.todo_load())
            .order_by(next_due.is_(None), next_due, Todo.created_at, Todo.id)
            .offset(page * page_size)
            .limit(page_size)
        )
    )
    occs = await c.open_occurrences(uow, [t.id for t in todos])
    items = [c.todo_view(actor, t, occs[t.id]) for t in todos]
    await uow.session.commit()  # resolve may have created the server's fallback list
    return Page(items=items, page=page, page_size=page_size, total=total)


async def autocomplete(
    uow: Uow, actor: Actor, query: str, limit: int = 25
) -> list[tuple[int, str, str]]:
    """(id, title, list name) of the server's open to-dos whose title contains `query`;
    prefix matches first. The adapter builds the label (and cuts it to its UI's limit)."""
    if actor.guild_id is None:
        return []
    q = query.strip()
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    stmt = (
        select(Todo.id, Todo.title, TodoList.name)
        .join(TodoList, TodoList.id == Todo.list_id)
        .where(c.visible(actor), Todo.status == TodoStatus.OPEN)
    )
    if q:
        stmt = stmt.where(Todo.title.ilike(f"%{escaped}%", escape="\\"))
    stmt = stmt.order_by(
        case((Todo.title.ilike(f"{escaped}%", escape="\\"), 0), else_=1),
        Todo.created_at.desc(),
        Todo.id.desc(),
    ).limit(limit)
    return [(todo_id, title, name) for todo_id, title, name in await uow.session.execute(stmt)]


# --- change ------------------------------------------------------------------------------


async def _load_for_edit(uow: Uow, actor: Actor, todo_id: int) -> Todo:
    todo = await c.load_todo(uow, actor, todo_id, lock=True)
    c.require_open(todo)
    c.require_edit(actor, todo)
    return todo


async def _retime_once(uow: Uow, todo: Todo, patch: TodoPatch) -> list[Effect]:
    if patch.rule is not None:
        raise InvalidOperation("A one-time to-do has no repeat rule.")
    now = uow.clock.now()
    old_zone = get_zone(todo.timezone)
    zone = get_zone(patch.timezone) if patch.timezone else old_zone
    if patch.due is not None:
        resolved = resolve_due(patch.due.date, patch.due.time, zone, now)
    elif todo.due_at is not None:  # timezone only: same wall-clock time in the new zone
        local = todo.due_at.astimezone(old_zone)
        resolved = resolve_due(local.date(), local.time().replace(tzinfo=None), zone, now)
    else:
        resolved = None
    due_at = resolved.at if isinstance(resolved, Timed) else None
    if due_at is not None:  # validate everything before changing anything
        await _require_channel(uow, todo.guild_id)
    effects, _ = await c.cancel_open(uow, todo, include_sent=True)
    todo.timezone = zone.key
    todo.due_at = due_at
    if due_at is not None:
        c.add_pending(uow, todo, due_at)
    return effects


async def _retime_recurring(uow: Uow, todo: Todo, patch: TodoPatch) -> None:
    if patch.due is not None:
        raise InvalidOperation("A repeating to-do has no date; change its repeat rule instead.")
    if patch.timezone:
        todo.timezone = get_zone(patch.timezone).key
    if patch.rule is not None:
        todo.recurrence = recurrence.to_json(patch.rule)
    # The sent reminder (if any) stays: it is the current occurrence and can still be done.
    await c.cancel_open(uow, todo, include_sent=False)
    c.add_next_pending(uow, todo, after=uow.clock.now())


async def edit(uow: Uow, actor: Actor, todo_id: int, patch: TodoPatch) -> Outcome[TodoView]:
    """Change title/details/timing. New timing replaces the pending occurrence; for a
    one-time to-do an already-sent reminder is cancelled and its message deleted."""
    todo = await _load_for_edit(uow, actor, todo_id)
    if patch.title is not None:
        title = c.clean_title(patch.title)
        await c.require_unique_title(uow, todo.list, title, exclude_todo_id=todo.id)
        todo.title = title
    if "details" in patch.model_fields_set:
        todo.details = c.clean_details(patch.details)

    effects: list[Effect] = []
    retime = patch.due is not None or patch.rule is not None or bool(patch.timezone)
    if retime:
        if todo.kind == TodoKind.ONCE:
            effects = await _retime_once(uow, todo, patch)
        else:
            await _retime_recurring(uow, todo, patch)
    await c.flush_titles(uow, todo.title, todo.list.name)
    view = await c.view_of(uow, actor, todo)
    await uow.session.commit()
    return Outcome(value=view, effects=effects, changed_schedule=retime)


async def set_details(
    uow: Uow, actor: Actor, todo_id: int, details: str | None
) -> Outcome[TodoView]:
    return await edit(uow, actor, todo_id, TodoPatch(details=details))


async def set_assignees(
    uow: Uow, actor: Actor, todo_id: int, user_ids: Sequence[int]
) -> Outcome[TodoView]:
    """Replace the assignees. They get pinged; they don't need to be collaborators (D50)."""
    todo = await _load_for_edit(uow, actor, todo_id)
    wanted = _clean_assignees(actor, list(user_ids))
    for assignee in list(todo.assignees):
        if assignee.user_id not in wanted:
            todo.assignees.remove(assignee)
    current = {a.user_id for a in todo.assignees}
    todo.assignees.extend(TodoAssignee(user_id=u) for u in wanted if u not in current)
    view = await c.view_of(uow, actor, todo)
    await uow.session.commit()
    return Outcome(value=view)


async def complete(uow: Uow, actor: Actor, todo_id: int) -> Outcome[TodoView]:
    """One-time: done (closing its reminder). Repeating: check off the current occurrence
    (the sent reminder if there is one, else the next pending one)."""
    todo = await c.load_todo(uow, actor, todo_id, lock=True)
    c.require_open(todo)
    c.require_complete(actor, todo)
    occs = (await c.open_occurrences(uow, [todo.id]))[todo.id]
    active = c.find(occs, OccurrenceStatus.SENT) or c.find(occs, OccurrenceStatus.PENDING)
    if active is not None:
        effects, changed = await c.finish_occurrence(uow, actor, todo, active, occs)
    elif todo.kind == TodoKind.ONCE:
        c.mark_todo_done(todo, actor, uow.clock.now())
        effects, changed = [], False
    else:
        raise InvalidOperation("This repeating to-do has nothing to check off right now.")
    view = await c.view_of(uow, actor, todo)
    await uow.session.commit()
    return Outcome(value=view, effects=effects, changed_schedule=changed)


async def delete(uow: Uow, actor: Actor, todo_id: int) -> Outcome[TodoView]:
    """Soft delete: status cancelled, open occurrences cancelled, reminder deleted."""
    todo = await _load_for_edit(uow, actor, todo_id)
    effects, had_pending = await c.cancel_open(uow, todo, include_sent=True)
    todo.status = TodoStatus.CANCELLED
    view = await c.view_of(uow, actor, todo)
    await uow.session.commit()
    return Outcome(value=view, effects=effects, changed_schedule=had_pending)


async def move(uow: Uow, actor: Actor, todo_id: int, list_id: int) -> Outcome[TodoView]:
    """Move a to-do to another list of the same server (D48). Needs edit rights on its
    list and add rights on the target; the title must be free there (D44). Reminders,
    subtasks and assignees stay."""
    todo = await _load_for_edit(uow, actor, todo_id)
    target = await lists.resolve(uow, actor, list_id)
    if target.id == todo.list_id:
        raise InvalidOperation(f"{bold(todo.title)} is already on {bold(target.name)}.")
    c.require_add(actor, target)
    await c.require_unique_title(uow, target, todo.title, exclude_todo_id=todo.id)
    todo.list = target
    await c.flush_titles(uow, todo.title, target.name)
    view = await c.view_of(uow, actor, todo)
    await uow.session.commit()
    return Outcome(value=view)
