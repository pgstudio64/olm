import os
import json
import tempfile

from olm.core.pattern_generator import (
    BLOC_1, BLOC_2_FACE, BLOC_3_COTE, BLOC_4_FACE, BLOC_6_FACE,
    PASSAGE_CM, PASSAGE_SINGLE_CM, CHAIR_CLEARANCE_CM, DESK_D_CM, DESK_W_CM,
    compose_row, compose_double_row, FaceZone, DoubleRowPattern,
    export_catalogue, render_pattern_svg,
    rotate_pattern_90, rotate_double_row_90, mirror_double_row,
    PATTERNS, DOUBLE_ROW_PATTERNS, PATTERNS_ALL, DOUBLE_ROW_PATTERNS_ALL,
)


def test_bloc_1_passage_30cm():
    """BLOC_1 : passage accès poste seul = 30 cm (ES-03), pas 90 cm."""
    assert BLOC_1.eo_cm == DESK_W_CM
    assert BLOC_1.ns_cm == DESK_D_CM
    assert BLOC_1.n_desks == 1
    # W : débattement 70 cm + passage 30 cm = 100 cm
    assert BLOC_1.faces.west.non_superposable_cm == CHAIR_CLEARANCE_CM
    assert BLOC_1.faces.west.candidate_cm == PASSAGE_SINGLE_CM
    assert BLOC_1.faces.west.total_cm == 100
    # E : absent (côté écran)
    assert BLOC_1.faces.east == FaceZone.absent()


def test_bloc_2_face_dimensions():
    assert BLOC_2_FACE.eo_cm == 160
    assert BLOC_2_FACE.ns_cm == 180
    # E/W : zone fixe (70 cm) + zone min. circulation (90 cm) = 160 cm (ES-04)
    assert BLOC_2_FACE.faces.east.non_superposable_cm == CHAIR_CLEARANCE_CM
    assert BLOC_2_FACE.faces.east.candidate_cm == PASSAGE_CM
    assert BLOC_2_FACE.faces.west.total_cm == CHAIR_CLEARANCE_CM + PASSAGE_CM
    # N/S : absent (pas de fauteuil)
    assert BLOC_2_FACE.faces.north == FaceZone.absent()
    assert BLOC_2_FACE.faces.south == FaceZone.absent()


def test_single_bloc4_pattern():
    p = compose_row([BLOC_4_FACE], "test")
    assert p.physical_eo_cm == DESK_W_CM * 2
    assert p.physical_ns_cm == DESK_D_CM * 2
    # EO total = west(70+90) + 160 + east(70+90) = 480
    assert p.total_eo_cm == (CHAIR_CLEARANCE_CM + PASSAGE_CM) * 2 + DESK_W_CM * 2
    # NS total = north(0) + 360 + south(0) = 360 (N/S absents)
    assert p.total_ns_cm == DESK_D_CM * 2


def test_b6_b2f_pattern():
    p = compose_row([BLOC_6_FACE, BLOC_2_FACE], "test")
    assert p.physical_eo_cm == DESK_W_CM * 2 + DESK_W_CM * 2   # BLOC_6_FACE.eo + BLOC_2_FACE.eo
    assert p.n_desks == 8
    # EO total = west_B6(70+90) + 320 + east_B2F(70+90) = 640
    assert p.total_eo_cm == (CHAIR_CLEARANCE_CM + PASSAGE_CM) * 2 + DESK_W_CM * 4


def test_bloc6_derogatory():
    assert BLOC_6_FACE.derogatory is True
    assert BLOC_4_FACE.derogatory is False


def test_double_row_ns_total():
    p = compose_double_row([BLOC_4_FACE], [BLOC_4_FACE], "test")
    # 90 + 180 + 90 + 180 + 90 = 630
    assert p.total_ns_cm == 630


def test_double_row_central_corridor():
    p = compose_double_row([BLOC_4_FACE], [BLOC_4_FACE], "test")
    # ES-06 passage inter-blocs = 90 cm
    assert p.central_corridor_cm == 90


