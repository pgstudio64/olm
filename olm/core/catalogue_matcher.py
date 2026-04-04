"""Matching de patterns catalogue vers pièces réelles — solver_lab.

Pipeline (D-39/D-40, TODO Étape 3) :
    1. Sélection : emprise ≤ pièce + front de Pareto (largeur, profondeur)
    2. Miroir E-O
    3. Calage sticks + homothétie
    4. Suppression unitaire de postes en zone interdite
    5. Scoring (circulation + confort)
    6. Sélection du meilleur par standard
    7. Rectangle vide résiduel

Module : croisement 3 standards × pièces cibles.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

import copy

from olm.core.app_config import get_standard_label
from olm.core.room_model import RoomSpec
from olm.core.spacing_config import ALL_CONFIGS
from olm.core.pattern_generator import (
    DESK_W_CM, DESK_D_CM,
    BLOC_1, BLOC_2_FACE, BLOC_2_COTE, BLOC_3_COTE, BLOC_4_FACE, BLOC_6_FACE,
    BLOC_2_ORTHO_D, BLOC_2_ORTHO_G,
)

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOGUE_PATH = os.path.join(BASE_DIR, "catalogue", "patterns.json")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PatternCandidate:
    """Pattern candidat issu de la sélection.

    Attributes:
        pattern: Données JSON brutes du pattern.
        name: Nom du pattern.
        room_width_cm: Largeur de la pièce du pattern.
        room_depth_cm: Profondeur de la pièce du pattern.
        standard: Standard d'aménagement.
        n_desks: Nombre total de postes.
    """
    pattern: dict
    name: str
    room_width_cm: int
    room_depth_cm: int
    standard: str
    n_desks: int


@dataclass
class SelectionResult:
    """Résultat de la sélection pour un standard donné.

    Attributes:
        standard: Nom du standard.
        candidates: Patterns sur le front de Pareto.
        all_fitting: Tous les patterns dont l'emprise rentre (avant Pareto).
    """
    standard: str
    candidates: list[PatternCandidate]
    all_fitting: list[PatternCandidate]


# ---------------------------------------------------------------------------
# Chargement catalogue
# ---------------------------------------------------------------------------

def load_catalogue(path: str = CATALOGUE_PATH) -> list[dict]:
    """Charge le catalogue de patterns depuis le fichier JSON.

    Args:
        path: Chemin vers le fichier catalogue.

    Returns:
        Liste des patterns (dicts JSON).
    """
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("patterns", [])


# ---------------------------------------------------------------------------
# Comptage de postes
# ---------------------------------------------------------------------------

# Dimensions canoniques (eo_cm, ns_cm) et nombre de postes par type
_BLOCK_REGISTRY = {
    "BLOC_1":          (BLOC_1.eo_cm, BLOC_1.ns_cm, 1),
    "BLOC_2_FACE":     (BLOC_2_FACE.eo_cm, BLOC_2_FACE.ns_cm, 2),
    "BLOC_2_COTE":     (BLOC_2_COTE.eo_cm, BLOC_2_COTE.ns_cm, 2),
    "BLOC_3_COTE":     (BLOC_3_COTE.eo_cm, BLOC_3_COTE.ns_cm, 3),
    "BLOC_4_FACE":     (BLOC_4_FACE.eo_cm, BLOC_4_FACE.ns_cm, 4),
    "BLOC_6_FACE":     (BLOC_6_FACE.eo_cm, BLOC_6_FACE.ns_cm, 6),
    "BLOC_2_ORTHO_D":  (BLOC_2_ORTHO_D.eo_cm, BLOC_2_ORTHO_D.ns_cm, 2),
    "BLOC_2_ORTHO_G":  (BLOC_2_ORTHO_G.eo_cm, BLOC_2_ORTHO_G.ns_cm, 2),
}

_BLOCK_N_DESKS = {k: v[2] for k, v in _BLOCK_REGISTRY.items()}

# Types de blocs ortho (miroir = swap D↔G)
_ORTHO_MIRROR = {
    "BLOC_2_ORTHO_D": "BLOC_2_ORTHO_G",
    "BLOC_2_ORTHO_G": "BLOC_2_ORTHO_D",
}


def count_desks(pattern: dict) -> int:
    """Compte le nombre total de postes dans un pattern JSON.

    Args:
        pattern: Pattern au format catalogue JSON.

    Returns:
        Nombre de postes.
    """
    total = 0
    for row in pattern.get("rows", []):
        for block in row.get("blocks", []):
            btype = block.get("type", "")
            total += _BLOCK_N_DESKS.get(btype, 0)
    return total


# ---------------------------------------------------------------------------
# Étape 1 — Sélection + front de Pareto
# ---------------------------------------------------------------------------

def effective_dimensions(room: RoomSpec) -> tuple[int, int]:
    """Calcule les dimensions effectives d'une pièce après exclusions périphériques.

    Une exclusion est périphérique si elle longe un mur sur toute sa largeur
    ou profondeur. Elle réduit la dimension effective correspondante.

    Returns:
        (effective_width_cm, effective_depth_cm)
    """
    ew = room.width_cm
    ed = room.depth_cm

    for z in room.exclusion_zones:
        # North strip: y=0, covers full width
        if z.y_cm == 0 and z.x_cm == 0 and z.width_cm >= room.width_cm:
            ed -= z.depth_cm
        # South strip: y + depth = room depth, covers full width
        elif (z.y_cm + z.depth_cm >= room.depth_cm
              and z.x_cm == 0 and z.width_cm >= room.width_cm):
            ed -= z.depth_cm
        # West strip: x=0, covers full depth
        elif z.x_cm == 0 and z.y_cm == 0 and z.depth_cm >= room.depth_cm:
            ew -= z.width_cm
        # East strip: x + width = room width, covers full depth
        elif (z.x_cm + z.width_cm >= room.width_cm
              and z.y_cm == 0 and z.depth_cm >= room.depth_cm):
            ew -= z.width_cm

    return max(0, ew), max(0, ed)


def _fits_in_room(pattern: dict, room: RoomSpec) -> bool:
    """Vérifie si l'emprise du pattern rentre dans la pièce cible.

    Utilise les dimensions effectives (après exclusions périphériques).
    """
    pw = pattern.get("room_width_cm", 0)
    pd = pattern.get("room_depth_cm", 0)
    ew, ed = effective_dimensions(room)
    return pw <= ew and pd <= ed


def _is_dominated(p: PatternCandidate, others: list[PatternCandidate]) -> bool:
    """Vérifie si p est dominé par au moins un autre candidat.

    Un pattern P1 domine P2 si :
        P1.room_width_cm >= P2.room_width_cm ET
        P1.room_depth_cm >= P2.room_depth_cm ET
        au moins une inégalité stricte.
    """
    for o in others:
        if o is p:
            continue
        if (o.room_width_cm >= p.room_width_cm
                and o.room_depth_cm >= p.room_depth_cm
                and (o.room_width_cm > p.room_width_cm
                     or o.room_depth_cm > p.room_depth_cm)):
            return True
    return False


def pareto_front(candidates: list[PatternCandidate]) -> list[PatternCandidate]:
    """Extrait le front de Pareto sur (largeur, profondeur).

    Les patterns dominés en largeur ET profondeur par un autre sont exclus.

    Args:
        candidates: Liste de candidats dont l'emprise rentre dans la pièce.

    Returns:
        Sous-liste des candidats non dominés.
    """
    if len(candidates) <= 1:
        return list(candidates)
    return [p for p in candidates if not _is_dominated(p, candidates)]


def select_candidates(
    catalogue: list[dict],
    room: RoomSpec,
    standard: str | None = None,
) -> SelectionResult | list[SelectionResult]:
    """Sélectionne les patterns candidats pour une pièce cible.

    Filtre par emprise (≤ pièce) puis extrait le front de Pareto.
    Si standard est spécifié, retourne un seul SelectionResult.
    Sinon, retourne une liste de 3 SelectionResult (un par standard).

    Args:
        catalogue: Patterns JSON du catalogue.
        room: Pièce cible.
        standard: Standard d'aménagement (None = tous les 3).

    Returns:
        SelectionResult ou liste de SelectionResult.
    """
    standards = [standard] if standard else list(ALL_CONFIGS.keys())
    results = []

    for std in standards:
        fitting = []
        for p in catalogue:
            if p.get("standard") != std:
                continue
            if not _fits_in_room(p, room):
                continue
            candidate = PatternCandidate(
                pattern=p,
                name=p["name"],
                room_width_cm=p["room_width_cm"],
                room_depth_cm=p["room_depth_cm"],
                standard=std,
                n_desks=count_desks(p),
            )
            fitting.append(candidate)

        front = pareto_front(fitting)
        # Tri par nombre de postes décroissant
        front.sort(key=lambda c: c.n_desks, reverse=True)

        results.append(SelectionResult(
            standard=std,
            candidates=front,
            all_fitting=fitting,
        ))

        logger.info(
            "Sélection %s : %d patterns rentrent, %d sur le front Pareto",
            std, len(fitting), len(front),
        )

    if standard:
        return results[0]
    return results


# ---------------------------------------------------------------------------
# Étape 2 — Miroir Est-Ouest
# ---------------------------------------------------------------------------

def _block_eo_extent(block: dict) -> int:
    """Largeur EO d'un bloc à son orientation courante.

    Args:
        block: Bloc JSON avec 'type' et 'orientation'.

    Returns:
        Largeur en cm dans l'axe EO.
    """
    btype = block.get("type", "")
    orient = block.get("orientation", 0)
    eo, ns, _ = _BLOCK_REGISTRY.get(btype, (0, 0, 0))
    if orient in (90, 270):
        return ns
    return eo


def _mirror_block(block: dict) -> dict:
    """Miroir E-O d'un bloc individuel.

    - Types ortho : ORTHO_D ↔ ORTHO_G, orientation = (360 - θ) % 360
    - Autres blocs : orientation = (180 - θ) % 360
    - Sticks : E ↔ O
    - offset_ns_cm inchangé

    Args:
        block: Bloc JSON original.

    Returns:
        Nouveau dict bloc miroir.
    """
    b = copy.deepcopy(block)
    btype = b.get("type", "")
    orient = b.get("orientation", 0)

    # Swap type ortho
    if btype in _ORTHO_MIRROR:
        b["type"] = _ORTHO_MIRROR[btype]
        b["orientation"] = (360 - orient) % 360
    else:
        b["orientation"] = (180 - orient) % 360

    # Swap sticks E ↔ O (W est un alias de O dans certains cas)
    if "sticks" in b:
        _STICK_MIRROR = {"E": "O", "O": "E", "W": "E", "N": "N", "S": "S"}
        b["sticks"] = [_STICK_MIRROR.get(s, s) for s in b["sticks"]]

    return b


def _mirror_row(row: dict, room_width_cm: int) -> dict:
    """Miroir E-O d'une rangée de blocs.

    Inverse l'ordre des blocs et recalcule les gaps.

    Args:
        row: Rangée JSON {"blocks": [...]}.
        room_width_cm: Largeur de la pièce.

    Returns:
        Nouvelle rangée miroir.
    """
    blocks = row.get("blocks", [])
    if not blocks:
        return copy.deepcopy(row)

    # Calculer les positions absolues de chaque bloc
    positions = []  # (x_start, width)
    x = 0
    for block in blocks:
        gap = block.get("gap_cm", 0)
        w = _block_eo_extent(block)
        x += gap
        positions.append((x, w))
        x += w

    # Espace résiduel à droite
    remaining_right = room_width_cm - x

    # Miroir : ordre inversé, positions reflétées
    mirrored_blocks = []
    n = len(blocks)
    prev_right = 0

    for i in range(n - 1, -1, -1):
        orig_x, orig_w = positions[i]
        # Position miroir du bloc
        mirror_x = room_width_cm - orig_x - orig_w
        gap = mirror_x - prev_right
        mirrored_block = _mirror_block(blocks[i])
        mirrored_block["gap_cm"] = gap
        mirrored_blocks.append(mirrored_block)
        prev_right = mirror_x + orig_w

    return {"blocks": mirrored_blocks}


def _mirror_windows(windows: list[dict], room_width_cm: int) -> list[dict]:
    """Miroir E-O des fenêtres."""
    result = []
    for w in windows:
        mw = copy.deepcopy(w)
        face = mw.get("face", "")
        if face in ("north", "south"):
            mw["offset_cm"] = room_width_cm - mw["offset_cm"] - mw["width_cm"]
        elif face == "east":
            mw["face"] = "west"
        elif face == "west":
            mw["face"] = "east"
        result.append(mw)
    return result


def _mirror_openings(openings: list[dict], room_width_cm: int) -> list[dict]:
    """Miroir E-O des ouvertures (portes)."""
    result = []
    for o in openings:
        mo = copy.deepcopy(o)
        face = mo.get("face", "")
        if face in ("north", "south"):
            mo["offset_cm"] = room_width_cm - mo["offset_cm"] - mo["width_cm"]
        elif face == "east":
            mo["face"] = "west"
        elif face == "west":
            mo["face"] = "east"
        # Swap hinge side
        hs = mo.get("hinge_side", "left")
        mo["hinge_side"] = "right" if hs == "left" else "left"
        result.append(mo)
    return result


def _mirror_exclusions(
    exclusions: list[dict], room_width_cm: int,
) -> list[dict]:
    """Miroir E-O des zones d'exclusion."""
    result = []
    for z in exclusions:
        mz = copy.deepcopy(z)
        mz["x_cm"] = room_width_cm - z["x_cm"] - z["width_cm"]
        result.append(mz)
    return result


