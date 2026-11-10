# S5 — Slash commands & interactive views

**Goal:** the complete command surface (minus reminder delivery), as a thin adapter over S4 services.

**Depends on:** S4. Reads S3's `core.discord_time`/`core.tz`. **Branch:** `claude/s5-commands`.

## Adapter rules
- Build an `Actor` from each interaction: `user_id`, `guild_id = interaction.guild_id` **only if the bot is installed in that guild** (`interaction.is_guild_integration()`), `can_manage_guild = interaction.permissions.manage_guild`, origin `discord`.
- `scope` option (`Server` / `Personal`) on list/create commands. Default: `Server` where the bot is guild-installed, else `Personal`. Choosing `Server` elsewhere → friendly error.
- Defer (`ephemeral=True, thinking=True`) before DB work, **except** paths that must open a modal as the first response.
- Central error handler (`tree.on_error` + view `on_error`): `SidequestError` → its message, ephemeral; anything else → log with traceback, generic ephemeral apology.
- After every service call: execute returned effects (delete messages, ignore NotFound/Forbidden) and wake the scheduler when `changed_schedule`.
- `allowed_mentions=AllowedMentions.none()` on all command responses; escape user text.
- Before the first response of any command, check `consume_tz_hint` / `consume_dm_failure` and prepend a one-line note if needed.
- Rendering lives in `bot/render.py` as pure functions (`TodoView` → embed/text) so S6 can reuse them and they are unit-testable.
- Render within Discord's limits (BRIEF §4.11): all embeds of a message share 6000 chars; details first, then as many subtasks as fit, then "… and N more". Subtask selects: 25 options each, so 1–2 selects; labels ≤ 100 chars. A message has at most 5 component rows: 2 subtask selects + 1 button row leaves room.
- Replies are ephemeral (D27).

## Install contexts
| Command group | allowed_installs | allowed_contexts |
|---|---|---|
| `/todo …` | guild + user | guild, bot DM, private channels |
| `/settings …` | guild + user | all |
| `/sidequest about` | guild + user | all |
| `/sidequest channel` | guild only | guild only, `default_permissions(manage_guild=True)` |

## Commands
Shared options: `title` (≤200), `scope`, `timezone` (autocomplete via `search_zones`), `assignee`, `assignee2`, `assignee3` (user options; server scope only), `details` (bool: if true, respond with a modal instead of creating immediately).

| Command | Options | Behaviour |
|---|---|---|
| `/todo add` | title, date?, time?, timezone?, assignees?, scope?, details? | `resolve_due` → `create_once`. Neither date nor time → untimed; time alone → next occurrence; date alone → error "add a time". Reply shows the due time via `ts_due`, or "no reminder". |
| `/todo repeat daily` | title, times, … | `DailyRule` |
| `/todo repeat weekly` | title, days, times, … | `WeeklyRule` |
| `/todo repeat monthly-weekday` | title, week (choices First/Second/Third/Fourth/Last), weekday (choices), times, … | `MonthlyRule` — "every first Sunday" |
| `/todo repeat monthly-day` | title, day (string: `1`–`31` or `last`, via `parse_month_day`), times, … | `MonthlyDayRule` — "every 15th"; reply notes the last-day fallback for 29–31 |
| `/todo list` | scope?, show (open timed/untimed/all)?, post? | Paginated (10/page) embed, Prev/Next buttons. `post:true` only for server scope → public message. |
| `/todo upcoming` | scope?, days (1–31, default 7) | Pending occurrences with `ts_due`; a select menu (≤25) to check items off early; refreshes after each pick. |
| `/todo show` | todo | Detail embed: title, details, due or rule description + next occurrence, assignees, subtasks. Components: subtask multi-select(s) (two selects when > 25 subtasks), Done, Edit details. |
| `/todo done` | todo | `complete` |
| `/todo edit` | todo, title?, date?, time?, times?, days?, week?, weekday?, day?, timezone? | Validates fields against the to-do's kind and rule type (switching rule type = delete + recreate; not supported in edit). |
| `/todo details` | todo | Modal with a paragraph `TextInput` (≤4000, prefilled), empty = remove. |
| `/todo assign` | todo | Ephemeral `UserSelect` (multi, max 10, prefilled with current assignees) → `set_assignees`. Server only. |
| `/todo delete` | todo | Confirm/cancel buttons. |
| `/todo subtask add` | todo, items | `items` separated by `;` (slash options are single-line). |
| `/todo subtask remove` | todo, subtask (autocomplete scoped to the chosen todo) | |
| `/settings timezone` | timezone? | No arg → show current (and whether it's the default). |
| `/sidequest channel` | channel (text channel option) | Post a confirmation message there first; on success save it; on failure explain missing permissions. |
| `/sidequest about` | — | Already exists from S1. |

`todo` options use autocomplete → `services.todos.autocomplete`, label `"[S] title"` / `"[P] title"` (≤100 chars), value = id.

Modals: create-with-details collects `details` (paragraph) and re-shows `title` (prefilled) so the user can fix it; the to-do is created on submit using the original options carried in the modal instance.

## Views (`bot/views/`)
- All S5 views (list paging, upcoming, show, assign, delete confirm, and the paging on a public `post:true` list) are normal `discord.ui.View`s with a 5-minute timeout; disable their components on timeout. They need not survive restarts.
- Restart-proof components only exist on reminder messages, which are S6.
- Use Components V2 only if it simplifies layout; plain embeds are fine.

## Command sync
On startup compute a hash of `tree` command payloads; global sync only if it differs from `app_meta['command_hash']` (avoids rate limits on every restart). `DEV_GUILD_ID` set → always sync to that guild.

## Checklist
1. Actor builder, error handler, effect executor, render helpers — main session.
2. `/settings timezone` and `/todo add` end-to-end (incl. details modal) as the reference pattern — main session.
3. Remaining commands following the pattern — Haiku, one command group per subagent, reviewed.
4. `/todo upcoming` and `/todo show` views — main session.
5. Command sync hashing — Haiku.
6. Tests — Haiku: render functions (snapshot-style strings, incl. a max-size to-do — 4000-char details + 50 subtasks — staying under 6000 chars), option → service argument mapping, scope defaulting, `items` splitting.
7. Manual checklist for Tim (below).

## Manual test checklist (Tim, dev bot)
- [ ] `/settings timezone` autocomplete finds `Europe/Amsterdam`; setting it works
- [ ] `/todo add` untimed, time-only, explicit `today` + time, date+time; date-only rejected; past time rejected; `9pm` rejected with the 24h hint
- [ ] `/todo repeat monthly-day day:31` → next occurrences fall back to the last day in shorter months
- [ ] A to-do with 30 subtasks shows two selects in `/todo show`; the embed doesn't error
- [ ] `/todo add details:True` opens a modal; multi-line text shows in `/todo show`
- [ ] Server timed to-do before `/sidequest channel` is set → clear error
- [ ] `/todo repeat weekly days:mon,thu times:12:00` → description reads correctly, next occurrence timestamp right
- [ ] Personal to-do created in a server is visible in DMs with the bot, and not visible to another user
- [ ] `/todo upcoming` → check one off early → it disappears
- [ ] `/todo assign` with the user select; non-assignee without Manage Server can't edit
- [ ] Autocomplete on `todo` options responds quickly

## Out of scope
Posting reminders, the reminder Done button, DMs (S6).
