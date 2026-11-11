# S3 — Time & recurrence (pure core)

**Goal:** every time-related rule of the app as pure, heavily tested functions. No DB, no Discord.

**Depends on:** S1 (package skeleton). **Branch:** `claude/s3-time-recurrence`.

All functions take explicit inputs (`now`, `tz`) — never read the clock themselves.

## Modules

### `core/clock.py`
`Clock` protocol with `now() -> datetime` (aware UTC); `SystemClock`. The test clock `FixedClock` (settable/advanceable) lives in `tests/support/clock.py`, not in the package (Tim, 2026-11-11).

### `core/errors.py`
`SidequestError` base with a user-safe `message`. Subclasses used here: `InvalidTime`, `InvalidDate`, `InvalidTimezone`, `InPast`, `InvalidRule`. (S4 adds more.)

### `core/tz.py`
- `get_zone(name) -> ZoneInfo` — validates IANA names (case-insensitive match against `zoneinfo.available_timezones()`, returns canonical spelling); `UTC` accepted.
- `search_zones(query, limit=25) -> list[str]` for autocomplete: prefix matches first, then substring matches, both case-insensitive; matches on the city part too (`amster` → `Europe/Amsterdam`).

### `core/timeparse.py`
- `parse_time(s) -> time`: accepts `H:MM`, `HH:MM`, `HH.MM`, 00:00–23:59. Rejects anything with am/pm with a specific message ("Use 24-hour time, e.g. 14:30").
- `parse_times(s) -> list[time]`: comma/space separated, deduplicated, sorted, 1–12 entries.
- `parse_date(s, today) -> date`: `YYYY-MM-DD`, `DD-MM-YYYY` (separators `-` `/` `.`), `today`/`tomorrow`. Two-digit years are rejected. English only (D28).
- `parse_weekdays(s) -> list[Weekday]`: `mon,thu`, full English names, `weekdays`, `weekend`.
- `parse_month_day(s) -> int`: `1`–`31` (also `1st`, `15th`, …) or `last` → `-1`.
- `resolve_local(d, t, tz) -> datetime (UTC)`: DST rules — nonexistent → shift forward by the gap; ambiguous → first instance (`fold=0`).
- `resolve_due(date | None, time | None, tz, now) -> Due`: returns `Untimed` or `Timed(utc_dt)`.
  - neither → `Untimed`
  - date without time → `InvalidTime("A date needs a time, e.g. 14:30")` (D17)
  - time without date → today if still ahead in `tz`, else tomorrow (D18)
  - explicit date (including today) + time → that moment; in the past → `InPast`

### `core/recurrence.py`
- Pydantic models (discriminated union on `type`): `DailyRule(times)`, `WeeklyRule(weekdays, times)`, `MonthlyRule(week: 1..4 | -1, weekday, times)`, `MonthlyDayRule(day: 1..31 | -1, times)`. For `MonthlyDayRule` a day the month lacks falls back to the month's last day (D21); `-1` is always the last day. `times` serialized as `"HH:MM"`. `RecurrenceRule = Annotated[Union[...], Field(discriminator="type")]` + `to_json()/from_json()` matching the JSONB shape in S2.
- `next_occurrence(rule, tz, after: datetime) -> datetime` — first occurrence **strictly after** `after`, in UTC. Algorithm: walk local dates from `after`'s local date; for matching dates, resolve each sorted time with `resolve_local`; return the first result `> after`. Hard cap (e.g. 800 days) → raise.
- `occurrences_between(rule, tz, start, end) -> list[datetime]` (used by `/todo upcoming` previews and tests).
- `describe(rule, tz) -> str`, 24h wall-clock, e.g.
  - "Every day at 08:00 and 20:00 (Europe/Amsterdam)"
  - "Every Monday and Thursday at 12:00 (Europe/Amsterdam)"
  - "Every last Sunday of the month at 12:00 (UTC)"
  - "Every month on the 15th at 09:00 (UTC)" / "Every month on the last day at 09:00 (UTC)"; for days 29–31 append "(or the last day of shorter months)"

### `core/discord_time.py`
- `ts(dt, style="f") -> str` → `<t:{int(dt.timestamp())}:{style}>`; styles `t T d D f F R` as a `Literal`.
- `ts_due(dt) -> str` → `"<t:…:F> (<t:…:R>)"` — the standard way to show a due time.
- Rejects naive datetimes.
- This is the **only** place user-facing points in time are formatted (C5).

### `core/limits.py`
Constants from BRIEF §4.11.

## Test cases (Haiku writes table-driven tests from this list; main session writes the engine)

Time/date parsing:
- `9:05`, `09:05`, `09.05`, `23:59`, `00:00` OK; `24:00`, `9:5`, `9pm`, `9:00 AM`, `` reject; am/pm gives the 24h hint
- `2026-11-12`, `12-11-2026`, `12/11/2026`, `12.11.2026` all → 12 Nov 2026; `31-02-2026` rejected; `12-11-26` rejected
- `today`/`tomorrow` relative to a given `today`; `vandaag`/`morgen` rejected (English only)
- time-only at 23:30 local when now is 23:45 → tomorrow 23:30; when now is 23:00 → today
- explicit `today` + a time still ahead → today; explicit `today` + a time already passed → `InPast`
- date without time → `InvalidTime`; neither → `Untimed`
- `parse_month_day`: `15`, `15th`, `1st`, `31`, `last` OK; `0`, `32`, `fifteenth` rejected

DST (Europe/Amsterdam 2026: spring 29 Mar 02:00→03:00, fall 25 Oct 03:00→02:00; also America/New_York):
- daily 02:30 on 29 Mar 2026 → 03:30 local that day (shifted), 02:30 the next day
- daily 02:30 on 25 Oct 2026 → fires once (first instance, UTC+2)
- daily 12:00 keeps 12:00 local across both transitions (UTC offset changes)

Recurrence:
- daily `08:00, 20:00`, after = 08:00 exactly → 20:00 same day (strictly after)
- daily after = 21:00 → 08:00 next day
- weekly mon+thu 12:00 from a Friday → next Monday; from Monday 11:59 → same Monday
- monthly 1st Sunday: month starting on a Sunday (Feb 2026 starts Sunday → 1 Feb) and one that doesn't
- monthly last Sunday in Feb 2028 (leap year) and Feb 2027
- monthly 4th Friday vs last Friday in a month with 5 Fridays
- monthly_day 15 at 09:00, after = 15th 09:00 exactly → 15th of next month
- monthly_day 31 → 31 Jan, 28 Feb 2027, 29 Feb 2028, 31 Mar, 30 Apr (fallback to last day)
- monthly_day 30 in February → last day of February; monthly_day -1 → last day of every month
- monthly_day 31 never fires twice in one month and never skips a month
- `occurrences_between` over a DST week returns the expected count
- `describe` output for each rule type
- JSON round-trip for each rule type; invalid payloads (`week: 5`, `day: 0`, `day: 32`, empty times, 13 times, unknown weekday) raise `InvalidRule`

tz:
- `europe/amsterdam` → `Europe/Amsterdam`; `Mars/Base` rejected; `search_zones("amst")` contains `Europe/Amsterdam` first

## Acceptance
All tests pass; `core` imports nothing from `discord`/`sqlalchemy`/`sidequest.db`.

## Interfaces exported
`Clock`, `get_zone`, `search_zones`, `parse_time(s)`, `parse_times`, `parse_date`, `parse_weekdays`, `parse_month_day`, `resolve_due` → `Untimed | Timed`, `RecurrenceRule` + `next_occurrence`/`occurrences_between`/`describe`, `ts`/`ts_due`, error classes.
