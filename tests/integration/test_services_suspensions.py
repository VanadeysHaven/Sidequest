"""Service-level tests for suspending a repeating to-do between dates (D81-D89): the three date
forms, the preview and its cap, the refusals, reminders that are up or checked off early, undo,
the scheduler and the stored rule."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from sidequest.core.enums import OccurrenceStatus, Weekday
from sidequest.core.errors import (
    Forbidden,
    InvalidOperation,
    InvalidRule,
    LimitExceeded,
    SidequestError,
)
from sidequest.core.recurrence import DailyRule, RecurrenceRule, WeeklyRule
from sidequest.db.models import Occurrence, Todo
from sidequest.services import lists, occurrences, settings, suspensions, todos, undo
from sidequest.services.actor import Actor
from sidequest.services.dto import (
    DueReminder,
    SuspensionChange,
    SuspensionPreview,
    SuspensionView,
    TodoView,
)
from sidequest.services.uow import Uow
from tests.support.clock import FixedClock

GUILD = 100
OWNER = 1
OTHER = 2
MANAGER = 9
CHANNEL = 555
TITLE = "stretch"
NOW = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)  # a Monday

OVERLAP = (
    "That overlaps the suspension from 20-11-2026 to 22-11-2026. "
    "Cancel that one first, or pick other dates."
)
NO_DATES = "Give `start`, `end` or both."
IN_PAST = "A suspension can't start before today."
END_BEFORE = "The end date can't be before the start date."
TOO_FAR = "A suspension can end at most a year ahead."
SKIPS_ALL = (
    "That would skip every remaining reminder. Change the end date or delete the to-do instead."
)
ONLY_REPEATING = "Only repeating to-dos can be suspended."
GONE_PREFIX = "That suspension isn't there any more."
LIMIT = "A to-do can have at most 10 current or upcoming suspensions."
NOTHING_TO_SKIP = f"No reminder of **{TITLE}** falls between 17-11-2026 and 20-11-2026."
NOTHING_ON_16TH = f"No reminder of **{TITLE}** falls between 16-11-2026 and 16-11-2026."

OPS = ["preview", "suspend"]
"""Every refusal applies to both `preview` and `suspend` (D85)."""

# 16 Nov 2026 + 367 days: one day more than a year ahead.
TOO_FAR_END = date(2027, 11, 18)


def member(user_id: int, guild_id: int | None, manage: bool = False) -> Actor:
    return Actor(user_id=user_id, guild_id=guild_id, can_manage_guild=manage, origin="discord")


ACTOR = member(OWNER, GUILD)
OTHER_ACTOR = member(OTHER, GUILD)
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


async def _daily_with_gap(uow: Uow) -> int:
    """A daily 08:00 to-do with one suspension, 20-22 Nov, already in place."""
    view = await _create(uow, DailyRule(times=["08:00"]))
    await suspensions.suspend(uow, ACTOR, view.id, nov(20), nov(22))
    return view.id


async def _run(
    op: str,
    uow: Uow,
    actor: Actor,
    todo_id: int,
    start: date | None,
    end: date | None,
) -> object:
    if op == "preview":
        return await suspensions.preview(uow, actor, todo_id, start, end)
    return (await suspensions.suspend(uow, actor, todo_id, start, end)).value


# --- the three date forms (D82) -----------------------------------------------------------

FORMS = [
    pytest.param(
        nov(17), None, (nov(17), nov(17)), (at(17, 8),), at(16, 8), False, id="only start"
    ),
    pytest.param(
        nov(16), None, (nov(16), nov(16)), (at(16, 8),), at(17, 8), True, id="start is today"
    ),
    pytest.param(
        None,
        nov(17),
        (nov(16), nov(17)),
        (at(16, 8), at(17, 8)),
        at(18, 8),
        True,
        id="only end",
    ),
    pytest.param(
        nov(17),
        nov(18),
        (nov(17), nov(18)),
        (at(17, 8), at(18, 8)),
        at(16, 8),
        False,
        id="both",
    ),
]


@pytest.mark.parametrize(
    ("start", "end", "rng", "skipped", "next_due", "running"),
    FORMS,
)
async def test_the_three_date_forms_skip_their_reminders(
    uow: Uow,
    start: date | None,
    end: date | None,
    rng: tuple[date, date],
    skipped: tuple[datetime, ...],
    next_due: datetime,
    running: bool,
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))
    before = view.pending_occurrence_id

    previewed = await suspensions.preview(uow, ACTOR, view.id, start, end)
    assert previewed.title == TITLE
    assert previewed.suspension == SuspensionView(start=rng[0], end=rng[1], running=running)
    assert previewed.skipped == skipped
    assert previewed.total == len(skipped)
    untouched = await todos.get(uow, ACTOR, view.id)  # a preview writes nothing
    assert untouched.pending_occurrence_id == before
    assert untouched.suspensions == ()

    out = await suspensions.suspend(uow, ACTOR, view.id, start, end)
    assert out.changed_schedule is True
    assert out.value.suspension == previewed.suspension
    assert out.value.todo.suspensions == (previewed.suspension,)
    assert out.value.todo.next_due_at == next_due


async def test_only_end_on_a_day_whose_morning_reminder_fired_keeps_that_reminder(
    uow: Uow, clock: FixedClock
) -> None:
    view = await _create(uow, DailyRule(times=["08:00", "20:00"]))
    clock.set(at(16, 8))
    [mine] = _mine(await occurrences.claim_due(uow, clock.now()), view.id)
    sent_id = mine.occurrence.id
    await occurrences.attach_message(uow, sent_id, CHANNEL, 999)

    clock.set(at(16, 9))
    previewed = await suspensions.preview(uow, ACTOR, view.id, None, nov(16))
    assert previewed.skipped == (at(16, 20),)  # the sent 08:00 is not among them
    assert previewed.total == 1
    assert previewed.suspension.running is True

    out = await suspensions.suspend(uow, ACTOR, view.id, None, nov(16))
    assert out.value.todo.reminder is not None
    assert out.value.todo.reminder.id == sent_id
    assert out.value.todo.next_due_at == at(17, 8)
    occ = await uow.session.get(Occurrence, sent_id, populate_existing=True)
    assert occ is not None
    assert occ.status == OccurrenceStatus.SENT
    assert occ.message_id == 999
    assert occ.channel_id == CHANNEL


async def test_preview_lists_every_skipped_reminder_oldest_first(uow: Uow) -> None:
    view = await _create(uow, DailyRule(times=["08:00", "12:00", "20:00"]))

    previewed = await suspensions.preview(uow, ACTOR, view.id, nov(16), nov(25))
    assert previewed.total == 30  # ten days, three times a day; the bot pages through them
    assert len(previewed.skipped) == 30
    assert previewed.skipped[:3] == (at(16, 8), at(16, 12), at(16, 20))
    assert previewed.skipped[-1] == at(25, 20)
    assert list(previewed.skipped) == sorted(previewed.skipped)


async def test_a_reminder_that_is_up_stays_sent_with_its_message(
    uow: Uow, clock: FixedClock
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))
    clock.set(at(16, 8))
    [mine] = _mine(await occurrences.claim_due(uow, clock.now()), view.id)
    sent_id = mine.occurrence.id
    await occurrences.attach_message(uow, sent_id, CHANNEL, 999)

    clock.set(at(16, 8, 5))
    out = await suspensions.suspend(uow, ACTOR, view.id, nov(17), nov(18))
    assert out.value.todo.reminder is not None
    assert out.value.todo.reminder.id == sent_id
    assert out.value.todo.next_due_at == at(19, 8)
    occ = await uow.session.get(Occurrence, sent_id, populate_existing=True)
    assert occ is not None
    assert occ.status == OccurrenceStatus.SENT
    assert occ.message_id == 999
    assert occ.channel_id == CHANNEL


# --- refusals (D85), for preview and suspend ----------------------------------------------

REFUSED = [
    pytest.param(None, None, InvalidOperation, NO_DATES, id="neither date"),
    pytest.param(nov(15), None, InvalidOperation, IN_PAST, id="start before today"),
    pytest.param(nov(20), nov(18), InvalidOperation, END_BEFORE, id="end before start"),
    pytest.param(None, TOO_FAR_END, InvalidOperation, TOO_FAR, id="end more than a year ahead"),
    pytest.param(nov(21), nov(21), InvalidRule, OVERLAP, id="overlaps the existing one"),
]


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize(("start", "end", "error", "message"), REFUSED)
async def test_a_bad_date_range_is_refused(
    uow: Uow,
    op: str,
    start: date | None,
    end: date | None,
    error: type[SidequestError],
    message: str,
) -> None:
    todo_id = await _daily_with_gap(uow)
    before = await todos.get(uow, ACTOR, todo_id)

    with pytest.raises(error) as caught:
        await _run(op, uow, ACTOR, todo_id, start, end)
    assert caught.value.message == message

    after = await todos.get(uow, ACTOR, todo_id)
    assert after.suspensions == before.suspensions
    assert after.pending_occurrence_id == before.pending_occurrence_id


@pytest.mark.parametrize("op", OPS)
async def test_a_range_ending_a_year_ahead_is_still_allowed(uow: Uow, op: str) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))
    end = nov(16) + timedelta(days=366)
    result = await _run(op, uow, ACTOR, view.id, None, end)
    if op == "preview":
        assert isinstance(result, SuspensionPreview)
        assert result.suspension.end == end
    else:
        assert isinstance(result, SuspensionChange)
        assert result.suspension.end == end


@pytest.mark.parametrize("op", OPS)
async def test_a_range_with_nothing_to_skip_is_refused(uow: Uow, op: str) -> None:
    await _set_channel(uow)
    view = (
        await todos.create_recurring(
            uow,
            ACTOR,
            title=TITLE,
            rule=WeeklyRule(weekdays=[Weekday.MON], times=["08:00"]),
        )
    ).value

    with pytest.raises(InvalidOperation) as caught:
        await _run(op, uow, ACTOR, view.id, nov(17), nov(20))
    assert caught.value.message == NOTHING_TO_SKIP


@pytest.mark.parametrize("op", OPS)
async def test_a_suspension_that_would_skip_every_remaining_reminder_is_refused(
    uow: Uow, op: str
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"], end=nov(17)))

    with pytest.raises(InvalidOperation) as caught:
        await _run(op, uow, ACTOR, view.id, nov(16), nov(17))
    assert caught.value.message == SKIPS_ALL


async def test_a_suspension_that_would_skip_every_remaining_one_is_allowed_while_one_is_up(
    uow: Uow, clock: FixedClock
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"], end=nov(17)))
    clock.set(at(16, 8))
    [mine] = _mine(await occurrences.claim_due(uow, clock.now()), view.id)
    sent_id = mine.occurrence.id

    clock.set(at(16, 8, 5))
    previewed = await suspensions.preview(uow, ACTOR, view.id, nov(17), nov(17))
    assert previewed.skipped == (at(17, 8),)
    out = await suspensions.suspend(uow, ACTOR, view.id, nov(17), nov(17))
    assert out.value.todo.pending_occurrence_id is None
    assert out.value.todo.next_due_at is None
    assert out.value.todo.reminder is not None
    assert out.value.todo.reminder.id == sent_id
    assert out.value.todo.final_occurrence_id == sent_id  # the one that is up is the last now


@pytest.mark.parametrize("op", OPS)
async def test_a_one_time_to_do_cannot_be_suspended(uow: Uow, op: str) -> None:
    view = (await todos.create_once(uow, ACTOR, title=TITLE)).value

    with pytest.raises(InvalidOperation) as caught:
        await _run(op, uow, ACTOR, view.id, nov(17), nov(17))
    assert caught.value.message == ONLY_REPEATING


@pytest.mark.parametrize("op", OPS)
async def test_a_member_without_edit_rights_is_forbidden(uow: Uow, op: str) -> None:
    await _set_channel(uow)
    owned = await lists.create(uow, ACTOR, "Work")
    view = (
        await todos.create_recurring(
            uow,
            ACTOR,
            list_id=owned.id,
            title=TITLE,
            rule=DailyRule(times=["08:00"]),
        )
    ).value

    with pytest.raises(Forbidden):
        await _run(op, uow, OTHER_ACTOR, view.id, nov(17), nov(17))


async def test_suspending_more_than_ten_is_refused(uow: Uow) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))
    for day in range(16, 26):  # ten single days, the 16th to the 25th
        await suspensions.suspend(uow, ACTOR, view.id, nov(day), None)

    with pytest.raises(LimitExceeded) as caught:
        await suspensions.preview(uow, ACTOR, view.id, nov(26), None)
    assert caught.value.message == LIMIT
    with pytest.raises(LimitExceeded) as caught:
        await suspensions.suspend(uow, ACTOR, view.id, nov(26), None)
    assert caught.value.message == LIMIT


async def test_touching_suspensions_are_allowed(uow: Uow) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))
    await suspensions.suspend(uow, ACTOR, view.id, nov(20), nov(22))
    out = await suspensions.suspend(uow, ACTOR, view.id, nov(23), nov(24))

    assert out.value.todo.suspensions == (
        SuspensionView(start=nov(20), end=nov(22), running=False),
        SuspensionView(start=nov(23), end=nov(24), running=False),
    )


# --- unsuspend ----------------------------------------------------------------------------


async def test_unsuspend_makes_the_next_reminder_earlier_again(uow: Uow) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))
    suspended = await suspensions.suspend(uow, ACTOR, view.id, nov(16), nov(18))
    assert suspended.value.todo.next_due_at == at(19, 8)

    out = await suspensions.unsuspend(uow, ACTOR, view.id, nov(16))
    assert out.changed_schedule is True
    assert out.value.suspension == SuspensionView(start=nov(16), end=nov(18), running=True)
    assert out.value.todo.suspensions == ()
    assert out.value.todo.next_due_at == at(16, 8)


async def test_unsuspend_of_a_start_without_a_suspension_is_refused(uow: Uow) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))

    with pytest.raises(InvalidOperation) as caught:
        await suspensions.unsuspend(uow, ACTOR, view.id, nov(20))
    assert caught.value.message.startswith(GONE_PREFIX)


# --- reminders checked off early, and undo ------------------------------------------------


async def test_a_suspension_does_not_bring_back_a_reminder_checked_off_early(
    uow: Uow, clock: FixedClock
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))
    early_id = view.pending_occurrence_id
    assert early_id is not None
    clock.set(at(16, 7, 30))
    await occurrences.complete_occurrence(uow, ACTOR, early_id)

    clock.set(at(16, 7, 31))
    await suspensions.suspend(uow, ACTOR, view.id, nov(17), nov(17))

    occs = await _occurrences(uow, view.id)
    assert [(o.due_at, o.status) for o in occs] == [
        (at(16, 8), OccurrenceStatus.DONE),
        (at(17, 8), OccurrenceStatus.CANCELLED),
        (at(18, 8), OccurrenceStatus.PENDING),
    ]
    after = await todos.get(uow, ACTOR, view.id)
    assert after.pending_occurrence_id != early_id
    assert after.next_due_at == at(18, 8)
    with pytest.raises(InvalidOperation) as caught:
        await suspensions.preview(uow, ACTOR, view.id, nov(16), nov(16))
    assert (
        caught.value.message
        == f"No reminder of **{TITLE}** falls between 16-11-2026 and 16-11-2026."
    )


async def test_undo_of_a_check_off_is_refused_once_a_suspension_cancelled_its_follow_up(
    uow: Uow, clock: FixedClock
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))
    assert view.pending_occurrence_id is not None
    clock.set(at(16, 7, 30))
    checked = await occurrences.complete_occurrence(uow, ACTOR, view.pending_occurrence_id)

    clock.set(at(16, 7, 31))
    await suspensions.suspend(uow, ACTOR, view.id, nov(17), nov(17))

    clock.set(at(16, 7, 32))
    with pytest.raises(InvalidOperation) as caught:
        await undo.undo(uow, ACTOR, checked.value.undo)
    assert caught.value.message == (
        f"**{TITLE}** was changed after it was checked off, so it can't be undone."
    )


# --- views --------------------------------------------------------------------------------


async def test_the_view_shows_a_running_suspension_and_when_it_ends(
    uow: Uow, clock: FixedClock
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))
    await suspensions.suspend(uow, ACTOR, view.id, nov(18), nov(20))

    upcoming = await todos.get(uow, ACTOR, view.id)
    assert upcoming.suspensions == (SuspensionView(start=nov(18), end=nov(20), running=False),)
    assert upcoming.suspended_until is None

    clock.set(at(18, 7))
    running = await todos.get(uow, ACTOR, view.id)
    assert running.suspensions == (SuspensionView(start=nov(18), end=nov(20), running=True),)
    assert running.suspended_until == nov(20)

    clock.set(at(21, 7))
    over = await todos.get(uow, ACTOR, view.id)
    assert over.suspensions == ()
    assert over.suspended_until is None


# --- the scheduler ------------------------------------------------------------------------


async def test_the_scheduler_posts_nothing_on_suspended_days_and_the_first_day_after(
    uow: Uow, clock: FixedClock
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))
    clock.set(at(16, 7))
    await suspensions.suspend(uow, ACTOR, view.id, nov(17), nov(18))

    clock.set(at(16, 8))
    [first] = _mine(await occurrences.claim_due(uow, clock.now()), view.id)
    assert first.occurrence.due_at == at(16, 8)

    for day in (17, 18):
        clock.set(at(day, 8))
        assert _mine(await occurrences.claim_due(uow, clock.now()), view.id) == []

    clock.set(at(19, 8))
    [after] = _mine(await occurrences.claim_due(uow, clock.now()), view.id)
    assert after.occurrence.due_at == at(19, 8)


# --- the stored rule ----------------------------------------------------------------------


async def test_a_finished_suspension_is_dropped_from_the_stored_rule_when_another_is_added(
    uow: Uow, clock: FixedClock
) -> None:
    view = await _create(uow, DailyRule(times=["08:00"]))
    clock.set(at(16, 7))
    await suspensions.suspend(uow, ACTOR, view.id, nov(16), nov(16))
    clock.set(at(16, 8))
    await occurrences.claim_due(uow, clock.now())

    clock.set(at(17, 7))
    out = await suspensions.suspend(uow, ACTOR, view.id, nov(20), nov(20))
    assert out.value.todo.suspensions == (
        SuspensionView(start=nov(20), end=nov(20), running=False),
    )

    todo = await uow.session.get(Todo, view.id, populate_existing=True)
    assert todo is not None
    assert todo.recurrence is not None
    assert todo.recurrence["suspended"] == [{"start": "2026-11-20", "end": "2026-11-20"}]
