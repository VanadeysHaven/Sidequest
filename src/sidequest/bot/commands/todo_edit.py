"""`/todo edit`: title, timing and repeat rule (the rule type itself can't change), and the
week builder for weekly to-dos (`custom-times:true`, D95)."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, options, render, render_week
from sidequest.bot.commands import common
from sidequest.bot.commands.common import Every, Title
from sidequest.bot.options import WeekdayOption, WeekOption
from sidequest.bot.views.week_builder import WeekBuilderView
from sidequest.core.errors import Forbidden
from sidequest.core.recurrence import WeeklyRule, WeekTimes, with_week
from sidequest.core.text import bold
from sidequest.services import todos
from sidequest.services.dto import TodoPatch, TodoView


def edit_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="edit", description="Change a to-do's title, time or repeat rule")
    @app_commands.describe(
        todo="The to-do",
        title="New title",
        date="One-time: new date or a weekday (keeps the time if you give none)",
        time="One-time: new 24-hour time, e.g. 14:30",
        times="Repeating: new times, e.g. 08:00, 20:00",
        days="Weekly: new weekdays, e.g. mon,thu or all",
        week="Monthly (weekday): which week",
        weekday="Monthly (weekday): which day",
        day="Monthly (day): 1–31 or last",
        every=f"Weekly: {common.EVERY_DESCRIPTION}",
        start=common.EDIT_START_DESCRIPTION,
        end=common.EDIT_END_DESCRIPTION,
        timezone="New timezone (keeps the same wall-clock time)",
        custom_times="Weekly: change the week, with different times per day",
    )
    @app_commands.rename(custom_times="custom-times")
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
        end: str | None = None,
        timezone: str | None = None,
        custom_times: bool = False,
    ) -> None:
        common.check_options(date_text=date, time_text=time, timezone=timezone)
        common.check_options(date_text=start)
        common.check_options(date_text=end)
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        todo_id = adapter.parse_id(todo)
        async with adapter.uows(interaction)() as uow:
            current = await todos.get(uow, actor, todo_id)
            zone = timezone or current.timezone
            due = None
            if date or time:
                due = await adapter.due_input(uow, actor, date, time, zone)
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
                start=await adapter.edit_date(uow, actor, start, zone),
                end=await adapter.edit_date(uow, actor, end, zone),
                custom_times=custom_times,
            )
            if not custom_times:
                out = await todos.edit(uow, actor, todo_id, patch)
                notes = await adapter.collect_notes(uow, actor.user_id)
        if custom_times:
            await _open_week_builder(interaction, current, patch, zone)
            return
        view = await adapter.apply(interaction, out)
        await adapter.reply(interaction, _updated_text(view), notes=notes)

    return edit


def _updated_text(todo: TodoView) -> str:
    return f"✏️ Updated **{render.esc(todo.title)}**.\n{render.when(todo)}"


async def _open_week_builder(
    interaction: discord.Interaction, current: TodoView, patch: TodoPatch, zone: str
) -> None:
    """The week builder with the to-do's week (D95). The other options in `patch` (title,
    timezone, every, start, end) are applied together with the new week on Save."""
    if not current.can_edit:  # refuse before the week is built, not on Save
        raise Forbidden(
            f"Only the owner and collaborators of {bold(current.list_name)} "
            "(or someone with Manage Server) can change its to-dos."
        )
    rule = patch.rule
    assert isinstance(rule, WeeklyRule)  # edit_patch refuses custom-times on other types
    fields = {name: getattr(patch, name) for name in patch.model_fields_set}

    async def save(
        save_interaction: discord.Interaction, new_rule: WeeklyRule, title: str, text: str | None
    ) -> str:
        actor = adapter.actor_from(save_interaction)
        changes = TodoPatch(**{**fields, "rule": new_rule})
        async with adapter.uows(save_interaction)() as uow:
            out = await todos.edit(uow, actor, current.id, changes)
            notes = await adapter.collect_notes(uow, actor.user_id)
        todo = await adapter.apply(save_interaction, out)
        return adapter.with_notes(notes, _updated_text(todo)) or ""

    def make_rule(week: WeekTimes) -> WeeklyRule:
        return with_week(rule, week)

    view = WeekBuilderView(
        interaction.user.id,
        title=patch.title or current.title,
        week=rule.week,
        tz=zone,
        make_rule=make_rule,
        save=save,
        cancel_text=render_week.NOTHING_CHANGED,
        every=rule.every,
        start=rule.start,
        end=rule.end,
    )
    view.interaction = interaction
    await adapter.reply(interaction, embed=view.embed(), view=view)
