"""Confirmations: checking off as a non-assignee (D67), deleting a to-do, unsetting the
reminder channel (D36), transferring a list (D52)."""

from collections.abc import Awaitable, Callable

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.core.enums import TodoStatus
from sidequest.services import lists, todos
from sidequest.services import settings as user_settings
from sidequest.services.dto import TodoView

type InteractionCallback = Callable[[discord.Interaction], Awaitable[None]]


def must_confirm(user_id: int, todo: TodoView) -> bool:
    """D67: someone who isn't an assignee is asked first. Not when they may not check it
    off at all (or it's no longer open): the check-off refuses that straight away."""
    return todo.status == TodoStatus.OPEN and todo.can_complete and user_id not in todo.assignee_ids


class CheckOffConfirmView(BaseView):
    """**Check off anyway** / **Cancel** (D67). The callbacks respond to the interaction
    themselves; the view stops once one of them succeeds (a refused check-off keeps the
    buttons, so Cancel still works)."""

    def __init__(
        self, owner_id: int, on_confirm: InteractionCallback, on_cancel: InteractionCallback
    ) -> None:
        super().__init__(owner_id)
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel

    @discord.ui.button(label="Check off anyway", style=discord.ButtonStyle.success)
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["CheckOffConfirmView"]
    ) -> None:
        await self.on_confirm(interaction)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["CheckOffConfirmView"]
    ) -> None:
        await self.on_cancel(interaction)
        self.stop()


async def not_checked_off(interaction: discord.Interaction) -> None:
    """Cancel on a reply that was only the question (reminder Done, `/todo done`)."""
    await interaction.response.edit_message(content="Not checked off.", view=None)


class DeleteConfirmView(BaseView):
    def __init__(self, owner_id: int, todo_id: int, title: str) -> None:
        super().__init__(owner_id)
        self.todo_id = todo_id
        self.title = title

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["DeleteConfirmView"]
    ) -> None:
        await interaction.response.defer()
        async with adapter.uows(interaction)() as uow:
            out = await todos.delete(uow, adapter.actor_from(interaction), self.todo_id)
        await adapter.apply(interaction, out)
        await interaction.edit_original_response(
            content=f"🗑️ Deleted **{render.esc(self.title)}**.",
            view=None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["DeleteConfirmView"]
    ) -> None:
        await interaction.response.edit_message(content="Kept it.", view=None)
        self.stop()


class ClearChannelConfirmView(BaseView):
    def __init__(self, owner_id: int, channel_id: int) -> None:
        super().__init__(owner_id)
        self.channel_id = channel_id

    @discord.ui.button(label="Unset channel", style=discord.ButtonStyle.danger)
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ClearChannelConfirmView"]
    ) -> None:
        await interaction.response.defer()
        async with adapter.uows(interaction)() as uow:
            # Checks Manage Server again: permissions may have changed since the command.
            await user_settings.clear_reminder_channel(uow, adapter.actor_from(interaction))
        await interaction.edit_original_response(
            content="🔕 The reminder channel is unset. Set a new one with `/sidequest channel`.",
            view=None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["ClearChannelConfirmView"]
    ) -> None:
        await interaction.response.edit_message(
            content=f"Kept <#{self.channel_id}> as the reminder channel.",
            view=None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        self.stop()


class TransferConfirmView(BaseView):
    def __init__(self, owner_id: int, list_id: int, new_owner_id: int) -> None:
        super().__init__(owner_id)
        self.list_id = list_id
        self.new_owner_id = new_owner_id

    @discord.ui.button(label="Transfer", style=discord.ButtonStyle.danger)
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["TransferConfirmView"]
    ) -> None:
        await interaction.response.defer()
        async with adapter.uows(interaction)() as uow:
            # Checks the permission again: it may have changed since the command.
            lst = await lists.transfer(
                uow, adapter.actor_from(interaction), self.list_id, self.new_owner_id
            )
        await interaction.edit_original_response(
            content=f"🔑 <@{self.new_owner_id}> now owns **{render.esc(lst.name)}**.",
            view=None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["TransferConfirmView"]
    ) -> None:
        await interaction.response.edit_message(content="Nothing changed.", view=None)
        self.stop()
