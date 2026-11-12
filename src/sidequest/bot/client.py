"""Discord client: gateway with no intents; everything arrives as interactions (D11)."""

import asyncio
import contextlib
import hashlib
import json
import logging
import signal
from collections.abc import Callable
from typing import Any

import discord
from discord import app_commands

from sidequest.bot.adapter import BotDeps, DbCommandHashStore
from sidequest.bot.commands.about import SidequestGroup
from sidequest.bot.commands.lists import build_lists_group
from sidequest.bot.commands.settings import build_settings_group
from sidequest.bot.commands.todo import build_todo_group
from sidequest.bot.errors import report_error
from sidequest.bot.notifier import DiscordNotifier
from sidequest.bot.views.reminder import DoneButton, SubtaskSelect
from sidequest.config import Settings
from sidequest.core.clock import Clock, SystemClock
from sidequest.db.session import create_engine, create_sessionmaker
from sidequest.health import HEARTBEAT_FILE, Watchdog
from sidequest.scheduler.loop import Scheduler
from sidequest.scheduler.retention import HistoryPurger
from sidequest.scheduler.signal import ScheduleSignal
from sidequest.services.dto import DueReminder
from sidequest.services.uow import UowFactory

log = logging.getLogger(__name__)

SCHEDULER_STOP_TIMEOUT = 5.0
"""Seconds `close()` waits for the scheduler to finish its iteration before cancelling it.
Docker sends SIGKILL 10 s after SIGTERM, so this leaves time for the rest of the shutdown."""


def command_hash(payload: list[dict[str, Any]]) -> str:
    """sha256 hex of the payload as canonical JSON (sort_keys=True, separators=(",", ":"))."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class SidequestClient(discord.Client):
    def __init__(self, settings: Settings, clock: Clock, deps: BotDeps) -> None:
        # Nobody is pinged unless a send says so explicitly (reminders ping their users).
        super().__init__(
            intents=discord.Intents.none(), allowed_mentions=discord.AllowedMentions.none()
        )
        self.settings = settings
        self.clock = clock
        self.deps = deps
        self.started_at = clock.now()
        self.tree = app_commands.CommandTree(self)
        self.tree.error(report_error)
        self._scheduler: Scheduler | None = None
        self._scheduler_task: asyncio.Task[None] | None = None
        self._watchdog: Watchdog | None = None
        self._purger_task: asyncio.Task[None] | None = None
        self._shutting_down = False

    async def setup_hook(self) -> None:
        self.tree.add_command(SidequestGroup(self.settings, self.started_at))
        self.tree.add_command(build_todo_group())
        self.tree.add_command(build_lists_group())
        self.tree.add_command(build_settings_group())
        # Reminder buttons/selects: matched by custom_id, so they survive restarts.
        self.add_dynamic_items(DoneButton, SubtaskSelect)

        await self._sync_commands()

        # A stop signal during the command sync already ran close(); start nothing new then.
        if self.deps.run_scheduler and not self._shutting_down:
            self._start_scheduler()
            self._start_history_cleanup()

    def _start_scheduler(self) -> None:
        """Runs in the background; REST calls work from here on, before the gateway is up."""
        scheduler = Scheduler(self.deps.uows, DiscordNotifier(self), self.deps.signal, self.clock)
        task = asyncio.create_task(scheduler.run(), name="sidequest-scheduler")
        task.add_done_callback(_scheduler_stopped)
        self._scheduler = scheduler
        self._scheduler_task = task
        # Exits the process if the heartbeat goes stale, so Docker restarts the bot (D38).
        self._watchdog = Watchdog(HEARTBEAT_FILE)
        self._watchdog.start()

    async def repost(self, reminder: DueReminder) -> None:
        """Post a reminder whose check-off was undone (D64): post, attach the message id,
        or mark it failed. Without a running scheduler nothing happens here; its crash
        recovery posts the reminder within ~1–2 minutes once it runs."""
        if self._scheduler is not None:
            await self._scheduler.deliver(reminder)

    def _start_history_cleanup(self) -> None:
        """Daily deletion of old history (D8), only when HISTORY_RETENTION_DAYS is set."""
        days = self.settings.history_retention_days
        if days is None:
            return
        purger = HistoryPurger(self.deps.uows, self.clock, days)
        self._purger_task = asyncio.create_task(purger.run(), name="sidequest-history-cleanup")
        log.info("History cleanup on: keeping %d days", days)

    async def _stop_history_cleanup(self) -> None:
        """Cancel it: it is idle almost always, and a cancelled cleanup just rolls back."""
        task, self._purger_task = self._purger_task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _stop_scheduler(self) -> None:
        """Let the scheduler finish its current iteration; cancel it if that takes too long."""
        scheduler, task = self._scheduler, self._scheduler_task
        self._scheduler = self._scheduler_task = None
        if scheduler is None or task is None or task.done():
            return
        scheduler.stop()
        await asyncio.wait({task}, timeout=SCHEDULER_STOP_TIMEOUT)
        if not task.done():
            log.warning("Scheduler still busy after %.0f s; cancelling it", SCHEDULER_STOP_TIMEOUT)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _sync_commands(self) -> None:
        """Register commands with Discord (D32). Never both global and guild copies: a guild
        that has both shows every command twice.

        - SYNC_GLOBAL=true: global commands (every server the bot is installed in; there
          are no DM or user-install commands, D40). Guilds in SYNC_GUILD_IDS get their guild
          commands deleted, cleaning up after server-only mode.
        - SYNC_GLOBAL=false: server-only mode for a dev bot. Commands go to SYNC_GUILD_IDS
          (instant) and the global commands are cleared.

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
        self._shutting_down = True
        if self._watchdog is not None:
            self._watchdog.stop()  # the heartbeat stops now; that's not a hang
            self._watchdog = None
        await self._stop_history_cleanup()
        await self._stop_scheduler()
        await super().close()
        if self.deps.engine is not None:
            await self.deps.engine.dispose()


