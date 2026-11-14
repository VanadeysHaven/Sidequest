# Brief — Weekday dates, suspensions, per-day times, start and end dates

**Status:** done (Segments 1–4, incl. D98) · **Branch:** `claude/dates-and-schedules` · **Migration:** none (all new data lives in
the rule JSON) · Written by Claude (Opus 5.5), 2026-11-14.

Four features, one segment each, **numbered in build order**: run Segment 1, 2, 3, 4, one per session.
Start/end (2) comes before suspensions (3) because suspensions need "a repeating to-do can run out of
occurrences", which Segment 2 introduces. Each segment ends with green checks, its Handoff lines and a
stop for Tim. (Tim's original numbering: 1 weekday dates, 2 suspensions, 3 per-day times, 4 start/end.)

**Read first:** `CLAUDE.md` §3 (how the pieces talk), §4 (repeating rules, occurrences and reminders),
§5. Main code: `core/timeparse.py`, `core/recurrence.py`, `services/_common.py` (`add_next_pending`,
`finish_occurrence`, `todo_view`), `services/todos.py` (`create_recurring`, `_retime_recurring`, `complete`),
`services/occurrences.py` (`claim_due`, `complete_occurrence`), `services/undo.py`, `bot/options.py`,
`bot/adapter.py` (`due_input`, `local_date`), `bot/commands/repeat.py`, `bot/commands/todo_edit.py`,
`bot/views/confirm.py`, `bot/render.py` (`when`, `short_when`, `todo_embed`).

**Who does what.** Main session: everything in `core/recurrence.py`, services, scheduler and the new views.
Haiku (`model: "haiku"`, self-contained prompt, reviewed): the table-driven tests listed per segment,
copying an option or wiring pattern to the other commands once the first one is done, and check runs.
Opus: docs.

**Shown dates.** Points in time stay Discord timestamps (D1). Plain dates (start, end, suspensions) are
not points in time; they're shown as `DD-MM-YYYY` (e.g. `16-11-2026`), with "today" where that's clearer.

---

## Segment 1 — A weekday is a date

### Decisions (D70–D72)

| ID | Decision | Source |
|---|---|---|
| D70 | **Every date option accepts a weekday name**: `mon`…`sun`, full names, `tue/tues`, `weds`, `thu/thur/thurs` (the `days` words without `weekdays`/`weekend`), any case. It becomes the next date with that weekday, in the zone the to-do uses (as `today`/`tomorrow`). Applies to `/todo add date`, `/todo edit date`, `start` and `end` (Segment 2) and the suspension dates (Segment 3). | Tim |
| D71 | **Weekday = today.** With a time (`/todo add date+time`; `/todo edit date`, which keeps the current time when none is given): today if that moment is still to come, otherwise the same weekday next week. For date-only options (`start`, `end`, suspensions): today counts. `today` itself keeps its old behaviour (a past moment is refused). | Tim (timed), Claude (date-only) |
| D72 | **Wording.** `DATE_HINT` becomes "Use YYYY-MM-DD or DD-MM-YYYY (e.g. 2026-11-12), today, tomorrow or a weekday (e.g. monday)." Option descriptions mention "or a weekday" (≤ 100 chars). `next monday` and similar are not supported. | Claude |

Example (today Sat 14-11-2026): `monday` → 16-11-2026. On Monday 16-11 at 14:00, `date:monday time:14:30`
→ 16-11 14:30; at 15:00 → 23-11 14:30.

### Implementation
- `core/timeparse.py`: `parse_date(s, today)` resolves weekday words (today if it matches, else the next
  one). New `is_weekday_word(s) -> bool`. Share the word table with `parse_weekdays` (minus the groups).
- `DueInput` gets `roll_week: bool = False` ("came from a weekday name: if the moment has passed, use the
  same weekday next week"). `resolve_due(..., *, roll_week=False)`: if `roll_week` and the moment is
  `<= now`, add 7 days (resolve again for DST) instead of raising `InPast`.
- `adapter.due_input` sets `roll_week=is_weekday_word(date_text)`. `options.edit_patch` keeps the flag when
  it fills in the current time.
- `common.check_options` already validates the format with a dummy date; weekday words pass.

### Checklist
1. [x] Core + adapter + options + descriptions — **Haiku** from this section, reviewed.
2. [x] Tests — **Haiku**, reviewed: `parse_date` for every word from a Wednesday and on the matching day;
   `is_weekday_word`; `resolve_due` with `roll_week` (later today, earlier today, exactly now → next week,
   DST week in Europe/Amsterdam); `edit_patch` keeping the flag; a non-weekday date unchanged.
3. [x] Docs — Opus: `CLAUDE.md` §4 (dates line), §6 (D70–D72); README features line.
4. [x] Checks (CLAUDE.md §7). Handoff.

### Manual test (Tim)
- [x] `/todo add date:monday time:14:30` → due next Monday 14:30.
- [x] On the weekday itself: a time still to come → today; a time already gone → next week.
- [x] `/todo edit todo:<timed> date:friday` → Friday, same time.
- [x] `date:mondy` → error with the new hint.

---

## Segment 2 — Start and end dates for repeating to-dos

### Decisions (D73–D80)

| ID | Decision | Source |
|---|---|---|
| D73 | **All four `/todo repeat` commands get `start` and `end`** (optional dates, inclusive, weekday names work). `/todo edit` gets `end`, and `start` for every repeating to-do (was weekly only). `start:none` / `end:none` in `/todo edit` removes it. Weekly with `every` ≥ 2 keeps D54–D59: `start` also picks the on-weeks; removing it re-anchors to the next occurrence (D56). Takes "start dates for daily/monthly rules" off the out-of-scope list. | Tim |
| D74 | **First and last.** The first reminder is the first occurrence on or after `start`, the last is the last one on or before `end` (dates in the to-do's zone). `start`/`end` don't have to be matching days. | Tim, Claude (non-matching days) |
| D75 | **Validation.** `start` at most a year ahead (`START_AHEAD_MAX_DAYS`, now for all rules); `end` ≥ `start`; at least one occurrence between now (or `start`) and `end`, else "No reminder of **title** falls between DD-MM-YYYY and DD-MM-YYYY." Exception on edit: when a reminder is up, an `end` that leaves nothing after it is allowed, and that reminder becomes the last. `end` has no upper limit. | Claude |
| D76 | **Running out.** After the last occurrence is posted, nothing new is scheduled: a repeating to-do can now have **no pending occurrence**. Its last reminder stays up until it's checked off (nothing replaces it, so D7 doesn't apply). After downtime past `end`, the one catch-up reminder is the last. | Claude |
| D77 | ~~**Confirm the last one.**~~ **Dropped (Tim, 2026-11-14, after the build): no extra confirmation; checking off the last one works like any check-off (D67 still applies).** Original: Checking off the last occurrence (reminder Done, `/todo done`, `/todo show` → Done, `/todo upcoming` early) first asks "This is the last reminder of **title** (it ends on DD-MM-YYYY). Checking it off marks the to-do done. Check it off?" with **Check off** / **Cancel**. When the D67 non-assignee question applies too, it's one message with both sentences. Ticking subtasks never asks. | Tim |
| D78 | **The last check-off marks the to-do done**, like a one-time to-do (`completed_at/by` set, kept in history, off the open lists). **Its name is free again** at once (the open-title index only covers open to-dos, D44). | Tim |
| D79 | **Undo** of the last check-off reopens the to-do and restores the occurrence as usual (D63/D64). It's refused with the title-clash message when an open to-do on the list has taken the name since. | Claude |
| D80 | **Display.** The rule description ends with ", from DD-MM-YYYY" (only while `start` is still ahead) and ", until DD-MM-YYYY". `render.when`: "Next: …"; when the next one is the last, "Next (last): …"; when the last is up and nothing follows, "Last reminder — nothing after this one". `short_when` shows "🔁 last: …" for the final one. | Claude |

### Implementation
- **`core/recurrence.py`** (main session):
  - Move `start` from `WeeklyRule` to `_Rule` and add `end: EndDate | None = None`; `to_json` leaves both
    out when unset (old rows keep their shape). Validate `end >= start` in a model validator.
  - `_matches` checks the window for every rule type. `next_occurrence(...) -> datetime | None`: **None
    means the series is over** (search stops after `end`). `InvalidRule("no upcoming occurrence")` stays
    only as the bug guard when the search runs out without an `end`. Update `occurrences_between` and
    `anchored` for None.
  - `anchored`: the start limit for all rules; it doesn't check "something left" (the service does,
    because of the D75 exception).
  - `describe(rule, tz, today: date | None = None)`: D80 suffixes (`from` only when `start > today`).
- **Services:** `add_next_pending` returns `Occurrence | None`. Callers: `create_recurring` (None →
  refuse, D75), `_retime_recurring` (None and no sent reminder → refuse), `claim_due` (None → nothing),
  `finish_occurrence` (None → no follow-up, `followup_id=None`; and when the occurrence being checked off
  is the last, mark the to-do done with `mark_todo_done`).
  - "Last": an open occurrence with no other pending one after it and `next_occurrence(after its
    due_at) is None`. `TodoView` gets `final_occurrence_id: int | None` (computed in `todo_view`) and
    `ends_on: date | None`.
  - `services/undo.py`: when the token's check-off finished the to-do, reopen it (`status=open`,
    `completed_*` cleared) behind `require_unique_title` + `flush_titles`, then restore the occurrence as
    today. A repeating undo with `followup_id=None` and `previous=pending` has nothing to cancel.
  - Keep `todos.py` under ~400 lines: move helpers into `_common.py` or a new module if needed.
