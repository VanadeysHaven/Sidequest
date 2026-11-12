"""Size limits (BRIEF §4.11)."""

# Sidequest's own limits (D29).
TITLE_MAX = 200
DETAILS_MAX = 4000
SUBTASK_TITLE_MAX = 100
SUBTASKS_MAX = 50
ASSIGNEES_MAX = 10
TIMES_PER_RULE_MAX = 12

# Weekly rules (S9).
WEEK_INTERVAL_MAX = 52
"""`every` on a weekly rule: 1–52 weeks."""
START_AHEAD_MAX_DAYS = 366
"""How far ahead a weekly rule's `start` may be, checked when it is set."""

# Server lists (S8).
LIST_NAME_MAX = 50
LISTS_MAX = 25
"""Per server; keeps the delete flow's move select to one menu."""
COLLABORATORS_MAX = 25
"""Per list; one user select."""

# Discord's limits that rendering must respect.
SELECT_OPTIONS_MAX = 25
SELECT_LABEL_MAX = 100
EMBED_DESCRIPTION_MAX = 4096
EMBEDS_TOTAL_MAX = 6000