def mirror_pattern(pattern: dict) -> dict:
    """Génère le miroir Est-Ouest d'un pattern.

    Le miroir reflète le pattern autour de l'axe vertical central :
    - Blocs : ordre inversé par rangée, gaps recalculés
    - Types ortho : D ↔ G
    - Orientations ajustées
    - Sticks : E ↔ O
    - Géométrie pièce : offsets miroir, hinge_side inversé

    Args:
        pattern: Pattern JSON original.

    Returns:
        Nouveau dict pattern miroir, suffixé '_MIR'.
    """
    room_w = pattern.get("room_width_cm", 0)
    mirrored = copy.deepcopy(pattern)
    mirrored["name"] = pattern["name"] + "_MIR"

    # Miroir des rangées
    mirrored["rows"] = [
        _mirror_row(row, room_w) for row in pattern.get("rows", [])
    ]

    # Miroir de la géométrie pièce
    if "room_windows" in pattern:
        mirrored["room_windows"] = _mirror_windows(
            pattern["room_windows"], room_w,
        )
    if "room_openings" in pattern:
        mirrored["room_openings"] = _mirror_openings(
            pattern["room_openings"], room_w,
        )
    if "room_exclusions" in pattern:
        mirrored["room_exclusions"] = _mirror_exclusions(
            pattern["room_exclusions"], room_w,
        )

    return mirrored


