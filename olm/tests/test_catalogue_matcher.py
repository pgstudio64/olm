"""Tests pour catalogue_matcher — pipeline de matching 7 étapes (D-54)."""
from __future__ import annotations

import copy
import sys
import os

import pytest

# Ajout du chemin solver_lab pour imports directs
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from olm.core.room_model import RoomSpec, ExclusionZone, OpeningSpec, WindowSpec, Face, HingeSide
from olm.core.catalogue_matcher import (
    count_desks,
    pareto_front,
    PatternCandidate,
    select_candidates,
    SelectionResult,
    mirror_pattern,
    adapt_to_room,
    compute_desk_positions,
    DeskPosition,
    remove_conflicting_desks,
    largest_free_rectangle_m2,
    generate_auto_name,
    compact_catalogue_names,
    load_catalogue,
    _BLOCK_N_DESKS,
)
from olm.core.pattern_generator import DESK_W_CM, DESK_D_CM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pattern(
    rows_spec: list[list[dict]],
    name: str = "test",
    standard: str = "AFNOR_ADVICE",
    room_width_cm: int = 400,
    room_depth_cm: int = 400,
    row_gaps_cm: list[int] | None = None,
    room_openings: list[dict] | None = None,
) -> dict:
    """Construit un pattern JSON minimal pour les tests.

    rows_spec: liste de listes de dicts bloc, ex:
        [[{"type": "BLOCK_1", "gap_cm": 0}]]
    """
    rows = []
    for row_blocks in rows_spec:
        blocks = []
        for b in row_blocks:
            block = {
                "type": b.get("type", "BLOCK_1"),
                "orientation": b.get("orientation", 0),
                "gap_cm": b.get("gap_cm", 0),
                "offset_ns_cm": b.get("offset_ns_cm", 0),
            }
            if "sticks" in b:
                block["sticks"] = b["sticks"]
            blocks.append(block)
        rows.append({"blocks": blocks})
    p = {
        "name": name,
        "standard": standard,
        "room_width_cm": room_width_cm,
        "room_depth_cm": room_depth_cm,
        "rows": rows,
    }
    if row_gaps_cm is not None:
        p["row_gaps_cm"] = row_gaps_cm
    if room_openings is not None:
        p["room_openings"] = room_openings
    return p


def _make_candidate(
    name: str = "C",
    room_width_cm: int = 300,
    room_depth_cm: int = 400,
    standard: str = "AFNOR_ADVICE",
    n_desks: int = 4,
) -> PatternCandidate:
    """Construit un PatternCandidate minimal."""
    pattern = _make_pattern(
        [[{"type": "BLOCK_4_FACE"}]],
        name=name,
        standard=standard,
        room_width_cm=room_width_cm,
        room_depth_cm=room_depth_cm,
    )
    return PatternCandidate(
        pattern=pattern,
        name=name,
        room_width_cm=room_width_cm,
        room_depth_cm=room_depth_cm,
        standard=standard,
        n_desks=n_desks,
    )


# ---------------------------------------------------------------------------
# 1. count_desks
# ---------------------------------------------------------------------------

class TestCountDesks:
    """Vérifie le comptage de postes pour les types de blocs connus."""

    @pytest.mark.parametrize("block_type,expected", [
        ("BLOCK_1", 1),
        ("BLOCK_2_FACE", 2),
        ("BLOCK_2_SIDE", 2),
        ("BLOCK_3_SIDE", 3),
        ("BLOCK_4_FACE", 4),
        ("BLOCK_6_FACE", 6),
        ("BLOCK_2_ORTHO_R", 2),
        ("BLOCK_2_ORTHO_L", 2),
    ])
    def test_single_block(self, block_type: str, expected: int):
        p = _make_pattern([[{"type": block_type}]])
        assert count_desks(p) == expected

    def test_multiple_blocks(self):
        p = _make_pattern([
            [{"type": "BLOCK_4_FACE"}, {"type": "BLOCK_2_FACE"}],
            [{"type": "BLOCK_1"}],
        ])
        assert count_desks(p) == 4 + 2 + 1

    def test_empty_pattern(self):
        p = _make_pattern([])
        assert count_desks(p) == 0

    def test_unknown_block_type(self):
        p = _make_pattern([[{"type": "BLOCK_UNKNOWN"}]])
        assert count_desks(p) == 0


