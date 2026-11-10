"""`sidequest` command line entry point."""

import argparse
import logging
import sys
from collections.abc import Sequence

from sidequest import __version__
from sidequest.config import Settings, load_settings
from sidequest.logging import setup_logging

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sidequest",
        description="Sidequest Discord to-do bot. Without a command: migrate (if enabled) and run.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.add_parser("migrate", help="apply database migrations (alembic upgrade head)")
    commands.add_parser("web", help="web frontend (not implemented yet)")
    return parser


def run_migrations(settings: Settings) -> None:
    from sidequest.db.migrate import upgrade_head

    log.info("Applying database migrations")
    upgrade_head(settings.database_url)


def run_bot(settings: Settings) -> None:
    from sidequest.bot.client import run

    run(settings)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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