# ---------------------------------------------------------------------------
# Étape 3 — Calage sticks + homothétie
# ---------------------------------------------------------------------------

_STICK_O = frozenset({"O", "W"})


def _block_ns_extent(block: dict) -> int:
    """Hauteur NS d'un bloc à son orientation courante."""
    btype = block.get("type", "")
    orient = block.get("orientation", 0)
    eo, ns, _ = _BLOCK_REGISTRY.get(btype, (0, 0, 0))
    if orient in (90, 270):
        return eo
    return ns


def _adapt_row_eo(
    row: dict, orig_width: int, target_width: int,
) -> dict:
    """Adapte une rangée à une largeur de pièce cible.

    Algorithme :
    - Blocs stick O : position fixe (distance au mur ouest préservée)
    - Blocs stick E : position décalée de dw (distance au mur est préservée)
    - Blocs sans stick EO : interpolation linéaire entre les ancres voisines
    - Sans ancre : positions inchangées (espace supplémentaire à droite)

    Args:
        row: Rangée JSON originale.
        orig_width: Largeur de la pièce du pattern.
        target_width: Largeur de la pièce cible.

    Returns:
        Nouvelle rangée avec gaps adaptés.
    """
    dw = target_width - orig_width
    blocks = row.get("blocks", [])
    if not blocks or dw == 0:
        return copy.deepcopy(row)

    # Positions absolues originales
    positions = []  # (x_start, width)
    x = 0
    for b in blocks:
        x += b.get("gap_cm", 0)
        w = _block_eo_extent(b)
        positions.append((x, w))
        x += w

    # Ancres : (index, new_x)
    anchors = []
    for i, b in enumerate(blocks):
        sticks = set(b.get("sticks", []))
        if sticks & _STICK_O:
            anchors.append((i, positions[i][0]))
        elif "E" in sticks:
            anchors.append((i, positions[i][0] + dw))

    # Nouvelles positions
    new_x = [positions[i][0] for i in range(len(blocks))]

    if not anchors:
        pass  # Pas d'ancre → positions inchangées, espace à droite
    elif len(anchors) == 1:
        idx, ax = anchors[0]
        shift = ax - positions[idx][0]
        for i in range(len(blocks)):
            new_x[i] = positions[i][0] + shift
    else:
        anchors.sort()
        for idx, ax in anchors:
            new_x[idx] = ax

        # Avant la première ancre : même décalage
        first_idx, first_ax = anchors[0]
        shift_left = first_ax - positions[first_idx][0]
        for i in range(first_idx):
            new_x[i] = positions[i][0] + shift_left

        # Après la dernière ancre : même décalage
        last_idx, last_ax = anchors[-1]
        shift_right = last_ax - positions[last_idx][0]
        for i in range(last_idx + 1, len(blocks)):
            new_x[i] = positions[i][0] + shift_right

        # Entre ancres consécutives : interpolation linéaire
        for a in range(len(anchors) - 1):
            li, lx = anchors[a]
            ri, rx = anchors[a + 1]
            orig_span = positions[ri][0] - positions[li][0]
            new_span = rx - lx
            for i in range(li + 1, ri):
                if orig_span > 0:
                    frac = (positions[i][0] - positions[li][0]) / orig_span
                    new_x[i] = lx + frac * new_span
                else:
                    new_x[i] = lx

    # Recalcul des gaps
    new_blocks = []
    prev_right = 0
    for i in range(len(blocks)):
        gap = max(0, int(round(new_x[i] - prev_right)))
        nb = copy.deepcopy(blocks[i])
        nb["gap_cm"] = gap
        new_blocks.append(nb)
        prev_right = int(round(new_x[i])) + positions[i][1]

    return {"blocks": new_blocks}


