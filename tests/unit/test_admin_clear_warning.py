"""Tests for the warning shown before unsetting the reminder channel (`/channel clear`)."""

from sidequest.bot.commands.admin import clear_warning

CHANNEL = 555


def test_warning_without_scheduled_todos_names_the_channel_only() -> None:
    text = clear_warning(CHANNEL, 0)
    assert f"<#{CHANNEL}>" in text
    assert "stop reminding" not in text
    assert "Reminders already posted stay" in text


def test_warning_with_one_scheduled_todo_uses_singular() -> None:
    text = clear_warning(CHANNEL, 1)
    assert "**1** timed server to-do will stop reminding" in text
    assert "Reminders already posted stay" in text


def test_warning_with_several_scheduled_todos_uses_plural() -> None:
    text = clear_warning(CHANNEL, 3)
    assert "**3** timed server to-dos will stop reminding" in text
    assert "Reminders already posted stay" in text
