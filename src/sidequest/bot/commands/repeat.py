"""`/todo repeat …`: the group, and the four repeating-to-do commands (daily, weekly, monthly by
weekday, monthly by day). Each follows the `/todo add` pattern and creates via
`todos.create_recurring`."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, options
from sidequest.bot.commands import common
from sidequest.bot.commands.common import (
    CREATE_DESCRIPTIONS,
    END_DESCRIPTION,
    START_PLAIN_DESCRIPTION,
    Every,
    Title,
)
from sidequest.bot.options import WeekdayOption, WeekOption
from sidequest.core.recurrence import RecurrenceRule
from sidequest.services import todos
from sidequest.services.actor import Actor
from sidequest.services.dto import TodoView
from sidequest.services.effects import Outcome
from sidequest.services.uow import Uow


def build_repeat_group() -> app_commands.Group:
    """A fresh `/todo repeat` group (fresh command objects, so several clients can coexist)."""
    group = app_commands.Group(name="repeat", description="Add a repeating to-do")
    group.add_command(daily_command())
    group.add_command(weekly_command())
    group.add_command(monthly_weekday_command())
    group.add_command(monthly_day_command())
    return group


async def window[R: RecurrenceRule](
    uow: Uow, actor: Actor, rule: R, start: str | None, end: str | None, tz: str | None
) -> R:
    """`rule` with the `start`/`end` options, as dates in the to-do's zone (D73)."""
    start_date = await adapter.local_date(uow, actor, start, tz) if start else None
    end_date = await adapter.local_date(uow, actor, end, tz) if end else None
    return options.with_window(rule, start_date, end_date)


def daily_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="daily", description="Add a to-do that repeats every day")
    @app_commands.describe(**CREATE_DESCRIPTIONS)
    @app_commands.describe(
        times="24-hour times, comma-separated, e.g. 08:00, 20:00",
        start=START_PLAIN_DESCRIPTION,
        end=END_DESCRIPTION,
    )
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(timezone=autocomplete.timezone, list_=autocomplete.todo_list)
    async def daily(
        interaction: discord.Interaction,
        title: Title,
        times: str,
        timezone: str | None = None,
        assignee: discord.User | None = None,
        assignee2: discord.User | None = None,
        assignee3: discord.User | None = None,
        list_: str | None = None,
        start: str | None = None,
        end: str | None = None,
        details: bool = False,
    ) -> None:
        common.check_options(list_value=list_, date_text=start, timezone=timezone)
        common.check_options(date_text=end)
        rule = options.daily_rule(times)

        async def create(uow: Uow, actor: Actor, title: str, text: str | None) -> Outcome[TodoView]:
            return await todos.create_recurring(
                uow,
                actor,
                list_id=adapter.parse_list_id(list_),
                title=title,
                rule=await window(uow, actor, rule, start, end, timezone),
                details=text,
                timezone=timezone,
                assignee_ids=adapter.user_ids([assignee, assignee2, assignee3]),
            )

        await common.create_flow(interaction, title=title, with_details=details, create=create)

    return daily


def weekly_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(
        name="weekly", description="Add a to-do that repeats on weekdays you pick"
    )
    @app_commands.describe(**CREATE_DESCRIPTIONS)
    @app_commands.describe(
        days="e.g. mon,thu or weekdays / weekend",
        times="24-hour times, comma-separated, e.g. 08:00, 20:00",
        every=common.EVERY_DESCRIPTION,
        start=common.START_DESCRIPTION,
        end=END_DESCRIPTION,
    )
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(timezone=autocomplete.timezone, list_=autocomplete.todo_list)
    async def weekly(
        interaction: discord.Interaction,
        title: Title,
        days: str,
        times: str,
        timezone: str | None = None,
        assignee: discord.User | None = None,
        assignee2: discord.User | None = None,
        assignee3: discord.User | None = None,
        list_: str | None = None,
        every: Every = 1,
        start: str | None = None,
        end: str | None = None,
        details: bool = False,
    ) -> None:
        common.check_options(list_value=list_, date_text=start, timezone=timezone)
        common.check_options(date_text=end)
        rule = options.weekly_rule(days, times, every)

        async def create(uow: Uow, actor: Actor, title: str, text: str | None) -> Outcome[TodoView]:
            return await todos.create_recurring(
                uow,
                actor,
                list_id=adapter.parse_list_id(list_),
                title=title,
                rule=await window(uow, actor, rule, start, end, timezone),
                details=text,
                timezone=timezone,
                assignee_ids=adapter.user_ids([assignee, assignee2, assignee3]),
            )

        await common.create_flow(interaction, title=title, with_details=details, create=create)

    return weekly