def _adapt_ns(
    pattern: dict, orig_depth: int, target_depth: int,
) -> dict:
    """Adapte la dimension NS d'un pattern à la pièce cible.

    Distribution de l'espace supplémentaire dd :
    - Rangées avec au moins un bloc stick N : position NS préservée
    - Rangées avec au moins un bloc stick S : décalées de dd
    - Rangées sans stick NS : interpolation ou distribution proportionnelle
    - Si une seule rangée : offset_ns_cm des blocs stick N/S ajusté, sinon
      espace supplémentaire distribué dans row_gaps_cm

    Args:
        pattern: Pattern JSON adapté (largeur déjà ajustée).
        orig_depth: Profondeur de la pièce du pattern.
        target_depth: Profondeur de la pièce cible.

    Returns:
        Pattern avec row_gaps_cm et offset_ns_cm ajustés.
    """
    dd = target_depth - orig_depth
    p = copy.deepcopy(pattern)
    rows = p.get("rows", [])
    row_gaps = list(p.get("row_gaps_cm", []))

    if dd == 0 or not rows:
        return p

    if len(rows) == 1:
        # Une seule rangée : l'espace supplémentaire va au-dessus/en-dessous
        # Les blocs avec stick S voient leur offset_ns augmenter de dd
        for b in rows[0].get("blocks", []):
            sticks = set(b.get("sticks", []))
            if "S" in sticks:
                b["offset_ns_cm"] = b.get("offset_ns_cm", 0) + dd
        p["rows"] = rows
        return p

    # Plusieurs rangées : distribuer dd dans les row_gaps
    # Identifier si première rangée a stick N ou dernière a stick S
    def _row_has_stick(row, stick_dir):
        for b in row.get("blocks", []):
            if stick_dir in set(b.get("sticks", [])):
                return True
        return False

    first_has_n = _row_has_stick(rows[0], "N")
    last_has_s = _row_has_stick(rows[-1], "S")

    if not row_gaps:
        # Pas de gaps entre rangées → dd va en dessous
        p["row_gaps_cm"] = row_gaps
        return p

    # Distribuer dd proportionnellement dans les row_gaps
    total_gaps = sum(row_gaps)
    if total_gaps > 0:
        for i in range(len(row_gaps)):
            row_gaps[i] += int(round(dd * row_gaps[i] / total_gaps))
    else:
        # Gaps tous à 0 : distribution égale
        per_gap = dd // len(row_gaps)
        for i in range(len(row_gaps)):
            row_gaps[i] += per_gap

    p["row_gaps_cm"] = row_gaps
    return p


def adapt_to_room(
    pattern: dict, target_room: RoomSpec,
) -> dict:
    """Adapte un pattern catalogue à une pièce cible.

    Calage : les blocs stick restent collés à leur mur.
    Homothétie : les blocs non-stick sont redistribués proportionnellement.

    Args:
        pattern: Pattern JSON du catalogue.
        target_room: Pièce cible (dimensions ≥ pattern).

    Returns:
        Nouveau pattern avec gaps ajustés et dimensions cibles.
    """
    orig_w = pattern.get("room_width_cm", 0)
    orig_d = pattern.get("room_depth_cm", 0)
    target_w = target_room.width_cm
    target_d = target_room.depth_cm

    # Adaptation EO (par rangée)
    adapted = copy.deepcopy(pattern)
    adapted["rows"] = [
        _adapt_row_eo(row, orig_w, target_w)
        for row in pattern.get("rows", [])
    ]
    adapted["room_width_cm"] = target_w
    adapted["room_depth_cm"] = target_d

    # Adaptation NS
    adapted = _adapt_ns(adapted, orig_d, target_d)

    # Géométrie pièce : remplacer par celle de la pièce cible
    adapted["room_windows"] = [
        {"face": w.face.value, "offset_cm": w.offset_cm, "width_cm": w.width_cm}
        for w in target_room.windows
    ]
    adapted["room_openings"] = [
        {"face": o.face.value, "offset_cm": o.offset_cm, "width_cm": o.width_cm,
         "has_door": o.has_door, "opens_inward": o.opens_inward,
         "hinge_side": o.hinge_side.value}
        for o in target_room.openings
    ]
    adapted["room_exclusions"] = [
        {"x_cm": z.x_cm, "y_cm": z.y_cm,
         "width_cm": z.width_cm, "depth_cm": z.depth_cm}
        for z in target_room.exclusion_zones
    ]

    return adapted


# ---------------------------------------------------------------------------
# Étape 4 — Suppression unitaire de postes en zone interdite
# ---------------------------------------------------------------------------

@dataclass
class DeskPosition:
    """Position absolue d'un poste dans le pattern.

    Attributes:
        row_idx: Index de la rangée.
        block_idx: Index du bloc dans la rangée.
        desk_idx: Index du poste dans le bloc.
        x_cm: Coin NW du poste, axe est.
        y_cm: Coin NW du poste, axe sud.
        width_cm: Dimension EO du poste.
        depth_cm: Dimension NS du poste.
        block_type: Type du bloc parent.
    """
    row_idx: int
    block_idx: int
    desk_idx: int
    x_cm: int
    y_cm: int
    width_cm: int
    depth_cm: int
    block_type: str


