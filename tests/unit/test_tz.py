"""Table-driven tests for `sidequest.core.tz`."""

import pytest

from sidequest.core.errors import InvalidTimezone
from sidequest.core.tz import get_zone, search_zones


@pytest.mark.parametrize(
    ("name", "key"),
    [
        pytest.param("europe/amsterdam", "Europe/Amsterdam", id="lowercase"),
        pytest.param("Europe/Amsterdam", "Europe/Amsterdam", id="canonical"),
        pytest.param("  EUROPE/AMSTERDAM  ", "Europe/Amsterdam", id="upper-and-whitespace"),
        pytest.param("UTC", "UTC", id="utc"),
    ],
)
def test_get_zone_returns_canonical_key(name: str, key: str) -> None:
    assert get_zone(name).key == key


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Mars/Base", id="unknown-zone"),
        pytest.param("", id="empty"),
    ],
)
def test_get_zone_rejects_unknown(name: str) -> None:
    with pytest.raises(InvalidTimezone):
        get_zone(name)


@pytest.mark.parametrize(
    ("query", "limit"),
    [
        pytest.param("a", 5, id="limit-five"),
        pytest.param("a", 1, id="limit-one"),
    ],
)
def test_search_zones_respects_limit(query: str, limit: int) -> None:
    assert len(search_zones(query, limit=limit)) == limit


def test_search_zones_prefix_match_first() -> None:
    assert search_zones("amst")[0] == "Europe/Amsterdam"


def test_search_zones_spaces_match_underscores() -> None:
    assert "America/New_York" in search_zones("new york")


def test_search_zones_prefix_matches_come_before_substring_matches() -> None:
    results = search_zones("europe/a")
    assert results
    assert all(name.startswith("Europe/A") for name in results)
