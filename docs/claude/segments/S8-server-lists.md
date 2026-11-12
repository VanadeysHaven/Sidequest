# S8 — Server lists (drop personal lists and DMs)

> Written by Claude (Opus 5.5), 2026-11-12, from Tim's request and answers. This segment changes the product, not just the code: read §1 and §2 before touching anything.

**Goal:** Sidequest becomes server-only. The personal list and everything DM-related is removed. Instead, a server can have **several named lists**; every to-do lives on exactly one list. Users pick their own default list per server with `/settings`.

**Depends on:** S1–S7 (all done). **Branch:** `claude/s8-server-lists`. It already exists (created by the session that wrote this brief) and holds only this brief plus the README/PROGRESS updates. Once Tim has committed those, don't run `git switch -c`; check it is the current branch and that the working tree is clean.

**Why:** Tim, 2026-11-12: "the whole personal/server list thing doesn't work." Personal lists depend on DMs, and commands in DMs never worked (see PROGRESS "Future work"). Tim chose to drop them rather than fix them.

---

## 1. Decisions (append to BRIEF §3 as D40–D53, dated 2026-11-12)

| ID | Decision | Source |
|---|---|---|
| D40 | **No personal lists, no DMs.** Sidequest only works in servers where the bot is installed. Commands are guild-install + guild-context only (no user install, no DMs, no group DMs). Reminders are only posted in the server's reminder channel. Supersedes D2, D5, D19, D26 and D35. The DM verification and the "commands don't work in DMs" future-work item are closed. | Tim |
| D41 | A server has **any number of named lists** (max 25, see §4). Each to-do belongs to exactly one list. One reminder channel per server for all lists (D6 unchanged). | Tim |
| D42 | Every server has a **"Default List"**. It is the server's *fallback list*: users who never picked a default get it. It can be renamed but **not deleted**. It is created by the migration for existing servers and, for new servers, the first time anyone uses Sidequest there (see the note under this table). | Tim (list), Claude (mechanism) |
| D43 | **List names** are unique per server, **case-insensitive** ("Groceries" and "groceries" clash), trimmed, 1–50 characters. | Tim |
| D44 | **To-do titles** are unique among the **open** to-dos of one list, **case-insensitive**. Done and deleted to-dos don't count, so "Take out bins" can be added again after it is finished. Checked on create, title edit and move. | Tim |
| D45 | Each user can choose a **default list per server** with `/settings default-list`. Commands without a `list` option use it. If it is unset, or that list was deleted, the server's fallback list is used. | Tim |
| D46 | **Managing lists:** anyone in the server can create a list and becomes its **owner**. Renaming, deleting, managing collaborators and transferring ownership need the owner or Manage Server. The fallback list ("Default List", made by the migration or automatically) has **no owner**; its rules are in D51. | Tim |
| D47 | **Deleting a list** that still has open to-dos asks what to do with them: **Delete them** (cancelled, their reminder messages deleted) or **Move them** to another list (pick from a select), plus **Cancel**. A move is refused if any title would clash on the target list, and the reply names the clashing titles. An empty list just gets Delete/Cancel. Finished history on a deleted list is deleted with it. | Tim |
| D48 | **`/todo move`** moves one to-do to another list in the same server (edit permission, D20; title must not clash, D44). Reminders, subtasks and assignees stay. | Tim |
| D49 | Commands that show to-dos take an optional `list` option and show **one** list. `/todo list` without `list` shows your default list (D45: your setting, else the fallback list). `/todo upcoming` without `list` uses **your own default-list setting only**; if you haven't set one (or it was deleted), `list` is required and the reply says so. The Server/Personal/Both buttons (D35) go away. Autocomplete and other places that mix lists show the list name next to the title. | Tim |
| D50 | **Collaborators.** Every list except the server's fallback list has an **owner** and up to 25 **collaborators**. Everyone in the server can **see** every list and its to-dos. Only the owner, collaborators and Manage Server can **add, edit, set details, assign, add/remove subtasks, delete, move, check off** to-dos and **tick subtasks** on it, also via a reminder's Done button and subtask select. This replaces D3 and D20 for these lists: a to-do's creator or an assignee who isn't (or no longer is) a collaborator can't change or check it off. Collaborators can't rename/delete the list or manage collaborators (D46). Assignees don't have to be collaborators: they still get pinged. | Tim |
| D51 | **The fallback list ("Default List") is open to everyone.** Every member can add, edit, delete, assign, move and check off its to-dos and tick subtasks (no D20 restriction any more). Only **Manage Server** can **rename** it. It never has an owner or collaborators, can't be transferred, and **can't be deleted by anyone**, not even Manage Server (D42). The migrated server to-dos live here, so nobody loses access. | Tim |
| D52 | **Transferring ownership:** `/lists transfer` by the owner or Manage Server; not for the fallback list (D51). The new owner must be a server member and not a bot. If they were a collaborator they stop being one (the owner is implicit). The **old owner becomes a collaborator**; if that would exceed 25 collaborators, the transfer is refused ("remove a collaborator first"). | Tim |
| D53 | `/settings default-list` only accepts a list you can add to-dos to. If you later lose that right, `/todo add` without `list` says so and names the list, rather than silently picking another. | Tim |

