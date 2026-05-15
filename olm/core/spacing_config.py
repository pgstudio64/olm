"""Spacing configuration registry.

Spacing standards are loaded dynamically from project/config.json via
app_config. The generic core defines no built-in standards — they are
business data provided by the project layer.

Derived values (ES-04, ES-05) are computed from primitives.
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
        front_access_cm: ES-02 — Front access (sit/stand).
        access_single_desk_cm: ES-03 — Access for a single desk against a wall.
        passage_behind_one_row_cm: ES-04 — Total depth desk-to-zone edge
            (chair clearance + free passage).
        passage_between_back_to_back_cm: ES-05 — Passage between two
            back-to-back rows.
        passage_cm: ES-06 — Passage between distinct blocks.
        door_exclusion_depth_cm: ES-08 — Clear zone in front of a door.
        desk_to_wall_cm: ES-09 — Lateral desk-to-wall distance.
        max_island_size: ES-10 — Maximum block size (desks).
        min_block_separation_cm: ES-11 — Minimum separation between blocks.
        main_corridor_cm: PS-04 — Main corridor width.
    """
    name: str
    chair_clearance_cm: int          # ES-01
    front_access_cm: int             # ES-02
    access_single_desk_cm: int       # ES-03
    passage_behind_one_row_cm: int   # ES-04
    passage_between_back_to_back_cm: int  # ES-05
    passage_cm: int                  # ES-06
    door_exclusion_depth_cm: int     # ES-08
    desk_to_wall_cm: int             # ES-09
    max_island_size: int             # ES-10
    min_block_separation_cm: int     # ES-11
    main_corridor_cm: int            # PS-04

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
]

# Face-to-face blocks: E/W zones = chair + passage (ES-06)
_FACE_TO_FACE_BLOCKS = {"BLOCK_2_FACE", "BLOCK_4_FACE", "BLOCK_6_FACE"}

# Orthogonal blocks: chair + passage_single zones on the chair faces
_ORTHO_BLOCKS: dict[str, set[str]] = {
    "BLOCK_2_ORTHO_R": {"north", "east"},
    "BLOCK_2_ORTHO_L": {"north", "west"},
}

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


def build_block_defs(cfg: SpacingConfig) -> dict[str, dict]:
    """Build block definitions for a given standard.

    Fixed zones (chair clearance) and circulation zones vary
    according to the layout standard.

    Args:
        cfg: Spacing configuration for the target standard.

    Returns:
        Dict mapping block name to its JSON definition (with faces).
    """
    chair = cfg.chair_clearance_cm
    passage = cfg.passage_cm
    passage_single = cfg.access_single_desk_cm - chair

    defs: dict[str, dict] = {}
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