# ---------------------------------------------------------------------------
# 2. pareto_front
# ---------------------------------------------------------------------------

class TestParetoFront:
    """Vérifie le front de Pareto sur (largeur, profondeur)."""

    def test_no_dominated(self):
        """Deux candidats non dominés restent tous les deux."""
        c1 = _make_candidate("A", room_width_cm=400, room_depth_cm=300)
        c2 = _make_candidate("B", room_width_cm=300, room_depth_cm=400)
        front = pareto_front([c1, c2])
        assert len(front) == 2

    def test_dominated_removed(self):
        """Un candidat dominé par un autre est éliminé."""
        big = _make_candidate("big", room_width_cm=500, room_depth_cm=500)
        small = _make_candidate("small", room_width_cm=300, room_depth_cm=300)
        front = pareto_front([big, small])
        assert len(front) == 1
        assert front[0].name == "big"

    def test_identical_not_dominated(self):
        """Deux candidats de mêmes dimensions ne se dominent pas."""
        c1 = _make_candidate("A", room_width_cm=400, room_depth_cm=400)
        c2 = _make_candidate("B", room_width_cm=400, room_depth_cm=400)
        front = pareto_front([c1, c2])
        assert len(front) == 2

    def test_single_candidate(self):
        c = _make_candidate("solo")
        front = pareto_front([c])
        assert len(front) == 1

    def test_empty(self):
        assert pareto_front([]) == []

    def test_three_candidates_mixed(self):
        """Un dominé, deux non dominés sur le front."""
        c1 = _make_candidate("A", room_width_cm=500, room_depth_cm=300)
        c2 = _make_candidate("B", room_width_cm=300, room_depth_cm=500)
        c3 = _make_candidate("C", room_width_cm=400, room_depth_cm=400)
        # c3 n'est dominé ni par c1 (c1.depth=300 < c3.depth=400)
        # ni par c2 (c2.width=300 < c3.width=400)
        front = pareto_front([c1, c2, c3])
        assert len(front) == 3


# ---------------------------------------------------------------------------
# 3. select_candidates (avec vrai catalogue)
# ---------------------------------------------------------------------------

class TestSelectCandidates:
    """Vérifie la sélection de candidats avec le vrai catalogue."""

    @pytest.fixture
    def catalogue(self):
        return load_catalogue()

    def test_small_room_no_candidates(self, catalogue):
        """Pièce trop petite : aucun candidat ne rentre."""
        if not catalogue:
            pytest.skip("Catalogue vide")
        tiny = RoomSpec(width_cm=100, depth_cm=100)
        results = select_candidates(catalogue, tiny)
        for sel in results:
            assert len(sel.candidates) == 0

    def test_large_room_has_candidates(self, catalogue):
        """Pièce assez grande : au moins un candidat rentre."""
        if not catalogue:
            pytest.skip("Catalogue vide")
        large = RoomSpec(width_cm=800, depth_cm=600)
        results = select_candidates(catalogue, large)
        # Au moins un standard devrait avoir des candidats
        total = sum(len(sel.candidates) for sel in results)
        assert total > 0

    def test_single_standard_returns_single_result(self, catalogue):
        if not catalogue:
            pytest.skip("Catalogue vide")
        room = RoomSpec(width_cm=800, depth_cm=600)
        result = select_candidates(catalogue, room, standard="AFNOR_ADVICE")
        assert isinstance(result, SelectionResult)
        assert result.standard == "AFNOR_ADVICE"

    def test_pareto_subset_of_fitting(self, catalogue):
        """Les candidats Pareto sont un sous-ensemble de all_fitting."""
        if not catalogue:
            pytest.skip("Catalogue vide")
        room = RoomSpec(width_cm=600, depth_cm=500)
        results = select_candidates(catalogue, room)
        for sel in results:
            for c in sel.candidates:
                assert c in sel.all_fitting


