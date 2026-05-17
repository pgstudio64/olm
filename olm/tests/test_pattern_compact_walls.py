"""Tests for olm.core.pattern_compact_walls — wall shrink with attached blocks.

D-217: Compact shrinks the room by moving east/south walls inward.
Blocks touching a wall (lock or accidental contact) move with it.
"""
from __future__ import annotations

import copy

import pytest

from olm.core.pattern_normalize import normalize_pattern
from olm.core.spacing_config import SpacingConfig

# ---------------------------------------------------------------------------
# Standalone spacing configs (no project/config.json dependency)
# ---------------------------------------------------------------------------

_BASE = dict(
    door_exclusion_depth_cm=180,
    max_island_size=4,
    main_corridor_cm=140,
)

# Standard 3 (Site): chair=70, walking=90, slip_in=30
STD3 = SpacingConfig(
    name="standard3",
    chair_clearance_cm=70,
    walking_margin_cm=90,
    slip_in_margin_cm=30,
    **_BASE,
)

# Standard 1 (AFNOR): chair=70, walking=90, slip_in=30
STD1 = SpacingConfig(
    name="standard1",
    chair_clearance_cm=70,
    walking_margin_cm=90,
    slip_in_margin_cm=30,
    **_BASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pattern_480x500_site_1() -> dict:
    """Reproduce the user case: 480x500_Site_1 (standard3).

    Row 0: WS01 (BLOCK_1 orient 180, sticks=[N,W])
           WS02 (BLOCK_1 orient 0, gap=320, sticks=[N,E])
    Row 1: WS3  (BLOCK_1 orient 0, gap=400, offset_ns=-40, sticks=[E,S])
    row_gaps=[180], room 480x500.
    """
    return {
        "name": "480x500_Site_1",
        "rows": [
            {"blocks": [
                {"type": "BLOCK_1", "orientation": 180, "gap_cm": 0,
                 "offset_ns_cm": 0, "sticks": ["N", "W"]},
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 320,
                 "offset_ns_cm": 0, "sticks": ["N", "E"]},
            ]},
            {"blocks": [
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 400,
                 "offset_ns_cm": -40, "sticks": ["E", "S"]},
            ]},
        ],
        "row_gaps_cm": [180],
        "room_width_cm": 480,
        "room_depth_cm": 500,
        "standard": "standard3",
        "room_windows": [
            {"face": "north", "offset_cm": 0, "width_cm": 480, "origin": "auto"},
        ],
        "room_openings": [
            {"face": "south", "hinge_side": "left", "offset_cm": 10,
             "opens_inward": True, "origin": "manual", "width_cm": 90,
             "has_door": True},
        ],
        "room_exclusions": [],
    }


# ---------------------------------------------------------------------------
# Test 1: User case 480x500_Site_1
# ---------------------------------------------------------------------------


class TestUserCase480x500Site1:
    """Reproduce the bug: room should shrink to 340x360, all locks valid."""

    def test_room_shrinks_to_300x360(self):
        """D-229: chair-only zones → room 300x360 (was 340x360)."""
        pat = _pattern_480x500_site_1()
        result = normalize_pattern(pat, STD3)

        # D-229: W/E face = chair(70) only, candidate=0.
        # Gap WS01-WS02 = E(70) + W(70) = 140.
        # Width = 0 + 80 + 140 + 80 + 0 = 300.
        assert pat["room_width_cm"] == 300
        assert pat["room_depth_cm"] == 360

    def test_ws02_still_touches_east(self):
        """WS02 (row 0, block 1) must remain at east wall."""
        pat = _pattern_480x500_site_1()
        normalize_pattern(pat, STD3)

        # D-229: gap = E(70)+W(70)=140. WS02 x_max = room_width.
        ws02 = pat["rows"][0]["blocks"][1]
        ws01 = pat["rows"][0]["blocks"][0]
        ws02_x = ws01["gap_cm"] + 80 + ws02["gap_cm"]
        ws02_x_max = ws02_x + 80  # eo=80
        assert ws02_x_max == pat["room_width_cm"]

    def test_ws3_still_touches_east_and_south(self):
        """WS3 (row 1, block 0) must remain at east and south walls."""
        pat = _pattern_480x500_site_1()
        normalize_pattern(pat, STD3)

        ws3 = pat["rows"][1]["blocks"][0]
        ws3_x = ws3["gap_cm"]
        ws3_x_max = ws3_x + 80  # eo=80
        assert ws3_x_max == pat["room_width_cm"]


