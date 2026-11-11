"""Repeat rules: validation, JSON (JSONB) shape, next occurrence, and descriptions.

Pure and hand-written (D15). All rule times are wall-clock times in the to-do's timezone,
so they stay at the same local time across DST (BRIEF §4.3). JSON shape (S2):

    {"type": "daily",       "times": ["08:00", "20:00"]}
    {"type": "weekly",      "weekdays": ["mon", "thu"], "times": ["12:00"]}
    {"type": "monthly",     "week": 1, "weekday": "sun", "times": ["12:00"]}  # week -1 = last
    {"type": "monthly_day", "day": 15, "times": ["09:00"]}                    # day -1 = last
"""

import calendar
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal
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
)

from sidequest.core.enums import Weekday
from sidequest.core.errors import InvalidRule, SidequestError
from sidequest.core.limits import TIMES_PER_RULE_MAX
from sidequest.core.timeparse import parse_time, resolve_local

# Every valid rule fires at least once a month; this only guards against bugs.
MAX_SEARCH_DAYS = 800

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


RuleTime = Annotated[
    time, BeforeValidator(_to_time), PlainSerializer(_hhmm, return_type=str, when_used="json")
]
Times = Annotated[tuple[RuleTime, ...], AfterValidator(_check_times)]
Weekdays = Annotated[tuple[Weekday, ...], AfterValidator(_check_weekdays)]
Week = Annotated[int, Field(strict=True), AfterValidator(_check_week)]
MonthDay = Annotated[int, Field(strict=True), AfterValidator(_check_day)]


# --- rules -------------------------------------------------------------------------------


class _Rule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as e:
            raise InvalidRule(_error_message(e)) from None


class DailyRule(_Rule):
    type: Literal["daily"] = "daily"
    times: Times


class WeeklyRule(_Rule):
    type: Literal["weekly"] = "weekly"
    weekdays: Weekdays
    times: Times


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
    return f"Invalid repeat rule ({where}): {msg}" if where else f"Invalid repeat rule: {msg}"


def from_json(data: Any) -> RecurrenceRule:
    """Validate a JSONB payload into a rule. Raises `InvalidRule`."""
    try:
        return _adapter.validate_python(data)
    except ValidationError as e:
        raise InvalidRule(_error_message(e)) from None


def to_json(rule: RecurrenceRule) -> dict[str, Any]:
    """The JSONB payload for a rule (times as "HH:MM")."""
    return rule.model_dump(mode="json")


# --- occurrences -------------------------------------------------------------------------


def _last_day(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def _matches(rule: RecurrenceRule, d: date) -> bool:
    match rule:
        case DailyRule():
            return True
        case WeeklyRule():
            return Weekday.from_index(d.weekday()) in rule.weekdays
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


def next_occurrence(rule: RecurrenceRule, tz: ZoneInfo, after: datetime) -> datetime:
    """The first occurrence strictly after `after`, as aware UTC."""
    if after.tzinfo is None:
        raise ValueError("naive datetime; use timezone-aware UTC")
    # Start a day early: cheap insurance against DST edge cases around local midnight.
    start = after.astimezone(tz).date() - timedelta(days=1)
    for offset in range(MAX_SEARCH_DAYS):
        d = start + timedelta(days=offset)
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
    result: list[datetime] = []
    at = next_occurrence(rule, tz, start - timedelta(microseconds=1))
    while at < end:
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


def describe(rule: RecurrenceRule, tz: ZoneInfo) -> str:
    """Human description in 24h wall-clock time, e.g. "Every day at 08:00 (UTC)"."""
    at = f"at {_join([_hhmm(t) for t in rule.times])} ({tz.key})"
    match rule:
        case DailyRule():
            return f"Every day {at}"
        case WeeklyRule():
            return f"Every {_join([w.full_name for w in rule.weekdays])} {at}"
        case MonthlyRule():
            return f"Every {_WEEK_WORDS[rule.week]} {rule.weekday.full_name} of the month {at}"
        case MonthlyDayRule():
            if rule.day == -1:
                return f"Every month on the last day {at}"
            fallback = " (or the last day of shorter months)" if rule.day >= 29 else ""
            return f"Every month on the {_ordinal(rule.day)}{fallback} {at}"
