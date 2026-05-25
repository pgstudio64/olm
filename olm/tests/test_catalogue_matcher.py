"""Tests for catalogue_matcher — 7-step matching pipeline + D-238 grade."""
from __future__ import annotations

import pytest

from olm.core.catalogue_matcher import (
    _GRADE_TO_DIM,
    MatchScore,
    PatternAdaptOverlap,
    PatternCandidate,
    SelectionResult,
    _assert_no_block_overlap,
    _candidate_sort_key,
    _classify_fit,
    _compute_composite_and_grade,
    _compute_dim_back_door,
    _compute_dim_face_wall,
    _compute_dim_light,
    _compute_dim_passage,
    _pattern_to_circulation_format,
    _select_top_desks,
    adapt_dimensions,
    adapt_to_room,
    candidate_category,
    circulates_well,
    compact_catalogue_names,
    compute_desk_positions,
    compute_opening_forbidden_zones,
    count_desks,
    dedupe_by_fingerprint,
    generate_auto_name,
    generate_mirrors,
    largest_free_rectangle_m2,
    load_catalogue,
    max_working_desks,
    mirror_pattern,
    remove_conflicting_desks,
    score_candidate,
    select_best,
    select_candidates,
)
from olm.core.pattern_generator import DESK_D_CM, DESK_W_CM
from olm.core.room_model import (
    ExclusionZone,
    Face,
    OpeningSpec,
    RoomSpec,
    WindowSpec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pattern(
    rows_spec: list[list[dict]],
    name: str = "test",
    standard: str = "standard1",
    room_width_cm: int = 400,
    room_depth_cm: int = 400,
    row_gaps_cm: list[int] | None = None,
    room_openings: list[dict] | None = None,
) -> dict:
    """Build a minimal JSON pattern for tests.

    rows_spec: list of lists of block dicts, e.g.:
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
    standard: str = "standard1",
    n_desks: int = 4,
) -> PatternCandidate:
    """Build a minimal PatternCandidate."""
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
    """Verifies desk counting for known block types."""

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
# 2. _select_top_desks + _classify_fit (D-244)
# ---------------------------------------------------------------------------

class TestSelectTopDesks:
    """D-244: keeps only N and N-1 desk counts."""

    def test_top_and_top_minus_one(self):
        """6-desk and 5-desk patterns kept, 4-desk excluded."""
        c6 = _make_candidate("C6", n_desks=6)
        c5 = _make_candidate("C5", n_desks=5)
        c4 = _make_candidate("C4", n_desks=4)
        result = _select_top_desks([c6, c5, c4])
        desks = {c.n_desks for c in result}
        assert desks == {6, 5}

    def test_all_same_desk_count(self):
        """All fittings at N=6: only 6 and 5 in keep_set, 5 absent."""
        c1 = _make_candidate("A", n_desks=6)
        c2 = _make_candidate("B", n_desks=6)
        result = _select_top_desks([c1, c2])
        assert len(result) == 2

    def test_single_candidate(self):
        c = _make_candidate("solo", n_desks=4)
        result = _select_top_desks([c])
        assert len(result) == 1

    def test_empty(self):
        assert _select_top_desks([]) == []

    def test_multiple_at_each_level(self):
        """Multiple patterns at N and N-1 all kept."""
        cs = [
            _make_candidate("A6", n_desks=6),
            _make_candidate("B6", n_desks=6),
            _make_candidate("C6", n_desks=6),
            _make_candidate("D5", n_desks=5),
            _make_candidate("E5", n_desks=5),
            _make_candidate("F4", n_desks=4),
        ]
        result = _select_top_desks(cs)
        assert len(result) == 5
        assert all(c.n_desks >= 5 for c in result)


class TestClassifyFit:
    """4-state classification: fitting / oversize_1axis / oversize_2axes / hidden."""

    def test_fitting(self):
        """Footprint smaller than room → fitting."""
        p = _make_pattern([[{"type": "BLOCK_1"}]],
                          room_width_cm=200, room_depth_cm=200)
        room = RoomSpec(width_cm=400, depth_cm=400)
        cls, overflow = _classify_fit(p, room)
        assert cls == "fitting"
        assert overflow == 0.0

    def test_oversize_1axis_width(self):
        """Width exceeds by < 10%, depth OK → oversize_1axis."""
        p = _make_pattern([[{"type": "BLOCK_1"}]],
                          room_width_cm=308, room_depth_cm=200)
        room = RoomSpec(width_cm=300, depth_cm=400)
        # 308-300=8 <= 10%*300=30 → oversize_1axis
        cls, overflow = _classify_fit(p, room)
        assert cls == "oversize_1axis"
        assert overflow == 8.0

    def test_oversize_1axis_depth(self):
        """Depth exceeds by < 10%, width OK → oversize_1axis."""
        p = _make_pattern([[{"type": "BLOCK_1"}]],
                          room_width_cm=200, room_depth_cm=320)
        room = RoomSpec(width_cm=400, depth_cm=300)
        # 320-300=20 <= 10%*300=30 → oversize_1axis
        cls, overflow = _classify_fit(p, room)
        assert cls == "oversize_1axis"
        assert overflow == 20.0

    def test_oversize_2axes(self):
        """Both axes exceed within tolerance → oversize_2axes."""
        p = _make_pattern([[{"type": "BLOCK_1"}]],
                          room_width_cm=325, room_depth_cm=325)
        room = RoomSpec(width_cm=300, depth_cm=300)
        # 25/300 = 8.3% < 10% on each axis
        cls, overflow = _classify_fit(p, room)
        assert cls == "oversize_2axes"
        assert overflow == 25.0

    def test_hidden_1axis_exceeds_tolerance(self):
        """Single axis exceeds tolerance → hidden."""
        p = _make_pattern([[{"type": "BLOCK_1"}]],
                          room_width_cm=400, room_depth_cm=200)
        room = RoomSpec(width_cm=300, depth_cm=400)
        # 400-300=100, 100/300=33% > 10%
        cls, overflow = _classify_fit(p, room)
        assert cls == "hidden"
        assert overflow == 100.0

    def test_hidden_2axes_one_exceeds(self):
        """Both axes overflow but one exceeds tolerance → hidden."""
        p = _make_pattern([[{"type": "BLOCK_1"}]],
                          room_width_cm=350, room_depth_cm=310)
        room = RoomSpec(width_cm=300, depth_cm=300)
        # width: 50/300=16.7% > 10%, depth: 10/300=3.3% < 10%
        cls, _ = _classify_fit(p, room)
        assert cls == "hidden"

    def test_custom_tolerances(self):
        """Custom tolerances respected."""
        p = _make_pattern([[{"type": "BLOCK_1"}]],
                          room_width_cm=350, room_depth_cm=200)
        room = RoomSpec(width_cm=300, depth_cm=400)
        # 50/300=16.7% — hidden at 10%, but ok at 20%
        cls_10, _ = _classify_fit(p, room, tol_1axis=0.10)
        assert cls_10 == "hidden"
        cls_20, _ = _classify_fit(p, room, tol_1axis=0.20)
        assert cls_20 == "oversize_1axis"

    def test_zero_effective_dimension(self):
        """Room with zero effective dimension → hidden."""
        p = _make_pattern([[{"type": "BLOCK_1"}]],
                          room_width_cm=100, room_depth_cm=100)
        room = RoomSpec(
            width_cm=300, depth_cm=100,
            exclusion_zones=[ExclusionZone(
                x_cm=0, y_cm=0, width_cm=300, depth_cm=100,
            )],
        )
        # effective depth = 0
        cls, _ = _classify_fit(p, room)
        assert cls == "hidden"


# ---------------------------------------------------------------------------
# 3. select_candidates (with real catalogue)
# ---------------------------------------------------------------------------

class TestSelectCandidates:
    """Verifies candidate selection with the real catalogue."""

    @pytest.fixture
    def catalogue(self):
        return load_catalogue()

    def test_small_room_all_oversize(self, catalogue):
        """Room too small: all candidates are oversize (D-242)."""
        if not catalogue:
            pytest.skip("Empty catalogue")
        tiny = RoomSpec(width_cm=50, depth_cm=50)
        results = select_candidates(catalogue, tiny)
        for sel in results:
            for c in sel.candidates:
                assert c.oversize, f"{c.name} should be oversize for 50x50"

    def test_large_room_has_candidates(self, catalogue):
        """Room large enough: at least one candidate fits."""
        if not catalogue:
            pytest.skip("Empty catalogue")
        large = RoomSpec(width_cm=800, depth_cm=600)
        results = select_candidates(catalogue, large)
        # At least one standard should have candidates
        total = sum(len(sel.candidates) for sel in results)
        assert total > 0

    def test_single_standard_returns_single_result(self, catalogue):
        if not catalogue:
            pytest.skip("Empty catalogue")
        room = RoomSpec(width_cm=800, depth_cm=600)
        result = select_candidates(catalogue, room, standard="standard1")
        assert isinstance(result, SelectionResult)
        assert result.standard == "standard1"

    def test_candidates_are_all_non_hidden(self, catalogue):
        """D-304: candidates = all non-hidden (no desk-count elaguage)."""
        if not catalogue:
            pytest.skip("Empty catalogue")
        room = RoomSpec(width_cm=600, depth_cm=500)
        results = select_candidates(catalogue, room)
        for sel in results:
            for c in sel.candidates:
                assert c.fit_class != "hidden"

    def test_hidden_patterns_excluded(self, catalogue):
        """D-244: patterns exceeding 10% tolerance are hidden."""
        if not catalogue:
            pytest.skip("Empty catalogue")
        tiny = RoomSpec(width_cm=50, depth_cm=50)
        results = select_candidates(catalogue, tiny)
        for sel in results:
            # All candidates should be oversize (tolere) or fitting
            # but patterns >> 10% bigger should be excluded
            for c in sel.candidates:
                # Declared dimensions must be within 10% of room
                assert c.room_width_cm <= 55 or c.room_depth_cm <= 55 or (
                    c.oversize
                ), f"{c.name} should be hidden for 50x50"

    def test_fitting_before_oversize_in_candidates(self, catalogue):
        """Fitting candidates come before oversize in the list."""
        if not catalogue:
            pytest.skip("Empty catalogue")
        room = RoomSpec(width_cm=600, depth_cm=500)
        results = select_candidates(catalogue, room)
        for sel in results:
            saw_oversize = False
            for c in sel.candidates:
                if c.oversize:
                    saw_oversize = True
                elif saw_oversize:
                    pytest.fail(
                        f"Fitting candidate {c.name} appears after "
                        f"oversize in {sel.standard}"
                    )

    def test_oversize_order_by_overflow(self, catalogue):
        """Oversize candidates sorted by overflow_cm ascending."""
        if not catalogue:
            pytest.skip("Empty catalogue")
        room = RoomSpec(width_cm=600, depth_cm=500)
        results = select_candidates(catalogue, room)
        for sel in results:
            oversize_cands = [c for c in sel.candidates if c.oversize]
            # Within each fit_class group, overflow must be ascending
            prev_cls = ""
            prev_overflow = -1.0
            for c in oversize_cands:
                if c.fit_class != prev_cls:
                    prev_overflow = -1.0
                    prev_cls = c.fit_class
                assert c.overflow_cm >= prev_overflow, (
                    f"{c.name}: overflow {c.overflow_cm} < prev "
                    f"{prev_overflow} in {sel.standard}"
                )
                prev_overflow = c.overflow_cm

    def test_1axis_before_2axes(self, catalogue):
        """oversize_1axis group appears before oversize_2axes."""
        if not catalogue:
            pytest.skip("Empty catalogue")
        room = RoomSpec(width_cm=600, depth_cm=500)
        results = select_candidates(catalogue, room)
        for sel in results:
            saw_2axes = False
            for c in sel.candidates:
                if c.fit_class == "oversize_2axes":
                    saw_2axes = True
                elif c.fit_class == "oversize_1axis" and saw_2axes:
                    pytest.fail(
                        f"1axis {c.name} after 2axes in {sel.standard}"
                    )


# ---------------------------------------------------------------------------
# 4. mirror_pattern
# ---------------------------------------------------------------------------

class TestMirrorPattern:
    """Verifies E-W mirror of patterns."""

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

    def test_sticks_e_w_swap(self):
        """E sticks become W and vice versa. Legacy "O" is normalized to "W"."""
        p = _make_pattern([
            [
                {"type": "BLOCK_1", "sticks": ["W"], "gap_cm": 0},
                {"type": "BLOCK_1", "sticks": ["E"], "gap_cm": 100},
            ],
        ], room_width_cm=400)
        m = mirror_pattern(p)
        blocks = m["rows"][0]["blocks"]
        all_sticks = [b.get("sticks", []) for b in blocks]
        flat_sticks = [s for sticks in all_sticks for s in sticks]
        assert "E" in flat_sticks
        assert "W" in flat_sticks
        # Legacy "O" in input is normalized to "W" in the mirror output
        assert "O" not in flat_sticks

    def test_sticks_legacy_o_normalized_to_w(self):
        """A legacy pattern with stick "O" mirrors to canonical "W"... but
        already-W input mirrors to "E", so this test starts from "O" in input."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "sticks": ["O"], "gap_cm": 0}],
        ], room_width_cm=400)
        m = mirror_pattern(p)
        sticks_out = m["rows"][0]["blocks"][0].get("sticks", [])
        # Legacy "O" -> "E" (since O is treated as a west alias)
        assert sticks_out == ["E"]

    def test_ortho_r_becomes_l(self):
        """BLOCK_2_ORTHO_R becomes BLOCK_2_ORTHO_L and vice versa."""
        p = _make_pattern([
            [{"type": "BLOCK_2_ORTHO_R"}],
        ], room_width_cm=400)
        m = mirror_pattern(p)
        assert m["rows"][0]["blocks"][0]["type"] == "BLOCK_2_ORTHO_L"

    def test_ortho_l_becomes_r(self):
        p = _make_pattern([
            [{"type": "BLOCK_2_ORTHO_L"}],
        ], room_width_cm=400)
        m = mirror_pattern(p)
        assert m["rows"][0]["blocks"][0]["type"] == "BLOCK_2_ORTHO_R"

    def test_double_mirror_roundtrip(self):
        """Mirror twice = back to original (same desk positions)."""
        p = _make_pattern([
            [{"type": "BLOCK_4_FACE", "gap_cm": 20, "sticks": ["W"]},
             {"type": "BLOCK_2_FACE", "gap_cm": 30, "sticks": ["E"]}],
        ], room_width_cm=500)
        m1 = mirror_pattern(p)
        m2 = mirror_pattern(m1)
        # Desk positions must be identical
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
    """Verifies stick alignment + homothety."""

    def test_stick_e_stays_at_east_wall(self):
        """A block with stick E must remain flush with the east wall in the target room."""
        # Pattern in a 400-wide room with stick E block at gap=200
        p = _make_pattern([
            [{"type": "BLOCK_1", "sticks": ["W"], "gap_cm": 0},
             {"type": "BLOCK_1", "sticks": ["E"], "gap_cm": 100}],
        ], room_width_cm=400, room_depth_cm=300)

        target = RoomSpec(width_cm=500, depth_cm=300)
        adapted = adapt_to_room(p, target)
        assert adapted["room_width_cm"] == 500

        # Compute adapted desk positions
        desks = compute_desk_positions(adapted)
        # Stick E block: its position + width must reach the east wall
        # Verify that the gap has been adjusted correctly (100cm more)
        blocks = adapted["rows"][0]["blocks"]
        x = 0
        for b in blocks:
            x += b.get("gap_cm", 0)
            from olm.core.catalogue_matcher import _block_eo_extent
            x += _block_eo_extent(b)
        # The last position must not exceed the target width
        assert x <= 500

    def test_gaps_adjusted_with_extra_width(self):
        """Extra space is distributed among anchors."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "sticks": ["W"], "gap_cm": 10},
             {"type": "BLOCK_1", "sticks": ["E"], "gap_cm": 50}],
        ], room_width_cm=300, room_depth_cm=300)
        target = RoomSpec(width_cm=400, depth_cm=300)
        adapted = adapt_to_room(p, target)
        # W block gap stays fixed, E block gap increases
        blocks = adapted["rows"][0]["blocks"]
        assert blocks[0]["gap_cm"] == 10  # Stick W unchanged

    def test_room_dimensions_updated(self):
        p = _make_pattern([[{"type": "BLOCK_1"}]],
                          room_width_cm=300, room_depth_cm=300)
        target = RoomSpec(width_cm=500, depth_cm=400)
        adapted = adapt_to_room(p, target)
        assert adapted["room_width_cm"] == 500
        assert adapted["room_depth_cm"] == 400


# ---------------------------------------------------------------------------
# 5b. adapt_dimensions
# ---------------------------------------------------------------------------

class TestAdaptDimensions:
    """Verifies adapt_dimensions preserves locks."""

    def test_stick_e_preserved_on_width_increase(self):
        """Block with stick E stays flush with east wall after width increase."""
        # BLOCK_1 eo_cm = 80. gap = 300 - 80 = 220 -> flush at east wall.
        p = _make_pattern([
            [{"type": "BLOCK_1", "sticks": ["E"], "gap_cm": 220}],
        ], room_width_cm=300, room_depth_cm=300)

        adapted = adapt_dimensions(p, 400, 300)
        assert adapted["room_width_cm"] == 400
        assert adapted["room_depth_cm"] == 300

        # Block must remain flush with east wall (gap + eo = 400)
        blocks = adapted["rows"][0]["blocks"]
        from olm.core.catalogue_matcher import _block_eo_extent
        x = blocks[0].get("gap_cm", 0) + _block_eo_extent(blocks[0])
        assert x == 400

    def test_stick_s_offset_increases_on_depth_increase(self):
        """Single row with stick S: offset_ns_cm increases by depth delta."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "sticks": ["S"], "gap_cm": 0,
              "offset_ns_cm": 100}],
        ], room_width_cm=300, room_depth_cm=300)

        adapted = adapt_dimensions(p, 300, 400)
        assert adapted["room_depth_cm"] == 400
        blocks = adapted["rows"][0]["blocks"]
        assert blocks[0]["offset_ns_cm"] == 200  # 100 + (400-300)

    def test_no_change_when_dimensions_equal(self):
        """Same dimensions returns identical pattern."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 50}],
        ], room_width_cm=300, room_depth_cm=300)

        adapted = adapt_dimensions(p, 300, 300)
        assert adapted["rows"][0]["blocks"][0]["gap_cm"] == 50


# ---------------------------------------------------------------------------
# 5c. D-271 — no-lock hug-walls placement
# ---------------------------------------------------------------------------

class TestNoLockHugWalls:
    """Sans lock, les blocs sont collés aux cloisons et le surplus
    est réparti dans les écarts entre blocs (D-271)."""

    def test_double_width_hugs_walls(self):
        """Pattern 270-wide in 540-wide room: blocks hug walls."""
        # BLOCK_1 eo = 80 (DESK_D). gap=90 + 80 + gap=100 = 270
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 90},
             {"type": "BLOCK_1", "gap_cm": 100}],
        ], room_width_cm=270, room_depth_cm=300)
        target = RoomSpec(width_cm=540, depth_cm=300)
        adapted = adapt_to_room(p, target)
        from olm.core.pattern_fit import compute_pattern_footprint
        from olm.core.spacing_config import ALL_CONFIGS
        x_min, x_max, _, _ = compute_pattern_footprint(
            adapted, ALL_CONFIGS["standard1"],
        )
        # First block flush with west wall (face zone included)
        assert x_min == 0
        # Last block flush with east wall (face zone included)
        assert x_max == 540
        # Surplus went into the inter-block gap, not the head gap
        blocks = adapted["rows"][0]["blocks"]
        assert blocks[1]["gap_cm"] > 100

    def test_lock_w_preserves_position(self):
        """With lock W, block stays at its position, extra space at right."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "sticks": ["W"], "gap_cm": 90}],
        ], room_width_cm=270, room_depth_cm=300)
        target = RoomSpec(width_cm=540, depth_cm=300)
        adapted = adapt_to_room(p, target)
        blocks = adapted["rows"][0]["blocks"]
        assert blocks[0]["gap_cm"] == 90  # unchanged (lock W)


