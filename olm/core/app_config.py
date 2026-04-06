"""Centralized configuration loader for OLM.

Loads project/config.json once at import time. Provides typed getters
and writers. Falls back to embedded defaults if config.json is absent.

Spacing standards (e.g. AFNOR, GROUP, SITE) are business data defined
in project/config.json — the generic core has no built-in standards.

IMPORTANT: This module must NOT import anything from olm.core to
avoid circular imports. Only stdlib imports (json, os, pathlib, logging).
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolve config.json path: olm/core/app_config.py -> olm/ -> AI-OLM/ -> project/
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "project" / "config.json"

# Embedded defaults (used when config.json is absent).
# Spacing standards are intentionally empty — they are business data
# provided by the project/ layer, not by the generic core.
_EMBEDDED_DEFAULTS = {
    "room_code": "14",
    "standard_labels": {},
    "default_door_width_cm": 90,
    "desk_width_cm": 180,
    "desk_depth_cm": 80,
    "grid_cell_cm": 10,
    "matching": {
        "w_density": 0.5,
        "w_comfort": 0.5,
        "min_desks_drop_ratio": 0.30,
    },
    "spacing": {},
}


def _load() -> dict:
    """Load config.json, fall back to embedded defaults."""
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load %s: %s — using defaults", _CONFIG_PATH, e)
    else:
        logger.info("Config not found at %s — using embedded defaults", _CONFIG_PATH)
    return json.loads(json.dumps(_EMBEDDED_DEFAULTS))  # deep copy


_cfg: dict = _load()


def _save() -> None:
    """Persist config to disk atomically."""
    tmp = str(_CONFIG_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, _CONFIG_PATH)


# ── Getters ────────────────────────────────────────────────────────────────

def get(key: str, default=None):
    """Get a top-level config value."""
    return _cfg.get(key, default)


def get_spacing(standard: str) -> dict:
    """Get spacing dict for a standard. Returns defaults if not found."""
    spacing = _cfg.get("spacing", {})
    defaults = _EMBEDDED_DEFAULTS.get("spacing", {})
    return spacing.get(standard, defaults.get(standard, {}))


def get_all_standards() -> list[str]:
    """Return the list of standard keys."""
    return list(_cfg.get("spacing", {}).keys())


def get_standard_label(key: str) -> str:
    """Return the display label for a standard key."""
    labels = _cfg.get("standard_labels", {})
    return labels.get(key, key)


def get_room_code() -> str:
    """Return the room code used for OCR detection."""
    return _cfg.get("room_code", "14")


def get_matching() -> dict:
    """Return matching configuration."""
    return _cfg.get("matching", {"w_density": 0.5, "w_comfort": 0.5})


# ── Writers ────────────────────────────────────────────────────────────────

def update(key: str, value) -> None:
    """Update a top-level config key and persist."""
    _cfg[key] = value
    _save()


def update_nested(path: list[str], value) -> None:
    """Update a nested config key and persist.

    Args:
        path: list of keys, e.g. ["matching", "w_density"]
        value: new value
    """
    d = _cfg
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value
    _save()


def update_spacing(standard: str, values: dict) -> None:
    """Update spacing values for a standard and persist."""
    spacing = _cfg.setdefault("spacing", {})
    current = spacing.setdefault(standard, {})
    current.update(values)
    _save()


def reset_spacing(standard: str) -> None:
    """Reset spacing for a standard to embedded defaults."""
    defaults = _EMBEDDED_DEFAULTS.get("spacing", {}).get(standard, {})
    if not defaults:
        raise ValueError(f"Unknown standard: {standard}")
    _cfg.setdefault("spacing", {})[standard] = dict(defaults)
    _save()


def reload() -> None:
    """Reload config from disk. Useful after external modification."""
    global _cfg
    _cfg = _load()
