"""Editing a repeating to-do after its next reminder was checked off early must not bring
that reminder back: the new pending one comes after the checked-off one."""

from datetime import UTC, datetime

import pytest

from sidequest.core.recurrence import DailyRule
from sidequest.services import occurrences, settings, todos
from sidequest.services.actor import Actor
from sidequest.services.dto import TodoPatch
from sidequest.services.uow import Uow
from tests.support.clock import FixedClock

GUILD = 100
CHANNEL = 555
ACTOR = Actor(user_id=1, guild_id=GUILD, can_manage_guild=False, origin="discord")
MANAGER = Actor(user_id=9, guild_id=GUILD, can_manage_guild=True, origin="discord")


def at(day: int, hour: int) -> datetime:
    return datetime(2026, 11, day, hour, tzinfo=UTC)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(at(16, 10))


PATCHES = [
    pytest.param(TodoPatch(timezone="UTC"), at(17, 20), id="same zone"),
    pytest.param(TodoPatch(rule=DailyRule(times=["20:00", "22:00"])), at(16, 22), id="new times"),
    pytest.param(TodoPatch(rule=DailyRule(times=["20:00"], end=at(20, 0).date())), at(17, 20)),
]


@pytest.mark.parametrize(("patch", "expected"), PATCHES)
async def test_edit_after_early_check_off_keeps_it_checked_off(
    uow: Uow, clock: FixedClock, patch: TodoPatch, expected: datetime
) -> None:
    await settings.set_reminder_channel(uow, MANAGER, CHANNEL)
    view = (
        await todos.create_recurring(uow, ACTOR, title="water", rule=DailyRule(times=["20:00"]))
    ).value
    assert view.next_due_at == at(16, 20)
    assert view.pending_occurrence_id is not None

    await occurrences.complete_occurrence(uow, ACTOR, view.pending_occurrence_id)
    assert (await todos.get(uow, ACTOR, view.id)).next_due_at == at(17, 20)

    edited = (await todos.edit(uow, ACTOR, view.id, patch)).value
    assert edited.next_due_at == expected
