"""Unit tests for reminder messages: render.reminder_pings, reminder_embed and reminder_view."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import discord

from sidequest.bot import render
from sidequest.bot.views.reminder import reminder_view
from sidequest.core.enums import OccurrenceStatus, Scope, TodoKind, TodoStatus
from sidequest.core.recurrence import DailyRule, describe
from sidequest.services.dto import OccurrenceView, SubtaskView, TodoView

START = datetime(2030, 1, 7, 9, 0, tzinfo=UTC)


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
        "due_at": START,
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


def make_occurrence(**overrides: object) -> OccurrenceView:
    defaults: dict[str, object] = {
        "id": 7,
        "todo_id": 1,
        "due_at": START,
        "status": OccurrenceStatus.SENT,
        "late": False,
        "sent_at": START,
        "channel_id": 555,
        "message_id": None,
    }
    return OccurrenceView(**{**defaults, **overrides})


def sub(i: int, title: str = "x") -> SubtaskView:
    return SubtaskView(id=i, position=i, title=title, done=False, done_at=None, done_by=None)


def _field(embed_fields: list[tuple[str, str]], name: str) -> str | None:
    return next((value for field_name, value in embed_fields if field_name == name), None)


def _fields(embed: discord.Embed) -> list[tuple[str, str]]:
    return [(f.name, f.value) for f in embed.fields]


# --- reminder_pings ----------------------------------------------------------------------


def test_server_reminder_pings_every_assignee() -> None:
    todo = make_todo(scope=Scope.SERVER, guild_id=5, assignee_ids=(1, 2))
    assert render.reminder_pings(todo) == "<@1> <@2>"


def test_personal_reminder_has_no_pings() -> None:
    todo = make_todo(scope=Scope.PERSONAL, assignee_ids=())
    assert render.reminder_pings(todo) is None


# --- reminder_embed ----------------------------------------------------------------------


def test_on_time_reminder_shows_due_without_late_note() -> None:
    e = render.reminder_embed(make_todo(), make_occurrence(late=False))

    value = _field(_fields(e), "Due")
    assert value is not None
    assert "<t:" in value
    assert "Late" not in value


def test_late_reminder_says_it_was_due() -> None:
    due = START - timedelta(hours=3)
    e = render.reminder_embed(make_todo(), make_occurrence(due_at=due, late=True))

    value = _field(_fields(e), "Due")
    assert value is not None
    assert "Late — was due" in value


def test_recurring_reminder_shows_repeat_rule() -> None:
    rule = DailyRule(times=["08:00"])
    todo = make_todo(
        kind=TodoKind.RECURRING,
        rule=rule,
        rule_description=describe(rule, ZoneInfo("UTC")),
        due_at=None,
    )
    e = render.reminder_embed(todo, make_occurrence())

    repeats = _field(_fields(e), "Repeats")
    assert repeats == todo.rule_description


def test_one_time_reminder_has_no_repeat_field() -> None:
    e = render.reminder_embed(make_todo(), make_occurrence())

    assert _field(_fields(e), "Repeats") is None


def test_largest_reminder_stays_within_embed_budget() -> None:
    todo = make_todo(
        title="T" * 200,
        details="D" * 4000,
        subtasks=tuple(sub(i, "S" * 100) for i in range(1, 51)),
    )
    e = render.reminder_embed(todo, make_occurrence())

    assert len(e) <= 6000


# --- reminder_view -----------------------------------------------------------------------


async def test_reminder_without_subtasks_has_only_done_button() -> None:
    view = reminder_view(occurrence_id=7, todo=make_todo())

    assert len(view.children) == 1
    assert view.children[0].item.custom_id == "sq:occ:done:7"  # type: ignore[attr-defined]


async def test_reminder_with_30_subtasks_has_two_selects_and_done() -> None:
    todo = make_todo(subtasks=tuple(sub(i) for i in range(1, 31)))
    view = reminder_view(occurrence_id=7, todo=todo)

    assert len(view.children) == 3
    first, second, done = (child.item for child in view.children)  # type: ignore[attr-defined]
    assert first.custom_id == "sq:occ:sub:7:0"
    assert len(first.options) == 25
    assert second.custom_id == "sq:occ:sub:7:1"
    assert len(second.options) == 5
    assert done.custom_id == "sq:occ:done:7"
