"""Components on reminder messages: Done button and subtask selects.

They are `DynamicItem`s: the occurrence id lives in the custom_id, so they keep working
after a restart without stored views (register with `client.add_dynamic_items`).

- Done: ``sq:occ:done:<occurrence_id>``
- Subtasks: ``sq:occ:sub:<occurrence_id>:<page>``; page 0 = subtasks 1–25, page 1 = 26–50
  (D29). Each select only changes the subtasks it shows.
"""

import contextlib
import logging
import re
from typing import Any

import discord

from sidequest.bot import adapter, render
from sidequest.bot.errors import report_error
from sidequest.bot.views.confirm import CheckOffConfirmView, must_confirm, not_checked_off
from sidequest.bot.views.undo import UndoView
from sidequest.core.errors import InvalidOperation, NotFound
from sidequest.core.limits import SELECT_OPTIONS_MAX
from sidequest.services import occurrences
from sidequest.services.actor import Actor
from sidequest.services.dto import TodoView

log = logging.getLogger(__name__)

GONE = "This to-do no longer exists."


def reminder_view(occurrence_id: int, todo: TodoView) -> discord.ui.View:
    """Subtask select(s) (if any) and the Done button for one reminder."""
    view = discord.ui.View(timeout=None)
    pages = render.subtask_option_pages(todo)
    for page, options in enumerate(pages):
        first = page * SELECT_OPTIONS_MAX + 1
        placeholder = (
            "Tick subtasks" if len(pages) == 1 else f"Subtasks {first}–{first + len(options) - 1}"
        )
        view.add_item(SubtaskSelect(occurrence_id, page, options, placeholder))
    view.add_item(DoneButton(occurrence_id))
    return view


def reminder_actor(interaction: discord.Interaction) -> Actor:
    """Who pressed a reminder component.

    Unlike `adapter.actor_from`, the guild comes straight from the interaction: only the
    bot posts reminder messages, so a reminder in a server proves the bot is installed
    there (and a component interaction may not carry the guild install owner). Manage
    Server counts: it may check off on any list (D50). A non-collaborator gets the
    service's `Forbidden` and the reminder stays.
    """
    perms = interaction.permissions
    guild_id = interaction.guild_id
    return Actor(
        user_id=interaction.user.id,
        guild_id=guild_id,
        can_manage_guild=guild_id is not None and (perms.manage_guild or perms.administrator),
        origin="discord",
    )


async def _delete_reminder(message: discord.Message | None) -> None:
    if message is None:
        return
    with contextlib.suppress(discord.NotFound, discord.Forbidden):
        await message.delete()


async def _delete_if_stale(
    interaction: discord.Interaction, occurrence_id: int, message: discord.Message | None
) -> bool:
    """Delete the reminder message if its occurrence is closed or gone. True if deleted."""
    async with adapter.uows(interaction)() as uow:
        live = await occurrences.is_live(uow, occurrence_id)
    if not live:
        await _delete_reminder(message)
    return not live


