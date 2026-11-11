"""`/todo repeat …`: the group, and the four repeating-to-do commands (daily, weekly, monthly by
weekday, monthly by day). Each follows the `/todo add` pattern and creates via
`todos.create_recurring`."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, options
from sidequest.bot.adapter import ScopeOption
from sidequest.bot.commands import common
from sidequest.bot.commands.common import CREATE_DESCRIPTIONS, Title
from sidequest.bot.options import WeekdayOption, WeekOption
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


def daily_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="daily", description="Add a to-do that repeats every day")
    @app_commands.describe(**CREATE_DESCRIPTIONS)
    @app_commands.describe(times="24-hour times, comma-separated, e.g. 08:00, 20:00")
    @app_commands.autocomplete(timezone=autocomplete.timezone)
    async def daily(
        interaction: discord.Interaction,
        title: Title,
        times: str,
        timezone: str | None = None,
        assignee: discord.User | None = None,
        assignee2: discord.User | None = None,
        assignee3: discord.User | None = None,
        scope: ScopeOption | None = None,
        details: bool = False,
    ) -> None:
        common.check_options(interaction=interaction, scope=scope, timezone=timezone)
        rule = options.daily_rule(times)

        async def create(uow: Uow, actor: Actor, title: str, text: str | None) -> Outcome[TodoView]:
            return await todos.create_recurring(
                uow,
                actor,
                scope=adapter.resolve_scope(actor, scope),
                title=title,
                rule=rule,
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
    )
    @app_commands.autocomplete(timezone=autocomplete.timezone)
    async def weekly(
        interaction: discord.Interaction,
        title: Title,
        days: str,
        times: str,
        timezone: str | None = None,
        assignee: discord.User | None = None,
        assignee2: discord.User | None = None,
        assignee3: discord.User | None = None,
        scope: ScopeOption | None = None,
        details: bool = False,
    ) -> None:
        common.check_options(interaction=interaction, scope=scope, timezone=timezone)
        rule = options.weekly_rule(days, times)

        async def create(uow: Uow, actor: Actor, title: str, text: str | None) -> Outcome[TodoView]:
            return await todos.create_recurring(
                uow,
                actor,
                scope=adapter.resolve_scope(actor, scope),
                title=title,
                rule=rule,
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
    )
    @app_commands.autocomplete(timezone=autocomplete.timezone)
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
        scope: ScopeOption | None = None,
        details: bool = False,
    ) -> None:
        common.check_options(interaction=interaction, scope=scope, timezone=timezone)
        rule = options.monthly_weekday_rule(week, weekday, times)

        async def create(uow: Uow, actor: Actor, title: str, text: str | None) -> Outcome[TodoView]:
            return await todos.create_recurring(
                uow,
                actor,
                scope=adapter.resolve_scope(actor, scope),
                title=title,
                rule=rule,
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
    )
    @app_commands.autocomplete(timezone=autocomplete.timezone)
    async def monthly_day(
        interaction: discord.Interaction,
        title: Title,
        day: str,
        times: str,
        timezone: str | None = None,
        assignee: discord.User | None = None,
        assignee2: discord.User | None = None,
        assignee3: discord.User | None = None,
        scope: ScopeOption | None = None,
        details: bool = False,
    ) -> None:
        common.check_options(interaction=interaction, scope=scope, timezone=timezone)
        rule = options.monthly_day_rule(day, times)

        async def create(uow: Uow, actor: Actor, title: str, text: str | None) -> Outcome[TodoView]:
            return await todos.create_recurring(
                uow,
                actor,
                scope=adapter.resolve_scope(actor, scope),
                title=title,
                rule=rule,
                details=text,
                timezone=timezone,
                assignee_ids=adapter.user_ids([assignee, assignee2, assignee3]),
            )

        await common.create_flow(interaction, title=title, with_details=details, create=create)

    return monthly_day
