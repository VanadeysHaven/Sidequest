"""Discord client: gateway with no intents; everything arrives as interactions (D11)."""

import hashlib
import json
import logging
from typing import Any

import discord
from discord import app_commands

from sidequest.bot.adapter import BotDeps, DbCommandHashStore
from sidequest.bot.commands.about import SidequestGroup
from sidequest.bot.commands.settings import build_settings_group
from sidequest.bot.commands.todo import build_todo_group
from sidequest.bot.errors import report_error
from sidequest.config import Settings
from sidequest.core.clock import Clock, SystemClock
from sidequest.db.session import create_engine, create_sessionmaker
from sidequest.scheduler.signal import ScheduleSignal
from sidequest.services.uow import UowFactory

log = logging.getLogger(__name__)


def command_hash(payload: list[dict[str, Any]]) -> str:
    """sha256 hex of the payload as canonical JSON (sort_keys=True, separators=(",", ":"))."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class SidequestClient(discord.Client):
    def __init__(self, settings: Settings, clock: Clock, deps: BotDeps) -> None:
        super().__init__(intents=discord.Intents.none())
        self.settings = settings
        self.clock = clock
        self.deps = deps
        self.started_at = clock.now()
        self.tree = app_commands.CommandTree(self)
        self.tree.error(report_error)

    async def setup_hook(self) -> None:
        self.tree.add_command(SidequestGroup(self.settings, self.started_at))
        self.tree.add_command(build_todo_group())
        self.tree.add_command(build_settings_group())

        await self._sync_commands()

    async def _sync_commands(self) -> None:
        """Register commands with Discord (D32). Never both global and guild copies: a guild
        that has both shows every command twice.

        - SYNC_GLOBAL=true: global commands (every server, DMs, user installs). Guilds in
          SYNC_GUILD_IDS get their guild commands deleted, cleaning up after server-only mode.
        - SYNC_GLOBAL=false: server-only mode for a dev bot. Commands go to SYNC_GUILD_IDS
          (instant) and the global commands are cleared, so DMs/user installs have none.

        The global sync is skipped when the hash of the global payload matches the one stored
        in app_meta `command_hash`, so it only runs when the global commands change.
        """
        guilds = [discord.Object(id=guild_id) for guild_id in self.settings.sync_guild_ids]

        if self.settings.sync_global:
            if await self._sync_global():
                log.info("Synced %d global command(s)", len(self.tree.get_commands()))
            # No guild commands are registered for these guilds, so syncing deletes them.
            for guild in guilds:
                await self._sync_guild(guild, "Deleted guild commands from guild %s")
            return

        for guild in guilds:
            self.tree.copy_global_to(guild=guild)
        self.tree.clear_commands(guild=None)
        if await self._sync_global():
            log.info("Server-only mode: cleared global commands")
        for guild in guilds:
            await self._sync_guild(guild, "Synced command(s) to guild %s")

    async def _sync_global(self) -> bool:
        """Sync global commands unless their payload hash is unchanged. Returns True if synced."""
        payload = [cmd.to_dict(self.tree) for cmd in self.tree.get_commands()]
        digest = command_hash(payload)
        try:
            stored = await self.deps.command_hashes.load()
        except Exception as exc:
            log.warning("Could not read the command hash: %s", exc)
            stored = None
        if stored == digest:
            log.info("Global commands unchanged; skipped sync")
            return False

        await self.tree.sync()
        try:
            await self.deps.command_hashes.save(digest)
        except Exception as exc:
            log.warning("Could not store the command hash: %s", exc)
        return True

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

    async def close(self) -> None:
        await super().close()
        if self.deps.engine is not None:
            await self.deps.engine.dispose()


def build_deps(settings: Settings, clock: Clock) -> BotDeps:
    engine = create_engine(settings.database_url)
    uows = UowFactory(create_sessionmaker(engine), clock, settings.default_timezone)
    return BotDeps(
        uows=uows,
        signal=ScheduleSignal(),
        command_hashes=DbCommandHashStore(uows),
        engine=engine,
    )


def run(settings: Settings) -> None:
    clock = SystemClock()
    client = SidequestClient(settings, clock, build_deps(settings, clock))
    # log_handler=None: keep the logging set up by sidequest.logging.
    client.run(settings.discord_token.get_secret_value(), log_handler=None)
