"""`/todo show`: subtask selects (1–2), Done, Edit details; after Done, Undo (D60)."""

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import TIMEOUT, BaseView
from sidequest.bot.views.confirm import CheckOffConfirmView, must_confirm
from sidequest.bot.views.modals import DetailsModal
from sidequest.bot.views.undo import UNDO_TIMEOUT, run_undo
from sidequest.core.enums import TodoStatus
from sidequest.core.limits import SELECT_OPTIONS_MAX
from sidequest.services import subtasks, todos
from sidequest.services.dto import TodoView, UndoToken


class ShowView(BaseView):
    def __init__(self, owner_id: int, todo: TodoView) -> None:
        super().__init__(owner_id)
        self.todo_id = todo.id
        self.token: UndoToken | None = None
        self.build(todo)

    def build(self, todo: TodoView) -> None:
        """(Re)create the components for the current state of the to-do."""
        self.clear_items()
        if todo.status != TodoStatus.OPEN:
            return
        # D50: no Done or subtask ticking for someone who may not check it off.
        pages = render.subtask_option_pages(todo) if todo.can_complete else []
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

        if todo.can_complete:
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
            todo = await todos.get(uow, actor, self.todo_id)
        if not must_confirm(actor.user_id, todo):
            await self._check_off(interaction)
            return
        # D67: swap the buttons for the question; Cancel brings them back.
        await interaction.edit_original_response(
            content=render.check_off_prompt(todo),
            view=CheckOffConfirmView(interaction.user.id, self._confirmed, self._kept),
            allowed_mentions=adapter.NO_MENTIONS,
        )

    async def _confirmed(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self._check_off(interaction)

    async def _kept(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        async with adapter.uows(interaction)() as uow:
            todo = await todos.get(uow, adapter.actor_from(interaction), self.todo_id)
        await self._refresh(interaction, todo)

    async def _check_off(self, interaction: discord.Interaction) -> None:
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            out = await todos.complete(uow, actor, self.todo_id)
        checked = await adapter.apply(interaction, out)
        # D37: the to-do disappears; only the confirmation (and next occurrence) is left,
        # with an Undo button for the next 2 hours (D60).
        self.token = checked.undo
        self.clear_items()
        undo: discord.ui.Button[ShowView] = discord.ui.Button(
            label="Undo", emoji="↩️", style=discord.ButtonStyle.secondary
        )
        undo.callback = self._undo  # type: ignore[method-assign]
        self.add_item(undo)
        self.timeout = UNDO_TIMEOUT
        await interaction.edit_original_response(
            content=render.done_text(checked.todo),
            embed=None,
            view=self,
            allowed_mentions=adapter.NO_MENTIONS,
        )

    async def _undo(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if self.token is None:
            return
        todo, text = await run_undo(interaction, self.token, adapter.actor_from(interaction))
        self.token = None
        self.timeout = TIMEOUT
        # The to-do is back, with its normal buttons.
        await self._refresh(interaction, todo, content=text)

    async def _edit_details(self, interaction: discord.Interaction) -> None:
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            todo = await todos.get(uow, actor, self.todo_id)
        # Saving refreshes this message, so the new details show right away.
        await interaction.response.send_modal(
            DetailsModal(todo.id, todo.details, on_saved=self._refresh)
        )

    async def _refresh(
        self, interaction: discord.Interaction, todo: TodoView, content: str | None = None
    ) -> None:
        self.build(todo)
        # After a timeout (e.g. a slow details edit) the view no longer listens: drop it.
        live = bool(self.children) and not self.is_finished()
        await interaction.edit_original_response(
            content=content,
            embed=render.todo_embed(todo),
            view=self if live else None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        if not live:
            self.stop()
