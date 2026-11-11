"""Graceful shutdown: `serve()` closes the client on a stop signal, and closing the client lets
the scheduler finish its iteration (or cancels it after a timeout)."""

import asyncio
from collections.abc import Callable
from types import TracebackType

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from sidequest.bot import client as client_module
from sidequest.bot.adapter import BotDeps
from sidequest.bot.client import SidequestClient, serve
from sidequest.config import Settings
from sidequest.core.clock import SystemClock
from sidequest.scheduler.signal import ScheduleSignal
from sidequest.services.uow import UowFactory


class FakeClient:
    """Just what `serve()` uses: async context manager, start(), close()."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.events: list[str] = []
        self._closed = asyncio.Event()
        self._fail_with = fail_with

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.events.append("exit")
        if not self._closed.is_set():
            await self.close()

    async def start(self, token: str) -> None:
        self.events.append(f"start {token}")
        if self._fail_with is not None:
            raise self._fail_with
        await self._closed.wait()
        self.events.append("start returned")

    async def close(self) -> None:
        self.events.append("close")
        self._closed.set()


@pytest.fixture
def stop_signal(monkeypatch: pytest.MonkeyPatch) -> list[Callable[[], None]]:
    """Captures the callback `serve()` registers for SIGTERM/SIGINT."""
    callbacks: list[Callable[[], None]] = []
    monkeypatch.setattr(client_module, "_on_stop_signals", callbacks.append)
    return callbacks


async def test_stop_signal_closes_client_and_returns(
    stop_signal: list[Callable[[], None]],
) -> None:
    fake = FakeClient()
    task = asyncio.create_task(serve(fake, "tok"))  # type: ignore[arg-type]
    await asyncio.sleep(0.01)
    assert fake.events == ["start tok"]

    [trigger] = stop_signal
    trigger()
    await asyncio.wait_for(task, timeout=2)

    assert fake.events == ["start tok", "close", "start returned", "exit"]


async def test_start_failure_propagates_and_closes(stop_signal: list[Callable[[], None]]) -> None:
    fake = FakeClient(fail_with=RuntimeError("bad token"))

    with pytest.raises(RuntimeError, match="bad token"):
        await serve(fake, "tok")  # type: ignore[arg-type]

    assert fake.events == ["start tok", "exit", "close"]


class FakeScheduler:
    def __init__(self, *, obeys_stop: bool) -> None:
        self.obeys_stop = obeys_stop
        self.stopped = asyncio.Event()
        self.finished = False

    def stop(self) -> None:
        if self.obeys_stop:
            self.stopped.set()

    async def run(self) -> None:
        await self.stopped.wait()
        self.finished = True


def make_client(scheduler: FakeScheduler) -> tuple[SidequestClient, asyncio.Task[None]]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        discord_token="token",  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@h/db",  # type: ignore[call-arg]
    )
    clock = SystemClock()
    deps = BotDeps(
        uows=UowFactory(async_sessionmaker(), clock),
        signal=ScheduleSignal(),
        command_hashes=None,  # type: ignore[arg-type]  # not used here
        run_scheduler=False,
    )
    client = SidequestClient(settings, clock, deps)
    task = asyncio.create_task(scheduler.run())
    client._scheduler = scheduler  # type: ignore[assignment]
    client._scheduler_task = task
    return client, task


async def test_close_lets_the_scheduler_finish() -> None:
    scheduler = FakeScheduler(obeys_stop=True)
    client, task = make_client(scheduler)
    await asyncio.sleep(0)

    await client.close()

    assert scheduler.finished
    assert task.done() and not task.cancelled()


async def test_close_cancels_a_scheduler_that_does_not_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_module, "SCHEDULER_STOP_TIMEOUT", 0.05)
    scheduler = FakeScheduler(obeys_stop=False)
    client, task = make_client(scheduler)
    await asyncio.sleep(0)

    await client.close()

    assert task.cancelled()
    assert not scheduler.finished
