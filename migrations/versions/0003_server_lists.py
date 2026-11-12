"""Server lists: named lists per server, collaborators, per-user default list (S8).

Drops personal to-dos and everything DM-related (D40). Every server gets one ownerless
"Default List" (its fallback list, D42) holding all its existing to-dos.

Downgrade restores the 0002 shape: every to-do becomes a server to-do again and the lists,
collaborators and default-list settings are dropped. Personal to-dos deleted by the
upgrade can't come back; restore a backup for that.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12
"""

import logging
from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

DEFAULT_LIST_NAME = "Default List"
TITLE_MAX = 200


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def _numbered(title: str, n: int) -> str:
    suffix = f" ({n})"
    return title[: TITLE_MAX - len(suffix)] + suffix


def _dedupe_open_titles(bind: sa.Connection) -> int:
    """D44: within each list, open to-dos with the same title (any case) keep the oldest
    as-is; the others become "title (2)", "title (3)", … skipping names already taken."""
    rows = bind.execute(
        sa.text(
            "SELECT id, list_id, title FROM todos WHERE status = 'open' "
            "ORDER BY list_id, created_at, id"
        )
    ).all()
    taken: dict[int, set[str]] = defaultdict(set)
    for _, list_id, title in rows:
        taken[list_id].add(title.lower())

    seen: dict[int, set[str]] = defaultdict(set)
    renamed = 0
    for todo_id, list_id, title in rows:
        key = title.lower()
        if key not in seen[list_id]:
            seen[list_id].add(key)
            continue
        n = 2
        while _numbered(title, n).lower() in taken[list_id]:
            n += 1
        new_title = _numbered(title, n)
        taken[list_id].add(new_title.lower())
        seen[list_id].add(new_title.lower())
        bind.execute(
            sa.text("UPDATE todos SET title = :title WHERE id = :id"),
            {"title": new_title, "id": todo_id},
        )
        renamed += 1
    return renamed


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Personal to-dos go (D40); subtasks, assignees and occurrences cascade.
    deleted = bind.execute(sa.text("DELETE FROM todos WHERE scope = 'personal'")).rowcount
    log.info("Deleted %s personal to-do(s)", deleted)

    # 2. Lists.
    op.create_table(
        "todo_lists",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_todo_lists")),
        sa.UniqueConstraint("id", "guild_id", name=op.f("uq_todo_lists_id_guild_id")),
    )
    op.create_index(
        "uq_todo_lists_guild_id_name",
        "todo_lists",
        ["guild_id", sa.text("lower(name)")],
        unique=True,
    )

    # 3. Every server with to-dos gets a settings row.
    op.execute(
        "INSERT INTO guild_settings (guild_id) SELECT DISTINCT guild_id FROM todos "
        "WHERE guild_id IS NOT NULL ON CONFLICT DO NOTHING"
    )

    # 4. One ownerless "Default List" per server, set as its fallback list.
    op.add_column("guild_settings", sa.Column("default_list_id", sa.BigInteger(), nullable=True))
    bind.execute(
        sa.text(
            "WITH created AS ("
            "  INSERT INTO todo_lists (guild_id, name) SELECT guild_id, :name FROM guild_settings"
            "  RETURNING id, guild_id"
            ") "
            "UPDATE guild_settings g SET default_list_id = created.id "
            "FROM created WHERE g.guild_id = created.guild_id"
        ),
        {"name": DEFAULT_LIST_NAME},
    )
    op.create_foreign_key(
        op.f("fk_guild_settings_default_list_id_todo_lists"),
        "guild_settings",
        "todo_lists",
        ["default_list_id", "guild_id"],
        ["id", "guild_id"],
        ondelete="RESTRICT",
    )

    # 5. Every to-do goes on its server's Default List.
    op.add_column("todos", sa.Column("list_id", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE todos t SET list_id = g.default_list_id "
        "FROM guild_settings g WHERE g.guild_id = t.guild_id"
    )
    op.alter_column("todos", "list_id", existing_type=sa.BigInteger(), nullable=False)
    op.alter_column("todos", "guild_id", existing_type=sa.BigInteger(), nullable=False)

    # 6. Open titles must be unique per list before the unique index exists.
    renamed = _dedupe_open_titles(bind)
    log.info("Renamed %s open to-do(s) with a duplicate title", renamed)

    # 7. Drop scope; new indexes, FKs and tables.
    op.drop_index(
        "ix_todos_personal_owner_status",
        table_name="todos",
        postgresql_where=sa.text("scope = 'personal'"),
    )
    op.drop_index(
        "ix_todos_server_guild_status",
        table_name="todos",
        postgresql_where=sa.text("scope = 'server'"),
    )
    op.drop_constraint(op.f("ck_todos_scope_guild"), "todos", type_="check")
    op.drop_column("todos", "scope")  # also drops its CHECK (ck_todos_scope)
    op.create_index("ix_todos_guild_id_status", "todos", ["guild_id", "status"], unique=False)
    op.create_index("ix_todos_list_id_status", "todos", ["list_id", "status"], unique=False)
    op.create_index(
        "uq_todos_list_id_open_title",
        "todos",
        ["list_id", sa.text("lower(title)")],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_foreign_key(
        op.f("fk_todos_list_id_todo_lists"),
        "todos",
        "todo_lists",
        ["list_id", "guild_id"],
        ["id", "guild_id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "user_guild_settings",
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("default_list_id", sa.BigInteger(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["default_list_id", "guild_id"],
            ["todo_lists.id", "todo_lists.guild_id"],
            name=op.f("fk_user_guild_settings_default_list_id_todo_lists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "guild_id", name=op.f("pk_user_guild_settings")),
    )
    op.create_table(
        "list_collaborators",
        sa.Column("list_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["todo_lists.id"],
            name=op.f("fk_list_collaborators_list_id_todo_lists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("list_id", "user_id", name=op.f("pk_list_collaborators")),
    )
    op.create_index(
        "ix_list_collaborators_user_id", "list_collaborators", ["user_id"], unique=False
    )

    op.drop_column("user_settings", "dm_failed_at")


def downgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("dm_failed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_index("ix_list_collaborators_user_id", table_name="list_collaborators")
    op.drop_table("list_collaborators")
    op.drop_table("user_guild_settings")

    op.drop_constraint(op.f("fk_todos_list_id_todo_lists"), "todos", type_="foreignkey")
    op.drop_index(
        "uq_todos_list_id_open_title",
        table_name="todos",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.drop_index("ix_todos_list_id_status", table_name="todos")
    op.drop_index("ix_todos_guild_id_status", table_name="todos")

    op.add_column(
        "todos",
        sa.Column("scope", sa.String(length=16), server_default="server", nullable=False),
    )
    op.alter_column("todos", "scope", existing_type=sa.String(length=16), server_default=None)
    op.create_check_constraint(op.f("ck_todos_scope"), "todos", "scope IN ('server', 'personal')")
    op.create_check_constraint(
        op.f("ck_todos_scope_guild"), "todos", "(scope = 'server') = (guild_id IS NOT NULL)"
    )
    op.alter_column("todos", "guild_id", existing_type=sa.BigInteger(), nullable=True)
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
    op.drop_column("todos", "list_id")

    op.drop_constraint(
        op.f("fk_guild_settings_default_list_id_todo_lists"), "guild_settings", type_="foreignkey"
    )
    op.drop_column("guild_settings", "default_list_id")

    op.drop_index("uq_todo_lists_guild_id_name", table_name="todo_lists")
    op.drop_table("todo_lists")
