"""Service-level tests for clearing a server's reminder channel (D36)."""

from datetime import UTC, datetime, time

import pytest

from sidequest.core.errors import Forbidden, InvalidOperation, ReminderChannelNotSet
from sidequest.core.recurrence import DailyRule
from sidequest.services import occurrences, settings, todos
from sidequest.services.actor import Actor
from sidequest.services.dto import DueInput, DueReminder
from sidequest.services.uow import Uow
from tests.support.clock import FixedClock

GUILD = 100
GUILD_OTHER = 200
OWNER = 1
MANAGER = 9
CHANNEL = 555
CHANNEL_OTHER = 556


def member(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, day, hour, minute, tzinfo=UTC)


async def _set_channel(uow: Uow, guild_id: int = GUILD, channel_id: int = CHANNEL) -> None:
    await settings.set_reminder_channel(uow, member(MANAGER, guild_id, True), channel_id)


async def _clear(uow: Uow, guild_id: int = GUILD) -> None:
    await settings.clear_reminder_channel(uow, member(MANAGER, guild_id, True))


async def _timed_server_todo(uow: Uow, guild_id: int = GUILD, title: str = "timed") -> int:
    out = await todos.create_once(
        uow,
        member(OWNER, guild_id),
        title=title,
        due=DueInput(time=time(10, 0)),
    )
    return out.value.id


async def test_manager_clears_the_reminder_channel(uow: Uow) -> None:
    await _set_channel(uow)
    await _clear(uow)
    assert (await settings.get_guild_settings(uow, GUILD)).reminder_channel_id is None


async def test_clearing_without_a_channel_is_invalid(uow: Uow) -> None:
    with pytest.raises(InvalidOperation):
        await _clear(uow)


async def test_clearing_twice_is_invalid_the_second_time(uow: Uow) -> None:
    await _set_channel(uow)
    await _clear(uow)
    with pytest.raises(InvalidOperation):
        await _clear(uow)


async def test_member_without_manage_server_is_forbidden_and_channel_stays(uow: Uow) -> None:
    await _set_channel(uow)
    with pytest.raises(Forbidden):
        await settings.clear_reminder_channel(uow, member(OWNER, GUILD, False))
    assert (await settings.get_guild_settings(uow, GUILD)).reminder_channel_id == CHANNEL


async def test_clearing_outside_a_server_is_invalid(uow: Uow) -> None:
    await _set_channel(uow)
    with pytest.raises(InvalidOperation):
        await settings.clear_reminder_channel(uow, member(MANAGER, None, True))


async def test_count_scheduled_server_todos_counts_only_open_timed_server_todos(
    uow: Uow,
) -> None:
    await _set_channel(uow)
    await _set_channel(uow, GUILD_OTHER, CHANNEL_OTHER)

    # Counts: timed one-time server to-do.
    await _timed_server_todo(uow, title="once timed")
    # Counts: daily server to-do with a pending reminder.
    await todos.create_recurring(
        uow,
        member(OWNER, GUILD),
        title="daily",
        rule=DailyRule(times=["08:00"]),
    )
    # Does not count: untimed server to-do.
    await todos.create_once(uow, member(OWNER, GUILD), title="untimed")
    # Does not count: timed server to-do in another guild.
    await _timed_server_todo(uow, guild_id=GUILD_OTHER, title="other guild")
    # Does not count: timed server to-do that is completed.
    done_id = await _timed_server_todo(uow, title="completed")
    await todos.complete(uow, member(OWNER, GUILD), done_id)

    assert await settings.count_scheduled_server_todos(uow, GUILD) == 2


async def test_after_clearing_timed_server_todos_cannot_be_created(uow: Uow) -> None:
    await _set_channel(uow)
    await _clear(uow)
    with pytest.raises(ReminderChannelNotSet):
        await _timed_server_todo(uow, title="too late")


async def test_todo_created_before_clearing_is_claimed_without_a_channel(
    uow: Uow, clock: FixedClock
) -> None:
    await _set_channel(uow)
    tid = await _timed_server_todo(uow, title="before clear")
    await _clear(uow)

    clock.set(utc(7, 10))
    claimed = await occurrences.claim_due(uow, clock.now())
    mine: list[DueReminder] = [r for r in claimed if r.todo.id == tid]
    assert len(mine) == 1
    assert mine[0].channel_id is None
