"""`/todo upcoming`: a select to check pending occurrences of one list off early, and one
to undo those check-offs (D69)."""

from datetime import timedelta

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.bot.views.confirm import CheckOffConfirmView, must_confirm
from sidequest.bot.views.undo import UNDO_TIMEOUT, run_undo
from sidequest.core.limits import SELECT_OPTIONS_MAX
from sidequest.services import occurrences
from sidequest.services.actor import Actor
from sidequest.services.dto import UndoToken, UpcomingItem
from sidequest.services.uow import Uow

LIMIT = 25  # one select menu


async def load(uow: Uow, actor: Actor, list_id: int, days: int) -> list[UpcomingItem]:
    until = uow.clock.now() + timedelta(days=days)
    return await occurrences.list_upcoming(uow, actor, list_id, until, limit=LIMIT)


class UpcomingView(BaseView):
    """The select only offers the to-dos the viewer may check off (D50). Check-offs made
    from this message can be undone from a second select, in any order (D69)."""

    def __init__(
        self, owner_id: int, list_id: int, list_name: str, days: int, items: list[UpcomingItem]
    ) -> None:
        super().__init__(owner_id)
        self.list_id = list_id
        self.list_name = list_name
        self.days = days
        self.items = items
        self.content: str | None = None
        self.undos: list[tuple[UndoToken, str]] = []
        """Check-offs made from this message, oldest first (at most 25)."""
        self.select: discord.ui.Select[UpcomingView] = discord.ui.Select(
            placeholder="Check one off early…", row=0
        )
        self.select.callback = self._picked  # type: ignore[method-assign]
        self.undo_select: discord.ui.Select[UpcomingView] = discord.ui.Select(
            placeholder="Undo a check-off…", row=1
        )
        self.undo_select.callback = self._undo_picked  # type: ignore[method-assign]
        self.build(items)

    def build(self, items: list[UpcomingItem]) -> None:
        self.items = items
        self.clear_items()
        options = render.upcoming_options(items)
        if options:
            self.select.options = options
            self.add_item(self.select)
        if self.undos:
            self.undo_select.options = render.undo_options([title for _, title in self.undos])
            self.add_item(self.undo_select)

    def embed(self, items: list[UpcomingItem]) -> discord.Embed:
        return render.upcoming_embed(items, self.list_name, self.days, LIMIT)

    async def _picked(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        occurrence_id = int(self.select.values[0])
        user_id = interaction.user.id
        item = next((i for i in self.items if i.occurrence_id == occurrence_id), None)
        if item is None or not must_confirm(user_id, item.todo):
            await self._check_off(interaction, occurrence_id)
            return

        # D67: swap both selects for the question; Cancel brings them back.
        async def confirmed(confirm: discord.Interaction) -> None:
            await confirm.response.defer()
            await self._check_off(confirm, occurrence_id)

        await interaction.edit_original_response(
            content=render.check_off_prompt(item.todo),
            view=CheckOffConfirmView(user_id, confirmed, self._kept),
            allowed_mentions=adapter.NO_MENTIONS,
        )

    async def _kept(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self._reload(interaction, self.content)

    async def _check_off(self, interaction: discord.Interaction, occurrence_id: int) -> None:
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            out = await occurrences.complete_occurrence(uow, actor, occurrence_id)
        checked = await adapter.apply(interaction, out)
        self.undos.append((checked.undo, checked.todo.title))
        del self.undos[:-SELECT_OPTIONS_MAX]  # drop the oldest beyond one select
        self.timeout = UNDO_TIMEOUT
        await self._reload(interaction, render.done_text(checked.todo))

    async def _undo_picked(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        index = int(self.undo_select.values[0])
        if not 0 <= index < len(self.undos):
            return
        token, _ = self.undos[index]
        # A refused undo raises here and keeps the entry (it may work later, D69).
        _, text = await run_undo(interaction, token, adapter.actor_from(interaction))
        del self.undos[index]
        await self._reload(interaction, text)

    async def _reload(self, interaction: discord.Interaction, content: str | None) -> None:
        """Reload the list and show it with `content` above it."""
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            items = await load(uow, actor, self.list_id, self.days)
        self.content = content
        self.build(items)
        await interaction.edit_original_response(
            content=content,
            embed=self.embed(items),
            view=self if self.children else None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        if not self.children:
            self.stop()
