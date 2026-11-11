"""Pure rendering: service DTOs → message text, embeds and select options.

No I/O here, so S6 (reminders) can reuse it and tests can check the output directly.
Points in time only via `core.discord_time` (C5). User text is escaped.
"""

from collections.abc import Sequence

import discord

from sidequest.core.discord_time import ts, ts_due
from sidequest.core.enums import Scope, TodoKind, TodoStatus
from sidequest.core.limits import (
    EMBED_DESCRIPTION_MAX,
    EMBEDS_TOTAL_MAX,
    SELECT_LABEL_MAX,
    SELECT_OPTIONS_MAX,
)
from sidequest.services.dto import (
    ListFilter,
    OccurrenceView,
    Page,
    SubtaskView,
    TodoView,
    UpcomingItem,
)

EMBED_TITLE_MAX = 256
FIELD_VALUE_MAX = 1024
CONTINUED = "​"  # field name for continuation fields (names can't be empty)
DONE_MARK = "☑"
OPEN_MARK = "☐"


# --- text helpers ------------------------------------------------------------------------


def cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def esc(text: str) -> str:
    """User text for inline use: no markdown, no mentions."""
    return discord.utils.escape_markdown(discord.utils.escape_mentions(text))


def scope_tag(scope: Scope) -> str:
    return "[S]" if scope == Scope.SERVER else "[P]"


def list_name(scope: Scope) -> str:
    return "the server list" if scope == Scope.SERVER else "your personal list"


def mentions(user_ids: Sequence[int]) -> str:
    """Mentions render as names; command replies send them with no pings."""
    return ", ".join(f"<@{user_id}>" for user_id in user_ids)


def when(todo: TodoView) -> str:
    """Due time, repeat rule + next occurrence, or "No reminder"."""
    if todo.kind == TodoKind.RECURRING:
        nxt = ts_due(todo.next_due_at) if todo.next_due_at else "nothing scheduled"
        return f"{todo.rule_description}\nNext: {nxt}"
    if todo.due_at is not None:
        return f"Due {ts_due(todo.due_at)}"
    return "No reminder (untimed)"


def short_when(todo: TodoView) -> str:
    """One-line timing for list rows."""
    if todo.kind == TodoKind.RECURRING:
        if todo.next_due_at is None:
            return "🔁 nothing scheduled"
        return f"🔁 {ts(todo.next_due_at, 'f')} ({ts(todo.next_due_at, 'R')})"
    if todo.due_at is not None:
        return f"{ts(todo.due_at, 'f')} ({ts(todo.due_at, 'R')})"
    return "no reminder"


def autocomplete_label(title: str, scope: Scope) -> str:
    """`[S] title` / `[P] title`, cut to Discord's 100-char choice name limit."""
    return cut(f"{scope_tag(scope)} {title}", SELECT_LABEL_MAX)


# --- replies -----------------------------------------------------------------------------


def created_text(todo: TodoView) -> str:
    lines = [f"✅ Added **{esc(todo.title)}** to {list_name(todo.scope)}.", when(todo)]
    if todo.scope == Scope.SERVER:
        lines.append(f"Assigned to {mentions(todo.assignee_ids)}")
    return "\n".join(lines)


def done_text(todo: TodoView) -> str:
    """The reply after checking something off (same wording everywhere, D37)."""
    text = f"✅ Checked off **{esc(todo.title)}**."
    if todo.kind == TodoKind.RECURRING and todo.next_due_at is not None:
        text += f" Next: {ts_due(todo.next_due_at)}"
    return text


# --- detail embed ------------------------------------------------------------------------


def subtask_line(number: int, sub: SubtaskView) -> str:
    return f"{DONE_MARK if sub.done else OPEN_MARK} {number}. {esc(sub.title)}"


def _subtask_fields(subtasks: Sequence[SubtaskView], budget: int) -> list[tuple[str, str]]:
    """As many subtask lines as fit in `budget` characters (field names included), packed
    into fields of ≤ 1024 chars, then "… and N more"."""
    if not subtasks:
        return []
    done = sum(s.done for s in subtasks)
    first_name = f"Subtasks ({done}/{len(subtasks)} done)"
    more_room = len(CONTINUED) + len(f"\n… and {len(subtasks)} more")
    budget -= more_room

    fields: list[list[str]] = []
    cost = len(first_name)
    for number, sub in enumerate(subtasks, start=1):
        line = subtask_line(number, sub)
        current = fields[-1] if fields else None
        fits_field = current is not None and len("\n".join([*current, line])) <= FIELD_VALUE_MAX
        extra = len(line) + 1 if fits_field else len(line) + (len(CONTINUED) if fields else 0)
        if cost + extra > budget:
            break
        if fits_field and current is not None:
            current.append(line)
        else:
            fields.append([line])
        cost += extra

    shown = sum(len(f) for f in fields)
    if shown < len(subtasks):
        more = f"… and {len(subtasks) - shown} more"
        if fields and len("\n".join([*fields[-1], more])) <= FIELD_VALUE_MAX:
            fields[-1].append(more)
        else:
            fields.append([more])
    return [
        (first_name if i == 0 else CONTINUED, "\n".join(lines)) for i, lines in enumerate(fields)
    ]


