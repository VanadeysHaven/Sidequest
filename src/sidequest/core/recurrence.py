"""Repeat rules: validation, JSON (JSONB) shape, next occurrence, and descriptions.

Pure and hand-written (D15). All rule times are wall-clock times in the to-do's timezone,
so they stay at the same local time across DST (BRIEF §4.3). JSON shape (S2):

    {"type": "daily",       "times": ["08:00", "20:00"]}
    {"type": "weekly",      "weekdays": ["mon", "thu"], "times": ["12:00"]}
    {"type": "weekly",      "weekdays": ["tue"], "times": ["07:00"],
                            "every": 2, "start": "2026-11-03"}         # S9, see below
    {"type": "monthly",    "week": 1, "weekday": "sun", "times": ["12:00"]}  # week -1 = last
    {"type": "monthly_day", "day": 15, "times": ["09:00"]}                    # day -1 = last

Weekly rules may repeat every 2–52 weeks (`every`, left out when 1; S9, D54–D59). Every rule
may have a `start` and an `end` date (inclusive, in the to-do's zone, left out when unset;
D73/D74): nothing fires before `start` or after `end`. With `every` ≥ 2 the week
(Monday–Sunday) of `start` is the first on-week. A rule with `every` ≥ 2 must be anchored
(have a `start`, see `anchored`) before it is stored or scheduled. A rule with an `end`
runs out: `next_occurrence` returns None after its last occurrence (D76).

Every rule may also be suspended between dates (D81, D88): `"suspended": [{"start":
"2026-11-16", "end": "2026-11-22"}]`, inclusive, sorted, never overlapping, left out when
empty. Nothing fires on a suspended day. Finished ones are dropped when the rule is written
(`pruned`, via `anchored`).
"""

import calendar
import itertools
import re
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from sidequest.core.enums import Weekday
from sidequest.core.errors import InvalidRule, SidequestError
from sidequest.core.limits import START_AHEAD_MAX_DAYS, TIMES_PER_RULE_MAX, WEEK_INTERVAL_MAX
from sidequest.core.text import plain_date
from sidequest.core.timeparse import parse_time, resolve_local

# Every valid rule fires within 52 weeks of the later of the search start and its `start`
# date (weekly rules repeat at most every 52 weeks), plus at most one skipped by a
# suspension (they end at most a year ahead, D82); this only guards against bugs.
MAX_SEARCH_DAYS = 800

_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# --- field types -------------------------------------------------------------------------


def _to_time(value: Any) -> time:
    if isinstance(value, time):
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("times must be whole minutes without a timezone")
        return value
    if isinstance(value, str):
        try:
            return parse_time(value)
        except SidequestError as e:
            raise ValueError(e.message) from None
    raise ValueError("times must be HH:MM strings")


def _hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _check_times(times: tuple[time, ...]) -> tuple[time, ...]:
    unique = tuple(sorted(set(times)))
    if not unique:
        raise ValueError("a rule needs at least one time")
    if len(unique) > TIMES_PER_RULE_MAX:
        raise ValueError(f"a rule has at most {TIMES_PER_RULE_MAX} times")
    return unique


def _check_weekdays(days: tuple[Weekday, ...]) -> tuple[Weekday, ...]:
    unique = tuple(sorted(set(days), key=lambda w: w.index))
    if not unique:
        raise ValueError("a weekly rule needs at least one weekday")
    return unique


def _check_week(week: int) -> int:
    if week not in (1, 2, 3, 4, -1):
        raise ValueError("week must be 1–4 or -1 (last)")
    return week


def _check_day(day: int) -> int:
    if not (1 <= day <= 31 or day == -1):
        raise ValueError("day must be 1–31 or -1 (last day)")
    return day


def _check_every(every: int) -> int:
    if not 1 <= every <= WEEK_INTERVAL_MAX:
        raise ValueError(f"every must be 1–{WEEK_INTERVAL_MAX} weeks")
    return every


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        raise ValueError("must be a date without a time")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _ISO_DATE_RE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError("must be a YYYY-MM-DD date")


