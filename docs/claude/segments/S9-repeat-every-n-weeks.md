# S9 — Repeat every N weeks

> Written by Claude (Opus 5.5), 2026-11-12, from Tim's request ("reminders that repeat every x weeks"). Tim confirmed the design the same day (answers at the end); the decisions in §1 are final.

**Goal:** a weekly repeating to-do can repeat every N weeks ("every 2 weeks on Tuesday at 07:00", "every 3 weeks on Friday at 18:00"), and any weekly to-do can be told not to start before a date. Everything else about repeating to-dos stays as it is.

**Depends on:** S1–S8. **Branch:** `claude/s9-repeat-every-n-weeks`, created by the S9 session (WORKFLOW §1). No schema migration.

**Interfaces you need (read only these files, not other segment docs):** `core/recurrence.py` (rule models, `next_occurrence`, `describe`, `to_json`/`from_json`), `core/timeparse.py` (`parse_date`), `core/limits.py`, `bot/options.py` (`weekly_rule`, `edited_rule`, `edit_patch`, `REPEAT_ONLY`), `bot/commands/repeat.py` (`weekly_command`), `bot/commands/todo_edit.py`, `bot/commands/common.py` (`check_options`, `create_flow`), `bot/adapter.py` (`due_input`, for how a date is parsed in the to-do's timezone), `services/todos.py` (`create_recurring`, `_retime_recurring`), `services/_common.py` (`add_next_pending`, `effective_zone`), `tests/unit/test_recurrence.py`.

---

## 1. Decisions (append to BRIEF §3 as D54–D59, dated 2026-11-12)

| ID | Decision | Source |
|---|---|---|
| D54 | **Weekly rules get an interval:** `every` = 1–52 weeks, default 1 (today's behaviour). It's an option on `/todo repeat weekly`, not a separate command. Only weekly rules; "every N days" and "every N months" stay out of scope. Removes "every N weeks" from BRIEF §8. | Tim |
| D55 | **Weeks run Monday–Sunday.** A week is "on" when the number of weeks between its Monday and the Monday of the `start` week is a multiple of `every`. Consequence: with `days:sun,mon every:2` the Sunday and the following Monday are in different weeks, so they never fire as a pair (see the example in §2.3). | Tim |
| D56 | **`start`** (optional date) on any weekly rule: **nothing fires before that date**. With `every` ≥ 2 it also sets which weeks are on: its week is the first on-week. Past dates are allowed, so a schedule can be lined up with the real world ("the bins went out on 3 Nov, every 2 weeks"). At most one year ahead. Without `start` and with `every` ≥ 2, it is set to the date of the next time the rule would fire as a plain weekly rule, so the **first reminder is always the soonest one possible**. With `every:1` and no `start`, none is stored. | Tim |
| D57 | **Editing:** `/todo edit` gets `every` and `start` (weekly to-dos only). Changing `days`, `times`, `timezone` or `every` keeps the stored `start` (the weeks stay put). Going from `every:1` without a `start` to ≥ 2 anchors the same way as creating (so the next reminder doesn't move). `start` can be replaced but not cleared; a past `start` on an `every:1` rule has no effect. | Claude (follows from D56) |
| D58 | **Wording:** `every` ≥ 2 → "Every 2 weeks on Monday and Thursday at 12:00 (Europe/Amsterdam)". `every:1` keeps today's "Every Monday and Thursday at 12:00 (…)". The start date isn't in the description; the "Next:" timestamp already shows when it fires. | Claude |
| D59 | **Storage:** two optional keys in the weekly JSON: `every` only when ≥ 2, `start` only when set. E.g. `{"type": "weekly", "weekdays": ["tue"], "times": ["07:00"], "every": 2, "start": "2026-11-03"}`. A rule with `every:1` and no `start` keeps exactly today's JSON, so existing rows are untouched and **no migration is needed**. | Claude |

---

## 2. Behaviour (what Tim will see)

### 2.1 Commands

| Command | Change |
|---|---|
| `/todo repeat weekly … [every] [start]` | `every`: integer option 1–52 (`app_commands.Range[int, 1, 52]`), described "Repeat every N weeks (default 1)". `start`: string, same formats as `date` elsewhere (`YYYY-MM-DD`, `DD-MM-YYYY`, `today`, `tomorrow`), described "Don't start before this date; with every ≥ 2 it also picks the weeks". Both go at the end, before `details`. |
| `/todo edit … [every] [start]` | Same two options. On a daily/monthly to-do → today's "This to-do repeats daily, so `every` can't be changed…" message (via `_RULE_FIELDS`). On a one-time to-do → the existing "for repeating to-dos" message, which now also lists `every` and `start`. |
| `/todo repeat daily / monthly-*` | Unchanged. |

Errors (user-safe `.message`):
- `start` more than a year ahead → "`start` can be at most a year ahead."
- Bad date → the existing `DATE_HINT` message (checked before a `details:True` modal opens, via `common.check_options(date_text=start)`).

The create/edit replies need no new text: they already show `render.when(view)` (description + "Next: <timestamp>").

### 2.2 Interaction with existing rules
Nothing else changes: missed reminders (D7) still close when the next one fires (so a reminder can stay up for N weeks), subtasks reset per occurrence (D4), catch-up after downtime is still at most one reminder, DST handling is per day as today, and `/todo upcoming` just shows fewer rows.

### 2.3 Worked examples (created Thu 2026-11-12 13:00, Europe/Amsterdam)

| Input | `start` stored | Next occurrences |
|---|---|---|
| `days:mon times:07:00 every:2` | 2026-11-16 (default) | Mon 16 Nov, Mon 30 Nov, Mon 14 Dec |
| `days:mon,thu times:12:00 every:2` | 2026-11-16 (Thu 12 Nov 12:00 has passed) | Mon 16 Nov, Thu 19 Nov, Mon 30 Nov, Thu 3 Dec |
| `days:tue times:07:00 every:2 start:2026-11-03` | 2026-11-03 (past) | Tue 17 Nov, Tue 1 Dec, Tue 15 Dec |
| `days:fri times:18:00 every:3 start:2026-12-04` | 2026-12-04 | Fri 4 Dec, Fri 25 Dec, Fri 15 Jan 2027 |
| `days:sun,mon times:10:00 every:2` | 2026-11-15 (a Sunday, so the week of Mon 9 Nov) | Sun 15 Nov, Mon 23 Nov, Sun 29 Nov, Mon 7 Dec (D55) |
| `days:mon times:07:00 start:2026-11-26` (`every:1`) | 2026-11-26 | Mon 30 Nov, Mon 7 Dec, Mon 14 Dec |
| `days:mon times:07:00` (`every:1`) | none | Mon 16 Nov, Mon 23 Nov (today's behaviour) |

These rows (computed with a reference implementation) belong in the recurrence test table.

---

## 3. Core: `core/recurrence.py` (main session)

- `core/limits.py`: `WEEK_INTERVAL_MAX = 52`, `START_AHEAD_MAX_DAYS = 366`.
- `WeeklyRule` gains `every: int = 1` (strict int, 1–52) and `start: date | None = None` (JSON `"YYYY-MM-DD"`). `every ≥ 2` with `start=None` is **allowed in the model** but means "not anchored yet": `next_occurrence`, `occurrences_between` and `to_json` raise `ValueError` for it (a bug guard: an unanchored rule must never be stored or scheduled).
- `to_json`: leave out `every` when it is 1 and `start` when it is None, so old rows round-trip byte-for-byte. Careful: `model_dump(exclude_defaults=True)` would also drop `type` (it has a default too); exclude the two fields explicitly or use a model serializer. Test both directions.
- New pure function `anchored(rule, tz, now) -> RecurrenceRule`: returns non-weekly rules unchanged. For weekly rules: if `start` is set, check it is at most `START_AHEAD_MAX_DAYS` after today in `tz` (`InvalidRule` with the §2.1 message) and return the rule; if `start` is None and `every == 1`, return it unchanged; otherwise fill `start` with the local date (in `tz`) of `next_occurrence(rule with every=1, tz, now)`.
  - The one-year check only applies when the rule is created or its `start` is changed (it's checked against "now", and a stored start only gets closer over time). `anchored` is called exactly in those two places (§4), so that holds; on an edit that doesn't touch `start`, the stored one is in the past or within the year anyway.
- `_matches` for weekly: weekday in `weekdays`; if `start` is set, `d >= start`; if `every ≥ 2`, `((monday(d) - monday(start)).days // 7) % every == 0`.
- `next_occurrence`: start the day loop at `max(after's local date - 1 day, start)` instead of only the former, so a future `start` doesn't burn search days. With `every ≤ 52` an on-week comes within 364 days, inside `MAX_SEARCH_DAYS = 800`; update the comment that says "every valid rule fires at least once a month".
- `describe`: §1 D58. Keep the plural "weeks" (`every` is never 1 there).
- Module docstring: add the new JSON shape.

---

## 4. Services and bot

### 4.1 Services (main session)
- `todos.create_recurring`: `rule = recurrence.anchored(rule, zone, uow.clock.now())` right after resolving the zone, before `to_json`.
- `todos._retime_recurring`: when `patch.rule` is given, anchor it in the **new** zone (if `patch.timezone` changed) with `now`. Because `edited_rule` keeps the stored `start` (§4.2), `anchored` only fills it for a change from `every:1` without a `start` to ≥ 2, which is D57.
- Nothing else: `add_next_pending`, the scheduler and retention only call `next_occurrence`.

### 4.2 Bot
- `options.weekly_rule(days, times, every: int = 1, start: date | None = None)`.
- `options.edited_rule(..., every: int | None = None, start: date | None = None)`: `_RULE_FIELDS[WeeklyRule]` adds `"every"`, `"start"`; `REPEAT_ONLY` adds both. `every` given → replace; `start` given → replace; otherwise both keep their stored values. Update the one-time error text in `edit_patch` to list `every` and `start`.
- Parsing `start`: it is a date in the to-do's timezone (for `today`/`tomorrow`). In `/todo repeat weekly`, parse it inside the `create` callback with the effective zone (the same zone logic `adapter.due_input` uses; add a small `adapter.local_date(uow, actor, text, timezone) -> date` rather than duplicating it). In `/todo edit`, use `timezone or current.timezone`, as `date` does there. Format-check it up front with `common.check_options(date_text=start)`.
- `repeat.py` weekly command and `todo_edit.py`: add the options and descriptions from §2.1. Option count stays well under Discord's 25 (weekly: 12, edit: 13). The payload changes, so the global command sync runs once on the next start (expected).

---

## 5. Checklist (one task each; routing per WORKFLOW §3)

1. **BRIEF** — Opus: append D54–D59; §4.3 gets a bullet "**Every N weeks / start date:** a weekly rule may repeat every 2–52 weeks, and `start` keeps it from firing before a date and picks the weeks (D54–D56)"; §8 "every N days/weeks intervals" → "every N days / every N months intervals; start dates for daily/monthly rules"; §6 gets the S9 row.
2. **`core/recurrence.py` + limits** — main session (§3).
3. **Recurrence tests** — Haiku from this case list, added to `tests/unit/test_recurrence.py`, reviewed:
   - the seven rows of §2.3 (`anchored` with now = 2026-11-12 13:00 Europe/Amsterdam, then three to four `next_occurrence` steps);
   - `every:2` with `start` on a Thursday and `days:mon,thu` → the Monday of the start week is skipped (before `start`), the Thursday fires;
   - `every:1` with `start` on a Wednesday and `days:mon,wed` → that Wednesday is the first, the Monday before it is skipped;
   - `start` far in the past (2020-01-06, `every:2`) → phase still right in 2026;
   - `every:52` → next occurrence 52 weeks after the previous one;
   - DST: `every:2`, `days:sun times:02:30` across the 2027-03-28 spring-forward → fires at 03:30 that day, same as plain weekly;
   - `to_json`/`from_json`: `every:1` without `start` unchanged (byte-equal to today's shape, no `every`/`start` keys); `every:1` with `start` → only a `start` key; `every:2` round trip; `every:0`, `every:53`, `every:true`, `every:"2"`, `start:"12-11-2026"` → `InvalidRule`; unknown key still rejected;
   - unanchored (`every:2`, no `start`): `to_json` and `next_occurrence` raise `ValueError`;
   - `anchored`: leaves daily/monthly rules, `every:1` rules without `start` and already-anchored rules alone; `start` 367 days ahead → `InvalidRule`, 366 days → OK (for both `every:1` and `every:2`);
   - `describe`: `every:1` unchanged (also with a `start`); `every:2` and `every:3` wording per D58.
4. **Services + bot** — main session (§4).
5. **Option and service tests** — Haiku, reviewed:
   - `tests/unit/test_options.py`: `weekly_rule` with `every`/`start`; `edited_rule`: `every` on daily → error naming `every`; `every:2` on an `every:1` rule without `start` → `start` None (filled by the service); `every:3` on an `every:2` rule keeps `start`; `every:1` on an `every:2` rule keeps `start`; `start` alone replaces it (for `every:1` and `every:2`); `edit_patch` on a one-time to-do with `every` → error listing `every`.
   - `tests/integration/test_services_todos.py`: create `every:2` without `start` → pending at the first occurrence and `start` stored; with a past `start` → pending in the right week; create `every:1` with a future `start` → pending on the first matching day on/after it; `start` 400 days ahead → `InvalidRule`; edit a plain weekly to-do to `every:2` → the pending occurrence's `due_at` is unchanged; edit `every:2 → 3` keeps `start`; edit to `every:1` → JSON has no `every` key and keeps `start`; changing timezone keeps `start`.
   - `tests/integration/test_scheduler.py`: an `every:2` to-do's claim materializes the next pending two weeks later.
6. **Docs** — Opus: RUNBOOK upgrade note (no migration; **rolling back to a pre-S9 build after someone used `every` or `start` breaks the scheduler**, because older code rejects the unknown keys: finish or delete those to-dos before rolling back); root `README.md` features line; `PROGRESS.md` handoff.
7. **Checks** (WORKFLOW §6): `ruff check .`, `ruff format --check .`, `pytest` with `TEST_DATABASE_URL`. `alembic check` should still be clean (no model change).

---

## 6. Manual test checklist (Tim, dev bot)

- [ ] `/todo repeat weekly title:Bins days:tue times:07:00 every:2 start:<a recent Tuesday>` → reply says "Every 2 weeks on Tuesday at 07:00 (…)"; "Next:" is the right Tuesday (this week or next, depending on the phase).
- [ ] Same without `start` → "Next:" is the very next Tuesday.
- [ ] `/todo repeat weekly … start:<a date next week>` (no `every`) → "Every Tuesday …", "Next:" is the first Tuesday on/after that date.
- [ ] `start` more than a year ahead → refused; `start:31-02-2027` → date hint.
- [ ] `/todo show` and `/todo list` show the "Every 2 weeks …" description.
- [ ] Time test: an `every:2` to-do with `times` = now+2 min and `days` = today → reminder posts; check it off → "Next:" is two weeks later.
- [ ] `/todo edit` an existing plain weekly to-do with `every:2` → "Next:" doesn't change. Then `every:3` → the weeks keep counting from the same start. Then `every:1` → back to "Every Tuesday …".
- [ ] `/todo edit` a daily to-do with `every:2` → "This to-do repeats daily, so `every` can't be changed…".
- [ ] `/todo upcoming days:30` shows an every-2-weeks to-do only in its on-weeks.

## Acceptance
All checks green; the §2.3 examples pass as tests; old weekly rules round-trip unchanged; Tim's manual checklist passes on the dev bot; BRIEF/RUNBOOK/README/PROGRESS updated by Opus.

---

## Tim's answers (2026-11-12)

1. One command or two? → an `every` option on `/todo repeat weekly` (D54).
2. Default phase → the first reminder is the soonest possible (D56).
3. Week start → Monday (D55).
4. `start` with `every:1` → allowed, as "don't start before this date" (D56). Only weekly rules for now; daily/monthly start dates stay out of scope.
5. Range 1–52 weeks → yes (D54).