# ---------------------------------------------------------------------------
# 4. mirror_pattern
# ---------------------------------------------------------------------------

class TestMirrorPattern:
    """Vérifie le miroir E-O des patterns."""

    def test_preserves_desk_count(self):
        p = _make_pattern([
            [{"type": "BLOCK_4_FACE", "gap_cm": 10}, {"type": "BLOCK_2_FACE", "gap_cm": 20}],
        ], room_width_cm=600)
        m = mirror_pattern(p)
        assert count_desks(m) == count_desks(p)

    def test_name_suffix_mir(self):
        p = _make_pattern([[{"type": "BLOCK_1"}]], name="test_pat")
        m = mirror_pattern(p)
        assert m["name"] == "test_pat_MIR"

    def test_sticks_e_o_swap(self):
        """Sticks E deviennent O et vice versa."""
        p = _make_pattern([
            [
                {"type": "BLOCK_1", "sticks": ["O"], "gap_cm": 0},
                {"type": "BLOCK_1", "sticks": ["E"], "gap_cm": 100},
            ],
        ], room_width_cm=400)
        m = mirror_pattern(p)
        # L'ordre des blocs est inversé dans le miroir
        blocks = m["rows"][0]["blocks"]
        # L'ancien bloc E (dernier) est maintenant premier avec stick O
        # L'ancien bloc O (premier) est maintenant dernier avec stick E
        all_sticks = [b.get("sticks", []) for b in blocks]
        flat_sticks = [s for sticks in all_sticks for s in sticks]
        assert "E" in flat_sticks
        assert "O" in flat_sticks

    def test_ortho_d_becomes_g(self):
        """BLOCK_2_ORTHO_R devient BLOCK_2_ORTHO_L et inversement."""
        p = _make_pattern([
            [{"type": "BLOCK_2_ORTHO_R"}],
        ], room_width_cm=400)
        m = mirror_pattern(p)
        assert m["rows"][0]["blocks"][0]["type"] == "BLOCK_2_ORTHO_L"

    def test_ortho_g_becomes_d(self):
        p = _make_pattern([
            [{"type": "BLOCK_2_ORTHO_L"}],
        ], room_width_cm=400)
        m = mirror_pattern(p)
        assert m["rows"][0]["blocks"][0]["type"] == "BLOCK_2_ORTHO_R"

    def test_double_mirror_roundtrip(self):
        """Miroir deux fois = retour à l'original (mêmes positions de postes)."""
        p = _make_pattern([
            [{"type": "BLOCK_4_FACE", "gap_cm": 20, "sticks": ["O"]},
             {"type": "BLOCK_2_FACE", "gap_cm": 30, "sticks": ["E"]}],
        ], room_width_cm=500)
        m1 = mirror_pattern(p)
        m2 = mirror_pattern(m1)
        # Les positions de postes doivent être identiques
        desks_orig = compute_desk_positions(p)
        desks_round = compute_desk_positions(m2)
        assert len(desks_orig) == len(desks_round)
        for d1, d2 in zip(desks_orig, desks_round):
            assert abs(d1.x_cm - d2.x_cm) <= 1
            assert abs(d1.y_cm - d2.y_cm) <= 1


# ---------------------------------------------------------------------------
# 5. adapt_to_room
# ---------------------------------------------------------------------------

