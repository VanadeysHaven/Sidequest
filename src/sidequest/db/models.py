"""ORM models: the full Sidequest schema (BRIEF §5, S2 segment doc).

Relationships use ``lazy="raise"``: async code must load them explicitly
(``selectinload``/``joinedload``), so a forgotten load fails loudly instead of
with an obscure greenlet error. Child rows are removed by ``ON DELETE CASCADE``
in the database (``passive_deletes=True``).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sidequest.core.enums import OccurrenceStatus, TodoKind, TodoStatus
from sidequest.db.base import Base

__all__ = [
    "AppMeta",
    "GuildSettings",
    "ListCollaborator",
    "Occurrence",
    "OccurrenceStatus",
    "Subtask",
    "Todo",
    "TodoAssignee",
    "TodoKind",
    "TodoList",
    "TodoStatus",
    "UserGuildSettings",
    "UserSettings",
]

TIMEZONE_LENGTH = 64
LIST_NAME_LENGTH = 50


def _str_enum[E: StrEnum](enum_cls: type[E], name: str) -> Enum:
    """VARCHAR + CHECK (not a native PG enum), storing the enum *values*."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )


def _identity_pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


class _Timestamps:
    # Fetch server-generated values (created_at) on INSERT via RETURNING, so async code
    # can read them after a flush without a lazy load.
    __mapper_args__ = {"eager_defaults": True}

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class UserSettings(_Timestamps, Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    timezone: Mapped[str | None] = mapped_column(String(TIMEZONE_LENGTH))
    tz_hint_shown: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class TodoList(_Timestamps, Base):
    """A named list in one server (D41). `owner_id` NULL = the server's fallback list,
    open to everyone (D42, D51); services never clear an owner."""

    __tablename__ = "todo_lists"
    __table_args__ = (
        # Target of the composite FKs, so nothing can point at another server's list.
        UniqueConstraint("id", "guild_id"),
        # D43: names are unique per server, case-insensitive.
        Index("uq_todo_lists_guild_id_name", "guild_id", text("lower(name)"), unique=True),
    )

    id: Mapped[int] = _identity_pk()
    guild_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(LIST_NAME_LENGTH))
    owner_id: Mapped[int | None] = mapped_column(BigInteger)

    collaborators: Mapped[list["ListCollaborator"]] = relationship(
        back_populates="list",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="ListCollaborator.user_id",
    )

    @property
    def collaborator_ids(self) -> frozenset[int]:
        """Needs `collaborators` loaded."""
        return frozenset(c.user_id for c in self.collaborators)


class ListCollaborator(Base):
    """Users who may work on an owned list's to-dos (D50). Never holds the owner."""

    __tablename__ = "list_collaborators"
    __table_args__ = (Index("ix_list_collaborators_user_id", "user_id"),)

    list_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("todo_lists.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    list: Mapped[TodoList] = relationship(back_populates="collaborators", lazy="raise")


class GuildSettings(_Timestamps, Base):
    __tablename__ = "guild_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["default_list_id", "guild_id"],
            ["todo_lists.id", "todo_lists.guild_id"],
            ondelete="RESTRICT",
        ),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    reminder_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    default_list_id: Mapped[int | None] = mapped_column(BigInteger)
    """The server's fallback list ("Default List", D42). Set on first use."""


class UserGuildSettings(_Timestamps, Base):
    """A user's own default list in one server (D45). The row goes when the list goes."""

    __tablename__ = "user_guild_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["default_list_id", "guild_id"],
            ["todo_lists.id", "todo_lists.guild_id"],
            ondelete="CASCADE",
        ),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    default_list_id: Mapped[int] = mapped_column(BigInteger)