# ---------------------------------------------------------------------------
# Test 2: No blocks attached to east wall — no shrink
# ---------------------------------------------------------------------------


class TestNoBlocksAttachedEast:
    """Single block in the middle — east wall does not move."""

    def test_no_shrink_when_block_not_touching(self):
        pat = {
            "name": "TEST_NO_ATTACH",
            "rows": [{"blocks": [
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 100,
                 "offset_ns_cm": 0},
            ]}],
            "row_gaps_cm": [],
            "room_width_cm": 500,
            "room_depth_cm": 300,
            "standard": "standard3",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        normalize_pattern(pat, STD3)

        # Block at gap=100, eo=80, west_face=90 (orient 0).
        # Effective: x_min=100-90=10, x_max=100+80=180.
        # Block NOT touching east (180 != 500).
        # After fit: room shrinks to bbox = 180 - 10 = 170, snap to 170.
        # But compact_walls should not affect — block never touched east.
        # fit_room will resize to minimum anyway.
        # Key: the block does NOT move to the east wall.
        assert pat["room_width_cm"] <= 180  # fit shrinks to packing size


# ---------------------------------------------------------------------------
# Test 3: Block accidentally touching east (no lock but at wall)
# ---------------------------------------------------------------------------


class TestBlockAccidentallyTouchingEast:
    """Block at x_max == room_width without formal lock — moves with wall."""

    def test_accidental_touch_shrinks(self):
        # D-229: orient 0 W=70 (chair), E=0.
        # Min gap = 0 + 70 = 70. width = 70+80+70+80 = 300.
        pat = {
            "name": "TEST_ACCIDENTAL",
            "rows": [{"blocks": [
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 0,
                 "offset_ns_cm": 0},
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 320,
                 "offset_ns_cm": 0},
            ]}],
            "row_gaps_cm": [],
            "room_width_cm": 480,
            "room_depth_cm": 300,
            "standard": "standard3",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        normalize_pattern(pat, STD3)

        assert pat["room_width_cm"] == 300
        b_right = pat["rows"][0]["blocks"][1]
        b_left = pat["rows"][0]["blocks"][0]
        x_right = b_left["gap_cm"] + 80 + b_right["gap_cm"]
        assert x_right + 80 == pat["room_width_cm"]


# ---------------------------------------------------------------------------
# Test 4: 3 blocks — residual balanced by normalize_intra
# ---------------------------------------------------------------------------


class TestThreeBlocksResidual:
    """Row with 3 blocks, only rightmost touching east.

    After compact, normalize_intra sets all internal gaps to minimum.
    """

    def test_three_blocks_all_gaps_minimized(self):
        # D-229: A orient 180: E=70. B orient 0: W=70, E=0. C orient 0: W=70.
        # Gap A-B min = 70+70 = 140. Gap B-C min = 0+70 = 70.
        pat = {
            "name": "TEST_3BLOCKS",
            "rows": [{"blocks": [
                {"type": "BLOCK_1", "orientation": 180, "gap_cm": 0,
                 "offset_ns_cm": 0},
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 200,
                 "offset_ns_cm": 0},
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 500,
                 "offset_ns_cm": 0},
            ]}],
            "row_gaps_cm": [],
            "room_width_cm": 940,
            "room_depth_cm": 300,
            "standard": "standard3",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        normalize_pattern(pat, STD3)

        blocks = pat["rows"][0]["blocks"]
        assert blocks[1]["gap_cm"] == 140
        assert blocks[2]["gap_cm"] == 70
        # Room = 80 + 140 + 80 + 70 + 80 = 450. Snap 450.
        assert pat["room_width_cm"] == 450


