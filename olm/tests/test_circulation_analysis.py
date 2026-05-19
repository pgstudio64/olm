"""Tests pour olm.core.circulation_analysis — P1.3.

Couvre : _compute_grade (5 paliers), _compute_violations (4 cas),
build_grid (2), analyse() integration (5 dont piece en L).
"""
from __future__ import annotations

import numpy as np
import pytest

from olm.core.circulation_analysis import (
    _compute_grade,
    _compute_violations,
    analyse,
    build_grid,
)
from olm.core.matching_config import GRID_CELL_CM
from olm.core.types import CellType

# ---------------------------------------------------------------------------
# Helpers — factories synthetiques
# ---------------------------------------------------------------------------

def _make_room(
    eo_cm: int = 500,
    ns_cm: int = 500,
    doors: list[dict] | None = None,
) -> dict:
    """Room dict synthetique."""
    if doors is None:
        doors = [{"wall": "south", "position_cm": 200, "width_cm": 90}]
    return {"eo_cm": eo_cm, "ns_cm": ns_cm, "doors": doors}


def _make_block(
    type_name: str,
    x_cm: int,
    y_cm: int,
    eo_cm: int,
    ns_cm: int,
    orientation: int = 0,
) -> dict:
    """Block dict synthetique."""
    return {
        "type": type_name,
        "orientation": orientation,
        "x_cm": x_cm,
        "y_cm": y_cm,
        "eo_cm": eo_cm,
        "ns_cm": ns_cm,
    }


# ---------------------------------------------------------------------------
# 1-5 : _compute_grade — 5 paliers + frontieres
# ---------------------------------------------------------------------------

class TestComputeGrade:
    """Tests des 5 paliers de CIRCULATION_GRADES."""

    def test_grade_a_full_connectivity_low_detour(self) -> None:
        """Grade A : connectivity 100 %, detour < 1.30."""
        assert _compute_grade(100.0, 1.1) == "A"

    def test_grade_b_high_connectivity_moderate_detour(self) -> None:
        """Grade B : connectivity >= 90 %, detour < 1.60."""
        assert _compute_grade(95.0, 1.5) == "B"

    def test_grade_c_medium_connectivity(self) -> None:
        """Grade C : connectivity >= 70 %, detour < 2.00."""
        assert _compute_grade(75.0, 1.8) == "C"

    def test_grade_d_low_connectivity_high_detour(self) -> None:
        """Grade D : connectivity >= 50 %, detour sans contrainte."""
        assert _compute_grade(60.0, 5.0) == "D"

    def test_grade_f_very_low_connectivity(self) -> None:
        """Grade F : connectivity < 50 %."""
        assert _compute_grade(40.0, 3.0) == "F"

    def test_grade_boundary_a_to_b(self) -> None:
        """Frontiere A/B : detour == 1.30 (strict <) → B."""
        assert _compute_grade(100.0, 1.30) == "B"

    def test_grade_boundary_b_to_c(self) -> None:
        """Frontiere B/C : detour == 1.60 (strict <) → C."""
        assert _compute_grade(90.0, 1.60) == "C"

    def test_grade_boundary_d_threshold(self) -> None:
        """Frontiere D/F : connectivity 49.9 % → F."""
        assert _compute_grade(49.9, 1.0) == "F"


# ---------------------------------------------------------------------------
# 6-9 : _compute_violations
# ---------------------------------------------------------------------------

