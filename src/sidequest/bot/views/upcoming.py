"""`/todo upcoming`: pick which list (when none was given), then a select to check pending
occurrences off early."""

from datetime import timedelta

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.core.enums import Scope
from sidequest.services import occurrences
from sidequest.services.actor import Actor
from sidequest.services.dto import UpcomingItem
from sidequest.services.uow import Uow

LIMIT = 25  # one select menu


async def load(uow: Uow, actor: Actor, scope: Scope | None, days: int) -> list[UpcomingItem]:
    until = uow.clock.now() + timedelta(days=days)
    return await occurrences.list_upcoming(uow, actor, scope, until, limit=LIMIT)


class ScopePickView(BaseView):
    """Asks which list to show when `/todo upcoming` ran in a server without `scope`."""

    def __init__(self, owner_id: int, days: int) -> None:
        super().__init__(owner_id)
        self.days = days

    @discord.ui.button(label="Server list", style=discord.ButtonStyle.primary)
    async def server_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ScopePickView"]
    ) -> None:
        await self._show(interaction, Scope.SERVER)

    @discord.ui.button(label="Personal list", style=discord.ButtonStyle.primary)
    async def personal_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ScopePickView"]
    ) -> None:
        await self._show(interaction, Scope.PERSONAL)

    @discord.ui.button(label="Both", style=discord.ButtonStyle.secondary)
    async def both_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ScopePickView"]
    ) -> None:
        await self._show(interaction, None)

    async def _show(self, interaction: discord.Interaction, scope: Scope | None) -> None:
        await interaction.response.defer()
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            items = await load(uow, actor, scope, self.days)
        view = UpcomingView(interaction.user.id, scope, self.days, items)
        view.message = self.message  # same message, so the new view can time out cleanly
        self.stop()
        await interaction.edit_original_response(
            content=None,
            embed=render.upcoming_embed(items, self.days, LIMIT),
            view=view if view.children else None,
            allowed_mentions=adapter.NO_MENTIONS,
        )


class UpcomingView(BaseView):
    def __init__(
        self, owner_id: int, scope: Scope | None, days: int, items: list[UpcomingItem]
    ) -> None:
        super().__init__(owner_id)
        self.scope = scope
        self.days = days
        self.select: discord.ui.Select[UpcomingView] = discord.ui.Select(
            placeholder="Check one off early…"
        )
        self.select.callback = self._picked  # type: ignore[method-assign]
        self.build(items)

    def build(self, items: list[UpcomingItem]) -> None:
        self.clear_items()
        if items:
            self.select.options = render.upcoming_options(items)
            self.add_item(self.select)

    async def _picked(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            out = await occurrences.complete_occurrence(uow, actor, int(self.select.values[0]))
            todo = await adapter.apply(interaction, out)
            items = await load(uow, actor, self.scope, self.days)
        self.build(items)
        await interaction.edit_original_response(
            content=f"✅ Checked off **{render.esc(todo.title)}**.",
            embed=render.upcoming_embed(items, self.days, LIMIT),
            view=self if self.children else None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        if not self.children:
            self.stop()
