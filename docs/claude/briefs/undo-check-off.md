# Brief — Undo a check-off, and confirm when you're not an assignee

**Status:** waiting for review. Built 2026-11-12; checks green (654 tests). Tim's manual test (§6) is still open.
**Branch:** `claude/undo-check-off` · **Migration:** none · Written by Claude (Opus 5.5), 2026-11-12.

**Goal:** a check-off is no longer a one-way street. Wherever something is checked off, the reply gets an
**Undo** button that works for 2 hours and puts everything back, including a reminder that was deleted.
And someone who isn't an assignee is asked to confirm before they check a to-do off.

**Read first:** `CLAUDE.md` §3 (how the pieces talk) and §4 (occurrences and reminders). Code you'll touch:
`services/_common.py` (`finish_occurrence`, `close`, `reset_subtasks`, `mark_todo_done`, `require_complete`,
`require_unique_title`, `flush_titles`), `services/todos.py` (`complete`), `services/occurrences.py`
(`complete_occurrence`, `_lock_occurrence`, `attach_message`, `unposted_sent`, `_reminders`),
`services/dto.py`, `scheduler/loop.py` (`deliver`, `recover`), `bot/client.py` (`_scheduler`),
`bot/render.py` (`done_text`), `bot/views/base.py`, `bot/views/reminder.py` (`DoneButton`),
`bot/views/show.py`, `bot/views/upcoming.py`, `bot/views/confirm.py`, `bot/commands/todo_manage.py`
(`done_command`).

---

## 1. Decisions (new, D60–D69)

