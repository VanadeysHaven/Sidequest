# Workflow — how Claude works on Sidequest

> Written by Claude (Opus 5.5), 2026-11-10. These rules are binding for every Claude session and subagent.

## 1. Session protocol

1. Read `README.md`, `BRIEF.md`, this file, `PROGRESS.md`, then **only** the current segment doc.
2. Check git state with read-only commands (`git status`, `git branch --show-current`, `git diff --stat`).
   - If the previous segment's changes are still uncommitted, **stop** and ask Tim to review and commit first.
   - Otherwise create the segment branch: `git switch -c claude/sNN-<slug>` (e.g. `claude/s2-data-model`).
3. Turn the segment's checklist into a task list (TaskCreate) and work through it.
4. Delegate according to §3. Review every subagent diff before ticking its task.
5. Run checks (§6). Do not mark a segment done with failing checks.
6. Have Opus 5.5 update `PROGRESS.md` (status + handoff note) and append any new decisions to `BRIEF.md` §3.
7. Stop and report to Tim: what was built, files changed, deviations from the spec, open questions, and a suggested commit message. **Do not start the next segment.**

If a segment is too big for one session, stop at a natural checkpoint, write a handoff note in `PROGRESS.md` ("Next session starts at checklist item X"), and stop.

## 2. Git rules (hard)

- Allowed: `git status`, `diff`, `log`, `show`, `branch`, and creating a branch (`git switch -c` / `git branch`).
- **Never**: `commit`, `push`, `merge`, `rebase`, `reset`, `stash`, `clean`, `checkout -- <file>`, `restore`, `cherry-pick`, `tag`, or anything touching remotes. **No worktrees.**
- Never switch branches while there are uncommitted changes.
- New executable files (e.g. `update.sh`): tell Tim to run `git add --chmod=+x <file>`, because Tim is on Windows and the executable bit won't otherwise reach the Pi.

## 3. Model routing

| Work | Who |
|---|---|
| All documentation (`docs/claude/*`, root `README.md`, runbook) | **Opus 5.5** (main session or Opus subagent). Never Haiku/Sonnet. |
| Design decisions, schema, recurrence engine, scheduler, services & permissions, reviewing subagent output | Main session |
| Boilerplate from an exact spec (`.gitattributes`, `.gitignore`, `.dockerignore`, Dockerfile, compose files, `update.sh` port, `.env.example`) | Haiku subagent |
| Repeating an established pattern (more slash commands after the first one exists, more views, more service methods with identical shape) | Haiku subagent, reviewed |
| Table-driven tests from a case list given in the segment doc | Haiku subagent |
| Running lint/tests and summarizing failures; mechanical lint/format fixes | Haiku subagent |
| Broad codebase searches | Explore agent |

Rules for subagent prompts:
- Self-contained: paste the exact spec excerpt, file paths, conventions (§5) and the acceptance check. Don't tell them to "read the brief".
- Ask for a short report: files changed, commands run, results. No full file dumps.
- Haiku never makes design decisions. If the spec is ambiguous it stops and reports back.
- Spawn with `model: "haiku"` on the Agent tool.

## 4. Context budget

- Don't read other segment docs; each segment lists the interfaces it needs.
- Prefer `grep`/targeted reads over reading whole files. Keep source files under ~400 lines.
- Push bulky work (test runs, wide searches) into subagents so their output stays out of the main context.
- Use `/clear` between segments; `PROGRESS.md` carries the state.

## 5. Code conventions

- Python 3.13, full type hints, `ruff` lint + format (line length 100).
- Layering (BRIEF §5.2): `core` imports no `discord`/`sqlalchemy`; `services`/`db` import no `discord`. A unit test (`tests/unit/test_layering.py`) enforces this by scanning imports.
- All datetimes are timezone-aware UTC internally. Get "now" only through `core.clock.Clock` so tests can control it.
- User-facing points in time go through `core.discord_time` only. Wall-clock text (rule descriptions) uses `HH:MM`.
- User-provided text in bot output is escaped (`discord.utils.escape_mentions` / markdown) and messages set explicit `allowed_mentions` (users only on reminders, none elsewhere).
- Logging via `logging`, never `print`.
- Dependencies: edit `pyproject.toml`, then run `scripts/compile-requirements.sh`. Never hand-edit `requirements*.txt`.
- Line endings LF (enforced by `.gitattributes`; Tim develops on Windows, deploys on Linux).

## 6. Checks

- `ruff check .` and `ruff format --check .`
- `pytest tests/unit`
- `pytest tests/integration` against the test Postgres (`docker compose -f compose.test.yaml up -d`, `TEST_DATABASE_URL`). If Docker isn't available, say so in the report; never fake or skip silently.
- Claude can't use Discord itself: each segment that touches Discord ends with a **manual test checklist** for Tim (dev bot, `DEV_GUILD_ID` for instant command sync).

## 7. Documentation rules

- Claude's docs live in `docs/claude/`. Written by Opus 5.5.
- `BRIEF.md`: append decisions to §3 with a date; don't silently rewrite existing decisions.
- `PROGRESS.md`: update at the end of every session.
- If implementation must deviate from a segment doc, record why in the handoff note.