class TestComputeViolations:
    """Tests des violations circulation."""

    def test_violation_isolated_zone(self) -> None:
        """Zone isolee >= 0.50 m2 → ISOLATED_ZONE."""
        cell_size_m = GRID_CELL_CM / 100.0
        # Zone de 10x5 cellules = 50 cellules × 0.01 m2 = 0.50 m2
        zones = [(0, 0, 10, 5)]
        violations = _compute_violations(
            connectivity_pct=80.0,
            isolated_area_pct=10.0,
            isolated_zones=zones,
            worst_detour=1.5,
            cell_size_m=cell_size_m,
        )
        assert any("ISOLATED_ZONE" in v for v in violations)

    def test_violation_detour_excessive(self) -> None:
        """Detour > 2.00 (seuil grade C) → DETOUR_EXCESSIVE."""
        cell_size_m = GRID_CELL_CM / 100.0
        violations = _compute_violations(
            connectivity_pct=100.0,
            isolated_area_pct=0.0,
            isolated_zones=[],
            worst_detour=2.5,
            cell_size_m=cell_size_m,
        )
        assert any("DETOUR_EXCESSIVE" in v for v in violations)

    def test_violation_large_isolated(self) -> None:
        """Zone isolee > 2.0 m2 → LARGE_ISOLATED."""
        cell_size_m = GRID_CELL_CM / 100.0
        # Zone de 20x10 cellules = 200 cellules × 0.01 m2 = 2.0 m2
        # Besoin > 2.0, donc 201 cellules → 20x11 = 220
        zones = [(0, 0, 20, 11)]
        violations = _compute_violations(
            connectivity_pct=80.0,
            isolated_area_pct=15.0,
            isolated_zones=zones,
            worst_detour=1.5,
            cell_size_m=cell_size_m,
        )
        assert any("LARGE_ISOLATED" in v for v in violations)

    def test_no_violations_clean(self) -> None:
        """Aucune violation quand tout est correct."""
        cell_size_m = GRID_CELL_CM / 100.0
        violations = _compute_violations(
            connectivity_pct=100.0,
            isolated_area_pct=0.0,
            isolated_zones=[],
            worst_detour=1.2,
            cell_size_m=cell_size_m,
        )
        assert violations == []


# ---------------------------------------------------------------------------
# 10-11 : build_grid
# ---------------------------------------------------------------------------