- **Bot:** `start`/`end` on daily, monthly-weekday, monthly-day (copy the weekly pattern — **Haiku** after
  the first); `edit_patch`/`edited_rule`: `start`/`end` allowed for all rule types, a `CLEAR` sentinel for
  `none`. `views/confirm.py`: `must_confirm(actor, todo, occurrence_id)` is true for non-assignees or the
  final occurrence; `render.check_off_prompt(todo, *, not_assignee, last)` builds one message.
  The created/edited reply shows the description with its dates.
- **Runbook:** add "Upgrading to dates-and-schedules": no migration, but **rolling back is unsafe** once
  a to-do uses `start`/`end` on a non-weekly rule, `end`, suspensions or per-day times: older code
  rejects the new JSON keys (`extra="forbid"`). Rollback = restore the pre-upgrade backup.

### Checklist
1. [x] Recurrence core — main session.
2. [x] Core tests — **Haiku**, reviewed (`tests/unit/test_recurrence_window.py`): every rule type with
   `start` only / `end` only / both; first = first match on/after start, last = last match on/before
   end; non-matching start/end days; `end < start` refused; JSON round-trip and old shapes unchanged;
   `next_occurrence` → None after the last; `every` ≥ 2 with `end`; DST day as last day; `describe`
   suffixes.
