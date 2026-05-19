import json
import os
import tempfile

from olm.core.pattern_generator import (
    BLOCK_1,
    BLOCK_2_FACE,
    BLOCK_2_ORTHO_L,
    BLOCK_2_ORTHO_R,
    BLOCK_4_FACE,
    BLOCK_6_FACE,
    CHAIR_CLEARANCE_CM,
    DESK_D_CM,
    DESK_W_CM,
    DOUBLE_ROW_PATTERNS,
    DOUBLE_ROW_PATTERNS_ALL,
    WALKING_MARGIN_CM,
    SLIP_IN_MARGIN_CM,
    PATTERNS,
    PATTERNS_ALL,
    FaceZone,
    compose_double_row,
    compose_row,
    export_catalogue,
    mirror_double_row,
    render_pattern_svg,
    rotate_pattern_90,
)


def test_bloc_1_chair_only():
    """BLOCK_1: chair clearance only on west face (D-229)."""
    assert BLOCK_1.eo_cm == DESK_D_CM
    assert BLOCK_1.ns_cm == DESK_W_CM
    assert BLOCK_1.n_desks == 1
    # W: chair clearance only, candidate=0
    assert BLOCK_1.faces.west.non_superposable_cm == CHAIR_CLEARANCE_CM
    assert BLOCK_1.faces.west.candidate_cm == 0
    assert BLOCK_1.faces.west.total_cm == CHAIR_CLEARANCE_CM
    # E: absent (screen side)
    assert BLOCK_1.faces.east == FaceZone.absent()


def test_bloc_2_face_dimensions():
    assert BLOCK_2_FACE.eo_cm == 160
    assert BLOCK_2_FACE.ns_cm == 180
    # E/W: chair clearance only, candidate=0 (D-229)
    assert BLOCK_2_FACE.faces.east.non_superposable_cm == CHAIR_CLEARANCE_CM
    assert BLOCK_2_FACE.faces.east.candidate_cm == 0
    assert BLOCK_2_FACE.faces.west.total_cm == CHAIR_CLEARANCE_CM
    # N/S: absent (no chair)
    assert BLOCK_2_FACE.faces.north == FaceZone.absent()
    assert BLOCK_2_FACE.faces.south == FaceZone.absent()


def test_single_bloc4_pattern():
    p = compose_row([BLOCK_4_FACE], "test")
    assert p.physical_eo_cm == DESK_D_CM * 2
    assert p.physical_ns_cm == DESK_W_CM * 2
    # EO total = west(70) + 160 + east(70) = 300 (D-229: candidate=0)
    assert p.total_eo_cm == CHAIR_CLEARANCE_CM * 2 + DESK_D_CM * 2
    # NS total = north(0) + 360 + south(0) = 360 (N/S absent)
    assert p.total_ns_cm == DESK_W_CM * 2


def test_b6_b2f_pattern():
    p = compose_row([BLOCK_6_FACE, BLOCK_2_FACE], "test")
    assert p.physical_eo_cm == DESK_D_CM * 2 + DESK_D_CM * 2
    assert p.n_desks == 8
    # EO total = west(70) + 320 + east(70) = 460 (D-229)
    assert p.total_eo_cm == CHAIR_CLEARANCE_CM * 2 + DESK_D_CM * 4



def test_bloc6_derogatory():
    assert BLOCK_6_FACE.derogatory is True
    assert BLOCK_4_FACE.derogatory is False


def test_double_row_ns_total():
    p = compose_double_row([BLOCK_4_FACE], [BLOCK_4_FACE], "test")
    # walking(90) + desk(80) + corridor(90) + desk(80) + walking(90) = 430
    assert p.total_ns_cm == (
        2 * WALKING_MARGIN_CM + 2 * DESK_D_CM + p.central_corridor_cm
    )


def test_double_row_central_corridor():
    p = compose_double_row([BLOCK_4_FACE], [BLOCK_4_FACE], "test")
    # ES-02 inter-row walking margin = 90 cm
    assert p.central_corridor_cm == 90


def test_double_row_desks():
    p = compose_double_row(
        [BLOCK_4_FACE, BLOCK_2_FACE],
        [BLOCK_4_FACE, BLOCK_2_FACE],
        "test",
    )
    assert p.n_desks == 12


def test_double_row_eo_asymmetric():
    # north row wider than south -> total_eo = max
    p = compose_double_row(
        [BLOCK_4_FACE, BLOCK_2_FACE], [BLOCK_4_FACE], "test",
    )
    assert p.total_eo_cm == compose_double_row(
        [BLOCK_4_FACE, BLOCK_2_FACE],
        [BLOCK_4_FACE, BLOCK_2_FACE],
        "ref",
    ).north_row.total_eo_cm