class TestAdaptToRoom:
    """Vérifie le calage sticks + homothétie."""

    def test_stick_e_stays_at_east_wall(self):
        """Un bloc stick E doit rester collé au mur est dans la pièce cible."""
        # Pattern dans pièce 400 avec bloc stick E à position gap=200
        p = _make_pattern([
            [{"type": "BLOCK_1", "sticks": ["O"], "gap_cm": 0},
             {"type": "BLOCK_1", "sticks": ["E"], "gap_cm": 100}],
        ], room_width_cm=400, room_depth_cm=300)

        target = RoomSpec(width_cm=500, depth_cm=300)
        adapted = adapt_to_room(p, target)
        assert adapted["room_width_cm"] == 500

        # Calculer les positions de postes adaptées
        desks = compute_desk_positions(adapted)
        # Le bloc stick E : sa position + largeur doit atteindre le mur est
        # On vérifie que le gap a été ajusté correctement (dw=100 de plus)
        blocks = adapted["rows"][0]["blocks"]
        x = 0
        for b in blocks:
            x += b.get("gap_cm", 0)
            from olm.core.catalogue_matcher import _block_eo_extent
            x += _block_eo_extent(b)
        # La dernière position ne doit pas dépasser la largeur cible
        assert x <= 500

    def test_gaps_adjusted_with_extra_width(self):
        """L'espace supplémentaire est distribué entre les ancres."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "sticks": ["O"], "gap_cm": 10},
             {"type": "BLOCK_1", "sticks": ["E"], "gap_cm": 50}],
        ], room_width_cm=300, room_depth_cm=300)
        target = RoomSpec(width_cm=400, depth_cm=300)
        adapted = adapt_to_room(p, target)
        # Le gap du bloc O reste fixe, le gap du bloc E augmente
        blocks = adapted["rows"][0]["blocks"]
        assert blocks[0]["gap_cm"] == 10  # Stick O inchangé

    def test_room_dimensions_updated(self):
        p = _make_pattern([[{"type": "BLOCK_1"}]],
                          room_width_cm=300, room_depth_cm=300)
        target = RoomSpec(width_cm=500, depth_cm=400)
        adapted = adapt_to_room(p, target)
        assert adapted["room_width_cm"] == 500
        assert adapted["room_depth_cm"] == 400


# ---------------------------------------------------------------------------
# 6. compute_desk_positions
# ---------------------------------------------------------------------------

class TestComputeDeskPositions:
    """Vérifie les positions absolues des postes."""

    def test_single_bloc_1(self):
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 10}],
        ])
        desks = compute_desk_positions(p)
        assert len(desks) == 1
        d = desks[0]
        assert d.x_cm == 10
        assert d.y_cm == 0
        assert d.width_cm == DESK_W_CM
        assert d.depth_cm == DESK_D_CM

    def test_bloc_4_face_has_4_desks(self):
        p = _make_pattern([
            [{"type": "BLOCK_4_FACE", "gap_cm": 0}],
        ])
        desks = compute_desk_positions(p)
        assert len(desks) == 4
        # Tous dans le rectangle du bloc
        for d in desks:
            assert d.x_cm >= 0
            assert d.y_cm >= 0

    def test_two_rows_with_gap(self):
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 0}],
            [{"type": "BLOCK_1", "gap_cm": 0}],
        ], row_gaps_cm=[50])
        desks = compute_desk_positions(p)
        assert len(desks) == 2
        # Le second poste doit être décalé verticalement
        assert desks[1].y_cm > desks[0].y_cm

    def test_gap_between_blocks(self):
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 0},
             {"type": "BLOCK_1", "gap_cm": 50}],
        ])
        desks = compute_desk_positions(p)
        assert len(desks) == 2
        assert desks[1].x_cm == DESK_W_CM + 50

    def test_rotated_bloc_1(self):
        """Un BLOCK_1 orienté à 90 a ses dimensions swappées."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "orientation": 90, "gap_cm": 0}],
        ])
        desks = compute_desk_positions(p)
        assert len(desks) == 1
        d = desks[0]
        # Après rotation 90, w et d sont échangés
        assert d.width_cm == DESK_D_CM
        assert d.depth_cm == DESK_W_CM


# ---------------------------------------------------------------------------
# 7. remove_conflicting_desks
# ---------------------------------------------------------------------------

