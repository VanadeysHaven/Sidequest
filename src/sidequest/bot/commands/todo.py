"""`/todo …`: the group, and `/todo add` (the reference pattern for create commands)."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete
from sidequest.bot.commands import common, todo_edit, todo_list, todo_manage, todo_view
from sidequest.bot.commands.common import CREATE_DESCRIPTIONS, Title
from sidequest.bot.commands.repeat import build_repeat_group
from sidequest.bot.commands.subtask import build_subtask_group
from sidequest.services import todos
from sidequest.services.actor import Actor
from sidequest.services.dto import TodoView
from sidequest.services.effects import Outcome
from sidequest.services.uow import Uow


def build_todo_group() -> app_commands.Group:
    """A fresh `/todo` group (fresh command objects, so several clients can coexist)."""
    group = app_commands.Group(
        name="todo",
        description="Your to-dos",
        allowed_installs=common.GUILD_INSTALLS,
        allowed_contexts=common.GUILD_CONTEXTS,
    )
    for command in (
        add_command(),
        todo_list.list_command(),
        todo_view.upcoming_command(),
        todo_view.show_command(),
        *todo_manage.commands(),
        todo_edit.edit_command(),
    ):
        group.add_command(command)
    group.add_command(build_repeat_group())
    group.add_command(build_subtask_group())
    return group


def add_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="add", description="Add a one-time to-do")
    @app_commands.describe(**CREATE_DESCRIPTIONS)
    @app_commands.describe(
        date="YYYY-MM-DD, DD-MM-YYYY, today or tomorrow (needs a time)",
        time="24-hour time, e.g. 14:30 (without a date: the next 14:30)",
    )
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(timezone=autocomplete.timezone, list_=autocomplete.todo_list)
    async def add(
        interaction: discord.Interaction,
        title: Title,
        date: str | None = None,
        time: str | None = None,
        timezone: str | None = None,
        assignee: discord.User | None = None,
        assignee2: discord.User | None = None,
        assignee3: discord.User | None = None,
        list_: str | None = None,
        details: bool = False,
    ) -> None:
        common.check_options(list_value=list_, date_text=date, time_text=time, timezone=timezone)

        async def create(uow: Uow, actor: Actor, title: str, text: str | None) -> Outcome[TodoView]:
            return await todos.create_once(
                uow,
                actor,
                list_id=adapter.parse_list_id(list_),
                title=title,
                details=text,
                due=await adapter.due_input(uow, actor, date, time, timezone),
                timezone=timezone,
                assignee_ids=adapter.user_ids([assignee, assignee2, assignee3]),
            )

        await common.create_flow(interaction, title=title, with_details=details, create=create)

    return add
