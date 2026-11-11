"""`sidequest` command line entry point."""

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

from sidequest import __version__
from sidequest.logging import setup_logging

if TYPE_CHECKING:
    from sidequest.config import Settings

log = logging.getLogger(__name__)


def load_settings() -> "Settings":
    # Imported here so `sidequest healthcheck` (every minute on the Pi) skips pydantic.
    from sidequest.config import load_settings as load

    return load()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sidequest",
        description="Sidequest Discord to-do bot. Without a command: migrate (if enabled) and run.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.add_parser("migrate", help="apply database migrations (alembic upgrade head)")
    commands.add_parser(
        "healthcheck",
        help="exit 1 unless the reminder loop wrote its heartbeat in the last 3 minutes",
    )
    commands.add_parser("web", help="web frontend (not implemented yet)")
    return parser


def run_migrations(settings: "Settings") -> None:
    from sidequest.db.migrate import upgrade_head

    log.info("Applying database migrations")
    upgrade_head(settings.database_url)


def run_bot(settings: "Settings") -> None:
    from sidequest.bot.client import run

    run(settings)


def healthcheck() -> int:
    """Docker HEALTHCHECK. Needs no settings, database or Discord: it only reads a file."""
    from sidequest.core.clock import SystemClock
    from sidequest.health import HEARTBEAT_FILE, check_heartbeat

    problem = check_heartbeat(HEARTBEAT_FILE, SystemClock().now())
    if problem is not None:
        sys.stderr.write(f"unhealthy: {problem}\n")
        return 1
    sys.stdout.write("healthy\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "healthcheck":
        return healthcheck()

    if args.command == "web":
        sys.stderr.write("sidequest web: not implemented yet\n")
        return 2

    settings = load_settings()
    setup_logging(settings.log_level)

    if args.command == "migrate":
        run_migrations(settings)
        return 0

    if settings.run_migrations:
        run_migrations(settings)
    run_bot(settings)
    return 0