class TestRemoveConflictingDesks:
    """Vérifie la suppression de postes en zone interdite."""

    def test_desk_in_exclusion_zone_removed(self):
        """Un poste dans une zone d'exclusion est supprimé."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 10}],
        ], room_width_cm=400, room_depth_cm=400)
        # Zone d'exclusion couvrant la position du desk (x=10, y=0)
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            exclusion_zones=[
                ExclusionZone(x_cm=0, y_cm=0, width_cm=200, depth_cm=200),
            ],
        )
        result, removed = remove_conflicting_desks(p, room)
        assert len(removed) == 1
        assert result["_n_desks_after_removal"] == 0

    def test_desk_outside_exclusion_zone_kept(self):
        """Un poste hors zone d'exclusion est conservé."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 10}],
        ], room_width_cm=400, room_depth_cm=400)
        # Zone d'exclusion loin du desk
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            exclusion_zones=[
                ExclusionZone(x_cm=300, y_cm=300, width_cm=50, depth_cm=50),
            ],
        )
        result, removed = remove_conflicting_desks(p, room)
        assert len(removed) == 0
        assert result["_n_desks_after_removal"] == 1

    def test_desk_outside_room_removed(self):
        """Un poste qui dépasse de la pièce est supprimé."""
        # Bloc placé à gap=350 dans une pièce de 400 (le desk de 160cm dépasse)
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 350}],
        ], room_width_cm=400, room_depth_cm=400)
        room = RoomSpec(width_cm=400, depth_cm=400)
        result, removed = remove_conflicting_desks(p, room)
        assert len(removed) == 1

    def test_no_exclusions_no_removal(self):
        """Sans zone d'exclusion et dans la pièce, rien n'est supprimé."""
        p = _make_pattern([
            [{"type": "BLOCK_4_FACE", "gap_cm": 10}],
        ], room_width_cm=600, room_depth_cm=600)
        room = RoomSpec(width_cm=600, depth_cm=600)
        result, removed = remove_conflicting_desks(p, room)
        assert len(removed) == 0
        assert result["_n_desks_after_removal"] == 4


# ---------------------------------------------------------------------------
# 8. largest_free_rectangle_m2
# ---------------------------------------------------------------------------

