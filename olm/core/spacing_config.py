"""Spacing configuration registry.

Spacing standards are loaded dynamically from project/config.json via
app_config. The generic core defines no built-in standards — they are
business data provided by the project layer.

D-229: 6 parameters (3 atomic primitives + 3 independent).
Derived distances (access single desk, passage behind one person, etc.)
are computed on the fly, never stored.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, fields

import olm.core.pattern_generator as _pg
from olm.core.app_config import (
    get_all_standards,
    get_current_standard,
    get_spacing,
)
from olm.core.app_config import reset_spacing as _reset_spacing
from olm.core.app_config import update_spacing as _update_spacing

logger = logging.getLogger(__name__)


@dataclass
class SpacingConfig:
    """Spacing parameters for a given standard.

    All dimensions in centimetres.

    Attributes:
        name: Standard slot identifier (e.g. "standard1").
        chair_clearance_cm: ES-01 — Chair clearance zone.
        walking_margin_cm: ES-02 — Walking margin beyond chair.
        slip_in_margin_cm: ES-03 — Slip-in margin for single
            desk access.
        main_corridor_cm: ES-04 — Main corridor width.
        door_exclusion_depth_cm: ES-05 — Clear zone in front
            of a door.
        max_island_size: ES-06 — Maximum block size (desks).
        main_corridor_threshold: D-233 — Number of desks
            served by a gap to qualify as main corridor.
    """
    name: str
    chair_clearance_cm: int          # ES-01
    walking_margin_cm: int           # ES-02
    slip_in_margin_cm: int           # ES-03
    main_corridor_cm: int            # ES-04
    door_exclusion_depth_cm: int     # ES-05
    max_island_size: int             # ES-06
    distance_tolerance_cm: int = 5     # D-257
    main_corridor_threshold: int = 6  # D-233

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SpacingConfig:
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)


# ── Build configs from app_config ─────────────────────────────────────────

def _build_configs() -> dict[str, SpacingConfig]:
    """Build SpacingConfig instances from app_config."""
    configs = {}
    for slot in get_all_standards():
        d = get_spacing(slot)
        d["name"] = slot
        configs[slot] = SpacingConfig.from_dict(d)
    return configs


ALL_CONFIGS: dict[str, SpacingConfig] = _build_configs()


def get_default() -> SpacingConfig | None:
    """Return the current standard config, or the first available."""
    current = get_current_standard()
    if current and current in ALL_CONFIGS:
        return ALL_CONFIGS[current]
    if ALL_CONFIGS:
        return next(iter(ALL_CONFIGS.values()))
    return None


def get_default_name() -> str | None:
    """Return the current standard slot id, or the first available."""
    current = get_current_standard()
    if current and current in ALL_CONFIGS:
        return current
    if ALL_CONFIGS:
        return next(iter(ALL_CONFIGS.keys()))
    return None


def reset_config(name: str) -> SpacingConfig:
    """Reset a spacing config to its default values.

    Args:
        name: Standard slot id.

    Returns:
        The reset SpacingConfig.
    """
    _reset_spacing(name)
    ALL_CONFIGS[name] = SpacingConfig.from_dict(
        {**get_spacing(name), "name": name})
    return ALL_CONFIGS[name]


def update_config(name: str, values: dict) -> SpacingConfig:
    """Update a spacing config and persist to disk.

    Args:
        name: Standard slot id.
        values: Dict of field names -> new values.

    Returns:
        The updated SpacingConfig.
    """
    _update_spacing(name, values)
    ALL_CONFIGS[name] = SpacingConfig.from_dict(
        {**get_spacing(name), "name": name})
    return ALL_CONFIGS[name]


# ── Block definitions per standard ────────────────────────────────────────
# Extracted from olm/server/services/config_service.py so that core modules
# (pattern_fit) can build block defs without importing the server layer.

_BASE_BLOCKS = [
    _pg.BLOCK_1, _pg.BLOCK_2_FACE, _pg.BLOCK_2_SIDE, _pg.BLOCK_3_SIDE,
    _pg.BLOCK_4_FACE, _pg.BLOCK_6_FACE,
    _pg.BLOCK_2_ORTHO_L, _pg.BLOCK_2_ORTHO_R,
    _pg.CABINET,
]

# Block dimension formulas: (eo_factor_w, eo_factor_d, ns_factor_w, ns_factor_d)
_BLOCK_DESK_FACTORS: dict[str, tuple[int, int, int, int]] = {
    "BLOCK_1":          (0, 1, 1, 0),
    "BLOCK_2_FACE":     (0, 2, 1, 0),
    "BLOCK_2_SIDE":     (0, 1, 2, 0),
    "BLOCK_3_SIDE":     (0, 1, 3, 0),
    "BLOCK_4_FACE":     (0, 2, 2, 0),
    "BLOCK_6_FACE":     (0, 2, 3, 0),
    "BLOCK_2_ORTHO_R":  (1, 0, 1, 1),
    "BLOCK_2_ORTHO_L":  (1, 0, 1, 1),
}


def _block_def_to_json(block: _pg.Block) -> dict:
    """Convert a Block to a JSON dict, recomputing dimensions from config.

    Uses current module-level DESK_W_CM / DESK_D_CM from pattern_generator
    so that runtime desk-dimension changes are reflected.
    """
    factors = _BLOCK_DESK_FACTORS.get(block.name)
    if factors:
        fw, fd, gw, gd = factors
        eo = fw * _pg.DESK_W_CM + fd * _pg.DESK_D_CM
        ns = gw * _pg.DESK_W_CM + gd * _pg.DESK_D_CM
    elif block.name == "CABINET":
        # D-256: read current module-level dims (reactive to config changes)
        eo = _pg.CABINET_W_CM
        ns = _pg.CABINET_D_CM
    else:
        eo = block.eo_cm
        ns = block.ns_cm
    return {
        "name": block.name,
        "eo_cm": eo,
        "ns_cm": ns,
        "n_desks": block.n_desks,
        "derogatory": block.derogatory,
        "furniture": block.furniture,
        "faces": {
            "north": {"non_superposable_cm": block.faces.north.non_superposable_cm,
                       "candidate_cm": block.faces.north.candidate_cm,
                       "internal": block.faces.north.internal},
            "south": {"non_superposable_cm": block.faces.south.non_superposable_cm,
                       "candidate_cm": block.faces.south.candidate_cm,
                       "internal": block.faces.south.internal},
            "east":  {"non_superposable_cm": block.faces.east.non_superposable_cm,
                       "candidate_cm": block.faces.east.candidate_cm,
                       "internal": block.faces.east.internal},
            "west":  {"non_superposable_cm": block.faces.west.non_superposable_cm,
                       "candidate_cm": block.faces.west.candidate_cm,
                       "internal": block.faces.west.internal},
        },
    }


def build_block_defs(cfg: SpacingConfig) -> dict[str, dict]:
    """Build block definitions for a given standard.

    D-244: candidate_cm = slip_in_margin_cm on chair faces so that the
    backend footprint includes the slip-in zone (grey band drawn by
    the frontend). Non-chair faces keep candidate_cm = 0.
    non_superposable_cm = cfg.chair_clearance_cm on chair faces
    (faces where the module-level block has non_superposable_cm > 0).

    Args:
        cfg: Spacing configuration for the target standard.

    Returns:
        Dict mapping block name to its JSON definition (with faces).
    """
    chair = cfg.chair_clearance_cm
    slip_in = cfg.slip_in_margin_cm
    defs: dict[str, dict] = {}
    for block in _BASE_BLOCKS:
        d = _block_def_to_json(block)
        for face_dir in ("north", "south", "east", "west"):
            fd = d["faces"][face_dir]
            has_chair = fd["non_superposable_cm"] > 0
            if has_chair:
                fd["non_superposable_cm"] = chair
                fd["candidate_cm"] = slip_in
            else:
                fd["candidate_cm"] = 0
            # D-316: pre-compute outer_extent_cm (overhang for internal
            # faces, total_cm for normal faces).
            total = fd["non_superposable_cm"] + fd["candidate_cm"]
            if not fd.get("internal", False):
                fd["outer_extent_cm"] = total
            else:
                # Void depth: block edge minus desk edge on the
                # internal face's axis.  Derived from block geometry,
                # reactive to desk dimension changes.
                if face_dir in ("east", "west"):
                    void_depth = d["eo_cm"] - _pg.DESK_D_CM
                else:
                    void_depth = d["ns_cm"] - _pg.DESK_D_CM
                fd["outer_extent_cm"] = max(0, total - void_depth)
        defs[block.name] = d
    return defs
