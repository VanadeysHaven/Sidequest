"""Schema constraints, enum storage, ordering and cascades against a migrated PostgreSQL DB."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sidequest.db.models import (
    Occurrence,
    OccurrenceStatus,
    Scope,
    Subtask,
    Todo,
    TodoAssignee,
    TodoKind,
)

DUE = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
RULE = {"type": "daily", "times": ["08:00"]}


def make_todo(**overrides: Any) -> Todo:
    defaults: dict[str, Any] = {
        "scope": Scope.PERSONAL,
        "guild_id": None,
        "owner_id": 1,
        "title": "t",
        "kind": TodoKind.ONCE,
        "timezone": "UTC",
    }
    defaults.update(overrides)
    return Todo(**defaults)


async def _add_todo(session: AsyncSession) -> int:
    todo = make_todo()
    session.add(todo)
    await session.flush()
    assert todo.id is not None
    return todo.id


# --- Accepted rows -----------------------------------------------------------------------------


async def test_personal_once_untimed_todo_is_accepted(session: AsyncSession) -> None:
    session.add(make_todo())
    await session.flush()


async def test_server_once_timed_todo_is_accepted(session: AsyncSession) -> None:
    session.add(make_todo(scope=Scope.SERVER, guild_id=10, due_at=DUE))
    await session.flush()


async def test_recurring_todo_with_rule_and_no_due_at_is_accepted(session: AsyncSession) -> None:
    session.add(make_todo(kind=TodoKind.RECURRING, recurrence=RULE, due_at=None))
    await session.flush()


async def test_details_of_exactly_4000_chars_is_accepted(session: AsyncSession) -> None:
    session.add(make_todo(details="x" * 4000))
    await session.flush()


# --- Rejected by CHECK constraints -------------------------------------------------------------

REJECTED_CHECK_CASES = [
    pytest.param({"scope": Scope.SERVER, "guild_id": None}, id="server-without-guild"),
    pytest.param({"scope": Scope.PERSONAL, "guild_id": 10}, id="personal-with-guild"),
    pytest.param({"kind": TodoKind.RECURRING, "recurrence": None}, id="recurring-without-rule"),
    pytest.param(
        {"kind": TodoKind.RECURRING, "recurrence": RULE, "due_at": DUE},
        id="recurring-with-due-at",
    ),
    pytest.param({"kind": TodoKind.ONCE, "recurrence": RULE}, id="once-with-rule"),
    pytest.param({"details": "x" * 4001}, id="details-too-long"),
]


@pytest.mark.parametrize("overrides", REJECTED_CHECK_CASES)
async def test_check_constraint_rejects_invalid_todo(
    session: AsyncSession, overrides: dict[str, Any]
) -> None:
    session.add(make_todo(**overrides))
    with pytest.raises(IntegrityError):
        await session.flush()


# --- Occurrence partial unique indexes ---------------------------------------------------------


async def test_two_pending_occurrences_for_one_todo_are_rejected(session: AsyncSession) -> None:
    todo_id = await _add_todo(session)
    session.add_all(
        [
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.PENDING),
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.PENDING),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_two_sent_occurrences_for_one_todo_are_rejected(session: AsyncSession) -> None:
    todo_id = await _add_todo(session)
    session.add_all(
        [
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.SENT),
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.SENT),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_one_pending_and_one_sent_occurrence_are_accepted(session: AsyncSession) -> None:
    todo_id = await _add_todo(session)
    session.add_all(
        [
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.PENDING),
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.SENT),
        ]
    )
    await session.flush()


async def test_two_missed_occurrences_for_one_todo_are_accepted(session: AsyncSession) -> None:
    todo_id = await _add_todo(session)
    session.add_all(
        [
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.MISSED),
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.MISSED),
        ]
    )
    await session.flush()


async def test_pending_occurrences_on_two_todos_are_accepted(session: AsyncSession) -> None:
    first_id = await _add_todo(session)
    second_id = await _add_todo(session)
    session.add_all(
        [
            Occurrence(todo_id=first_id, due_at=DUE, status=OccurrenceStatus.PENDING),
            Occurrence(todo_id=second_id, due_at=DUE, status=OccurrenceStatus.PENDING),
        ]
    )
    await session.flush()


# --- Storage and ORM behaviour -----------------------------------------------------------------


async def test_enum_values_are_stored_as_lowercase_values(session: AsyncSession) -> None:
    todo = make_todo()
    session.add(todo)
    await session.flush()
    assert todo.id is not None

    row = (
        await session.execute(
            text("SELECT scope, kind, status FROM todos WHERE id = :id"), {"id": todo.id}
        )
    ).one()
    assert tuple(row) == ("personal", "once", "open")

    occurrence = Occurrence(todo_id=todo.id, due_at=DUE)
    session.add(occurrence)
    await session.flush()
    status = (
        await session.execute(
            text("SELECT status FROM occurrences WHERE id = :id"), {"id": occurrence.id}
        )
    ).scalar_one()
    assert status == "pending"


async def test_subtasks_are_ordered_by_position_then_id(session: AsyncSession) -> None:
    todo_id = await _add_todo(session)
    session.add_all(
        [
            Subtask(todo_id=todo_id, position=2, title="c"),
            Subtask(todo_id=todo_id, position=1, title="a"),
            Subtask(todo_id=todo_id, position=1, title="b"),
        ]
    )
    await session.flush()
    session.expunge_all()

    todo = (
        await session.execute(
            select(Todo).where(Todo.id == todo_id).options(selectinload(Todo.subtasks))
        )
    ).scalar_one()
    assert [subtask.title for subtask in todo.subtasks] == ["a", "b", "c"]


async def _add_todo_with_children(session: AsyncSession) -> int:
    todo = make_todo(
        assignees=[TodoAssignee(user_id=100), TodoAssignee(user_id=101)],
        subtasks=[
            Subtask(position=1, title="s1"),
            Subtask(position=2, title="s2"),
        ],
        occurrences=[Occurrence(due_at=DUE, status=OccurrenceStatus.PENDING)],
    )
    session.add(todo)
    await session.flush()
    assert todo.id is not None
    return todo.id


async def _child_counts(session: AsyncSession, todo_id: int) -> tuple[int, int, int]:
    assignees = await session.scalar(
        select(func.count()).select_from(TodoAssignee).where(TodoAssignee.todo_id == todo_id)
    )
    subtasks = await session.scalar(
        select(func.count()).select_from(Subtask).where(Subtask.todo_id == todo_id)
    )
    occurrences = await session.scalar(
        select(func.count()).select_from(Occurrence).where(Occurrence.todo_id == todo_id)
    )
    return assignees or 0, subtasks or 0, occurrences or 0


async def test_deleting_todo_via_sql_cascades_to_children(session: AsyncSession) -> None:
    todo_id = await _add_todo_with_children(session)
    await session.execute(delete(Todo).where(Todo.id == todo_id))
    assert await _child_counts(session, todo_id) == (0, 0, 0)


async def test_deleting_todo_via_orm_cascades_to_children(session: AsyncSession) -> None:
    todo_id = await _add_todo_with_children(session)
    session.expunge_all()

    todo = await session.get(Todo, todo_id)
    assert todo is not None
    await session.delete(todo)
    await session.flush()
    assert await _child_counts(session, todo_id) == (0, 0, 0)