def _scheduler_stopped(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        log.critical("Scheduler crashed; the watchdog will restart the bot", exc_info=exc)
    else:
        log.info("Scheduler stopped")


def build_deps(settings: Settings, clock: Clock) -> BotDeps:
    engine = create_engine(settings.database_url)
    uows = UowFactory(create_sessionmaker(engine), clock, settings.default_timezone)
    return BotDeps(
        uows=uows,
        signal=ScheduleSignal(),
        command_hashes=DbCommandHashStore(uows),
        engine=engine,
    )


async def serve(client: discord.Client, token: str) -> None:
    """Run the client until it stops by itself or SIGTERM/SIGINT arrives, then close it.

    Docker stops a container with SIGTERM. Python running as PID 1 ignores SIGTERM unless a
    handler is installed, so without this Docker would wait 10 s and SIGKILL the bot.
    """
    stop = asyncio.Event()
    _on_stop_signals(stop.set)
    async with client:
        runner = asyncio.create_task(client.start(token), name="sidequest-discord")
        stopper = asyncio.create_task(stop.wait(), name="sidequest-stop-signal")
        await asyncio.wait({runner, stopper}, return_when=asyncio.FIRST_COMPLETED)
        stopper.cancel()
        if not runner.done():
            log.info("Shutting down")
            await client.close()  # start() returns once the gateway is closed
        await runner  # re-raises a login/connection failure
    log.info("Stopped")


def _on_stop_signals(callback: Callable[[], None]) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Windows event loops have no signal handlers; Ctrl+C there cancels the main
        # task instead, and `async with client` still closes the client.
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, _log_signal_then(sig, callback))


def _log_signal_then(sig: signal.Signals, callback: Callable[[], None]) -> Callable[[], None]:
    def handler() -> None:
        log.info("Received %s", sig.name)
        callback()

    return handler


def run(settings: Settings) -> None:
    clock = SystemClock()
    client = SidequestClient(settings, clock, build_deps(settings, clock))
    # Logging is set up by sidequest.logging; discord.py's own setup (Client.run) isn't used.
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(client, settings.discord_token.get_secret_value()))
