"""Discord client: gateway with no intents; everything arrives as interactions (D11)."""

import logging

import discord
from discord import app_commands

from sidequest.bot.commands.about import SidequestGroup
from sidequest.config import Settings
from sidequest.core.clock import Clock

log = logging.getLogger(__name__)


class SidequestClient(discord.Client):
    def __init__(self, settings: Settings, clock: Clock) -> None:
        super().__init__(intents=discord.Intents.none())
        self.settings = settings
        self.clock = clock
        self.started_at = clock.now()
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        self.tree.add_command(SidequestGroup(self.settings, self.started_at))

        await self._sync_commands()

    async def _sync_commands(self) -> None:
        """Register commands with Discord (D32). Never both global and guild copies: a guild
        that has both shows every command twice.

        - SYNC_GLOBAL=true: global commands (every server, DMs, user installs). Guilds in
          SYNC_GUILD_IDS get their guild commands deleted, cleaning up after server-only mode.
        - SYNC_GLOBAL=false: server-only mode for a dev bot. Commands go to SYNC_GUILD_IDS
          (instant) and the global commands are cleared, so DMs/user installs have none.
        """
        guilds = [discord.Object(id=guild_id) for guild_id in self.settings.sync_guild_ids]

        if self.settings.sync_global:
            synced = await self.tree.sync()
            log.info("Synced %d global command(s)", len(synced))
            # No guild commands are registered for these guilds, so syncing deletes them.
            for guild in guilds:
                await self._sync_guild(guild, "Deleted guild commands from guild %s")
            return

        for guild in guilds:
            self.tree.copy_global_to(guild=guild)
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        log.info("Server-only mode: cleared global commands")
        for guild in guilds:
            await self._sync_guild(guild, "Synced command(s) to guild %s")

    async def _sync_guild(self, guild: discord.abc.Snowflake, done_message: str) -> None:
        try:
            await self.tree.sync(guild=guild)
        except discord.HTTPException as exc:
            # Usually: the bot isn't in that guild. Don't block startup over it.
            log.warning("Could not sync commands for guild %s: %s", guild.id, exc)
        else:
            log.info(done_message, guild.id)

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("Logged in as %s (id %s)", self.user, self.user.id)


def run(settings: Settings) -> None:
    client = SidequestClient(settings, Clock())
    # log_handler=None: keep the logging set up by sidequest.logging.
    client.run(settings.discord_token.get_secret_value(), log_handler=None)