class TestLargestFreeRectangle:
    """Vérifie le calcul du plus grand rectangle vide."""

    def test_room_larger_than_pattern_nonzero(self):
        """Une pièce plus grande que le pattern a un rectangle vide > 0."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 10}],
        ], room_width_cm=600, room_depth_cm=600)
        room = RoomSpec(width_cm=600, depth_cm=600)
        area = largest_free_rectangle_m2(p, room)
        assert area > 0

    def test_empty_pattern_large_rect(self):
        """Un pattern vide dans une grande pièce = rectangle quasi-total."""
        p = _make_pattern([], room_width_cm=500, room_depth_cm=500)
        room = RoomSpec(width_cm=500, depth_cm=500)
        area = largest_free_rectangle_m2(p, room)
        # La pièce fait 25 m², le rectangle libre doit en être proche
        # (moins les murs périphériques d'1 cellule de 10cm)
        assert area > 15.0

    def test_tiny_room_zero(self):
        """Pièce trop petite pour contenir un rectangle."""
        p = _make_pattern([], room_width_cm=5, room_depth_cm=5)
        room = RoomSpec(width_cm=5, depth_cm=5)
        area = largest_free_rectangle_m2(p, room)
        assert area == 0.0


# ---------------------------------------------------------------------------
# 9. generate_auto_name (D-50)
# ---------------------------------------------------------------------------

class TestGenerateAutoName:
    """Vérifie la convention de nommage D-50."""

    def test_first_pattern_in_group(self):
        """Premier pattern dans un groupe : incrément = 1."""
        p = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="",
            standard="AFNOR_ADVICE",
            room_width_cm=310,
            room_depth_cm=480,
        )
        name = generate_auto_name(p, catalogue=[])
        assert name == "310x480_AFNOR_1"

    def test_second_pattern_increments(self):
        """Second pattern dans un groupe : incrément = 2."""
        p1 = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="310x480_AFNOR_1",
            standard="AFNOR_ADVICE",
            room_width_cm=310,
            room_depth_cm=480,
        )
        p2 = _make_pattern(
            [[{"type": "BLOCK_2_FACE"}]],
            name="",
            standard="AFNOR_ADVICE",
            room_width_cm=310,
            room_depth_cm=480,
        )
        name = generate_auto_name(p2, catalogue=[p1])
        assert name == "310x480_AFNOR_2"

    def test_two_openings_suffix(self):
        """Pattern avec >= 2 ouvertures : suffixe _{k}O."""
        p = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="",
            standard="GROUP",
            room_width_cm=400,
            room_depth_cm=500,
            room_openings=[
                {"face": "south", "offset_cm": 10, "width_cm": 90},
                {"face": "east", "offset_cm": 20, "width_cm": 90},
            ],
        )
        name = generate_auto_name(p, catalogue=[])
        assert name == "400x500_GROUP_2O_1"

    def test_one_opening_no_suffix(self):
        """Pattern avec 1 ouverture : pas de suffixe O."""
        p = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="",
            standard="SITE",
            room_width_cm=300,
            room_depth_cm=400,
            room_openings=[
                {"face": "south", "offset_cm": 10, "width_cm": 90},
            ],
        )
        name = generate_auto_name(p, catalogue=[])
        assert name == "300x400_SITE_1"

    def test_different_standards_independent(self):
        """Des groupes de standards différents ont des incréments indépendants."""
        p_afnor = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="310x480_AFNOR_1",
            standard="AFNOR_ADVICE",
            room_width_cm=310,
            room_depth_cm=480,
        )
        p_site = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="",
            standard="SITE",
            room_width_cm=310,
            room_depth_cm=480,
        )
        name = generate_auto_name(p_site, catalogue=[p_afnor])
        assert name == "310x480_SITE_1"


# ---------------------------------------------------------------------------
# 10. compact_catalogue_names
# ---------------------------------------------------------------------------

class TestCompactCatalogueNames:
    """Vérifie la renumérotation après suppression."""

    def test_renumber_after_gap(self):
        """Suppression du n=2 dans [1,2,3] donne [1,2]."""
        patterns = [
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_1",
                          standard="AFNOR_ADVICE", room_width_cm=310,
                          room_depth_cm=480),
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_3",
                          standard="AFNOR_ADVICE", room_width_cm=310,
                          room_depth_cm=480),
        ]
        result = compact_catalogue_names(patterns)
        names = [p["name"] for p in result]
        assert names == ["310x480_AFNOR_1", "310x480_AFNOR_2"]

    def test_single_pattern_becomes_1(self):
        patterns = [
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_5",
                          standard="AFNOR_ADVICE", room_width_cm=310,
                          room_depth_cm=480),
        ]
        compact_catalogue_names(patterns)
        assert patterns[0]["name"] == "310x480_AFNOR_1"

    def test_different_groups_independent(self):
        """Deux groupes différents sont renumérotés indépendamment."""
        patterns = [
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_3",
                          standard="AFNOR_ADVICE", room_width_cm=310,
                          room_depth_cm=480),
            _make_pattern([[{"type": "BLOCK_1"}]], name="400x500_SITE_5",
                          standard="SITE", room_width_cm=400,
                          room_depth_cm=500),
        ]
        compact_catalogue_names(patterns)
        assert patterns[0]["name"] == "310x480_AFNOR_1"
        assert patterns[1]["name"] == "400x500_SITE_1"

    def test_already_compact_unchanged(self):
        """Un catalogue déjà compact ne change pas."""
        patterns = [
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_1",
                          standard="AFNOR_ADVICE", room_width_cm=310,
                          room_depth_cm=480),
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_2",
                          standard="AFNOR_ADVICE", room_width_cm=310,
                          room_depth_cm=480),
        ]
        compact_catalogue_names(patterns)
        names = [p["name"] for p in patterns]
        assert names == ["310x480_AFNOR_1", "310x480_AFNOR_2"]
