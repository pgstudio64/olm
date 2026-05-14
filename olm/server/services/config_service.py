"""Configuration service — project config, plans dir, detection overrides, blocks.

This module is the root dependency for all other services. It does NOT
import from any other ``olm.server.services.*`` module.
"""
from __future__ import annotations

import functools
import json
import logging
import os

from olm.core.pattern_generator import (
    BLOCK_1, BLOCK_2_FACE, BLOCK_2_SIDE, BLOCK_3_SIDE, BLOCK_4_FACE,
    BLOCK_6_FACE, BLOCK_2_ORTHO_L, BLOCK_2_ORTHO_R,
    DESK_W_CM, DESK_D_CM,
)
from olm.core.spacing_config import ALL_CONFIGS

logger = logging.getLogger(__name__)

# Runtime flag — set by app.py __main__ via set_dev_mode().
# Stored here (not in app.py) to avoid the __main__ dual-import problem.
_DEV_MODE: bool = False


def set_dev_mode(enabled: bool) -> None:
    """Set developer mode flag (called from app.py __main__)."""
    global _DEV_MODE
    _DEV_MODE = enabled

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
# Block definitions
# ---------------------------------------------------------------------------

_BASE_BLOCKS = [
    BLOCK_1, BLOCK_2_FACE, BLOCK_2_SIDE, BLOCK_3_SIDE,
    BLOCK_4_FACE, BLOCK_6_FACE, BLOCK_2_ORTHO_L, BLOCK_2_ORTHO_R,
]

# Face-to-face blocks: E/W zones = chair + passage (ES-06)
_FACE_TO_FACE_BLOCKS = {"BLOCK_2_FACE", "BLOCK_4_FACE", "BLOCK_6_FACE"}

# Orthogonal blocks: chair + passage_single zones on the chair faces
_ORTHO_BLOCKS = {
    "BLOCK_2_ORTHO_R": {"north", "east"},
    "BLOCK_2_ORTHO_L": {"north", "west"},
}

# Block dimension formulas: (eo_factor_w, eo_factor_d, ns_factor_w, ns_factor_d)
_BLOCK_DESK_FACTORS = {
    "BLOCK_1":          (0, 1, 1, 0),
    "BLOCK_2_FACE":     (0, 2, 1, 0),
    "BLOCK_2_SIDE":     (0, 1, 2, 0),
    "BLOCK_3_SIDE":     (0, 1, 3, 0),
    "BLOCK_4_FACE":     (0, 2, 2, 0),
    "BLOCK_6_FACE":     (0, 2, 3, 0),
    "BLOCK_2_ORTHO_R":  (1, 0, 1, 1),
    "BLOCK_2_ORTHO_L":  (1, 0, 1, 1),
}


def _block_def_to_json(block) -> dict:
    """Convert a Block to a JSON dict, recomputing dimensions from config."""
    from olm.core.pattern_generator import DESK_W_CM, DESK_D_CM
    factors = _BLOCK_DESK_FACTORS.get(block.name)
    if factors:
        fw, fd, gw, gd = factors
        eo = fw * DESK_W_CM + fd * DESK_D_CM
        ns = gw * DESK_W_CM + gd * DESK_D_CM
    else:
        eo = block.eo_cm
        ns = block.ns_cm
    return {
        "name": block.name,
        "eo_cm": eo,
        "ns_cm": ns,
        "n_desks": block.n_desks,
        "derogatory": block.derogatory,
        "faces": {
            "north": {"non_superposable_cm": block.faces.north.non_superposable_cm,
                       "candidate_cm": block.faces.north.candidate_cm},
            "south": {"non_superposable_cm": block.faces.south.non_superposable_cm,
                       "candidate_cm": block.faces.south.candidate_cm},
            "east":  {"non_superposable_cm": block.faces.east.non_superposable_cm,
                       "candidate_cm": block.faces.east.candidate_cm},
            "west":  {"non_superposable_cm": block.faces.west.non_superposable_cm,
                       "candidate_cm": block.faces.west.candidate_cm},
        },
    }


def _build_block_defs(cfg) -> dict:
    """Build block definitions for a given standard.

    Fixed zones (chair clearance) and circulation zones vary
    according to the layout standard.
    """
    chair = cfg.chair_clearance_cm
    passage = cfg.passage_cm
    passage_single = cfg.access_single_desk_cm - chair

    defs = {}
    for block in _BASE_BLOCKS:
        d = _block_def_to_json(block)
        if block.name in _FACE_TO_FACE_BLOCKS:
            for face in ("east", "west"):
                d["faces"][face] = {
                    "non_superposable_cm": chair,
                    "candidate_cm": passage,
                }
        elif block.name in _ORTHO_BLOCKS:
            chair_faces = _ORTHO_BLOCKS[block.name]
            for face in ("north", "south", "east", "west"):
                if face in chair_faces:
                    d["faces"][face] = {
                        "non_superposable_cm": chair,
                        "candidate_cm": passage_single,
                    }
                else:
                    d["faces"][face] = {
                        "non_superposable_cm": 0,
                        "candidate_cm": 0,
                    }
        else:
            d["faces"]["west"] = {
                "non_superposable_cm": chair,
                "candidate_cm": passage_single,
            }
        defs[block.name] = d
    return defs


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


def get_config() -> dict:
    """Return full config dict augmented with olm_version and dev_mode."""
    from olm.core import app_config
    from olm import __version__
    cfg = dict(app_config._cfg)
    cfg["olm_version"] = __version__
    cfg["dev_mode"] = _DEV_MODE
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
    # Invalidate block defs cache when desk dimensions change
    key = data.get("key", "")
    if key in ("desk_width_cm", "desk_depth_cm"):
        import olm.core.pattern_generator as pg
        pg.DESK_W_CM = app_config.get("desk_width_cm", 180)
        pg.DESK_D_CM = app_config.get("desk_depth_cm", 80)
        invalidate_block_cache()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Blocks endpoint logic
# ---------------------------------------------------------------------------


def get_blocks(standard: str | None = None) -> dict:
    """Return block definitions for the requested standard.

    Args:
        standard: standard name (e.g. ``"SITE"``). If ``None``, uses the
                  default from config.

    Returns:
        Dict with ``blocks``, ``standard``, and ``constants``.
    """
    from olm.core.spacing_config import get_default_name, get_default
    import olm.core.pattern_generator as pg
    default_name = get_default_name() or ""
    std = standard or default_name
    cfg = ALL_CONFIGS.get(std, get_default())
    block_defs = get_block_defs(std)
    return {
        "blocks": block_defs,
        "standard": std,
        "constants": {
            "DESK_W_CM": pg.DESK_W_CM,
            "DESK_D_CM": pg.DESK_D_CM,
            "CHAIR_CLEARANCE_CM": cfg.chair_clearance_cm,
            "PASSAGE_CM": cfg.passage_cm,
            "PASSAGE_SINGLE_CM": cfg.access_single_desk_cm
            - cfg.chair_clearance_cm,
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


def get_spacing() -> dict:
    """Return all spacing configurations."""
    configs = {}
    for name, cfg in ALL_CONFIGS.items():
        configs[name] = cfg.to_dict()
    return configs


def update_spacing(data: dict) -> dict:
    """Update a spacing standard.

    Args:
        data: dict with ``standard`` (req), ``values`` (opt), ``reset`` (opt).

    Returns:
        ``{"ok": True, "config": {...}}`` on success.

    Raises:
        ValueError: if ``standard`` is missing.
    """
    from olm.core.spacing_config import update_config as sp_update, reset_config
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