class Todo(_Timestamps, Base):
    __tablename__ = "todos"
    __table_args__ = (
        ForeignKeyConstraint(
            ["list_id", "guild_id"],
            ["todo_lists.id", "todo_lists.guild_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "kind <> 'recurring' OR (recurrence IS NOT NULL AND due_at IS NULL)",
            name="recurring_rule",
        ),
        CheckConstraint("kind <> 'once' OR recurrence IS NULL", name="once_no_rule"),
        CheckConstraint("char_length(details) <= 4000", name="details_length"),
        Index("ix_todos_guild_id_status", "guild_id", "status"),
        Index("ix_todos_list_id_status", "list_id", "status"),
        # D44: open titles are unique per list, case-insensitive.
        Index(
            "uq_todos_list_id_open_title",
            "list_id",
            text("lower(title)"),
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    id: Mapped[int] = _identity_pk()
    guild_id: Mapped[int] = mapped_column(BigInteger)
    list_id: Mapped[int] = mapped_column(BigInteger)
    owner_id: Mapped[int] = mapped_column(BigInteger)
    """The creator. Gives no rights of its own any more (D50)."""
    title: Mapped[str] = mapped_column(String(200))
    details: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[TodoKind] = mapped_column(_str_enum(TodoKind, "kind"))
    due_at: Mapped[datetime | None]
    timezone: Mapped[str] = mapped_column(String(TIMEZONE_LENGTH))
    # none_as_null: Python None must be SQL NULL (not JSON 'null') for the CHECKs to hold.
    recurrence: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    status: Mapped[TodoStatus] = mapped_column(
        _str_enum(TodoStatus, "status"),
        default=TodoStatus.OPEN,
        server_default=TodoStatus.OPEN.value,
    )
    completed_at: Mapped[datetime | None]
    completed_by: Mapped[int | None] = mapped_column(BigInteger)

    assignees: Mapped[list["TodoAssignee"]] = relationship(
        back_populates="todo",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    subtasks: Mapped[list["Subtask"]] = relationship(
        back_populates="todo",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by=lambda: [Subtask.position, Subtask.id],
    )
    occurrences: Mapped[list["Occurrence"]] = relationship(
        back_populates="todo",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="Occurrence.due_at",
    )
    # Last on purpose: the name shadows the builtin `list` for the rest of the class body.
    # Setting it also sets list_id and guild_id (composite FK).
    list: Mapped[TodoList] = relationship(lazy="raise")


class TodoAssignee(Base):
    __tablename__ = "todo_assignees"
    __table_args__ = (Index("ix_todo_assignees_user_id", "user_id"),)

    todo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("todos.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    todo: Mapped[Todo] = relationship(back_populates="assignees", lazy="raise")


class Subtask(Base):
    __tablename__ = "subtasks"
    __table_args__ = (Index("ix_subtasks_todo_id", "todo_id"),)

    id: Mapped[int] = _identity_pk()
    todo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("todos.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(100))
    done_at: Mapped[datetime | None]
    done_by: Mapped[int | None] = mapped_column(BigInteger)

    todo: Mapped[Todo] = relationship(back_populates="subtasks", lazy="raise")


class Occurrence(Base):
    __tablename__ = "occurrences"
    __table_args__ = (
        Index("ix_occurrences_status_due_at", "status", "due_at"),
        # Plain index for lookups by to-do and for the FK cascade.
        Index("ix_occurrences_todo_id", "todo_id"),
        # D7: at most one pending and at most one sent occurrence per to-do.
        Index(
            "uq_occurrences_todo_id_pending",
            "todo_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "uq_occurrences_todo_id_sent",
            "todo_id",
            unique=True,
            postgresql_where=text("status = 'sent'"),
        ),
    )

    id: Mapped[int] = _identity_pk()
    todo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("todos.id", ondelete="CASCADE"))
    due_at: Mapped[datetime]
    status: Mapped[OccurrenceStatus] = mapped_column(
        _str_enum(OccurrenceStatus, "status"),
        default=OccurrenceStatus.PENDING,
        server_default=OccurrenceStatus.PENDING.value,
    )
    sent_at: Mapped[datetime | None]
    late: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None]
    completed_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    todo: Mapped[Todo] = relationship(back_populates="occurrences", lazy="raise")


class AppMeta(Base):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
