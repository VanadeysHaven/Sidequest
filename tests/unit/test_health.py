"""Heartbeat check (`sidequest.health`) and the `sidequest healthcheck` command."""

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sidequest import cli, health

NOW = datetime(2030, 1, 7, 12, 0, tzinfo=UTC)


def test_fresh_heartbeat_is_healthy(tmp_path: Path) -> None:
    path = tmp_path / "beat"
    health.write_heartbeat(path, NOW - timedelta(seconds=30))

    assert health.check_heartbeat(path, NOW) is None


def test_heartbeat_exactly_at_the_limit_is_healthy(tmp_path: Path) -> None:
    path = tmp_path / "beat"
    health.write_heartbeat(path, NOW - health.MAX_AGE)

    assert health.check_heartbeat(path, NOW) is None


def test_old_heartbeat_is_unhealthy(tmp_path: Path) -> None:
    path = tmp_path / "beat"
    health.write_heartbeat(path, NOW - timedelta(minutes=3, seconds=1))

    assert health.check_heartbeat(path, NOW) == "heartbeat is 181 s old (limit 180 s)"


def test_missing_heartbeat_is_unhealthy(tmp_path: Path) -> None:
    problem = health.check_heartbeat(tmp_path / "missing", NOW)

    assert problem is not None and problem.startswith("no heartbeat yet")


@pytest.mark.parametrize("content", ["", "garbage", "2030-01-07T12:00:00"])
def test_unreadable_heartbeat_is_unhealthy(tmp_path: Path, content: str) -> None:
    path = tmp_path / "beat"
    path.write_text(content, encoding="utf-8")

    assert health.check_heartbeat(path, NOW) is not None


def test_healthcheck_command_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "beat"
    monkeypatch.setattr(health, "HEARTBEAT_FILE", path)
    # The healthcheck must not need settings (no token or database in its environment).
    monkeypatch.setattr(cli, "load_settings", lambda: pytest.fail("healthcheck loaded settings"))

    assert cli.main(["healthcheck"]) == 1
    assert "unhealthy: no heartbeat yet" in capsys.readouterr().err

    health.write_heartbeat(path, datetime.now(UTC))
    assert cli.main(["healthcheck"]) == 0
    assert capsys.readouterr().out == "healthy\n"


class Ticker:
    """A settable monotonic clock (seconds)."""

    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def make_watchdog(path: Path, ticker: Ticker, **kwargs: object) -> health.Watchdog:
    options: dict[str, object] = {
        "on_stale": lambda problem: None,
        "max_age": timedelta(minutes=3),
        "start_grace": timedelta(minutes=5),
        "monotonic": ticker,
    }
    options.update(kwargs)
    return health.Watchdog(path, **options)  # type: ignore[arg-type]


def test_write_heartbeat_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "beat"
    health.write_heartbeat(path, NOW)
    health.write_heartbeat(path, NOW + timedelta(seconds=1))

    assert sorted(p.name for p in tmp_path.iterdir()) == ["beat"]
    assert health.check_heartbeat(path, NOW + timedelta(seconds=1)) is None


def test_watchdog_allows_start_grace_before_first_heartbeat(tmp_path: Path) -> None:
    ticker = Ticker()
    dog = make_watchdog(tmp_path / "beat", ticker)

    ticker.value += 300
    assert dog.problem() is None

    ticker.value += 1
    assert dog.problem() == "no heartbeat within 300 s of starting"


def test_watchdog_flags_a_heartbeat_that_stops_changing(tmp_path: Path) -> None:
    path = tmp_path / "beat"
    ticker = Ticker()
    dog = make_watchdog(path, ticker)
    health.write_heartbeat(path, NOW)
    assert dog.problem() is None

    ticker.value += 120
    health.write_heartbeat(path, NOW + timedelta(minutes=2))
    assert dog.problem() is None

    ticker.value += 180
    assert dog.problem() is None

    ticker.value += 1
    assert dog.problem() == "heartbeat unchanged for 181 s (limit 180 s)"


def test_watchdog_ignores_wall_clock_jumps(tmp_path: Path) -> None:
    """After a Pi boots, NTP can move the wall clock hours ahead of the last beat."""
    path = tmp_path / "beat"
    ticker = Ticker()
    dog = make_watchdog(path, ticker)
    health.write_heartbeat(path, NOW - timedelta(hours=1))
    assert dog.problem() is None

    ticker.value += 60
    health.write_heartbeat(path, NOW)
    assert dog.problem() is None


def test_watchdog_thread_calls_on_stale_once(tmp_path: Path) -> None:
    problems: list[str] = []
    fired = threading.Event()

    def on_stale(problem: str) -> None:
        problems.append(problem)
        fired.set()

    ticker = Ticker()
    dog = make_watchdog(
        tmp_path / "beat", ticker, on_stale=on_stale, interval=0.01, start_grace=timedelta(0)
    )
    dog.start()
    ticker.value += 1

    assert fired.wait(timeout=2)
    dog.stop()
    assert problems == ["no heartbeat within 0 s of starting"]


def test_stopped_watchdog_never_fires(tmp_path: Path) -> None:
    problems: list[str] = []
    ticker = Ticker()
    dog = make_watchdog(
        tmp_path / "beat", ticker, on_stale=problems.append, interval=0.05, start_grace=timedelta(0)
    )
    dog.start()
    dog.stop()
    ticker.value += 1

    threading.Event().wait(0.15)
    assert problems == []
