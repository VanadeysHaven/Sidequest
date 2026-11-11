"""User and server settings: timezone, one-time hints, reminder channel."""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from sidequest.core.enums import OccurrenceStatus, Scope, TodoStatus
from sidequest.core.errors import Forbidden, InvalidOperation
from sidequest.core.tz import get_zone
from sidequest.db.models import GuildSettings, Occurrence, Todo, UserSettings
from sidequest.services import permissions
from sidequest.services._common import user_timezone
from sidequest.services.actor import Actor
from sidequest.services.dto import GuildSettingsView
from sidequest.services.uow import Uow


async def get_user_timezone(uow: Uow, user_id: int) -> tuple[str, bool]:
    """(IANA name, is_default). `is_default` means the user never set one (D25)."""
    return await user_timezone(uow, user_id)


async def set_user_timezone(uow: Uow, actor: Actor, tz_name: str) -> str:
    """Set the actor's own timezone; returns the canonical name."""
    name = get_zone(tz_name).key
    stmt = insert(UserSettings).values(user_id=actor.user_id, timezone=name)
    stmt = stmt.on_conflict_do_update(
        index_elements=[UserSettings.user_id], set_={"timezone": name}
    )
    await uow.session.execute(stmt)
    await uow.session.commit()
    return name


async def consume_tz_hint(uow: Uow, user_id: int) -> bool:
    """True exactly once for a user without a timezone (D25): "times are in UTC…"."""
    stmt = insert(UserSettings).values(user_id=user_id, tz_hint_shown=True)
    stmt = stmt.on_conflict_do_update(
        index_elements=[UserSettings.user_id],
        set_={"tz_hint_shown": True},
        where=(UserSettings.tz_hint_shown.is_(False)) & (UserSettings.timezone.is_(None)),
    ).returning(UserSettings.user_id)
    shown = (await uow.session.execute(stmt)).first() is not None
    await uow.session.commit()
    return shown


async def consume_dm_failure(uow: Uow, user_id: int) -> datetime | None:
    """When a DM reminder to this user last failed, then clear it (D26). None if not."""
    row = await uow.session.scalar(
        select(UserSettings)
        .where(UserSettings.user_id == user_id, UserSettings.dm_failed_at.is_not(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        return None
    failed_at = row.dm_failed_at
    row.dm_failed_at = None
    await uow.session.commit()
    return failed_at


NO_REMINDER_CHANNEL = "This server has no reminder channel set."


def _require_manage(actor: Actor) -> int:
    """The actor's guild id, if they may change its reminder channel (Manage Server, D6)."""
    if actor.guild_id is None:
        raise InvalidOperation("The reminder channel can only be set in a server.")
    if not permissions.can_manage_guild(actor, actor.guild_id):
        raise Forbidden("You need the Manage Server permission to change the reminder channel.")
    return actor.guild_id


async def set_reminder_channel(uow: Uow, actor: Actor, channel_id: int) -> GuildSettingsView:
    """Requires Manage Server (D6). The adapter verifies the bot can post there first."""
    _require_manage(actor)
    assert actor.guild_id is not None
    stmt = insert(GuildSettings).values(guild_id=actor.guild_id, reminder_channel_id=channel_id)
    stmt = stmt.on_conflict_do_update(
        index_elements=[GuildSettings.guild_id], set_={"reminder_channel_id": channel_id}
    )
    await uow.session.execute(stmt)
    await uow.session.commit()
    return GuildSettingsView(guild_id=actor.guild_id, reminder_channel_id=channel_id)


async def get_guild_settings(uow: Uow, guild_id: int) -> GuildSettingsView:
    channel_id = await uow.session.scalar(
        select(GuildSettings.reminder_channel_id).where(GuildSettings.guild_id == guild_id)
    )
    return GuildSettingsView(guild_id=guild_id, reminder_channel_id=channel_id)


async def clear_reminder_channel(uow: Uow, actor: Actor) -> None:
    """Unset the reminder channel (D36). Requires Manage Server. Reminders that come due
    afterwards are marked failed (`no_channel`); posted ones stay and keep working."""
    guild_id = _require_manage(actor)
    result = await uow.session.execute(
        update(GuildSettings)
        .where(GuildSettings.guild_id == guild_id, GuildSettings.reminder_channel_id.is_not(None))
        .values(reminder_channel_id=None)
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        await uow.session.rollback()
        raise InvalidOperation(NO_REMINDER_CHANNEL)
    await uow.session.commit()


async def count_scheduled_server_todos(uow: Uow, guild_id: int) -> int:
    """Open server to-dos that still have a reminder coming (a pending occurrence): the
    ones that stop reminding when the reminder channel is unset."""
    count = await uow.session.scalar(
        select(func.count(func.distinct(Todo.id)))
        .join(Occurrence, Occurrence.todo_id == Todo.id)
        .where(
            Todo.scope == Scope.SERVER,
            Todo.guild_id == guild_id,
            Todo.status == TodoStatus.OPEN,
            Occurrence.status == OccurrenceStatus.PENDING,
        )
    )
    return count or 0
