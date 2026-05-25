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

from olm.server.services.config_service import (
    BASE_DIR,
    PROJECT_ROOT,
    atomic_write_json,
    is_dev_mode,
)

CATALOGUE_DIR = os.path.join(PROJECT_ROOT, "project", "catalogue")
CATALOGUE_PATH = os.path.join(CATALOGUE_DIR, "patterns.json")

# Default catalogue shipped with the public code (olm/data/).
DEFAULT_CATALOGUE_PATH = os.path.join(
    BASE_DIR, "data", "default_catalogue.json",
)


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


def load_default_catalogue() -> list[dict]:
    """Load the default catalogue shipped with the public code.

    Returns:
        List of pattern dicts, or [] if file is absent or empty.
    """
    if not os.path.exists(DEFAULT_CATALOGUE_PATH):
        return []
    with open(DEFAULT_CATALOGUE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("patterns", [])


def find_pattern(patterns: list[dict], name: str) -> int:
    """Return the pattern index by name, or -1 if not found."""
    for i, p in enumerate(patterns):
        if p["name"] == name:
            return i
    return -1


# ---------------------------------------------------------------------------
# Pattern CRUD
# ---------------------------------------------------------------------------


def _add_fit_class(pattern: dict) -> None:
    """Annotate *pattern* with ``fit_class`` (ok/tolere/reject).

    Uses the pattern's standard to resolve spacing. Falls back to
    ``"ok"`` if the standard is unknown.  The pattern dict is mutated
    in-place (response-only, not persisted).
    """
    from olm.core.pattern_classify import classify_pattern
    from olm.core.spacing_config import ALL_CONFIGS

    std = pattern.get("standard", "")
    spacing = ALL_CONFIGS.get(std) if std else None
    if spacing is None:
        pattern["fit_class"] = "ok"
        return
    try:
        pattern["fit_class"] = classify_pattern(pattern, spacing)
    except Exception:
        logger.exception("classify_pattern failed for %s", pattern.get("name"))
        pattern["fit_class"] = "ok"


def _add_min_room(pattern: dict) -> None:
    """Annotate *pattern* with ``min_room_width`` / ``min_room_depth``.

    D-305: circulation-aware minimum room dimensions.  The pattern
    dict is mutated in-place (response-only, not persisted).
    """
    from olm.core.pattern_fit import compute_min_room_circ
    from olm.core.spacing_config import ALL_CONFIGS

    std = pattern.get("standard", "")
    spacing = ALL_CONFIGS.get(std) if std else None
    if spacing is None:
        return
    try:
        min_w, min_d = compute_min_room_circ(pattern, spacing)
        pattern["min_room_width"] = min_w
        pattern["min_room_depth"] = min_d
    except Exception:
        logger.exception(
            "_add_min_room failed for %s", pattern.get("name"),
        )


def list_patterns() -> dict:
    """Return all patterns with count, fit classification, and min room.

    Includes ``default_available`` flag for the first-launch banner:
    True when the private catalogue is empty and the default is not.

    Each pattern in the response carries ``fit_class``
    (``"ok"`` / ``"tolere"`` / ``"reject"``) and
    ``min_room_width`` / ``min_room_depth`` (D-305), computed
    on-the-fly and not persisted to disk.
    """
    patterns = load_catalogue()
    default_available = (
        len(patterns) == 0 and len(load_default_catalogue()) > 0
    )
    for p in patterns:
        _add_fit_class(p)
        _add_min_room(p)
    return {
        "patterns": patterns,
        "count": len(patterns),
        "default_available": default_available,
    }


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

    # D-213: canonicalize block order before saving
    from olm.core.pattern_canonicalize import canonicalize_blocks
    canonicalize_blocks(data)

    idx = find_pattern(patterns, data["name"])
    if idx >= 0:
        patterns[idx] = data
    else:
        patterns.append(data)

    compact_catalogue_names(patterns)
    save_catalogue(patterns)
    return {"ok": True, "name": data["name"], "count": len(patterns)}


def get_pattern(name: str) -> dict | None:
    """Return a pattern by name, or ``None`` if not found.

    The returned dict includes a ``fit_class`` field.
    """
    patterns = load_catalogue()
    idx = find_pattern(patterns, name)
    if idx < 0:
        return None
    p = patterns[idx]
    _add_fit_class(p)
    return p


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


def _get_target_spacing(target_standard: str | None = None):
    """Return the SpacingConfig for the target standard.

    Args:
        target_standard: Explicit standard slot id. If ``None``,
            falls back to the global active standard.

    Raises:
        ValueError: if the standard is unknown or not configured.
    """
    from olm.core.spacing_config import ALL_CONFIGS, get_default_name
    slot = target_standard or get_default_name()
    if not slot or slot not in ALL_CONFIGS:
        raise ValueError(f"Unknown standard: {slot!r}")
    return ALL_CONFIGS[slot]


def _recalibrate(
    patterns: list[dict],
    target_standard: str | None = None,
) -> dict:
    """Recalibrate patterns to the target standard via normalization.

    Mutates patterns in place.

    Args:
        patterns: List of pattern dicts.
        target_standard: Explicit standard slot. Falls back to global.

    Returns:
        Summary dict with counts: expanded / compressed / noop / errors.
    """
    from olm.core.pattern_normalize import normalize_catalogue
    spacing = _get_target_spacing(target_standard)
    results = normalize_catalogue(patterns, spacing)

    expanded = sum(1 for r in results if r.direction == "expanded")
    compressed = sum(1 for r in results if r.direction == "compressed")
    noop = sum(1 for r in results if r.direction == "noop")
    with_warnings = sum(1 for r in results if r.warnings)

    for r in results:
        if r.warnings:
            logger.info(
                "Pattern '%s': %s",
                r.name, "; ".join(r.warnings),
            )

    return {
        "expanded": expanded,
        "compressed": compressed,
        "noop": noop,
        "with_warnings": with_warnings,
    }


def import_catalogue(data: dict) -> dict:
    """Import patterns into the catalogue with recalibration.

    Standard-scoped replace: imported patterns (after recalibration to
    the target standard) replace all existing patterns of that standard.
    Patterns of other standards are preserved (strict isolation).

    Args:
        data: dict with ``patterns`` list and optional ``target_standard``.

    Returns:
        ``{"ok": True, "imported": int, "total": int,
          "recalibration": {...}}``.

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

    # Deep-copy to avoid mutating caller's data during recalibration
    imported = copy.deepcopy(imported)

    # Pop target_standard from data (injected by frontend)
    target_standard = data.pop("target_standard", None)

    # Recalibrate imported patterns to target standard
    recal_summary = _recalibrate(imported, target_standard)

    # Resolve the actual standard name after recalibration
    target_actual = _get_target_spacing(target_standard).name

    # Standard-scoped replace: keep patterns of other standards,
    # replace all patterns of the target standard with imported ones.
    existing = load_catalogue()
    catalogue = [p for p in existing if p.get("standard") != target_actual]
    catalogue.extend(imported)

    compact_catalogue_names(catalogue)
    save_catalogue(catalogue)

    return {
        "ok": True,
        "imported": len(imported),
        "total": len(catalogue),
        "recalibration": recal_summary,
    }


def import_default_catalogue(
    target_standard: str | None = None,
) -> dict:
    """Import the default catalogue into the private catalogue.

    Loads ALL patterns from the default (no standard filter), then
    delegates to ``import_catalogue`` which recalibrates everything
    to the target standard (standard-scoped replace on the private side).

    Args:
        target_standard: Standard to recalibrate to. Falls back to global.

    Returns:
        Same structure as ``import_catalogue``.

    Raises:
        ValueError: if default catalogue is empty.
    """
    default_patterns = load_default_catalogue()
    if not default_patterns:
        raise ValueError("Default catalogue is empty")
    data: dict = {"patterns": default_patterns}
    if target_standard:
        data["target_standard"] = target_standard
    return import_catalogue(data)


def save_as_default_catalogue(
    target_standard: str | None = None,
) -> dict:
    """Save private catalogue patterns of the target standard as default.

    Standard-scoped: only patterns matching the target standard are
    written to the default file. Patterns of other standards already
    present in the default are preserved (strict isolation).

    Requires --dev mode. Runs structural validations before writing.

    Args:
        target_standard: Standard to save. Falls back to global.

    Returns:
        ``{"ok": True, "count": int, "standard": str}``.

    Raises:
        PermissionError: if not in --dev mode.
        ValueError: if validation fails (with descriptive message).
    """
    if not is_dev_mode():
        raise PermissionError(
            "Save as default is only available in --dev mode"
        )

    target_actual = _get_target_spacing(target_standard).name
    all_patterns = load_catalogue()
    patterns = [
        p for p in all_patterns if p.get("standard") == target_actual
    ]
    if not patterns:
        raise ValueError(
            f"No patterns for standard '{target_actual}' "
            f"in the private catalogue"
        )

    # Validity check: footprint (body + face zones + door swing area)
    # must fit within room dimensions. Uses the single source of truth
    # in pattern_fit so PE, matcher and save-as-default share one rule.
    from olm.core.pattern_fit import (
        PatternStructurallyInvalid,
        compute_pattern_footprint,
        is_pattern_valid,
    )
    from olm.core.spacing_config import ALL_CONFIGS

    target_spacing = ALL_CONFIGS.get(target_actual)
    for pat in patterns:
        name = pat.get("name", "?")
        if target_spacing is None:
            continue
        try:
            x_min, x_max, y_min, y_max = compute_pattern_footprint(
                pat, target_spacing,
            )
        except PatternStructurallyInvalid as e:
            raise ValueError(f"Pattern '{name}': {e}") from e
        if not is_pattern_valid(pat, target_spacing):
            room_w = pat.get("room_width_cm", 0)
            room_d = pat.get("room_depth_cm", 0)
            raise ValueError(
                f"Pattern '{name}': footprint "
                f"x=[{x_min},{x_max}] y=[{y_min},{y_max}] "
                f"does not fit in room {room_w}x{room_d} cm"
            )

    # Overwrite the entire default (no merge — the default is mono-standard)
    default_dir = os.path.dirname(DEFAULT_CATALOGUE_PATH)
    os.makedirs(default_dir, exist_ok=True)
    atomic_write_json(
        DEFAULT_CATALOGUE_PATH,
        {"patterns": copy.deepcopy(patterns)},
    )

    logger.info(
        "Saved %d patterns (standard '%s') as default catalogue",
        len(patterns), target_actual,
    )
    return {
        "ok": True,
        "count": len(patterns),
        "standard": target_actual,
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