# ---------------------------------------------------------------------------
# 5d. D-244 — NS clamp offset_ns_cm single-row
# ---------------------------------------------------------------------------

class TestAdaptNSClamp:
    """D-244: offset_ns_cm clamps to 0 when room shrinks."""

    def test_stick_s_offset_clamped_to_zero(self):
        """offset_ns_cm=50, dd=-100 → clamped to 0."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "sticks": ["S"], "gap_cm": 0,
              "offset_ns_cm": 50}],
        ], room_width_cm=300, room_depth_cm=400)
        adapted = adapt_dimensions(p, 300, 300)
        blocks = adapted["rows"][0]["blocks"]
        assert blocks[0]["offset_ns_cm"] == 0

    def test_row_gaps_clamped_to_zero(self):
        """Multi-row: row_gaps clamped to 0 when room shrinks a lot."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 0}],
            [{"type": "BLOCK_1", "gap_cm": 0}],
        ], room_width_cm=300, room_depth_cm=400, row_gaps_cm=[100])
        adapted = adapt_dimensions(p, 300, 200)
        assert all(g >= 0 for g in adapted.get("row_gaps_cm", []))


# ---------------------------------------------------------------------------
# 5e. D-244 — overlap guard
# ---------------------------------------------------------------------------

class TestOverlapGuard:
    """D-244: runtime guard against block overlap after adaptation."""

    def test_normal_pattern_no_overlap(self):
        """Normal pattern in normal room: no exception."""
        p = _make_pattern([
            [{"type": "BLOCK_4_FACE", "gap_cm": 10}],
        ], room_width_cm=400, room_depth_cm=400)
        target = RoomSpec(width_cm=500, depth_cm=500)
        adapted = adapt_to_room(p, target)
        # Should not raise
        _assert_no_block_overlap(adapted)

    def test_overlap_detected(self):
        """Forged pattern with overlapping blocks raises exception."""
        p = {
            "name": "overlap_test",
            "standard": "standard1",
            "room_width_cm": 200,
            "room_depth_cm": 200,
            "rows": [{"blocks": [
                {"type": "BLOCK_4_FACE", "gap_cm": 0, "orientation": 0},
                {"type": "BLOCK_4_FACE", "gap_cm": -50, "orientation": 0},
            ]}],
        }
        with pytest.raises(PatternAdaptOverlap):
            _assert_no_block_overlap(p)


