"""Unit tests for sidequest.bot.render (pure: DTOs in, text/embeds/options out)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sidequest.bot import render
from sidequest.core.enums import Scope, TodoKind, TodoStatus
from sidequest.core.recurrence import DailyRule, describe
from sidequest.services.dto import Page, SubtaskView, TodoView, UpcomingItem

START = datetime(2030, 1, 7, 9, 0, tzinfo=UTC)

OPEN_MARK = "☐"
DONE_MARK = "☑"


def make_todo(**overrides: object) -> TodoView:
    defaults: dict[str, object] = {
        "id": 1,
        "scope": Scope.PERSONAL,
        "guild_id": None,
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
    }
    return TodoView(**{**defaults, **overrides})


def sub(i: int, title: str = "x", done: bool = False) -> SubtaskView:
    return SubtaskView(
        id=i,
        position=i,
        title=title,
        done=done,
        done_at=START if done else None,
        done_by=10 if done else None,
    )


def _max_size_todo(subtask_title: str = "S" * 100, details: str | None = "D" * 4000) -> TodoView:
    rule = DailyRule(times=["09:00"])
    return make_todo(
        title="T" * 200,
        details=details,
        scope=Scope.SERVER,
        guild_id=5,
        assignee_ids=tuple(range(1, 11)),
        kind=TodoKind.RECURRING,
        rule=rule,
        rule_description=describe(rule, ZoneInfo("UTC")),
        next_due_at=START,
        subtasks=tuple(sub(i, subtask_title) for i in range(1, 51)),
    )


# --- todo_embed --------------------------------------------------------------------------


def test_max_size_todo_stays_within_discord_limits() -> None:
    e = render.todo_embed(_max_size_todo())

    assert len(e) <= 6000
    assert len(e.description) <= 4096
    assert all(len(field.value) <= 1024 for field in e.fields)
    assert len(e.fields) <= 25


def test_max_size_todo_says_how_many_subtasks_were_left_out() -> None:
    e = render.todo_embed(_max_size_todo())

    shown = sum(
        line.startswith(OPEN_MARK)
        for field in e.fields
        if field.name.startswith("Subtasks") or field.name == "​"
        for line in field.value.split("\n")
    )
    n = 50 - shown
    assert e.fields[-1].value.endswith(f"… and {n} more")


def test_short_subtasks_all_shown_without_more_text() -> None:
    e = render.todo_embed(_max_size_todo(subtask_title="x", details=None))

    shown = sum(
        line.startswith(OPEN_MARK)
        for field in e.fields
        if field.name.startswith("Subtasks") or field.name == "​"
        for line in field.value.split("\n")
    )
    assert shown == 50
    texts = [e.description or ""] + [part for f in e.fields for part in (f.name, f.value)]
    assert all("more" not in text for text in texts)


def test_subtask_field_shows_done_count_and_marks() -> None:
    todo = make_todo(
        subtasks=(sub(1, "x"), sub(2, "x", done=True), sub(3, "x")),
    )
    e = render.todo_embed(todo)

    fields = {f.name: f.value for f in e.fields}
    assert fields["Subtasks (1/3 done)"] == f"{OPEN_MARK} 1. x\n{DONE_MARK} 2. x\n{OPEN_MARK} 3. x"


# --- when --------------------------------------------------------------------------------


def test_when_untimed() -> None:
    assert render.when(make_todo()) == "No reminder (untimed)"


def test_when_one_time_with_due_date() -> None:
    ts = int(START.timestamp())
    todo = make_todo(due_at=START)
    assert render.when(todo) == f"Due <t:{ts}:F> (<t:{ts}:R>)"


def test_when_recurring_with_next_occurrence() -> None:
    ts = int(START.timestamp())
    todo = make_todo(
        kind=TodoKind.RECURRING,
        rule=DailyRule(times=["09:00"]),
        rule_description="Every day at 09:00 (UTC)",
        next_due_at=START,
    )
    assert render.when(todo) == (f"Every day at 09:00 (UTC)\nNext: <t:{ts}:F> (<t:{ts}:R>)")


def test_when_recurring_without_next_occurrence() -> None:
    todo = make_todo(
        kind=TodoKind.RECURRING,
        rule=DailyRule(times=["09:00"]),
        rule_description="Every day at 09:00 (UTC)",
        next_due_at=None,
    )
    assert "nothing scheduled" in render.when(todo)


# --- esc ---------------------------------------------------------------------------------


def test_esc_neutralises_mentions_and_markdown() -> None:
    result = render.esc("@everyone *bold*")
    assert "@everyone" not in result
    assert "\\*bold\\*" in result


# --- replies -----------------------------------------------------------------------------


def test_created_text_personal_has_no_assignees() -> None:
    result = render.created_text(make_todo())
    assert "your personal list" in result
    assert "Assigned" not in result


def test_created_text_server_lists_assignees() -> None:
    todo = make_todo(scope=Scope.SERVER, guild_id=5, assignee_ids=(1, 2))
    result = render.created_text(todo)
    assert "the server list" in result
    assert "Assigned to <@1>, <@2>" in result


def test_done_text_for_finished_one_time_todo() -> None:
    todo = make_todo(status=TodoStatus.DONE)
    assert render.done_text(todo) == "✅ Checked off **Buy milk**."


def test_done_text_for_recurring_todo_shows_next_occurrence() -> None:
    todo = make_todo(
        kind=TodoKind.RECURRING,
        rule=DailyRule(times=["09:00"]),
        rule_description="Every day at 09:00 (UTC)",
        next_due_at=START,
    )
    result = render.done_text(todo)
    assert result.startswith("✅ Checked off **Buy milk**. Next: <t:")


def test_done_text_for_recurring_todo_without_next_occurrence() -> None:
    todo = make_todo(
        kind=TodoKind.RECURRING,
        rule=DailyRule(times=["09:00"]),
        rule_description="Every day at 09:00 (UTC)",
        next_due_at=None,
    )
    assert render.done_text(todo) == "✅ Checked off **Buy milk**."


# --- subtask options ---------------------------------------------------------------------


def test_subtask_option_pages_split_into_selects_of_25() -> None:
    todo = make_todo(subtasks=tuple(sub(i) for i in range(1, 31)))
    pages = render.subtask_option_pages(todo)
    assert [len(page) for page in pages] == [25, 5]


def test_subtask_option_label_is_cut_to_100_chars() -> None:
    todo = make_todo(subtasks=(sub(1, "S" * 100),))
    (option,) = render.subtask_option_pages(todo)[0]
    assert len(option.label) <= 100
    assert option.label.endswith("…")


def test_subtask_option_defaults_and_values() -> None:
    todo = make_todo(subtasks=(sub(1), sub(2, done=True), sub(3, done=True)))
    options = [option for page in render.subtask_option_pages(todo) for option in page]
    assert [option.default for option in options] == [False, True, True]
    assert [option.value for option in options] == ["1", "2", "3"]


# --- list and upcoming -------------------------------------------------------------------


def test_list_embed_server_page_two_of_three() -> None:
    page = Page[TodoView](
        items=[make_todo(id=i, title=f"t{i}") for i in range(10)],
        page=1,
        page_size=10,
        total=25,
    )
    e = render.list_embed(page, Scope.SERVER)

    assert e.title == "Server list"
    assert e.footer.text == "Page 2/3 · 25 open"
    assert e.description is not None
    assert e.description.split("\n")[0].startswith("`11.`")


def test_list_embed_empty_page_with_filter() -> None:
    page = Page[TodoView](items=[], page=0, page_size=10, total=0)
    e = render.list_embed(page, Scope.PERSONAL, "untimed")

    assert e.title == "Your personal list · untimed"
    assert e.description == "Nothing here. Add one with `/todo add`."


def _upcoming(count: int) -> list[UpcomingItem]:
    return [
        UpcomingItem(occurrence_id=100 + i, due_at=START, todo=make_todo(id=i, title=f"t{i}"))
        for i in range(count)
    ]


def test_upcoming_embed_empty_seven_days_has_no_footer() -> None:
    e = render.upcoming_embed([], 7, 25)
    assert e.description == "Nothing due in the next 7 days."
    assert e.footer.text is None


def test_upcoming_embed_empty_one_day_uses_singular() -> None:
    e = render.upcoming_embed([], 1, 25)
    assert e.description == "Nothing due in the next day."


def test_upcoming_embed_full_list_has_limit_footer() -> None:
    e = render.upcoming_embed(_upcoming(25), 7, 25)
    assert e.footer.text == "Showing the first 25."


def test_upcoming_options_labels_and_values() -> None:
    items = [
        UpcomingItem(occurrence_id=100 + i, due_at=START, todo=make_todo(id=i, title=title))
        for i, title in enumerate(["Buy milk", "Walk dog", "Pay rent"])
    ]
    options = render.upcoming_options(items)
    assert [option.label for option in options] == [
        "1. Buy milk",
        "2. Walk dog",
        "3. Pay rent",
    ]
    assert [option.value for option in options] == ["100", "101", "102"]


# --- autocomplete ------------------------------------------------------------------------


def test_autocomplete_label_server_tag() -> None:
    assert render.autocomplete_label("Milk", Scope.SERVER) == "[S] Milk"


def test_autocomplete_label_long_title_is_cut_to_100() -> None:
    label = render.autocomplete_label("x" * 200, Scope.PERSONAL)
    assert label.startswith("[P] ")
    assert len(label) == 100