3. [x] Services — main session (above).
4. [x] Service tests — **Haiku**, reviewed: create with nothing in the window refused; scheduler posts
   the last one and leaves no pending; catch-up past `end` gives one late reminder and nothing after;
   last checked off (reminder, early, `/todo done`) → to-do done, name free (new open to-do with the same
   title works); undo reopens; undo refused after the name was taken; edit `end` earlier cancels a pending
   occurrence past it; the D75 exception with a reminder up; `start:none`/`end:none`; `final_occurrence_id`.
5. [x] Bot — main session for the render; **Haiku** for the option copies (the confirm was dropped, D77).
6. [x] Render unit tests — **Haiku**: `when`/`short_when` for next, next-last, last-up; prompt with
   last only, non-assignee only, both.
7. [x] Docs — Opus: `CLAUDE.md` §4 (rules, "at most one pending, none after the last"), §6 D73–D80,
   out-of-scope list; README; runbook note.
8. [x] Checks. Handoff.

### Manual test (Tim)
- [x] `/todo repeat daily times:20:00 start:monday end:wednesday` → `/todo show` says "from … until …",
      fires Mon, Tue, Wed.
- [x] Done on Tuesday's reminder → the reply says "Next (last): …"; `/todo show` too, `/todo list`
      shows "🔁 last: …".