# Positions relatives des desks dans chaque type de bloc à orientation 0°
# Format: list[(dx, dy, desk_w, desk_d)] relatif au coin NW du bloc
_DESK_LAYOUTS: dict[str, list[tuple[int, int, int, int]]] = {
    "BLOC_1": [
        (0, 0, DESK_W_CM, DESK_D_CM),
    ],
    "BLOC_2_FACE": [
        (0, 0, DESK_W_CM, DESK_D_CM),
        (DESK_W_CM, 0, DESK_W_CM, DESK_D_CM),
    ],
    "BLOC_2_COTE": [
        (0, 0, DESK_W_CM, DESK_D_CM),
        (0, DESK_D_CM, DESK_W_CM, DESK_D_CM),
    ],
    "BLOC_3_COTE": [
        (0, 0, DESK_W_CM, DESK_D_CM),
        (0, DESK_D_CM, DESK_W_CM, DESK_D_CM),
        (0, 2 * DESK_D_CM, DESK_W_CM, DESK_D_CM),
    ],
    "BLOC_4_FACE": [
        (0, 0, DESK_W_CM, DESK_D_CM),
        (DESK_W_CM, 0, DESK_W_CM, DESK_D_CM),
        (0, DESK_D_CM, DESK_W_CM, DESK_D_CM),
        (DESK_W_CM, DESK_D_CM, DESK_W_CM, DESK_D_CM),
    ],
    "BLOC_6_FACE": [
        (0, 0, DESK_W_CM, DESK_D_CM),
        (DESK_W_CM, 0, DESK_W_CM, DESK_D_CM),
        (0, DESK_D_CM, DESK_W_CM, DESK_D_CM),
        (DESK_W_CM, DESK_D_CM, DESK_W_CM, DESK_D_CM),
        (0, 2 * DESK_D_CM, DESK_W_CM, DESK_D_CM),
        (DESK_W_CM, 2 * DESK_D_CM, DESK_W_CM, DESK_D_CM),
    ],
    "BLOC_2_ORTHO_D": [
        # desk1 (regard S) : barre horizontale en haut
        (0, 0, DESK_D_CM, DESK_W_CM),
        # desk2 (regard W) : barre verticale en bas à gauche
        (0, DESK_W_CM, DESK_W_CM, DESK_D_CM),
    ],
    "BLOC_2_ORTHO_G": [
        # desk1 (regard S) : barre horizontale en haut
        (0, 0, DESK_D_CM, DESK_W_CM),
        # desk2 (regard E) : barre verticale en bas à droite
        (DESK_D_CM - DESK_W_CM, DESK_W_CM, DESK_W_CM, DESK_D_CM),
    ],
}