class TestBuildGrid:
    """Tests de construction de la grille discrete."""

    def test_walls_and_door(self) -> None:
        """Grille avec murs peripheriques et porte south."""
        room = _make_room(eo_cm=200, ns_cm=200,
                          doors=[{"wall": "south",
                                  "position_cm": 50, "width_cm": 90}])
        grid = build_grid(room, [])
        rows, cols = grid.shape
        assert rows == 200 // GRID_CELL_CM
        assert cols == 200 // GRID_CELL_CM

        # Mur nord (row 0)
        assert np.all(grid[0, :] == int(CellType.WALL))
        # Interieur = corridor
        assert grid[rows // 2, cols // 2] == int(CellType.CORRIDOR)
        # Porte south : cellules (rows-1, 5) a (rows-1, 13)
        door_start = 50 // GRID_CELL_CM
        door_end = (50 + 90) // GRID_CELL_CM
        for c in range(door_start, door_end):
            assert grid[rows - 1, c] == int(CellType.DOOR)

    def test_block_footprint(self) -> None:
        """Un bloc cree des cellules FOOTPRINT dans la grille."""
        room = _make_room(eo_cm=500, ns_cm=500)
        block = _make_block("BLOCK_1", x_cm=100, y_cm=100,
                            eo_cm=80, ns_cm=180)
        grid = build_grid(room, [block])

        # Centre du bloc = FOOTPRINT
        r_mid = (100 + 90) // GRID_CELL_CM
        c_mid = (100 + 40) // GRID_CELL_CM
        assert grid[r_mid, c_mid] == int(CellType.FOOTPRINT)

        # Cellule loin du bloc = CORRIDOR
        assert grid[40, 40] == int(CellType.CORRIDOR)

    def test_oversize_block_clamps_indices(self) -> None:
        """Regression D-242 : un bloc qui deborde la piece ne crashe pas.

        Avant ce fix, ``build_grid`` indexait ``grid[row1:row2, col1:col2]``
        sans clamp, ce qui levait ``IndexError: index N out of bounds for
        axis 0 with size M`` quand un pattern oversize atteignait la
        circulation analysis (apres D-242 qui retire le hard filter).
        """
        room = _make_room(eo_cm=350, ns_cm=350)
        # Bloc volontairement plus large que la piece (480 > 350)
        block = _make_block("BLOCK_1", x_cm=0, y_cm=0,
                            eo_cm=480, ns_cm=500)
        # Ne doit pas lever — clampage aux bornes du grid
        grid = build_grid(room, [block])
        rows, cols = grid.shape
        assert rows == 350 // GRID_CELL_CM
        assert cols == 350 // GRID_CELL_CM
        # Tout l'interieur est FOOTPRINT (le bloc clamp couvre toute la piece
        # sauf les bords WALL).
        assert grid[rows // 2, cols // 2] == int(CellType.FOOTPRINT)


class TestAnalyseOversize:
    """Regression D-242 hotfix #2 : analyse() ne crashe pas sur oversize."""

    def test_analyse_oversize_block_no_crash(self) -> None:
        """Bloc place largement hors piece (x=480 dans piece 350) — analyse ne plante pas.

        Avant ce fix, ``_access_for_zone`` calculait un r ou c hors bornes
        cote positif (eg r1=48 dans grid de 35 rangees), que ``_best_walkable``
        utilisait directement pour ``grid[r, c]`` → IndexError axis 0.
        """
        room = _make_room(eo_cm=350, ns_cm=350,
                          doors=[{"wall": "south",
                                  "position_cm": 50, "width_cm": 90}])
        # Bloc place a x=480 (hors piece 350), simule un pattern oversize
        block = _make_block("BLOCK_1", x_cm=480, y_cm=480,
                            eo_cm=80, ns_cm=180)
        result = analyse(room, [block])
        # Ne doit pas crasher — la grade est ce qu'elle est, on n'a juste
        # pas d'IndexError.
        assert result.grade in ("A", "B", "C", "D", "E", "F")


# ---------------------------------------------------------------------------
# 12-16 : analyse() integration
# ---------------------------------------------------------------------------

class TestAnalyse:
    """Tests d'integration du pipeline analyse()."""

    def test_empty_room_grade_a(self) -> None:
        """Piece vide avec 1 porte → Grade A, 100 % connectivity."""
        room = _make_room(eo_cm=500, ns_cm=500)
        result = analyse(room, [])

        assert result.grade == "A"
        assert result.connectivity_pct == pytest.approx(100.0, abs=1.0)
        assert result.worst_detour_ratio < 1.30
        assert result.desk_ids == []
        assert result.violations == []

    def test_no_door_grade_f(self) -> None:
        """Piece sans porte → Grade F, violation 'No door found'."""
        room = _make_room(doors=[])
        result = analyse(room, [])

        assert result.grade == "F"
        assert any("No door" in v for v in result.violations)

    def test_two_doors(self) -> None:
        """Piece avec 2 portes (south + north) → Grade A."""
        room = _make_room(
            eo_cm=500, ns_cm=500,
            doors=[
                {"wall": "south", "position_cm": 200, "width_cm": 90},
                {"wall": "north", "position_cm": 200, "width_cm": 90},
            ],
        )
        result = analyse(room, [])

        assert result.grade == "A"
        assert result.connectivity_pct == pytest.approx(100.0, abs=1.0)

    def test_blocked_area_connectivity_degraded(self) -> None:
        """Barre horizontale coupant la piece → connectivity < 100 %."""
        room = _make_room(eo_cm=500, ns_cm=500)
        # Barre horizontale mur-a-mur a y=240, hauteur 20 cm.
        # Coupe la piece en 2 sections nord/sud deconnectees.
        # La porte est au sud → section nord isolee.
        bar = _make_block("FAKE_BAR", x_cm=0, y_cm=240,
                          eo_cm=500, ns_cm=20)
        result = analyse(room, [bar])

        assert result.connectivity_pct < 100.0
        assert result.grade != "A"

    def test_room_with_block_and_desk(self) -> None:
        """Piece avec 1 BLOCK_1 accessible → desk_ids non vide."""
        # BLOCK_1 : 80×180, chaise face west (non_superposable=70)
        # Place le bloc assez loin du mur pour que la chaise soit accessible.
        room = _make_room(eo_cm=500, ns_cm=500)
        block = _make_block("BLOCK_1", x_cm=200, y_cm=100,
                            eo_cm=80, ns_cm=180)
        result = analyse(room, [block])

        assert result.grade in ("A", "B")
        assert len(result.desk_ids) >= 1
        assert all(w >= 0 for w in result.path_widths)

    def test_l_shaped_room(self) -> None:
        """Piece en L : bbox + exclusion_zone dans un coin NE."""
        # Piece 1000×1000, exclusion 200×200 dans le coin NE → L leger.
        # 1 porte au sud loin du bloc, 1 BLOCK_1 dans la partie accessible.
        # La porte est placee a droite (position_cm=500) pour s'aligner
        # avec le large corridor sous le bloc (>= 80 cm de bordure
        # commune avec le rectangle de porte).
        room = _make_room(eo_cm=1000, ns_cm=1000,
                          doors=[{"wall": "south",
                                  "position_cm": 500, "width_cm": 90}])
        exclusion = _make_block("FAKE_PILLAR", x_cm=800, y_cm=0,
                                eo_cm=200, ns_cm=200)
        desk = _make_block("BLOCK_1", x_cm=200, y_cm=400,
                           eo_cm=80, ns_cm=180)
        result = analyse(room, [exclusion, desk])

        assert result.connectivity_pct == pytest.approx(100.0, abs=1.0)
        assert len(result.desk_ids) >= 1
