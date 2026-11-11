"""`/sidequest …`: server administration (the reminder channel)."""

import discord
from discord import app_commands

from sidequest.bot import adapter
from sidequest.bot.views.confirm import ClearChannelConfirmView
from sidequest.core.errors import Forbidden, InvalidOperation
from sidequest.services import settings as user_settings
from sidequest.services.actor import Actor


def channel_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(
        name="channel",
        description="Set or unset the channel for server reminders (Manage Server)",
    )
    @app_commands.describe(
        channel="A text channel the bot can post in",
        clear="True: unset the reminder channel (asks for confirmation first)",
    )
    async def channel(
        interaction: discord.Interaction,
        channel: app_commands.AppCommandChannel | None = None,
        clear: bool = False,
    ) -> None:
        actor = adapter.actor_from(interaction)
        if actor.guild_id is None:
            raise InvalidOperation("Use this in a server where Sidequest is added.")
        if not actor.can_manage_guild:
            raise Forbidden("You need the Manage Server permission to change the reminder channel.")
        if clear and channel is not None:
            raise InvalidOperation("Give either a channel or `clear:True`, not both.")
        if clear:
            await _ask_to_clear(interaction, actor)
        elif channel is None:
            raise InvalidOperation("Pick a channel, or use `clear:True` to unset it.")
        else:
            await _set(interaction, actor, channel)

    return channel


async def _set(
    interaction: discord.Interaction, actor: Actor, channel: app_commands.AppCommandChannel
) -> None:
    if channel.type not in (discord.ChannelType.text, discord.ChannelType.news):
        raise InvalidOperation("Pick a text channel.")
    await adapter.defer(interaction)
    cant_post = (
        f"I can't post in <#{channel.id}>. Give Sidequest View Channel, Send Messages "
        "and Embed Links there, then try again."
    )
    try:
        await interaction.client.get_partial_messageable(channel.id, guild_id=actor.guild_id).send(
            "✅ Sidequest reminders for this server will be posted here.",
            allowed_mentions=adapter.NO_MENTIONS,
        )
    except discord.HTTPException as exc:  # Forbidden is a subclass
        raise InvalidOperation(cant_post) from exc
    async with adapter.uows(interaction)() as uow:
        await user_settings.set_reminder_channel(uow, actor, channel.id)
        notes = await adapter.collect_notes(uow, actor.user_id)
    await adapter.reply(
        interaction, f"📣 Server reminders will be posted in <#{channel.id}>.", notes=notes
    )


async def _ask_to_clear(interaction: discord.Interaction, actor: Actor) -> None:
    """D36: warn what stops working, then Confirm / Cancel."""
    assert actor.guild_id is not None
    await adapter.defer(interaction)
    async with adapter.uows(interaction)() as uow:
        current = await user_settings.get_guild_settings(uow, actor.guild_id)
        if current.reminder_channel_id is None:
            raise InvalidOperation(user_settings.NO_REMINDER_CHANNEL)
        scheduled = await user_settings.count_scheduled_server_todos(uow, actor.guild_id)
        notes = await adapter.collect_notes(uow, actor.user_id)
    await adapter.reply(
        interaction,
        clear_warning(current.reminder_channel_id, scheduled),
        notes=notes,
        view=ClearChannelConfirmView(actor.user_id, current.reminder_channel_id),
    )


def clear_warning(channel_id: int, scheduled: int) -> str:
    lines = [f"⚠️ Unset the reminder channel (now <#{channel_id}>)?"]
    if scheduled:
        todos = "to-do" if scheduled == 1 else "to-dos"
        lines.append(
            f"**{scheduled}** timed server {todos} will stop reminding: reminders that "
            "come due are marked as failed and not posted."
        )
    lines.append(
        "New timed server to-dos can't be added until a channel is set again. "
        "Reminders already posted stay and keep working."
    )
    return "\n".join(lines)