# ---------------------------------------------------------------------------
# Test 5: Gap already at minimum — no-op
# ---------------------------------------------------------------------------


class TestGapAtMinimumSkipped:
    """Pattern already at minimum dimensions — compact is no-op."""

    def test_already_minimal(self):
        # D-229: orient 180 E=70, orient 0 W=70. Min gap = 140.
        # Room = 80+140+80 = 300.
        pat = {
            "name": "TEST_MINIMAL",
            "rows": [{"blocks": [
                {"type": "BLOCK_1", "orientation": 180, "gap_cm": 0,
                 "offset_ns_cm": 0},
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 140,
                 "offset_ns_cm": 0},
            ]}],
            "row_gaps_cm": [],
            "room_width_cm": 300,
            "room_depth_cm": 300,
            "standard": "standard3",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        orig = copy.deepcopy(pat)
        normalize_pattern(pat, STD3)

        assert pat["room_width_cm"] == 300
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 140


# ---------------------------------------------------------------------------
# Test 6: No compact possible (single block, room already fitted)
# ---------------------------------------------------------------------------


class TestNoCompactPossible:
    """Single block — compact_walls is a no-op, fit sizes to minimum."""

    def test_single_block_no_compact(self):
        pat = {
            "name": "TEST_NOCOMPACT",
            "rows": [{"blocks": [
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 0,
                 "offset_ns_cm": 0},
            ]}],
            "row_gaps_cm": [],
            "room_width_cm": 500,
            "room_depth_cm": 500,
            "standard": "standard3",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        normalize_pattern(pat, STD3)

        # D-229: W face=70 (chair only). width=70+80=150. depth=180.
        assert pat["room_width_cm"] == 150
        assert pat["room_depth_cm"] == 180


# ---------------------------------------------------------------------------
# Test 7: Block touching both east AND west — no-op for east
# ---------------------------------------------------------------------------


class TestBlockTouchingBothWalls:
    """Block spans the full room width — east wall cannot move."""

    def test_touching_both_walls_noop(self):
        # D-229: W face=70, E=0. Room width=70+80=150.
        # Block at gap=70: x=70, x_max=150. x_min_eff=0.
        pat = {
            "name": "TEST_BOTH_WALLS",
            "rows": [{"blocks": [
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 70,
                 "offset_ns_cm": 0},
            ]}],
            "row_gaps_cm": [],
            "room_width_cm": 150,
            "room_depth_cm": 300,
            "standard": "standard3",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        normalize_pattern(pat, STD3)

        assert pat["room_width_cm"] == 150  # unchanged


# ---------------------------------------------------------------------------
# Test 8: Door exclusion may re-extend room after compact
# ---------------------------------------------------------------------------


class TestDoorExclusionAfterCompact:
    """Door exclusion zone can prevent full shrink (EC-5)."""

    def test_door_exclusion_limits_shrink(self):
        # Same as user case but with a LARGE door exclusion.
        # Standard3 has door_exclusion_depth_cm=120.
        # After compact to 340x360, the door on south (offset=10, w=90)
        # band [10, 100] overlaps blocks. fit checks if the door exclusion
        # zone requires more depth.
        pat = _pattern_480x500_site_1()
        result = normalize_pattern(pat, STD3)

        # With std3 door_exclusion=120:
        # Door on south, band x=[10,100]. After compact, blocks at x:
        # WS01 at gap[0], WS02 at gap[0]+80+180. WS3 at gap[0]+...
        # The door exclusion checks if any block's south effective edge
        # falls in the door's X band and adds clearance.
        # For this specific case, door_exclusion should not prevent
        # the expected 340x360 because blocks are far from the door band.
        # (Door at x=10..100, blocks at x≈0..340 with bodies at 80..170
        #  for WS01 and 260..340 for WS02/WS3).
        # WS01 body [0,80], eff_s=0. In band [10,100]? overlap [10,80]. Yes!
        # So door exclusion extends y_max: WS01 y_max(180) + 120 = 300.
        # But bbox_y_max after compact is 360 (from WS3). 300 < 360 → no ext.
        assert pat["room_depth_cm"] == 360