| ID | Decision | Source |
|---|---|---|
| D60 | **Undo button** on every check-off reply: a reminder's Done (its ephemeral "✅ Checked off" reply), `/todo done`, `/todo show` → Done, and `/todo upcoming` → check off early. | Tim |
| D61 | **Undo works for 2 hours** after the check-off. It is an ordinary in-memory view (2-hour timeout), so it **does not survive a bot restart**: after a restart or after 2 hours, pressing it gets Discord's "This interaction failed". The service also refuses an undo more than 2 hours after `completed_at`, as a guard. | Tim |
| D62 | **Only the person who checked it off can undo it**, not other collaborators or admins, and only while they may still check off on that list. (The button sits on their own reply anyway; the service checks it too.) | Tim |
| D63 | **Undo restores the state from before the check-off:** a one-time to-do is open again; the occurrence goes back to what it was (`pending` or `sent`); an occurrence that the check-off created (the next one of a repeating to-do) is cancelled; subtask ticks that the check-off reset come back, for subtasks that still exist and haven't been ticked since. | Claude |
| D64 | **A reminder that was up comes back**: re-posted in the reminder channel as a new message, **pinging the assignees again**, keeping its "Late — was due …" marker if it had one. A reminder that was still pending (checked off early) just goes back to pending; if its time has passed in the meantime, it posts straight away. | Tim (ping), Claude |
| D65 | **Undo is refused** (ephemeral error, nothing changes) when: more than 2 hours have passed; it was already undone; the to-do was deleted or edited after the check-off; for a repeating to-do, the next reminder already went out (two open reminders aren't allowed, D7), or the next occurrence was itself checked off after this one (undo that one first); for a one-time to-do, another open to-do on the list now has the same title (D44); the user may no longer check off on that list. | Claude |
| D66 | **No storage change.** What undo needs (previous occurrence status, the follow-up occurrence's id, the subtask ticks that were reset) is returned by the check-off service as an `UndoToken` and kept in the Undo view's memory. The service re-checks everything against the database before using it. | Claude (follows from D61) |
| D67 | **Confirm when you're not an assignee.** If the person checking off isn't one of the to-do's assignees, they first see "**title** is assigned to @Anna and @Ben, not you. Check it off anyway?" with **Check off anyway** / **Cancel**. Applies to all four places in D60, and to **everyone** who isn't an assignee, list owners and Manage Server included. Ticking subtasks never asks. Mentions are shown but never ping. Someone who may not check off on that list gets the usual refusal straight away, not the question. | Tim (confirm, scope), Claude (wording) |
| D68 | **Wording.** After Undo: "↩️ Undone: **title** is open again." For a re-posted reminder, add " The reminder is back in <#channel>." Next reminder already sent: "Too late to undo: the next reminder for **title** already went out." Edited since: "**title** was changed after it was checked off, so it can't be undone." Next one checked off later: "Undo the later check-off of **title** first." | Claude |
| D69 | **`/todo upcoming` gets an undo select** instead of a button, because several to-dos can be checked off from one message. "Undo a check-off…" lists everything checked off from that message (newest first, as "N. title", max 25). Picking one undoes it, removes it from the select and refreshes the list in place; they can be undone in any order. The select disappears when it's empty. | Tim |

These change D37 only by adding the button; the check-off text stays the same.

---

## 2. Behaviour

### 2.1 Where the buttons show up

| Place | Today | New |
|---|---|---|
| Reminder → **Done** | Reminder deleted; ephemeral "✅ Checked off **title**." | Same, plus **Undo** on that ephemeral reply. Non-assignee: the ephemeral reply is first the confirm question (D67); **Check off anyway** does the check-off, deletes the reminder and turns the reply into the check-off text + Undo; **Cancel** turns it into "Not checked off." and the reminder stays. |
| `/todo done` | Ephemeral check-off text | Same + **Undo**. Non-assignee: the reply is the confirm question first. |
| `/todo show` → **Done** | Message becomes only the check-off text | Same + **Undo**. After Undo the message shows the to-do again with its normal buttons. Non-assignee: the buttons are swapped for **Check off anyway** / **Cancel** with the question as the text; Cancel puts the normal buttons back. |
| `/todo upcoming` → pick one | Check-off text above the refreshed list | Same, plus the **undo select** (D69) under the check-off select. Undoing one refreshes the list in place and the text becomes the D68 line. Non-assignee: both selects are swapped for the two confirm buttons with the question as the text; Cancel puts them back. |

On the reminder and `/todo done` replies, Undo replaces the reply with the D68 text and removes the button.

### 2.2 What undo does, case by case

| Checked off | Undo |
|---|---|
| One-time, untimed | To-do `open`, `completed_at/by` cleared. |
| One-time, timed, reminder still pending (checked off early) | To-do `open`; occurrence back to `pending`. Due time passed meanwhile → the scheduler posts it at once (late if > 2 min). |
| One-time, timed, reminder was up | To-do `open`; occurrence back to `sent`, re-posted with pings (D64). |
| Repeating, reminder was up | Occurrence back to `sent`, re-posted with pings; subtask ticks restored. The next pending occurrence stays. Refused if that next one has been sent since. |
| Repeating, checked off early (pending) | Occurrence back to `pending`; the follow-up occurrence the check-off created is cancelled; subtask ticks restored. Refused if the follow-up has been sent since, or cancelled by an edit. |

Nothing else changes: assignees, details and subtasks themselves are untouched.

---

## 3. Services (main session)

- **DTOs** (`services/dto.py`, strict and frozen like the rest):
  - `UndoToken(todo_id, occurrence_id: int | None, previous: OccurrenceStatus | None,
    followup_id: int | None, ticks: tuple[SubtaskTick, ...])` with `SubtaskTick(id, done_at, done_by)`.
    `occurrence_id`/`previous` are None for a one-time to-do checked off without an open occurrence
    (untimed, or one whose reminder failed).
  - `CheckedOff(todo: TodoView, undo: UndoToken)`. `todos.complete` and
    `occurrences.complete_occurrence` return `Outcome[CheckedOff]`; update the four callers.
  - `Undone(todo: TodoView, repost: DueReminder | None)`.
- **Capture the state.** `_common.finish_occurrence` records, before changing anything, the occurrence's
  status and (for repeating to-dos, which reset them) the ticked subtasks; after `add_next_pending` it
  flushes and records the new occurrence's id as `followup_id`. It returns these along with the effects,
  and the two services build the `UndoToken`.
- **New `services/undo.py`:** `undo(uow, actor, token) -> Outcome[Undone]`.
  - Lock the to-do first (`load_todo(lock=True)`); load the occurrence with `populate_existing`. Then check
    D65 in this order: to-do deleted → `NotFound`; the occurrence isn't `done` (or, without an
    occurrence, the to-do isn't `done`) → `InvalidOperation("That one isn't checked off any more.")`;
    `completed_by != actor.user_id` → `Forbidden("Only the person who checked it off can undo it.")`;
    `now - completed_at > UNDO_WINDOW` (2 h, in `core/limits.py`) → `InvalidOperation`;
    `require_complete(actor, todo)`.
  - Previous `sent`: refuse if the to-do has another `sent` occurrence. Otherwise occurrence → `sent`,
    `channel_id`/`message_id` cleared, **`sent_at = now`** (so crash recovery waits its 60 s and doesn't
    post a second copy), `late` kept → `repost` = this reminder (reuse `_reminders`).
  - Previous `pending`, repeating: the `followup_id` occurrence must still be `pending` (sent or missed →
    "next reminder already went out"; done → "undo the later check-off first"; cancelled → "changed after
    it was checked off"). Cancel it, flush (one pending per to-do), occurrence → `pending`.
  - One-time: `require_unique_title` + `flush_titles` (D44), to-do → `open`, `completed_at/by` → None,
    then the occurrence as above.
  - Restore `ticks` for subtasks that still exist and are unticked now.
  - Clear the occurrence's `completed_at`/`completed_by`. Commit. `changed_schedule=True` whenever a
    pending occurrence was touched.
- **Confirm (D67)** needs one read for the reminder button: `occurrences.todo_for(uow, actor,
  occurrence_id) -> TodoView` (no lock). `TodoView` already has `assignee_ids` and `can_complete`.

## 4. Bot (main session; the repeated entry-point wiring can go to Haiku once the first one is done)

- **Undo view** (`bot/views/undo.py`): `UndoView(BaseView)` with one **Undo** button, owner-only,
  `timeout = UNDO_WINDOW`. It holds the `UndoToken` and an `on_undone` callback; the default callback
  edits the message to the D68 text with no view. Used by the reminder reply and `/todo done`.
- `ShowView` adds the Undo button to itself after Done and rebuilds the normal view after Undo.
- `UpcomingView` keeps a list of `(UndoToken, title)` for check-offs made from it and shows them in a second
  select, "Undo a check-off…" (D69): newest first, labels "N. title" cut to 100 chars, value = index in the
  list, at most 25 (drop the oldest beyond that). After an undo it removes that entry and reloads the list.
  A refused undo keeps the entry (the error may be temporary, e.g. "undo the later check-off first").
- Both views raise their timeout to `UNDO_WINDOW` once they hold something to undo (discord.py restarts the
  timer when `timeout` is set). Share the undo call (service, `apply`, re-post) in one helper,
  e.g. `views/undo.run_undo(interaction, token) -> TodoView`.
- **Re-posting:** add `SidequestClient.repost(reminder)` that runs `Scheduler.deliver(reminder)` (posts,
  attaches the message id, or marks it failed). If the scheduler isn't running, do nothing: recovery posts
  it within ~1–2 minutes. Pings come from the normal reminder rendering.
- **Reminder Done actor:** the Undo button on a reminder's reply builds its actor with `reminder_actor`
  (as `DoneButton` does), because that interaction may lack the guild-install owner.
- **`render`:** `undone_text(todo, channel_id | None)` and `check_off_prompt(todo)` (assignees as `<@id>`
  joined "A, B and C"). Replies keep `AllowedMentions.none()`.
- **Confirm:** a generic `CheckOffConfirmView(owner_id, on_confirm, on_cancel)` in `views/confirm.py`
  (`BaseView`, 5 minutes). Before checking off, entry points check `todo.can_complete` (refuse as today)
  and then `actor.user_id in todo.assignee_ids`:
  - `DoneButton._done`: get the to-do with `todo_for`; non-assignee → ephemeral reply with the prompt;
    confirm runs today's check-off path (incl. deleting the reminder) and edits the reply into the
    check-off text + Undo.
  - `/todo done`: `todos.get` first; same prompt as the reply.
  - `ShowView._done`, `UpcomingView._picked`: swap components for the two buttons, prompt as the text;
    Cancel rebuilds the normal components.

## 5. Checklist

1. [x] **Services** — main session (§3): DTOs, state capture in `finish_occurrence`, `services/undo.py`,
   `todo_for`, `UNDO_WINDOW`.
2. [x] **Service tests** — Haiku from this list, `tests/integration/test_services_undo.py`, reviewed:
   - each row of §2.2: the state after undo equals the state before the check-off (statuses,
     `completed_*`, pending `due_at`, subtask ticks);
   - the returned `UndoToken` has the right `previous`, `followup_id` and `ticks` for each case;
   - re-post: `repost` returned, `message_id` cleared, `sent_at` = now, `late` kept; `unposted_sent`
     with `older_than = now - 60 s` does **not** return it;
   - refusals: 2 h + 1 s (FixedClock) → too late, exactly 2 h → OK; undo twice; another user; the user
     lost collaborator rights; to-do deleted; next reminder sent since (both repeating cases); follow-up
     cancelled by an edit; title clash on a one-time to-do;
   - chain: check off a repeating to-do early twice (A, then its follow-up B) → undo A is refused with
     "undo the later check-off first"; undo B, then A → back to the original pending occurrence;
   - a subtask deleted after the check-off is skipped; one ticked since the check-off keeps its new tick;
   - the scheduler, after an undo of an early check-off, fires the restored occurrence, not the cancelled
     follow-up (`tests/integration/test_scheduler.py`).
3. [x] **Bot** — main session (§4): `UndoView`, `run_undo`, `repost`, render helpers, confirm view, the four
   entry points.
4. [x] **Unit tests** — Haiku, reviewed: `render.undone_text` (with/without channel), `check_off_prompt`
   (1, 2 and 3+ assignees, escaping).
5. [x] **Docs** — Opus: `CLAUDE.md` (§4 check-off rules, §6 D60–D69), root `README.md` features line, this
   brief's Status + Handoff. No runbook note needed (no migration).
6. [x] **Checks** — `ruff check .`, `ruff format --check .`, `pytest` with `TEST_DATABASE_URL`.

## 6. Manual test checklist (Tim, dev bot)

- [ ] Reminder of a one-time to-do → Done → reply has Undo → Undo: reminder posted again in the channel,
      assignees pinged, reply says "Undone … The reminder is back in #channel".
- [ ] Repeating to-do with subtasks, tick two, Done on its reminder → Undo → reminder back, the two
      ticks are back, "Next" in `/todo show` unchanged.
- [ ] `/todo upcoming` → check off a repeating one early → undo it from "Undo a check-off…" → the list
      refreshes with it back at its original time, and only one entry for that to-do.
- [ ] `/todo upcoming` → check off three → the undo select lists all three, newest first → undo the
      middle one → it's back in the list, the other two stay in the undo select.
- [ ] `/todo upcoming` → check off the same daily to-do twice in a row → undoing the first one says
      "Undo the later check-off … first"; undoing the second, then the first, works.
- [ ] `/todo done` on an untimed to-do → Undo → it's back in `/todo list`.
- [ ] `/todo show` → Done → Undo → the to-do is shown again with its buttons.
- [ ] Undo twice → "isn't checked off any more".
- [ ] Repeating to-do due in 2 min: check off the current reminder, wait until the next one posts, then
      Undo → "the next reminder … already went out".
- [ ] One-time to-do: check off, add a new to-do with the same title, Undo → title-clash message.
- [ ] Non-assignee presses Done on a reminder → confirm question naming the assignees, nobody pinged;
      Cancel → reminder stays; Check off anyway → checked off, with Undo.
- [ ] Non-assignee `/todo done`, `/todo show` → Done, `/todo upcoming` pick → same question; Cancel puts
      the normal buttons/select back.
- [ ] An assignee checks off → no question.

## 7. Tim's answers (2026-11-12)

1. Where does Undo live for reminders? → on the "Checked off" reply (D60).
2. Re-ping the assignees when a reminder comes back? → yes (D64).
3. How long does Undo work? → 2 hours (D61); it doesn't have to survive restarts.
4. Confirm when a non-assignee checks off? → yes (D67), also for list owners and Manage Server.
5. Ticking subtasks asks too? → no (D67).
6. Who can undo? → only the person who checked it off (D62).
7. Several check-offs in one `/todo upcoming` message? → an undo select, any order (D69).

## Handoff

Built by Claude (Opus 5.5), 2026-11-12.

**What was built**
- Services: `UndoToken`/`SubtaskTick`/`CheckedOff`/`Undone` DTOs; `finish_occurrence` captures the
  state and returns the token; `todos.complete` and `occurrences.complete_occurrence` return
  `Outcome[CheckedOff]`; new `services/undo.py`; `occurrences.todo_for` and `occurrences.due_reminder`
  (a public wrapper around `_reminders` for the re-post); `UNDO_WINDOW` in `core/limits.py`.
- Bot: `views/undo.py` (`run_undo`, `UndoView`), `CheckOffConfirmView` + `must_confirm` +
  `not_checked_off` in `views/confirm.py`, `SidequestClient.repost` (reached via `adapter.repost`),
  `render.undone_text` / `check_off_prompt` / `and_join` / `undo_options`, and the four entry points.
- Tests: `tests/integration/test_services_undo.py` (20), one scheduler test, 13 render unit tests;
  four existing tests now read `.value.todo`.

**Deviations**
- `followup_id` means "the to-do's pending occurrence right after the check-off" for **every**
  repeating check-off, not only when the check-off created it. When the reminder was up, that is the
  existing next occurrence: undo leaves it alone but requires it to still be pending. That gives one
  rule for both repeating cases: sent/missed/failed → "already went out", done → "undo the later
  check-off first", cancelled → "changed". Undo cancels it only when `previous` was pending.
- `run_undo` returns `(TodoView, text)` rather than just the to-do, so callers get the D68 line with
  the channel.
- "Too late" wording (not set in D68): "A check-off can only be undone for 2 hours."
- No confirm question when the reminder is no longer live (already checked off or missed). The
  check-off runs straight away and reports what happened, as before.
- The service tests use `times=["08:00", "08:30"]` for the "next reminder went out" cases, so the
  next occurrence falls inside the 2-hour window.

**Open questions**
- None.
