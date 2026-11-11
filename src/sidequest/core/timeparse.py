"""Parsing user input for times, dates and rule parts, and resolving local times to UTC.

English only (D28). Times are 24-hour only (C4). Functions never read the clock: callers
pass `today` / `now` explicitly.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sidequest.core.discord_time import ts
from sidequest.core.enums import Weekday
from sidequest.core.errors import InPast, InvalidDate, InvalidRule, InvalidTime
from sidequest.core.limits import TIMES_PER_RULE_MAX

_TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})")
_AM_PM_RE = re.compile(r"[ap]\.?\s*m\b", re.IGNORECASE)
_LIST_SEP_RE = re.compile(r"[,\s]+")

_YMD_RE = re.compile(r"(\d{4})([-/.])(\d{1,2})\2(\d{1,2})")
_DMY_RE = re.compile(r"(\d{1,2})([-/.])(\d{1,2})\2(\d{4})")
_DMY_SHORT_YEAR_RE = re.compile(r"\d{1,2}([-/.])\d{1,2}\1\d{2}")

_MONTH_DAY_RE = re.compile(r"(\d{1,2})(st|nd|rd|th)?")

TIME_HINT = "Use 24-hour time, e.g. 14:30."
DATE_HINT = "Use YYYY-MM-DD or DD-MM-YYYY (e.g. 2026-11-12), or today/tomorrow."


# --- times -------------------------------------------------------------------------------


def parse_time(s: str) -> time:
    """`H:MM`, `HH:MM` or `HH.MM`, 00:00–23:59."""
    text = s.strip()
    if _AM_PM_RE.search(text):
        raise InvalidTime(f"No am/pm, please. {TIME_HINT}")
    match = _TIME_RE.fullmatch(text)
    if match is None:
        raise InvalidTime(f"Invalid time: {text or '(empty)'}. {TIME_HINT}")
    hour, minute = int(match[1]), int(match[2])
    if hour > 23 or minute > 59:
        raise InvalidTime(f"Invalid time: {text}. {TIME_HINT}")
    return time(hour, minute)


def parse_times(s: str) -> list[time]:
    """Comma- or space-separated times; deduplicated, sorted, 1–12 entries."""
    if _AM_PM_RE.search(s):
        raise InvalidTime(f"No am/pm, please. {TIME_HINT}")
    parts = [p for p in _LIST_SEP_RE.split(s.strip()) if p]
    if not parts:
        raise InvalidTime(f"Enter at least one time. {TIME_HINT}")
    times = sorted({parse_time(p) for p in parts})
    if len(times) > TIMES_PER_RULE_MAX:
        raise InvalidTime(f"At most {TIMES_PER_RULE_MAX} times, please.")
    return times


# --- dates -------------------------------------------------------------------------------


def parse_date(s: str, today: date) -> date:
    """`YYYY-MM-DD`, `DD-MM-YYYY` (separators `-` `/` `.`), `today` or `tomorrow`."""
    text = s.strip().lower()
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)

    if match := _YMD_RE.fullmatch(text):
        year, month, day = int(match[1]), int(match[3]), int(match[4])
    elif match := _DMY_RE.fullmatch(text):
        day, month, year = int(match[1]), int(match[3]), int(match[4])
    elif _DMY_SHORT_YEAR_RE.fullmatch(text):
        raise InvalidDate(f"Write the year in full, e.g. 12-11-2026. {DATE_HINT}")
    else:
        raise InvalidDate(f"Invalid date: {s.strip() or '(empty)'}. {DATE_HINT}")

    try:
        return date(year, month, day)
    except ValueError:
        raise InvalidDate(f"{s.strip()} is not a valid date.") from None


# --- rule parts --------------------------------------------------------------------------

_WEEKDAY_WORDS: dict[str, tuple[Weekday, ...]] = {
    **{w.value: (w,) for w in Weekday},
    **{w.full_name.lower(): (w,) for w in Weekday},
    "tues": (Weekday.TUE,),
    "weds": (Weekday.WED,),
    "thur": (Weekday.THU,),
    "thurs": (Weekday.THU,),
    "weekdays": (Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.FRI),
    "weekend": (Weekday.SAT, Weekday.SUN),
}


def parse_weekdays(s: str) -> list[Weekday]:
    """`mon,thu`, full English names, `weekdays`, `weekend`; deduplicated, Monday first."""
    parts = [p for p in _LIST_SEP_RE.split(s.strip().lower()) if p and p != "and"]
    if not parts:
        raise InvalidRule("Enter at least one weekday, e.g. mon,thu.")
    found: set[Weekday] = set()
    for part in parts:
        days = _WEEKDAY_WORDS.get(part)
        if days is None:
            raise InvalidRule(
                f"Unknown weekday: {part}. Use e.g. mon,thu or monday,thursday, "
                "or weekdays / weekend."
            )
        found.update(days)
    return sorted(found, key=lambda w: w.index)


def parse_month_day(s: str) -> int:
    """`1`–`31` (also `1st`, `15th`, …) or `last` → -1."""
    text = s.strip().lower()
    if text == "last":
        return -1
    match = _MONTH_DAY_RE.fullmatch(text)
    if match is None or not 1 <= int(match[1]) <= 31:
        raise InvalidRule(f"Invalid day of the month: {s.strip()}. Use 1–31 or last.")
    return int(match[1])


# --- resolving ---------------------------------------------------------------------------


def resolve_local(d: date, t: time, tz: ZoneInfo) -> datetime:
    """Wall-clock date + time in `tz` → aware UTC datetime.

    DST: a nonexistent local time (spring-forward gap) shifts forward by the gap; an
    ambiguous one (fall-back) resolves to its first instance. Both follow from `fold=0`:
    zoneinfo then applies the offset in force *before* the transition, which for a gap
    time lands the length of the gap later, and for a repeated time picks the earlier one.
    """
    if t.tzinfo is not None:
        raise ValueError("expected a wall-clock time without tzinfo")
    local = datetime.combine(d, t.replace(fold=0), tzinfo=tz)
    return local.astimezone(UTC)


@dataclass(frozen=True)
class Untimed:
    """No date and no time: the to-do has no reminder."""


@dataclass(frozen=True)
class Timed:
    """A single due moment, aware UTC."""

    at: datetime


type Due = Untimed | Timed


def resolve_due(d: date | None, t: time | None, tz: ZoneInfo, now: datetime) -> Due:
    """Turn optional date/time input for a one-time to-do into its due moment (D17, D18)."""
    if now.tzinfo is None:
        raise ValueError("naive datetime; use timezone-aware UTC")
    if t is None:
        if d is not None:
            raise InvalidTime("A date needs a time, e.g. 14:30.")
        return Untimed()

    if d is None:
        today = now.astimezone(tz).date()
        at = resolve_local(today, t, tz)
        if at <= now:
            at = resolve_local(today + timedelta(days=1), t, tz)
        return Timed(at)

    at = resolve_local(d, t, tz)
    if at <= now:
        raise InPast(f"{ts(at)} is in the past. Pick a later date or time.")
    return Timed(at)
