"""Undo a check-off (D60–D66).

The check-off services return an `UndoToken` with the state from before; the bot keeps it
in memory (no storage, D66). `undo` re-checks everything against the database first and
refuses (nothing changes) when putting it back would clash with what happened since (D65).
"""

from sidequest.core.enums import OccurrenceStatus, TodoKind, TodoStatus
from sidequest.core.errors import Forbidden, InvalidOperation, NotFound
from sidequest.core.limits import UNDO_WINDOW
from sidequest.core.text import bold
from sidequest.db.models import Occurrence, Todo
from sidequest.services import _common as c
from sidequest.services import occurrences
from sidequest.services.actor import Actor
from sidequest.services.dto import DueReminder, Undone, UndoToken
from sidequest.services.effects import Outcome
from sidequest.services.uow import Uow

NOT_CHECKED_OFF = "That one isn't checked off any more."
NOT_YOURS = "Only the person who checked it off can undo it."
TOO_LATE = "A check-off can only be undone for 2 hours."


def next_sent(title: str) -> InvalidOperation:
    return InvalidOperation(
        f"Too late to undo: the next reminder for {bold(title)} already went out."
    )


def edited(title: str) -> InvalidOperation:
    return InvalidOperation(
        f"{bold(title)} was changed after it was checked off, so it can't be undone."
    )


def later_first(title: str) -> InvalidOperation:
    return InvalidOperation(f"Undo the later check-off of {bold(title)} first.")


async def undo(uow: Uow, actor: Actor, token: UndoToken) -> Outcome[Undone]:
    """Put a check-off back (D63): the to-do and occurrence as they were, the follow-up
    occurrence the check-off created cancelled, reset subtask ticks restored. A reminder
    that was up is marked sent again without a message and returned as `repost` (D64)."""
    todo = await c.load_todo(uow, actor, token.todo_id, lock=True)
    if todo.status == TodoStatus.CANCELLED:
        raise NotFound(c.NOT_FOUND)
    occ = await _checked_off(uow, actor, todo, token)
    c.require_complete(actor, todo)

    now = uow.clock.now()
    changed = False
    open_occs = (await c.open_occurrences(uow, [todo.id]))[todo.id]
    resend = occ is not None and token.previous == OccurrenceStatus.SENT
    if resend and c.find(open_occs, OccurrenceStatus.SENT) is not None:
        raise next_sent(todo.title)  # one sent reminder per to-do (D7)

    if todo.kind == TodoKind.RECURRING:
        followup = await _followup(uow, todo, token)
        if token.previous == OccurrenceStatus.PENDING:
            # The check-off scheduled the next one; free the one-pending slot again.
            followup.status = OccurrenceStatus.CANCELLED
            await uow.session.flush()
            changed = True
    else:
        await c.require_unique_title(uow, todo.list, todo.title, exclude_todo_id=todo.id)
        todo.status = TodoStatus.OPEN
        todo.completed_at = None
        todo.completed_by = None
        await c.flush_titles(uow, todo.title, todo.list.name)

    if occ is not None:
        occ.completed_at = None
        occ.completed_by = None
        if token.previous == OccurrenceStatus.PENDING:
            occ.status = OccurrenceStatus.PENDING
            changed = True
        else:
            occ.status = OccurrenceStatus.SENT
            occ.channel_id = None
            occ.message_id = None
            occ.sent_at = now  # crash recovery waits its minute, so no second copy
            # `late` stays: a late reminder comes back with its "Late — was due" marker.

    _restore_ticks(todo, token)
    view = await c.view_of(uow, actor, todo)
    repost: DueReminder | None = None
    if occ is not None and resend:
        repost = await occurrences.due_reminder(uow, occ, todo)
    await uow.session.commit()
    return Outcome(value=Undone(todo=view, repost=repost), changed_schedule=changed)


async def _checked_off(uow: Uow, actor: Actor, todo: Todo, token: UndoToken) -> Occurrence | None:
    """The checked-off occurrence (None without one), after the D65 checks on it: still
    checked off, by this actor, within the undo window."""
    occ: Occurrence | None = None
    if token.occurrence_id is None:
        if todo.kind != TodoKind.ONCE:
            raise InvalidOperation(NOT_CHECKED_OFF)
        done = todo.status == TodoStatus.DONE
        completed_at, completed_by = todo.completed_at, todo.completed_by
    else:
        occ = await uow.session.get(Occurrence, token.occurrence_id, populate_existing=True)
        if occ is None or occ.todo_id != todo.id:
            raise NotFound(c.NOT_FOUND)
        if token.previous not in c.OPEN_OCCURRENCE:
            raise InvalidOperation(NOT_CHECKED_OFF)
        done = occ.status == OccurrenceStatus.DONE and (
            todo.kind == TodoKind.RECURRING or todo.status == TodoStatus.DONE
        )
        completed_at, completed_by = occ.completed_at, occ.completed_by
    if not done:
        raise InvalidOperation(NOT_CHECKED_OFF)
    if completed_by != actor.user_id:
        raise Forbidden(NOT_YOURS)
    if completed_at is None or uow.clock.now() - completed_at > UNDO_WINDOW:
        raise InvalidOperation(TOO_LATE)
    return occ


async def _followup(uow: Uow, todo: Todo, token: UndoToken) -> Occurrence:
    """A repeating to-do's pending occurrence from right after the check-off; it must
    still be pending, or something happened since that undo would contradict (D65)."""
    followup = None
    if token.followup_id is not None:
        followup = await uow.session.get(Occurrence, token.followup_id, populate_existing=True)
    if followup is None or followup.todo_id != todo.id:
        raise edited(todo.title)
    match followup.status:
        case OccurrenceStatus.PENDING:
            return followup
        case OccurrenceStatus.DONE:
            raise later_first(todo.title)
        case OccurrenceStatus.CANCELLED:
            raise edited(todo.title)
        case _:  # sent, missed, failed
            raise next_sent(todo.title)


def _restore_ticks(todo: Todo, token: UndoToken) -> None:
    """Ticks the check-off reset, for subtasks that still exist and are unticked now."""
    subtasks = {s.id: s for s in todo.subtasks}
    for tick in token.ticks:
        sub = subtasks.get(tick.id)
        if sub is not None and sub.done_at is None:
            sub.done_at = tick.done_at
            sub.done_by = tick.done_by
