"""Unit tests for sidequest.bot.options (slash option values → service arguments)."""

from datetime import date, time

import pytest

from sidequest.bot.options import (
    WeekdayOption,
    WeekOption,
    daily_rule,
    edit_patch,
    edited_rule,
    monthly_day_rule,
    monthly_weekday_rule,
    split_items,
    weekly_rule,
)
from sidequest.core.enums import TodoKind, Weekday
from sidequest.core.errors import InvalidOperation, InvalidTime
from sidequest.core.recurrence import DailyRule, MonthlyDayRule, MonthlyRule, WeeklyRule
from sidequest.services.dto import DueInput
from tests.unit.test_render import START, make_todo

# --- split_items -------------------------------------------------------------------------


def test_split_items_drops_blanks_and_trims() -> None:
    assert split_items("a; b ;;c; ") == ["a", "b", "c"]


def test_split_items_empty_text() -> None:
    assert split_items("") == []


# --- rule builders -----------------------------------------------------------------------


def test_daily_rule_sorts_times() -> None:
    rule = daily_rule("20:00, 08:00")
    assert isinstance(rule, DailyRule)
    assert rule.times == (time(8), time(20))


def test_weekly_rule_sorts_weekdays() -> None:
    rule = weekly_rule("thu,mon", "12:00")
    assert isinstance(rule, WeeklyRule)
    assert rule.weekdays == (Weekday.MON, Weekday.THU)


def test_monthly_weekday_rule_last_sunday() -> None:
    rule = monthly_weekday_rule(WeekOption.Last, WeekdayOption.Sunday, "12:00")
    assert isinstance(rule, MonthlyRule)
    assert rule.week == -1
    assert rule.weekday == Weekday.SUN


def test_monthly_day_rule_last() -> None:
    rule = monthly_day_rule("last", "09:00")
    assert isinstance(rule, MonthlyDayRule)
    assert rule.day == -1


def test_monthly_day_rule_ordinal_suffix() -> None:
    assert monthly_day_rule("31st", "09:00").day == 31


def test_daily_rule_rejects_am_pm() -> None:
    with pytest.raises(InvalidTime):
        daily_rule("9pm")


# --- edited_rule -------------------------------------------------------------------------


def test_edited_rule_replaces_weekdays_and_keeps_times() -> None:
    rule = edited_rule(weekly_rule("mon", "12:00"), days="fri")
    assert isinstance(rule, WeeklyRule)
    assert rule.weekdays == (Weekday.FRI,)
    assert rule.times == (time(12),)


def test_edited_rule_rejects_option_for_other_rule_type() -> None:
    with pytest.raises(InvalidOperation) as info:
        edited_rule(daily_rule("08:00"), days="mon")
    assert "`days`" in info.value.message


def test_edited_rule_nothing_given_returns_none() -> None:
    assert edited_rule(daily_rule("08:00")) is None


def test_edited_rule_replaces_day_of_month() -> None:
    rule = edited_rule(monthly_day_rule("1", "09:00"), day="15")
    assert isinstance(rule, MonthlyDayRule)
    assert rule.day == 15


# --- edit_patch --------------------------------------------------------------------------


def test_edit_patch_rejects_repeat_options_for_one_time_todo() -> None:
    with pytest.raises(InvalidOperation):
        edit_patch(make_todo(), times="10:00")


def test_edit_patch_rejects_date_for_recurring_todo() -> None:
    todo = make_todo(kind=TodoKind.RECURRING, rule=daily_rule("08:00"))
    with pytest.raises(InvalidOperation):
        edit_patch(todo, due=DueInput(time=time(9)))


def test_edit_patch_without_changes_is_an_error() -> None:
    with pytest.raises(InvalidOperation) as info:
        edit_patch(make_todo())
    assert "Nothing to change" in info.value.message


