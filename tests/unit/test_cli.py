"""Unit tests for the `sidequest` command line entry point."""

from collections.abc import Callable

import pytest

from sidequest import cli
from sidequest.config import Settings

DATABASE_URL = "postgresql+asyncpg://u:p@h/db"


def make_settings(run_migrations: bool) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        discord_token="token",  # type: ignore[call-arg]
        database_url=DATABASE_URL,  # type: ignore[call-arg]
        run_migrations=run_migrations,  # type: ignore[call-arg]
    )


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    recorded: list[str] = []
    monkeypatch.setattr(cli, "setup_logging", lambda level: None)
    monkeypatch.setattr(cli, "run_migrations", lambda settings: recorded.append("migrate"))
    monkeypatch.setattr(cli, "run_bot", lambda settings: recorded.append("bot"))
    return recorded


@pytest.fixture
def set_settings(monkeypatch: pytest.MonkeyPatch) -> Callable[[bool], None]:
    def _set(run_migrations: bool) -> None:
        settings = make_settings(run_migrations)
        monkeypatch.setattr(cli, "load_settings", lambda: settings)

    return _set


def test_default_run_migrates_then_starts_bot(
    calls: list[str], set_settings: Callable[[bool], None]
) -> None:
    set_settings(True)

    result = cli.main([])

    assert calls == ["migrate", "bot"]
    assert result == 0


def test_run_skips_migrations_when_disabled(
    calls: list[str], set_settings: Callable[[bool], None]
) -> None:
    set_settings(False)

    result = cli.main([])

    assert calls == ["bot"]
    assert result == 0


def test_migrate_runs_only_migrations(
    calls: list[str], set_settings: Callable[[bool], None]
) -> None:
    set_settings(True)

    result = cli.main(["migrate"])

    assert calls == ["migrate"]
    assert result == 0


def test_migrate_runs_migrations_even_when_disabled_in_settings(
    calls: list[str], set_settings: Callable[[bool], None]
) -> None:
    set_settings(False)

    result = cli.main(["migrate"])

    assert calls == ["migrate"]
    assert result == 0


def test_web_is_not_implemented(
    calls: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_load_settings() -> Settings:
        pytest.fail("load_settings must not be called for `web`")

    monkeypatch.setattr(cli, "load_settings", fail_load_settings)

    result = cli.main(["web"])

    assert result == 2
    assert calls == []
    assert "not implemented" in capsys.readouterr().err


def test_version_prints_program_name_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])

    assert excinfo.value.code == 0
    assert "sidequest" in capsys.readouterr().out


def test_unknown_command_exits_with_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bogus"])

    assert excinfo.value.code == 2