- [x] Wednesday's reminder up → `/todo show` says "Last reminder — nothing after this one".
- [x] Done on it (no extra question) → the reply ends with `render.LAST_DONE` ("This was the last
      occurance of this reminder, …"); the to-do is gone from `/todo list`.
- [x] Undo it → back, reminder re-posted. Check it off again → a new to-do with the same title can
      be added.
- [x] Non-assignee on the last one → only the usual "assigned to …, not you" question.
- [x] `/todo edit end:none` → back to repeating forever.
- [x] `end` before any occurrence → refused with the dates.

---

## Segment 3 — Suspending a repeating to-do

### Decisions (D81–D89)

| ID | Decision | Source |
|---|---|---|
| D81 | **Suspensions.** A repeating to-do can be suspended between two dates, inclusive, in its zone: no reminder fires on those days; it carries on with the first occurrence after the end day. Repeating to-dos only. Several per to-do, **never overlapping** (touching is fine), at most 10 current/upcoming (`SUSPENSIONS_MAX`). | Tim |
| D82 | **`/todo suspend todo [start] [end]`**, at least one date. Only `start` → just that day. Only `end` → from now until `end`. Both → that range. `start` ≥ today, `end` ≥ `start`, `end` at most a year ahead. Weekday names work (today counts, D71). | Tim (forms), Claude (limits) |
| D83 | **What "now" covers.** Reminders that have already fired, including one that is up right now, are not affected: it stays and can be checked off. Only reminders still to come are skipped. | Claude |
| D84 | **Always confirm.** ~~The reply lists every reminder that would be skipped (`<t:…:f>`, oldest first, within the to-do's `end`): up to 20 lines, then "…and N more (M in total)".~~ **Changed by Tim (2026-11-14, after the build):** "Are you sure you want to suspend **title** from DD-MM-YYYY to DD-MM-YYYY. The following N occurrence(s) will be skipped:", then every skipped reminder as `<t:…:f> (<t:…:R>)`, oldest first, 20 per page with ◀ Prev / Next ▶ and "Page N/M". Buttons **Suspend** / **Cancel** (5 minutes). The service re-checks everything on Suspend. Reply: "⏸️ **title** is suspended from DD-MM-YYYY to DD-MM-YYYY. Next: <ts>". | Tim (confirm with list), Claude (cap, wording) |
| D85 | **Refused** (before the confirm, and again on Suspend): nothing to skip ("No reminder of **title** falls between …"); overlap ("That overlaps the suspension from DD-MM-YYYY to DD-MM-YYYY. Cancel that one first, or pick other dates."); it would skip every remaining reminder of a to-do with an `end` while none is up ("That would skip every remaining reminder. Change the end date or delete the to-do instead."); more than 10. | Claude |
| D86 | **Cancel with `/todo unsuspend todo suspension`**; `suspension` autocompletes that to-do's current and upcoming suspensions ("16-11-2026 – 22-11-2026", "today – 22-11-2026"), like `/todo subtask remove`. No confirm (adding it again is easy). Reminders skipped earlier don't come back; the next one is the first still to come. Reply: "▶️ Suspension from … to … cancelled. Next: <ts>". | Tim (cancellable), Claude (command) |
| D87 | **Display.** `/todo show` gets a "Suspended" field with current and upcoming suspensions. `short_when` adds "⏸️ until DD-MM-YYYY" while one is running. `Next:` already skips them. | Claude |
| D88 | **Storage: in the rule JSON**, `"suspended": [{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}, …]`, sorted, left out when empty; no migration. Finished ones (`end` < today) are dropped whenever the rule is written. Rule edits and timezone changes keep them as the same local dates. | Claude |
| D89 | **Permissions and schedule.** Same rights as editing (`require_edit`). Suspend and unsuspend replace the pending occurrence like an edit does, so an earlier check-off can then no longer be undone ("changed after it was checked off", D65). | Claude |

### Implementation
- **Core** (main session): `DateRange(start, end)` (frozen, `start <= end`, JSON as above) and
  `_Rule.suspended: tuple[DateRange, ...] = ()`; `_matches` is False on a suspended day. Helpers:
  `with_suspension(rule, rng)` (overlap → `InvalidRule`), `without_suspension(rule, start)`,
  `pruned(rule, today)`. The preview is `occurrences_between(rule, tz, max(now, start 00:00), end+1 00:00)`
  of the rule as it is now.
- **Services:** new `services/suspensions.py`: `preview(uow, actor, todo_id, start, end) ->
  SuspensionPreview(start, end, skipped: tuple[datetime, ...], total: int)` (no write), `suspend(...) ->
  Outcome[TodoView]`, `unsuspend(uow, actor, todo_id, start: date) -> Outcome[TodoView]`,
  `current(uow, actor, todo_id) -> tuple[DateRange, ...]` (autocomplete). Lock the to-do; write the
  pruned rule; `cancel_open(include_sent=False)` + `add_next_pending(after=now)`; `changed_schedule=True`.
  Dates come in as `date | None`; the service fills in today (in the to-do's zone) and applies D82.
- **Bot:** `bot/commands/todo_suspend.py` with both commands; autocomplete `suspension` reads
  `namespace.todo` (value = ISO start date). Confirm view in `views/confirm.py` or `views/suspend.py`.
  Wire the second command after the first — **Haiku** may do `unsuspend` + autocomplete from the pattern.

### Checklist
1. [x] Core — main session. 2. [x] Core tests — **Haiku**: skipping days, touching vs overlapping,
   pruning, JSON round-trip, `next_occurrence` across a suspension, with `end`.
3. [x] Services — main session. 4. [x] Service tests — **Haiku**: the three D82 forms (incl. "only end" on
   a day whose earlier reminder already fired); preview count and cap; each D85 refusal; reminder up stays
   (D83); unsuspend reschedules earlier; undo after suspend refused as changed; one-time to-do refused;
   permissions.
5. [x] Bot — main session. 6. [x] Render tests — **Haiku**: preview text with 0/3/25 entries,
   the Suspended field, `short_when` marker.
7. [x] Docs — Opus: `CLAUDE.md` §4 (new subsection), §6 D81–D89; README. 8. [x] Checks. Handoff.

### Manual test (Tim)
- [x] `/todo suspend todo:<daily> start:monday end:wednesday` → list of the skipped reminders → Suspend →
      nothing fires Mon–Wed, Thursday does.
- [x] `start` only → only that day; `end` only → from now.
- [x] A long range on a daily with several times → 20 lines with relative times,
      "Page 1/N", ◀ Prev / Next ▶ page through all of them.
- [x] Overlapping second suspension refused; touching one accepted.
- [x] `/todo unsuspend` autocompletes both; cancel one → Next moves earlier.
- [x] `/todo show` lists them; `/todo list` shows ⏸️ while one runs.

---

## Segment 4 — Different times per weekday (week builder)

Tim chose the **week builder** over a schedule text option or a per-day override command (2026-11-14).

### Decisions (D90–D97)

| ID | Decision | Source |
|---|---|---|
| D90 | **Weekly rules can have different times per weekday** (e.g. Mon 05:10, Tue 07:30, Wed–Thu 05:10, Sat 09:00 and 18:00). 1–12 times per day. | Tim |
| D91 | **Storage.** Same times on every chosen day → the existing `weekdays` + `times` shape (old rows unchanged). Otherwise `"day_times": {"mon": ["05:10"], "tue": ["07:30"], …}` replaces both. The model normalises (collapses equal times back) and gives `times_for(day)`; `next_occurrence` uses it. `every`, `start`, `end`, `suspended` work as before. | Claude |
| D92 | **Opening the builder: `/todo repeat weekly custom-times:true`.** `days` and `times` become optional: without `custom-times` both are required ("Give `days` and `times`, or set `custom-times:true` to build the week."); with it, both given together prefill the builder (one alone is an error). All other options are taken as usual. | Tim |
| D93 | **Layout.** Ephemeral message: embed "Week for **title**", seven lines Mon–Sun (times, or "—"), footer with the zone and every/start/end. Row 1: multi-select **Set times for…** (Mon–Sun; each option's description = its times or "off"); closing it opens the modal "Times for Mon, Wed and Thu" (one field, prefilled when the picked days share times, placeholder `05:10, 18:00`). Row 2: multi-select **Turn days off…**. Row 3: **Save**, **Cancel**. After each change the selection resets and the embed updates. *(Changed after Tim's test, 2026-11-14: the first layout's Pick days + Set times button needed two clicks.)* | Tim (builder, layout change), Claude (details) |
| D94 | **Save / Cancel / timeout.** Save needs at least one day with times. With `details:true`, Save opens the details modal, then creates (same as `create_flow`). The reply is today's created text with the week. Cancel → "Not added." (edit: "Nothing changed."). Owner-only, **15-minute** timeout → "This week editor expired; nothing was saved." | Claude |
| D95 | **Editing: `/todo edit todo custom-times:true`** on a weekly to-do opens the builder with its current week. It can be combined with the other edit options except `days`/`times`; all are applied together on Save. On another rule type: the usual "can't switch the repeat type" error. | Claude |
| D96 | **`days:`/`times:` on a to-do with per-day times are refused** in `/todo edit`: "**title** has different times per day; use `custom-times:true` to change its week." (No guessing which day gets what.) | Claude |
| D97 | **Description** groups days with equal times, in weekday order: "Every Monday, Wednesday and Thursday at 05:10, Tuesday at 07:30 and Saturday at 09:00 and 18:00 (Europe/Amsterdam)", plus the D80 suffixes. | Claude |
| D98 | **`all` in `days`** means Monday–Sunday, next to `weekdays` and `weekend` (any case; mixes with other words, e.g. `all,mon`). Only `all`: no `daily`/`everyday`. Not a date word (D70 dates are unchanged). Works wherever `days` is parsed: `/todo repeat weekly` (also as builder prefill) and `/todo edit`. The `days` descriptions and the unknown-weekday hint mention it. | Tim (2026-11-15) |

### Implementation
- **Core** (main session): `WeeklyRule` with optional `day_times`, normalising validator, `times_for`,
  JSON per D91, `describe` per D97; `edited_rule` raises D96.
- **Bot** (main session): `bot/views/week_builder.py` — `WeekBuilderView(BaseView)` holding a
  `dict[Weekday, tuple[time, ...]]`, `timeout=900`, an `on_save(interaction, rule)` callback, and a
  `TimesModal(BaseModal)` that parses with `parse_times`. `render.week_embed(title, week, tz, rule extras)`.
  `/todo repeat weekly` and `/todo edit` build the callback (create via `todos.create_recurring` /
  edit via `todos.edit`), reusing `create_flow`'s details step on Save.

### Checklist
1. [x] Core — main session. 2. [x] Core tests — **Haiku**: JSON round-trip both shapes, collapsing,
   `next_occurrence` across a mixed week incl. DST, with `every` 2 and suspensions, ≤ 12 per day,
   `describe` grouping, D96 refusals.
3. [x] Builder view + commands — main session. 4. [x] Render tests — **Haiku**: `week_embed` lines and
   select descriptions.
5. [x] Docs — Opus: `CLAUDE.md` §4 rules, §3 package map (new view), §6 D90–D97; README.
6. [x] Checks. Handoff.
7. [x] D98 — main session: `all` in `_WEEKDAY_WORDS` (`core/timeparse.py`), the `days` option
   descriptions (`repeat.py`, `todo_edit.py`) and the error hint; tests in `test_timeparse.py`;
   `CLAUDE.md` §6 D98; checks; Handoff line.

### Manual test (Tim)
- [x] `/todo repeat weekly title:Gym custom-times:true` → Set times for… Mon, Wed, Thu → 05:10 → Tue
      → 07:30 → Sat → 09:00, 18:00 → Save (each form opens on the first try) → description as D97, reminders fire at those times.
- [x] Prefill with `days:weekdays times:05:10`, change Tuesday only.
- [x] Turn days off… a day; Save with no days → refused.
- [x] `details:true` → details form after Save.
- [x] `/todo edit todo:Gym custom-times:true` shows the current week; Save changes the next reminder.
- [x] `/todo edit todo:Gym times:06:00` → D96 message.
- [x] Leave the builder for 15 minutes → expired text.
- [x] `/todo repeat weekly title:Walk days:all times:07:00` → "Every Monday, Tuesday, … and Sunday at 07:00";
      `days:all times:05:10 custom-times:true` prefills all seven days (D98).

---

## Tim's answers (2026-11-14)

Numbered by Tim's original feature order.

1. Weekday on today → today if the time is still to come, else next week (D71).
2. Suspension forms (one day / from now / range), confirmation listing every skipped reminder,
   cancellable, several per to-do, never overlapping (D81–D86).
3. Per-day times UI → the week builder via `custom-times:true` (D92–D95).
4. Start/end inclusive; confirm on the last occurrence (D73–D77).
5. After the last check-off the to-do is **marked done** (not deleted), and its name is free again (D78).

## Handoff
(per segment, filled in by the session that builds it)

### Segment 1 — 2026-11-14
- **Built:** weekday names in every date option (`core.timeparse._DAY_WORDS`, shared with
  `parse_weekdays`; `is_weekday_word`; `parse_date` → next such day, today included).
  `DueInput.roll_week` → `resolve_due(..., roll_week=)` adds 7 days (resolved again) instead of
  `InPast`; set by `adapter.due_input`, kept by `options.edit_patch`, passed in `create_once` and
  `_retime_once`. New `DATE_HINT`; `date`/`start` descriptions say "or a weekday" (edit `start`: 91 chars).
- **Tests:** `test_timeparse.py` (+53 cases: every word from a Wednesday, matching day, rejected words,
  `is_weekday_word`, `roll_week` incl. both DST changes), `test_options.py` (+3, flag kept).
- **Checks:** ruff check/format clean; full `pytest` with the test Postgres: 710 passed, 0 skipped.
  No model change, so no `alembic check`.
- **Deviations:** none. `start` (weekly) already went through `parse_date`, so it accepts weekday names
  with "today counts" as D71 asks for date-only options.
- **Open questions:** none.
- **Manual tests:** all four passed on the dev bot (Tim, 2026-11-14).

### Segment 2 — 2026-11-14
- **Built:** `start`/`end` on `_Rule` (all types, JSON keys only when set, `end ≥ start` validator);
  `_matches` checks the window; `next_occurrence` → `None` when the series is over;
  `anchored` checks the year-ahead limit for every rule; `describe(rule, tz, today)` with the D80
  suffixes; `core.text.plain_date` (DD-MM-YYYY). New `services/_series.py` (`final_occurrence`,
  `is_over`, `require_upcoming`, `nothing_between`). `add_next_pending` → `Occurrence | None`;
  `finish_occurrence` marks the to-do done after the last one (`UndoToken.finished`); `undo` reopens it
  behind the title check. `TodoView.final_occurrence_id`/`ends_on`; `todo_view` takes `now`. Bot:
  `start`/`end` on all four repeat commands (`repeat.window` → `options.with_window`, validated),
  `/todo edit start|end` for every rule with `none` (`options.CLEAR`, `adapter.edit_date`);
  `render.when`/`short_when`; `render.done_text` says "Next (last): …" before the final one and
  adds `LAST_DONE` (Tim's wording) after it (Tim's requests). The D77 confirmation was built and then removed at
  Tim's request (views, `confirm.py` and `check_off_prompt` are unchanged from before the segment).
- **Tests:** `test_recurrence_window.py` (70), `test_services_series_end.py` (21, integration),
  `test_render.py` (+21); three weekly `describe` cases now pass `today` (pattern only).
- **Checks:** ruff check/format clean; full `pytest` with the test Postgres: 822 passed. No model
  change, so no `alembic check`.
- **Deviations:**
  - When `end` is already past, the D75 refusal reads "No reminder of **title** is left: it ends on
    DD-MM-YYYY." ("falls between" would show a backwards range).
  - `/todo done` on an open repeating to-do with nothing open whose series is over (its last reminder
    failed, e.g. no channel) marks it done (undoable) instead of "nothing to check off right now";
    otherwise it would stay open forever.
  - Weekly `every` ≥ 2 without `start` and nothing left before `end` anchors to today (the service
    then refuses, or the D75 exception keeps the reminder as the last).
  - `describe` with `today=None` always shows "from" (the services always pass today).
  - `services/_common.py` is ~415 lines (the series logic went to `_series.py`).
- **Open questions:** none. (An `end` earlier than the reminder that's up is accepted and that
  reminder becomes the last: kept, Tim 2026-11-14.)
- **Manual tests:** all passed on the dev bot (Tim, 2026-11-14).

### Segment 3 — 2026-11-14
- **Built:** `recurrence.DateRange` and `suspended` on every rule (sorted, no overlap, JSON key
  only when set); `_matches` skips suspended days; `pruned` (also run by `anchored`),
  `with_suspension`, `without_suspension`, `suspended_until`. New `services/suspensions.py`
  (`preview`, `suspend`, `unsuspend`); `TodoView.suspensions` / `suspended_until`
  (`_series.suspension_views`). Bot: `commands/todo_suspend.py` (`/todo suspend`,
  `/todo unsuspend`), `views/suspend.py` (`SuspendConfirmView`), `autocomplete.suspension`,
  render `suspension_label`, `suspend_preview_text`, `suspended_text`, `unsuspended_text`, the
  "Suspended" field and the `short_when` marker; `render.next_line` shared by `when`.
  Limits `SUSPENSIONS_MAX`, `SUSPENSION_PAGE_SIZE`. After Tim's review: the confirmation uses
  his wording, shows relative times and pages through every skipped reminder (the preview
  returns all of them; `SuspendConfirmView` has ◀ Prev / Next ▶, re-rendering only).
- **Bug fix (Tim asked for it during the session):** `/todo edit` of a repeating to-do whose next
  reminder had been checked off early brought that reminder back (the new pending one was picked
  from now). New `_series.schedule_base`: the series continues after the latest sent or
  checked-off occurrence, never before now; used by `_retime_recurring`, suspend and unsuspend.
  Test: `tests/integration/test_services_edit_after_early.py`.
- **Tests:** `test_recurrence_suspended.py` (83), `test_services_suspensions.py` (37,
  integration), `test_render_suspensions.py` (31), `test_services_edit_after_early.py` (3).
- **Checks:** ruff check/format clean; full `pytest` with the test Postgres: 969 passed. No model
  change, so no `alembic check`.
- **Deviations:**
  - No `suspensions.current()` service: the autocomplete reads `todos.get(...).suspensions`, like
    the subtask autocomplete. `suspend`/`unsuspend` return `SuspensionChange(todo, suspension)`
    instead of a bare `TodoView` (the replies need the range).
  - Wording: in the replies after Suspend / unsuspend a one-day suspension says "for
    16-11-2026" and one that has started says "today"; the unsuspend reply names the to-do
    ("▶️ Suspension of **title** from … to … cancelled."). The confirmation always shows both
    dates, as in Tim's wording, with "occurrence" / "occurrences" by count.
  - `start` before today: "A suspension can't start before today."
  - `bot/render.py` is now ~465 lines and `services/_common.py` 416 (over the ~400 guideline);
    the suspension text could move to its own render module later.
- **Open questions:**
  - With the edit fix, checking off tonight's 20:00 early and then changing the times to
    `20:00, 22:00` still schedules tonight's 22:00 (only occurrences up to the checked-off one are
    skipped). Should an early check-off cover the rest of that day instead?
- **Manual tests:** all passed on the dev bot, incl. the edit fix (Tim, 2026-11-14).

### Segment 4 — 2026-11-14
- **Built:** `WeeklyRule.day_times` (D91): a `day_times` input collapses to `weekdays` + `times`
  when every day has the same times, else keeps `day_times` with `times == ()`; `has_day_times`,
  `times_for`, `week`, `recurrence.with_week`, `WeekTimes`. `next_occurrence` uses each day's
  times; `to_json` writes either shape; `describe` groups days (D97). `options`:
  `weekly_prefill` (D92), `check_window`, `edited_rule(custom_times=, title=)` with the D96
  refusal and "`custom-times` can't be combined with `days` or `times`."; `edit_patch(custom_times=)`.
  Bot: `views/week_builder.py` (`WeekBuilderView`, `TimesModal`), `render_week.py`,
  `/todo repeat weekly custom-times` (`repeat.week_builder_flow`), `/todo edit custom-times`
  (`todo_edit._open_week_builder`).
- **Tests:** `test_recurrence_day_times.py` (75), `test_render_week.py` (30), both by Haiku and
  reviewed. The brief's "exactly 7 occurrences" for the mixed week was a typo in Claude's test
  spec; the week has 6 reminders and the test checks 6.
- **Checks:** ruff check/format clean; full `pytest` with the test Postgres: 1074 passed. No model
  change, so no `alembic check`.
- **Deviations:**
  - Timeout is **14.5 minutes** (`WEEK_BUILDER_TIMEOUT = 870`), not 15. Discord's interaction
    tokens last 15 minutes, so at exactly 15 the "expired" edit would fail. The view edits the
    message with the token of the latest click or modal (`view.interaction`).
  - The render code lives in a new `bot/render_week.py`, not `render.py` (already ~477 lines).
  - `/todo edit custom-times:true` checks edit rights before opening the builder (`can_edit`),
    so nobody builds a week only to be refused on Save.
  - Save, Cancel and success replace the builder message itself (no new reply). A refusal on
    Save (e.g. title taken, nothing before `end`) is shown ephemerally and the builder stays open.
  - Extra messages: Save with no days → "Set times for at least one day first."; one of
    `days`/`times` with `custom-times` → "To fill in the week, give both `days` and `times` (or
    neither)."; `custom-times` on a daily/monthly to-do → the usual type error naming
    `custom-times`.
  - **Layout change after Tim's test (D93):** a separate Set times button needed two clicks
    (Discord sends a multi-select only when it closes; the click that closes it doesn't reach
    the button). Now closing **Set times for…** opens the times form, and **Turn days off…**
    replaces Clear. Known limit: if you close the times form without submitting, the picked
    days stay shown; change the selection to open it again.
- **D98 (2026-11-15):** `all` added to `_WEEKDAY_WORDS`; the `days` descriptions and the
  unknown-weekday hint mention it; 4 cases added to `test_timeparse.py` (also: `all` is no
  date word). Full `pytest`: 1079 passed.
- **Open questions:** none new. (Segment 3's question about early check-off + time edits stands.)
- **Manual tests:** all passed on the dev bot, incl. `days:all` (Tim, 2026-11-15).
