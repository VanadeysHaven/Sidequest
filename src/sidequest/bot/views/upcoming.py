"""`/todo upcoming`: a select to check pending occurrences of one list off early."""

from datetime import timedelta

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.services import occurrences
from sidequest.services.actor import Actor
from sidequest.services.dto import UpcomingItem
from sidequest.services.uow import Uow

LIMIT = 25  # one select menu


async def load(uow: Uow, actor: Actor, list_id: int, days: int) -> list[UpcomingItem]:
    until = uow.clock.now() + timedelta(days=days)
    return await occurrences.list_upcoming(uow, actor, list_id, until, limit=LIMIT)


class UpcomingView(BaseView):
    """The select only offers the to-dos the viewer may check off (D50)."""

    def __init__(
        self, owner_id: int, list_id: int, list_name: str, days: int, items: list[UpcomingItem]
    ) -> None:
        super().__init__(owner_id)
        self.list_id = list_id
        self.list_name = list_name
        self.days = days
        self.select: discord.ui.Select[UpcomingView] = discord.ui.Select(
            placeholder="Check one off early…"
        )
        self.select.callback = self._picked  # type: ignore[method-assign]
        self.build(items)

    def build(self, items: list[UpcomingItem]) -> None:
        self.clear_items()
        options = render.upcoming_options(items)
        if options:
            self.select.options = options
            self.add_item(self.select)

    def embed(self, items: list[UpcomingItem]) -> discord.Embed:
        return render.upcoming_embed(items, self.list_name, self.days, LIMIT)

    async def _picked(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            out = await occurrences.complete_occurrence(uow, actor, int(self.select.values[0]))
            todo = await adapter.apply(interaction, out)
            items = await load(uow, actor, self.list_id, self.days)
        self.build(items)
        await interaction.edit_original_response(
            content=render.done_text(todo),
            embed=self.embed(items),
            view=self if self.children else None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        if not self.children:
            self.stop()
