# S2 — Data model

**Goal:** the full schema as SQLAlchemy 2 typed ORM models, the first real Alembic migration, and an integration-test harness against real Postgres.

**Depends on:** S1 (`db/base.py`, `db/session.py`, Alembic wiring). **Branch:** `claude/s2-data-model`.

## Conventions
- Enum-like columns: `String` + `CHECK` (SQLAlchemy `Enum(..., native_enum=False)`), so adding values is a cheap migration.
- Discord IDs: `BIGINT`. Own primary keys: `BIGINT GENERATED ALWAYS AS IDENTITY`.
- All timestamps `TIMESTAMPTZ`, stored UTC. `created_at`/`updated_at` with server defaults.
- `recurrence` is `JSONB`; its shape is validated by `core.recurrence.RecurrenceRule` (S3), not by the DB. Shape:
  ```json
  {"type": "daily",   "times": ["08:00", "20:00"]}
  {"type": "weekly",  "weekdays": ["mon", "thu"], "times": ["12:00"]}
  {"type": "monthly", "week": 1, "weekday": "sun", "times": ["12:00"]}   // week: 1..4 or -1 (last)
  {"type": "monthly_day", "day": 15, "times": ["09:00"]}                 // day: 1..31 or -1 (last day)
  ```

## Tables

### `user_settings`
| column | type | notes |
|---|---|---|
| user_id | BIGINT PK | Discord user |
| timezone | VARCHAR(64) NULL | IANA; NULL → `DEFAULT_TIMEZONE` |
| tz_hint_shown | BOOL default false | D25: tell the user once about the default |
| dm_failed_at | TIMESTAMPTZ NULL | set when a DM reminder fails (S6), cleared after warning |
| created_at, updated_at | | |

### `guild_settings`
| column | type | notes |
|---|---|---|
| guild_id | BIGINT PK | |
| reminder_channel_id | BIGINT NULL | D6 |
| created_at, updated_at | | |

### `todos`
| column | type | notes |
|---|---|---|
| id | BIGINT identity PK | |
| scope | VARCHAR `server`/`personal` | |
| guild_id | BIGINT NULL | required iff scope = server |
| owner_id | BIGINT NOT NULL | creator; for personal = list owner |
| title | VARCHAR(200) NOT NULL | |
| details | TEXT NULL | ≤ 4000 (checked in services; also `CHECK (char_length(details) <= 4000)`) |
| kind | VARCHAR `once`/`recurring` | |
| due_at | TIMESTAMPTZ NULL | once + timed (NULL = untimed; no date-only to-dos, D17) |
| timezone | VARCHAR(64) NOT NULL | tz the to-do was created in |
| recurrence | JSONB NULL | required iff kind = recurring |
| status | VARCHAR `open`/`done`/`cancelled` default `open` | |
| completed_at | TIMESTAMPTZ NULL | |
| completed_by | BIGINT NULL | |
| created_at, updated_at | | |

CHECK constraints:
- `(scope = 'server') = (guild_id IS NOT NULL)`
- `kind = 'recurring'` ⇒ `recurrence IS NOT NULL AND due_at IS NULL`
- `kind = 'once'` ⇒ `recurrence IS NULL`

Indexes: `(guild_id, status)` where scope = server; `(owner_id, status)` where scope = personal.

### `todo_assignees`
`todo_id` FK → todos ON DELETE CASCADE, `user_id` BIGINT, PK `(todo_id, user_id)`, index on `user_id`.

### `subtasks`
`id` identity PK, `todo_id` FK CASCADE, `position` INT NOT NULL, `title` VARCHAR(100) (fits a select-option label), `done_at` TIMESTAMPTZ NULL, `done_by` BIGINT NULL. Ordered by `(position, id)`. Index `(todo_id)`.

### `occurrences`
| column | type | notes |
|---|---|---|
| id | BIGINT identity PK | used in button custom_ids |
| todo_id | FK → todos CASCADE | |
| due_at | TIMESTAMPTZ NOT NULL | |
| status | VARCHAR `pending`/`sent`/`done`/`missed`/`cancelled`/`failed` | |
| sent_at | TIMESTAMPTZ NULL | |
| late | BOOL default false | posted after a delay (bot was down) |
| channel_id | BIGINT NULL | where the reminder was posted (channel or DM channel) |
| message_id | BIGINT NULL | |
| failure_reason | VARCHAR(64) NULL | e.g. `no_channel`, `dm_closed`, `forbidden` |
| completed_at, completed_by | | |
| created_at | | |

Indexes: `(status, due_at)`; **partial unique** `(todo_id) WHERE status = 'pending'`; **partial unique** `(todo_id) WHERE status = 'sent'` (enforces D7: one open reminder per to-do).

Status flow:
```
pending ──fire──▶ sent ──Done──▶ done
   │                └─next occurrence fires──▶ missed
   ├──checked off early──▶ done
   ├──to-do edited/deleted──▶ cancelled
sent ──post failed──▶ failed
```

### `app_meta`
`key` VARCHAR PK, `value` TEXT. Used for the command-sync hash (S5).

## Checklist
1. `db/models.py` with all tables, relationships (`Todo.assignees`, `Todo.subtasks` ordered, `Todo.occurrences`), constraints and indexes as above — main session.
2. Alembic revision `0001_initial` via autogenerate, then hand-review (partial indexes and CHECKs often need manual edits) — main session.
3. Integration harness — Haiku, reviewed:
   - `tests/integration/conftest.py`: reads `TEST_DATABASE_URL`, runs `alembic upgrade head` once per session on a fresh database, gives each test a session inside a transaction that is rolled back.
   - Skip the integration suite with a clear message if `TEST_DATABASE_URL` is unset.
4. Tests — Haiku, from this list:
   - migration upgrade → downgrade → upgrade works
   - each CHECK constraint rejects a bad row (server without guild, recurring without rule, recurring with due_at, once with a rule)
   - second `pending` occurrence for the same to-do is rejected; same for `sent`
   - cascade delete removes assignees/subtasks/occurrences

## Acceptance
Migrations apply cleanly on the compose Postgres; unit + integration tests pass; layering test still green.

## Interfaces exported to later segments
`sidequest.db.models`: `UserSettings`, `GuildSettings`, `Todo`, `TodoAssignee`, `Subtask`, `Occurrence`, `AppMeta`, plus string enums `Scope`, `TodoKind`, `TodoStatus`, `OccurrenceStatus` (define these in `core/` so services can use them without importing `db`).