**About "created upon joining a server" (D42):** the bot runs with `Intents.none()` (D11), so Discord never tells it when it joins a server (`on_guild_join` needs the `guilds` intent). Instead, a service helper creates the server's settings row and its "Default List" the first time any command runs in that server. For users this looks the same: the list is there the first time they look. It also covers servers the bot joined while it was offline. Enabling the `guilds` intent would only be needed if Tim wants something to happen *before* anyone uses the bot; he hasn't asked for that.

Also update the rest of the BRIEF to match (don't silently rewrite decisions: mark superseded ones like D16, e.g. `~~…~~ Superseded by D40.`):
- §1: one paragraph about named server lists; drop the personal list.
- §4.1 Lists and scope → rewrite for lists (D41–D45).
- §4.6: drop the "personal to-dos: no assignees" line.
- §4.8: drop the "Personal" reminder bullet; the reminder shows the list name.
- §4.9: drop the personal parts.
- §4.10: replace the table with the one in §4.2 below (D46, D50, D51); D3 and D20 become "Superseded by D50/D51".
- §4.11: add the list limits from §4.
- §5.4: replace the DM limitation paragraph with one line: "No DMs (D40)".

---

## 2. Behaviour (what Tim will see)

### 2.1 Commands
All commands: guild install, guild context only (`AppInstallationType(guild=True, user=False)`, `AppCommandContext(guild=True, dm_channel=False, private_channel=False)`), and that includes `/sidequest`. The `scope` option disappears everywhere.

| Command | Change |
|---|---|
| `/lists create name` | New. Anyone; the caller becomes the owner. Replies "📋 Created list **name**. Only you can add to-dos to it so far; add people with `/lists collaborators`." |
| `/lists rename list name` | New. Owner or Manage Server (D46); only Manage Server for the fallback list (D51). |
| `/lists delete list` | New. Owner or Manage Server; not the fallback list. Confirmation view (D47, §2.3). |
| `/lists collaborators list` | New. Owner or Manage Server. Replies with a user select (max 25, prefilled with the current collaborators), the same pattern as `/todo assign` (`views/assign.py`). Bots and the owner are dropped from the selection, with a note. Saving replaces the set: "👥 **List** now has N collaborator(s): @a, @b" (`AllowedMentions.none()`). |
| `/lists transfer list user` | New (D52). Owner or Manage Server; not the fallback list. Confirm/Cancel: "Make @user the owner of **List**? The current owner stays on as a collaborator." |
| `/lists show` | New. All lists of the server: name, owner (or "open to everyone" for the fallback list), number of collaborators, number of open to-dos, a marker on the fallback list and on the caller's own default. Ephemeral. |
| `/settings default-list [list] [clear]` | New. No arguments: show your default here. `list`: set it (must be a list you can add to, D53). `clear:True`: back to the server fallback. Both → error. |
| `/todo add`, `/todo repeat …` | `scope` → `list` (optional, autocomplete; default: your default list, D45). |
| `/todo list [list] [show] [post]` | Shows one list (D49). `post:true` works for any list. Embed title = list name. |
| `/todo upcoming [list] [days]` | One list (D49): `list`, else your default-list setting, else error "Pick a list with `list:`, or set a default with `/settings default-list`." Embed title = list name. No scope buttons. The "check one off early" select only offers to-dos the caller may check off (D50); the embed still shows all. |
| `/todo move todo list` | New (D48). |
| `/todo show/done/details/assign/delete/edit`, `/todo subtask …` | Permission checks per D50/D51 (§4.2); `assign` loses its personal-list error; `edit` checks title uniqueness. `/todo show` hides the Done button and subtask selects when the caller can't check off (new `TodoView.can_complete`). |
| Reminder **Done** button / subtask select | A non-collaborator gets an ephemeral "Only the owner and collaborators of **List** can check this off." and the reminder stays. |
| `/settings timezone` | Unchanged. |

The `list` option is a string option with autocomplete (value = list id as text), the same way `todo` options work today (`adapter.parse_id`, message "Pick a list from the suggestions that appear while you type."). Autocomplete shows the server's lists, prefix matches first, at most 25.

The `todo` autocomplete searches all open to-dos of the server. Because the same title can now exist on two lists, the label is `[List name] title` (list name cut to 30 chars, whole label to 100), replacing `[S]`/`[P]`.

### 2.2 Output text
- Created: "✅ Added **title** to **List name**." (+ the existing when/assignee lines).
- `todo_embed` footer: `List: <name>`; title loses the `[S]`/`[P]` tag.
- Reminder footer: `<List name> · press Done when it's done` (keep today's wording after the list name).
- `list_embed` and `upcoming_embed` titles: the list name (rows need no list tag any more).
- Moved: "📦 Moved **title** to **List name**."
- All list names in output go through `render.esc` (mentions + markdown), like titles.

### 2.3 `/lists delete` flow (D47)
1. Command checks permission and that it isn't the fallback list (error: "**Default List** is this server's fallback list, so it can't be deleted. You can rename it.", using the current name).
2. No open to-dos → "Delete list **X**? This can't be undone." + **Delete** / **Cancel**.
3. N open to-dos → "**X** has N open to-do(s). What should happen to them?" + **Delete list and its N to-do(s)** (danger), a select **Move them to…** (all other lists, max 24 options, so §4's 25-list limit keeps this in one select), and **Cancel**.
4. Move with clashes → ephemeral error "These titles already exist on **Y**: a, b, c. Rename or finish them first." The confirmation stays usable.
5. Success: "🗑️ Deleted list **X** and its N to-do(s)." / "🗑️ Deleted list **X**; moved N to-do(s) to **Y**." Reminder messages of deleted to-dos are removed (effects).
6. Users whose default was X fall back to the server fallback automatically (FK `ON DELETE CASCADE` on their row, §3).

---

## 3. Schema and migration `0003`

Create with `alembic revision --rev-id 0003 -m "server lists"`. Follow the naming convention in `db/base.py`. Finish with `alembic check` showing no drift.

### 3.1 Target schema
```
todo_lists
  id            BIGINT IDENTITY ALWAYS PK
  guild_id      BIGINT NOT NULL
  name          VARCHAR(50) NOT NULL
  owner_id      BIGINT NULL            -- NULL = ownerless/open list (migration, auto "Default List"; D51)
  created_at, updated_at               -- _Timestamps mixin
  UNIQUE (id, guild_id)                -- target of the composite FKs below
  UNIQUE INDEX uq_todo_lists_guild_id_name ON (guild_id, lower(name))

list_collaborators                     -- D50
  list_id   BIGINT FK → todo_lists(id) ON DELETE CASCADE
  user_id   BIGINT
  PK (list_id, user_id), INDEX ix_list_collaborators_user_id (user_id)
  -- the owner is never stored here (services keep that invariant on transfer/save)

guild_settings
  + default_list_id BIGINT NULL        -- the server's fallback list (D42)
    FK (default_list_id, guild_id) → todo_lists(id, guild_id) ON DELETE RESTRICT

user_guild_settings                    -- new; per user per server (D45)
  user_id, guild_id   BIGINT, PK (user_id, guild_id)
  default_list_id     BIGINT NOT NULL
    FK (default_list_id, guild_id) → todo_lists(id, guild_id) ON DELETE CASCADE
  created_at, updated_at

todos
  - scope (column + its CHECK), - CHECK scope_guild, - ix_todos_personal_owner_status
  - ix_todos_server_guild_status  →  + ix_todos_guild_id_status (guild_id, status)
  guild_id NOT NULL
  + list_id BIGINT NOT NULL
    FK (list_id, guild_id) → todo_lists(id, guild_id) ON DELETE CASCADE
  + INDEX ix_todos_list_id_status (list_id, status)
  + UNIQUE INDEX uq_todos_list_id_open_title ON (list_id, lower(title)) WHERE status = 'open'
  owner_id stays (now always "creator"; don't rename the column, it only causes churn)

user_settings
  - dm_failed_at
```
The composite FKs make it impossible for a to-do or a default to point at another server's list. `Scope` leaves `core/enums.py` and `db/models.py`; remove it from `__all__`.

### 3.2 `upgrade()` data steps, in this order
1. `DELETE FROM todos WHERE scope = 'personal'` (subtasks, assignees and occurrences cascade). Personal reminder messages already sitting in DMs stay; that's accepted.
2. Create `todo_lists`.
3. `INSERT INTO guild_settings (guild_id) SELECT DISTINCT guild_id FROM todos ON CONFLICT DO NOTHING`, so every server with to-dos has a settings row.
4. One "Default List" (`owner_id` NULL, so it stays open to everyone, D51) per `guild_settings` row; set `guild_settings.default_list_id` to it.
5. Add `todos.list_id` as nullable, fill it from the guild's default list, then set it `NOT NULL` and `guild_id NOT NULL`.
6. **Deduplicate open titles** before creating the unique index: within each list, open to-dos whose `lower(title)` repeats keep the oldest (`created_at, id`) as-is and rename the others to `title (2)`, `title (3)`, … Cut the base title so the result fits in 200 characters, and skip a suffix if that name is already taken. Do this in Python via `op.get_bind()`. Log how many were renamed.
7. Drop `scope` and its constraints/indexes, create the new indexes/FKs, create `user_guild_settings` and `list_collaborators` (empty), drop `user_settings.dm_failed_at`.

`downgrade()` restores the 0002 shape (`scope='server'` for every to-do, drops lists and the new table, re-adds `dm_failed_at`). Personal to-dos can't come back, and the docstring says so. `test_migrations.py` must still pass the round trip.

### 3.3 Migration test (new, `tests/integration/test_migration_0003.py`)
Upgrade to `0002`, insert by plain SQL: a personal to-do with an occurrence and a subtask, server to-dos in two guilds (one guild without a `guild_settings` row), two open server to-dos titled "Bins" and "bins" plus a done "Bins" in the same guild. Upgrade to `0003` and assert: the personal rows are gone (incl. children); each guild has exactly one "Default List" set as its `default_list_id`; every to-do points at its guild's list; the open duplicate became "bins (2)" and the done one is untouched; `dm_failed_at` is gone.

---

## 4. Services (main session — design work)

Limits in `core/limits.py`: `LIST_NAME_MAX = 50`, `LISTS_MAX = 25` per server (keeps the move select in §2.3 to one menu, and autocomplete shows them all), `COLLABORATORS_MAX = 25` per list (one user select).

New errors in `core/errors.py` (user-safe `.message`, like the others): `NameTaken(InvalidOperation)` for D43/D44 clashes.

### 4.1 `services/lists.py` (new)
```python
async def ensure_guild(uow, guild_id) -> int                 # fallback list id; creates settings row + "Default List" if missing
async def resolve(uow, actor, list_id: int | None) -> TodoList  # None → actor's default → fallback; NotFound if not in actor's guild
async def create(uow, actor, name) -> ListView
async def rename(uow, actor, list_id, name) -> ListView
async def delete_preview(uow, actor, list_id) -> ListDeletePreview   # view + open_count + move targets; permission + fallback checks
async def delete(uow, actor, list_id, *, move_to: int | None) -> Outcome[ListDeleteResult]
async def list_lists(uow, actor) -> list[ListView]
async def autocomplete(uow, actor, query, limit=25) -> list[tuple[int, str]]
async def get(uow, actor, list_id) -> ListView
async def set_collaborators(uow, actor, list_id, user_ids: Sequence[int]) -> ListView   # replaces the set
async def transfer(uow, actor, list_id, new_owner_id: int) -> ListView
```
- `set_collaborators`: owner or Manage Server; drops the owner's id from the set; > 25 → `LimitExceeded`. Bots can't be filtered in services (no Discord), so the adapter drops `user.bot` before calling.
- `transfer` (D52): lock the list; owner or Manage Server; new owner == current owner → `InvalidOperation`; remove the new owner from collaborators; add the old owner (if any) as collaborator, `LimitExceeded` if that makes 26; set `owner_id`. The adapter refuses bots.
- `ensure_guild` must be race-safe (two first commands at once): `INSERT … ON CONFLICT DO NOTHING` for the settings row; create the list only if `default_list_id IS NULL`, under `SELECT … FOR UPDATE` of the settings row. Call it from `resolve`, `create`, `list_lists`, `autocomplete` and the settings functions, i.e. everywhere a guild's lists are read or the fallback is needed.
- Name checks: `clean_list_name` (strip, non-empty, ≤ 50). Uniqueness: query `lower(name)` first for a friendly `NameTaken` ("There's already a list called **X**."), and also map the unique-index `IntegrityError` to the same error (race).
- `delete` locks the list row, re-checks permission and the fallback rule, then either (a) cancels every open to-do the way `todos.delete` does, collecting `DeleteMessage` effects, or (b) checks for title clashes on `move_to` (raise `NameTaken` listing the clashing titles, max 10 shown + "and N more"), then moves the open to-dos (`list_id = move_to`). Then it deletes the list row (history cascades). `changed_schedule=True` if any pending occurrence was cancelled.
- `DTOs` (`services/dto.py`, strict + frozen per D34): `ListView(id, guild_id, name, owner_id: int | None, collaborator_ids: tuple[int, ...], is_fallback, is_my_default, open_count, can_manage, can_add)`, `ListDeletePreview(list: ListView, open_count, targets: list[ListView])`, `ListDeleteResult(name, deleted: int, moved: int, moved_to: str | None)`.

### 4.2 `permissions.py`
The new table (also goes into BRIEF §4.10). "Member" = anyone in that server; Manage Server and the system actor may always do everything.

| Action | Owned list (D50) | Fallback list "Default List" (D51) |
|---|---|---|
| See the list and its to-dos | any member | any member |
| Check off (command, upcoming, reminder Done), tick subtasks | owner, collaborators | any member |
| Add a to-do (incl. moving one *onto* the list) | owner, collaborators | any member |
| Edit, details, assign, subtask add/remove, delete, move *off* the list | owner, collaborators | any member |
| Rename the list | owner | Manage Server only |
| Delete the list, set collaborators, transfer | owner | never (Manage Server neither) |
| Create a list | any member | — |

"Owned list" = `owner_id IS NOT NULL`; the fallback list is the one with `owner_id IS NULL` and `guild_settings.default_list_id` pointing at it. Use `owner_id IS NULL` as the open/closed test in permission code, and keep the invariant that only the fallback list is ownerless (services never clear an owner).

Functions (pure, as today; they take small Protocols, not ORM objects):
- `ListAccess` protocol: `guild_id`, `owner_id: int | None`, `collaborator_ids: Collection[int]`.
- `can_view(actor, todo)`: system, or `actor.guild_id == todo.guild_id`. Drop the personal branch and `scope` from `TodoAccess`.
- `can_work_on(actor, lst)`: same guild and (`owner_id is None`, or actor is owner/collaborator, or Manage Server). Used for add, edit, check off and subtasks. Keep thin named wrappers (`can_add`, `can_edit`, `can_complete`) so call sites read well and a future split is easy.
- `can_rename_list(actor, lst)`, `can_manage_list(actor, lst)` (delete, collaborators, transfer) per the table.
- `TodoView` gets `can_complete` next to `can_edit`. `ListView` gets `can_add`, `can_manage`.
- `can_create` → removed; every service that needs a guild calls a shared `_common.require_guild(actor) -> int` that raises `InvalidOperation("Sidequest only works in a server where it's installed.")`.
- Error messages: adding → "Only the owner and collaborators of **List** can add to-dos to it."; editing → "Only the owner and collaborators of **List** (or someone with Manage Server) can change its to-dos." (ownerless: today's D20 message); managing → "Only the owner of **List** or someone with Manage Server can do that."
- Loading: whenever a to-do is loaded for a permission check, its list and the list's collaborators are loaded too (`selectinload(Todo.list).selectinload(TodoList.collaborators)`), so `TodoView.can_edit` stays right.

### 4.3 `todos.py` and `_common.py`
- `create_once`/`create_recurring`: `scope=` → `list_id: int | None = None` (resolved with `lists.resolve`). Assignee rules = today's server rules (default: the creator).
- Title uniqueness (D44) on create, `edit` (title change) and `move`: shared helper `_common.require_unique_title(uow, list_id, title, exclude_todo_id=None)` + `IntegrityError` mapping. Message: "**title** is already on **List** (open to-dos need unique names)."
- `move(uow, actor, todo_id, list_id) -> Outcome[TodoView]`: lock, `require_open`, `require_edit` on the source list, `can_add` on the target (via `lists.resolve`, same guild), no-op error if it's already there, title check, update.
- `complete` (and `occurrences.complete_occurrence`, `subtasks.set_done`): replace the "any member" check with `can_complete` (D50). The scheduler (system actor) is unaffected. `occurrences.is_live` must keep working for non-collaborators, so a stale reminder still gets cleaned up.
- `list_todos(uow, actor, list_id: int | None, filter, page, page_size)`: one list, resolved like D45.
- `autocomplete(uow, actor, query, limit)` → `(id, title, list_name)`, all open to-dos of the actor's guild.
- `c.visible(actor)` → simply `Todo.guild_id == require_guild(actor)`.
- `TodoView`: drop `scope`; `guild_id: int`; add `list_id: int`, `list_name: str`. Loading needs the list name. Add a `relationship` `Todo.list` (`lazy="raise"`) and `selectinload` it wherever views are built (`_todo_query`, `list_todos`, `list_upcoming`, `claim_due`, `unposted_sent`, retention is unaffected).
- `set_assignees`: drop the personal check.
- `_require_channel`: no scope parameter any more.

### 4.4 `occurrences.py`, `settings.py`, scheduler
- `list_upcoming(uow, actor, list_id: int, until, limit)`: one list (resolved and permission-checked like `list_todos`).
- The upcoming default (D49) needs the user's **own** setting without the fallback: `settings.own_default_list_id(uow, actor) -> int | None`. The command raises `InvalidOperation` with the message from §2.1 when both it and the option are empty.
- Remove `FAILURE_DM_CLOSED`, the `dm_failed_at` write in `mark_failed`, `DueReminder.dm_user_id`. `DueReminder.channel_id` stays `int | None` (None = no channel set).
- `settings.py`: remove `consume_dm_failure`. Add `get_default_list(uow, actor) -> ListView` (the effective one) + whether it's the fallback, `set_default_list(uow, actor, list_id) -> ListView` (upsert `user_guild_settings`), `clear_default_list(uow, actor) -> ListView`. `count_scheduled_server_todos` loses the `scope` filter.
- `scheduler/loop.py` should need no change beyond what the type checker finds.

---

## 5. Bot layer

- `bot/commands/common.py`: `ANYWHERE_*` → `GUILD_INSTALLS` / `GUILD_CONTEXTS`; `CREATE_DESCRIPTIONS`: drop `scope`, add `list`; `check_options` drops `scope`.
- `bot/adapter.py`: remove `ScopeOption`, `resolve_scope`, `NOT_IN_SERVER`; add `parse_list_id(value: str | None) -> int | None`. `collect_notes` keeps only the timezone hint.
- `bot/commands/lists.py` (new): `build_lists_group()` with create/rename/delete/collaborators/transfer/show. New views: `bot/views/list_delete.py` (the D47 view), `bot/views/collaborators.py` (user select, modelled on `views/assign.py`), and a transfer Confirm/Cancel (next to the others in `views/confirm.py`).
- `bot/views/reminder.py`: Done/subtask select by a non-collaborator → the ephemeral error from §2.1; don't delete the message.
- `bot/views/show.py`: build the Done button and subtask selects only when `todo.can_complete`.
- `bot/commands/settings.py`: `default-list` subcommand.
- `bot/commands/todo_manage.py`: add `move_command()`; `assign` loses its personal check.
- `bot/commands/todo_list.py`, `todo_view.py`, `views/listing.py`, `views/upcoming.py`: `scope` → `list_id`; delete `ScopePickView`.
- `bot/commands/about.py`: guild-only install/contexts for `SidequestGroup`.
- `bot/autocomplete.py`: new `todo_list` callback; `todo` uses the new label.
- `bot/render.py`: remove `scope_tag`/`list_name(scope)`; use `todo.list_name` (§2.2); `list_embed(page, list_name, filter)`; new `lists_embed(lists)` for `/lists show`.
- `bot/notifier.py`: remove the DM branch (`create_dm`, the 50007 handling for DMs).
- `bot/client.py`: register the `/lists` group; update the `_sync_commands` docstring (no DMs/user installs). The command payload changes, so the global sync runs once on the next start (expected).
- The commands still check `actor.guild_id` at runtime (via the services): a guild where only a user-installed copy exists has no `is_guild_integration()`.

Keep files under ~400 lines (WORKFLOW §4); `todo_manage.py` may need splitting.

---

## 6. Checklist (one task each; routing per WORKFLOW §3)

1. **BRIEF** — Opus: append D40–D53 (as in §1; all confirmed by Tim on 2026-11-12), mark superseded decisions, update §1/§4/§5.4.
2. **Schema + migration 0003 + migration test** — main session (§3).
3. **Services**: `lists.py`, permissions, todos/occurrences/settings changes, DTOs, errors, limits — main session (§4).
4. **Service tests** — Haiku from this case list, reviewed:
   - lists: create (caller is owner); duplicate name in any case → `NameTaken`; same name in another guild OK; > 25 lists → `LimitExceeded`; rename by owner / by Manage Server OK, by a collaborator or other member → `Forbidden`; rename the fallback list with Manage Server OK, by any other member → `Forbidden`; delete the fallback → `InvalidOperation` even with Manage Server; collaborators and transfer on the fallback → `InvalidOperation`; delete empty list; delete with to-dos (to-dos cancelled, `DeleteMessage` for a sent reminder, pending cancelled, `changed_schedule`); move-delete (to-dos moved, reminders untouched); move-delete with a clash → `NameTaken` naming the titles and nothing changed; move-delete onto a list the caller can't add to → `Forbidden`; deleting a list removes users' default for it → `get_default_list` returns the fallback; `ensure_guild` called twice (and concurrently on two connections) creates one "Default List".
   - collaborators: owner sets them; Manage Server sets them; a collaborator → `Forbidden`; owner id in the set is dropped; 26 → `LimitExceeded`; replacing the set removes the ones left out.
   - transfer: by owner and by Manage Server; old owner becomes collaborator; new owner removed from collaborators; to the current owner → `InvalidOperation`; at 25 collaborators with an old owner to add → `LimitExceeded`, nothing changed; afterwards the old owner can still add to-dos but can no longer rename.
   - permissions in practice: on an owned list a non-collaborator gets `Forbidden` for add, edit, details, assign, subtask add/remove, tick subtasks, `complete`, `complete_occurrence` (reminder Done) and delete; the to-do's creator who was removed as collaborator → `Forbidden`; an assignee who isn't a collaborator → `Forbidden` on complete; Manage Server → allowed; on the fallback list any member may do all of these.
   - todos: create without `list_id` → user default, else fallback; with another guild's list id → `NotFound`; duplicate open title in any case → `NameTaken`; same title allowed after the first is done; same title on another list OK; edit title into a clash → `NameTaken`; `move` (permission, clash, same list, other guild); `list_todos` shows one list; `autocomplete` returns list names; `list_upcoming` returns only the given list; `own_default_list_id` is None when unset and after the list was deleted, and set otherwise.
   - settings: set/show/clear default list; setting a list from another guild → `NotFound`; setting a list you can't add to → `Forbidden` (D53); `/todo add` without `list` after losing collaborator rights on your default → `Forbidden` naming the list.
   - permissions table (`tests/unit/test_permissions.py`): drop personal rows; add rows for `can_work_on` / `can_rename_list` / `can_manage_list` × (owner, collaborator, other member, Manage Server, other guild, system) × (owned list, fallback list).
5. **Bot**: commands, views, render, autocomplete, notifier, client — main session for `lists.py`, the delete view and the permission-dependent UI (Done button / selects hidden or refused per D50); Haiku for the repeated `scope` → `list` swap in the four `/todo repeat` commands, reviewed.
6. **Clean up** every remaining reference: `grep -rn -i "personal\|scope\|dm_failed\|create_dm\|dm_user\|ANYWHERE" src tests` should only hit unrelated words. Update existing tests that use `scope=` / personal fixtures (`tests/integration/*`, `test_render.py`, `test_reminder_render.py`, `test_adapter.py`, `test_command_sync.py`, `test_schema.py`).
7. **Docs** — Opus: RUNBOOK (Developer Portal: **untick User Install**; the `0003` migration **deletes personal to-dos**, and `update.sh` takes a backup first; remove the DM sections and `dm_closed`); root `README.md` (features: named server lists); `PROGRESS.md` (close the DM future-work item and the open DM checklist items as obsolete, handoff note).
8. **Checks** (WORKFLOW §6): `ruff check .`, `ruff format --check .`, `pytest` with `TEST_DATABASE_URL`, `alembic check`.

---

## 7. Manual test checklist (Tim, dev bot)

- [ ] `./update.sh` on a copy of the production data (or the Pi after a backup): log shows `Running upgrade 0002 -> 0003`; old server to-dos appear on **Default List**; personal ones are gone.
- [ ] Startup log shows a global (or guild) command sync once; commands no longer appear in DMs with the bot.
- [ ] In a fresh server (bot just invited): `/lists show` shows **Default List**.
- [ ] `/lists create Groceries`; `/lists create groceries` → "already a list called".
- [ ] `/todo add title:Milk list:Groceries` → "Added **Milk** to **Groceries**"; again → name taken; `title:milk` → name taken; on Default List → fine.
- [ ] `/todo done Milk`, then `/todo add Milk list:Groceries` → allowed.
- [ ] `/settings default-list list:Groceries`; `/todo add Eggs` (no list) → Groceries. `/settings default-list` shows it; `clear:True` → back to Default List.
- [ ] `/todo list` (no list) shows your default list; `list:` another one; `post:true` works.
- [ ] `/todo upcoming` with no default set and no `list:` → asks you to pick one or set a default. With `list:` → that list. After `/settings default-list` → your default list without the option.
- [ ] Autocomplete on `todo` options shows `[List] title`; on `list` options shows the server's lists.
- [ ] `/todo move` to another list; into a clash → error.
- [ ] `/lists rename` as owner works; as a collaborator or another member without Manage Server → refused; renaming Default List needs Manage Server.
- [ ] `/lists delete` Default List → refused for everyone, also an admin (rename hint).
- [ ] Second account (not a collaborator) on Groceries: can see it in `/todo list` and `/todo upcoming`, but `/todo add list:Groceries`, `/todo edit`, `/todo done`, a reminder's **Done** button and ticking subtasks are all refused; `/todo show` shows no Done button. On Default List the same account can do everything.
- [ ] `/lists collaborators Groceries` → add the second account → now it can add, edit and check off. Remove it → refused again.
- [ ] `/lists transfer Groceries @second` → second account is owner and can rename; you are now a collaborator (can add, can't rename). `/lists transfer` on Default List → refused.
- [ ] `/settings default-list list:Groceries` as a non-collaborator → refused (D53).
- [ ] `/lists delete` a list with open to-dos → Delete / Move / Cancel. Delete: to-dos gone, a posted reminder of one disappears. Move: to-dos show up on the target list; a clash names the titles.
- [ ] A user whose default list was deleted → `/settings default-list` shows Default List.
- [ ] Reminders still post in the reminder channel, footer shows the list name; Done works.

## Acceptance
All checks green; `alembic check` clean; migration test passes; Tim's manual checklist passes on the dev bot; BRIEF/RUNBOOK/README/PROGRESS updated by Opus.
