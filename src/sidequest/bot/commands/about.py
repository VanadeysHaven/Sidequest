"""`/sidequest about`: version and deploy info."""

from datetime import UTC, datetime

import discord
from discord import app_commands

from sidequest import __version__
from sidequest.config import Settings
from sidequest.core.discord_time import ts


def about_text(settings: Settings, started_at: datetime) -> str:
    commit = f"`{settings.commit}`" if settings.commit else "unknown"
    branch = f"`{settings.branch}`" if settings.branch else "unknown"
    if settings.deploy_time is not None:
        deployed = ts(datetime.fromtimestamp(settings.deploy_time, UTC), "F")
    else:
        deployed = "unknown (not deployed with update.sh)"
    return "\n".join(
        [
            f"**Sidequest** v{__version__}",
            f"Commit: {commit} on {branch}",
            f"Deployed: {deployed}",
            f"Running since: {ts(started_at, 'R')}",
        ]
    )


@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
class SidequestGroup(app_commands.Group, name="sidequest", description="About Sidequest"):
    def __init__(self, settings: Settings, started_at: datetime) -> None:
        super().__init__()
        self.settings = settings
        self.started_at = started_at

    @app_commands.command(name="about", description="Version and deploy info")
    async def about(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            about_text(self.settings, self.started_at),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
