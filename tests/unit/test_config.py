"""Unit tests for `sidequest.config.Settings`."""

import pytest
from pydantic import ValidationError

from sidequest.config import Settings

ENV_VARS = (
    "DISCORD_TOKEN",
    "DATABASE_URL",
    "DEFAULT_TIMEZONE",
    "LOG_LEVEL",
    "SYNC_GLOBAL",
    "SYNC_GUILD_IDS",
    "RUN_MIGRATIONS",
    "COMMIT",
    "BRANCH",
    "DEPLOY_TIME",
    "HISTORY_RETENTION_DAYS",
)

DATABASE_URL = "postgresql+asyncpg://u:p@h/db"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "discord_token": "token",
        "database_url": DATABASE_URL,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_defaults_when_only_required_values_given() -> None:
    settings = make_settings()

    assert settings.discord_token.get_secret_value() == "token"
    assert settings.database_url == DATABASE_URL
    assert settings.default_timezone == "UTC"
    assert settings.log_level == "INFO"
    assert settings.sync_global is True
    assert settings.sync_guild_ids == []
    assert settings.run_migrations is True
    assert settings.commit is None
    assert settings.branch is None
    assert settings.deploy_time is None


def test_valid_timezone_is_accepted() -> None:
    settings = make_settings(default_timezone="Europe/Amsterdam")

    assert settings.default_timezone == "Europe/Amsterdam"


@pytest.mark.parametrize("timezone", ["Mars/Olympus", "", "not a zone"])
def test_invalid_timezone_is_rejected(timezone: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(default_timezone=timezone)


def test_log_level_is_uppercased() -> None:
    settings = make_settings(log_level="debug")

    assert settings.log_level == "DEBUG"


def test_unknown_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(log_level="LOUD")


def test_values_are_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "env-token")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("SYNC_GUILD_IDS", "123,456")
    monkeypatch.setenv("RUN_MIGRATIONS", "false")
    monkeypatch.setenv("DEPLOY_TIME", "1700000000")
    monkeypatch.setenv("COMMIT", "abc1234")
    monkeypatch.setenv("BRANCH", "main")

    settings = Settings(_env_file=None)

    assert settings.discord_token.get_secret_value() == "env-token"
    assert settings.sync_guild_ids == [123, 456]
    assert settings.run_migrations is False
    assert settings.deploy_time == 1700000000
    assert settings.commit == "abc1234"
    assert settings.branch == "main"


def test_empty_environment_value_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("SYNC_GUILD_IDS", "")

    settings = Settings(_env_file=None)

    assert settings.sync_guild_ids == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("123", [123]),
        (" 123 , 456 ", [123, 456]),
        ("123,,456,", [123, 456]),
        (" , ", []),
    ],
)
def test_sync_guild_ids_are_split_and_stripped(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[int]
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("SYNC_GUILD_IDS", raw)

    settings = Settings(_env_file=None)

    assert settings.sync_guild_ids == expected


def test_non_numeric_sync_guild_id_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("SYNC_GUILD_IDS", "123,abc")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_sync_guild_ids_accepts_list_kwarg() -> None:
    settings = Settings(
        _env_file=None,
        discord_token="token",
        database_url=DATABASE_URL,
        sync_guild_ids=[1, 2],
    )

    assert settings.sync_guild_ids == [1, 2]


def test_missing_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_server_only_sync_reads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("SYNC_GLOBAL", "false")
    monkeypatch.setenv("SYNC_GUILD_IDS", "123")

    settings = Settings(_env_file=None)

    assert settings.sync_global is False
    assert settings.sync_guild_ids == [123]


def test_server_only_sync_without_guild_ids_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("SYNC_GLOBAL", "false")

    with pytest.raises(ValidationError, match="SYNC_GLOBAL=false requires"):
        Settings(_env_file=None)


def test_global_sync_without_guild_ids_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("SYNC_GLOBAL", "true")

    settings = Settings(_env_file=None)

    assert settings.sync_global is True
    assert settings.sync_guild_ids == []


def test_history_retention_is_unset_by_default() -> None:
    settings = make_settings()

    assert settings.history_retention_days is None


def test_history_retention_days_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("HISTORY_RETENTION_DAYS", "30")

    settings = Settings(_env_file=None)

    assert settings.history_retention_days == 30


def test_empty_history_retention_days_keeps_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("HISTORY_RETENTION_DAYS", "")

    settings = Settings(_env_file=None)

    assert settings.history_retention_days is None


def test_zero_history_retention_days_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("HISTORY_RETENTION_DAYS", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
