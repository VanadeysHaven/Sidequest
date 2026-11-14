"""Repeating to-dos that run out (D73–D78): the last occurrence and the "anything left?" check."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sidequest.core import recurrence
from sidequest.core.errors import InvalidRule
from sidequest.core.recurrence import RecurrenceRule
from sidequest.core.text import bold, plain_date
from sidequest.db.models import Occurrence


def final_occurrence(
    rule: RecurrenceRule, tz: ZoneInfo, pending: Occurrence | None, sent: Occurrence | None
) -> Occurrence | None:
    """The open occurrence that is the series' last one, if any (D76).

    The pending one when nothing follows it; without a pending one, the reminder that is up
    (the scheduler always materializes the next one unless the series is over, so a lone
    reminder is the last, also a catch-up after downtime past `end`).
    """
    if pending is not None:
        return pending if recurrence.next_occurrence(rule, tz, pending.due_at) is None else None
    return sent


def nothing_between(title: str, rule: RecurrenceRule, tz: ZoneInfo, now: datetime) -> InvalidRule:
    """D75: no occurrence falls between now (or `start`) and `end`."""
    first = now.astimezone(tz).date()
    if rule.start is not None:
        first = max(first, rule.start)
    end = rule.end if rule.end is not None else first
    if end < first:
        return InvalidRule(f"No reminder of {bold(title)} is left: it ends on {plain_date(end)}.")
    return InvalidRule(
        f"No reminder of {bold(title)} falls between {plain_date(first)} and {plain_date(end)}."
    )


def is_over(rule: RecurrenceRule, tz: ZoneInfo, now: datetime) -> bool:
    """Nothing left after `now` (D76)."""
    return recurrence.next_occurrence(rule, tz, now) is None


def require_upcoming(title: str, rule: RecurrenceRule, tz: ZoneInfo, now: datetime) -> None:
    """D75: a new or changed rule needs at least one occurrence after `now`."""
    if is_over(rule, tz, now):
        raise nothing_between(title, rule, tz, now)
