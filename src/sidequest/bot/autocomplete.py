"""Autocomplete callbacks. They never raise: a failure just shows no suggestions."""

import logging

import discord
from discord import app_commands

from sidequest.bot import render
from sidequest.bot.adapter import actor_from, uows
from sidequest.core.errors import SidequestError
from sidequest.core.limits import SELECT_LABEL_MAX
from sidequest.core.tz import search_zones
from sidequest.services import lists, todos

log = logging.getLogger(__name__)

type Choices = list[app_commands.Choice[str]]


async def timezone(interaction: discord.Interaction, current: str) -> Choices:
    return [app_commands.Choice(name=name, value=name) for name in search_zones(current)]


async def todo(interaction: discord.Interaction, current: str) -> Choices:
    """Open to-dos from every list of the server; value = id. Label `[List] title`."""
    try:
        actor = actor_from(interaction)
        async with uows(interaction)() as uow:
            found = await todos.autocomplete(uow, actor, current)
    except Exception:
        log.exception("To-do autocomplete failed")
        return []
    return [
        app_commands.Choice(name=render.autocomplete_label(title, list_name), value=str(todo_id))
        for todo_id, title, list_name in found
    ]


async def todo_list(interaction: discord.Interaction, current: str) -> Choices:
    """The server's lists, prefix matches first; value = list id."""
    try:
        actor = actor_from(interaction)
        async with uows(interaction)() as uow:
            found = await lists.autocomplete(uow, actor, current)
    except Exception:
        log.exception("List autocomplete failed")
        return []
    return [
        app_commands.Choice(name=render.cut(name, SELECT_LABEL_MAX), value=str(list_id))
        for list_id, name in found
    ]


async def subtask(interaction: discord.Interaction, current: str) -> Choices:
    """Subtasks of the to-do chosen in the `todo` option; value = subtask id."""
    raw = getattr(interaction.namespace, "todo", None)
    if not isinstance(raw, str) or not raw.strip().isdigit():
        return []
    query = current.strip().lower()
    try:
        actor = actor_from(interaction)
        async with uows(interaction)() as uow:
            view = await todos.get(uow, actor, int(raw))
    except SidequestError:  # e.g. NotFound: just no suggestions
        return []
    except Exception:
        log.exception("Subtask autocomplete failed")
        return []
    return [
        app_commands.Choice(
            name=render.cut(f"{number}. {sub.title}", SELECT_LABEL_MAX), value=str(sub.id)
        )
        for number, sub in enumerate(view.subtasks, start=1)
        if query in sub.title.lower()
    ][:25]
