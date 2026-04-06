"""Spacing configuration registry.

Spacing standards are loaded dynamically from project/config.json via
app_config. The generic core defines no built-in standards — they are
business data provided by the project layer.

Derived values (ES-04, ES-05) are computed from primitives.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, fields

from olm.core.app_config import get_spacing, get_all_standards
from olm.core.app_config import update_spacing as _update_spacing
from olm.core.app_config import reset_spacing as _reset_spacing

logger = logging.getLogger(__name__)


@dataclass
class SpacingConfig:
    """Spacing parameters for a given standard.

    All dimensions in centimetres.

    Attributes:
        name: Standard identifier.
        chair_clearance_cm: ES-01 — Chair clearance zone.
        front_access_cm: ES-02 — Front access (sit/stand).
        access_single_desk_cm: ES-03 — Access for a single desk against a wall.
        passage_behind_one_row_cm: ES-04 — Total depth desk→zone edge
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
    for name in get_all_standards():
        d = get_spacing(name)
        d["name"] = name
        configs[name] = SpacingConfig.from_dict(d)
    return configs


ALL_CONFIGS: dict[str, SpacingConfig] = _build_configs()


def get_default() -> SpacingConfig | None:
    """Return the first available standard, or None if none loaded."""
    if ALL_CONFIGS:
        return next(iter(ALL_CONFIGS.values()))
    return None


def get_default_name() -> str | None:
    """Return the name of the first available standard, or None."""
    if ALL_CONFIGS:
        return next(iter(ALL_CONFIGS.keys()))
    return None


def reset_config(name: str) -> SpacingConfig:
    """Reset a spacing config to its default values.

    Args:
        name: Standard name.

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
        name: Standard name.
        values: Dict of field names -> new values.

    Returns:
        The updated SpacingConfig.
    """
    _update_spacing(name, values)
    ALL_CONFIGS[name] = SpacingConfig.from_dict(
        {**get_spacing(name), "name": name})
    return ALL_CONFIGS[name]
