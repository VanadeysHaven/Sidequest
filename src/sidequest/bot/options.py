"""Slash command options → service arguments. Pure, so the mapping is unit-testable."""

import enum
from datetime import date
from typing import Any

from sidequest.core.enums import TodoKind, Weekday
from sidequest.core.errors import InvalidOperation
from sidequest.core.recurrence import (
    DailyRule,
    MonthlyDayRule,
    MonthlyRule,
    RecurrenceRule,
    WeeklyRule,
)
from sidequest.core.timeparse import parse_month_day, parse_times, parse_weekdays
from sidequest.core.tz import get_zone
from sidequest.services.dto import DueInput, TodoPatch, TodoView


class WeekOption(enum.Enum):
    """`week` choices for monthly-weekday rules. Member names are what Discord shows."""

    First = 1
    Second = 2
    Third = 3
    Fourth = 4
    Last = -1


class WeekdayOption(enum.Enum):
    Monday = "mon"
    Tuesday = "tue"
    Wednesday = "wed"
    Thursday = "thu"
    Friday = "fri"
    Saturday = "sat"
    Sunday = "sun"


class Clear(enum.Enum):
    """`start:none` / `end:none` in `/todo edit`: remove the date (D73)."""

    CLEAR = "none"


CLEAR = Clear.CLEAR
type EditDate = date | Clear | None
"""A `/todo edit` date option: a date, `CLEAR`, or None (not given)."""


def is_clear(text: str) -> bool:
    return text.strip().lower() == CLEAR.value


REPEAT_ONLY = ("times", "days", "week", "weekday", "day", "every", "start", "end")


def edit_patch(
    todo: TodoView,
    *,
    title: str | None = None,
    due: DueInput | None = None,
    timezone: str | None = None,
    times: str | None = None,
    days: str | None = None,
    week: WeekOption | None = None,
    weekday: WeekdayOption | None = None,
    day: str | None = None,
    every: int | None = None,
    start: EditDate = None,
    end: EditDate = None,
) -> TodoPatch:
    """`/todo edit` options → `TodoPatch`, checked against the to-do's kind and rule type.

    For a timed one-time to-do, a date without a time keeps its current wall-clock time.
    """
    fields: dict[str, Any] = {}
    if title is not None:
        fields["title"] = title
    if timezone:
        fields["timezone"] = timezone
    rule_parts = {
        "times": times,
        "days": days,
        "week": week,
        "weekday": weekday,
        "day": day,
        "every": every,
        "start": start,
        "end": end,
    }
    if todo.kind == TodoKind.RECURRING:
        if due is not None:
            raise InvalidOperation(
                "A repeating to-do has no date or single time. "
                "Change `times` (or `days`, `week`, `weekday`, `day`) instead."
            )
        assert todo.rule is not None
        rule = edited_rule(todo.rule, **rule_parts)  # type: ignore[arg-type]
        if rule is not None:
            fields["rule"] = rule
    else:
        if any(value is not None for value in rule_parts.values()):
            raise InvalidOperation(
                "`times`, `days`, `week`, `weekday`, `day`, `every`, `start` and `end` are "
                "for repeating to-dos. "
                "Use `date` and `time` here."
            )
        if due is not None:
            if due.time is None and due.date is not None and todo.due_at is not None:
                zone = get_zone(timezone or todo.timezone)
                due = DueInput(
                    date=due.date,
                    time=todo.due_at.astimezone(zone).time(),
                    roll_week=due.roll_week,
                )
            fields["due"] = due
    if not fields:
        raise InvalidOperation("Nothing to change: give at least one option besides `todo`.")
    return TodoPatch(**fields)


def split_items(text: str) -> list[str]:
    """`/todo subtask add items:` uses `;` as separator (slash options are single-line)."""
    return [part.strip() for part in text.split(";") if part.strip()]


# --- rules -------------------------------------------------------------------------------


def daily_rule(times: str) -> DailyRule:
    return DailyRule(times=parse_times(times))


def weekly_rule(days: str, times: str, every: int = 1, start: date | None = None) -> WeeklyRule:
    """`every` ≥ 2 without `start` is anchored by the service (D56)."""
    return WeeklyRule(
        weekdays=parse_weekdays(days), times=parse_times(times), every=every, start=start
    )


def with_window[R: RecurrenceRule](rule: R, start: date | None, end: date | None) -> R:
    """`rule` with the `start`/`end` options (D73), validated (`end` before `start` is
    refused)."""
    return type(rule)(**{**rule.model_dump(), "start": start, "end": end})


def monthly_weekday_rule(week: WeekOption, weekday: WeekdayOption, times: str) -> MonthlyRule:
    return MonthlyRule(week=week.value, weekday=Weekday(weekday.value), times=parse_times(times))


def monthly_day_rule(day: str, times: str) -> MonthlyDayRule:
    return MonthlyDayRule(day=parse_month_day(day), times=parse_times(times))


_WINDOW = {"start", "end"}
"""Every rule type has them (D73)."""
_RULE_FIELDS: dict[type, set[str]] = {
    DailyRule: {"times"} | _WINDOW,
    WeeklyRule: {"times", "days", "every"} | _WINDOW,
    MonthlyRule: {"times", "week", "weekday"} | _WINDOW,
    MonthlyDayRule: {"times", "day"} | _WINDOW,
}
_KIND_NAMES: dict[type, str] = {
    DailyRule: "daily",
    WeeklyRule: "weekly",
    MonthlyRule: "monthly on a weekday",
    MonthlyDayRule: "monthly on a day",
}


def edited_rule(
    rule: RecurrenceRule,
    *,
    times: str | None = None,
    days: str | None = None,
    week: WeekOption | None = None,
    weekday: WeekdayOption | None = None,
    day: str | None = None,
    every: int | None = None,
    start: EditDate = None,
    end: EditDate = None,
) -> RecurrenceRule | None:
    """`rule` with the given parts replaced (None: nothing given). The rule type stays;
    an option that belongs to another rule type is an error (BRIEF: switching type means
    delete + re-create). A rule keeps its stored `start`/`end` unless one is given (D57);
    `CLEAR` removes it (D73). A weekly rule with `every` ≥ 2 and no `start` (cleared, or
    going to `every` ≥ 2 without one) is left for the service to anchor (D56)."""
    given = {
        name
        for name, value in {
            "times": times,
            "days": days,
            "week": week,
            "weekday": weekday,
            "day": day,
            "every": every,
            "start": start,
            "end": end,
        }.items()
        if value is not None
    }
    if not given:
        return None
    wrong = sorted(given - _RULE_FIELDS[type(rule)])
    if wrong:
        names = ", ".join(f"`{n}`" for n in wrong)
        raise InvalidOperation(
            f"This to-do repeats {_KIND_NAMES[type(rule)]}, so {names} can't be changed. "
            "To switch the repeat type, delete the to-do and add it again."
        )

    changes: dict[str, Any] = {}
    if times is not None:
        changes["times"] = parse_times(times)
    if days is not None:
        changes["weekdays"] = parse_weekdays(days)
    if week is not None:
        changes["week"] = week.value
    if weekday is not None:
        changes["weekday"] = Weekday(weekday.value)
    if day is not None:
        changes["day"] = parse_month_day(day)
    if every is not None:
        changes["every"] = every
    for name, value in (("start", start), ("end", end)):
        if value is not None:
            changes[name] = None if value is CLEAR else value
    return type(rule)(**{**rule.model_dump(), **changes})