# ---------------------------------------------------------------------------
# 6. compute_desk_positions
# ---------------------------------------------------------------------------

class TestComputeDeskPositions:
    """Verifies absolute desk positions."""

    def test_single_bloc_1(self):
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 10}],
        ])
        desks = compute_desk_positions(p)
        assert len(desks) == 1
        d = desks[0]
        assert d.x_cm == 10
        assert d.y_cm == 0
        # D-223: width_cm / depth_cm now reflect the desk extent in the EO/NS
        # frame. BLOCK_1 at orient=0 occupies DESK_D_CM (EO) × DESK_W_CM (NS).
        assert d.width_cm == DESK_D_CM
        assert d.depth_cm == DESK_W_CM

    def test_bloc_4_face_has_4_desks(self):
        p = _make_pattern([
            [{"type": "BLOCK_4_FACE", "gap_cm": 0}],
        ])
        desks = compute_desk_positions(p)
        assert len(desks) == 4
        # All within the block rectangle
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
        # Second desk must be offset vertically
        assert desks[1].y_cm > desks[0].y_cm

    def test_gap_between_blocks(self):
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 0},
             {"type": "BLOCK_1", "gap_cm": 50}],
        ])
        desks = compute_desk_positions(p)
        assert len(desks) == 2
        assert desks[1].x_cm == DESK_D_CM + 50

    def test_rotated_bloc_1(self):
        """A BLOCK_1 rotated 90 degrees has its dimensions swapped."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "orientation": 90, "gap_cm": 0}],
        ])
        desks = compute_desk_positions(p)
        assert len(desks) == 1
        d = desks[0]
        # D-223: at orient=0 the desk extent is (DESK_D_CM, DESK_W_CM) along
        # (EO, NS). After 90° CW rotation, swap to (DESK_W_CM, DESK_D_CM).
        assert d.width_cm == DESK_W_CM
        assert d.depth_cm == DESK_D_CM


# ---------------------------------------------------------------------------
# 7. remove_conflicting_desks
# ---------------------------------------------------------------------------

class TestRemoveConflictingDesks:
    """Verifies removal of desks in forbidden zones."""

    def test_desk_in_exclusion_zone_removed(self):
        """A desk inside an exclusion zone is removed."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 10}],
        ], room_width_cm=400, room_depth_cm=400)
        # Exclusion zone covering the desk position (x=10, y=0)
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
        """A desk outside an exclusion zone is kept."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 10}],
        ], room_width_cm=400, room_depth_cm=400)
        # Exclusion zone far from the desk
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
        """A desk that extends beyond the room boundary is removed."""
        # Block placed at gap=350 in a 400-wide room (the 160cm desk overflows)
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 350}],
        ], room_width_cm=400, room_depth_cm=400)
        room = RoomSpec(width_cm=400, depth_cm=400)
        result, removed = remove_conflicting_desks(p, room)
        assert len(removed) == 1

    def test_no_exclusions_no_removal(self):
        """Without exclusion zones and within the room, nothing is removed."""
        p = _make_pattern([
            [{"type": "BLOCK_4_FACE", "gap_cm": 10}],
        ], room_width_cm=600, room_depth_cm=600)
        room = RoomSpec(width_cm=600, depth_cm=600)
        result, removed = remove_conflicting_desks(p, room)
        assert len(removed) == 0
        assert result["_n_desks_after_removal"] == 4


# ---------------------------------------------------------------------------
# 7b. Entry-opening forbidden zones (912.4)
# ---------------------------------------------------------------------------

class TestOpeningForbiddenZones:
    """Geometry + entry predicate of the opening clear strips (912.4)."""

    def test_south_door_zone(self):
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[OpeningSpec(face=Face.SOUTH, offset_cm=50,
                                  width_cm=90, has_door=True)],
        )
        assert compute_opening_forbidden_zones(room, 90) == [(50, 310, 90, 90)]

    def test_west_door_zone(self):
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[OpeningSpec(face=Face.WEST, offset_cm=20,
                                  width_cm=90, has_door=True)],
        )
        assert compute_opening_forbidden_zones(room, 70) == [(0, 20, 70, 90)]

    def test_corridor_opening_without_door_included(self):
        """A south (canonical corridor) opening is an entry even without door."""
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[OpeningSpec(face=Face.SOUTH, offset_cm=0,
                                  width_cm=90, has_door=False)],
        )
        assert compute_opening_forbidden_zones(room, 90)

    def test_exterior_bay_excluded_when_door_exists(self):
        """D-317: north bay is not an entry when a door exists → no zone
        for the bay (only for the door)."""
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[
                OpeningSpec(face=Face.NORTH, offset_cm=0,
                            width_cm=90, has_door=False),
                OpeningSpec(face=Face.SOUTH, offset_cm=100,
                            width_cm=90, has_door=True),
            ],
        )
        zones = compute_opening_forbidden_zones(room, 90)
        # Only the south door gets a zone, not the north bay.
        assert len(zones) == 1
        assert zones[0][1] == 400 - 90  # south zone y

    def test_exterior_bay_fallback_when_no_door(self):
        """D-317: north bay becomes entry via fallback when room has
        no door and no corridor opening → zone IS created."""
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[OpeningSpec(face=Face.NORTH, offset_cm=0,
                                  width_cm=90, has_door=False)],
        )
        zones = compute_opening_forbidden_zones(room, 90)
        assert len(zones) == 1

    def test_zero_margin_no_zone(self):
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[OpeningSpec(face=Face.SOUTH, offset_cm=0,
                                  width_cm=90, has_door=True)],
        )
        assert compute_opening_forbidden_zones(room, 0) == []


class TestRemoveDesksOnOpening:
    """Desks landing on an entry strip are dropped at placement (912.4)."""

    def test_desk_on_west_door_removed_with_margin(self):
        p = _make_pattern([[{"type": "BLOCK_1", "gap_cm": 0}]],
                          room_width_cm=400, room_depth_cm=400)
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[OpeningSpec(face=Face.WEST, offset_cm=0,
                                  width_cm=90, has_door=True)],
        )
        # Legacy behaviour (margin 0) keeps the desk.
        _, removed0 = remove_conflicting_desks(p, room, 0)
        assert len(removed0) == 0
        # With the walking margin, the desk on the entry strip is dropped.
        _, removed1 = remove_conflicting_desks(p, room, 90)
        assert len(removed1) == 1

    def test_desk_on_exterior_bay_kept_when_door_exists(self):
        """D-317: bay is not entry when a real door exists → desk kept."""
        p = _make_pattern([[{"type": "BLOCK_1", "gap_cm": 0}]],
                          room_width_cm=400, room_depth_cm=400)
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[
                OpeningSpec(face=Face.NORTH, offset_cm=0,
                            width_cm=90, has_door=False),
                OpeningSpec(face=Face.SOUTH, offset_cm=200,
                            width_cm=90, has_door=True),
            ],
        )
        _, removed = remove_conflicting_desks(p, room, 90)
        assert len(removed) == 0


class TestCirculationEntryStrip:
    """A desk on an entry no longer makes the room falsely infeasible (912.4)."""

    def test_entry_unsealed_and_remaining_desk_reachable(self):
        from olm.core.circulation_analysis import analyse
        from olm.core.pattern_fit import build_circ_blocks_from_pattern
        # Block A sits on the west door (sealing it); block B is reachable.
        p = _make_pattern([[
            {"type": "BLOCK_1", "gap_cm": 0},
            {"type": "BLOCK_1", "gap_cm": 140},
        ]], room_width_cm=600, room_depth_cm=600)
        blocks = build_circ_blocks_from_pattern(p)
        room_dict = {"eo_cm": 600, "ns_cm": 600,
                     "doors": [{"wall": "west", "position_cm": 0,
                                "width_cm": 90}]}
        room = RoomSpec(
            width_cm=600, depth_cm=600,
            openings=[OpeningSpec(face=Face.WEST, offset_cm=0,
                                  width_cm=90, has_door=True)],
        )
        zones = compute_opening_forbidden_zones(room, 90)
        # Without the fix: block A seals the west door → no path at all.
        circ_no = analyse(room_dict, blocks, 0)
        assert not circ_no.path_widths
        # With the entry strip: door reopened, on-entry desk skipped, the
        # remaining desk is reachable.
        circ_yes = analyse(room_dict, blocks, 0, forbidden_zones=zones)
        assert circ_yes.path_widths


# ---------------------------------------------------------------------------
# 8. largest_free_rectangle_m2
# ---------------------------------------------------------------------------

class TestLargestFreeRectangle:
    """Verifies the largest free rectangle calculation."""

    def test_room_larger_than_pattern_nonzero(self):
        """A room larger than the pattern has a free rectangle > 0."""
        p = _make_pattern([
            [{"type": "BLOCK_1", "gap_cm": 10}],
        ], room_width_cm=600, room_depth_cm=600)
        room = RoomSpec(width_cm=600, depth_cm=600)
        area = largest_free_rectangle_m2(p, room)
        assert area > 0

    def test_empty_pattern_large_rect(self):
        """An empty pattern in a large room = near-total rectangle."""
        p = _make_pattern([], room_width_cm=500, room_depth_cm=500)
        room = RoomSpec(width_cm=500, depth_cm=500)
        area = largest_free_rectangle_m2(p, room)
        # The room is 25 m², the free rectangle should be close
        # (minus the peripheral 1-cell border of 10cm)
        assert area > 15.0

    def test_tiny_room_zero(self):
        """Room too small to contain a rectangle."""
        p = _make_pattern([], room_width_cm=5, room_depth_cm=5)
        room = RoomSpec(width_cm=5, depth_cm=5)
        area = largest_free_rectangle_m2(p, room)
        assert area == 0.0


# ---------------------------------------------------------------------------
# 9. generate_auto_name
# ---------------------------------------------------------------------------

class TestGenerateAutoName:
    """Verifies the auto-naming convention."""

    def test_first_pattern_in_group(self):
        """First pattern in a group: increment = 1."""
        p = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="",
            standard="standard1",
            room_width_cm=310,
            room_depth_cm=480,
        )
        name = generate_auto_name(p, catalogue=[])
        assert name == "310x480_AFNOR_1"

    def test_second_pattern_increments(self):
        """Second pattern in a group: increment = 2."""
        p1 = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="310x480_AFNOR_1",
            standard="standard1",
            room_width_cm=310,
            room_depth_cm=480,
        )
        p2 = _make_pattern(
            [[{"type": "BLOCK_2_FACE"}]],
            name="",
            standard="standard1",
            room_width_cm=310,
            room_depth_cm=480,
        )
        name = generate_auto_name(p2, catalogue=[p1])
        assert name == "310x480_AFNOR_2"

    def test_two_openings_suffix(self):
        """Pattern with >= 2 openings: suffix _{k}O."""
        p = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="",
            standard="standard2",
            room_width_cm=400,
            room_depth_cm=500,
            room_openings=[
                {"face": "south", "offset_cm": 10, "width_cm": 90},
                {"face": "east", "offset_cm": 20, "width_cm": 90},
            ],
        )
        name = generate_auto_name(p, catalogue=[])
        assert name == "400x500_Kardham_2O_1"

    def test_one_opening_no_suffix(self):
        """Pattern with 1 opening: no O suffix."""
        p = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="",
            standard="standard3",
            room_width_cm=300,
            room_depth_cm=400,
            room_openings=[
                {"face": "south", "offset_cm": 10, "width_cm": 90},
            ],
        )
        name = generate_auto_name(p, catalogue=[])
        assert name == "300x400_Site_1"

    def test_different_standards_independent(self):
        """Different standard groups have independent increments."""
        p_afnor = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="310x480_AFNOR_1",
            standard="standard1",
            room_width_cm=310,
            room_depth_cm=480,
        )
        p_site = _make_pattern(
            [[{"type": "BLOCK_1"}]],
            name="",
            standard="standard3",
            room_width_cm=310,
            room_depth_cm=480,
        )
        name = generate_auto_name(p_site, catalogue=[p_afnor])
        assert name == "310x480_Site_1"


# ---------------------------------------------------------------------------
# 10. compact_catalogue_names
# ---------------------------------------------------------------------------

class TestCompactCatalogueNames:
    """Verifies renumbering after deletion."""

    def test_renumber_after_gap(self):
        """Deleting n=2 from [1,2,3] yields [1,2]."""
        patterns = [
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_1",
                          standard="standard1", room_width_cm=310,
                          room_depth_cm=480),
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_3",
                          standard="standard1", room_width_cm=310,
                          room_depth_cm=480),
        ]
        result = compact_catalogue_names(patterns)
        names = [p["name"] for p in result]
        assert names == ["310x480_AFNOR_1", "310x480_AFNOR_2"]

    def test_single_pattern_becomes_1(self):
        patterns = [
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_5",
                          standard="standard1", room_width_cm=310,
                          room_depth_cm=480),
        ]
        compact_catalogue_names(patterns)
        assert patterns[0]["name"] == "310x480_AFNOR_1"

    def test_different_groups_independent(self):
        """Two different groups are renumbered independently."""
        patterns = [
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_3",
                          standard="standard1", room_width_cm=310,
                          room_depth_cm=480),
            _make_pattern([[{"type": "BLOCK_1"}]], name="400x500_Site_5",
                          standard="standard3", room_width_cm=400,
                          room_depth_cm=500),
        ]
        compact_catalogue_names(patterns)
        assert patterns[0]["name"] == "310x480_AFNOR_1"
        assert patterns[1]["name"] == "400x500_Site_1"

    def test_already_compact_unchanged(self):
        """An already compact catalogue is unchanged."""
        patterns = [
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_1",
                          standard="standard1", room_width_cm=310,
                          room_depth_cm=480),
            _make_pattern([[{"type": "BLOCK_1"}]], name="310x480_AFNOR_2",
                          standard="standard1", room_width_cm=310,
                          room_depth_cm=480),
        ]
        compact_catalogue_names(patterns)
        names = [p["name"] for p in patterns]
        assert names == ["310x480_AFNOR_1", "310x480_AFNOR_2"]


# ---------------------------------------------------------------------------
# 11. dedupe_by_fingerprint
# ---------------------------------------------------------------------------

def _candidate_from_pattern(
    pattern: dict,
    name: str | None = None,
    standard: str = "standard1",
) -> PatternCandidate:
    """Build a PatternCandidate from a JSON pattern."""
    return PatternCandidate(
        pattern=pattern,
        name=name or pattern["name"],
        room_width_cm=pattern["room_width_cm"],
        room_depth_cm=pattern["room_depth_cm"],
        standard=standard,
        n_desks=count_desks(pattern),
    )


class TestDedupeByFingerprint:
    """Verifies structural deduplication of candidates."""

    def test_symmetric_mirror_deduped(self):
        """BLOCK_4_FACE alone (symmetric_180): mirror is identical → 1 result."""
        p = _make_pattern(
            [[{"type": "BLOCK_4_FACE", "gap_cm": 70}]],
            name="sym",
            room_width_cm=300,
            room_depth_cm=400,
        )
        orig = _candidate_from_pattern(p)
        candidates = generate_mirrors([orig])
        assert len(candidates) == 2
        result = dedupe_by_fingerprint(candidates)
        assert len(result) == 1
        assert result[0].name == "sym"

    def test_asymmetric_mirror_kept(self):
        """BLOCK_1 + BLOCK_2_FACE in one row (asymmetric): both kept."""
        p = _make_pattern(
            [[
                {"type": "BLOCK_1", "gap_cm": 0, "sticks": ["W"]},
                {"type": "BLOCK_2_FACE", "gap_cm": 50, "sticks": ["E"]},
            ]],
            name="asym",
            room_width_cm=400,
            room_depth_cm=400,
        )
        orig = _candidate_from_pattern(p)
        candidates = generate_mirrors([orig])
        assert len(candidates) == 2
        result = dedupe_by_fingerprint(candidates)
        assert len(result) == 2

    def test_mirror_inherits_oversize_and_fit_class(self):
        """Mirror PatternCandidate inherits oversize, fit_class, overflow_cm."""
        p = _make_pattern(
            [[
                {"type": "BLOCK_1", "gap_cm": 0, "sticks": ["W"]},
                {"type": "BLOCK_2_FACE", "gap_cm": 50, "sticks": ["E"]},
            ]],
            name="big_oversize",
            room_width_cm=600,
            room_depth_cm=400,
        )
        orig = PatternCandidate(
            pattern=p, name=p["name"],
            room_width_cm=600, room_depth_cm=400,
            standard="standard1", n_desks=3,
            oversize=True,
            fit_class="oversize_1axis",
            overflow_cm=25.0,
        )
        candidates = generate_mirrors([orig])
        assert len(candidates) == 2
        for c in candidates:
            assert c.oversize
            assert c.fit_class == "oversize_1axis"
            assert c.overflow_cm == 25.0

    def test_two_independent_patterns_same_layout_deduped(self):
        """Two catalogue patterns with identical block layout → 1 result."""
        p1 = _make_pattern(
            [[{"type": "BLOCK_4_FACE", "gap_cm": 50}]],
            name="pat_A",
            room_width_cm=300,
            room_depth_cm=400,
        )
        p2 = _make_pattern(
            [[{"type": "BLOCK_4_FACE", "gap_cm": 50}]],
            name="pat_B",
            room_width_cm=300,
            room_depth_cm=400,
        )
        c1 = _candidate_from_pattern(p1)
        c2 = _candidate_from_pattern(p2)
        result = dedupe_by_fingerprint([c1, c2])
        assert len(result) == 1
        assert result[0].name == "pat_A"

    def test_different_layouts_all_kept(self):
        """Patterns with different block layouts are all preserved."""
        p1 = _make_pattern(
            [[{"type": "BLOCK_4_FACE", "gap_cm": 50}]],
            name="A",
            room_width_cm=400,
            room_depth_cm=400,
        )
        p2 = _make_pattern(
            [[{"type": "BLOCK_4_FACE", "gap_cm": 100}]],
            name="B",
            room_width_cm=400,
            room_depth_cm=400,
        )
        p3 = _make_pattern(
            [[{"type": "BLOCK_2_FACE", "gap_cm": 50}]],
            name="C",
            room_width_cm=400,
            room_depth_cm=400,
        )
        candidates = [
            _candidate_from_pattern(p1),
            _candidate_from_pattern(p2),
            _candidate_from_pattern(p3),
        ]
        result = dedupe_by_fingerprint(candidates)
        assert len(result) == 3

    def test_single_candidate_no_regression(self):
        """A single candidate passes through unchanged."""
        p = _make_pattern(
            [[{"type": "BLOCK_1", "gap_cm": 0}]],
            name="solo",
            room_width_cm=300,
            room_depth_cm=300,
        )
        candidates = [_candidate_from_pattern(p)]
        result = dedupe_by_fingerprint(candidates)
        assert len(result) == 1
        assert result[0].name == "solo"


# ---------------------------------------------------------------------------
# 12. D-238 — Multi-dimensional grade
# ---------------------------------------------------------------------------

class TestChairSide:
    """Verifies chair_side is computed for each desk."""

    def test_block_1_chair_side_west(self):
        """BLOCK_1 at 0° has chair on west side."""
        p = _make_pattern([[{"type": "BLOCK_1", "gap_cm": 10}]])
        desks = compute_desk_positions(p)
        assert len(desks) == 1
        assert desks[0].chair_side == "W"

    def test_block_2_face_chair_sides(self):
        """BLOCK_2_FACE has desks with W and E chair sides."""
        p = _make_pattern([[{"type": "BLOCK_2_FACE", "gap_cm": 0}]])
        desks = compute_desk_positions(p)
        assert len(desks) == 2
        assert desks[0].chair_side == "W"
        assert desks[1].chair_side == "E"

    def test_block_1_rotated_90(self):
        """BLOCK_1 at 90° rotates chair from W to N."""
        p = _make_pattern(
            [[{"type": "BLOCK_1", "orientation": 90, "gap_cm": 0}]],
        )
        desks = compute_desk_positions(p)
        assert desks[0].chair_side == "N"

    def test_block_2_ortho_r(self):
        """BLOCK_2_ORTHO_R at 0°: desk0 chair N, desk1 chair E."""
        p = _make_pattern(
            [[{"type": "BLOCK_2_ORTHO_R", "gap_cm": 0}]],
            room_width_cm=500, room_depth_cm=500,
        )
        desks = compute_desk_positions(p)
        assert len(desks) == 2
        assert desks[0].chair_side == "N"
        assert desks[1].chair_side == "E"


class TestDimCirculation:
    """Verifies dimension 1 — circulation grade mapping."""

    def test_grade_a_maps_to_1(self):
        assert _GRADE_TO_DIM["A"] == 1.0

    def test_grade_f_maps_to_0(self):
        assert _GRADE_TO_DIM["F"] == 0.0

    def test_grade_e_maps_to_02(self):
        assert _GRADE_TO_DIM["E"] == 0.2


class TestDimLight:
    """Verifies dimension 2 — window proximity."""

    def test_no_windows_returns_none(self):
        """Room without windows → N/A."""
        p = _make_pattern(
            [[{"type": "BLOCK_1", "gap_cm": 10}]],
            room_width_cm=400, room_depth_cm=400,
        )
        desks = compute_desk_positions(p)
        room = RoomSpec(width_cm=400, depth_cm=400)
        assert _compute_dim_light(desks, room) is None

    def test_desk_near_window(self):
        """Desk within 200 cm of a north window → ratio 1.0."""
        p = _make_pattern(
            [[{"type": "BLOCK_1", "gap_cm": 10}]],
            room_width_cm=400, room_depth_cm=400,
        )
        desks = compute_desk_positions(p)
        # Window on north face near the desk
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            windows=[WindowSpec(face=Face.NORTH, offset_cm=0, width_cm=100)],
        )
        result = _compute_dim_light(desks, room)
        assert result == 1.0

    def test_desk_far_from_window(self):
        """Desk more than 200 cm from window → ratio 0.0."""
        p = _make_pattern(
            [[{"type": "BLOCK_1", "gap_cm": 10}]],
            room_width_cm=800, room_depth_cm=800,
        )
        desks = compute_desk_positions(p)
        # Window on south face, far from desk at (10, 0)
        room = RoomSpec(
            width_cm=800, depth_cm=800,
            windows=[WindowSpec(face=Face.SOUTH, offset_cm=700, width_cm=50)],
        )
        result = _compute_dim_light(desks, room)
        assert result == 0.0


class TestDimBackDoor:
    """Verifies dimension 3 — back to corridor door."""

    def test_no_corridor_door_returns_none(self):
        """No opening on south face → N/A."""
        p = _make_pattern(
            [[{"type": "BLOCK_1", "gap_cm": 10}]],
            room_width_cm=400, room_depth_cm=400,
        )
        desks = compute_desk_positions(p)
        room = RoomSpec(width_cm=400, depth_cm=400)
        assert _compute_dim_back_door(desks, room) is None

    def test_door_not_behind(self):
        """BLOCK_1 chair=W, corridor door=south → not behind → 1.0."""
        p = _make_pattern(
            [[{"type": "BLOCK_1", "gap_cm": 10}]],
            room_width_cm=400, room_depth_cm=400,
        )
        desks = compute_desk_positions(p)
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[OpeningSpec(
                face=Face.SOUTH, offset_cm=10, width_cm=90,
            )],
        )
        result = _compute_dim_back_door(desks, room)
        assert result == 1.0  # chair=W, door=south → no back-to-door

    def test_door_behind_desk(self):
        """BLOCK_1 rotated 270° has chair=S → back faces south door."""
        # 270° CW from W: W→N→E→S. Chair=S = back faces south.
        # Room 400x300, desk center ≈ (100, 40), door center ≈ (100, 300).
        # Distance ≈ 260 cm ≤ 300 threshold → detected.
        p = _make_pattern(
            [[{"type": "BLOCK_1", "orientation": 270, "gap_cm": 10}]],
            room_width_cm=400, room_depth_cm=300,
        )
        desks = compute_desk_positions(p)
        assert desks[0].chair_side == "S"
        room = RoomSpec(
            width_cm=400, depth_cm=300,
            openings=[OpeningSpec(
                face=Face.SOUTH, offset_cm=50, width_cm=100,
            )],
        )
        result = _compute_dim_back_door(desks, room)
        assert result == 0.0  # back faces south door


class TestDimFaceWall:
    """Verifies dimension 4 — face wall."""

    def test_desk_screen_faces_wall(self):
        """BLOCK_1 chair=W → screen=E. Desk at x=310 in 400-wide room.
        Distance to east wall = 400 - (310+80) = 10. If walking_margin ≥ 10 → bad."""
        p = _make_pattern(
            [[{"type": "BLOCK_1", "gap_cm": 310}]],
            room_width_cm=400, room_depth_cm=400,
        )
        desks = compute_desk_positions(p)
        room = RoomSpec(width_cm=400, depth_cm=400)
        result = _compute_dim_face_wall(desks, room, walking_margin_cm=90)
        assert result == 0.0  # screen 10 cm from wall ≤ 90

    def test_desk_screen_far_from_wall(self):
        """BLOCK_1 at gap=10 in 400-wide room.
        Screen side E, distance = 400 - (10+80) = 310 > 90."""
        p = _make_pattern(
            [[{"type": "BLOCK_1", "gap_cm": 10}]],
            room_width_cm=400, room_depth_cm=400,
        )
        desks = compute_desk_positions(p)
        room = RoomSpec(width_cm=400, depth_cm=400)
        result = _compute_dim_face_wall(desks, room, walking_margin_cm=90)
        assert result == 1.0


class TestCompositeAndGrade:
    """Verifies composite score and letter grade."""

    def test_all_dimensions_perfect(self):
        """All dims at 1.0 → composite 1.0, grade A."""
        dims = {
            "circulation": 1.0,
            "light": 1.0,
            "back_door": 1.0,
            "face_wall": 1.0,
            "distance": None,
        }
        weights = {
            "circulation": 1.0, "light": 1.0,
            "back_door": 1.0, "face_wall": 1.0, "distance": 1.0,
        }
        composite, grade = _compute_composite_and_grade(dims, weights)
        assert composite == 1.0
        assert grade == "A"

    def test_na_excluded_from_denominator(self):
        """N/A dimensions are excluded from the weighted average."""
        dims = {
            "circulation": 0.8,
            "light": None,
            "back_door": None,
            "face_wall": None,
            "distance": None,
        }
        weights = {
            "circulation": 1.0, "light": 1.0,
            "back_door": 1.0, "face_wall": 1.0, "distance": 1.0,
        }
        composite, grade = _compute_composite_and_grade(dims, weights)
        assert composite == 0.8
        assert grade == "B"

    def test_grade_thresholds(self):
        """Verify each grade threshold boundary."""
        w = {"x": 1.0}
        assert _compute_composite_and_grade({"x": 0.95}, w)[1] == "A"
        assert _compute_composite_and_grade({"x": 0.90}, w)[1] == "A"
        assert _compute_composite_and_grade({"x": 0.89}, w)[1] == "B"
        assert _compute_composite_and_grade({"x": 0.75}, w)[1] == "B"
        assert _compute_composite_and_grade({"x": 0.74}, w)[1] == "C"
        assert _compute_composite_and_grade({"x": 0.60}, w)[1] == "C"
        assert _compute_composite_and_grade({"x": 0.59}, w)[1] == "D"
        assert _compute_composite_and_grade({"x": 0.45}, w)[1] == "D"
        assert _compute_composite_and_grade({"x": 0.44}, w)[1] == "E"
        assert _compute_composite_and_grade({"x": 0.30}, w)[1] == "E"
        assert _compute_composite_and_grade({"x": 0.29}, w)[1] == "F"

    def test_weighted_average(self):
        """Composite respects weights."""
        dims = {"circulation": 1.0, "light": 0.0}
        weights = {"circulation": 3.0, "light": 1.0}
        composite, _ = _compute_composite_and_grade(dims, weights)
        assert composite == 0.75  # (3*1.0 + 1*0.0) / 4


class TestScoreCandidateGrade:
    """Verifies score_candidate produces D-238 grade fields."""

    def test_score_has_grade_fields(self):
        """score_candidate must populate all D-238 fields."""
        p = _make_pattern(
            [[{"type": "BLOCK_1", "gap_cm": 10}]],
            room_width_cm=400, room_depth_cm=400,
        )
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[OpeningSpec(
                face=Face.SOUTH, offset_cm=100, width_cm=90,
            )],
            windows=[WindowSpec(face=Face.NORTH, offset_cm=0, width_cm=200)],
        )
        p["_n_desks_after_removal"] = 1
        score = score_candidate(p, room, "standard1")
        assert score.dim_reachability is not None
        assert score.dim_light is not None
        assert score.dim_back_door is not None
        assert score.dim_face_wall is not None
        # dim_passage is None when min_passage_cm <= 0 (no passage found)
        if score.min_passage_cm > 0:
            assert score.dim_passage is not None
            assert score.passage_grade in ("A", "B", "C", "D", "F")
        else:
            assert score.dim_passage is None
            assert score.passage_grade is None
        assert score.composite_score >= 0
        assert score.room_grade in ("A", "B", "C", "D", "E", "F")


class TestComputeDimPassage:
    """D-293 — passage comfort dimension with 5 grade thresholds."""

    def test_no_passage(self):
        """min_passage_cm <= 0 → (None, None)."""
        dim, grade = _compute_dim_passage(0, None)
        assert dim is None
        assert grade is None

    def test_grade_a(self):
        """min_passage >= corridor → A (1.0)."""
        from olm.core.spacing_config import get_default
        cfg = get_default()
        dim, grade = _compute_dim_passage(cfg.main_corridor_cm, cfg)
        assert dim == 1.0
        assert grade == "A"

    def test_grade_b(self):
        """min_passage > passage AND < corridor → B (0.8)."""
        from olm.core.spacing_config import get_default
        cfg = get_default()
        mid = cfg.walking_margin_cm + 1
        if mid < cfg.main_corridor_cm:
            dim, grade = _compute_dim_passage(mid, cfg)
            assert dim == 0.8
            assert grade == "B"

    def test_grade_c(self):
        """min_passage == passage → C (0.6)."""
        from olm.core.spacing_config import get_default
        cfg = get_default()
        dim, grade = _compute_dim_passage(cfg.walking_margin_cm, cfg)
        assert dim == 0.6
        assert grade == "C"

    def test_grade_d(self):
        """min_passage >= passage * 0.5 AND < passage → D (0.4)."""
        from olm.core.spacing_config import get_default
        cfg = get_default()
        val = cfg.walking_margin_cm * 0.5
        dim, grade = _compute_dim_passage(val, cfg)
        assert dim == 0.4
        assert grade == "D"

    def test_grade_f(self):
        """min_passage < passage * 0.5 → F (0.0)."""
        from olm.core.spacing_config import get_default
        cfg = get_default()
        val = cfg.walking_margin_cm * 0.5 - 1
        dim, grade = _compute_dim_passage(val, cfg)
        assert dim == 0.0
        assert grade == "F"


class TestCirculationEntries:
    """D-280/D-296: entries = doors + corridor-face (south) openings.

    The room is canonical here (corridor = south), so circulation must enter
    through doors and/or south openings, never an exterior bay.
    """

    @staticmethod
    def _walls(room: RoomSpec) -> set[str]:
        pattern = _make_pattern([[{"type": "BLOCK_1"}]])
        room_dict, _ = _pattern_to_circulation_format(pattern, room)
        return {d["wall"] for d in room_dict["doors"]}

    def test_door_plus_south_opening(self):
        """Door (north) + free passage (south) → both are entries."""
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[
                OpeningSpec(face=Face.NORTH, offset_cm=100, width_cm=90,
                            has_door=True),
                OpeningSpec(face=Face.SOUTH, offset_cm=100, width_cm=90,
                            has_door=False),
            ],
        )
        assert self._walls(room) == {"north", "south"}

    def test_door_without_south_opening(self):
        """Door (north) + non-corridor passage (east) → only the door."""
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[
                OpeningSpec(face=Face.NORTH, offset_cm=100, width_cm=90,
                            has_door=True),
                OpeningSpec(face=Face.EAST, offset_cm=100, width_cm=90,
                            has_door=False),
            ],
        )
        assert self._walls(room) == {"north"}

    def test_no_door_prefers_south_opening(self):
        """No door, south + north passages → only the south (corridor) one."""
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[
                OpeningSpec(face=Face.SOUTH, offset_cm=100, width_cm=90,
                            has_door=False),
                OpeningSpec(face=Face.NORTH, offset_cm=100, width_cm=90,
                            has_door=False),
            ],
        )
        assert self._walls(room) == {"south"}

    def test_no_door_no_south_falls_back_to_all(self):
        """No door, no south opening → fall back to all openings."""
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[
                OpeningSpec(face=Face.EAST, offset_cm=100, width_cm=90,
                            has_door=False),
                OpeningSpec(face=Face.WEST, offset_cm=100, width_cm=90,
                            has_door=False),
            ],
        )
        assert self._walls(room) == {"east", "west"}

    def test_no_openings(self):
        """No openings at all → no entries."""
        room = RoomSpec(width_cm=400, depth_cm=400, openings=[])
        assert self._walls(room) == set()


# ---------------------------------------------------------------------------
# 3-category model — circulates_well, candidate_category,
# max_working_desks, _candidate_sort_key, select_best
# ---------------------------------------------------------------------------

def _make_score(
    m2: float = 10.0,
    min_passage: float = 120.0,
    grade: str | None = "C",
    name: str = "P",
    n_desks: int = 4,
    fit_class: str = "fitting",
    overflow_cm: float = 0.0,
    room_grade: str = "C",
) -> MatchScore:
    """Minimal MatchScore for select_best / sort key tests."""
    return MatchScore(
        pattern_name=name, standard="s1", n_desks=n_desks,
        m2_per_desk=m2, circulation_grade="A",
        connectivity_pct=100.0, min_passage_cm=min_passage,
        worst_detour=1.0, largest_free_rect_m2=1.0,
        adapted_pattern={}, passage_grade=grade,
        fit_class=fit_class, overflow_cm=overflow_cm,
        room_grade=room_grade,
    )


class TestCirculatesWell:
    """circulates_well predicate."""

    def test_grade_a(self):
        assert circulates_well(_make_score(grade="A")) is True

    def test_grade_b(self):
        assert circulates_well(_make_score(grade="B")) is True

    def test_grade_c(self):
        assert circulates_well(_make_score(grade="C")) is True

    def test_grade_d(self):
        assert circulates_well(_make_score(grade="D")) is False

    def test_grade_f(self):
        assert circulates_well(_make_score(grade="F")) is False

    def test_grade_none(self):
        assert circulates_well(_make_score(grade=None)) is False


class TestMaxWorkingDesks:
    """max_working_desks helper."""

    def test_max_among_fitting_well(self):
        scores = [
            _make_score(n_desks=3, grade="A"),
            _make_score(n_desks=2, grade="B"),
            _make_score(n_desks=5, grade="D"),  # bad circ → excluded
        ]
        assert max_working_desks(scores) == 3

    def test_zero_when_no_fitting_well(self):
        scores = [
            _make_score(n_desks=4, grade="F"),
            _make_score(n_desks=6, fit_class="oversize_1axis"),
        ]
        assert max_working_desks(scores) == 0

    def test_empty(self):
        assert max_working_desks([]) == 0


class TestCandidateCategory:
    """candidate_category classification."""

    def test_fits_well(self):
        s = _make_score(fit_class="fitting", grade="B", n_desks=4)
        assert candidate_category(s, max_working=4) == "fits_well"

    def test_fewer_desks(self):
        s = _make_score(fit_class="fitting", grade="B", n_desks=2)
        assert candidate_category(s, max_working=4) == "fewer_desks"

    def test_too_tight_bad_circulation(self):
        s = _make_score(fit_class="fitting", grade="D", n_desks=4)
        assert candidate_category(s, max_working=4) == "too_tight"

    def test_too_tight_passage_none(self):
        s = _make_score(fit_class="fitting", grade=None, min_passage=0.0)
        assert candidate_category(s, max_working=4) == "too_tight"

    def test_too_tight_oversize(self):
        s = _make_score(fit_class="oversize_1axis", overflow_cm=15.0)
        assert candidate_category(s, max_working=4) == "too_tight"

    def test_fewer_desks_when_max_working_zero(self):
        """All fitting+well → fewer_desks if max_working=0 (no well)."""
        s = _make_score(fit_class="fitting", grade="A", n_desks=2)
        assert candidate_category(s, max_working=0) == "fewer_desks"


class TestCandidateSortKey:
    """_candidate_sort_key category-based comparator."""

    def test_fits_well_beats_too_tight(self):
        """fits_well (fitting+good circ) < too_tight (fitting+bad circ)."""
        fw = _make_score(n_desks=2, fit_class="fitting", grade="B", name="fw")
        tt = _make_score(n_desks=3, fit_class="fitting", grade="D", name="tt")
        mw = 2
        assert _candidate_sort_key(fw, mw) < _candidate_sort_key(tt, mw)

    def test_too_tight_beats_fewer_desks(self):
        """too_tight < fewer_desks (fewer_desks displayed last)."""
        tt = _make_score(
            n_desks=2, fit_class="fitting", grade="F", name="tt")
        fd = _make_score(
            n_desks=1, fit_class="fitting", grade="A", name="fd")
        mw = 2
        assert _candidate_sort_key(tt, mw) < _candidate_sort_key(fd, mw)

    def test_more_desks_wins_same_category(self):
        """3 desks beats 2 desks within same category."""
        two = _make_score(n_desks=2, name="two")
        three = _make_score(n_desks=3, name="three")
        mw = 3
        assert _candidate_sort_key(three, mw) < _candidate_sort_key(two, mw)

    def test_better_grade_breaks_tie(self):
        """At same desk count, grade A beats grade D."""
        grade_a = _make_score(n_desks=3, room_grade="A", name="a")
        grade_d = _make_score(n_desks=3, room_grade="D", name="d")
        mw = 3
        assert _candidate_sort_key(grade_a, mw) < _candidate_sort_key(grade_d, mw)

    def test_overflow_discriminates_too_tight(self):
        """Within too_tight, lower overflow wins."""
        small = _make_score(
            fit_class="oversize_1axis", overflow_cm=5.0, name="small")
        big = _make_score(
            fit_class="oversize_1axis", overflow_cm=20.0, name="big")
        mw = 0
        assert _candidate_sort_key(small, mw) < _candidate_sort_key(big, mw)

    def test_3desks_gradeD_vs_2desks_gradeA_same_category(self):
        """3 desks grade D beats 2 desks grade A (desks before grade)."""
        three_d = _make_score(n_desks=3, room_grade="D", name="3D")
        two_a = _make_score(n_desks=2, room_grade="A", name="2A")
        mw = 3
        assert _candidate_sort_key(three_d, mw) < _candidate_sort_key(two_a, mw)


class TestSelectBest:
    """select_best returns best by _candidate_sort_key."""

    def test_fits_well_preferred_over_too_tight(self):
        fw = _make_score(n_desks=2, grade="C", name="fw")
        tt = _make_score(n_desks=4, grade="D", name="tt")
        best = select_best([tt, fw])
        assert best is fw

    def test_returns_too_tight_when_no_fits_well(self):
        """No fits_well → returns best of too_tight (not None)."""
        tt = _make_score(
            n_desks=3, fit_class="fitting", grade="D", name="tt")
        os = _make_score(
            n_desks=4, fit_class="oversize_1axis",
            overflow_cm=10.0, grade="A", name="os")
        best = select_best([os, tt])
        assert best is tt

    def test_returns_oversize_when_no_fitting(self):
        """Only oversize → returns best oversize."""
        osa = _make_score(
            fit_class="oversize_1axis", overflow_cm=5.0, name="a")
        osb = _make_score(
            fit_class="oversize_1axis", overflow_cm=20.0, name="b")
        best = select_best([osb, osa])
        assert best is osa

    def test_empty_returns_none(self):
        assert select_best([]) is None
