"""The week builder (D92–D95): different times per weekday for `/todo repeat weekly
custom-times:true` and `/todo edit custom-times:true`.

One ephemeral message: the week embed, **Set times for…** (multi-select; closing it opens
the times modal for the picked days), **Turn days off…** (multi-select), **Save**,
**Cancel** (D93, changed after Tim's test: a separate Set times button needed two clicks,
because Discord only sends a multi-select when it closes, and the click that closes it
doesn't reach the button). The week lives in the view's memory; nothing is stored until
Save, which hands the rule to the command's `save` callback.
"""

import contextlib
from collections.abc import Awaitable, Callable
from datetime import date, time

import discord

from sidequest.bot import adapter, render_week
from sidequest.bot.views.base import BaseModal, BaseView
from sidequest.bot.views.modals import CreateWithDetailsModal
from sidequest.core.enums import Weekday
from sidequest.core.errors import InvalidOperation
from sidequest.core.recurrence import WeeklyRule, WeekTimes
from sidequest.core.timeparse import parse_times

WEEK_BUILDER_TIMEOUT = 870
"""14.5 minutes without a click (D94: "15 minutes"). Discord's interaction tokens last 15
minutes, so the expired text must go out a little earlier to still reach the message."""

type MakeRule = Callable[[WeekTimes], WeeklyRule]
"""The week → the full rule (the command's every/start/end, the to-do's suspensions)."""
type Save = Callable[[discord.Interaction, WeeklyRule, str, str | None], Awaitable[str]]
"""Saves the rule (the interaction is deferred; title and details for a create) and returns
the text that replaces the builder."""


class WeekBuilderView(BaseView):
    """Owner-only. `ask_details`: Save first opens the details form (`details:true`)."""

    def __init__(
        self,
        owner_id: int,
        *,
        title: str,
        week: WeekTimes,
        tz: str,
        make_rule: MakeRule,
        save: Save,
        cancel_text: str,
        every: int = 1,
        start: date | None = None,
        end: date | None = None,
        ask_details: bool = False,
    ) -> None:
        super().__init__(owner_id)
        self.timeout = WEEK_BUILDER_TIMEOUT
        self.todo_title = title
        self.week: WeekTimes = dict(week)
        self.tz = tz
        self.every, self.start, self.end = every, start, end
        self.interaction: discord.Interaction | None = None
        """The latest interaction on the message: its token can still edit it on timeout."""
        self._make_rule = make_rule
        self._save = save
        self._cancel_text = cancel_text
        self._ask_details = ask_details
        self._refresh()

    # --- rendering -----------------------------------------------------------------------

    def embed(self) -> discord.Embed:
        return render_week.week_embed(
            self.todo_title, self.week, self.tz, every=self.every, start=self.start, end=self.end
        )

    def _refresh(self) -> None:
        """New select options (nothing picked: the selection resets after a change)."""
        self.times_select.options = render_week.day_options(self.week)
        self.off_select.options = render_week.day_options(self.week)

    async def show(self, interaction: discord.Interaction) -> None:
        """Re-render the builder in response to `interaction` (a click or the times modal)."""
        self._refresh()
        self.interaction = interaction
        await interaction.response.edit_message(
            embed=self.embed(), view=self, allowed_mentions=adapter.NO_MENTIONS
        )

    def set_times(self, days: list[Weekday], times: tuple[time, ...]) -> None:
        for day in days:
            self.week[day] = tuple(times)
        self.week = dict(sorted(self.week.items(), key=lambda item: item[0].index))

    @staticmethod
    def _picked(select: discord.ui.Select["WeekBuilderView"]) -> list[Weekday]:
        return sorted({Weekday(v) for v in select.values}, key=lambda d: d.index)

    # --- components ----------------------------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        allowed = await super().interaction_check(interaction)
        if allowed:
            self.interaction = interaction
        return allowed

    @discord.ui.select(
        placeholder=render_week.TIMES_SELECT_PLACEHOLDER, min_values=1, max_values=7, row=0
    )
    async def times_select(
        self, interaction: discord.Interaction, select: discord.ui.Select["WeekBuilderView"]
    ) -> None:
        await interaction.response.send_modal(TimesModal(self, self._picked(select)))

    @discord.ui.select(
        placeholder=render_week.OFF_SELECT_PLACEHOLDER, min_values=1, max_values=7, row=1
    )
    async def off_select(
        self, interaction: discord.Interaction, select: discord.ui.Select["WeekBuilderView"]
    ) -> None:
        for day in self._picked(select):
            self.week.pop(day, None)
        await self.show(interaction)

    @discord.ui.button(label="Save", style=discord.ButtonStyle.success, row=2)
    async def save_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["WeekBuilderView"]
    ) -> None:
        if not self.week:
            raise InvalidOperation(render_week.EMPTY_WEEK)
        rule = self._make_rule(self.week)  # refuses a broken rule before any form opens
        if not self._ask_details:
            await self._finish(interaction, rule, self.todo_title, None)
            return

        async def submit(
            modal_interaction: discord.Interaction, title: str, details: str | None
        ) -> None:
            await self._finish(modal_interaction, rule, title, details)

        await interaction.response.send_modal(CreateWithDetailsModal(self.todo_title, submit))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["WeekBuilderView"]
    ) -> None:
        await interaction.response.edit_message(content=self._cancel_text, embed=None, view=None)
        self.stop()

    async def _finish(
        self, interaction: discord.Interaction, rule: WeeklyRule, title: str, details: str | None
    ) -> None:
        """Save, then replace the builder with the reply. A refusal keeps the builder."""
        if self.is_finished():  # expired while the details form was open
            raise InvalidOperation(render_week.EXPIRED)
        await interaction.response.defer()  # edits the builder message
        text = await self._save(interaction, rule, title, details)
        await interaction.edit_original_response(
            content=text, embed=None, view=None, allowed_mentions=adapter.NO_MENTIONS
        )
        self.stop()

    async def on_timeout(self) -> None:
        if self.interaction is None:
            return
        # The token may have expired after all, or the message been dismissed.
        with contextlib.suppress(discord.HTTPException):
            await self.interaction.edit_original_response(
                content=render_week.EXPIRED, embed=None, view=None
            )


class TimesModal(BaseModal):
    """The modal "Times for Mon, Wed and Thu": one field, prefilled when the picked days
    share times."""

    def __init__(self, builder: WeekBuilderView, days: list[Weekday]) -> None:
        super().__init__(title=render_week.times_modal_title(days))
        self.builder = builder
        self.days = days
        shared = render_week.shared_times(builder.week, days)
        self.times_input: discord.ui.TextInput[TimesModal] = discord.ui.TextInput(
            label="Times (24-hour, comma-separated)",
            default=render_week.times_text(shared) if shared else None,
            placeholder=render_week.TIMES_PLACEHOLDER,
            max_length=100,
        )
        self.add_item(self.times_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if self.builder.is_finished():
            raise InvalidOperation(render_week.EXPIRED)
        times = tuple(parse_times(self.times_input.value))
        self.builder.set_times(self.days, times)
        await self.builder.show(interaction)
