"""Centralized configuration loader for OLM.

Loads project/config.json once at import time. Provides typed getters
and writers. Falls back to embedded defaults if config.json is absent.

Standards are generic slots (standard1, standard2, standard3) with
configurable labels — see docs/specs/STANDARDS.md.

IMPORTANT: This module must NOT import anything from olm.core to
avoid circular imports. Only stdlib imports (json, os, pathlib, logging).
"""

import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolve config.json path: olm/core/app_config.py -> olm/ -> AI-OLM/ -> project/
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "project" / "config.json"

# Embedded defaults (used when config.json is absent).
# Standards are intentionally empty — they are business data
# provided by the project/ layer, not by the generic core.
_EMBEDDED_DEFAULTS: dict = {
    "room_code": "14",
    "default_door_width_cm": 90,
    "desk_width_cm": 180,
    "desk_depth_cm": 80,
    "grid_cell_cm": 10,
    "matching": {
        "w_density": 0.5,
        "w_comfort": 0.5,
        "w_light": 1.0,
        "w_back_door": 1.0,
        "w_face_wall": 1.0,
        "w_distance": 1.0,
        "min_desks_drop_ratio": 0.30,
    },
    "standards": {},
    "current_standard": "",
    "circulation_visible": True,
    # Export floor-summary cartouche (configurable via Settings).
    "cartouche_title_pt": 22,
    "cartouche_body_pt": 20,
    "cartouche_x_px": 20,
    "cartouche_y_px": 20,
}


def _load() -> dict:
    """Load config.json, fall back to embedded defaults."""
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load %s: %s — using defaults",
                           _CONFIG_PATH, e)
    else:
        logger.info("Config not found at %s — using embedded defaults",
                     _CONFIG_PATH)
    return json.loads(json.dumps(_EMBEDDED_DEFAULTS))  # deep copy


def _file_mtime() -> float | None:
    """Return config.json modification time, or None if absent."""
    try:
        return _CONFIG_PATH.stat().st_mtime
    except OSError:
        return None


_cfg: dict = _load()
_cfg_mtime: float | None = _file_mtime()


def reload_if_changed() -> None:
    """Reload config from disk if the file changed since last load.

    Guards against a stale in-memory cache: the config is loaded once at
    import, but the dev-server reloader does not watch config.json. Without
    this guard, an external edit is invisible and the next settings save
    rewrites the whole file with the outdated in-memory value (D-252). Called
    before every read of display config and before every write.
    """
    global _cfg_mtime
    mtime = _file_mtime()
    if mtime is not None and mtime != _cfg_mtime:
        fresh = _load()
        _cfg.clear()
        _cfg.update(fresh)
        _cfg_mtime = mtime


def _save() -> None:
    """Persist config to disk atomically with .bak."""
    global _cfg_mtime
    path = str(_CONFIG_PATH)
    if _CONFIG_PATH.exists():
        shutil.copy2(path, path + '.bak')
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    _cfg_mtime = _file_mtime()


# ── Getters ────────────────────────────────────────────────────────────────

def get(key: str, default=None):
    """Get a top-level config value."""
    return _cfg.get(key, default)


def get_all_standards() -> list[str]:
    """Return the list of standard slot ids (insertion order)."""
    return list(_cfg.get("standards", {}).keys())


def get_standard_label(slot: str) -> str:
    """Return the display label for a standard slot."""
    std = _cfg.get("standards", {}).get(slot, {})
    return std.get("label", slot)


def get_derogatory_label(slot: str) -> str:
    """Return the derogatory-use label for a standard slot.

    Empty string means no derogatory citation is shown for this standard.
    """
    std = _cfg.get("standards", {}).get(slot, {})
    return std.get("derogatory_label", "")


def get_spacing(slot: str) -> dict:
    """Get spacing dict for a standard slot."""
    std = _cfg.get("standards", {}).get(slot, {})
    return dict(std.get("spacing", {}))


def get_current_standard() -> str:
    """Return the current_standard slot id."""
    reload_if_changed()
    return _cfg.get("current_standard", "")


def set_current_standard(slot: str) -> None:
    """Set current_standard and persist atomically.

    Args:
        slot: A valid standard slot id.

    Raises:
        ValueError: If slot is not in the defined standards.
    """
    reload_if_changed()
    if slot not in get_all_standards():
        raise ValueError(f"Unknown standard slot: {slot}")
    _cfg["current_standard"] = slot
    _save()


def get_room_code() -> str:
    """Return the room code used for OCR detection."""
    return _cfg.get("room_code", "14")


def get_matching() -> dict:
    """Return matching configuration."""
    return _cfg.get("matching", {"w_density": 0.5, "w_comfort": 0.5})


# ── Writers ────────────────────────────────────────────────────────────────

def update(key: str, value) -> None:
    """Update a top-level config key and persist."""
    reload_if_changed()
    _cfg[key] = value
    _save()


def update_nested(path: list[str], value) -> None:
    """Update a nested config key and persist.

    Args:
        path: list of keys, e.g. ["matching", "w_density"]
        value: new value
    """
    reload_if_changed()
    d = _cfg
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value
    _save()


def update_spacing(slot: str, values: dict) -> None:
    """Update spacing values for a standard slot and persist."""
    reload_if_changed()
    standards = _cfg.setdefault("standards", {})
    std = standards.setdefault(slot, {})
    spacing = std.setdefault("spacing", {})
    spacing.update(values)
    _save()


def update_standard_label(slot: str, label: str) -> None:
    """Update the display label for a standard slot and persist."""
    reload_if_changed()
    standards = _cfg.setdefault("standards", {})
    std = standards.setdefault(slot, {})
    std["label"] = label
    _save()


def reset_spacing(slot: str) -> None:
    """Reset spacing for a standard to embedded defaults.

    Note: with generic slots, embedded defaults are empty. This
    raises ValueError if the slot has no embedded defaults.
    """
    defaults = _EMBEDDED_DEFAULTS.get("standards", {}).get(slot, {})
    spacing = defaults.get("spacing", {})
    if not spacing:
        raise ValueError(f"No embedded defaults for slot: {slot}")
    reload_if_changed()
    standards = _cfg.setdefault("standards", {})
    std = standards.setdefault(slot, {})
    std["spacing"] = dict(spacing)
    _save()


def reload() -> None:
    """Reload config from disk. Useful after external modification."""
    global _cfg, _cfg_mtime
    _cfg = _load()
    _cfg_mtime = _file_mtime()
