"""Run Alembic migrations from code (used by `sidequest` and `sidequest migrate`)."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config


def alembic_config(database_url: str) -> Config:
    # alembic.ini lives in the working directory (/app in Docker, repo root locally).
    ini = Path(os.environ.get("ALEMBIC_CONFIG", "alembic.ini"))
    if not ini.is_file():
        raise FileNotFoundError(f"{ini.resolve()} not found; run from the project directory")
    config = Config(str(ini))
    config.attributes["database_url"] = database_url
    return config


def upgrade_head(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
