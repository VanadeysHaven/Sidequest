"""`/todo show`: subtask selects (1–2), Done, Edit details."""

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.bot.views.modals import DetailsModal
from sidequest.core.enums import TodoStatus
from sidequest.core.limits import SELECT_OPTIONS_MAX
from sidequest.services import subtasks, todos
from sidequest.services.dto import TodoView


class ShowView(BaseView):
    def __init__(self, owner_id: int, todo: TodoView) -> None:
        super().__init__(owner_id)
        self.todo_id = todo.id
        self.build(todo)

    def build(self, todo: TodoView) -> None:
        """(Re)create the components for the current state of the to-do."""
        self.clear_items()
        if todo.status != TodoStatus.OPEN:
            return
        pages = render.subtask_option_pages(todo)
        for row, options in enumerate(pages):
            first = row * SELECT_OPTIONS_MAX + 1
            placeholder = (
                "Tick subtasks"
                if len(pages) == 1
                else f"Subtasks {first}–{first + len(options) - 1}"
            )
            select: discord.ui.Select[ShowView] = discord.ui.Select(
                placeholder=placeholder,
                min_values=0,
                max_values=len(options),
                options=options,
                row=row,
            )
            select.callback = self._ticked(select)  # type: ignore[method-assign]
            self.add_item(select)

        done: discord.ui.Button[ShowView] = discord.ui.Button(
            label="Done", style=discord.ButtonStyle.success, row=2
        )
        done.callback = self._done  # type: ignore[method-assign]
        self.add_item(done)
        if todo.can_edit:
            edit: discord.ui.Button[ShowView] = discord.ui.Button(
                label="Edit details", style=discord.ButtonStyle.secondary, row=2
            )
            edit.callback = self._edit_details  # type: ignore[method-assign]
            self.add_item(edit)

    def _ticked(self, select: discord.ui.Select["ShowView"]):  # noqa: ANN202
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            within = {int(option.value) for option in select.options}
            ticked = {int(value) for value in select.values}
            actor = adapter.actor_from(interaction)
            async with adapter.uows(interaction)() as uow:
                out = await subtasks.set_done(uow, actor, self.todo_id, ticked, within)
            await self._refresh(interaction, await adapter.apply(interaction, out))

        return callback

    async def _done(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            out = await todos.complete(uow, actor, self.todo_id)
        todo = await adapter.apply(interaction, out)
        # D37: the to-do disappears; only the confirmation (and next occurrence) is left.
        await interaction.edit_original_response(
            content=render.done_text(todo),
            embed=None,
            view=None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        self.stop()

    async def _edit_details(self, interaction: discord.Interaction) -> None:
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            todo = await todos.get(uow, actor, self.todo_id)
        await interaction.response.send_modal(DetailsModal(todo.id, todo.details))

    async def _refresh(
        self, interaction: discord.Interaction, todo: TodoView, content: str | None = None
    ) -> None:
        self.build(todo)
        await interaction.edit_original_response(
            content=content,
            embed=render.todo_embed(todo),
            view=self if self.children else None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        if not self.children:
            self.stop()