def test_edit_patch_title_only_sets_only_title() -> None:
    patch = edit_patch(make_todo(), title="Buy oat milk")
    assert patch.model_fields_set == {"title"}
    assert patch.title == "Buy oat milk"


def test_edit_patch_timezone_only() -> None:
    patch = edit_patch(make_todo(), timezone="Europe/Amsterdam")
    assert patch.timezone == "Europe/Amsterdam"


def test_edit_patch_recurring_times_become_rule() -> None:
    todo = make_todo(kind=TodoKind.RECURRING, rule=daily_rule("08:00"))
    patch = edit_patch(todo, times="07:00")
    assert patch.rule is not None
    assert patch.rule.times == (time(7),)


# --- date without time keeps wall-clock time ---------------------------------------------


def test_date_only_keeps_current_wall_clock_time() -> None:
    todo = make_todo(due_at=START, timezone="Europe/Amsterdam")
    patch = edit_patch(todo, due=DueInput(date=date(2030, 1, 10)))
    # START is 09:00 UTC, which is 10:00 in Amsterdam in January.
    assert patch.due == DueInput(date=date(2030, 1, 10), time=time(10, 0))


def test_date_only_on_untimed_todo_stays_untimed() -> None:
    todo = make_todo(timezone="Europe/Amsterdam")
    patch = edit_patch(todo, due=DueInput(date=date(2030, 1, 10)))
    assert patch.due == DueInput(date=date(2030, 1, 10))


# --- every N weeks (S9) ---


def test_weekly_rule_every_and_start_default_to_one_and_none() -> None:
    rule = weekly_rule("tue", "07:00")
    assert rule.every == 1
    assert rule.start is None


def test_weekly_rule_takes_every_and_start() -> None:
    rule = weekly_rule("tue", "07:00", every=2, start=date(2026, 11, 3))
    assert rule.every == 2
    assert rule.start == date(2026, 11, 3)


def test_edited_rule_rejects_every_for_other_rule_type() -> None:
    with pytest.raises(InvalidOperation) as info:
        edited_rule(daily_rule("08:00"), every=2)
    assert "`every`" in info.value.message


def test_edited_rule_every_without_start_leaves_start_for_the_service() -> None:
    rule = edited_rule(weekly_rule("mon", "12:00"), every=2)
    assert isinstance(rule, WeeklyRule)
    assert rule.every == 2
    assert rule.start is None


def test_edited_rule_keeps_stored_start_when_changing_every() -> None:
    stored = weekly_rule("mon", "12:00", every=2, start=date(2026, 11, 16))
    rule = edited_rule(stored, every=3)
    assert isinstance(rule, WeeklyRule)
    assert rule.every == 3
    assert rule.start == date(2026, 11, 16)


def test_edited_rule_every_one_keeps_stored_start() -> None:
    stored = weekly_rule("mon", "12:00", every=2, start=date(2026, 11, 16))
    rule = edited_rule(stored, every=1)
    assert isinstance(rule, WeeklyRule)
    assert rule.every == 1
    assert rule.start == date(2026, 11, 16)


def test_edited_rule_start_alone_on_every_one_rule() -> None:
    stored = weekly_rule("mon", "12:00", start=date(2026, 11, 16))
    rule = edited_rule(stored, start=date(2026, 12, 1))
    assert isinstance(rule, WeeklyRule)
    assert rule.start == date(2026, 12, 1)
    assert rule.every == 1


def test_edited_rule_start_alone_on_every_two_rule_keeps_every() -> None:
    stored = weekly_rule("mon", "12:00", every=2, start=date(2026, 11, 16))
    rule = edited_rule(stored, start=date(2026, 12, 1))
    assert isinstance(rule, WeeklyRule)
    assert rule.start == date(2026, 12, 1)
    assert rule.every == 2


def test_edit_patch_rejects_every_for_one_time_todo() -> None:
    with pytest.raises(InvalidOperation) as info:
        edit_patch(make_todo(), every=2)
    assert "`every`" in info.value.message
