"""Pure rendering for the week builder (D93): its embed, select options and modal title.

Kept out of `render.py` (already past the ~400-line guideline). Wall-clock times are
24h text, not timestamps (they aren't points in time); dates are `DD-MM-YYYY`.
"""

from collections.abc import Iterable
from datetime import date, time

import discord

from sidequest.bot.render import EMBED_TITLE_MAX, cut
from sidequest.core.enums import Weekday
from sidequest.core.recurrence import WeekTimes
from sidequest.core.text import plain_date

MODAL_TITLE_MAX = 45
OFF_LINE = "—"
OFF_OPTION = "off"

EXPIRED = "This week editor expired; nothing was saved."
NOT_ADDED = "Not added."
NOTHING_CHANGED = "Nothing changed."
TIMES_SELECT_PLACEHOLDER = "Set times for…"
OFF_SELECT_PLACEHOLDER = "Turn days off…"
EMPTY_WEEK = "Set times for at least one day first."
TIMES_PLACEHOLDER = "05:10, 18:00"


def short_name(day: Weekday) -> str:
    """The short name, e.g. "Mon"."""
    return day.full_name[:3]


def times_text(times: Iterable[time]) -> str:
    """The times as text, e.g. "05:10, 18:00" (empty for no times)."""
    return ", ".join(f"{t.hour:02d}:{t.minute:02d}" for t in times)


def week_lines(week: WeekTimes) -> list[str]:
    """Seven lines, Monday to Sunday: the day and its times, or "—" when it's off."""
    lines = []
    for day in Weekday:
        times = week.get(day, ())
        lines.append(f"**{short_name(day)}**  {times_text(times) if times else OFF_LINE}")
    return lines


def week_footer(
    tz: str, *, every: int = 1, start: date | None = None, end: date | None = None
) -> str:
    parts = [tz]
    if every >= 2:
        parts.append(f"every {every} weeks")
    if start is not None:
        parts.append(f"from {plain_date(start)}")
    if end is not None:
        parts.append(f"until {plain_date(end)}")
    return " · ".join(parts)


def week_embed(
    title: str,
    week: WeekTimes,
    tz: str,
    *,
    every: int = 1,
    start: date | None = None,
    end: date | None = None,
) -> discord.Embed:
    """Embed "Week for <title>" (embed titles show no markdown or mentions, so no escaping),
    seven day lines, footer with the zone and every/start/end (D93)."""
    embed = discord.Embed(
        title=cut(f"Week for {title}", EMBED_TITLE_MAX), description="\n".join(week_lines(week))
    )
    embed.set_footer(text=week_footer(tz, every=every, start=start, end=end))
    return embed


def day_options(week: WeekTimes) -> list[discord.SelectOption]:
    """Mon–Sun for **Set times for…** and **Turn days off…**; each description is the
    day's times or "off". None is selected (the selection resets after every change, D93)."""
    return [
        discord.SelectOption(
            label=day.full_name,
            value=day.value,
            description=times_text(week[day]) if week.get(day) else OFF_OPTION,
        )
        for day in Weekday
    ]


def times_modal_title(days: Iterable[Weekday]) -> str:
    """The modal title, e.g. "Times for Mon, Wed and Thu" ("every day" for all seven;
    ≤ 45 characters)."""
    picked = sorted(set(days), key=lambda d: d.index)
    if len(picked) == len(Weekday):
        return "Times for every day"
    names = [short_name(d) for d in picked]
    joined = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    return f"Times for {joined}"[:MODAL_TITLE_MAX]


def shared_times(week: WeekTimes, days: Iterable[Weekday]) -> tuple[time, ...] | None:
    """The times every one of `days` has (to prefill the modal), else None."""
    found = {week.get(day, ()) for day in days}
    if len(found) != 1:
        return None
    times = found.pop()
    return times or None
