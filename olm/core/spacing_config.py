"""Configurations d'espacement par standard d'aménagement — solver_lab.

Trois standards d'aménagement (cf. glossaire GLOSSARY.md) :
- AFNOR ADVICE : normes NF X35-102, caractère consultatif
- GROUP : standard interne du groupe
- SITE : standard spécifique au site client

Les valeurs dérivées (ES-04, ES-05) sont calculées à partir des primitives.

Persistence : les valeurs sont lues depuis project/config.json via app_config.
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

# Named references for backward compatibility
AFNOR_ADVICE = ALL_CONFIGS["AFNOR_ADVICE"]
GROUP = ALL_CONFIGS["GROUP"]
SITE = ALL_CONFIGS["SITE"]


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
        name: Standard name (AFNOR_ADVICE, GROUP, SITE).
        values: Dict of field names → new values.

    Returns:
        The updated SpacingConfig.
    """
    _update_spacing(name, values)
    ALL_CONFIGS[name] = SpacingConfig.from_dict(
        {**get_spacing(name), "name": name})
    return ALL_CONFIGS[name]
