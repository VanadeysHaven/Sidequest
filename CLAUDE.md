# Sidequest — instructions for Claude

Discord to-do bot (Python, discord.py, PostgreSQL, Docker on a Raspberry Pi).

## Start of every session
Read `docs/claude/README.md` and follow it: `BRIEF.md` → `WORKFLOW.md` → `PROGRESS.md` → only the current segment in `docs/claude/segments/`.

## Hard rules (details in `docs/claude/WORKFLOW.md`)
- **Git:** you may create branches (`claude/sNN-<slug>`). **Never** commit, push, merge, rebase, reset, stash, clean or restore. **No worktrees.** Don't switch branches with uncommitted changes.
- **Segments:** work on one segment per session. When it's done, update `PROGRESS.md`, then stop and ask Tim to review and commit. Don't start the next segment.
- **Models:** Haiku subagents for boilerplate, repeating an existing pattern, tests written from a given case list, and running checks. Design work and reviews stay in the main session.
- **Docs:** Claude's documentation lives in `docs/claude/` and is always written by Opus 5.5.
- **Unclear spec:** ask Tim rather than guessing. Haiku subagents stop and report instead of deciding.

## Code rules
- `core/` imports neither `discord` nor `sqlalchemy`; `services/` and `db/` never import `discord`.
- Times are entered as 24h `HH:MM`. Every point in time shown to users goes through `core.discord_time` (Discord timestamps).
- Get "now" from `core.clock.Clock` only; all datetimes are timezone-aware UTC internally.
- Dependencies: edit `pyproject.toml`, then run `scripts/compile-requirements.sh`. Never hand-edit `requirements*.txt`.
- Line endings LF. Before finishing: `ruff check .`, `ruff format --check .`, `pytest`.