RuleTime = Annotated[
    time, BeforeValidator(_to_time), PlainSerializer(_hhmm, return_type=str, when_used="json")
]
Times = Annotated[tuple[RuleTime, ...], AfterValidator(_check_times)]
Weekdays = Annotated[tuple[Weekday, ...], AfterValidator(_check_weekdays)]
Week = Annotated[int, Field(strict=True), AfterValidator(_check_week)]
MonthDay = Annotated[int, Field(strict=True), AfterValidator(_check_day)]
WeekInterval = Annotated[int, Field(strict=True), AfterValidator(_check_every)]
RuleDate = Annotated[date, BeforeValidator(_to_date)]

END_BEFORE_START = "The end date can't be before the start date."


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as e:
            raise InvalidRule(_error_message(e)) from None


class DateRange(_Frozen):
    """Two dates, both inclusive, in the to-do's zone: a suspension (D81, D88)."""

    start: RuleDate
    end: RuleDate

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end < self.start:
            raise ValueError(END_BEFORE_START)
        return self

    def overlaps(self, other: "DateRange") -> bool:
        """Sharing a day; touching ranges (one ends the day before the other starts) don't."""
        return self.start <= other.end and other.start <= self.end

    def __contains__(self, d: date) -> bool:
        return self.start <= d <= self.end


def _check_suspended(ranges: tuple[DateRange, ...]) -> tuple[DateRange, ...]:
    ordered = tuple(sorted(ranges, key=lambda r: r.start))
    for before, after in itertools.pairwise(ordered):
        if before.overlaps(after):
            raise ValueError("suspensions overlap")
    return ordered


Suspended = Annotated[tuple[DateRange, ...], AfterValidator(_check_suspended)]


# --- rules -------------------------------------------------------------------------------


class _Rule(_Frozen):
    """Every rule may have a `start` and an `end` date, both inclusive (D73/D74), and
    suspensions: date ranges without reminders, sorted, never overlapping (D81, D88)."""

    start: RuleDate | None = None
    end: RuleDate | None = None
    suspended: Suspended = ()

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(END_BEFORE_START)
        return self


class DailyRule(_Rule):
    type: Literal["daily"] = "daily"
    times: Times


class WeeklyRule(_Rule):
    """Given weekdays, every `every` weeks (Monday–Sunday weeks), never before `start`.

    `every` ≥ 2 without `start` is a valid model but "not anchored yet": run it through
    `anchored` before storing or scheduling it.
    """

    type: Literal["weekly"] = "weekly"
    weekdays: Weekdays
    times: Times
    every: WeekInterval = 1

    @property
    def is_anchored(self) -> bool:
        return self.every == 1 or self.start is not None


class MonthlyRule(_Rule):
    """The n-th (1–4) or last (-1) given weekday of the month."""

    type: Literal["monthly"] = "monthly"
    week: Week
    weekday: Weekday
    times: Times


class MonthlyDayRule(_Rule):
    """A day of the month (1–31) or its last day (-1). Missing days fall back to the last
    day of that month (D21)."""

    type: Literal["monthly_day"] = "monthly_day"
    day: MonthDay
    times: Times


RecurrenceRule = Annotated[
    DailyRule | WeeklyRule | MonthlyRule | MonthlyDayRule, Field(discriminator="type")
]
_adapter: TypeAdapter[RecurrenceRule] = TypeAdapter(RecurrenceRule)


def _error_message(e: ValidationError) -> str:
    first = e.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    msg = first["msg"].removeprefix("Value error, ")
    return f"Invalid repeat rule ({where}): {msg}" if where else msg  # model checks: as is


def from_json(data: Any) -> RecurrenceRule:
    """Validate a JSONB payload into a rule. Raises `InvalidRule`."""
    try:
        return _adapter.validate_python(data)
    except ValidationError as e:
        raise InvalidRule(_error_message(e)) from None