class DoneButton(
    discord.ui.DynamicItem[discord.ui.Button[Any]], template=r"sq:occ:done:(?P<occ>[0-9]+)"
):
    def __init__(self, occurrence_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Done",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=f"sq:occ:done:{occurrence_id}",
                row=2,
            )
        )
        self.occurrence_id = occurrence_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> "DoneButton":
        return cls(int(match["occ"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await self._done(interaction)
        except Exception as error:
            await report_error(interaction, error)

    async def _done(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = reminder_actor(interaction)
        reminder = interaction.message
        todo = await self._live_todo(interaction, actor)
        if todo is not None and must_confirm(actor.user_id, todo):
            # D67: ask first; the reminder stays up until they confirm.
            async def confirmed(confirm: discord.Interaction) -> None:
                await confirm.response.defer()
                text, undo_view = await self._check_off(confirm, reminder)
                undo_view.message = await confirm.edit_original_response(
                    content=text, view=undo_view, allowed_mentions=adapter.NO_MENTIONS
                )

            await adapter.reply(
                interaction,
                render.check_off_prompt(todo),
                view=CheckOffConfirmView(interaction.user.id, confirmed, not_checked_off),
            )
            return
        text, undo_view = await self._check_off(interaction, reminder)
        await adapter.reply(interaction, text, view=undo_view)

    async def _live_todo(self, interaction: discord.Interaction, actor: Actor) -> TodoView | None:
        """The to-do, if this reminder is still the live one (else the check-off itself
        reports what happened and clears the leftover message)."""
        try:
            async with adapter.uows(interaction)() as uow:
                todo = await occurrences.todo_for(uow, actor, self.occurrence_id)
        except NotFound:
            return None
        if todo.reminder is None or todo.reminder.id != self.occurrence_id:
            return None
        return todo

    async def _check_off(
        self, interaction: discord.Interaction, reminder: discord.Message | None
    ) -> tuple[str, UndoView]:
        """Check off, delete the reminder message; returns the reply text and its Undo."""
        actor = reminder_actor(interaction)
        try:
            async with adapter.uows(interaction)() as uow:
                out = await occurrences.complete_occurrence(uow, actor, self.occurrence_id)
        except (InvalidOperation, NotFound) as error:
            # Already checked off, missed, or the to-do was deleted: clear the leftover.
            stale = await _delete_if_stale(interaction, self.occurrence_id, reminder)
            if stale and isinstance(error, NotFound):
                raise NotFound(GONE) from error
            raise
        checked = await adapter.apply(interaction, out)
        if reminder is not None and not any(e.message_id == reminder.id for e in out.effects):
            await _delete_reminder(reminder)
        # The Undo button sits on an ephemeral reply to a reminder: same actor rules.
        undo_view = UndoView(interaction.user.id, checked.undo, actor_for=reminder_actor)
        return render.done_text(checked.todo), undo_view


class SubtaskSelect(
    discord.ui.DynamicItem[discord.ui.Select[Any]],
    template=r"sq:occ:sub:(?P<occ>[0-9]+):(?P<page>[0-9])",
):
    def __init__(
        self,
        occurrence_id: int,
        page: int,
        options: list[discord.SelectOption],
        placeholder: str | None = None,
    ) -> None:
        super().__init__(
            discord.ui.Select(
                custom_id=f"sq:occ:sub:{occurrence_id}:{page}",
                placeholder=placeholder,
                min_values=0,
                max_values=max(1, len(options)),
                options=options,
                row=page,
            )
        )
        self.occurrence_id = occurrence_id
        self.page = page

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> "SubtaskSelect":
        # Rebuilt from the message, so the options are exactly the subtasks the user saw.
        assert isinstance(item, discord.ui.Select)
        return cls(int(match["occ"]), int(match["page"]), list(item.options), item.placeholder)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await self._ticked(interaction)
        except Exception as error:
            await report_error(interaction, error)

    async def _ticked(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        within = {int(option.value) for option in self.item.options}
        ticked = {int(value) for value in self.item.values}
        actor = reminder_actor(interaction)
        try:
            async with adapter.uows(interaction)() as uow:
                out = await occurrences.tick_subtasks(
                    uow, actor, self.occurrence_id, ticked, within
                )
        except (InvalidOperation, NotFound):
            await _delete_if_stale(interaction, self.occurrence_id, interaction.message)
            raise
        todo = await adapter.apply(interaction, out)
        occurrence = todo.reminder
        if occurrence is None or occurrence.id != self.occurrence_id:
            return  # can't happen: tick_subtasks requires this reminder to be the sent one
        await interaction.edit_original_response(
            content=render.reminder_pings(todo),
            embed=render.reminder_embed(todo, occurrence),
            view=reminder_view(self.occurrence_id, todo),
            allowed_mentions=adapter.NO_MENTIONS,
        )
