"""Configuration service — project config, plans dir, detection overrides, blocks.

This module is the root dependency for all other services. It does NOT
import from any other ``olm.server.services.*`` module.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import shutil

import olm.core.pattern_generator as _pg
from olm.core.spacing_config import ALL_CONFIGS

logger = logging.getLogger(__name__)

# Runtime flag — set by app.py __main__ via set_dev_mode().
# Stored here (not in app.py) to avoid the __main__ dual-import problem.
_DEV_MODE: bool = False


# ---------------------------------------------------------------------------
# Atomic JSON write helper (P2.6 / D-188)
# ---------------------------------------------------------------------------


def atomic_write_json(path: str, data: dict) -> None:
    """Write JSON atomically with .bak of the previous version.

    1. If ``path`` exists, copy it to ``path + '.bak'``.
    2. Write to ``path + '.tmp'``.
    3. ``os.replace`` the tmp onto the target (atomic on POSIX & Windows).
    """
    if os.path.exists(path):
        shutil.copy2(path, path + '.bak')
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def set_dev_mode(enabled: bool) -> None:
    """Set developer mode flag (called from app.py __main__)."""
    global _DEV_MODE
    _DEV_MODE = enabled


def is_dev_mode() -> bool:
    """Return True if the server is running in developer mode."""
    return _DEV_MODE

# ---------------------------------------------------------------------------
# Paths — resolved once at import time
# ---------------------------------------------------------------------------

# olm/server/services/config_service.py → olm/server/services → olm/server → olm
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))            # olm/
PROJECT_ROOT = os.path.dirname(BASE_DIR)   # AI-OLM/

_CONFIG_PATH = os.path.join(PROJECT_ROOT, "project", "config.json")

# ---------------------------------------------------------------------------
# Project config loader (cached)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def load_project_config() -> dict:
    """Load and cache ``project/config.json``. Returns ``{}`` on error."""
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Cannot read %s: %s", _CONFIG_PATH, exc)
        return {}


# ---------------------------------------------------------------------------
# Plans directory
# ---------------------------------------------------------------------------


def get_plans_dir() -> str:
    """Return the plans directory path from config.json, or the default.

    Reads ``ingestion.plans_dir`` from ``project/config.json``. Relative
    paths are resolved against the project root. Falls back to
    ``<root>/project/plans`` if the key is absent or the file unreadable.
    """
    _default = os.path.join(PROJECT_ROOT, "project", "plans")
    _plans_dir = load_project_config().get("ingestion", {}).get(
        "plans_dir", "")
    if not _plans_dir:
        return _default
    if os.path.isabs(_plans_dir):
        return _plans_dir
    return os.path.join(PROJECT_ROOT, _plans_dir)


# ---------------------------------------------------------------------------
# Detection overrides (D-155)
# ---------------------------------------------------------------------------


def get_detection_overrides() -> dict | None:
    """Read OCR detection overrides from config.json (D-155).

    Returns a dict suitable for ``DetectionConfigCm.from_dict`` or ``None``
    if no overrides are configured.
    """
    _ing = load_project_config().get("ingestion", {})
    overrides = {}
    for key in ("cartouche_margin_cm", "text_skip_margin_cm",
                "corridor_width_cm", "exterior_width_cm",
                "max_door_width_cm", "min_opening_depth_cm",
                "min_obstacle_width_cm", "min_pillar_size_cm",
                "max_pillar_size_cm", "comb_step_cm",
                "max_opening_face_ratio"):
        if key in _ing:
            overrides[key] = float(_ing[key])
    if "binarize_threshold" in _ing:
        overrides["binarize_threshold"] = int(_ing["binarize_threshold"])
    return overrides or None


# ---------------------------------------------------------------------------
# Threshold & color helpers
# ---------------------------------------------------------------------------

_DEFAULT_EXTERIOR_RGB = (135, 206, 235)
_DEFAULT_CORRIDOR_RGB = (193, 247, 179)


def get_default_threshold() -> int:
    """Read binarize threshold from config.json, default 110."""
    _ing = load_project_config().get("ingestion", {})
    return int(_ing.get("binarize_threshold", 110))


def get_exterior_rgb() -> tuple[int, int, int]:
    """Read preprocessed exterior RGB from config.json (D-156)."""
    rgb = load_project_config().get("ingestion", {}).get(
        "preprocessed_exterior_rgb")
    if rgb and len(rgb) == 3:
        return tuple(int(v) for v in rgb)  # type: ignore[return-value]
    return _DEFAULT_EXTERIOR_RGB


def get_corridor_rgb() -> tuple[int, int, int]:
    """Read preprocessed corridor RGB from config.json."""
    rgb = load_project_config().get("ingestion", {}).get(
        "preprocessed_corridor_rgb")
    if rgb and len(rgb) == 3:
        return tuple(int(v) for v in rgb)  # type: ignore[return-value]
    return _DEFAULT_CORRIDOR_RGB


# ---------------------------------------------------------------------------
# Block definitions — delegated to olm.core.spacing_config.build_block_defs
# ---------------------------------------------------------------------------

from olm.core.spacing_config import build_block_defs as _build_block_defs

# Cache by standard
_BLOCK_DEFS_CACHE: dict[str, dict] = {}


def get_block_defs(standard_name: str) -> dict:
    """Return block defs for a standard (with cache)."""
    if standard_name not in _BLOCK_DEFS_CACHE:
        cfg = ALL_CONFIGS.get(standard_name)
        if cfg is None:
            from olm.core.spacing_config import get_default
            cfg = get_default()
        _BLOCK_DEFS_CACHE[standard_name] = _build_block_defs(cfg)
    return _BLOCK_DEFS_CACHE[standard_name]


def invalidate_block_cache(standard_name: str | None = None) -> None:
    """Invalidate block defs cache (one standard or all)."""
    if standard_name is None:
        _BLOCK_DEFS_CACHE.clear()
    else:
        _BLOCK_DEFS_CACHE.pop(standard_name, None)


# ---------------------------------------------------------------------------
# Config GET/POST logic
# ---------------------------------------------------------------------------


def _sync_runtime_dims() -> None:
    """Keep pattern_generator desk/cabinet dims in sync with config.json.

    ``update_config`` propagates desk/cabinet changes made via the UI, but a
    change made by any other means (direct file edit, or a server started
    before the value was set) would leave ``_pg.DESK_W_CM`` and the block-defs
    cache stale while the frontend reads the fresh value — producing a body
    (server ``eo_cm``) that no longer matches the desks (JS ``DESK_W``). This
    re-propagates on mismatch so both sides agree.
    """
    from olm.core import app_config
    dw = app_config.get("desk_width_cm", 180)
    dd = app_config.get("desk_depth_cm", 80)
    cw = app_config.get("cabinet_width_cm", 70)
    cd = app_config.get("cabinet_depth_cm", 40)
    changed = False
    if _pg.DESK_W_CM != dw or _pg.DESK_D_CM != dd:
        _pg.refresh_desk_dims(dw, dd)
        changed = True
    if _pg.CABINET_W_CM != cw or _pg.CABINET_D_CM != cd:
        _pg.refresh_cabinet_dims(cw, cd)
        changed = True
    if changed:
        from olm.core.catalogue_matcher import rebuild_block_registry
        rebuild_block_registry()
        invalidate_block_cache()


def get_config() -> dict:
    """Return full config dict augmented with olm_version and dev_mode.

    Exposes ``standards`` (slot -> {label, spacing}) and ``current_standard``.
    Legacy keys ``standard_labels``, ``spacing``, ``default_standard`` are
    omitted.
    """
    from olm import __version__
    from olm.core import app_config
    app_config.reload_if_changed()
    _sync_runtime_dims()
    cfg = dict(app_config._cfg)
    cfg["olm_version"] = __version__
    cfg["dev_mode"] = _DEV_MODE
    # Remove legacy keys that no longer exist in config.json
    cfg.pop("standard_labels", None)
    cfg.pop("spacing", None)
    cfg.pop("default_standard", None)
    return cfg


def update_config(data: dict) -> dict:
    """Update configuration keys and persist.

    Args:
        data: dict with either ``{key, value}`` (flat) or
              ``{path, value}`` (nested).

    Returns:
        ``{"ok": True}`` on success.

    Raises:
        ValueError: if neither ``key`` nor ``path`` is present.
    """
    from olm.core import app_config
    if "path" in data:
        app_config.update_nested(data["path"], data["value"])
    elif "key" in data:
        app_config.update(data["key"], data["value"])
    else:
        raise ValueError("Missing 'key' or 'path'")
    # Propagate desk/cabinet dimension changes to all dependent structures
    key = data.get("key", "")
    if key in ("desk_width_cm", "desk_depth_cm"):
        from olm.core.catalogue_matcher import rebuild_block_registry
        _pg.refresh_desk_dims(
            app_config.get("desk_width_cm", 180),
            app_config.get("desk_depth_cm", 80),
        )
        rebuild_block_registry()
        invalidate_block_cache()
    elif key in ("cabinet_width_cm", "cabinet_depth_cm"):
        from olm.core.catalogue_matcher import rebuild_block_registry
        _pg.refresh_cabinet_dims(
            app_config.get("cabinet_width_cm", 70),
            app_config.get("cabinet_depth_cm", 40),
        )
        rebuild_block_registry()
        invalidate_block_cache()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Blocks endpoint logic
# ---------------------------------------------------------------------------


def get_blocks(standard: str | None = None) -> dict:
    """Return block definitions for the requested standard.

    Args:
        standard: standard slot id. If ``None``, uses current_standard.

    Returns:
        Dict with ``blocks``, ``standard``, and ``constants``.
    """
    from olm.core.app_config import get_current_standard
    from olm.core.spacing_config import get_default
    std = standard or get_current_standard()
    cfg = ALL_CONFIGS.get(std, get_default())
    block_defs = get_block_defs(std)
    return {
        "blocks": block_defs,
        "standard": std,
        "constants": {
            "DESK_W_CM": _pg.DESK_W_CM,
            "DESK_D_CM": _pg.DESK_D_CM,
            "CHAIR_CLEARANCE_CM": cfg.chair_clearance_cm,
            "WALKING_MARGIN_CM": cfg.walking_margin_cm,
            "SLIP_IN_MARGIN_CM": cfg.slip_in_margin_cm,
            "MAIN_CORRIDOR_THRESHOLD": cfg.main_corridor_threshold,
        },
    }


# ---------------------------------------------------------------------------
# Spacing endpoint logic
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Upload validation (P2.1)
# ---------------------------------------------------------------------------

ALLOWED_UPLOAD_MIMES = frozenset({
    "image/png",
    "image/jpeg",
    "image/tiff",
    "application/pdf",
})


def _validate_upload(file) -> tuple[bool, str]:
    """Validate an uploaded file's MIME type.

    Args:
        file: A Flask ``FileStorage`` object.

    Returns:
        ``(True, "")`` if the MIME type is allowed, or
        ``(False, error_message)`` otherwise.
    """
    if file.mimetype not in ALLOWED_UPLOAD_MIMES:
        return False, (
            f"Type non accepté : {file.mimetype}. "
            f"Types autorisés : {', '.join(sorted(ALLOWED_UPLOAD_MIMES))}"
        )
    return True, ""


def get_health_status(uptime_seconds: float) -> tuple[dict, bool]:
    """Run health checks and return a status dict.

    Args:
        uptime_seconds: elapsed seconds since process start.

    Returns:
        ``(result_dict, all_ok)`` — ``all_ok`` is ``False`` if any check
        failed.
    """
    from olm import __version__
    checks: dict[str, bool] = {}
    errors: list[str] = []

    # config_readable
    try:
        load_project_config.cache_clear()
        cfg = load_project_config()
        checks["config_readable"] = isinstance(cfg, dict)
    except Exception as exc:
        checks["config_readable"] = False
        errors.append(f"config read error: {exc}")

    # catalogue_loadable
    try:
        from olm.server.services.catalogue_service import load_catalogue
        cat = load_catalogue()
        checks["catalogue_loadable"] = isinstance(cat, list)
    except Exception as exc:
        checks["catalogue_loadable"] = False
        errors.append(f"catalogue parse error: {exc}")

    # plans_dir_exists / plans_dir_writable
    try:
        plans = get_plans_dir()
        checks["plans_dir_exists"] = os.path.isdir(plans)
        if checks["plans_dir_exists"]:
            checks["plans_dir_writable"] = os.access(plans, os.W_OK)
        else:
            checks["plans_dir_writable"] = False
            errors.append(f"plans dir missing: {plans}")
    except Exception as exc:
        checks["plans_dir_exists"] = False
        checks["plans_dir_writable"] = False
        errors.append(f"plans dir error: {exc}")

    all_ok = all(checks.values())
    result: dict = {
        "status": "ok" if all_ok else "degraded",
        "version": __version__,
        "checks": checks,
        "uptime_seconds": round(uptime_seconds, 1),
    }
    if errors:
        result["errors"] = errors
    return result, all_ok


def get_spacing() -> dict:
    """Return all spacing configurations (slot -> {label, spacing})."""
    from olm.core import app_config
    result = {}
    for slot, cfg in ALL_CONFIGS.items():
        result[slot] = {
            "label": app_config.get_standard_label(slot),
            "spacing": cfg.to_dict(),
        }
    return result


def update_spacing(data: dict) -> dict:
    """Update a spacing standard.

    Args:
        data: dict with ``standard`` (req), ``values`` (opt), ``reset`` (opt).

    Returns:
        ``{"ok": True, "config": {...}}`` on success.

    Raises:
        ValueError: if ``standard`` is missing.
    """
    from olm.core.spacing_config import reset_config
    from olm.core.spacing_config import update_config as sp_update
    name = data.get("standard")
    values = data.get("values", {})
    if not name:
        raise ValueError("Required field: standard")
    if data.get("reset"):
        updated = reset_config(name)
    else:
        updated = sp_update(name, values)
    invalidate_block_cache(name)
    return {"ok": True, "config": updated.to_dict()}


def update_label(slot: str, label: str) -> dict:
    """Update the display label for a standard slot.

    Args:
        slot: Standard slot id.
        label: New display label.

    Returns:
        ``{"ok": True}``.
    """
    from olm.core import app_config
    app_config.update_standard_label(slot, label)
    return {"ok": True}


def update_current_standard(slot: str) -> dict:
    """Update the current_standard and persist.

    Args:
        slot: Standard slot id.

    Returns:
        ``{"ok": True, "current_standard": slot}``.

    Raises:
        ValueError: If slot is invalid.
    """
    from olm.core import app_config
    app_config.set_current_standard(slot)
    return {"ok": True, "current_standard": slot}
