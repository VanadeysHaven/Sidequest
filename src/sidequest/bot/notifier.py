"""Delivers reminders to Discord: the `Notifier` the scheduler uses (S6)."""

import logging
from collections.abc import Sequence

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.reminder import reminder_view
from sidequest.scheduler.notifier import Failed, Posted, PostResult
from sidequest.services.dto import DueReminder
from sidequest.services.effects import Effect
from sidequest.services.occurrences import (
    FAILURE_CHANNEL_GONE,
    FAILURE_FORBIDDEN,
    FAILURE_NO_CHANNEL,
)

log = logging.getLogger(__name__)

PINGS = discord.AllowedMentions(users=True, roles=False, everyone=False, replied_user=False)
"""Reminders ping users only (the assignees in the content), never roles or @everyone."""


class DiscordNotifier:
    def __init__(self, client: discord.Client) -> None:
        self._client = client

    async def execute(self, effects: Sequence[Effect]) -> None:
        await adapter.run_effects(self._client, effects)

    async def post(self, reminder: DueReminder) -> PostResult:
        """Post in the server's reminder channel (no DMs, D40)."""
        todo = reminder.todo
        if reminder.channel_id is None:
            return Failed(reason=FAILURE_NO_CHANNEL)
        channel = self._client.get_partial_messageable(reminder.channel_id)
        try:
            message = await channel.send(
                content=render.reminder_pings(todo),
                embed=render.reminder_embed(todo, reminder.occurrence),
                view=reminder_view(reminder.occurrence.id, todo),
                allowed_mentions=PINGS,
            )
        except discord.Forbidden:
            return Failed(reason=FAILURE_FORBIDDEN)
        except discord.NotFound:
            return Failed(reason=FAILURE_CHANNEL_GONE)
        return Posted(channel_id=message.channel.id, message_id=message.id)
