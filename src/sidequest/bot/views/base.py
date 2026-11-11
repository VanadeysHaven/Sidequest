"""Base classes for S5's short-lived views and modals (not restart-proof; S6 has those)."""

import contextlib
from typing import Any

import discord

from sidequest.bot.errors import report_error

TIMEOUT = 300  # seconds


class BaseView(discord.ui.View):
    """5-minute view that disables its components on timeout.

    `owner_id`: only that user may use it (None: anyone, e.g. a public list's paging).
    `adapter.reply` sets `message` so the timeout can edit it.
    """

    def __init__(self, owner_id: int | None) -> None:
        super().__init__(timeout=TIMEOUT)
        self.owner_id = owner_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is None or interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "These buttons belong to someone else's command.", ephemeral=True
        )
        return False

    def disable_all(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button | discord.ui.Select):
                item.disabled = True

    async def on_timeout(self) -> None:
        self.disable_all()
        if self.message is not None:
            # The message may be deleted, or the interaction token expired.
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]
    ) -> None:
        await report_error(interaction, error)


class BaseModal(discord.ui.Modal):
    def __init__(self, *, title: str) -> None:
        super().__init__(title=title, timeout=TIMEOUT)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)
