"""Unit tests for sidequest.bot.render (pure: DTOs in, text/embeds/options out)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sidequest.bot import render
from sidequest.core.enums import TodoKind, TodoStatus
from sidequest.core.recurrence import DailyRule, describe
from sidequest.services.dto import ListView, Page, SubtaskView, TodoView, UpcomingItem

START = datetime(2030, 1, 7, 9, 0, tzinfo=UTC)

OPEN_MARK = "☐"
DONE_MARK = "☑"


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


def make_list(**overrides: object) -> ListView:
    defaults: dict[str, object] = {
        "id": 1,
        "guild_id": 5,
        "name": "Groceries",
        "owner_id": 10,
        "collaborator_ids": (),
        "is_fallback": False,
        "is_my_default": False,
        "open_count": 0,
        "can_manage": True,
        "can_rename": True,
        "can_add": True,
    }
    return ListView(**{**defaults, **overrides})


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


def test_todo_embed_title_is_the_plain_title() -> None:
    e = render.todo_embed(make_todo())

    assert e.title == "Buy milk"


def test_todo_embed_footer_names_the_list() -> None:
    e = render.todo_embed(make_todo(list_name="Chores"))

    assert e.footer.text == "List: Chores"


def test_todo_embed_shows_assignees_field() -> None:
    e = render.todo_embed(make_todo(assignee_ids=(1, 2)))

    fields = {f.name: f.value for f in e.fields}
    assert fields["Assignees"] == "<@1>, <@2>"


def test_todo_embed_without_assignees_has_no_assignees_field() -> None:
    e = render.todo_embed(make_todo())

    assert all(f.name != "Assignees" for f in e.fields)


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


def test_created_text_names_the_list() -> None:
    result = render.created_text(make_todo())
    assert result.split("\n")[0] == "✅ Added **Buy milk** to **Groceries**."
    assert "Assigned" not in result


def test_created_text_lists_assignees() -> None:
    result = render.created_text(make_todo(assignee_ids=(1, 2)))
    assert "Assigned to <@1>, <@2>" in result


def test_created_text_escapes_title_and_list_name() -> None:
    result = render.created_text(make_todo(title="*Milk*", list_name="*Chores*"))
    assert result.split("\n")[0] == "✅ Added **\\*Milk\\*** to **\\*Chores\\***."


def test_moved_text_names_the_list() -> None:
    assert render.moved_text(make_todo()) == "📦 Moved **Buy milk** to **Groceries**."


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


def test_list_embed_page_two_of_three() -> None:
    page = Page[TodoView](
        items=[make_todo(id=i, title=f"t{i}") for i in range(10)],
        page=1,
        page_size=10,
        total=25,
    )
    e = render.list_embed(page, "Groceries")

    assert e.title == "Groceries"
    assert e.footer.text == "Page 2/3 · 25 open"
    assert e.description is not None
    assert e.description.split("\n")[0].startswith("`11.`")


def test_list_embed_empty_page_with_filter() -> None:
    page = Page[TodoView](items=[], page=0, page_size=10, total=0)
    e = render.list_embed(page, "Groceries", "untimed")

    assert e.title == "Groceries · untimed"
    assert e.description == "Nothing here. Add one with `/todo add`."


def test_list_embed_timed_filter_suffix() -> None:
    page = Page[TodoView](items=[], page=0, page_size=10, total=0)
    e = render.list_embed(page, "Groceries", "timed")

    assert e.title == "Groceries · timed"


def test_list_embed_escapes_list_name_markdown() -> None:
    page = Page[TodoView](items=[], page=0, page_size=10, total=0)
    e = render.list_embed(page, "*Groceries*")

    assert e.title == "\\*Groceries\\*"


def _upcoming(count: int) -> list[UpcomingItem]:
    return [
        UpcomingItem(occurrence_id=100 + i, due_at=START, todo=make_todo(id=i, title=f"t{i}"))
        for i in range(count)
    ]


def test_upcoming_embed_empty_seven_days_has_no_footer() -> None:
    e = render.upcoming_embed([], "Groceries", 7, 25)
    assert e.description == "Nothing due in the next 7 days."
    assert e.footer.text is None


def test_upcoming_embed_title_names_the_list_and_period() -> None:
    e = render.upcoming_embed([], "Groceries", 7, 25)
    assert e.title == "Groceries · upcoming, next 7 days"


def test_upcoming_embed_empty_one_day_uses_singular() -> None:
    e = render.upcoming_embed([], "Groceries", 1, 25)
    assert e.description == "Nothing due in the next day."
    assert e.title == "Groceries · upcoming, next day"


def test_upcoming_embed_full_list_has_limit_footer() -> None:
    e = render.upcoming_embed(_upcoming(25), "Groceries", 7, 25)
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


def test_upcoming_options_skip_items_the_viewer_cannot_complete() -> None:
    items = [
        UpcomingItem(occurrence_id=100, due_at=START, todo=make_todo(id=1, title="Buy milk")),
        UpcomingItem(
            occurrence_id=101,
            due_at=START,
            todo=make_todo(id=2, title="Walk dog", can_complete=False),
        ),
        UpcomingItem(occurrence_id=102, due_at=START, todo=make_todo(id=3, title="Pay rent")),
    ]
    options = render.upcoming_options(items)
    assert [option.label for option in options] == ["1. Buy milk", "3. Pay rent"]
    assert [option.value for option in options] == ["100", "102"]


# --- autocomplete ------------------------------------------------------------------------


def test_autocomplete_label_names_the_list() -> None:
    assert render.autocomplete_label("Milk", "Groceries") == "[Groceries] Milk"


def test_autocomplete_label_cuts_list_name_to_30_chars() -> None:
    label = render.autocomplete_label("Milk", "A" * 40)
    assert label == f"[{'A' * 29}…] Milk"


def test_autocomplete_label_long_title_is_cut_to_100() -> None:
    label = render.autocomplete_label("x" * 200, "Groceries")
    assert label.startswith("[Groceries] ")
    assert len(label) == 100
    assert label.endswith("…")


# --- lists -------------------------------------------------------------------------------


def test_lists_embed_fallback_list_is_open_to_everyone() -> None:
    fallback = make_list(
        id=1,
        name="Default List",
        owner_id=None,
        is_fallback=True,
        open_count=3,
        can_manage=False,
        can_rename=False,
    )
    e = render.lists_embed([fallback])

    assert e.title == "Lists"
    assert e.description == "**Default List** (server default) — open to everyone · 3 open"


def test_lists_embed_owned_list_shows_owner_collaborators_and_open_count() -> None:
    owned = make_list(
        id=2,
        name="Chores",
        owner_id=10,
        collaborator_ids=(11, 12),
        open_count=2,
        is_my_default=True,
    )
    e = render.lists_embed([owned])

    assert e.description == "**Chores** (your default) — owner <@10> · 2 collaborator(s) · 2 open"


def test_lists_embed_empty() -> None:
    assert render.lists_embed([]).description == "No lists yet."


def test_collaborators_text_with_collaborators() -> None:
    lst = make_list(name="Chores", collaborator_ids=(11, 12))
    assert render.collaborators_text(lst) == "👥 **Chores** now has 2 collaborator(s): <@11>, <@12>"


def test_collaborators_text_without_collaborators() -> None:
    lst = make_list(name="Chores", collaborator_ids=())
    assert render.collaborators_text(lst) == "👥 **Chores** now has 0 collaborator(s): nobody yet"


def test_list_options_labels_and_values() -> None:
    options = render.list_options(
        [make_list(id=1, name="Default List"), make_list(id=2, name="Chores")]
    )
    assert [option.label for option in options] == ["Default List", "Chores"]
    assert [option.value for option in options] == ["1", "2"]


def test_list_options_cut_long_names_to_100() -> None:
    (option,) = render.list_options([make_list(id=1, name="N" * 150)])
    assert len(option.label) == 100
    assert option.label.endswith("…")


# --- undo and check-off prompt -----------------------------------------------------------


def test_undone_text_without_channel() -> None:
    assert render.undone_text(make_todo()) == "↩️ Undone: **Buy milk** is open again."


def test_undone_text_names_the_reminder_channel() -> None:
    assert render.undone_text(make_todo(), channel_id=42) == (
        "↩️ Undone: **Buy milk** is open again. The reminder is back in <#42>."
    )


def test_undone_text_escapes_title() -> None:
    title = "*x* @everyone"
    assert render.undone_text(make_todo(title=title)) == (
        f"↩️ Undone: **{render.esc(title)}** is open again."
    )


def test_and_join_parts() -> None:
    cases = [
        ([], ""),
        (["A"], "A"),
        (["A", "B"], "A and B"),
        (["A", "B", "C"], "A, B and C"),
    ]
    for parts, expected in cases:
        assert render.and_join(parts) == expected, parts


def test_check_off_prompt_one_assignee() -> None:
    todo = make_todo(title="t", assignee_ids=(5,))
    assert (
        render.check_off_prompt(todo) == "**t** is assigned to <@5>, not you. Check it off anyway?"
    )


def test_check_off_prompt_two_assignees() -> None:
    todo = make_todo(title="t", assignee_ids=(5, 6))
    assert render.check_off_prompt(todo) == (
        "**t** is assigned to <@5> and <@6>, not you. Check it off anyway?"
    )


def test_check_off_prompt_three_assignees() -> None:
    todo = make_todo(title="t", assignee_ids=(5, 6, 7))
    assert render.check_off_prompt(todo) == (
        "**t** is assigned to <@5>, <@6> and <@7>, not you. Check it off anyway?"
    )


def test_check_off_prompt_escapes_title() -> None:
    title = "*x* @everyone"
    todo = make_todo(title=title, assignee_ids=(5,))
    assert render.check_off_prompt(todo) == (
        f"**{render.esc(title)}** is assigned to <@5>, not you. Check it off anyway?"
    )


def test_undo_options_newest_first_with_index_values() -> None:
    options = render.undo_options(["a", "b", "c"])
    assert [option.label for option in options] == ["1. c", "2. b", "3. a"]
    assert [option.value for option in options] == ["2", "1", "0"]


def test_undo_options_capped_at_25_newest() -> None:
    titles = [f"t{i}" for i in range(30)]
    options = render.undo_options(titles)
    assert len(options) == 25
    assert options[0].label.startswith("1. ")
    assert options[0].value == "29"


def test_undo_options_long_title_is_cut_to_100() -> None:
    (option,) = render.undo_options(["x" * 150])
    assert len(option.label) == 100
    assert option.label.endswith("…")
