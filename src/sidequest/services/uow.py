"""Unit of work: what every service function receives first."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sidequest.core.clock import Clock


@dataclass
class Uow:
    """One database session plus the clock and config the services need.

    Service functions commit their own work. Tests build one directly around the test
    session: ``Uow(session, FixedClock(...))``.
    """

    session: AsyncSession
    clock: Clock
    default_timezone: str = "UTC"


class UowFactory:
    """Opens a fresh `Uow` per request: ``async with uows() as uow: ...``."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        default_timezone: str = "UTC",
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._default_timezone = default_timezone

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[Uow]:
        async with self._sessions() as session:
            yield Uow(session, self._clock, self._default_timezone)
