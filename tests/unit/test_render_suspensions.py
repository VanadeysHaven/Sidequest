"""Unit tests for the suspension render functions (D84–D87) and their hooks in `todo_embed`
and `short_when` (pure: DTOs in, text/embeds out)."""

from datetime import UTC, date, datetime

import pytest

from sidequest.bot import render
from sidequest.core.discord_time import ts, ts_due
from sidequest.core.enums import TodoKind, TodoStatus
from sidequest.core.limits import SUSPENSION_PAGE_SIZE
from sidequest.services.dto import (
    SuspensionChange,
    SuspensionPreview,
    SuspensionView,
    TodoView,
)

START = datetime(2030, 1, 7, 9, 0, tzinfo=UTC)
NEXT_DUE = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
RULE = "Every day at 09:00 (UTC)"
FIRST = date(2026, 11, 16)
LAST = date(2026, 11, 22)
DAY_RANGE = "16-11-2026 – 22-11-2026"


def make_todo(**overrides: object) -> TodoView:
    defaults: dict[str, object] = {
        "id": 1,
        "guild_id": 5,
        "list_id": 1,
        "list_name": "Groceries",
        "owner_id": 10,
        "title": "Buy milk",
        "details": None,
        "kind": TodoKind.ONCE,
        "status": TodoStatus.OPEN,
        "timezone": "UTC",
        "due_at": None,
        "rule": None,
        "rule_description": None,
        "next_due_at": None,
        "pending_occurrence_id": None,
        "reminder": None,
        "assignee_ids": (),
        "subtasks": (),
        "created_at": START,
        "completed_at": None,
        "completed_by": None,
        "can_edit": True,
        "can_complete": True,
    }
    return TodoView(**{**defaults, **overrides})


def make_recurring(**overrides: object) -> TodoView:
    defaults: dict[str, object] = {
        "kind": TodoKind.RECURRING,
        "rule_description": RULE,
        "next_due_at": NEXT_DUE,
        "pending_occurrence_id": 7,
    }
    return make_todo(**{**defaults, **overrides})


def span(start: date = FIRST, end: date = LAST, running: bool = False) -> SuspensionView:
    return SuspensionView(start=start, end=end, running=running)


