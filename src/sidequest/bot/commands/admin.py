"""`/sidequest …`: server administration (the reminder channel)."""

import discord
from discord import app_commands

from sidequest.bot import adapter
from sidequest.core.errors import Forbidden, InvalidOperation
from sidequest.services import settings as user_settings


def channel_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(
        name="channel", description="Set the channel for server reminders (Manage Server)"
    )
    @app_commands.describe(channel="A text channel the bot can post in")
    async def channel(
        interaction: discord.Interaction,
        channel: app_commands.AppCommandChannel,
    ) -> None:
        actor = adapter.actor_from(interaction)
        if actor.guild_id is None:
            raise InvalidOperation("Use this in a server where Sidequest is added.")
        if not actor.can_manage_guild:
            raise Forbidden("You need the Manage Server permission to set the reminder channel.")
        if channel.type not in (discord.ChannelType.text, discord.ChannelType.news):
            raise InvalidOperation("Pick a text channel.")
        await adapter.defer(interaction)
        cant_post = (
            f"I can't post in <#{channel.id}>. Give Sidequest View Channel, Send Messages "
            "and Embed Links there, then try again."
        )
        try:
            await interaction.client.get_partial_messageable(
                channel.id, guild_id=actor.guild_id
            ).send(
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

    return channel
