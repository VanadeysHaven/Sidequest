"""Undo a check-off (D60–D64): the shared undo call and the Undo button.

The button is an ordinary in-memory view with a 2-hour timeout (D61): it doesn't survive a
restart. `ShowView` and `UpcomingView` reuse `run_undo` with their own components.
"""

from collections.abc import Callable

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.core.limits import UNDO_WINDOW
from sidequest.services import undo
from sidequest.services.actor import Actor
from sidequest.services.dto import TodoView, UndoToken

UNDO_TIMEOUT = UNDO_WINDOW.total_seconds()


async def run_undo(
    interaction: discord.Interaction, token: UndoToken, actor: Actor
) -> tuple[TodoView, str]:
    """Undo one check-off, run its effects and re-post its reminder (D64). Returns the
    to-do and the reply text (D68)."""
    async with adapter.uows(interaction)() as uow:
        out = await undo.undo(uow, actor, token)
    result = await adapter.apply(interaction, out)
    channel_id: int | None = None
    if result.repost is not None:
        await adapter.repost(interaction, result.repost)
        channel_id = result.repost.channel_id
    return result.todo, render.undone_text(result.todo, channel_id)


class UndoView(BaseView):
    """One **Undo** button on a check-off reply (a reminder's Done, `/todo done`).

    `actor_for`: how to build the actor from the button's interaction (`reminder_actor`
    for a reminder's reply, which may lack the guild install owner).
    """

    def __init__(
        self,
        owner_id: int,
        token: UndoToken,
        actor_for: Callable[[discord.Interaction], Actor] = adapter.actor_from,
    ) -> None:
        super().__init__(owner_id)
        self.timeout = UNDO_TIMEOUT
        self.token = token
        self.actor_for = actor_for

    @discord.ui.button(label="Undo", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def undo_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["UndoView"]
    ) -> None:
        await interaction.response.defer()
        _, text = await run_undo(interaction, self.token, self.actor_for(interaction))
        await interaction.edit_original_response(
            content=text, view=None, allowed_mentions=adapter.NO_MENTIONS
        )
        self.stop()
