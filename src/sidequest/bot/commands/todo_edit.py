"""`/todo edit`: title, timing and repeat rule (the rule type itself can't change)."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, options, render
from sidequest.bot.commands import common
from sidequest.bot.commands.common import Every, Title
from sidequest.bot.options import WeekdayOption, WeekOption
from sidequest.services import todos


def edit_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="edit", description="Change a to-do's title, time or repeat rule")
    @app_commands.describe(
        todo="The to-do",
        title="New title",
        date="One-time: new date (keeps the time if you give none)",
        time="One-time: new 24-hour time, e.g. 14:30",
        times="Repeating: new times, e.g. 08:00, 20:00",
        days="Weekly: new weekdays, e.g. mon,thu",
        week="Monthly (weekday): which week",
        weekday="Monthly (weekday): which day",
        day="Monthly (day): 1–31 or last",
        every=f"Weekly: {common.EVERY_DESCRIPTION}",
        start=f"Weekly: {common.START_DESCRIPTION}",
        timezone="New timezone (keeps the same wall-clock time)",
    )
    @app_commands.autocomplete(todo=autocomplete.todo, timezone=autocomplete.timezone)
    async def edit(
        interaction: discord.Interaction,
        todo: str,
        title: Title | None = None,
        date: str | None = None,
        time: str | None = None,
        times: str | None = None,
        days: str | None = None,
        week: WeekOption | None = None,
        weekday: WeekdayOption | None = None,
        day: str | None = None,
        every: Every | None = None,
        start: str | None = None,
        timezone: str | None = None,
    ) -> None:
        common.check_options(date_text=date, time_text=time, timezone=timezone)
        common.check_options(date_text=start)
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        todo_id = adapter.parse_id(todo)
        async with adapter.uows(interaction)() as uow:
            current = await todos.get(uow, actor, todo_id)
            zone = timezone or current.timezone
            due = None
            if date or time:
                due = await adapter.due_input(uow, actor, date, time, zone)
            start_date = await adapter.local_date(uow, actor, start, zone) if start else None
            patch = options.edit_patch(
                current,
                title=title,
                due=due,
                timezone=timezone,
                times=times,
                days=days,
                week=week,
                weekday=weekday,
                day=day,
                every=every,
                start=start_date,
            )
            out = await todos.edit(uow, actor, todo_id, patch)
            notes = await adapter.collect_notes(uow, actor.user_id)
        view = await adapter.apply(interaction, out)
        await adapter.reply(
            interaction,
            f"✏️ Updated **{render.esc(view.title)}**.\n{render.when(view)}",
            notes=notes,
        )

    return edit
