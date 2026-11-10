"""Process-wide logging setup: plain lines on stdout (Docker collects them)."""

import logging
import sys
import time


def setup_logging(level: str) -> None:
    formatter = logging.Formatter("%(asctime)sZ %(levelname)-8s %(name)s: %(message)s")
    formatter.converter = time.gmtime

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    # discord.py is chatty at INFO; only show its internals when debugging.
    logging.getLogger("discord").setLevel(logging.DEBUG if level == "DEBUG" else logging.WARNING)
    # Alembic logs one INFO line per internal plugin on every start.
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)
