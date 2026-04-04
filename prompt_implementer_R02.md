Implémente R-02 (Settings centralisés) dans le projet ~/AI-OLM/. Ce sont les étapes backend 1 à 9 + tests. L'étape 10 (UI HTML/JS) sera faite séparément.

ÉTAPE 1 -- Enrichir project/config.json

Remplacer le contenu de ~/AI-OLM/project/config.json par :

{
  "room_code": "14",
  "standard_labels": {
    "AFNOR_ADVICE": "AFNOR",
    "GROUP": "GROUP",
    "SITE": "SITE"
  },
  "default_door_width_cm": 90,
  "desk_width_cm": 80,
  "desk_depth_cm": 180,
  "grid_cell_cm": 10,
  "matching": {
    "w_density": 0.5,
    "w_comfort": 0.5,
    "min_desks_drop_ratio": 0.30
  },
  "ingestion": {
    "scale_cm_per_px": 0.5
  },
  "export": {
    "formats": ["json"]
  },
  "spacing": {
    "AFNOR_ADVICE": {
      "chair_clearance_cm": 70,
      "front_access_cm": 60,
      "access_single_desk_cm": 100,
      "passage_behind_one_row_cm": 160,
      "passage_between_back_to_back_cm": 230,
      "passage_cm": 90,
      "door_exclusion_depth_cm": 180,
      "desk_to_wall_cm": 20,
      "max_island_size": 4,
      "min_block_separation_cm": 90,
      "main_corridor_cm": 140
    },
    "GROUP": {
      "chair_clearance_cm": 70,
      "front_access_cm": 60,
      "access_single_desk_cm": 90,
      "passage_behind_one_row_cm": 120,
      "passage_between_back_to_back_cm": 180,
      "passage_cm": 90,
      "door_exclusion_depth_cm": 180,
      "desk_to_wall_cm": 10,
      "max_island_size": 6,
      "min_block_separation_cm": 90,
      "main_corridor_cm": 140
    },
    "SITE": {
      "chair_clearance_cm": 70,
      "front_access_cm": 60,
      "access_single_desk_cm": 90,
      "passage_behind_one_row_cm": 140,
      "passage_between_back_to_back_cm": 160,
      "passage_cm": 90,
      "door_exclusion_depth_cm": 120,
      "desk_to_wall_cm": 0,
      "max_island_size": 6,
      "min_block_separation_cm": 90,
      "main_corridor_cm": 140
    }
  }
}

ÉTAPE 2 -- Créer olm/core/app_config.py

Créer le fichier ~/AI-OLM/olm/core/app_config.py avec ce contenu :

