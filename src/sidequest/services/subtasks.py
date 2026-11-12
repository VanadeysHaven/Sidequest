"""Subtasks: a simple ordered checklist per to-do (D4). Reset happens when an occurrence
of a repeating to-do is closed (see `_common.finish_occurrence` and `claim_due`)."""

from collections.abc import Sequence

from sqlalchemy import select

from sidequest.core.errors import InvalidOperation, LimitExceeded, NotFound
from sidequest.core.limits import SUBTASK_TITLE_MAX, SUBTASKS_MAX
from sidequest.db.models import Subtask, Todo
from sidequest.services import _common as c
from sidequest.services.actor import Actor
from sidequest.services.dto import TodoView
from sidequest.services.effects import Outcome
from sidequest.services.uow import Uow

SUBTASK_NOT_FOUND = "That subtask doesn't exist (or isn't on a list you can see here)."


def _clean_subtask_title(title: str) -> str:
    title = title.strip()
    if not title:
        raise InvalidOperation("A subtask title can't be empty.")
    if len(title) > SUBTASK_TITLE_MAX:
        raise LimitExceeded(
            f"A subtask title is too long ({len(title)}/{SUBTASK_TITLE_MAX} characters)."
        )
    return title


async def _todo_of_subtask(uow: Uow, actor: Actor, subtask_id: int) -> tuple[Todo, Subtask]:
    """Lock the parent to-do and return it with the subtask (`NotFound` if not visible)."""
    todo_id = await uow.session.scalar(select(Subtask.todo_id).where(Subtask.id == subtask_id))
    if todo_id is None:
        raise NotFound(SUBTASK_NOT_FOUND)
    try:
        todo = await c.load_todo(uow, actor, todo_id, lock=True)
    except NotFound:
        raise NotFound(SUBTASK_NOT_FOUND) from None
    subtask = next((s for s in todo.subtasks if s.id == subtask_id), None)
    if subtask is None:  # removed between the two queries
        raise NotFound(SUBTASK_NOT_FOUND)
    c.require_open(todo)
    return todo, subtask


async def _done(uow: Uow, actor: Actor, todo: Todo) -> Outcome[TodoView]:
    view = await c.view_of(uow, actor, todo)
    await uow.session.commit()
    return Outcome(value=view)


async def add(uow: Uow, actor: Actor, todo_id: int, titles: Sequence[str]) -> Outcome[TodoView]:
    """Append subtasks (≤ 50 per to-do, each title ≤ 100 chars). Empty entries are skipped."""
    todo = await c.load_todo(uow, actor, todo_id, lock=True)
    c.require_open(todo)
    c.require_edit(actor, todo)
    cleaned = [_clean_subtask_title(t) for t in titles if t.strip()]
    if not cleaned:
        raise InvalidOperation("Give at least one subtask title.")
    if len(todo.subtasks) + len(cleaned) > SUBTASKS_MAX:
        room = SUBTASKS_MAX - len(todo.subtasks)
        raise LimitExceeded(
            f"A to-do can have at most {SUBTASKS_MAX} subtasks; there is room for {room} more."
        )
    position = max((s.position for s in todo.subtasks), default=-1)
    for offset, title in enumerate(cleaned, start=1):
        todo.subtasks.append(Subtask(position=position + offset, title=title))
    return await _done(uow, actor, todo)


async def remove(uow: Uow, actor: Actor, subtask_id: int) -> Outcome[TodoView]:
    todo, subtask = await _todo_of_subtask(uow, actor, subtask_id)
    c.require_edit(actor, todo)
    todo.subtasks.remove(subtask)
    return await _done(uow, actor, todo)


async def set_done(
    uow: Uow,
    actor: Actor,
    todo_id: int,
    done_ids: set[int],
    within: set[int] | None = None,
) -> Outcome[TodoView]:
    """Tick exactly `done_ids` among the subtasks in `within` (one select page; None = all).

    Subtasks outside `within` are left alone; ids that aren't this to-do's are ignored.
    Ticking needs the same right as checking off (D50).
    """
    todo = await c.load_todo(uow, actor, todo_id, lock=True)
    c.require_open(todo)
    c.require_complete(actor, todo)
    now = uow.clock.now()
    for sub in todo.subtasks:
        if within is not None and sub.id not in within:
            continue
        if sub.id in done_ids:
            if sub.done_at is None:
                sub.done_at = now
                sub.done_by = actor.user_id
        else:
            sub.done_at = None
            sub.done_by = None
    return await _done(uow, actor, todo)


async def toggle(uow: Uow, actor: Actor, subtask_id: int) -> Outcome[TodoView]:
    todo, subtask = await _todo_of_subtask(uow, actor, subtask_id)
    c.require_complete(actor, todo)
    if subtask.done_at is None:
        subtask.done_at = uow.clock.now()
        subtask.done_by = actor.user_id
    else:
        subtask.done_at = None
        subtask.done_by = None
    return await _done(uow, actor, todo)
