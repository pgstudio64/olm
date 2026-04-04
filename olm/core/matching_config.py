"""Paramètres du matching statique et de la grille — solver_lab.

Regroupe les paramètres algorithmiques du pipeline statique (grille,
seuils de filtrage). Les paramètres normatifs (espacements, zones
d'exclusion) restent dans spacing_config.py.
"""

from olm.core.app_config import get as _cfg_get

# Taille de cellule en cm. Utilisé pour le balayage du matching, la construction
# de la grille de circulation et toutes les discrétisations géométriques.
GRID_CELL_CM: int = _cfg_get("grid_cell_cm", 10)

# Seuil de filtrage par nombre de postes.
# Les candidats avec moins de (1 - ratio) × max_postes_trouvés sont éliminés.
# Exemple : ratio=0.30 → on garde les candidats avec ≥ 70% du meilleur.
_matching = _cfg_get("matching", {})
MIN_DESKS_DROP_RATIO: float = (
    _matching.get("min_desks_drop_ratio", 0.30) if isinstance(_matching, dict) else 0.30
)