"""Centralized configuration loader for OLM.

Loads project/config.json once at import time. Provides typed getters
and writers. Falls back to embedded defaults if config.json is absent.

IMPORTANT: This module must NOT import anything from olm.core to
avoid circular imports. Only stdlib imports (json, os, pathlib, logging).
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

-- Resolve config.json path: olm/core/app_config.py -> olm/ -> AI-OLM/ -> project/
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "project" / "config.json"

-- Embedded defaults (used when config.json is absent)
_EMBEDDED_DEFAULTS = {
    "room_code": "14",
    "standard_labels": {
        "AFNOR_ADVICE": "AFNOR",
        "GROUP": "GROUP",
        "SITE": "SITE",
    },
    "default_door_width_cm": 90,
    "desk_width_cm": 80,
    "desk_depth_cm": 180,
    "grid_cell_cm": 10,
    "matching": {
        "w_density": 0.5,
        "w_comfort": 0.5,
        "min_desks_drop_ratio": 0.30,
    },
    "spacing": {
        "AFNOR_ADVICE": {
            "chair_clearance_cm": 70,
            "front_access_cm": 60,
            "access_single_desk_cm": 100,
            "passage_behind_one_row_cm": 160,
            "passage_between_back_to_back_cm": 230,
            "passage_cm": 90,
            "door_exclusion_depth_cm": 180,
            "desk_to_wall_cm": 20,
            "max_island_size": 4,
            "min_block_separation_cm": 90,
            "main_corridor_cm": 140,
        },
        "GROUP": {
            "chair_clearance_cm": 70,
            "front_access_cm": 60,
            "access_single_desk_cm": 90,
            "passage_behind_one_row_cm": 120,
            "passage_between_back_to_back_cm": 180,
            "passage_cm": 90,
            "door_exclusion_depth_cm": 180,
            "desk_to_wall_cm": 10,
            "max_island_size": 6,
            "min_block_separation_cm": 90,
            "main_corridor_cm": 140,
        },
        "SITE": {
            "chair_clearance_cm": 70,
            "front_access_cm": 60,
            "access_single_desk_cm": 90,
            "passage_behind_one_row_cm": 140,
            "passage_between_back_to_back_cm": 160,
            "passage_cm": 90,
            "door_exclusion_depth_cm": 120,
            "desk_to_wall_cm": 0,
            "max_island_size": 6,
            "min_block_separation_cm": 90,
            "main_corridor_cm": 140,
        },
    },
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
    return json.loads(json.dumps(_EMBEDDED_DEFAULTS))  -- deep copy


_cfg: dict = _load()


def _save() -> None:
    """Persist config to disk atomically."""
    tmp = str(_CONFIG_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, _CONFIG_PATH)


-- Getters

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


-- Writers

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


ATTENTION : dans ce fichier, tous les commentaires Python doivent utiliser le symbole dièse. Le texte ci-dessus utilise -- pour les commentaires à cause d'une contrainte de formatage. Remplacer tous les -- en début de ligne par le symbole dièse suivi d'un espace.

ÉTAPE 3 -- Refactorer olm/core/spacing_config.py

Dans ~/AI-OLM/olm/core/spacing_config.py :

a) Supprimer la ligne OVERRIDES_PATH et l'import os (si plus utilisé).

b) Remplacer le bloc _DEFAULTS (lignes 71-114 environ) par un import :
   from olm.core.app_config import get_spacing, get_all_standards
   from olm.core.app_config import update_spacing as _update_spacing
   from olm.core.app_config import reset_spacing as _reset_spacing

c) Remplacer _load_overrides, _save_overrides, _build_configs par :

   def _build_configs() -> dict[str, SpacingConfig]:
       """Build SpacingConfig instances from app_config."""
       configs = {}
       for name in get_all_standards():
           d = get_spacing(name)
           d["name"] = name
           configs[name] = SpacingConfig.from_dict(d)
       return configs

d) Garder ALL_CONFIGS, AFNOR_ADVICE, GROUP, SITE inchangés.

e) Remplacer reset_config par :

   def reset_config(name: str) -> SpacingConfig:
       _reset_spacing(name)
       ALL_CONFIGS[name] = SpacingConfig.from_dict(
           {**get_spacing(name), "name": name})
       return ALL_CONFIGS[name]

f) Remplacer update_config par :

   def update_config(name: str, values: dict) -> SpacingConfig:
       _update_spacing(name, values)
       ALL_CONFIGS[name] = SpacingConfig.from_dict(
           {**get_spacing(name), "name": name})
       return ALL_CONFIGS[name]

g) Supprimer l'ancien import de OVERRIDES_PATH, la ligne qui le définit, et les fonctions _load_overrides/_save_overrides.

ÉTAPE 4 -- Refactorer olm/core/pattern_generator.py

Dans ~/AI-OLM/olm/core/pattern_generator.py, remplacer les deux premières constantes :

Avant :
  DESK_W_CM = 80
  DESK_D_CM = 180

Après :
  from olm.core.app_config import get as _cfg_get
  DESK_W_CM: int = _cfg_get("desk_width_cm", 80)
  DESK_D_CM: int = _cfg_get("desk_depth_cm", 180)

Ne pas toucher aux autres constantes (CHAIR_CLEARANCE_CM etc.) qui sont dérivées des blocs.

ÉTAPE 5 -- Refactorer olm/core/matching_config.py

Dans ~/AI-OLM/olm/core/matching_config.py, remplacer :

Avant :
  GRID_CELL_CM = 10

Après :
  from olm.core.app_config import get as _cfg_get
  GRID_CELL_CM: int = _cfg_get("grid_cell_cm", 10)

Si MIN_DESKS_DROP_RATIO existe, le remplacer aussi :
  MIN_DESKS_DROP_RATIO: float = _cfg_get("matching", {}).get("min_desks_drop_ratio", 0.30) if isinstance(_cfg_get("matching", {}), dict) else 0.30

ÉTAPE 6 -- Ajouter /api/config dans olm/server/app.py

Ajouter ces deux routes dans ~/AI-OLM/olm/server/app.py, juste après les routes /api/spacing existantes :

@app.route("/api/config", methods=["GET"])
def api_config_get():
    """Return the full configuration."""
    from olm.core import app_config
    return jsonify(app_config._cfg)


@app.route("/api/config", methods=["POST"])
def api_config_post():
    """Update configuration keys and persist.

    Body: {"key": "room_code", "value": "15"}
    or:   {"path": ["matching", "w_density"], "value": 0.7}
    """
    from olm.core import app_config
    data = request.json
    if "path" in data:
        app_config.update_nested(data["path"], data["value"])
    elif "key" in data:
        app_config.update(data["key"], data["value"])
    else:
        return jsonify({"error": "Missing 'key' or 'path'"}), 400
    return jsonify({"ok": True})

ÉTAPE 7 -- Mettre à jour olm/core/catalogue_matcher.py

Dans ~/AI-OLM/olm/core/catalogue_matcher.py :

a) Chercher le dict _STD_SHORT (qui contient "AFNOR_ADVICE": "AFNOR" etc.).
   Le remplacer par un import :
   from olm.core.app_config import get_standard_label

b) Partout où _STD_SHORT[xxx] ou _STD_SHORT.get(xxx) est utilisé, remplacer par get_standard_label(xxx).

c) Si _STD_LONG existe aussi, le supprimer et utiliser get_standard_label.

ÉTAPE 8 -- Mettre à jour olm/core/circulation_analysis.py

Dans ~/AI-OLM/olm/core/circulation_analysis.py :

a) Chercher les lignes avec AFNOR_ADVICE.door_exclusion_depth_cm dans des signatures de fonctions.

b) Ajouter en haut du fichier (après les imports existants de spacing_config) :
   _DEFAULT_DOOR_DEPTH = AFNOR_ADVICE.door_exclusion_depth_cm

c) Remplacer les default arguments qui utilisent AFNOR_ADVICE.door_exclusion_depth_cm par _DEFAULT_DOOR_DEPTH.

ÉTAPE 9 -- Mettre à jour olm/ingestion/extract.py

Dans ~/AI-OLM/olm/ingestion/extract.py :

a) Dans la fonction classify_texts (ou _is_room_code, ou là où "14" est comparé au texte détecté), ajouter :
   from olm.core.app_config import get_room_code

b) Remplacer la comparaison if stripped == "14": par if stripped == get_room_code():

ÉTAPE 10 -- Vérification

Exécuter dans l'ordre :

  cd ~/AI-OLM
  python -c "from olm.core.app_config import get; print('room_code:', get('room_code'))"
  python -c "from olm.core.app_config import get_all_standards; print('standards:', get_all_standards())"
  python -c "from olm.core.spacing_config import ALL_CONFIGS; print('spacing OK:', len(ALL_CONFIGS), 'configs')"
  python -c "from olm.core.pattern_generator import DESK_W_CM, DESK_D_CM; print('desk:', DESK_W_CM, 'x', DESK_D_CM)"
  python -c "from olm.core.matching_config import GRID_CELL_CM; print('grid:', GRID_CELL_CM)"
  python -c "from olm.core.catalogue_matcher import match_room; print('matcher OK')"
  python -m pytest olm/tests/ -v --tb=short

Si des erreurs d'import apparaissent, les corriger. La cause sera toujours un import non mis à jour.

ÉTAPE 11 -- Supprimer spacing_overrides.json

Si le fichier ~/AI-OLM/olm/core/spacing_overrides.json existe, le supprimer. Toute la persistance est dans project/config.json maintenant.

ÉTAPE 12 -- Commit

  cd ~/AI-OLM
  git add -A
  git commit -m "R-02: Settings centralisés — project/config.json source unique de vérité

  Nouveau module olm/core/app_config.py : charge config.json, expose getters/writers.
  spacing_config.py, pattern_generator.py, matching_config.py, catalogue_matcher.py,
  circulation_analysis.py, extract.py refactorés pour lire depuis app_config.
  Endpoint /api/config GET/POST ajouté dans app.py.
  spacing_overrides.json supprimé — tout dans config.json.

  Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

Quand tout est terminé, affiche un résumé : nombre de tests passés, résultats des vérifications.
