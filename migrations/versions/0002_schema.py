"""Full schema: settings, todos, assignees, subtasks, occurrences, app_meta (S2).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_meta",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_meta")),
    )
    op.create_table(
        "guild_settings",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("reminder_channel_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("guild_id", name=op.f("pk_guild_settings")),
    )
    op.create_table(
        "todos",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "server",
                "personal",
                name="scope",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("guild_id", sa.BigInteger(), nullable=True),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "once",
                "recurring",
                name="kind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("recurrence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "done",
                "cancelled",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope = 'server') = (guild_id IS NOT NULL)", name=op.f("ck_todos_scope_guild")
        ),
        sa.CheckConstraint(
            "kind <> 'once' OR recurrence IS NULL", name=op.f("ck_todos_once_no_rule")
        ),
        sa.CheckConstraint(
            "kind <> 'recurring' OR (recurrence IS NOT NULL AND due_at IS NULL)",
            name=op.f("ck_todos_recurring_rule"),
        ),
        sa.CheckConstraint("char_length(details) <= 4000", name=op.f("ck_todos_details_length")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_todos")),
    )
    op.create_index(
        "ix_todos_personal_owner_status",
        "todos",
        ["owner_id", "status"],
        unique=False,
        postgresql_where=sa.text("scope = 'personal'"),
    )
    op.create_index(
        "ix_todos_server_guild_status",
        "todos",
        ["guild_id", "status"],
        unique=False,
        postgresql_where=sa.text("scope = 'server'"),
    )
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("tz_hint_shown", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("dm_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_settings")),
    )
    op.create_table(
        "occurrences",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("todo_id", sa.BigInteger(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "sent",
                "done",
                "missed",
                "cancelled",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("late", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["todo_id"], ["todos.id"], name=op.f("fk_occurrences_todo_id_todos"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_occurrences")),
    )
    op.create_index(
        "ix_occurrences_status_due_at", "occurrences", ["status", "due_at"], unique=False
    )
    op.create_index("ix_occurrences_todo_id", "occurrences", ["todo_id"], unique=False)
    op.create_index(
        "uq_occurrences_todo_id_pending",
        "occurrences",
        ["todo_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_occurrences_todo_id_sent",
        "occurrences",
        ["todo_id"],
        unique=True,
        postgresql_where=sa.text("status = 'sent'"),
    )
    op.create_table(
        "subtasks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("todo_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["todo_id"], ["todos.id"], name=op.f("fk_subtasks_todo_id_todos"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subtasks")),
    )
    op.create_index("ix_subtasks_todo_id", "subtasks", ["todo_id"], unique=False)
    op.create_table(
        "todo_assignees",
        sa.Column("todo_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["todo_id"],
            ["todos.id"],
            name=op.f("fk_todo_assignees_todo_id_todos"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("todo_id", "user_id", name=op.f("pk_todo_assignees")),
    )
    op.create_index("ix_todo_assignees_user_id", "todo_assignees", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_todo_assignees_user_id", table_name="todo_assignees")
    op.drop_table("todo_assignees")
    op.drop_index("ix_subtasks_todo_id", table_name="subtasks")
    op.drop_table("subtasks")
    op.drop_index(
        "uq_occurrences_todo_id_sent",
        table_name="occurrences",
        postgresql_where=sa.text("status = 'sent'"),
    )
    op.drop_index(
        "uq_occurrences_todo_id_pending",
        table_name="occurrences",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index("ix_occurrences_todo_id", table_name="occurrences")
    op.drop_index("ix_occurrences_status_due_at", table_name="occurrences")
    op.drop_table("occurrences")
    op.drop_table("user_settings")
    op.drop_index(
        "ix_todos_server_guild_status",
        table_name="todos",
        postgresql_where=sa.text("scope = 'server'"),
    )
    op.drop_index(
        "ix_todos_personal_owner_status",
        table_name="todos",
        postgresql_where=sa.text("scope = 'personal'"),
    )
    op.drop_table("todos")
    op.drop_table("guild_settings")
    op.drop_table("app_meta")