def test_export_json_keys():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    export_catalogue(PATTERNS, DOUBLE_ROW_PATTERNS, path)
    with open(path, encoding="utf-8") as f:
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
    content = open(path, encoding="utf-8").read()
    assert "<svg" in content
    assert "4a90c4" in content   # candidate zone present
    assert "d0d0d0" in content   # desk present
    os.unlink(path)


def test_rotate_pattern_90_dimensions():
    p = compose_row([BLOCK_4_FACE], "P_B4")
    r = rotate_pattern_90(p)
    assert r.name == "P_B4__R90"
    assert r.orientation == 90
    assert r.physical_eo_cm == p.physical_ns_cm   # DESK_W_CM * 2 = 360
    assert r.physical_ns_cm == p.physical_eo_cm   # DESK_D_CM * 2 = 160
    # After 90 CW: W<-N(absent), E<-S(absent), N<-W(70), S<-E(70)
    # total_eo = west(0) + 360 + east(0) = 360
    assert r.total_eo_cm == DESK_W_CM * 2
    # total_ns = north.candidate(0) + 160 + south.candidate(0) = 160
    # D-229: candidate_cm=0, so total_ns = physical only
    assert r.total_ns_cm == DESK_D_CM * 2


def test_mirror_double_row_asymmetric():
    p = compose_double_row(
        [BLOCK_4_FACE], [BLOCK_4_FACE, BLOCK_2_FACE], "P_B4_B4B2F",
    )
    m = mirror_double_row(p)
    assert m is not None
    assert m.name == "P_B4_B4B2F__MIRROR"
    assert [b.name for b in m.north_row.blocks] == [
        "BLOCK_4_FACE", "BLOCK_2_FACE",
    ]
    assert [b.name for b in m.south_row.blocks] == ["BLOCK_4_FACE"]


def test_mirror_double_row_symmetric():
    p = compose_double_row(
        [BLOCK_4_FACE], [BLOCK_4_FACE], "P_B4_B4",
    )
    assert mirror_double_row(p) is None


def test_patterns_all_count():
    assert len(PATTERNS_ALL) == len(PATTERNS) * 2
    assert len(DOUBLE_ROW_PATTERNS_ALL) == (
        len(DOUBLE_ROW_PATTERNS) * 2 + 3
    )


def test_render_svg_dark_background():
    p = DOUBLE_ROW_PATTERNS[0]
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        path = f.name
    render_pattern_svg(p, path)
    content = open(path, encoding="utf-8").read()
    assert "1e1e1e" in content      # dark background
    assert "4a90c4" in content      # blue zone
    assert "8B6914" in content      # chair
    assert "1a1a1a" in content      # screen (OLO visual standard)
    assert "door" in content         # south door label
    os.unlink(path)


# ---------------------------------------------------------------------------
# D-241: FaceZone internal flag
# ---------------------------------------------------------------------------


def test_face_zone_internal_outer_cm():
    """internal=True → outer_cm=0, total_cm unchanged."""
    fz = FaceZone(70, 0, internal=True)
    assert fz.total_cm == 70
    assert fz.outer_cm == 0


def test_face_zone_external_outer_cm():
    """internal=False (default) → outer_cm == total_cm."""
    fz = FaceZone(70, 0)
    assert not fz.internal
    assert fz.outer_cm == fz.total_cm == 70


def test_face_zone_chair_internal_classmethod():
    """chair_internal() → correct values."""
    fz = FaceZone.chair_internal()
    assert fz.non_superposable_cm == CHAIR_CLEARANCE_CM
    assert fz.candidate_cm == 0
    assert fz.internal is True
    assert fz.outer_cm == 0


def test_ortho_r_east_internal():
    """ORTHO_R: east face is internal (chair in void)."""
    assert BLOCK_2_ORTHO_R.faces.east.internal is True
    assert BLOCK_2_ORTHO_R.faces.east.outer_cm == 0
    assert BLOCK_2_ORTHO_R.faces.north.internal is False
    assert BLOCK_2_ORTHO_R.faces.north.outer_cm == CHAIR_CLEARANCE_CM


def test_ortho_l_west_internal():
    """ORTHO_L: west face is internal (chair in void)."""
    assert BLOCK_2_ORTHO_L.faces.west.internal is True
    assert BLOCK_2_ORTHO_L.faces.west.outer_cm == 0
    assert BLOCK_2_ORTHO_L.faces.north.internal is False
    assert BLOCK_2_ORTHO_L.faces.north.outer_cm == CHAIR_CLEARANCE_CM