def at(hour: int) -> datetime:
    return datetime(2026, 11, 16 + hour // 24, hour % 24, 0, tzinfo=UTC)


# --- suspension_label --------------------------------------------------------------------


def test_label_is_a_date_range_with_en_dash() -> None:
    assert render.suspension_label(span()) == DAY_RANGE


def test_label_running_starts_with_today() -> None:
    label = render.suspension_label(span(start=date(2026, 11, 14), running=True))
    assert label == "today – 22-11-2026"


def test_label_one_day_shows_only_the_date() -> None:
    assert render.suspension_label(span(end=FIRST)) == "16-11-2026"


def test_label_one_day_running_says_today() -> None:
    label = render.suspension_label(
        span(start=date(2026, 11, 14), end=date(2026, 11, 14), running=True)
    )
    assert label == "today"


# --- suspend_preview_text ----------------------------------------------------------------


def preview(
    skipped: tuple[datetime, ...] = (),
    suspension: SuspensionView | None = None,
    title: str = "Buy milk",
) -> SuspensionPreview:
    return SuspensionPreview(title=title, suspension=suspension or span(), skipped=skipped)


def test_preview_first_line_names_title_and_range() -> None:
    text = render.suspend_preview_text(preview(skipped=(at(0), at(1), at(2))))

    assert text.splitlines()[0] == (
        "Are you sure you want to suspend **Buy milk** from 16-11-2026 to 22-11-2026. "
        "The following 3 occurrences will be skipped:"
    )


def test_preview_single_reminder_says_occurrence() -> None:
    text = render.suspend_preview_text(preview(skipped=(at(0),)))

    assert text.splitlines()[0].endswith("The following 1 occurrence will be skipped:")


def test_preview_one_day_range_names_the_day_twice() -> None:
    text = render.suspend_preview_text(preview(skipped=(at(0),), suspension=span(end=FIRST)))

    assert "from 16-11-2026 to 16-11-2026. " in text.splitlines()[0]


def test_preview_running_shows_the_start_date() -> None:
    running = span(start=date(2026, 11, 14), running=True)
    text = render.suspend_preview_text(preview(skipped=(at(0),), suspension=running))

    assert "from 14-11-2026 to 22-11-2026. " in text.splitlines()[0]


def test_preview_with_no_entries_has_no_bullets_and_no_more_line() -> None:
    text = render.suspend_preview_text(preview(skipped=()))

    lines = text.splitlines()
    assert len(lines) == 1
    assert lines[0].endswith("The following 0 occurrences will be skipped:")
    assert "•" not in text
    assert "Page" not in text
    assert render.suspend_preview_pages(preview(skipped=())) == 1


def bullets(skipped: tuple[datetime, ...]) -> list[str]:
    return [f"• {ts(d, 'f')} ({ts(d, 'R')})" for d in skipped]


def test_preview_three_entries_lists_each_with_relative_time() -> None:
    skipped = (at(0), at(1), at(2))
    text = render.suspend_preview_text(preview(skipped=skipped))

    assert text.splitlines()[1:] == bullets(skipped)
    assert "Page" not in text


def test_preview_exactly_one_page_has_no_page_line() -> None:
    skipped = tuple(at(h) for h in range(20))
    text = render.suspend_preview_text(preview(skipped=skipped))

    assert render.suspend_preview_pages(preview(skipped=skipped)) == 1
    assert text.splitlines()[1:] == bullets(skipped)


@pytest.mark.parametrize(
    ("page", "shown", "footer"),
    [
        pytest.param(0, range(0, 20), "Page 1/3", id="first"),
        pytest.param(1, range(20, 40), "Page 2/3", id="middle"),
        pytest.param(2, range(40, 45), "Page 3/3", id="last, partial"),
        pytest.param(9, range(40, 45), "Page 3/3", id="past the end clamps"),
        pytest.param(-1, range(0, 20), "Page 1/3", id="before the start clamps"),
    ],
)
def test_preview_pages_through_the_skipped_reminders(page: int, shown: range, footer: str) -> None:
    skipped = tuple(at(h) for h in range(45))
    text = render.suspend_preview_text(preview(skipped=skipped), page)

    lines = text.splitlines()
    assert SUSPENSION_PAGE_SIZE == 20
    assert render.suspend_preview_pages(preview(skipped=skipped)) == 3
    assert lines[0].endswith("The following 45 occurrences will be skipped:")
    assert lines[1:-1] == bullets(tuple(skipped[i] for i in shown))
    assert lines[-1] == footer


def test_preview_title_markdown_is_escaped() -> None:
    title = "*Milk* @everyone"
    text = render.suspend_preview_text(preview(skipped=(at(0),), title=title))

    assert f"suspend **{render.esc(title)}** from " in text.splitlines()[0]
    assert render.esc(title) != title
    assert "@everyone" not in text


# --- suspended_text / unsuspended_text ---------------------------------------------------


def test_suspended_text_for_recurring_todo_shows_next_reminder() -> None:
    todo = make_recurring()
    change = SuspensionChange(todo=todo, suspension=span())

    text = render.suspended_text(change)

    assert text == (
        f"⏸️ **Buy milk** is suspended from 16-11-2026 to 22-11-2026. Next: {ts_due(NEXT_DUE)}"
    )
    assert text.endswith(render.next_line(todo))


def test_suspended_text_next_line_matches_next_line_helper() -> None:
    todo = make_recurring()
    text = render.suspended_text(SuspensionChange(todo=todo, suspension=span()))

    assert text.endswith(
        f"Next: <t:{int(NEXT_DUE.timestamp())}:F> (<t:{int(NEXT_DUE.timestamp())}:R>)"
    )


def test_suspended_text_running_says_from_today() -> None:
    running = span(start=date(2026, 11, 14), running=True)
    text = render.suspended_text(SuspensionChange(todo=make_recurring(), suspension=running))

    assert text.startswith("⏸️ **Buy milk** is suspended from today to 22-11-2026. ")


def test_suspended_text_escapes_title() -> None:
    todo = make_recurring(title="*Milk* @everyone")
    text = render.suspended_text(SuspensionChange(todo=todo, suspension=span()))

    assert text.startswith(f"⏸️ **{render.esc('*Milk* @everyone')}** is suspended ")
    assert "@everyone" not in text


def test_unsuspended_text_names_the_cancelled_range_and_next_line() -> None:
    todo = make_recurring()
    text = render.unsuspended_text(SuspensionChange(todo=todo, suspension=span()))

    assert text == (
        "▶️ Suspension of **Buy milk** from 16-11-2026 to 22-11-2026 cancelled. "
        + render.next_line(todo)
    )


def test_unsuspended_text_one_day_uses_for_wording() -> None:
    todo = make_recurring()
    text = render.unsuspended_text(SuspensionChange(todo=todo, suspension=span(end=FIRST)))

    assert text.startswith("▶️ Suspension of **Buy milk** for 16-11-2026 cancelled. ")


# --- todo_embed "Suspended" field --------------------------------------------------------


def field_names(todo: TodoView) -> list[str]:
    return [f.name for f in render.todo_embed(todo).fields]


def test_embed_suspended_field_joins_labels_with_newline() -> None:
    todo = make_recurring(
        suspensions=(
            span(),
            span(start=date(2026, 12, 1), end=date(2026, 12, 1)),
        ),
    )
    fields = {f.name: f.value for f in render.todo_embed(todo).fields}

    assert fields["Suspended"] == "16-11-2026 – 22-11-2026\n01-12-2026"


def test_embed_suspended_field_follows_when_field() -> None:
    todo = make_recurring(suspensions=(span(),))
    names = field_names(todo)

    assert names[0] == "When"
    assert names[1] == "Suspended"


def test_embed_has_no_suspended_field_without_suspensions() -> None:
    assert "Suspended" not in field_names(make_recurring())


# --- short_when "⏸️ until" marker --------------------------------------------------------


def test_short_when_adds_until_marker_while_suspended() -> None:
    todo = make_recurring(suspended_until=date(2026, 11, 22))
    text = render.short_when(todo)

    assert text.endswith(" · ⏸️ until 22-11-2026")
    assert text.startswith(f"🔁 {ts(NEXT_DUE, 'f')} ({ts(NEXT_DUE, 'R')})")


def test_short_when_without_suspension_has_no_marker() -> None:
    text = render.short_when(make_recurring())

    assert "⏸️" not in text
    assert text == f"🔁 {ts(NEXT_DUE, 'f')} ({ts(NEXT_DUE, 'R')})"


def test_short_when_one_time_todo_ignores_suspension_marker() -> None:
    due = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
    todo = make_todo(kind=TodoKind.ONCE, due_at=due, suspended_until=date(2026, 11, 22))

    assert render.short_when(todo) == f"{ts(due, 'f')} ({ts(due, 'R')})"
    assert "⏸️" not in render.short_when(todo)


@pytest.mark.parametrize("suspended_until", [None, date(2026, 11, 22)])
def test_short_when_untimed_one_time_todo_is_unaffected(suspended_until: date | None) -> None:
    todo = make_todo(suspended_until=suspended_until)

    assert render.short_when(todo) == "no reminder"
