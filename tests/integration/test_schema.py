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
    Subtask,
    Todo,
    TodoAssignee,
    TodoKind,
    TodoList,
    TodoStatus,
)

DUE = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
RULE = {"type": "daily", "times": ["08:00"]}
GUILD = 10


@pytest.fixture
async def todo_list(session: AsyncSession) -> TodoList:
    """A server list the to-dos below belong to (owner None, like the fallback list)."""
    lst = TodoList(guild_id=GUILD, name="L", owner_id=None, collaborators=[])
    session.add(lst)
    await session.flush()
    assert lst.id is not None
    return lst


def make_todo(lst: TodoList, **overrides: Any) -> Todo:
    defaults: dict[str, Any] = {
        "list_id": lst.id,
        "guild_id": lst.guild_id,
        "owner_id": 1,
        "title": "t",
        "kind": TodoKind.ONCE,
        "timezone": "UTC",
    }
    defaults.update(overrides)
    return Todo(**defaults)


async def _add_todo(session: AsyncSession, lst: TodoList, title: str = "t") -> int:
    todo = make_todo(lst, title=title)
    session.add(todo)
    await session.flush()
    assert todo.id is not None
    return todo.id


# --- Accepted rows -----------------------------------------------------------------------------


async def test_once_untimed_todo_is_accepted(session: AsyncSession, todo_list: TodoList) -> None:
    session.add(make_todo(todo_list))
    await session.flush()


async def test_once_timed_todo_is_accepted(session: AsyncSession, todo_list: TodoList) -> None:
    session.add(make_todo(todo_list, due_at=DUE))
    await session.flush()


async def test_recurring_todo_with_rule_and_no_due_at_is_accepted(
    session: AsyncSession, todo_list: TodoList
) -> None:
    session.add(make_todo(todo_list, kind=TodoKind.RECURRING, recurrence=RULE, due_at=None))
    await session.flush()


async def test_details_of_exactly_4000_chars_is_accepted(
    session: AsyncSession, todo_list: TodoList
) -> None:
    session.add(make_todo(todo_list, details="x" * 4000))
    await session.flush()


# --- Rejected by CHECK constraints -------------------------------------------------------------

REJECTED_CHECK_CASES = [
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
    session: AsyncSession, todo_list: TodoList, overrides: dict[str, Any]
) -> None:
    session.add(make_todo(todo_list, **overrides))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_todo_must_share_the_guild_of_its_list(
    session: AsyncSession, todo_list: TodoList
) -> None:
    session.add(make_todo(todo_list, guild_id=GUILD + 1))
    with pytest.raises(IntegrityError):
        await session.flush()


# --- Open titles are unique per list (D44) -----------------------------------------------------


async def test_open_titles_are_unique_per_list_case_insensitively(
    session: AsyncSession, todo_list: TodoList
) -> None:
    session.add_all([make_todo(todo_list, title="Bins"), make_todo(todo_list, title="bins")])
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_done_todo_may_share_an_open_title(
    session: AsyncSession, todo_list: TodoList
) -> None:
    session.add_all(
        [
            make_todo(todo_list, title="Bins"),
            make_todo(todo_list, title="bins", status=TodoStatus.DONE),
        ]
    )
    await session.flush()


# --- Occurrence partial unique indexes ---------------------------------------------------------


async def test_two_pending_occurrences_for_one_todo_are_rejected(
    session: AsyncSession, todo_list: TodoList
) -> None:
    todo_id = await _add_todo(session, todo_list)
    session.add_all(
        [
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.PENDING),
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.PENDING),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_two_sent_occurrences_for_one_todo_are_rejected(
    session: AsyncSession, todo_list: TodoList
) -> None:
    todo_id = await _add_todo(session, todo_list)
    session.add_all(
        [
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.SENT),
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.SENT),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_one_pending_and_one_sent_occurrence_are_accepted(
    session: AsyncSession, todo_list: TodoList
) -> None:
    todo_id = await _add_todo(session, todo_list)
    session.add_all(
        [
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.PENDING),
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.SENT),
        ]
    )
    await session.flush()


async def test_two_missed_occurrences_for_one_todo_are_accepted(
    session: AsyncSession, todo_list: TodoList
) -> None:
    todo_id = await _add_todo(session, todo_list)
    session.add_all(
        [
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.MISSED),
            Occurrence(todo_id=todo_id, due_at=DUE, status=OccurrenceStatus.MISSED),
        ]
    )
    await session.flush()


async def test_pending_occurrences_on_two_todos_are_accepted(
    session: AsyncSession, todo_list: TodoList
) -> None:
    first_id = await _add_todo(session, todo_list)
    second_id = await _add_todo(session, todo_list, title="u")
    session.add_all(
        [
            Occurrence(todo_id=first_id, due_at=DUE, status=OccurrenceStatus.PENDING),
            Occurrence(todo_id=second_id, due_at=DUE, status=OccurrenceStatus.PENDING),
        ]
    )
    await session.flush()


# --- Storage and ORM behaviour -----------------------------------------------------------------


async def test_enum_values_are_stored_as_lowercase_values(
    session: AsyncSession, todo_list: TodoList
) -> None:
    todo = make_todo(todo_list)
    session.add(todo)
    await session.flush()
    assert todo.id is not None

    row = (
        await session.execute(
            text("SELECT kind, status FROM todos WHERE id = :id"), {"id": todo.id}
        )
    ).one()
    assert tuple(row) == ("once", "open")

    occurrence = Occurrence(todo_id=todo.id, due_at=DUE)
    session.add(occurrence)
    await session.flush()
    status = (
        await session.execute(
            text("SELECT status FROM occurrences WHERE id = :id"), {"id": occurrence.id}
        )
    ).scalar_one()
    assert status == "pending"


async def test_subtasks_are_ordered_by_position_then_id(
    session: AsyncSession, todo_list: TodoList
) -> None:
    todo_id = await _add_todo(session, todo_list)
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


async def _add_todo_with_children(session: AsyncSession, lst: TodoList) -> int:
    todo = make_todo(
        lst,
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


async def test_deleting_todo_via_sql_cascades_to_children(
    session: AsyncSession, todo_list: TodoList
) -> None:
    todo_id = await _add_todo_with_children(session, todo_list)
    await session.execute(delete(Todo).where(Todo.id == todo_id))
    assert await _child_counts(session, todo_id) == (0, 0, 0)


async def test_deleting_todo_via_orm_cascades_to_children(
    session: AsyncSession, todo_list: TodoList
) -> None:
    todo_id = await _add_todo_with_children(session, todo_list)
    session.expunge_all()

    todo = await session.get(Todo, todo_id)
    assert todo is not None
    await session.delete(todo)
    await session.flush()
    assert await _child_counts(session, todo_id) == (0, 0, 0)
