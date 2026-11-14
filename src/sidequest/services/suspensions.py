"""Suspending a repeating to-do between two dates (D81–D89).

A suspension lives in the rule JSON (D88): no reminder fires on its days. Reminders that
already went out, including one that is up, are not touched (D83). Suspend and unsuspend
replace the pending occurrence like an edit does (D89).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sidequest.core import recurrence
from sidequest.core.enums import OccurrenceStatus, TodoKind
from sidequest.core.errors import InvalidOperation, LimitExceeded
from sidequest.core.limits import (
    START_AHEAD_MAX_DAYS,
    SUSPENSIONS_MAX,
)
from sidequest.core.recurrence import DateRange, RecurrenceRule
from sidequest.core.text import bold, plain_date
from sidequest.core.timeparse import resolve_local
from sidequest.core.tz import get_zone
from sidequest.db.models import Todo
from sidequest.services import _common as c
from sidequest.services import _series
from sidequest.services.actor import Actor
from sidequest.services.dto import SuspensionChange, SuspensionPreview
from sidequest.services.effects import Outcome
from sidequest.services.uow import Uow

ONLY_REPEATING = "Only repeating to-dos can be suspended."
NO_DATES = "Give `start`, `end` or both."
IN_PAST = "A suspension can't start before today."
TOO_FAR = "A suspension can end at most a year ahead."
SKIPS_ALL = (
    "That would skip every remaining reminder. Change the end date or delete the to-do instead."
)
GONE = "That suspension isn't there any more. Pick one from the list that appears while you type."


async def _load(uow: Uow, actor: Actor, todo_id: int, *, lock: bool) -> Todo:
    """D89: the same rights as editing; repeating to-dos only (D81)."""
    todo = await c.load_todo(uow, actor, todo_id, lock=lock)
    c.require_open(todo)
    c.require_edit(actor, todo)
    if todo.kind != TodoKind.RECURRING:
        raise InvalidOperation(ONLY_REPEATING)
    return todo


def _date_range(start: date | None, end: date | None, today: date) -> DateRange:
    """D82: only `start` → that day; only `end` → today until `end`; both → that range."""
    if start is None and end is None:
        raise InvalidOperation(NO_DATES)
    first = start if start is not None else today
    last = end if end is not None else first
    if first < today:
        raise InvalidOperation(IN_PAST)
    if last < first:
        raise InvalidOperation(recurrence.END_BEFORE_START)
    if last > today + timedelta(days=START_AHEAD_MAX_DAYS):
        raise InvalidOperation(TOO_FAR)
    return DateRange(start=first, end=last)


def _day_start(d: date, zone: ZoneInfo) -> datetime:
    return resolve_local(d, time(0), zone)


@dataclass(frozen=True)
class _Plan:
    """A checked suspension (D82, D85) and the reminders it skips (D83, D84)."""

    rule: RecurrenceRule
    """The rule with the suspension added."""
    rng: DateRange
    skipped: list[datetime]
    base: datetime
    """See `_series.schedule_base`."""


async def _plan(uow: Uow, todo: Todo, start: date | None, end: date | None) -> _Plan:
    now = uow.clock.now()
    zone = get_zone(todo.timezone)
    today = now.astimezone(zone).date()
    rng = _date_range(start, end, today)
    current = recurrence.pruned(c.rule_of(todo), today)
    rule = recurrence.with_suspension(current, rng)  # refuses an overlap
    if len(rule.suspended) > SUSPENSIONS_MAX:
        raise LimitExceeded(
            f"A to-do can have at most {SUSPENSIONS_MAX} current or upcoming suspensions."
        )
    base = await _series.schedule_base(uow, todo.id, now)
    skipped = recurrence.occurrences_between(
        current,
        zone,
        max(base + timedelta(microseconds=1), _day_start(rng.start, zone)),
        _day_start(rng.end + timedelta(days=1), zone),
    )
    if not skipped:
        raise InvalidOperation(
            f"No reminder of {bold(todo.title)} falls between {plain_date(rng.start)} "
            f"and {plain_date(rng.end)}."
        )
    if _series.is_over(rule, zone, base):
        occs = (await c.open_occurrences(uow, [todo.id]))[todo.id]
        if c.find(occs, OccurrenceStatus.SENT) is None:
            raise InvalidOperation(SKIPS_ALL)  # with one up, that one becomes the last (D75)
    return _Plan(rule, rng, skipped, base)


async def preview(
    uow: Uow, actor: Actor, todo_id: int, start: date | None, end: date | None
) -> SuspensionPreview:
    """What a suspension would skip (D84), with every refusal of `suspend` (D85). No write."""
    todo = await _load(uow, actor, todo_id, lock=False)
    plan = await _plan(uow, todo, start, end)
    today = uow.clock.now().astimezone(get_zone(todo.timezone)).date()
    return SuspensionPreview(
        title=todo.title,
        suspension=_series.suspension_view(plan.rng, today),
        skipped=tuple(plan.skipped),
    )


async def _reschedule(
    uow: Uow, actor: Actor, todo: Todo, rule: RecurrenceRule, base: datetime, rng: DateRange
) -> Outcome[SuspensionChange]:
    """Store the rule and replace the pending occurrence (D89); a reminder that is up stays
    (D83)."""
    todo.recurrence = recurrence.to_json(rule)
    await c.cancel_open(uow, todo, include_sent=False)
    c.add_next_pending(uow, todo, after=base)
    view = await c.view_of(uow, actor, todo)
    today = uow.clock.now().astimezone(get_zone(todo.timezone)).date()
    await uow.session.commit()
    return Outcome(
        value=SuspensionChange(todo=view, suspension=_series.suspension_view(rng, today)),
        changed_schedule=True,
    )


async def suspend(
    uow: Uow, actor: Actor, todo_id: int, start: date | None, end: date | None
) -> Outcome[SuspensionChange]:
    """Suspend between `start` and `end` (D81, D82), checked again as in `preview`."""
    todo = await _load(uow, actor, todo_id, lock=True)
    plan = await _plan(uow, todo, start, end)
    return await _reschedule(uow, actor, todo, plan.rule, plan.base, plan.rng)


async def unsuspend(uow: Uow, actor: Actor, todo_id: int, start: date) -> Outcome[SuspensionChange]:
    """Cancel the current or upcoming suspension that starts on `start` (D86). Reminders it
    already skipped don't come back; the next one is the first still to come."""
    todo = await _load(uow, actor, todo_id, lock=True)
    now = uow.clock.now()
    today = now.astimezone(get_zone(todo.timezone)).date()
    rule, removed = recurrence.without_suspension(recurrence.pruned(c.rule_of(todo), today), start)
    if removed is None:
        raise InvalidOperation(GONE)
    base = await _series.schedule_base(uow, todo.id, now)
    return await _reschedule(uow, actor, todo, rule, base, removed)
