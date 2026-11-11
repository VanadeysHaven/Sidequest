"""Enforce the import rules between layers by scanning source with `ast`."""

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "sidequest"

LAYER_RULES: list[tuple[str, set[str]]] = [
    ("core", {"discord", "sqlalchemy", "sidequest.db"}),
    ("services", {"discord"}),
    ("db", {"discord"}),
]


def forbidden_imports(source: str, forbidden: set[str]) -> list[str]:
    """Entries of `forbidden` (packages or dotted subpackages) that `source` imports."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return sorted(f for f in forbidden if any(m == f or m.startswith(f"{f}.") for m in modules))


@pytest.mark.parametrize(("layer", "forbidden"), LAYER_RULES, ids=[r[0] for r in LAYER_RULES])
def test_layer_does_not_import_forbidden_packages(layer: str, forbidden: set[str]) -> None:
    layer_dir = PACKAGE_ROOT / layer
    violations: list[str] = []
    if layer_dir.is_dir():
        for path in sorted(layer_dir.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for module in forbidden_imports(source, forbidden):
                violations.append(f"{path.relative_to(PACKAGE_ROOT)} imports {module!r}")

    assert not violations, f"layer {layer!r} has forbidden imports: " + "; ".join(violations)


def test_helper_detects_import_of_submodule() -> None:
    assert forbidden_imports("import discord.ui", {"discord"}) == ["discord"]


def test_helper_detects_from_import() -> None:
    assert forbidden_imports("from sqlalchemy.orm import Session", {"sqlalchemy"}) == ["sqlalchemy"]


def test_helper_ignores_relative_import() -> None:
    assert forbidden_imports("from . import discord", {"discord"}) == []


def test_helper_ignores_similar_prefix() -> None:
    assert forbidden_imports("import discordant", {"discord"}) == []


def test_helper_detects_dotted_subpackage() -> None:
    assert forbidden_imports("from sidequest.db.models import Todo", {"sidequest.db"}) == [
        "sidequest.db"
    ]


def test_helper_ignores_sibling_of_dotted_subpackage() -> None:
    assert forbidden_imports("from sidequest.core import tz", {"sidequest.db"}) == []