def _require_anchored(rule: RecurrenceRule) -> None:
    if isinstance(rule, WeeklyRule) and not rule.is_anchored:
        raise ValueError("weekly rule with every >= 2 has no start; call anchored() first")


def to_json(rule: RecurrenceRule) -> dict[str, Any]:
    """The JSONB payload for a rule (times as "HH:MM"). `start` and `end` are left out when
    unset and a weekly `every` when it is 1, so older rows keep exactly their shape (D59)."""
    _require_anchored(rule)
    exclude: set[str] = set()
    if isinstance(rule, WeeklyRule) and rule.every == 1:
        exclude.add("every")
    if rule.start is None:
        exclude.add("start")
    if rule.end is None:
        exclude.add("end")
    if not rule.suspended:
        exclude.add("suspended")
    return rule.model_dump(mode="json", exclude=exclude)


def anchored(rule: RecurrenceRule, tz: ZoneInfo, now: datetime) -> RecurrenceRule:
    """The rule ready to store (D56, D75). Call it when a rule is created or changed.

    A `start` must be at most `START_AHEAD_MAX_DAYS` after today in `tz` (every rule type).
    A weekly rule with `every` ≥ 2 and no `start` gets the local date of its next
    occurrence as a plain weekly rule, so its first reminder is the soonest possible (today
    when nothing is left before its `end`). Whether anything is left before `end` is the
    caller's check (an edit may allow nothing, D75).
    """
    if now.tzinfo is None:
        raise ValueError("naive datetime; use timezone-aware UTC")
    today = now.astimezone(tz).date()
    rule = pruned(rule, today)
    if rule.start is not None:
        if rule.start > today + timedelta(days=START_AHEAD_MAX_DAYS):
            raise InvalidRule("`start` can be at most a year ahead.")
        return rule
    if not isinstance(rule, WeeklyRule) or rule.every == 1:
        return rule
    first = next_occurrence(rule.model_copy(update={"every": 1}), tz, now)
    return rule.model_copy(update={"start": first.astimezone(tz).date() if first else today})


# --- suspensions (D81–D88) ---------------------------------------------------------------


def pruned[R: RecurrenceRule](rule: R, today: date) -> R:
    """`rule` without the suspensions that are over (`end` before `today`, D88)."""
    current = tuple(r for r in rule.suspended if r.end >= today)
    if len(current) == len(rule.suspended):
        return rule
    return rule.model_copy(update={"suspended": current})


def with_suspension[R: RecurrenceRule](rule: R, rng: DateRange) -> R:
    """`rule` with one more suspension. `InvalidRule` when it overlaps one (D81, D85)."""
    for other in rule.suspended:
        if other.overlaps(rng):
            raise InvalidRule(
                f"That overlaps the suspension from {plain_date(other.start)} to "
                f"{plain_date(other.end)}. Cancel that one first, or pick other dates."
            )
    return type(rule)(**{**rule.model_dump(), "suspended": (*rule.suspended, rng)})


def without_suspension[R: RecurrenceRule](rule: R, start: date) -> tuple[R, DateRange | None]:
    """`rule` without the suspension starting on `start`, and that suspension (None, and
    the rule unchanged, when there is none)."""
    found = next((r for r in rule.suspended if r.start == start), None)
    if found is None:
        return rule, None
    kept = tuple(r for r in rule.suspended if r is not found)
    return rule.model_copy(update={"suspended": kept}), found


def suspended_until(rule: RecurrenceRule, today: date) -> date | None:
    """While a suspension runs (today included): its last day, following touching ones."""
    until: date | None = None
    for rng in rule.suspended:  # sorted by start
        if until is None:
            if today in rng:
                until = rng.end
        elif rng.start == until + timedelta(days=1):
            until = rng.end
    return until


# --- occurrences -------------------------------------------------------------------------