def _rotate_desk_layout(
    dx: int, dy: int, dw: int, dd: int,
    block_eo: int, block_ns: int, degrees: int,
) -> tuple[int, int, int, int]:
    """Rotation horaire d'un poste dans un bloc.

    Args:
        dx, dy: Position relative dans le bloc (orientation 0°).
        dw, dd: Dimensions du poste.
        block_eo, block_ns: Dimensions du bloc à orientation 0°.
        degrees: 90, 180, ou 270.

    Returns:
        (new_dx, new_dy, new_dw, new_dd) dans le bloc pivoté.
    """
    for _ in range((degrees // 90) % 4):
        # Rotation 90° horaire : (x, y) → (block_ns - y - dd, x)
        new_dx = block_ns - dy - dd
        new_dy = dx
        new_dw = dd
        new_dd = dw
        dx, dy, dw, dd = new_dx, new_dy, new_dw, new_dd
        block_eo, block_ns = block_ns, block_eo
    return dx, dy, dw, dd


def compute_desk_positions(pattern: dict) -> list[DeskPosition]:
    """Calcule les positions absolues de tous les postes d'un pattern.

    Args:
        pattern: Pattern JSON (adapté ou non).

    Returns:
        Liste de DeskPosition avec coordonnées absolues.
    """
    desks = []
    row_y = 0
    rows = pattern.get("rows", [])
    row_gaps = pattern.get("row_gaps_cm", [])

    for ri, row in enumerate(rows):
        if ri > 0 and ri - 1 < len(row_gaps):
            row_y += row_gaps[ri - 1]

        block_x = 0
        for bi, block in enumerate(row.get("blocks", [])):
            block_x += block.get("gap_cm", 0)
            btype = block.get("type", "")
            orient = block.get("orientation", 0)
            offset_ns = block.get("offset_ns_cm", 0)

            eo, ns, _ = _BLOCK_REGISTRY.get(btype, (0, 0, 0))
            desk_layout = _DESK_LAYOUTS.get(btype, [])

            for di, (dx, dy, dw, dd) in enumerate(desk_layout):
                if orient != 0:
                    dx, dy, dw, dd = _rotate_desk_layout(
                        dx, dy, dw, dd, eo, ns, orient,
                    )
                desks.append(DeskPosition(
                    row_idx=ri,
                    block_idx=bi,
                    desk_idx=di,
                    x_cm=block_x + dx,
                    y_cm=row_y + offset_ns + dy,
                    width_cm=dw,
                    depth_cm=dd,
                    block_type=btype,
                ))

            block_eo = ns if orient in (90, 270) else eo
            block_x += block_eo

        # Hauteur de la rangée = max NS des blocs
        max_ns = 0
        for block in row.get("blocks", []):
            max_ns = max(max_ns, _block_ns_extent(block))
        row_y += max_ns

    return desks


def _rects_intersect(
    x1: int, y1: int, w1: int, d1: int,
    x2: int, y2: int, w2: int, d2: int,
) -> bool:
    """Teste si deux rectangles se chevauchent (intersection non vide)."""
    return (x1 < x2 + w2 and x1 + w1 > x2
            and y1 < y2 + d2 and y1 + d1 > y2)


def remove_conflicting_desks(
    pattern: dict, room: RoomSpec,
) -> tuple[dict, list[DeskPosition]]:
    """Supprime les postes qui intersectent les zones interdites.

    Suppression unitaire : le poste est retiré, pas le bloc entier.
    Le pattern retourné a les blocs modifiés (postes supprimés marqués).

    Args:
        pattern: Pattern JSON (adapté à la pièce cible).
        room: Pièce cible avec exclusion_zones.

    Returns:
        (pattern_modifié, liste_des_postes_supprimés)
    """
    desks = compute_desk_positions(pattern)
    removed = []

    for desk in desks:
        for excl in room.exclusion_zones:
            if _rects_intersect(
                desk.x_cm, desk.y_cm, desk.width_cm, desk.depth_cm,
                excl.x_cm, excl.y_cm, excl.width_cm, excl.depth_cm,
            ):
                removed.append(desk)
                break

    # Aussi supprimer les postes qui dépassent de la pièce
    for desk in desks:
        if desk in removed:
            continue
        if (desk.x_cm < 0 or desk.y_cm < 0
                or desk.x_cm + desk.width_cm > room.width_cm
                or desk.y_cm + desk.depth_cm > room.depth_cm):
            removed.append(desk)

    # Construire le set des postes à garder
    removed_set = {(d.row_idx, d.block_idx, d.desk_idx) for d in removed}
    remaining_desks = [d for d in desks if
                       (d.row_idx, d.block_idx, d.desk_idx) not in removed_set]

    # Mettre à jour le compteur
    result = copy.deepcopy(pattern)
    n_remaining = len(remaining_desks)

    logger.info(
        "Suppression postes : %d supprimés, %d restants",
        len(removed), n_remaining,
    )

    # Stocker les infos de suppression dans le pattern
    result["_removed_desks"] = [
        {"row": d.row_idx, "block": d.block_idx, "desk": d.desk_idx,
         "x_cm": d.x_cm, "y_cm": d.y_cm}
        for d in removed
    ]
    result["_n_desks_after_removal"] = n_remaining

    return result, removed


def generate_mirrors(
    candidates: list[PatternCandidate],
) -> list[PatternCandidate]:
    """Génère les miroirs E-O de tous les candidats.

    Retourne la liste originale + les miroirs.

    Args:
        candidates: Candidats issus de la sélection.

    Returns:
        Liste étendue (originaux + miroirs).
    """
    result = list(candidates)
    for c in candidates:
        mirrored_pattern = mirror_pattern(c.pattern)
        result.append(PatternCandidate(
            pattern=mirrored_pattern,
            name=mirrored_pattern["name"],
            room_width_cm=c.room_width_cm,
            room_depth_cm=c.room_depth_cm,
            standard=c.standard,
            n_desks=c.n_desks,
        ))
    return result


# ---------------------------------------------------------------------------
# Étape 5 — Scoring (circulation + confort)
# ---------------------------------------------------------------------------

@dataclass
class MatchScore:
    """Scores d'un candidat après adaptation à la pièce cible.

    Attributes:
        pattern_name: Nom du pattern source.
        standard: Standard d'aménagement.
        n_desks: Nombre de postes après suppression.
        m2_per_desk: Surface par poste (m²).
        circulation_grade: Grade de circulation (A-F).
        connectivity_pct: Pourcentage de connexité.
        min_passage_cm: Passage minimum trouvé (cm).
        worst_detour: Pire ratio de détour.
        largest_free_rect_m2: Plus grand rectangle vide (m²).
        adapted_pattern: Pattern JSON adapté.
    """
    pattern_name: str
    standard: str
    n_desks: int
    m2_per_desk: float
    circulation_grade: str
    connectivity_pct: float
    min_passage_cm: float
    worst_detour: float
    largest_free_rect_m2: float
    adapted_pattern: dict


def _pattern_to_circulation_format(
    pattern: dict, room: RoomSpec,
) -> tuple[dict, list[dict]]:
    """Convertit un pattern catalogue + RoomSpec vers le format circulation.

    Args:
        pattern: Pattern JSON adapté (avec _removed_desks éventuel).
        room: Pièce cible.

    Returns:
        (room_dict, blocks_list) au format attendu par circulation_analysis.analyse().
    """
    # Room dict au format ancien
    doors = []
    for o in room.openings:
        doors.append({
            "wall": o.face.value,
            "position_cm": o.offset_cm,
            "width_cm": o.width_cm,
        })
    room_dict = {
        "eo_cm": room.width_cm,
        "ns_cm": room.depth_cm,
        "doors": doors,
    }

    # Blocs positionnés au format circulation
    blocks_out = []
    row_y = 0
    rows = pattern.get("rows", [])
    row_gaps = pattern.get("row_gaps_cm", [])

    for ri, row in enumerate(rows):
        if ri > 0 and ri - 1 < len(row_gaps):
            row_y += row_gaps[ri - 1]

        block_x = 0
        for bi, block in enumerate(row.get("blocks", [])):
            block_x += block.get("gap_cm", 0)
            btype = block.get("type", "")
            orient = block.get("orientation", 0)
            offset_ns = block.get("offset_ns_cm", 0)

            eo, ns, _ = _BLOCK_REGISTRY.get(btype, (0, 0, 0))
            if orient in (90, 270):
                block_eo, block_ns = ns, eo
            else:
                block_eo, block_ns = eo, ns

            blocks_out.append({
                "type": btype,
                "orientation": orient,
                "x_cm": block_x,
                "y_cm": row_y + offset_ns,
                "eo_cm": block_eo,
                "ns_cm": block_ns,
            })

            block_x += block_eo

        max_ns = 0
        for block in row.get("blocks", []):
            max_ns = max(max_ns, _block_ns_extent(block))
        row_y += max_ns

    return room_dict, blocks_out


def score_candidate(
    pattern: dict, room: RoomSpec, standard: str,
) -> MatchScore:
    """Calcule le score complet d'un candidat adapté.

    Args:
        pattern: Pattern JSON adapté et nettoyé (postes supprimés).
        room: Pièce cible.
        standard: Standard d'aménagement.

    Returns:
        MatchScore avec tous les indicateurs.
    """
    from olm.core.circulation_analysis import analyse as circ_analyse

    n_desks = pattern.get("_n_desks_after_removal", count_desks(pattern))
    area_m2 = room.width_cm * room.depth_cm / 10_000
    m2_per_desk = round(area_m2 / n_desks, 2) if n_desks > 0 else 0.0

    # Circulation
    cfg = ALL_CONFIGS.get(standard, ALL_CONFIGS["AFNOR_ADVICE"])
    room_dict, blocks_list = _pattern_to_circulation_format(pattern, room)
    circ = circ_analyse(room_dict, blocks_list, cfg.door_exclusion_depth_cm)

    # Passage minimum (via desk paths)
    min_passage = min(circ.path_widths) if circ.path_widths else 0.0

    # Rectangle vide résiduel
    free_rect_m2 = largest_free_rectangle_m2(pattern, room)

    return MatchScore(
        pattern_name=pattern.get("name", "?"),
        standard=standard,
        n_desks=n_desks,
        m2_per_desk=m2_per_desk,
        circulation_grade=circ.grade,
        connectivity_pct=circ.connectivity_pct,
        min_passage_cm=min_passage,
        worst_detour=circ.worst_detour_ratio,
        largest_free_rect_m2=free_rect_m2,
        adapted_pattern=pattern,
    )


# ---------------------------------------------------------------------------
# Étape 6 — Sélection du meilleur par standard
# ---------------------------------------------------------------------------

def _score_key(s: MatchScore) -> float:
    """Score composite pour sélection du meilleur candidat.

    Combine densité et confort avec les poids de config.json.
    Score plus bas = meilleur candidat (utilisé avec min()).

    Densité (0-1) : normalisée par n_desks (plus = mieux).
    Confort (0-1) : dérivé du grade de circulation (A=1, F=0).
    """
    from olm.core.app_config import get_matching

    matching = get_matching()
    w_density = matching.get("w_density", 0.5)
    w_comfort = matching.get("w_comfort", 0.5)

    # Normaliser densité : n_desks en [0, 1], inversé pour que min() fonctionne
    # On utilise 1/n_desks comme proxy (plus de postes = meilleur)
    density_score = 1.0 / max(s.n_desks, 1)

    # Normaliser confort : grade A=0, B=0.25, C=0.5, D=0.75, F=1.0
    grade_to_score = {"A": 0.0, "B": 0.25, "C": 0.5, "D": 0.75, "F": 1.0}
    comfort_score = grade_to_score.get(s.circulation_grade, 1.0)

    # Score composite (plus bas = meilleur)
    return w_density * density_score + w_comfort * comfort_score


def select_best(scores: list[MatchScore]) -> MatchScore | None:
    """Sélectionne le meilleur candidat parmi les scores.

    Args:
        scores: Liste de MatchScore pour un standard donné.

    Returns:
        Meilleur MatchScore, ou None si liste vide.
    """
    if not scores:
        return None
    return min(scores, key=_score_key)


# ---------------------------------------------------------------------------
# Étape 7 — Plus grand rectangle vide résiduel
# ---------------------------------------------------------------------------

def largest_free_rectangle_m2(
    pattern: dict, room: RoomSpec,
) -> float:
    """Calcule la surface du plus grand rectangle vide après aménagement.

    Utilise l'algorithme histogramme maximal (O(rows×cols)).

    Args:
        pattern: Pattern adapté avec positions de desks.
        room: Pièce cible.

    Returns:
        Surface en m² du plus grand rectangle vide.
    """
    import numpy as np
    from olm.core.matching_config import GRID_CELL_CM

    cols = room.width_cm // GRID_CELL_CM
    rows = room.depth_cm // GRID_CELL_CM
    if cols <= 0 or rows <= 0:
        return 0.0

    # Grille d'occupation : True = occupé
    occupied = np.zeros((rows, cols), dtype=bool)

    # Murs périphériques
    occupied[0, :] = True
    occupied[-1, :] = True
    occupied[:, 0] = True
    occupied[:, -1] = True

    # Desks restants (exclure les supprimés)
    desks = compute_desk_positions(pattern)
    removed_set = set()
    for rd in pattern.get("_removed_desks", []):
        removed_set.add((rd["row"], rd["block"], rd["desk"]))

    for d in desks:
        if (d.row_idx, d.block_idx, d.desk_idx) in removed_set:
            continue
        r1 = d.y_cm // GRID_CELL_CM
        r2 = (d.y_cm + d.depth_cm) // GRID_CELL_CM
        c1 = d.x_cm // GRID_CELL_CM
        c2 = (d.x_cm + d.width_cm) // GRID_CELL_CM
        r1 = max(0, min(r1, rows))
        r2 = max(0, min(r2, rows))
        c1 = max(0, min(c1, cols))
        c2 = max(0, min(c2, cols))
        occupied[r1:r2, c1:c2] = True

    # Zones d'exclusion
    for excl in room.exclusion_zones:
        r1 = excl.y_cm // GRID_CELL_CM
        r2 = (excl.y_cm + excl.depth_cm) // GRID_CELL_CM
        c1 = excl.x_cm // GRID_CELL_CM
        c2 = (excl.x_cm + excl.width_cm) // GRID_CELL_CM
        r1 = max(0, min(r1, rows))
        r2 = max(0, min(r2, rows))
        c1 = max(0, min(c1, cols))
        c2 = max(0, min(c2, cols))
        occupied[r1:r2, c1:c2] = True

    # Algorithme du plus grand rectangle dans un histogramme
    free = ~occupied
    heights = np.zeros(cols, dtype=int)
    max_area = 0

    for r in range(rows):
        for c in range(cols):
            heights[c] = heights[c] + 1 if free[r, c] else 0

        # Largest rectangle in histogram (stack-based)
        stack: list[int] = []
        for c in range(cols + 1):
            h = heights[c] if c < cols else 0
            while stack and heights[stack[-1]] > h:
                height = heights[stack.pop()]
                width = c if not stack else c - stack[-1] - 1
                max_area = max(max_area, height * width)
            stack.append(c)

    cell_area_m2 = (GRID_CELL_CM / 100) ** 2
    return round(max_area * cell_area_m2, 2)


# ---------------------------------------------------------------------------
# Pipeline complet
# ---------------------------------------------------------------------------

@dataclass
class MatchingResult:
    """Résultat complet du matching pour une pièce.

    Attributes:
        room: Pièce cible.
        by_standard: Meilleur score par standard.
        all_scores: Tous les scores calculés.
    """
    room: RoomSpec
    by_standard: dict[str, MatchScore | None]
    all_scores: list[MatchScore]


def match_room(
    catalogue: list[dict], room: RoomSpec,
) -> MatchingResult:
    """Pipeline complet de matching pour une pièce cible.

    Exécute les 7 étapes du pipeline pour les 3 standards.

    Args:
        catalogue: Patterns JSON du catalogue.
        room: Pièce cible.

    Returns:
        MatchingResult avec le meilleur par standard et tous les scores.
    """
    all_scores: list[MatchScore] = []
    by_standard: dict[str, MatchScore | None] = {}

    # Étape 1 : sélection par standard
    selection_results = select_candidates(catalogue, room)

    for sel in selection_results:
        std = sel.standard
        if not sel.candidates:
            by_standard[std] = None
            continue

        # Étape 2 : miroirs
        with_mirrors = generate_mirrors(sel.candidates)

        std_scores: list[MatchScore] = []
        for candidate in with_mirrors:
            # Étape 3 : adaptation
            adapted = adapt_to_room(candidate.pattern, room)

            # Étape 4 : suppression postes en zone interdite
            cleaned, removed = remove_conflicting_desks(adapted, room)

            # Étape 5 : scoring
            score = score_candidate(cleaned, room, std)
            std_scores.append(score)
            all_scores.append(score)

        # Étape 6 : sélection du meilleur
        by_standard[std] = select_best(std_scores)

    return MatchingResult(
        room=room,
        by_standard=by_standard,
        all_scores=all_scores,
    )


# ---------------------------------------------------------------------------
# Nommage automatique des patterns (D-50)
# ---------------------------------------------------------------------------

def _count_openings(pattern: dict) -> int:
    """Compte le nombre d'ouvertures (portes + baies) dans un pattern."""
    return len(pattern.get("room_openings", []))


def _pattern_group_key(pattern: dict) -> tuple[int, int, str, int]:
    """Clé de groupe pour le nommage : (width, depth, std_short, n_openings).

    Deux patterns sont dans le même groupe s'ils ont la même clé.
    Le suffixe _{k}O n'apparaît que si n_openings >= 2.
    """
    w = pattern.get("room_width_cm", 0)
    d = pattern.get("room_depth_cm", 0)
    std_key = pattern.get("standard", "")
    std = get_standard_label(std_key) if std_key else "UNKNOWN"
    n_open = _count_openings(pattern)
    return (w, d, std, n_open)


def generate_auto_name(
    pattern: dict, catalogue: list[dict],
) -> str:
    """Génère le nom automatique d'un pattern selon D-50.

    Format : {W}x{D}_{STANDARD}[_{k}O]_{n}
    - {k}O présent seulement si ≥ 2 ouvertures
    - {n} = prochain incrément disponible dans le groupe

    Args:
        pattern: Pattern à nommer.
        catalogue: Catalogue courant (pour calculer l'incrément).

    Returns:
        Nom généré.
    """
    key = _pattern_group_key(pattern)
    w, d, std_short, n_open = key

    # Compter les patterns existants dans le même groupe
    existing_n = []
    for p in catalogue:
        if _pattern_group_key(p) == key:
            # Extraire le n du nom existant
            n = _extract_increment(p.get("name", ""))
            if n is not None:
                existing_n.append(n)

    next_n = max(existing_n, default=0) + 1

    # Construire le nom
    base = f"{w}x{d}_{std_short}"
    if n_open >= 2:
        base += f"_{n_open}O"
    return f"{base}_{next_n}"


def _extract_increment(name: str) -> int | None:
    """Extrait l'incrément final d'un nom de pattern.

    Ex: '310x480_AFNOR_2O_3' → 3, '310x480_SITE_1' → 1,
        '310x480_SITE' → None (ancien format sans incrément)
    """
    parts = name.rsplit("_", 1)
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None


def compact_catalogue_names(catalogue: list[dict]) -> list[dict]:
    """Compacte les incréments de tous les patterns par groupe.

    Pour chaque groupe (même W×D + standard + nb ouvertures),
    renumérotation 1, 2, 3… sans trous, triée par nom original.

    Args:
        catalogue: Liste des patterns.

    Returns:
        Catalogue avec noms compactés (modifié en place ET retourné).
    """
    import re
    from collections import defaultdict

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for p in catalogue:
        key = _pattern_group_key(p)
        groups[key].append(p)

    for key, patterns in groups.items():
        w, d, std_short, n_open = key

        # Trier par incrément existant (ou par nom pour stabilité)
        def sort_key(p):
            n = _extract_increment(p.get("name", ""))
            return n if n is not None else 0
        patterns.sort(key=sort_key)

        # Renuméroter
        base = f"{w}x{d}_{std_short}"
        if n_open >= 2:
            base += f"_{n_open}O"

        for i, p in enumerate(patterns, start=1):
            p["name"] = f"{base}_{i}"

    return catalogue


def migrate_catalogue_names(catalogue: list[dict]) -> list[dict]:
    """Migre les noms existants vers la convention D-50.

    Les anciens noms (ex: '310x480_AFNOR') deviennent '310x480_AFNOR_1'.
    Les groupes sont compactés après migration.

    Args:
        catalogue: Catalogue avec anciens noms.

    Returns:
        Catalogue avec noms migrés.
    """
    # D'abord, s'assurer que chaque pattern a un nom parseable
    # Les anciens noms comme '310x480_AFNOR' n'ont pas d'incrément
    # compact_catalogue_names les renumérotera
    return compact_catalogue_names(catalogue)