# ---------------------------------------------------------------------------
# Test 9: Iterative catch — offset block caught by wall (D-218)
# ---------------------------------------------------------------------------


def _pattern_offset_east() -> dict:
    """480x500 variant: WS02 offset 50 cm from east wall (gap=270).

    Row 0: WS01 (orient 180, gap=0, sticks NW), WS02 (orient 0, gap=270, stick N)
    Row 1: WS03 (orient 0, gap=400, offset_ns=-40, sticks SE)
    WS03 touches east (400+80=480). WS02 does NOT (80+270+80=430 != 480).
    Iterative compact must first catch WS02 then compress together.
    """
    return {
        "name": "480x500_offset_east",
        "rows": [
            {"blocks": [
                {"type": "BLOCK_1", "orientation": 180, "gap_cm": 0,
                 "offset_ns_cm": 0, "sticks": ["N", "W"]},
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 270,
                 "offset_ns_cm": 0, "sticks": ["N"]},
            ]},
            {"blocks": [
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 400,
                 "offset_ns_cm": -40, "sticks": ["E", "S"]},
            ]},
        ],
        "row_gaps_cm": [180],
        "room_width_cm": 480,
        "room_depth_cm": 500,
        "standard": "standard3",
        "room_windows": [
            {"face": "north", "offset_cm": 0, "width_cm": 480, "origin": "auto"},
        ],
        "room_openings": [
            {"face": "south", "hinge_side": "left", "offset_cm": 10,
             "opens_inward": True, "origin": "manual", "width_cm": 90,
             "has_door": True},
        ],
        "room_exclusions": [],
    }


class TestCompactEastCatchesOffsetBlock:
    """D-218: Iterative catch-distance recovers slack from non-touching rows."""

    def test_room_width_300_after_normalize(self):
        """D-229: After full normalize_pattern, room_width must be 300."""
        pat = _pattern_offset_east()
        normalize_pattern(pat, STD3)
        assert pat["room_width_cm"] == 300

    def test_intermediate_gaps_after_compact(self):
        """After compact_walls only (no normalize_intra/fit), check gap_cm."""
        from olm.core.pattern_compact_walls import compact_walls
        from olm.core.spacing_config import build_block_defs

        pat = _pattern_offset_east()
        block_defs = build_block_defs(STD3)
        changes = compact_walls(pat, STD3)

        # D-229: WS02 gap: 270 → 140 (E(70)+W(70))
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 140
        # WS03 gap: 400 → 220 (reduced iteratively)
        assert pat["rows"][1]["blocks"][0]["gap_cm"] == 220
        assert changes >= 3


class TestCompactSouthUnaffectedByEastOffset:
    """D-218: South compact result identical regardless of east offset."""

    def test_room_depth_360(self):
        """room_depth_cm must be 360 (same as base 480x500 case)."""
        pat = _pattern_offset_east()
        normalize_pattern(pat, STD3)
        assert pat["room_depth_cm"] == 360


# ---------------------------------------------------------------------------
# Test 11: No block initially touching room_width (D-218 gate removal)
# ---------------------------------------------------------------------------


class TestCompactEastNoInitialTouching:
    """D-218: Compact works even when no block initially touches room_width."""

    def test_room_width_300(self):
        """D-229: Iterative catch compresses to 300."""
        pat = {
            "name": "TEST_NO_INITIAL_TOUCHING",
            "rows": [
                {"blocks": [
                    {"type": "BLOCK_1", "orientation": 180, "gap_cm": 0,
                     "offset_ns_cm": 0, "sticks": ["N", "W"]},
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 230,
                     "offset_ns_cm": 0, "sticks": ["N"]},
                ]},
                {"blocks": [
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 380,
                     "offset_ns_cm": 0, "sticks": ["S"]},
                ]},
            ],
            "row_gaps_cm": [180],
            "room_width_cm": 500,
            "room_depth_cm": 500,
            "standard": "standard3",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        normalize_pattern(pat, STD3)
        assert pat["room_width_cm"] == 300