def _last_day(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _matches(rule: RecurrenceRule, d: date) -> bool:
    if (rule.start is not None and d < rule.start) or (rule.end is not None and d > rule.end):
        return False
    if any(d in rng for rng in rule.suspended):
        return False
    match rule:
        case DailyRule():
            return True
        case WeeklyRule():
            if Weekday.from_index(d.weekday()) not in rule.weekdays:
                return False
            if rule.start is None:
                return True
            weeks = (_monday(d) - _monday(rule.start)).days // 7
            return weeks % rule.every == 0
        case MonthlyRule():
            if d.weekday() != rule.weekday.index:
                return False
            if rule.week == -1:
                return d.day + 7 > _last_day(d)
            return (d.day - 1) // 7 + 1 == rule.week
        case MonthlyDayRule():
            last = _last_day(d)
            target = last if rule.day == -1 else min(rule.day, last)
            return d.day == target


def next_occurrence(rule: RecurrenceRule, tz: ZoneInfo, after: datetime) -> datetime | None:
    """The first occurrence strictly after `after`, as aware UTC. None: the series is over
    (nothing left on or before `end`, D76)."""
    if after.tzinfo is None:
        raise ValueError("naive datetime; use timezone-aware UTC")
    _require_anchored(rule)
    # Start a day early: cheap insurance against DST edge cases around local midnight.
    first_day = after.astimezone(tz).date() - timedelta(days=1)
    if rule.start is not None:
        first_day = max(first_day, rule.start)  # nothing fires before `start`
    for offset in range(MAX_SEARCH_DAYS):
        d = first_day + timedelta(days=offset)
        if rule.end is not None and d > rule.end:
            return None
        if not _matches(rule, d):
            continue
        # Resolving can reorder or merge times on a DST day (02:30 in a gap becomes 03:30),
        # so sort the resolved instants rather than trusting the wall-clock order.
        for at in sorted({resolve_local(d, t, tz) for t in rule.times}):
            if at > after:
                return at
    raise InvalidRule("This repeat rule has no upcoming occurrence.")


def occurrences_between(
    rule: RecurrenceRule, tz: ZoneInfo, start: datetime, end: datetime
) -> list[datetime]:
    """All occurrences with `start <= occurrence < end`, as aware UTC."""
    _require_anchored(rule)
    result: list[datetime] = []
    at = next_occurrence(rule, tz, start - timedelta(microseconds=1))
    while at is not None and at < end:
        result.append(at)
        at = next_occurrence(rule, tz, at)
    return result


# --- descriptions ------------------------------------------------------------------------

_WEEK_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _ordinal(n: int) -> str:
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def describe(rule: RecurrenceRule, tz: ZoneInfo, today: date | None = None) -> str:
    """Human description in 24h wall-clock time, e.g. "Every day at 08:00 (UTC)", with
    ", from DD-MM-YYYY" while `start` is after `today` (always when `today` is None) and
    ", until DD-MM-YYYY" (D80)."""
    text = _describe_pattern(rule, tz)
    if rule.start is not None and (today is None or rule.start > today):
        text += f", from {plain_date(rule.start)}"
    if rule.end is not None:
        text += f", until {plain_date(rule.end)}"
    return text


def _describe_pattern(rule: RecurrenceRule, tz: ZoneInfo) -> str:
    at = f"at {_join([_hhmm(t) for t in rule.times])} ({tz.key})"
    match rule:
        case DailyRule():
            return f"Every day {at}"
        case WeeklyRule():
            days = _join([w.full_name for w in rule.weekdays])
            if rule.every >= 2:
                return f"Every {rule.every} weeks on {days} {at}"
            return f"Every {days} {at}"
        case MonthlyRule():
            return f"Every {_WEEK_WORDS[rule.week]} {rule.weekday.full_name} of the month {at}"
        case MonthlyDayRule():
            if rule.day == -1:
                return f"Every month on the last day {at}"
            fallback = " (or the last day of shorter months)" if rule.day >= 29 else ""
            return f"Every month on the {_ordinal(rule.day)}{fallback} {at}"