def todo_embed(todo: TodoView) -> discord.Embed:
    """Full view of one to-do (`/todo show`, reminders): details first, then as many
    subtasks as fit in Discord's 6000-char embed budget."""
    embed = discord.Embed(
        title=cut(f"{scope_tag(todo.scope)} {esc(todo.title)}", EMBED_TITLE_MAX),
        description=(
            cut(discord.utils.escape_mentions(todo.details), EMBED_DESCRIPTION_MAX)
            if todo.details
            else None
        ),
    )
    embed.add_field(name="When", value=when(todo), inline=False)
    if todo.reminder is not None and todo.reminder.sent_at is not None:
        embed.add_field(
            name="Reminder",
            value=f"Sent {ts(todo.reminder.sent_at, 'R')}, waiting to be checked off",
            inline=False,
        )
    if todo.status == TodoStatus.DONE and todo.completed_at is not None:
        by = f" by <@{todo.completed_by}>" if todo.completed_by else ""
        embed.add_field(name="Done", value=f"{ts(todo.completed_at, 'f')}{by}", inline=False)
    if todo.scope == Scope.SERVER and todo.assignee_ids:
        embed.add_field(name="Assignees", value=mentions(todo.assignee_ids), inline=False)
    embed.set_footer(text=f"{'Server' if todo.scope == Scope.SERVER else 'Personal'} to-do")

    for name, value in _subtask_fields(todo.subtasks, EMBEDS_TOTAL_MAX - len(embed)):
        embed.add_field(name=name, value=value, inline=False)
    return embed


# --- reminders ---------------------------------------------------------------------------


def reminder_pings(todo: TodoView) -> str | None:
    """Message content of a server reminder: the assignees' mentions (they do ping)."""
    if todo.scope != Scope.SERVER or not todo.assignee_ids:
        return None
    return " ".join(f"<@{user_id}>" for user_id in todo.assignee_ids)


def reminder_embed(todo: TodoView, occurrence: OccurrenceView) -> discord.Embed:
    """The reminder message: details first, due time (late note), repeat rule, then as many
    subtasks as fit in Discord's 6000-char embed budget."""
    embed = discord.Embed(
        title=cut(f"⏰ {esc(todo.title)}", EMBED_TITLE_MAX),
        description=(
            cut(discord.utils.escape_mentions(todo.details), EMBED_DESCRIPTION_MAX)
            if todo.details
            else None
        ),
    )
    due = occurrence.due_at
    if occurrence.late:
        embed.add_field(
            name="Due", value=f"{ts(due, 'F')}\nLate — was due {ts(due, 'R')}", inline=False
        )
    else:
        embed.add_field(name="Due", value=ts_due(due), inline=False)
    if todo.kind == TodoKind.RECURRING and todo.rule_description:
        embed.add_field(name="Repeats", value=todo.rule_description, inline=False)
    embed.set_footer(
        text=f"{'Server' if todo.scope == Scope.SERVER else 'Personal'} reminder · press Done "
        "when it's done"
    )

    for name, value in _subtask_fields(todo.subtasks, EMBEDS_TOTAL_MAX - len(embed)):
        embed.add_field(name=name, value=value, inline=False)
    return embed


def subtask_option_pages(todo: TodoView) -> list[list[discord.SelectOption]]:
    """Subtask select options, 25 per select (so 1–2 selects for ≤ 50 subtasks)."""
    options = [
        discord.SelectOption(
            label=cut(f"{number}. {sub.title}", SELECT_LABEL_MAX),
            value=str(sub.id),
            default=sub.done,
        )
        for number, sub in enumerate(todo.subtasks, start=1)
    ]
    return [options[i : i + SELECT_OPTIONS_MAX] for i in range(0, len(options), SELECT_OPTIONS_MAX)]


# --- list and upcoming -------------------------------------------------------------------

_FILTER_NAMES: dict[ListFilter, str] = {"all": "", "timed": " · timed", "untimed": " · untimed"}


def list_row(todo: TodoView) -> str:
    row = f"**{esc(cut(todo.title, 100))}** — {short_when(todo)}"
    if todo.subtasks:
        row += f" · {sum(s.done for s in todo.subtasks)}/{len(todo.subtasks)} subtasks"
    return row


def list_embed(page: Page[TodoView], scope: Scope, filter: ListFilter = "all") -> discord.Embed:
    title = "Server list" if scope == Scope.SERVER else "Your personal list"
    first = page.page * page.page_size
    rows = [f"`{first + i}.` {list_row(todo)}" for i, todo in enumerate(page.items, start=1)]
    embed = discord.Embed(
        title=f"{title}{_FILTER_NAMES[filter]}",
        description="\n".join(rows) or "Nothing here. Add one with `/todo add`.",
    )
    embed.set_footer(text=f"Page {page.page + 1}/{page.page_count} · {page.total} open")
    return embed


def upcoming_embed(items: Sequence[UpcomingItem], days: int, limit: int) -> discord.Embed:
    rows = [
        f"`{i}.` {ts(item.due_at, 'f')} ({ts(item.due_at, 'R')}) — "
        f"{scope_tag(item.todo.scope)} {esc(cut(item.todo.title, 100))}"
        for i, item in enumerate(items, start=1)
    ]
    period = "day" if days == 1 else f"{days} days"
    embed = discord.Embed(
        title=f"Upcoming · next {period}",
        description="\n".join(rows) or f"Nothing due in the next {period}.",
    )
    if len(items) >= limit:
        embed.set_footer(text=f"Showing the first {limit}.")
    return embed


def upcoming_options(items: Sequence[UpcomingItem]) -> list[discord.SelectOption]:
    """Select options matching the numbered rows (labels can't hold Discord timestamps)."""
    return [
        discord.SelectOption(
            label=cut(f"{i}. {item.todo.title}", SELECT_LABEL_MAX), value=str(item.occurrence_id)
        )
        for i, item in enumerate(items[:SELECT_OPTIONS_MAX], start=1)
    ]
