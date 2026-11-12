"""`/lists delete` confirmation (D47): delete the open to-dos, move them, or cancel."""

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.services import lists
from sidequest.services.dto import ListDeletePreview, ListDeleteResult


def result_text(result: ListDeleteResult) -> str:
    name = render.esc(result.name)
    if result.moved_to is not None:
        return (
            f"🗑️ Deleted list **{name}**; moved {result.moved} to-do(s) to "
            f"**{render.esc(result.moved_to)}**."
        )
    if result.deleted:
        return f"🗑️ Deleted list **{name}** and its {result.deleted} to-do(s)."
    return f"🗑️ Deleted list **{name}**."


class ListDeleteView(BaseView):
    """Empty list: Delete / Cancel. With open to-dos: Delete them too / Move them to… /
    Cancel. A failed move (title clash) shows an error and leaves this usable."""

    def __init__(self, owner_id: int, preview: ListDeletePreview) -> None:
        super().__init__(owner_id)
        self.list_id = preview.list.id
        self.name = preview.list.name
        self.open_count = preview.open_count

        if preview.targets and self.open_count:
            self.move_select: discord.ui.Select[ListDeleteView] = discord.ui.Select(
                placeholder="Move them to…", options=render.list_options(preview.targets), row=0
            )
            self.move_select.callback = self._move  # type: ignore[method-assign]
            self.add_item(self.move_select)

        label = f"Delete list and its {self.open_count} to-do(s)" if self.open_count else "Delete"
        delete: discord.ui.Button[ListDeleteView] = discord.ui.Button(
            label=label, style=discord.ButtonStyle.danger, row=1
        )
        delete.callback = self._delete  # type: ignore[method-assign]
        self.add_item(delete)

        cancel: discord.ui.Button[ListDeleteView] = discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.secondary, row=1
        )
        cancel.callback = self._cancel  # type: ignore[method-assign]
        self.add_item(cancel)

    def prompt(self) -> str:
        name = render.esc(self.name)
        if not self.open_count:
            return f"Delete list **{name}**? This can't be undone."
        return f"**{name}** has {self.open_count} open to-do(s). What should happen to them?"

    async def _finish(self, interaction: discord.Interaction, move_to: int | None) -> None:
        await interaction.response.defer()
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            out = await lists.delete(uow, actor, self.list_id, move_to=move_to)
        result = await adapter.apply(interaction, out)
        await interaction.edit_original_response(
            content=result_text(result), view=None, allowed_mentions=adapter.NO_MENTIONS
        )
        self.stop()

    async def _delete(self, interaction: discord.Interaction) -> None:
        await self._finish(interaction, None)

    async def _move(self, interaction: discord.Interaction) -> None:
        await self._finish(interaction, int(self.move_select.values[0]))

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            content=f"Kept **{render.esc(self.name)}**.",
            view=None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        self.stop()
