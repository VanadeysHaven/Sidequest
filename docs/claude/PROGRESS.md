# Progress

> Updated by Claude (Opus 5.5) at the end of every session.

## Status

| Seg | Title | Status | Branch |
|---|---|---|---|
| S1 | Foundation | ⏭️ next | — |
| S2 | Data model | ⬜ todo | — |
| S3 | Time & recurrence | ⬜ todo | — |
| S4 | Services | ⬜ todo | — |
| S5 | Commands | ⬜ todo | — |
| S6 | Reminders | ⬜ todo | — |
| S7 | Ops & hardening | ⬜ todo | — |

Legend: ⬜ todo · ⏭️ next · 🔨 in progress · 👀 waiting for Tim's review/commit · ✅ done

## Before S1 (Tim)
- [x] Review assumptions A1–A14 (done 2026-11-10 → decisions D17–D29).
- [x] A9: Pi confirmed 64-bit (`aarch64` / `arm64`) → D30.
- [ ] Create a **dev** Discord application (separate from production) with a test server; note its token and the test server ID for `DEV_GUILD_ID`.
- [ ] In the Developer Portal → Installation: enable **Guild Install** (scopes `applications.commands`, `bot`; permissions View Channel, Send Messages, Embed Links) and **User Install** (`applications.commands`). Leave all privileged intents off.

## Handoff log

### 2026-11-10 — Brief written
- Brief, workflow and segment docs created. No code yet.
- Next: S1. S2 and S3 may run in either order after S1.
- Same day: Tim reviewed the assumptions. Changes vs. the first draft: no date-only to-dos; monthly day-of-month rules (with last-day fallback); default timezone UTC; English-only input; 50 subtasks (two selects). Pi confirmed 64-bit (D30); no open assumptions. Root `CLAUDE.md` added.
