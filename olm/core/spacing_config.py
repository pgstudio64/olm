"""Configurations d'espacement par standard d'aménagement — solver_lab.

Trois standards d'aménagement (cf. glossaire GLOSSARY.md) :
- AFNOR ADVICE : normes NF X35-102, caractère consultatif
- GROUP : standard interne du groupe
- SITE : standard spécifique au site client

Les valeurs dérivées (ES-04, ES-05) sont calculées à partir des primitives.

Persistence : les valeurs peuvent être surchargées depuis un fichier JSON
(`spacing_overrides.json`). Les valeurs par défaut servent de fallback.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields

logger = logging.getLogger(__name__)

OVERRIDES_PATH = os.path.join(os.path.dirname(__file__), "spacing_overrides.json")


@dataclass
class SpacingConfig:
    """Paramètres d'espacement pour un standard d'aménagement donné.

    Toutes les dimensions en centimètres.

    Attributes:
        name: Identifiant du standard d'aménagement.
        chair_clearance_cm: ES-01 — Débattement chaise.
        front_access_cm: ES-02 — Accès frontal (s'asseoir).
        access_single_desk_cm: ES-03 — Accès poste seul dos à un mur.
        passage_behind_one_row_cm: ES-04 — Distance totale desk→extrémité zone
            (inclut recul fauteuil 70cm + passage libre).
        passage_between_back_to_back_cm: ES-05 — Passage entre 2 rangées dos à dos.
        passage_cm: ES-06 — Passage entre deux blocs distincts.
        door_exclusion_depth_cm: ES-08 — Zone libre devant porte.
        desk_to_wall_cm: ES-09 — Distance latérale table-mur.
        max_island_size: ES-10 — Taille max d'un bloc.
        min_block_separation_cm: ES-11 — Séparation minimale entre blocs.
        main_corridor_cm: PS-04 — Largeur couloir principal.
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


# ── Default values ────────────────────────────────────────────────────────

_DEFAULTS = {
    "AFNOR_ADVICE": SpacingConfig(
        name="AFNOR_ADVICE",
        chair_clearance_cm=70,
        front_access_cm=60,
        access_single_desk_cm=100,
        passage_behind_one_row_cm=160,
        passage_between_back_to_back_cm=230,
        passage_cm=90,
        door_exclusion_depth_cm=180,
        desk_to_wall_cm=20,
        max_island_size=4,
        min_block_separation_cm=90,
        main_corridor_cm=140,
    ),
    "GROUP": SpacingConfig(
        name="GROUP",
        chair_clearance_cm=70,
        front_access_cm=60,
        access_single_desk_cm=90,
        passage_behind_one_row_cm=120,
        passage_between_back_to_back_cm=180,
        passage_cm=90,
        door_exclusion_depth_cm=180,
        desk_to_wall_cm=10,
        max_island_size=6,
        min_block_separation_cm=90,
        main_corridor_cm=140,
    ),
    "SITE": SpacingConfig(
        name="SITE",
        chair_clearance_cm=70,
        front_access_cm=60,
        access_single_desk_cm=90,
        passage_behind_one_row_cm=140,
        passage_between_back_to_back_cm=160,
        passage_cm=90,
        door_exclusion_depth_cm=120,
        desk_to_wall_cm=0,
        max_island_size=6,
        min_block_separation_cm=90,
        main_corridor_cm=140,
    ),
}


# ── Mutable config with persistence ──────────────────────────────────────

def _load_overrides() -> dict[str, dict]:
    """Load overrides from JSON file if it exists."""
    if os.path.exists(OVERRIDES_PATH):
        try:
            with open(OVERRIDES_PATH) as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load spacing overrides: %s", e)
    return {}


def _save_overrides(overrides: dict[str, dict]) -> None:
    """Persist overrides to JSON file."""
    with open(OVERRIDES_PATH, "w") as f:
        json.dump(overrides, f, indent=2)


def _build_configs() -> dict[str, SpacingConfig]:
    """Build configs by merging defaults with any saved overrides."""
    overrides = _load_overrides()
    configs = {}
    for name, default in _DEFAULTS.items():
        d = default.to_dict()
        if name in overrides:
            d.update(overrides[name])
            d["name"] = name  # ensure name stays correct
        configs[name] = SpacingConfig.from_dict(d)
    return configs


ALL_CONFIGS: dict[str, SpacingConfig] = _build_configs()

# Named references for backward compatibility
AFNOR_ADVICE = ALL_CONFIGS["AFNOR_ADVICE"]
GROUP = ALL_CONFIGS["GROUP"]
SITE = ALL_CONFIGS["SITE"]


def reset_config(name: str) -> SpacingConfig:
    """Reset a spacing config to its default values.

    Args:
        name: Standard name.

    Returns:
        The default SpacingConfig.
    """
    if name not in _DEFAULTS:
        raise ValueError(f"Unknown standard: {name}")
    ALL_CONFIGS[name] = SpacingConfig.from_dict(_DEFAULTS[name].to_dict())
    overrides = _load_overrides()
    overrides.pop(name, None)
    _save_overrides(overrides)
    return ALL_CONFIGS[name]


def update_config(name: str, values: dict) -> SpacingConfig:
    """Update a spacing config and persist to disk.

    Args:
        name: Standard name (AFNOR_ADVICE, GROUP, SITE).
        values: Dict of field names → new values.

    Returns:
        The updated SpacingConfig.
    """
    if name not in ALL_CONFIGS:
        raise ValueError(f"Unknown standard: {name}")

    current = ALL_CONFIGS[name].to_dict()
    current.update(values)
    current["name"] = name
    updated = SpacingConfig.from_dict(current)
    ALL_CONFIGS[name] = updated

    # Persist only the delta from defaults
    overrides = _load_overrides()
    default_d = _DEFAULTS[name].to_dict()
    delta = {k: v for k, v in current.items() if v != default_d.get(k)}
    if delta:
        overrides[name] = delta
    elif name in overrides:
        del overrides[name]
    _save_overrides(overrides)

    return updated
