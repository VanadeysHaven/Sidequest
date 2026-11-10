# S4 — Services (domain layer)

**Goal:** every business operation as an async, Discord-free service function with permission checks. The bot (S5/S6) and the future web frontend call only these.

**Depends on:** S2 (models), S3 (time/recurrence). **Branch:** `claude/s4-services`.

## Core concepts

### `services/actor.py`
```python
@dataclass(frozen=True)
class Actor:
    user_id: int
    guild_id: int | None          # guild the request came from (None in DMs / web)
    can_manage_guild: bool        # Manage Server in guild_id
    origin: Literal["discord", "web", "system"]
```

### `services/effects.py`
Services never call Discord. They return results carrying effects for the adapter to execute:
```python
@dataclass(frozen=True)
class DeleteMessage:
    channel_id: int
    message_id: int

Effect = DeleteMessage    # union grows later (e.g. EditMessage)
```
Every mutating service returns a result object with `.effects: list[Effect]` and sets a `changed_schedule: bool` so the adapter can wake the scheduler.

### Unit of work
Each service function takes an `AsyncSession` (or a small `Uow` wrapper) as its first argument and commits itself. A `Clock` is injected (module-level `Services` class holding `session_factory`, `clock`, `config` is fine — choose one pattern and keep it).

### Errors (extend `core/errors.py`)
`NotFound`, `Forbidden`, `ReminderChannelNotSet`, `LimitExceeded`, `InvalidOperation` (e.g. editing a recurring to-do's date). All carry a user-safe message.

### DTOs
Return plain dataclasses (`TodoView`, `OccurrenceView`, `SubtaskView`, `UpcomingItem`, `Page[T]`), not ORM objects, so callers never lazy-load.

## Operations

### Settings (`services/settings.py`)
- `get_user_timezone(user_id) -> (tz_name, is_default)`; `set_user_timezone(actor, tz_name)`.
- `consume_tz_hint(user_id) -> bool` (D25: True once, then flag set).
- `consume_dm_failure(user_id) -> datetime | None` (S6 warning, then cleared).
- `set_reminder_channel(actor, channel_id)` — requires `can_manage_guild`.
- `get_guild_settings(guild_id)`.

### To-dos (`services/todos.py`)
- `create_once(actor, scope, title, details, due: Untimed|Timed, tz, assignee_ids)`
- `create_recurring(actor, scope, title, details, rule, tz, assignee_ids)`
- `get(actor, todo_id) -> TodoView`
- `list(actor, scope, filter: all|timed|untimed, page) -> Page[TodoView]` — open to-dos; timed (incl. repeating) first by next due, then untimed by created_at.
- `edit(actor, todo_id, patch)` — title, details, due (once), rule/times (recurring), timezone. Changing timing cancels the pending occurrence and creates a new one; a `sent` reminder of a once-to-do whose time changes becomes `cancelled` and yields a `DeleteMessage`.
- `set_details(actor, todo_id, details | None)`
- `set_assignees(actor, todo_id, user_ids)` — server scope only.
- `complete(actor, todo_id)` — once-to-dos: marks done, closes any pending/sent occurrence (effects for sent). Recurring: completes the current occurrence (same as `complete_occurrence` on the active one).
- `delete(actor, todo_id)` — status `cancelled`, open occurrences `cancelled`, effects for sent messages.
- `autocomplete(actor, query, scope | None, limit=25) -> list[(id, label)]` — must be fast (indexed, simple `ILIKE`).

Creation rules:
- Scope `server` requires `actor.guild_id`; timed or recurring server to-dos require a reminder channel → `ReminderChannelNotSet` (tell the user an admin must run `/sidequest channel`).
- Scope `personal`: `owner_id = actor.user_id`, `guild_id = None`, assignees rejected (D19).
- Server assignees default to `[actor.user_id]` (dedupe, ≤ 10).
- Timezone: explicit override, else user's, else `DEFAULT_TIMEZONE` (UTC) (D24, D25).
- Timed once → one `pending` occurrence at `due_at`. Recurring → one `pending` at `next_occurrence(rule, tz, now)`.

### Subtasks (`services/subtasks.py`)
- `add(actor, todo_id, titles: list[str])` (≤ 50 total, each title ≤ 100 chars), `remove(actor, subtask_id)`, `set_done(actor, todo_id, done_ids: set[int], within: set[int] | None = None)` (used by the multi-selects: within `within` — one select page — ticks exactly `done_ids`; `None` = all subtasks), `toggle(actor, subtask_id)`.
- Reset for recurring to-dos happens inside occurrence closing (below).

### Occurrences (`services/occurrences.py`) — used by S5 (upcoming) and S6 (scheduler)
- `list_upcoming(actor, scope, until) -> list[UpcomingItem]` — pending occurrences, ordered by `due_at`.
- `complete_occurrence(actor, occurrence_id)`:
  - `pending` → `done` (checked off early: reminder never sent)
  - `sent` → `done`, effect `DeleteMessage` (the button handler deletes it itself too; ignore NotFound)
  - already `done`/`missed`/`cancelled` → raise `InvalidOperation("already checked off")`
  - once-to-do → to-do `done`. Recurring → materialize next pending (`after = max(due_at, now)`), reset subtasks.
- Scheduler API (system actor):
  - `claim_due(now, limit) -> list[DueReminder]` — in one transaction: `SELECT … WHERE status='pending' AND due_at <= now FOR UPDATE SKIP LOCKED LIMIT n`; for each: set `sent`, `sent_at=now`, `late = now - due_at > 2 min`; for recurring: mark the previous `sent` occurrence `missed` (collect its message as an effect), reset subtasks, materialize next pending (`after = now`, so a long outage produces one catch-up, not a flood). `DueReminder` contains everything needed to render: todo view, subtasks, assignees, scope, guild reminder channel or owner id, rule description, effects.
  - `attach_message(occurrence_id, channel_id, message_id)`
  - `mark_failed(occurrence_id, reason)`; for `dm_closed` also set `user_settings.dm_failed_at`.
  - `unposted_sent(older_than) -> list[DueReminder]` — crash recovery (sent, no message_id).
  - `next_due_at() -> datetime | None` — for the scheduler's sleep.

### Permissions (`services/permissions.py`)
Pure functions over `(actor, todo, assignee_ids)` implementing BRIEF §4.10:
- `can_view`, `can_complete` (server: `actor.guild_id == todo.guild_id`; personal: owner) — note: reminder-button presses come from the reminder channel, so `guild_id` matches; DMs are personal.
- `can_edit` (server: creator, assignee, or `can_manage_guild`; personal: owner).
- Every service calls these; `NotFound` (not `Forbidden`) for to-dos the actor cannot view, so IDs don't leak across servers.

## Checklist
1. Actor, effects, errors, DTOs — main session.
2. Permissions + unit tests (table: actor × todo × action) — main session writes rules; Haiku writes the table tests.
3. Settings + todos + subtasks services — main session writes `create_once`, `create_recurring`, `complete`; Haiku may write the remaining same-shaped functions following them, reviewed.
4. Occurrence services incl. `claim_due` — main session.
5. Integration tests (real Postgres, `FixedClock`) — Haiku from this list, reviewed:
   - creating timed once → one pending occurrence; untimed → none
   - server timed to-do without reminder channel → `ReminderChannelNotSet`
   - personal to-do invisible to another user (NotFound) and from another guild context it is still visible to its owner
   - server to-do from guild A not visible from guild B
   - complete pending early → done, todo done, no effects
   - recurring: complete early → next pending exists, subtasks reset
   - `claim_due`: once fires once; recurring materializes next; previous `sent` → `missed` with DeleteMessage effect
   - outage: daily rule, clock jumps 3 days → one claim, `late=True`, next pending is in the future
   - two concurrent `claim_due` calls never return the same occurrence
   - edit time of once-to-do with a `sent` reminder → cancelled + DeleteMessage, new pending
   - limits enforced (title, details, 51st subtask rejected, subtask title > 100, assignees)
   - assignees on a personal to-do rejected
   - user without a timezone → to-do stored in UTC

## Acceptance
Unit + integration tests pass; `services` imports no `discord` (layering test).

## Interfaces exported
Everything above; S5/S6 should not need to touch the ORM directly.
