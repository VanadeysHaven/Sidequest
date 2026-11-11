"""Central error handling for commands, views and modals."""

import logging

import discord
from discord import app_commands

from sidequest.core.errors import SidequestError

log = logging.getLogger(__name__)

GENERIC = "Something went wrong on our side, sorry. Please try again in a moment."


def user_message(error: BaseException) -> str | None:
    """The text to show for an error the user caused, or None for a bug."""
    if isinstance(error, app_commands.CommandInvokeError):
        error = error.original
    if isinstance(error, SidequestError):
        return error.message
    if isinstance(error, app_commands.CheckFailure | app_commands.TransformerError):
        return str(error)
    return None


async def report_error(interaction: discord.Interaction, error: BaseException) -> None:
    """`SidequestError` → its message; anything else → logged with traceback + apology.
    Always ephemeral, whether or not the interaction was already answered."""
    message = user_message(error)
    if message is None:
        original = getattr(error, "original", error)
        command = interaction.command.qualified_name if interaction.command else None
        log.error("Unhandled error in %s", command or "component", exc_info=original)
        message = GENERIC
    text = f"❌ {discord.utils.escape_mentions(message)}"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
        else:
            await interaction.response.send_message(
                text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
    except discord.HTTPException as exc:
        log.warning("Could not report an error to the user: %s", exc)
