"""`/settings …`: per-user settings."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, render
from sidequest.bot.commands.common import GUILD_CONTEXTS, GUILD_INSTALLS
from sidequest.core.errors import InvalidOperation
from sidequest.services import settings as user_settings


def build_settings_group() -> app_commands.Group:
    group = app_commands.Group(
        name="settings",
        description="Your Sidequest settings",
        allowed_installs=GUILD_INSTALLS,
        allowed_contexts=GUILD_CONTEXTS,
    )

    @group.command(name="timezone", description="Show or set your timezone")
    @app_commands.describe(timezone="e.g. Europe/Amsterdam; leave empty to see your current one")
    @app_commands.autocomplete(timezone=autocomplete.timezone)
    async def timezone_command(
        interaction: discord.Interaction, timezone: str | None = None
    ) -> None:
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            if timezone:
                name = await user_settings.set_user_timezone(uow, actor, timezone)
                text = (
                    f"🕒 Your timezone is now **{name}**. New to-dos use it; existing ones "
                    "keep the timezone they were made in."
                )
            else:
                name, is_default = await user_settings.get_user_timezone(uow, actor.user_id)
                text = (
                    f"🕒 You haven't set a timezone, so the default **{name}** is used. "
                    "Set yours with `/settings timezone timezone:Europe/Amsterdam`."
                    if is_default
                    else f"🕒 Your timezone is **{name}**."
                )
            notes = await adapter.collect_notes(uow, actor.user_id)
        await adapter.reply(interaction, text, notes=notes)

    @group.command(name="default-list", description="Show or set your default list here")
    @app_commands.describe(
        list_="The list your commands use when you don't pick one",
        clear="Go back to the server's default list",
    )
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(list_=autocomplete.todo_list)
    async def default_list_command(
        interaction: discord.Interaction, list_: str | None = None, clear: bool = False
    ) -> None:
        if list_ and clear:
            raise InvalidOperation("Pick a list or use `clear:True`, not both.")
        list_id = adapter.parse_list_id(list_)
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            if list_id is not None:
                lst = await user_settings.set_default_list(uow, actor, list_id)
                text = f"📋 Your default list here is now **{render.esc(lst.name)}**."
            elif clear:
                lst = await user_settings.clear_default_list(uow, actor)
                text = f"📋 Back to the server's default list, **{render.esc(lst.name)}**."
            else:
                own = await user_settings.own_default_list_id(uow, actor)
                lst = await user_settings.get_default_list(uow, actor)
                text = (
                    f"📋 Your default list here is **{render.esc(lst.name)}**."
                    if own is not None
                    else f"📋 You haven't picked a default list here, so the server's "
                    f"default **{render.esc(lst.name)}** is used. Pick one with "
                    "`/settings default-list list:…`."
                )
            notes = await adapter.collect_notes(uow, actor.user_id)
        await adapter.reply(interaction, text, notes=notes)

    return group
