"""Catalogue service — pattern CRUD, DSL parse/export, catalogue import/export.

Handles all operations on the pattern catalogue (group D endpoints).
"""
from __future__ import annotations

import copy
import json
import logging
import os

from olm.core.catalogue_matcher import compact_catalogue_names, generate_auto_name
from olm.core.pattern_dsl import parse_dsl, to_dsl
from olm.core.room_dsl import parse_room_dsl

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Catalogue paths — resolved from config_service
# ---------------------------------------------------------------------------

from olm.server.services.config_service import PROJECT_ROOT, atomic_write_json

CATALOGUE_DIR = os.path.join(PROJECT_ROOT, "project", "catalogue")
CATALOGUE_PATH = os.path.join(CATALOGUE_DIR, "patterns.json")


# ---------------------------------------------------------------------------
# Catalogue I/O
# ---------------------------------------------------------------------------


def load_catalogue() -> list[dict]:
    """Load the catalogue from the JSON file."""
    if not os.path.exists(CATALOGUE_PATH):
        return []
    with open(CATALOGUE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("patterns", [])


def save_catalogue(patterns: list[dict]) -> None:
    """Save the catalogue to the JSON file."""
    os.makedirs(CATALOGUE_DIR, exist_ok=True)
    atomic_write_json(CATALOGUE_PATH, {"patterns": patterns})


def find_pattern(patterns: list[dict], name: str) -> int:
    """Return the pattern index by name, or -1 if not found."""
    for i, p in enumerate(patterns):
        if p["name"] == name:
            return i
    return -1


# ---------------------------------------------------------------------------
# Pattern CRUD
# ---------------------------------------------------------------------------


def list_patterns() -> dict:
    """Return all patterns with count."""
    patterns = load_catalogue()
    return {"patterns": patterns, "count": len(patterns)}


def create_pattern(data: dict) -> dict:
    """Create or update a pattern.

    Args:
        data: pattern dict with ``rows`` (req), ``name`` (opt),
              ``auto_name`` (opt bool).

    Returns:
        ``{"ok": True, "name": str, "count": int}``.

    Raises:
        ValueError: if ``rows`` is missing.
    """
    if not data or "rows" not in data:
        raise ValueError("Required field: rows")

    patterns = load_catalogue()
    auto_name = data.pop("auto_name", False)
    if auto_name or "name" not in data:
        data["name"] = generate_auto_name(data, patterns)

    idx = find_pattern(patterns, data["name"])
    if idx >= 0:
        patterns[idx] = data
    else:
        patterns.append(data)

    compact_catalogue_names(patterns)
    save_catalogue(patterns)
    return {"ok": True, "name": data["name"], "count": len(patterns)}


def get_pattern(name: str) -> dict | None:
    """Return a pattern by name, or ``None`` if not found."""
    patterns = load_catalogue()
    idx = find_pattern(patterns, name)
    if idx < 0:
        return None
    return patterns[idx]


def delete_pattern(name: str) -> dict | None:
    """Delete a pattern by name.

    Returns:
        ``{"ok": True, "name": str, "count": int}`` or ``None`` if absent.
    """
    patterns = load_catalogue()
    idx = find_pattern(patterns, name)
    if idx < 0:
        return None
    patterns.pop(idx)
    compact_catalogue_names(patterns)
    save_catalogue(patterns)
    return {"ok": True, "name": name, "count": len(patterns)}


def duplicate_pattern(name: str, new_name: str | None = None) -> dict:
    """Duplicate a pattern.

    Args:
        name: source pattern name.
        new_name: target name (default: ``name + "_copy"``).

    Returns:
        ``{"ok": True, "name": str, "count": int}``.

    Raises:
        KeyError: source not found.
        ValueError: ``new_name`` already in use.
    """
    patterns = load_catalogue()
    idx = find_pattern(patterns, name)
    if idx < 0:
        raise KeyError(f"Pattern not found: {name}")

    target = new_name or (name + "_copy")
    if find_pattern(patterns, target) >= 0:
        raise ValueError(f"Name already in use: {target}")

    new_pattern = copy.deepcopy(patterns[idx])
    new_pattern["name"] = target
    patterns.append(new_pattern)
    save_catalogue(patterns)
    return {"ok": True, "name": target, "count": len(patterns)}


# ---------------------------------------------------------------------------
# Catalogue import/export
# ---------------------------------------------------------------------------


def export_catalogue() -> dict:
    """Return the full catalogue as a dict for JSON download."""
    return {"patterns": load_catalogue()}


def import_catalogue(data: dict) -> dict:
    """Import patterns into the catalogue (merge).

    Args:
        data: dict with ``patterns`` list.

    Returns:
        ``{"ok": True, "imported": int, "total": int}``.

    Raises:
        ValueError: if validation fails.
    """
    if not data or "patterns" not in data:
        raise ValueError("Required field: patterns")

    imported = data["patterns"]
    if not isinstance(imported, list):
        raise ValueError("patterns must be a list")

    required_fields = {"rows", "room_width_cm", "room_depth_cm", "standard"}
    for i, p in enumerate(imported):
        missing = required_fields - set(p.keys())
        if missing:
            raise ValueError(f"Pattern #{i}: missing fields: {missing}")

    catalogue = load_catalogue()
    n_before = len(catalogue)
    for p in imported:
        catalogue.append(p)

    compact_catalogue_names(catalogue)
    save_catalogue(catalogue)

    return {
        "ok": True,
        "imported": len(catalogue) - n_before,
        "total": len(catalogue),
    }


# ---------------------------------------------------------------------------
# DSL parse/export
# ---------------------------------------------------------------------------


def dsl_parse(dsl_text: str) -> dict:
    """Parse pattern DSL text to JSON.

    Raises:
        DSLError: if parsing fails.
    """
    return parse_dsl(dsl_text)


def dsl_export(data: dict) -> dict:
    """Export a pattern JSON to DSL text.

    Returns:
        ``{"dsl": str}``.

    Raises:
        ValueError: if ``name`` is missing.
    """
    if not data or "name" not in data:
        raise ValueError("Required field: name")
    return {"dsl": to_dsl(data)}


def room_dsl_parse(dsl_text: str) -> dict:
    """Parse room DSL text to JSON.

    Returns:
        Dict with ``width_cm``, ``depth_cm``, ``windows``, ``openings``,
        ``exclusion_zones``, ``transparent_zones``.

    Raises:
        RoomDSLError: if parsing fails.
    """
    room = parse_room_dsl(dsl_text)
    return {
        "width_cm": room.width_cm,
        "depth_cm": room.depth_cm,
        "windows": [
            {"face": w.face.value, "offset_cm": w.offset_cm,
             "width_cm": w.width_cm}
            for w in room.windows
        ],
        "openings": [
            {"face": o.face.value, "offset_cm": o.offset_cm,
             "width_cm": o.width_cm, "has_door": o.has_door,
             "opens_inward": o.opens_inward,
             "hinge_side": o.hinge_side.value}
            for o in room.openings
        ],
        "exclusion_zones": [
            {"x_cm": z.x_cm, "y_cm": z.y_cm,
             "width_cm": z.width_cm, "depth_cm": z.depth_cm}
            for z in room.exclusion_zones
        ],
        "transparent_zones": [
            {"x_cm": z.x_cm, "y_cm": z.y_cm,
             "width_cm": z.width_cm, "depth_cm": z.depth_cm}
            for z in (room.transparent_zones or [])
        ],
    }