def monthly_weekday_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(
        name="monthly-weekday",
        description="Add a to-do for e.g. the first Sunday of every month",
    )
    @app_commands.describe(**CREATE_DESCRIPTIONS)
    @app_commands.describe(
        week="Which week of the month",
        weekday="Day of the week",
        times="24-hour times, comma-separated, e.g. 08:00, 20:00",
        start=START_PLAIN_DESCRIPTION,
        end=END_DESCRIPTION,
    )
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(timezone=autocomplete.timezone, list_=autocomplete.todo_list)
    async def monthly_weekday(
        interaction: discord.Interaction,
        title: Title,
        week: WeekOption,
        weekday: WeekdayOption,
        times: str,
        timezone: str | None = None,
        assignee: discord.User | None = None,
        assignee2: discord.User | None = None,
        assignee3: discord.User | None = None,
        list_: str | None = None,
        start: str | None = None,
        end: str | None = None,
        details: bool = False,
    ) -> None:
        common.check_options(list_value=list_, date_text=start, timezone=timezone)
        common.check_options(date_text=end)
        rule = options.monthly_weekday_rule(week, weekday, times)

        async def create(uow: Uow, actor: Actor, title: str, text: str | None) -> Outcome[TodoView]:
            return await todos.create_recurring(
                uow,
                actor,
                list_id=adapter.parse_list_id(list_),
                title=title,
                rule=await window(uow, actor, rule, start, end, timezone),
                details=text,
                timezone=timezone,
                assignee_ids=adapter.user_ids([assignee, assignee2, assignee3]),
            )

        await common.create_flow(interaction, title=title, with_details=details, create=create)

    return monthly_weekday


def monthly_day_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(
        name="monthly-day", description="Add a to-do for e.g. the 15th of every month"
    )
    @app_commands.describe(**CREATE_DESCRIPTIONS)
    @app_commands.describe(
        day="Day of the month: 1–31 or last (missing days fall back to the month's last day)",
        times="24-hour times, comma-separated, e.g. 08:00, 20:00",
        start=START_PLAIN_DESCRIPTION,
        end=END_DESCRIPTION,
    )
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(timezone=autocomplete.timezone, list_=autocomplete.todo_list)
    async def monthly_day(
        interaction: discord.Interaction,
        title: Title,
        day: str,
        times: str,
        timezone: str | None = None,
        assignee: discord.User | None = None,
        assignee2: discord.User | None = None,
        assignee3: discord.User | None = None,
        list_: str | None = None,
        start: str | None = None,
        end: str | None = None,
        details: bool = False,
    ) -> None:
        common.check_options(list_value=list_, date_text=start, timezone=timezone)
        common.check_options(date_text=end)
        rule = options.monthly_day_rule(day, times)

        async def create(uow: Uow, actor: Actor, title: str, text: str | None) -> Outcome[TodoView]:
            return await todos.create_recurring(
                uow,
                actor,
                list_id=adapter.parse_list_id(list_),
                title=title,
                rule=await window(uow, actor, rule, start, end, timezone),
                details=text,
                timezone=timezone,
                assignee_ids=adapter.user_ids([assignee, assignee2, assignee3]),
            )

        await common.create_flow(interaction, title=title, with_details=details, create=create)

    return monthly_day
