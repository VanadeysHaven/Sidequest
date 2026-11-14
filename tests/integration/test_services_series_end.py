"""Service-level tests for repeating to-dos that run out (D73-D78): the last occurrence, the
"anything left?" check on create and edit, checking off and undoing the last one."""

import re
from datetime import UTC, date, datetime
from typing import Literal

import pytest
from sqlalchemy import select

from sidequest.core.enums import OccurrenceStatus, TodoStatus, Weekday
from sidequest.core.errors import InvalidRule, NameTaken
from sidequest.core.recurrence import DailyRule, RecurrenceRule, WeeklyRule
from sidequest.db.models import Occurrence
from sidequest.services import occurrences, settings, todos, undo
from sidequest.services.actor import Actor
from sidequest.services.dto import CheckedOff, DueReminder, TodoPatch, TodoView
from sidequest.services.uow import Uow
from tests.support.clock import FixedClock

GUILD = 100
OWNER = 1
MANAGER = 9
CHANNEL = 555
TITLE = "stretch"
NOW = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)  # a Monday

CheckOffPath = Literal["early", "reminder", "complete"]


def member(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


ACTOR = member(OWNER, GUILD)
MANAGER_ACTOR = member(MANAGER, GUILD, True)


@pytest.fixture
def clock() -> FixedClock:
    """Overrides the conftest clock: these tests work in November 2026, starting Monday 07:00."""
    return FixedClock(NOW)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def nov(day: int) -> date:
    return date(2026, 11, day)


async def _occurrences(uow: Uow, todo_id: int) -> list[Occurrence]:
    rows = await uow.session.scalars(
        select(Occurrence).where(Occurrence.todo_id == todo_id).order_by(Occurrence.id)
    )
    return list(rows)


def _mine(reminders: list[DueReminder], todo_id: int) -> list[DueReminder]:
    return [r for r in reminders if r.todo.id == todo_id]


async def _set_channel(uow: Uow) -> None:
    await settings.set_reminder_channel(uow, MANAGER_ACTOR, CHANNEL)


async def _create(uow: Uow, rule: RecurrenceRule, title: str = TITLE) -> TodoView:
    await _set_channel(uow)
    out = await todos.create_recurring(uow, ACTOR, title=title, rule=rule)
    return out.value


async def _check_off_last(
    uow: Uow, clock: FixedClock, how: CheckOffPath
) -> tuple[int, int, CheckedOff]:
    """A series whose only reminder is Monday 16 Nov 08:00, checked off the given way.

    "early": the pending reminder, before it goes out. "reminder": the sent reminder (with a
    message). "complete": `todos.complete` on the sent reminder.
    Returns (to-do id, occurrence id, the check-off's result).
    """
    view = await _create(uow, DailyRule(times=["08:00"], end=nov(16)))
    occ_id = view.pending_occurrence_id
    assert occ_id is not None
    if how == "early":
        clock.set(at(16, 7, 30))
        checked = await occurrences.complete_occurrence(uow, ACTOR, occ_id)
        return view.id, occ_id, checked.value

    clock.set(at(16, 8))
    await occurrences.claim_due(uow, clock.now())
    await occurrences.attach_message(uow, occ_id, CHANNEL, 999)
    clock.set(at(16, 8, 2))
    if how == "reminder":
        checked = await occurrences.complete_occurrence(uow, ACTOR, occ_id)
    else:
        checked = await todos.complete(uow, ACTOR, view.id)
    return view.id, occ_id, checked.value


# --- 1. create: nothing left to remind of is refused -------------------------------------

REFUSED: list[tuple[RecurrenceRule, str]] = [
    pytest.param(  # today's 07:00 has passed and the next one is after the end
        DailyRule(times=["07:00"], end=nov(16)),
        f"No reminder of **{TITLE}** falls between 16-11-2026 and 16-11-2026.",
        id="nothing between now and end",
    ),
    pytest.param(  # the end is before today
        DailyRule(times=["20:00"], end=nov(10)),
        f"No reminder of **{TITLE}** is left: it ends on 10-11-2026.",
        id="end before today",
    ),
    pytest.param(  # Monday 16th is before `start`, Monday 23rd is after `end`
        WeeklyRule(weekdays=[Weekday.MON], times=["08:00"], start=nov(17), end=nov(20)),
        f"No reminder of **{TITLE}** falls between 17-11-2026 and 20-11-2026.",
        id="weekday outside start..end",
    ),
]


@pytest.mark.parametrize(("rule", "message"), REFUSED)
async def test_create_with_no_reminder_in_the_window_is_refused(
    uow: Uow, rule: RecurrenceRule, message: str
) -> None:
    await _set_channel(uow)
    with pytest.raises(InvalidRule) as caught:
        await todos.create_recurring(uow, ACTOR, title=TITLE, rule=rule)
    assert caught.value.message == message

    listed = await todos.list_todos(uow, ACTOR, None)
    assert listed.total == 0


# --- 2. the scheduler posts the last one -------------------------------------------------


async def test_scheduler_posts_the_last_reminder_and_schedules_nothing_after(
    uow: Uow, clock: FixedClock
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"], end=nov(17)))

    clock.set(at(16, 8))
    first = await occurrences.claim_due(uow, clock.now())
    assert [r.occurrence.due_at for r in _mine(first, view.id)] == [at(16, 8)]

    clock.set(at(17, 8))
    last = await occurrences.claim_due(uow, clock.now())
    [reminder] = _mine(last, view.id)
    sent_id = reminder.occurrence.id
    assert reminder.occurrence.status == OccurrenceStatus.SENT
    assert reminder.todo.final_occurrence_id == sent_id

    after = await todos.get(uow, ACTOR, view.id)
    assert after.pending_occurrence_id is None
    assert after.next_due_at is None
    assert after.reminder is not None
    assert after.reminder.id == sent_id
    assert after.final_occurrence_id == sent_id
    assert [o.status for o in await _occurrences(uow, view.id)] == [
        OccurrenceStatus.MISSED,
        OccurrenceStatus.SENT,
    ]

    clock.set(at(18, 8))
    assert _mine(await occurrences.claim_due(uow, clock.now()), view.id) == []


# --- 3. catch-up past the end ------------------------------------------------------------


async def test_catch_up_past_the_end_posts_one_late_reminder_and_nothing_after(
    uow: Uow, clock: FixedClock
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"], end=nov(17)))

    clock.set(at(18, 9))  # downtime that runs past the end
    [mine] = _mine(await occurrences.claim_due(uow, clock.now()), view.id)
    assert mine.occurrence.due_at == at(16, 8)
    assert mine.occurrence.late is True

    occs = await _occurrences(uow, view.id)
    assert [(o.status, o.due_at) for o in occs] == [(OccurrenceStatus.SENT, at(16, 8))]
    after = await todos.get(uow, ACTOR, view.id)
    assert after.pending_occurrence_id is None
    assert after.final_occurrence_id == mine.occurrence.id


# --- 4. checking off the last one finishes the to-do -------------------------------------


@pytest.mark.parametrize("how", ["early", "reminder", "complete"])
async def test_checking_off_the_last_reminder_finishes_the_to_do(
    uow: Uow, clock: FixedClock, how: CheckOffPath
) -> None:
    tid, occ_id, checked = await _check_off_last(uow, clock, how)

    assert checked.undo.finished is True
    assert checked.undo.followup_id is None
    assert checked.undo.occurrence_id == occ_id
    view = await todos.get(uow, ACTOR, tid)
    assert view.status == TodoStatus.DONE
    assert (view.completed_at, view.completed_by) == (clock.now(), OWNER)
    assert view.pending_occurrence_id is None
    assert view.reminder is None
    assert [o.status for o in await _occurrences(uow, tid)] == [OccurrenceStatus.DONE]

    again = await todos.create_once(uow, ACTOR, title=TITLE)
    assert again.value.status == TodoStatus.OPEN


async def test_complete_after_the_last_reminder_failed_finishes_the_to_do(
    uow: Uow, clock: FixedClock
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"], end=nov(16)))
    clock.set(at(16, 8))
    [reminder] = _mine(await occurrences.claim_due(uow, clock.now()), view.id)
    await occurrences.mark_failed(uow, reminder.occurrence.id, occurrences.FAILURE_NO_CHANNEL)

    clock.set(at(16, 8, 10))
    checked = await todos.complete(uow, ACTOR, view.id)
    assert checked.value.undo.finished is True
    assert checked.value.undo.occurrence_id is None
    assert (await todos.get(uow, ACTOR, view.id)).status == TodoStatus.DONE

    undone = await undo.undo(uow, ACTOR, checked.value.undo)
    assert undone.value.todo.status == TodoStatus.OPEN


# --- 5. undo of the last check-off reopens the to-do -------------------------------------


@pytest.mark.parametrize("how", ["early", "reminder"])
async def test_undo_of_the_last_check_off_reopens_the_to_do(
    uow: Uow, clock: FixedClock, how: CheckOffPath
) -> None:
    tid, occ_id, checked = await _check_off_last(uow, clock, how)

    clock.set(at(16, 8, 3))
    undone = await undo.undo(uow, ACTOR, checked.undo)

    view = await todos.get(uow, ACTOR, tid)
    assert view.status == TodoStatus.OPEN
    assert view.completed_at is None
    assert view.completed_by is None
    [occ] = await _occurrences(uow, tid)
    assert occ.id == occ_id
    assert occ.completed_at is None
    assert undone.value.todo.status == TodoStatus.OPEN
    if how == "early":
        assert occ.status == OccurrenceStatus.PENDING
        assert view.pending_occurrence_id == occ_id
        assert view.reminder is None
        assert undone.changed_schedule is True
        assert undone.value.repost is None
    else:
        assert occ.status == OccurrenceStatus.SENT
        assert occ.message_id is None
        assert occ.channel_id is None
        assert view.reminder is not None
        assert view.reminder.id == occ_id
        assert view.final_occurrence_id == occ_id
        assert undone.changed_schedule is False
        assert undone.value.repost is not None
        assert undone.value.repost.occurrence.id == occ_id
        assert undone.value.repost.occurrence.message_id is None


# --- 6. undo refused once the name was taken again ---------------------------------------


@pytest.mark.parametrize("how", ["early", "reminder"])
async def test_undo_of_the_last_check_off_is_refused_once_the_title_is_taken(
    uow: Uow, clock: FixedClock, how: CheckOffPath
) -> None:
    tid, _, checked = await _check_off_last(uow, clock, how)
    await todos.create_once(uow, ACTOR, title=TITLE.capitalize())  # case-insensitive clash

    with pytest.raises(NameTaken):
        await undo.undo(uow, ACTOR, checked.undo)
    view = await todos.get(uow, ACTOR, tid)
    assert view.status == TodoStatus.DONE


# --- 7. an earlier end cancels the pending one past it -----------------------------------


async def test_edit_with_an_earlier_end_cancels_the_pending_one_past_it(
    uow: Uow, clock: FixedClock
) -> None:
    clock.set(at(16, 9))
    view = await _create(uow, DailyRule(times=["08:00"]))  # 08:00 has passed: the next is the 17th
    old_id = view.pending_occurrence_id
    assert old_id is not None
    assert view.next_due_at == at(17, 8)

    clock.set(at(16, 9, 5))
    edited = await todos.edit(
        uow,
        ACTOR,
        view.id,
        TodoPatch(rule=DailyRule(times=["10:00"], end=nov(16))),
    )
    new_id = edited.value.pending_occurrence_id
    assert new_id is not None
    assert new_id != old_id
    assert edited.value.next_due_at == at(16, 10)
    assert edited.value.final_occurrence_id == new_id
    assert edited.value.ends_on == nov(16)
    statuses = {o.id: o.status for o in await _occurrences(uow, view.id)}
    assert statuses == {old_id: OccurrenceStatus.CANCELLED, new_id: OccurrenceStatus.PENDING}


# --- 8. edit leaving nothing after the end (D75) -----------------------------------------


async def test_edit_leaving_nothing_after_is_allowed_while_a_reminder_is_up(
    uow: Uow, clock: FixedClock
) -> None:
    clock.set(at(16, 7))
    view = await _create(uow, DailyRule(times=["08:00"]))
    clock.set(at(16, 8))
    [reminder] = _mine(await occurrences.claim_due(uow, clock.now()), view.id)
    sent_id = reminder.occurrence.id

    clock.set(at(16, 8, 5))
    edited = await todos.edit(
        uow,
        ACTOR,
        view.id,
        TodoPatch(rule=DailyRule(times=["08:00"], end=nov(16))),
    )
    assert edited.value.pending_occurrence_id is None
    assert edited.value.next_due_at is None
    assert edited.value.reminder is not None
    assert edited.value.reminder.id == sent_id
    assert edited.value.final_occurrence_id == sent_id
    assert edited.value.ends_on == nov(16)
    statuses = [o.status for o in await _occurrences(uow, view.id)]
    assert statuses == [OccurrenceStatus.SENT, OccurrenceStatus.CANCELLED]


async def test_edit_leaving_nothing_after_is_refused_without_a_reminder_up(
    uow: Uow, clock: FixedClock
) -> None:
    clock.set(at(16, 7))
    view = await _create(uow, DailyRule(times=["08:00"]))
    clock.set(at(16, 8))
    [reminder] = _mine(await occurrences.claim_due(uow, clock.now()), view.id)
    clock.set(at(16, 8, 2))
    await occurrences.complete_occurrence(uow, ACTOR, reminder.occurrence.id)  # nothing is up now
    before = await todos.get(uow, ACTOR, view.id)

    clock.set(at(16, 8, 5))
    message = f"No reminder of **{TITLE}** falls between 16-11-2026 and 16-11-2026."
    with pytest.raises(InvalidRule, match=re.escape(message)):
        await todos.edit(
            uow,
            ACTOR,
            view.id,
            TodoPatch(rule=DailyRule(times=["08:00"], end=nov(16))),
        )
    after = await todos.get(uow, ACTOR, view.id)
    assert after.rule == before.rule
    assert after.ends_on is None
    assert after.pending_occurrence_id == before.pending_occurrence_id
    assert after.pending_occurrence_id is not None


# --- 9. removing start or end via edit ---------------------------------------------------


async def test_removing_the_start_makes_the_series_run_from_now(
    uow: Uow, clock: FixedClock
) -> None:
    base = DailyRule(times=["08:00"], start=nov(20))
    view = await _create(uow, base)
    assert view.next_due_at == at(20, 8)

    edited = await todos.edit(
        uow,
        ACTOR,
        view.id,
        TodoPatch(rule=base.model_copy(update={"start": None})),
    )
    assert edited.value.rule == DailyRule(times=["08:00"])
    assert edited.value.next_due_at == at(16, 8)
    assert edited.value.final_occurrence_id is None


async def test_removing_the_end_makes_the_series_repeat_forever_again(
    uow: Uow, clock: FixedClock
) -> None:
    base = DailyRule(times=["08:00"], end=nov(17))
    view = await _create(uow, base)

    edited = await todos.edit(
        uow,
        ACTOR,
        view.id,
        TodoPatch(rule=base.model_copy(update={"end": None})),
    )
    assert edited.value.pending_occurrence_id is not None
    assert edited.value.ends_on is None
    assert edited.value.final_occurrence_id is None

    clock.set(at(16, 8))
    await occurrences.claim_due(uow, clock.now())
    clock.set(at(17, 8))
    await occurrences.claim_due(uow, clock.now())  # the 17th is past the old end
    after = await todos.get(uow, ACTOR, view.id)
    assert after.next_due_at == at(18, 8)
    assert after.final_occurrence_id is None


# --- 10. final_occurrence_id ------------------------------------------------------------

FINAL_CASES = [
    pytest.param(None, False, id="no end"),
    pytest.param(nov(16), True, id="pending is the last"),
    pytest.param(nov(17), False, id="pending is not the last"),
]


@pytest.mark.parametrize(("end", "is_last"), FINAL_CASES)
async def test_final_occurrence_is_the_pending_one_only_when_nothing_follows(
    uow: Uow, end: date | None, is_last: bool
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"], end=end))
    assert view.pending_occurrence_id is not None
    assert view.ends_on == end
    expected = view.pending_occurrence_id if is_last else None
    assert view.final_occurrence_id == expected
