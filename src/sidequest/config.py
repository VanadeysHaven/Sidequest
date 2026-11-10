"""Runtime configuration from environment variables and `configs/.env`."""

from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class DatabaseSettings(BaseSettings):
    """Only what the database layer needs, so Alembic can run without a bot token."""

    model_config = SettingsConfigDict(
        env_file="configs/.env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    database_url: str


class Settings(DatabaseSettings):
    discord_token: SecretStr
    default_timezone: str = "UTC"
    log_level: str = "INFO"
    # Command sync (D32). SYNC_GLOBAL=true: global commands; the listed guilds get their guild
    # commands deleted (cleans up after server-only mode). SYNC_GLOBAL=false: server-only mode
    # for a dev bot; commands go to the listed guilds only and global commands are cleared.
    # Env format: SYNC_GUILD_IDS=123,456
    sync_global: bool = True
    sync_guild_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    run_migrations: bool = True

    # Written by update.sh into configs/git.env.
    commit: str | None = None
    branch: str | None = None
    deploy_time: int | None = None  # unix seconds

    @field_validator("default_timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone: {value!r}") from exc
        return value

    @field_validator("sync_guild_ids", mode="before")
    @classmethod
    def _split_guild_ids(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def _server_only_needs_guilds(self) -> "Settings":
        if not self.sync_global and not self.sync_guild_ids:
            # Would clear the global commands and register none anywhere.
            raise ValueError("SYNC_GLOBAL=false requires at least one ID in SYNC_GUILD_IDS")
        return self

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}")
        return level


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
