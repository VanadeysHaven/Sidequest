"""History cleanup (D8): deletes old finished history so the database does not grow forever.

Two kinds of rows are deleted, and only when they are older than the cutoff:

- To-dos that are ``done`` or ``cancelled``, judged by ``coalesce(completed_at, updated_at)``.
  Their subtasks, assignees and occurrences go with them (ON DELETE CASCADE).
- Closed reminder occurrences (``done``, ``missed``, ``failed``, ``cancelled``) of repeating
  to-dos that are still open. Pending and sent occurrences are never deleted, and the
  occurrences of one-time to-dos only go away together with the to-do itself.
"""

from datetime import datetime

from sqlalchemy import delete, func, select

from sidequest.core.enums import OccurrenceStatus, TodoKind, TodoStatus
from sidequest.db.models import Occurrence, Todo
from sidequest.services.model import StrictModel
from sidequest.services.uow import Uow

CLOSED_OCCURRENCE_STATUSES = (
    OccurrenceStatus.DONE,
    OccurrenceStatus.MISSED,
    OccurrenceStatus.FAILED,
    OccurrenceStatus.CANCELLED,
)
FINISHED_TODO_STATUSES = (TodoStatus.DONE, TodoStatus.CANCELLED)


class PurgeResult(StrictModel):
    todos: int
    occurrences: int


async def purge_history(uow: Uow, older_than: datetime) -> PurgeResult:
    """Commits. Returns how many rows were deleted (cascaded child rows not counted)."""
    occurrence_result = await uow.session.execute(
        delete(Occurrence)
        .where(
            Occurrence.status.in_(CLOSED_OCCURRENCE_STATUSES),
            Occurrence.due_at < older_than,
            Occurrence.todo_id.in_(
                select(Todo.id).where(
                    Todo.status == TodoStatus.OPEN,
                    Todo.kind == TodoKind.RECURRING,
                )
            ),
        )
        .execution_options(synchronize_session=False)
    )
    todo_result = await uow.session.execute(
        delete(Todo)
        .where(
            Todo.status.in_(FINISHED_TODO_STATUSES),
            func.coalesce(Todo.completed_at, Todo.updated_at) < older_than,
        )
        .execution_options(synchronize_session=False)
    )
    await uow.session.commit()
    return PurgeResult(todos=todo_result.rowcount, occurrences=occurrence_result.rowcount)
