"""Unit tests for the week builder's pure rendering (D93): week lines, footer, embed, select
options, modal title and shared-times helpers in `sidequest.bot.render_week`."""

from datetime import date, time

import pytest

from sidequest.bot.render_week import (
    EXPIRED,
    NOT_ADDED,
    NOTHING_CHANGED,
    OFF_SELECT_PLACEHOLDER,
    day_options,
    shared_times,
    short_name,
    times_modal_title,
    times_text,
    week_embed,
    week_footer,
    week_lines,
)
from sidequest.core.enums import Weekday
from sidequest.core.recurrence import WeekTimes

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MIXED: WeekTimes = {
    Weekday.MON: (time(5, 10),),
    Weekday.TUE: (time(7, 30),),
    Weekday.WED: (time(5, 10),),
    Weekday.THU: (time(5, 10),),
    Weekday.SAT: (time(9, 0), time(18, 0)),
}
FULL: WeekTimes = {day: (time(9, 0), time(18, 0)) for day in Weekday}
MIXED_LINES = [
    "**Mon**  05:10",
    "**Tue**  07:30",
    "**Wed**  05:10",
    "**Thu**  05:10",
    "**Fri**  —",
    "**Sat**  09:00, 18:00",
    "**Sun**  —",
]
DAY_PAIRS: list[tuple[list[Weekday], str]] = [
    ([Weekday.MON], "Times for Mon"),
    ([Weekday.MON, Weekday.WED, Weekday.THU], "Times for Mon, Wed and Thu"),
    ([Weekday.THU, Weekday.MON, Weekday.MON], "Times for Mon and Thu"),
    (list(Weekday), "Times for every day"),
    (
        [Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.FRI, Weekday.SAT],
        "Times for Mon, Tue, Wed, Thu, Fri and Sat",
    ),
]


@pytest.mark.parametrize(
    ("week", "expected"),
    [
        ({}, [f"**{name}**  —" for name in DAY_NAMES]),
        (FULL, [f"**{name}**  09:00, 18:00" for name in DAY_NAMES]),
        (MIXED, MIXED_LINES),
    ],
    ids=["empty", "full", "mixed"],
)
def test_week_lines(week: WeekTimes, expected: list[str]) -> None:
    assert week_lines(week) == expected


@pytest.mark.parametrize(
    ("tz", "every", "start", "end", "expected"),
    [
        ("Europe/Amsterdam", 1, None, None, "Europe/Amsterdam"),
        (
            "Europe/Amsterdam",
            2,
            date(2026, 11, 16),
            date(2026, 12, 31),
            "Europe/Amsterdam · every 2 weeks · from 16-11-2026 · until 31-12-2026",
        ),
        ("UTC", 3, None, None, "UTC · every 3 weeks"),
        ("UTC", 1, date(2026, 11, 16), None, "UTC · from 16-11-2026"),
        ("UTC", 1, None, date(2026, 12, 31), "UTC · until 31-12-2026"),
    ],
    ids=["zone-only", "all-parts", "every-only", "start-only", "end-only"],
)
def test_week_footer(
    tz: str, every: int, start: date | None, end: date | None, expected: str
) -> None:
    assert week_footer(tz, every=every, start=start, end=end) == expected


def test_week_embed_title_description_and_footer() -> None:
    embed = week_embed(
        "Gym *x*",
        MIXED,
        "Europe/Amsterdam",
        every=2,
        start=date(2026, 11, 16),
        end=date(2026, 12, 31),
    )
    assert embed.title == "Week for Gym *x*"
    assert embed.description == "\n".join(MIXED_LINES)
    assert embed.footer.text == (
        "Europe/Amsterdam · every 2 weeks · from 16-11-2026 · until 31-12-2026"
    )


def test_week_embed_cuts_long_title() -> None:
    title = "a" * 300
    embed = week_embed(title, {}, "UTC")
    assert embed.title is not None
    assert len(embed.title) == 256
    assert embed.title.endswith("…")
    assert embed.title == f"Week for {title}"[:255] + "…"


def test_day_options() -> None:
    options = day_options({Weekday.MON: (time(9, 0), time(18, 0)), Weekday.WED: (time(5, 10),)})
    assert len(options) == 7
    assert [o.label for o in options] == [day.full_name for day in Weekday]
    assert [o.value for o in options] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    assert [o.description for o in options] == [
        "09:00, 18:00",
        "off",
        "05:10",
        "off",
        "off",
        "off",
        "off",
    ]
    assert all(o.default is False for o in options)


@pytest.mark.parametrize(("days", "expected"), DAY_PAIRS)
def test_times_modal_title(days: list[Weekday], expected: str) -> None:
    title = times_modal_title(days)
    assert title == expected
    assert len(title) <= 45


@pytest.mark.parametrize(
    ("week", "days", "expected"),
    [
        (MIXED, [Weekday.MON, Weekday.WED, Weekday.THU], (time(5, 10),)),
        (MIXED, [Weekday.MON, Weekday.TUE], None),
        ({}, [Weekday.MON, Weekday.TUE], None),
        (MIXED, [Weekday.MON, Weekday.FRI], None),
        (MIXED, [Weekday.SAT], (time(9, 0), time(18, 0))),
        (MIXED, [Weekday.FRI], None),
    ],
    ids=["shared", "differ", "all-off", "mixed-on-off", "single-day", "single-off"],
)
def test_shared_times(
    week: WeekTimes, days: list[Weekday], expected: tuple[time, ...] | None
) -> None:
    assert shared_times(week, days) == expected


@pytest.mark.parametrize(
    ("times", "expected"),
    [
        ([], ""),
        ([time(5, 10), time(18, 0)], "05:10, 18:00"),
        ([time(9, 0)], "09:00"),
    ],
)
def test_times_text(times: list[time], expected: str) -> None:
    assert times_text(times) == expected


def test_short_name() -> None:
    assert short_name(Weekday.WED) == "Wed"


@pytest.mark.parametrize(
    ("constant", "expected"),
    [
        (EXPIRED, "This week editor expired; nothing was saved."),
        (NOT_ADDED, "Not added."),
        (NOTHING_CHANGED, "Nothing changed."),
        (OFF_SELECT_PLACEHOLDER, "Turn days off…"),
    ],
)
def test_message_constants(constant: str, expected: str) -> None:
    assert constant == expected
