"""Analyse de circulation à partir d'un candidat du matching statique — solver_lab.

Construit une grille discrète depuis un candidat (room + blocks positionnés)
et analyse la qualité de la circulation en réutilisant les algorithmes de
solver/circulation.py (fonctions copiées pour autonomie).

Repère D-26 : origine NW, x EST, y SUD. Dimensions en centimètres.
"""
from __future__ import annotations

import heapq
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Deque, List, Optional, Set, Tuple

import numpy as np

from olm.core.matching_config import GRID_CELL_CM
from olm.core.types import CellType
from olm.core.spacing_config import AFNOR_ADVICE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclass résultat
# ---------------------------------------------------------------------------

@dataclass
class CirculationResult:
    """Résultat de l'analyse de circulation pour un candidat du matching.

    Attributes:
        grade: Grade de qualité (A à F).
        connectivity_pct: Pourcentage de rectangles de circulation atteignables.
        isolated_area_pct: Pourcentage de surface inaccessible.
        avg_detour_ratio: Ratio moyen distance graphe / distance euclidienne.
        worst_detour_ratio: Pire ratio de détour.
        violations: Messages de violation AFNOR.
        paths: Chemin cellulaire [(row, col)] par bloc (vide pour l'instant).
        path_widths: Largeur minimale en cm par chemin (vide pour l'instant).
        analysis_time_ms: Durée de l'analyse en millisecondes.
    """
    grade: str
    connectivity_pct: float
    isolated_area_pct: float
    avg_detour_ratio: float
    worst_detour_ratio: float
    violations: list[str] = field(default_factory=list)
    paths: list[list[tuple[int, int]]] = field(default_factory=list)
    path_widths: list[float] = field(default_factory=list)
    desk_ids: list[str] = field(default_factory=list)
    widths_per_cell: list[list[int]] = field(default_factory=list)
    analysis_time_ms: float = 0.0


# ---------------------------------------------------------------------------
# Construction de la grille
# ---------------------------------------------------------------------------

def build_grid(
    room: dict,
    blocks: list[dict],
    door_depth_cm: int = AFNOR_ADVICE.door_exclusion_depth_cm,
) -> np.ndarray:
    """Construit une grille numpy (ROWS × COLS) de CellType.

    Args:
        room: Dict avec eo_cm, ns_cm, doors (liste wall/position_cm/width_cm).
        blocks: Liste de dicts type/orientation/x_cm/y_cm/eo_cm/ns_cm.
        door_depth_cm: Profondeur de la zone d'exclusion porte en cm.

    Returns:
        Grille numpy int de shape (ROWS, COLS) initialisée avec les valeurs CellType.
    """
    # Imports locaux pour éviter la circularité au niveau module
    from olm.core.pattern_generator import (
        rotate_face_candidates,
        BLOC_1, BLOC_2_FACE, BLOC_2_COTE, BLOC_3_COTE, BLOC_4_FACE,
        BLOC_6_FACE, BLOC_2_ORTHO_D, BLOC_2_ORTHO_G,
    )
    _BLOCKS = {b.name: b for b in [
        BLOC_1, BLOC_2_FACE, BLOC_2_COTE, BLOC_3_COTE, BLOC_4_FACE,
        BLOC_6_FACE, BLOC_2_ORTHO_D, BLOC_2_ORTHO_G,
    ]}

    room_eo = room["eo_cm"]
    room_ns = room["ns_cm"]
    COLS = room_eo // GRID_CELL_CM
    ROWS = room_ns // GRID_CELL_CM

    grid = np.full((ROWS, COLS), int(CellType.CORRIDOR), dtype=np.int32)

    # Étape 3 — Murs périphériques
    grid[0, :] = int(CellType.WALL)
    grid[ROWS - 1, :] = int(CellType.WALL)
    grid[:, 0] = int(CellType.WALL)
    grid[:, COLS - 1] = int(CellType.WALL)

    # Étape 4 — Portes (écrasent les murs)
    for door in room.get("doors", []):
        wall = door["wall"]
        pos = door.get("position_cm", 0)
        width = door.get("width_cm", 90)
        c1 = pos // GRID_CELL_CM
        c2 = (pos + width) // GRID_CELL_CM

        if wall == "south":
            grid[ROWS - 1, c1:c2] = int(CellType.DOOR)
        elif wall == "north":
            grid[0, c1:c2] = int(CellType.DOOR)
        elif wall == "west":
            grid[c1:c2, 0] = int(CellType.DOOR)
        elif wall == "east":
            grid[c1:c2, COLS - 1] = int(CellType.DOOR)

    # Étape 5 — Zone d'exclusion porte : reste CORRIDOR (praticable à pied).
    # L'interdiction de placement de mobilier est gérée par le matcher
    # (static_matcher.compute_door_exclusion_zones), pas par la grille de
    # circulation. Marquer cette zone en WALL coupait la porte de l'intérieur.

    # Étape 6 — Empreintes des blocs (physique + zones fixes non superposables)
    for b in blocks:
        block_type = b["type"]
        orientation = b.get("orientation", 0)
        x_cm = b["x_cm"]
        y_cm = b["y_cm"]
        eo_cm = b["eo_cm"]
        ns_cm = b["ns_cm"]

        # Emprise physique
        col1 = x_cm // GRID_CELL_CM
        col2 = (x_cm + eo_cm) // GRID_CELL_CM
        row1 = y_cm // GRID_CELL_CM
        row2 = (y_cm + ns_cm) // GRID_CELL_CM
        grid[row1:row2, col1:col2] = int(CellType.FOOTPRINT)

        # Zones fixes (fauteuil, non_superposable_cm)
        if block_type not in _BLOCKS:
            continue
        block_def = _BLOCKS[block_type]
        faces = block_def.faces
        if orientation != 0:
            faces = rotate_face_candidates(faces, orientation)

        # North : bande au-dessus du bloc
        if faces.north.non_superposable_cm > 0:
            t = faces.north.non_superposable_cm // GRID_CELL_CM
            r1 = max(0, row1 - t)
            grid[r1:row1, col1:col2] = int(CellType.FOOTPRINT)

        # South : bande en-dessous du bloc
        if faces.south.non_superposable_cm > 0:
            t = faces.south.non_superposable_cm // GRID_CELL_CM
            r2 = min(ROWS, row2 + t)
            grid[row2:r2, col1:col2] = int(CellType.FOOTPRINT)

        # East : bande à droite du bloc
        if faces.east.non_superposable_cm > 0:
            t = faces.east.non_superposable_cm // GRID_CELL_CM
            c2 = min(COLS, col2 + t)
            grid[row1:row2, col2:c2] = int(CellType.FOOTPRINT)

        # West : bande à gauche du bloc
        if faces.west.non_superposable_cm > 0:
            t = faces.west.non_superposable_cm // GRID_CELL_CM
            c1 = max(0, col1 - t)
            grid[row1:row2, c1:col1] = int(CellType.FOOTPRINT)

    # Corridors intérieurs : toutes les cellules CORRIDOR sont confirmées
    # (les murs et empreintes ont été marqués, le reste reste CORRIDOR)
    return grid