def test_double_row_desks():
    p = compose_double_row([BLOC_4_FACE, BLOC_2_FACE], [BLOC_4_FACE, BLOC_2_FACE], "test")
    assert p.n_desks == 12


def test_double_row_eo_asymmetric():
    # rangée nord plus large que sud → total_eo = max
    p = compose_double_row([BLOC_4_FACE, BLOC_2_FACE], [BLOC_4_FACE], "test")
    assert p.total_eo_cm == compose_double_row(
        [BLOC_4_FACE, BLOC_2_FACE], [BLOC_4_FACE, BLOC_2_FACE], "ref"
    ).north_row.total_eo_cm


def test_export_json_keys():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    export_catalogue(PATTERNS, DOUBLE_ROW_PATTERNS, path)
    with open(path) as f:
        data = json.load(f)
    assert "single_row" in data
    assert "double_row" in data
    assert data["double_row"][0]["central_corridor_cm"] == 90
    os.unlink(path)


def test_render_svg_creates_file():
    p = DOUBLE_ROW_PATTERNS[0]
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        path = f.name
    render_pattern_svg(p, path)
    content = open(path).read()
    assert "<svg" in content
    assert "4a90c4" in content   # zone candidate présente
    assert "d0d0d0" in content   # bureau présent
    os.unlink(path)


def test_rotate_pattern_90_dimensions():
    p = compose_row([BLOC_4_FACE], "P_B4")
    r = rotate_pattern_90(p)
    assert r.name == "P_B4__R90"
    assert r.orientation == 90
    assert r.physical_eo_cm == p.physical_ns_cm   # DESK_D_CM * 2 = 360
    assert r.physical_ns_cm == p.physical_eo_cm   # DESK_W_CM * 2 = 160
    # Après rotation 90° CW : W←N(absent), E←S(absent), N←W(70+90), S←E(70+90)
    # total_eo = west(0) + 360 + east(0) = 360
    assert r.total_eo_cm == DESK_D_CM * 2
    # total_ns = north.candidate_cm(90) + 160 + south.candidate_cm(90) = 340
    assert r.total_ns_cm == PASSAGE_CM * 2 + DESK_W_CM * 2


def test_mirror_double_row_asymmetric():
    p = compose_double_row([BLOC_4_FACE], [BLOC_4_FACE, BLOC_2_FACE], "P_B4_B4B2F")
    m = mirror_double_row(p)
    assert m is not None
    assert m.name == "P_B4_B4B2F__MIRROR"
    assert [b.name for b in m.north_row.blocks] == ["BLOC_4_FACE", "BLOC_2_FACE"]
    assert [b.name for b in m.south_row.blocks] == ["BLOC_4_FACE"]


def test_mirror_double_row_symmetric():
    p = compose_double_row([BLOC_4_FACE], [BLOC_4_FACE], "P_B4_B4")
    assert mirror_double_row(p) is None


def test_patterns_all_count():
    assert len(PATTERNS_ALL) == len(PATTERNS) * 2
    # P_B4_B4 symétrique → pas de miroir
    # P_B4_B4B2F asymétrique → 1 miroir
    # P_B4B2F_B4B2F symétrique → pas de miroir
    # P_B2F_B2F symétrique → pas de miroir
    # P_B2F_B4 asymétrique → 1 miroir
    # P_B4B2F_B4 asymétrique → 1 miroir
    assert len(DOUBLE_ROW_PATTERNS_ALL) == len(DOUBLE_ROW_PATTERNS) * 2 + 3


def test_render_svg_dark_background():
    p = DOUBLE_ROW_PATTERNS[0]
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        path = f.name
    render_pattern_svg(p, path)
    content = open(path).read()
    assert "1e1e1e" in content      # fond sombre
    assert "4a90c4" in content      # zone bleue
    assert "8B6914" in content      # fauteuil
    assert "1a1a1a" in content      # écran (standard visuel OLO)
    assert "porte" in content       # label porte sud
    os.unlink(path)
