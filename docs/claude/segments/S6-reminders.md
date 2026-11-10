# S6 — Scheduler & reminders

**Goal:** reminders go out on time (in the server channel or by DM), can be checked off with a button that survives restarts, and nothing is lost or flooded when the bot restarts or was down.

**Depends on:** S4 (occurrence services), S5 (`bot/render.py`, effect executor). **Branch:** `claude/s6-reminders`.

## Components

### `scheduler/signal.py`
`SchedulerSignal` protocol: `wake()` and `async wait(timeout)`. Implementation: `asyncio.Event`. (Future: Postgres `LISTEN/NOTIFY` implementation for the web process — not now.)

### `scheduler/notifier.py`
`Notifier` protocol (implemented in `bot/`):
```python
async def post(reminder: DueReminder) -> PostResult   # Posted(channel_id, message_id) | Failed(reason)
async def execute(effects: list[Effect]) -> None
```

### `scheduler/loop.py`
```
on start: recover = services.unposted_sent(older_than=60s) → post each
loop:
    due = services.claim_due(now, limit=20)
    for r in due:
        notifier.execute(r.effects)            # delete replaced (missed) reminder
        result = notifier.post(r)
        Posted  → services.attach_message(...)
        Failed  → services.mark_failed(...)
    if due was full: continue immediately
    sleep until min(next_due_at, now + 60s), or until signal.wake()
```
- Started from `setup_hook` as a background task; cancelled cleanly on shutdown.
- One bad reminder must never kill the loop (log + `mark_failed`).
- Writes a heartbeat (timestamp file, e.g. `/tmp/sidequest-heartbeat`) every iteration for the S7 healthcheck.

### Bot notifier (`bot/notifier.py`)
- **Server reminder:** `client.get_partial_messageable(reminder_channel_id).send(...)`.
  - No channel configured → `Failed("no_channel")`; `Forbidden` → `Failed("forbidden")`; `NotFound` → `Failed("channel_gone")`.
- **Personal reminder:** `dm = await client.create_dm(discord.Object(owner_id))`, then send.
  - `Forbidden` / error 50007 → `Failed("dm_closed")` (service records `dm_failed_at`, user warned on next command — D26).
  - **Verify** early in this segment with a test account: can the bot DM a user who has the app user-installed but shares no server with it? Record the answer in `BRIEF.md` §5.4 (via Opus).
- Message:
  - `content`: mentions of all assignees (server only), e.g. `<@1> <@2>`; DMs need no mention.
  - embed via `render.reminder_embed(...)`: title, details, `Due: ts_due(due_at)`, `Late — was due <t:…:R>` when `late`, rule description for recurring, subtasks with ☐/☑.
  - `allowed_mentions = AllowedMentions(users=True, roles=False, everyone=False, replied_user=False)`.
  - components: `ReminderView(occurrence_id, subtasks)`.

### Persistent components (`bot/views/reminder.py`)
Use `discord.ui.DynamicItem` so they work after restarts without stored views; register with `client.add_dynamic_items(...)`.
- Done button: `custom_id = "sq:occ:done:<occurrence_id>"`.
- Subtask multi-select(s): `custom_id = "sq:occ:sub:<occurrence_id>:<page>"`, page 0 = subtasks 1–25, page 1 = 26–50 (D29); defaults = ticked ones. Each select updates only its own page's subtasks.

Done handler:
1. Actor from the interaction (anyone in the channel may press — D3; in DMs it's the owner).
2. `services.complete_occurrence(actor, id)`.
3. Respond ephemeral "✅ Checked off **title**" (DM: just respond), then delete `interaction.message`.
4. `InvalidOperation` (already done / missed) → ephemeral note, delete the message anyway.

Subtask select handler: `services.subtasks.set_done(actor, todo_id, selected_ids, within=page_subtask_ids)` (only the page's subtasks change) → re-render and `interaction.response.edit_message(...)`. Rendering uses S5's budgeted `render` helpers (6000-char embed limit).

## Edge cases to handle
- Recurring replace (D7): `claim_due` returns the old message as an effect; delete it **before** posting the new one.
- Reminder channel changed later: new reminders go to the new channel; old messages keep working (custom_id carries the occurrence id).
- To-do deleted while its reminder is up → service returns DeleteMessage effect (S4); a stale button press → NotFound → ephemeral "This to-do no longer exists" + delete message.
- Bot restarted mid-post → startup recovery re-posts (possible duplicate only in that crash window; acceptable).
- Rate limits: post sequentially; discord.py handles 429s.

## Checklist
1. Signal + Notifier protocols + scheduler loop with a `FakeNotifier` — main session.
2. Bot notifier + reminder view + DynamicItems — main session.
3. DM verification (above) — main session, recorded by Opus.
4. Tests — Haiku from this list, reviewed (scheduler with `FakeNotifier`, `FixedClock`, real Postgres):
   - once timed: fires exactly once at due time, not before
   - recurring daily: after firing, next pending exists; firing again marks previous missed + delete effect executed before post
   - outage: clock +3 days → exactly one late reminder
   - early completion → never posted
   - `Failed("no_channel")` / `Failed("dm_closed")` recorded; `dm_failed_at` set
   - crash recovery: `sent` without message_id older than 60 s is re-posted on start
   - loop survives a notifier exception
   - wake signal makes a newly created due-now to-do fire without waiting 60 s
5. Manual checklist for Tim.

## Manual test checklist (Tim, dev bot)
- [ ] Server to-do at now+2 min with two assignees → posted in the reminder channel, both pinged, Done deletes it
- [ ] Someone who isn't an assignee can press Done (D3)
- [ ] Personal timed to-do → arrives as DM with working Done button
- [ ] Daily to-do left unchecked → next occurrence replaces the old message
- [ ] Subtask select ticks items; on a repeating to-do they're reset for the next occurrence
- [ ] Restart the bot (`docker compose restart bot`) → old reminder's Done button still works
- [ ] Stop the bot past a due time, start it → one reminder marked late
- [ ] Close DMs from server members → personal reminder fails → warning on next command
- [ ] All times show as Discord timestamps