# ---------------------------------------------------------------------------
# Fonctions privées copiées depuis solver/circulation.py
# (Origine : solver/circulation.py — noms préfixés _ conservés)
# ---------------------------------------------------------------------------

def _rectangulate(circ_mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Découpe le masque de circulation en rectangles maximaux (scan greedy).

    Args:
        circ_mask: Masque booléen de shape (ROWS, COLS).

    Returns:
        Liste de (col, row, w, h) en cellules.
    """
    ROWS, COLS = circ_mask.shape
    covered = np.zeros((ROWS, COLS), dtype=bool)
    rects: list[tuple[int, int, int, int]] = []

    for row in range(ROWS):
        for col in range(COLS):
            if not circ_mask[row, col] or covered[row, col]:
                continue
            w = 1
            while col + w < COLS and circ_mask[row, col + w] and not covered[row, col + w]:
                w += 1
            h = 1
            while row + h < ROWS:
                row_ok = True
                for dc in range(w):
                    if not circ_mask[row + h, col + dc] or covered[row + h, col + dc]:
                        row_ok = False
                        break
                if not row_ok:
                    break
                h += 1
            covered[row:row + h, col:col + w] = True
            rects.append((col, row, w, h))

    return rects


def _shared_border_length(
    rect_a: tuple[int, int, int, int],
    rect_b: tuple[int, int, int, int],
) -> int:
    """Longueur du bord partagé entre deux rectangles (0 si non adjacents).

    Args:
        rect_a: (col, row, w, h) du premier rectangle.
        rect_b: (col, row, w, h) du second rectangle.

    Returns:
        Longueur du bord commun en cellules.
    """
    col_a, row_a, w_a, h_a = rect_a
    col_b, row_b, w_b, h_b = rect_b

    if col_a + w_a == col_b:
        return max(0, min(row_a + h_a, row_b + h_b) - max(row_a, row_b))
    if col_b + w_b == col_a:
        return max(0, min(row_a + h_a, row_b + h_b) - max(row_a, row_b))
    if row_a + h_a == row_b:
        return max(0, min(col_a + w_a, col_b + w_b) - max(col_a, col_b))
    if row_b + h_b == row_a:
        return max(0, min(col_a + w_a, col_b + w_b) - max(col_a, col_b))
    return 0


def _build_adjacency(
    rects: list[tuple[int, int, int, int]],
    min_passage: int,
) -> dict[int, list[int]]:
    """Construit le graphe d'adjacence entre rectangles.

    Args:
        rects: Liste de (col, row, w, h).
        min_passage: Longueur minimale de bord partagé en cellules.

    Returns:
        Dictionnaire d'adjacence {index: [voisins]}.
    """
    n = len(rects)
    adj: dict[int, list[int]] = {i: [] for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if _shared_border_length(rects[i], rects[j]) >= min_passage:
                adj[i].append(j)
                adj[j].append(i)
    return adj


def _find_entry_rect(
    rects: list[tuple[int, int, int, int]],
    grid: np.ndarray,
) -> Optional[int]:
    """Retourne l'index du rectangle contenant une cellule DOOR.

    Args:
        rects: Liste de (col, row, w, h).
        grid: Grille numpy de CellType.

    Returns:
        Index du rectangle d'entrée, ou None si aucune porte.
    """
    door_positions = list(zip(*np.where(grid == int(CellType.DOOR))))
    if not door_positions:
        return None

    for door_row, door_col in door_positions:
        for i, (col, row, w, h) in enumerate(rects):
            if row <= door_row < row + h and col <= door_col < col + w:
                return i

    # Fallback : rectangle le plus proche du centre moyen des portes
    avg_row = sum(int(r) for r, _ in door_positions) / len(door_positions)
    avg_col = sum(int(c) for _, c in door_positions) / len(door_positions)

    best_idx = 0
    best_dist = float("inf")
    for i, (col, row, w, h) in enumerate(rects):
        cx = col + w / 2
        cy = row + h / 2
        d = math.hypot(cx - avg_col, cy - avg_row)
        if d < best_dist:
            best_dist = d
            best_idx = i

    return best_idx


def _bfs(adj_graph: dict[int, list[int]], start: int) -> set[int]:
    """BFS dans le graphe d'adjacence depuis le nœud start.

    Args:
        adj_graph: Graphe d'adjacence {index: [voisins]}.
        start: Index de départ.

    Returns:
        Ensemble des indices atteignables (start inclus).
    """
    visited: set[int] = {start}
    queue: deque[int] = deque([start])
    while queue:
        node = queue.popleft()
        for neighbor in adj_graph[node]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return visited


def _rect_center_m(
    rect: tuple[int, int, int, int],
    cell_size_m: float,
) -> tuple[float, float]:
    """Centre d'un rectangle en mètres.

    Args:
        rect: (col, row, w, h) en cellules.
        cell_size_m: Taille d'une cellule en mètres.

    Returns:
        (cx_m, cy_m) coordonnées du centre.
    """
    col, row, w, h = rect
    return (col + w / 2) * cell_size_m, (row + h / 2) * cell_size_m


def _build_weighted_adjacency(
    rects: list[tuple[int, int, int, int]],
    adj_graph: dict[int, list[int]],
    cell_size_m: float,
) -> dict[int, list[tuple[int, float]]]:
    """Construit le graphe pondéré pour Dijkstra.

    Args:
        rects: Liste de (col, row, w, h).
        adj_graph: Graphe d'adjacence non pondéré.
        cell_size_m: Taille d'une cellule en mètres.

    Returns:
        Graphe pondéré {index: [(voisin, poids_m), ...]}.
    """
    weighted: dict[int, list[tuple[int, float]]] = {i: [] for i in range(len(rects))}
    for i, neighbors in adj_graph.items():
        cx_i, cy_i = _rect_center_m(rects[i], cell_size_m)
        for j in neighbors:
            cx_j, cy_j = _rect_center_m(rects[j], cell_size_m)
            dist = math.hypot(cx_j - cx_i, cy_j - cy_i)
            weighted[i].append((j, dist))
    return weighted


def _dijkstra(
    weighted_graph: dict[int, list[tuple[int, float]]],
    start: int,
) -> dict[int, float]:
    """Dijkstra depuis start dans un graphe pondéré.

    Args:
        weighted_graph: {index: [(voisin, poids), ...]}.
        start: Nœud source.

    Returns:
        Dictionnaire {index: distance_minimale_en_mètres}.
    """
    dist: dict[int, float] = {start: 0.0}
    heap: list[tuple[float, int]] = [(0.0, start)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")):
            continue
        for v, w in weighted_graph.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return dist


# ---------------------------------------------------------------------------
# Chemins BFS porte → fauteuil de chaque desk
# ---------------------------------------------------------------------------

@dataclass
class DeskAccess:
    """Résultat d'accès pour un desk d'un bloc."""
    target_row: int       # cellule BFS cible (walkable adjacente au fauteuil)
    target_col: int
    chair_row: float      # centre visuel du fauteuil (en cellules, peut être .5)
    chair_col: float
    desk_id: str


def _desk_access_cells(
    block: dict,
    grid: np.ndarray,
) -> list[DeskAccess]:
    """Cellules d'accès (côté fauteuil) de chaque desk d'un bloc.

    Pour les blocs standard (BLOC_1, BLOC_2_FACE, BLOC_4_FACE, etc.),
    le fauteuil est du côté de la face avec non_superposable_cm > 0.
    Un seul point d'accès par face active.

    Pour les blocs ortho (BLOC_2_ORTHO_D/G), chaque poste a sa propre
    face chaise — un point d'accès par poste avec la zone de chaise
    restreinte à la sous-zone du poste dans le bloc.

    Retourne le point BFS cible (cellule walkable) et le centre visuel
    du fauteuil pour le rendu des flèches.
    """
    from olm.core.pattern_generator import (
        DESK_W_CM, DESK_D_CM, rotate_face_candidates,
        BLOC_1, BLOC_2_FACE, BLOC_2_COTE, BLOC_3_COTE, BLOC_4_FACE,
        BLOC_6_FACE, BLOC_2_ORTHO_D, BLOC_2_ORTHO_G,
    )
    _BLOCKS = {b.name: b for b in [
        BLOC_1, BLOC_2_FACE, BLOC_2_COTE, BLOC_3_COTE, BLOC_4_FACE,
        BLOC_6_FACE, BLOC_2_ORTHO_D, BLOC_2_ORTHO_G,
    ]}

    block_type = block["type"]
    orientation = block.get("orientation", 0)
    x_cm = block["x_cm"]
    y_cm = block["y_cm"]

    if block_type not in _BLOCKS:
        return []
    block_def = _BLOCKS[block_type]
    faces = block_def.faces
    if orientation != 0:
        faces = rotate_face_candidates(faces, orientation)

    ROWS, COLS = grid.shape
    eo = block["eo_cm"]
    ns = block["ns_cm"]
    walkable = {int(CellType.CORRIDOR), int(CellType.DOOR)}

    def _best_walkable(
        candidates: list[tuple[int, int]], mid_r: float, mid_c: float,
    ) -> Optional[tuple[int, int]]:
        valid = [(r, c) for r, c in candidates if int(grid[r, c]) in walkable]
        if not valid:
            return None
        valid.sort(key=lambda rc: abs(rc[0] - mid_r) + abs(rc[1] - mid_c))
        return valid[0]

    def _access_for_zone(
        face: str, zone_x: int, zone_y: int, zone_eo: int, zone_ns: int,
        nsup_cm: int, desk_id: str,
    ) -> Optional[DeskAccess]:
        """Calcule le point d'accès pour une zone de poste sur une face."""
        c1 = zone_x // GRID_CELL_CM
        c2 = (zone_x + zone_eo) // GRID_CELL_CM
        r1 = zone_y // GRID_CELL_CM
        r2 = (zone_y + zone_ns) // GRID_CELL_CM
        r_mid = (r1 + r2) / 2.0
        c_mid = (c1 + c2) / 2.0
        nsup = nsup_cm // GRID_CELL_CM

        if face == "west":
            chair_col = c1 - nsup / 2.0
            c = c1 - nsup - 1
            if c < 0:
                return None
            cands = [(r, c) for r in range(max(0, r1), min(ROWS, r2))]
            best = _best_walkable(cands, r_mid, c)
            return DeskAccess(best[0], best[1], r_mid, chair_col, desk_id) if best else None
        elif face == "east":
            chair_col = c2 + nsup / 2.0
            c = c2 + nsup
            if c >= COLS:
                return None
            cands = [(r, c) for r in range(max(0, r1), min(ROWS, r2))]
            best = _best_walkable(cands, r_mid, c)
            return DeskAccess(best[0], best[1], r_mid, chair_col, desk_id) if best else None
        elif face == "north":
            chair_row = r1 - nsup / 2.0
            r = r1 - nsup - 1
            if r < 0:
                return None
            cands = [(r, c) for c in range(max(0, c1), min(COLS, c2))]
            best = _best_walkable(cands, r, c_mid)
            return DeskAccess(best[0], best[1], chair_row, c_mid, desk_id) if best else None
        elif face == "south":
            chair_row = r2 + nsup / 2.0
            r = r2 + nsup
            if r >= ROWS:
                return None
            cands = [(r, c) for c in range(max(0, c1), min(COLS, c2))]
            best = _best_walkable(cands, r, c_mid)
            return DeskAccess(best[0], best[1], chair_row, c_mid, desk_id) if best else None
        return None

    results: list[DeskAccess] = []

    # ── Blocs ortho : accès par poste individuel ──────────────────────────
    if block_type in ("BLOC_2_ORTHO_D", "BLOC_2_ORTHO_G"):
        # Déterminer les sous-zones de chaque poste selon l'orientation
        # ORTHO_D@0 : desk1 (regard S, chaise N) en haut, desk2 (regard W, chaise E) en bas-gauche
        # ORTHO_G@0 : desk1 (regard S, chaise N) en haut, desk2 (regard E, chaise W) en bas-droite
        # Après rotation, les faces chaise tournent avec rotate_face_candidates
        #
        # Stratégie : on connaît les faces chaise après rotation. Pour ORTHO,
        # les 2 faces non-nulles correspondent aux 2 postes distincts.
        # On découpe le bloc en 2 sous-zones selon la face.
        desk_faces = []
        for f_name in ("north", "south", "east", "west"):
            fz = getattr(faces, f_name)
            if fz.non_superposable_cm > 0:
                desk_faces.append((f_name, fz.non_superposable_cm))

        if len(desk_faces) == 2:
            # Face 1 : zone restreinte au poste correspondant
            # Heuristique : la face N/S couvre la moitié NS du bloc,
            # la face E/W couvre la moitié EO du bloc
            for idx, (f_name, nsup_cm) in enumerate(desk_faces):
                desk_id = f"{block_type}@{orientation}_d{idx}"
                if f_name in ("north", "south"):
                    # Poste horizontal : partie haute ou basse
                    if f_name == "north":
                        zone = (x_cm, y_cm, eo, min(ns, DESK_W_CM))
                    else:
                        zone = (x_cm, y_cm + ns - DESK_W_CM, eo, min(ns, DESK_W_CM))
                else:
                    # Poste vertical : partie gauche ou droite
                    if f_name == "west":
                        zone = (x_cm, y_cm, min(eo, DESK_W_CM), ns)
                    else:
                        zone = (x_cm + eo - DESK_W_CM, y_cm, min(eo, DESK_W_CM), ns)

                acc = _access_for_zone(f_name, *zone, nsup_cm, desk_id)
                if acc:
                    results.append(acc)
        return results

    # ── Blocs standard : accès par face ───────────────────────────────────
    access_faces = []
    if faces.west.non_superposable_cm > 0:
        access_faces.append("west")
    if faces.east.non_superposable_cm > 0:
        access_faces.append("east")
    if faces.north.non_superposable_cm > 0:
        access_faces.append("north")
    if faces.south.non_superposable_cm > 0:
        access_faces.append("south")

    for face in access_faces:
        nsup_cm = getattr(faces, face).non_superposable_cm
        desk_id = f"{block_type}@{orientation}"
        acc = _access_for_zone(face, x_cm, y_cm, eo, ns, nsup_cm, desk_id)
        if acc:
            results.append(acc)

    return results


def _distance_transform(grid: np.ndarray) -> np.ndarray:
    """Calcule la distance de chaque cellule au plus proche obstacle.

    Obstacle = WALL ou FOOTPRINT. Résultat en cellules (BFS Manhattan).
    Les cellules obstacle ont une distance de 0.
    """
    ROWS, COLS = grid.shape
    walkable = {int(CellType.CORRIDOR), int(CellType.DOOR)}
    dist_map = np.zeros((ROWS, COLS), dtype=np.int32)
    queue: deque[tuple[int, int]] = deque()

    # Initialiser : obstacles à distance 0, walkable à -1 (non visité)
    for r in range(ROWS):
        for c in range(COLS):
            if int(grid[r, c]) not in walkable:
                dist_map[r, c] = 0
                queue.append((r, c))
            else:
                dist_map[r, c] = -1

    # BFS multi-source depuis les obstacles
    while queue:
        r, c = queue.popleft()
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < ROWS and 0 <= nc < COLS and dist_map[nr, nc] == -1:
                dist_map[nr, nc] = dist_map[r, c] + 1
                queue.append((nr, nc))

    # Les cellules non atteintes restent à 0
    dist_map[dist_map == -1] = 0
    return dist_map


def _cell_bfs_path(
    grid: np.ndarray,
    start_cells: list[tuple[int, int]],
    target: tuple[int, int],
) -> Optional[list[tuple[int, int]]]:
    """Dijkstra cellulaire depuis start_cells vers target.

    Le coût par cellule favorise le centre des passages : une cellule
    à distance d des obstacles coûte 1/d (plus on est au centre, moins
    ça coûte). Le chemin passe naturellement au milieu des corridors.

    Returns:
        Chemin [(row, col), ...] du start le plus proche à target, ou None.
    """
    ROWS, COLS = grid.shape
    walkable = {int(CellType.CORRIDOR), int(CellType.DOOR)}

    # Carte de coût : inversement proportionnel à la distance aux obstacles
    dist_map = _distance_transform(grid)
    # cost(r, c) = 1.0 + K / max(dist, 1) — K contrôle la force d'attraction
    # vers le centre. K=3 donne un bon équilibre.
    K_CENTER = 3.0

    dist: dict[tuple[int, int], float] = {}
    prev: dict[tuple[int, int], Optional[tuple[int, int]]] = {}
    heap: list[tuple[float, int, int]] = []

    for sc in start_cells:
        if 0 <= sc[0] < ROWS and 0 <= sc[1] < COLS:
            dist[sc] = 0.0
            prev[sc] = None
            heapq.heappush(heap, (0.0, sc[0], sc[1]))

    while heap:
        d, r, c = heapq.heappop(heap)
        if (r, c) == target:
            path: list[tuple[int, int]] = []
            cur: Optional[tuple[int, int]] = (r, c)
            while cur is not None:
                path.append(cur)
                cur = prev[cur]
            path.reverse()
            return path
        if d > dist.get((r, c), float("inf")):
            continue
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < ROWS and 0 <= nc < COLS:
                if int(grid[nr, nc]) in walkable:
                    cell_dist = max(1, int(dist_map[nr, nc]))
                    cost = 1.0 + K_CENTER / cell_dist
                    nd = d + cost
                    if nd < dist.get((nr, nc), float("inf")):
                        dist[(nr, nc)] = nd
                        prev[(nr, nc)] = (r, c)
                        heapq.heappush(heap, (nd, nr, nc))
    return None


def _path_widths_per_cell_cm(
    path: list[tuple[int, int]],
    grid: np.ndarray,
) -> list[int]:
    """Largeur de passage perpendiculaire en cm pour chaque cellule du chemin.

    Pour chaque cellule, mesure le nombre de cellules CORRIDOR/DOOR contiguës
    dans la direction perpendiculaire au sens de déplacement.
    """
    if len(path) < 2:
        return [GRID_CELL_CM] * len(path)

    ROWS, COLS = grid.shape
    walkable = {int(CellType.CORRIDOR), int(CellType.DOOR)}
    widths: list[int] = []

    for i in range(len(path)):
        r, c = path[i]
        if i < len(path) - 1:
            dr = path[i + 1][0] - r
            dc = path[i + 1][1] - c
        else:
            dr = r - path[i - 1][0]
            dc = c - path[i - 1][1]

        if dr != 0:  # vertical → mesurer largeur horizontale
            w = 1
            for sign in (-1, 1):
                nc = c + sign
                while 0 <= nc < COLS and int(grid[r, nc]) in walkable:
                    w += 1
                    nc += sign
        else:  # horizontal → mesurer largeur verticale
            w = 1
            for sign in (-1, 1):
                nr = r + sign
                while 0 <= nr < ROWS and int(grid[nr, c]) in walkable:
                    w += 1
                    nr += sign

        widths.append(w * GRID_CELL_CM)

    return widths


def _path_min_width_cm(
    path: list[tuple[int, int]],
    grid: np.ndarray,
) -> float:
    """Largeur minimale de passage le long d'un chemin, en cm."""
    if not path:
        return 0.0
    widths = _path_widths_per_cell_cm(path, grid)
    return min(widths) if widths else GRID_CELL_CM


@dataclass
class DeskPathResult:
    """Résultat complet d'un chemin porte→fauteuil."""
    desk_id: str
    path: list[tuple[int, int]]       # chemin cellulaire BFS
    min_width_cm: float
    widths_cm: list[int]              # largeur par cellule
    door_center: tuple[float, float]  # (row, col) centre de la porte (fractionnaire)
    chair_center: tuple[float, float] # (row, col) centre du fauteuil (fractionnaire)


def _cluster_door_cells(
    grid: np.ndarray,
) -> list[list[tuple[int, int]]]:
    """Regroupe les cellules DOOR en clusters connexes (une porte = un cluster).

    Utilise un BFS 4-connexe sur les cellules DOOR.

    Args:
        grid: Grille avec cellules CellType.DOOR.

    Returns:
        Liste de clusters, chaque cluster = liste de (row, col).
    """
    door_type = int(CellType.DOOR)
    all_doors = set(
        (int(r), int(c))
        for r, c in zip(*np.where(grid == door_type))
    )
    if not all_doors:
        return []

    clusters: list[list[tuple[int, int]]] = []
    visited: set[tuple[int, int]] = set()

    for start in all_doors:
        if start in visited:
            continue
        cluster: list[tuple[int, int]] = []
        queue: Deque[tuple[int, int]] = deque([start])
        visited.add(start)
        while queue:
            r, c = queue.popleft()
            cluster.append((r, c))
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr, nc = r + dr, c + dc
                if (nr, nc) in all_doors and (nr, nc) not in visited:
                    visited.add((nr, nc))
                    queue.append((nr, nc))
        clusters.append(cluster)

    return clusters


def _compute_desk_paths(
    grid: np.ndarray,
    blocks: list[dict],
    room: dict,
) -> list[DeskPathResult]:
    """Calcule chemin porte→fauteuil et largeurs pour chaque desk.

    Multi-portes : un BFS par cluster de cellules DOOR, le meilleur
    chemin (plus court) est retenu pour chaque poste.
    """
    door_clusters = _cluster_door_cells(grid)
    if not door_clusters:
        return []

    # Tous les accès desks
    all_access: list[DeskAccess] = []
    for block in blocks:
        all_access.extend(_desk_access_cells(block, grid))

    if not all_access:
        return []

    results: list[DeskPathResult] = []

    for access in all_access:
        best_path: list[tuple[int, int]] | None = None
        best_len = float("inf")
        best_door_center = (0.0, 0.0)

        # Tester chaque porte (cluster)
        for cluster in door_clusters:
            path = _cell_bfs_path(
                grid, cluster, (access.target_row, access.target_col),
            )
            if path is not None and len(path) < best_len:
                best_path = path
                best_len = len(path)
                # Centre de cette porte
                best_door_center = (
                    sum(r for r, _ in cluster) / len(cluster) + 0.5,
                    sum(c for _, c in cluster) / len(cluster) + 0.5,
                )

        if best_path is None:
            results.append(DeskPathResult(
                desk_id=access.desk_id,
                path=[],
                min_width_cm=0.0,
                widths_cm=[],
                door_center=best_door_center,
                chair_center=(access.chair_row, access.chair_col),
            ))
        else:
            cell_widths = _path_widths_per_cell_cm(best_path, grid)
            results.append(DeskPathResult(
                desk_id=access.desk_id,
                path=best_path,
                min_width_cm=min(cell_widths),
                widths_cm=cell_widths,
                door_center=best_door_center,
                chair_center=(access.chair_row, access.chair_col),
            ))

    return results


def _compute_grade(connectivity_pct: float, worst_detour: float) -> str:
    """Calcule le grade de qualité de la circulation.

    Args:
        connectivity_pct: Pourcentage de rectangles atteignables.
        worst_detour: Pire ratio distance_graphe / distance_euclidienne.

    Returns:
        Grade "A" à "F".
    """
    if connectivity_pct >= 100.0 and worst_detour < 1.30:
        return "A"
    if connectivity_pct >= 90.0 and worst_detour < 1.60:
        return "B"
    if connectivity_pct >= 70.0 and worst_detour < 2.00:
        return "C"
    if connectivity_pct >= 50.0:
        return "D"
    return "F"


def _compute_violations(
    connectivity_pct: float,
    isolated_area_pct: float,
    isolated_zones: list[tuple[int, int, int, int]],
    worst_detour: float,
    cell_size_m: float,
) -> list[str]:
    """Génère les messages de violation pour feedback.

    Args:
        connectivity_pct: Pourcentage de connexité.
        isolated_area_pct: Pourcentage de surface inaccessible.
        isolated_zones: Rectangles inaccessibles [(col, row, w, h), ...].
        worst_detour: Pire ratio de détour.
        cell_size_m: Taille d'une cellule en mètres.

    Returns:
        Liste de messages de violation.
    """
    violations: list[str] = []
    MIN_ISOLATED_AREA_M2 = 0.50

    significant = [
        z for z in isolated_zones
        if z[2] * z[3] * cell_size_m ** 2 >= MIN_ISOLATED_AREA_M2
    ]
    if significant:
        violations.append(
            f"ISOLATED_ZONE: {len(significant)} zones inaccessibles "
            f"({isolated_area_pct:.0f}% surface)"
        )

    if worst_detour > 2.0:
        violations.append(f"DETOUR_EXCESSIVE: ratio {worst_detour:.2f} depuis porte")

    cell_area_m2 = cell_size_m ** 2
    for col, row, w, h in isolated_zones:
        area_m2 = w * h * cell_area_m2
        if area_m2 > 2.0:
            violations.append(f"LARGE_ISOLATED: zone {col},{row} = {area_m2:.1f} m²")

    return violations


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def analyse(
    room: dict,
    blocks: list[dict],
    door_depth_cm: int = AFNOR_ADVICE.door_exclusion_depth_cm,
) -> CirculationResult:
    """Analyse la qualité de la circulation pour un candidat du matching.

    Args:
        room: Dict avec eo_cm, ns_cm, doors.
        blocks: Liste de blocs positionnés (format candidat static_matcher).
        door_depth_cm: Profondeur de la zone d'exclusion porte en cm.

    Returns:
        CirculationResult avec grade, métriques et violations.
    """
    t0 = time.perf_counter()
    cell_size_m = GRID_CELL_CM / 100.0

    # Étape 1 — Construction de la grille
    grid = build_grid(room, blocks, door_depth_cm)
    if grid is None or grid.size == 0:
        return CirculationResult(
            grade="F",
            connectivity_pct=0.0,
            isolated_area_pct=100.0,
            avg_detour_ratio=0.0,
            worst_detour_ratio=0.0,
            violations=["Grille indisponible"],
            analysis_time_ms=round((time.perf_counter() - t0) * 1000, 2),
        )

    # Étape 2 — Masque de circulation
    circ_mask = (grid == int(CellType.CORRIDOR)) | (grid == int(CellType.DOOR))

    # Étape 3 — Rectangulation greedy
    rects = _rectangulate(circ_mask)
    if not rects:
        return CirculationResult(
            grade="F",
            connectivity_pct=0.0,
            isolated_area_pct=100.0,
            avg_detour_ratio=0.0,
            worst_detour_ratio=0.0,
            violations=["Aucune zone de circulation détectée"],
            analysis_time_ms=round((time.perf_counter() - t0) * 1000, 2),
        )

    # Étape 4 — Graphe d'adjacence
    # Largeur minimale de passage AFNOR NF X35-102 = 80 cm
    MIN_PASSAGE_CM = 80
    min_passage_cells = MIN_PASSAGE_CM // GRID_CELL_CM
    adj_graph = _build_adjacency(rects, min_passage=min_passage_cells)
    n_rects = len(rects)

    # Étape 5 — Rectangle d'entrée
    entry_idx = _find_entry_rect(rects, grid)
    if entry_idx is None:
        return CirculationResult(
            grade="F",
            connectivity_pct=0.0,
            isolated_area_pct=100.0,
            avg_detour_ratio=0.0,
            worst_detour_ratio=0.0,
            violations=["Aucune porte trouvée dans la zone de circulation"],
            analysis_time_ms=round((time.perf_counter() - t0) * 1000, 2),
        )

    # Étape 6 — Connexité BFS
    reachable: set[int] = _bfs(adj_graph, entry_idx)
    connectivity_pct = len(reachable) / n_rects * 100.0

    rect_areas = [w * h for (_, _, w, h) in rects]
    total_area_cells = sum(rect_areas)
    reachable_area_cells = sum(rect_areas[i] for i in reachable)
    isolated_area_cells = total_area_cells - reachable_area_cells
    isolated_area_pct = (
        isolated_area_cells / total_area_cells * 100.0 if total_area_cells > 0 else 0.0
    )
    isolated_zones = [rects[i] for i in range(n_rects) if i not in reachable]

    # Étape 7 — Dijkstra (détours)
    weighted_graph = _build_weighted_adjacency(rects, adj_graph, cell_size_m)
    dist_m = _dijkstra(weighted_graph, entry_idx)

    cx_e, cy_e = _rect_center_m(rects[entry_idx], cell_size_m)
    ratios: list[float] = []
    for i in reachable:
        if i == entry_idx:
            continue
        d_graph = dist_m.get(i, float("inf"))
        cx_i, cy_i = _rect_center_m(rects[i], cell_size_m)
        d_eucl = math.hypot(cx_i - cx_e, cy_i - cy_e)
        if d_eucl > 0.1 and d_graph < float("inf"):
            ratios.append(d_graph / d_eucl)

    avg_detour = sum(ratios) / len(ratios) if ratios else 1.0
    worst_detour = max(ratios) if ratios else 1.0

    # Étape 8 — Grade et violations
    grade = _compute_grade(connectivity_pct, worst_detour)
    violations = _compute_violations(
        connectivity_pct, isolated_area_pct, isolated_zones, worst_detour, cell_size_m
    )

    # Étape 9 — Chemins BFS porte → fauteuil de chaque desk
    desk_path_results = _compute_desk_paths(grid, blocks, room)
    paths = [r.path for r in desk_path_results]
    path_widths = [r.min_width_cm for r in desk_path_results]
    desk_ids = [r.desk_id for r in desk_path_results]
    widths_per_cell = [r.widths_cm for r in desk_path_results]

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.debug(
        "Circulation: grade=%s connectivity=%.1f%% detour_max=%.2f t=%.1fms",
        grade, connectivity_pct, worst_detour, elapsed_ms,
    )

    return CirculationResult(
        grade=grade,
        connectivity_pct=round(connectivity_pct, 1),
        isolated_area_pct=round(isolated_area_pct, 1),
        avg_detour_ratio=round(avg_detour, 3),
        worst_detour_ratio=round(worst_detour, 3),
        violations=violations,
        paths=paths,
        path_widths=path_widths,
        desk_ids=desk_ids,
        widths_per_cell=widths_per_cell,
        analysis_time_ms=elapsed_ms,
    )
