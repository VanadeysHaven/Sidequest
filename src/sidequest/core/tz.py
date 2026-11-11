"""IANA timezone lookup and search (autocomplete)."""

from functools import cache
from zoneinfo import ZoneInfo, available_timezones

from sidequest.core.errors import InvalidTimezone

# Entries some tz databases list that are not real user-facing zones.
_EXCLUDED = {"Factory", "localtime", "posixrules"}
_EXCLUDED_PREFIXES = ("posix/", "right/")


@cache
def _canonical_names() -> dict[str, str]:
    """Lower-case name → canonical spelling."""
    names = available_timezones() | {"UTC"}
    return {
        name.lower(): name
        for name in names
        if name not in _EXCLUDED and not name.startswith(_EXCLUDED_PREFIXES)
    }


@cache
def _sorted_names() -> tuple[str, ...]:
    return tuple(sorted(_canonical_names().values()))


def get_zone(name: str) -> ZoneInfo:
    """Return the zone for an IANA name, matched case-insensitively."""
    canonical = _canonical_names().get(name.strip().lower())
    if canonical is None:
        raise InvalidTimezone(
            f"Unknown timezone: {name}. Pick one from the list, e.g. Europe/Amsterdam."
        )
    return ZoneInfo(canonical)


def search_zones(query: str, limit: int = 25) -> list[str]:
    """Zone names matching `query`, best matches first.

    Order: names starting with the query, then names where a later part starts with it
    (`amster` → `Europe/Amsterdam`), then names containing it. Case-insensitive; spaces
    match underscores (`new york` → `America/New_York`).
    """
    q = query.strip().lower().replace(" ", "_")
    if not q:
        return list(_sorted_names()[:limit])

    tiers: tuple[list[str], list[str], list[str]] = ([], [], [])
    for name in _sorted_names():
        lower = name.lower()
        if lower.startswith(q):
            tiers[0].append(name)
        elif any(part.startswith(q) for part in lower.split("/")[1:]):
            tiers[1].append(name)
        elif q in lower:
            tiers[2].append(name)
    return [*tiers[0], *tiers[1], *tiers[2]][:limit]
