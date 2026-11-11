"""`/settings …`: per-user settings."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete
from sidequest.bot.commands.common import ANYWHERE_CONTEXTS, ANYWHERE_INSTALLS
from sidequest.services import settings as user_settings


def build_settings_group() -> app_commands.Group:
    group = app_commands.Group(
        name="settings",
        description="Your Sidequest settings",
        allowed_installs=ANYWHERE_INSTALLS,
        allowed_contexts=ANYWHERE_CONTEXTS,
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

    return group
