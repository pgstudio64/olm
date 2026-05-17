"""Tests for olm.core.pattern_normalize — pattern normalization to standard.

Covers: 3 standards, expand/compress/noop, offset_ns_cm untouched,
multi-row, rotated blocks, empty rows, single-block patterns, standard
update, cross-standard recalibration.
"""
from __future__ import annotations

import copy

import pytest

from olm.core.pattern_normalize import normalize_catalogue, normalize_pattern
from olm.core.spacing_config import SpacingConfig

# ---------------------------------------------------------------------------
# Test spacing configs — standalone, no project/config.json dependency
# ---------------------------------------------------------------------------

_BASE = dict(
    front_access_cm=60,
    passage_behind_one_row_cm=160,
    passage_between_back_to_back_cm=230,
    door_exclusion_depth_cm=180,
    max_island_size=4,
    min_block_separation_cm=90,
    main_corridor_cm=140,
)

# Standard 1 (AFNOR): chair=70, passage=90, access_single=100, dtw=20
STD1 = SpacingConfig(
    name="standard1",
    chair_clearance_cm=70,
    passage_cm=90,
    access_single_desk_cm=100,
    desk_to_wall_cm=20,
    **_BASE,
)

# Standard 2 (Kardham): chair=70, passage=90, access_single=90, dtw=10
STD2 = SpacingConfig(
    name="standard2",
    chair_clearance_cm=70,
    passage_cm=90,
    access_single_desk_cm=90,
    desk_to_wall_cm=10,
    **_BASE,
)

# Standard 3 (Site): chair=70, passage=90, access_single=90, dtw=0
STD3 = SpacingConfig(
    name="standard3",
    chair_clearance_cm=70,
    passage_cm=90,
    access_single_desk_cm=90,
    desk_to_wall_cm=0,
    **_BASE,
)


# ---------------------------------------------------------------------------
# Helper — minimal pattern builders
# ---------------------------------------------------------------------------


def _pattern_two_blocks_one_row(
    gap_cm: int,
    block1: str = "BLOCK_1",
    block2: str = "BLOCK_1",
    orient1: int = 0,
    orient2: int = 0,
    standard: str = "standard1",
) -> dict:
    """Two blocks in one row, separated by gap_cm."""
    return {
        "name": "TEST_2B1R",
        "rows": [{"blocks": [
            {"type": block1, "orientation": orient1, "gap_cm": 0},
            {"type": block2, "orientation": orient2, "gap_cm": gap_cm},
        ]}],
        "row_gaps_cm": [],
        "room_width_cm": 1000,
        "room_depth_cm": 1000,
        "standard": standard,
        "room_windows": [],
        "room_openings": [],
        "room_exclusions": [],
    }


def _pattern_two_rows(
    row_gap: int,
    block1: str = "BLOCK_1",
    block2: str = "BLOCK_1",
    standard: str = "standard1",
) -> dict:
    """Two rows with one block each, separated by row_gap."""
    return {
        "name": "TEST_2R",
        "rows": [
            {"blocks": [{"type": block1, "orientation": 0, "gap_cm": 0}]},
            {"blocks": [{"type": block2, "orientation": 0, "gap_cm": 0}]},
        ],
        "row_gaps_cm": [row_gap],
        "room_width_cm": 1000,
        "room_depth_cm": 1000,
        "standard": standard,
        "room_windows": [],
        "room_openings": [],
        "room_exclusions": [],
    }


def _pattern_single_block(standard: str = "standard1") -> dict:
    """Single block, no gaps to normalize."""
    return {
        "name": "TEST_1B",
        "rows": [{"blocks": [
            {"type": "BLOCK_1", "orientation": 0, "gap_cm": 0},
        ]}],
        "row_gaps_cm": [],
        "room_width_cm": 1000,
        "room_depth_cm": 1000,
        "standard": standard,
        "room_windows": [],
        "room_openings": [],
        "room_exclusions": [],
    }


# ---------------------------------------------------------------------------
# Expected gap values for reference
# ---------------------------------------------------------------------------
# BLOCK_1 at orientation 0:
#   west = chair(70) + passage_single
#   east = absent (0)
#   north/south = absent (0)
#
# For std1: passage_single = access_single(100) - chair(70) = 30
#   => west.total = 70+30 = 100, east.total = 0
#
# Gap between two BLOCK_1s in a row = east[left].total + west[right].total
#   = 0 + 100 = 100 (std1)
#
# For std2: passage_single = 90-70 = 20
#   => west.total = 70+20 = 90
#   Gap = 0 + 90 = 90
#
# For std3: same as std2 = 90
#
# BLOCK_2_FACE at orientation 0:
#   east/west = chair(70) + passage(90) = 160
#   north/south = absent (0)
#
# Gap BLOCK_2_FACE + BLOCK_1 = east_2F(160) + west_1(100) = 260 (std1)
#   std2: 160 + 90 = 250
#
# Row gap BLOCK_1 over BLOCK_1:
#   south[top].total=0, north[bottom].total=0 => row_gap = 0


# ===========================================================================
# Tests
# ===========================================================================


class TestSingleBlock:
    """Case 1: single block — normalization is a no-op on gaps."""

    def test_noop(self):
        pat = _pattern_single_block()
        result = normalize_pattern(pat, STD1)
        assert result.gaps_changed == 0
        assert result.row_gaps_changed == 0


class TestTwoBlocksIntraRowGap:
    """Cases 2-4: two BLOCK_1s in one row, gap expanded/compressed/exact."""

    def test_expand_gap_too_small(self):
        """Gap 50 < required 100 (std1) -> expanded to 100."""
        pat = _pattern_two_blocks_one_row(gap_cm=50, standard="standard1")
        result = normalize_pattern(pat, STD1)
        assert result.gaps_changed == 1
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 100

    def test_compress_gap_too_large(self):
        """Gap 200 > required 100 (std1) -> compressed to 100.

        D-218: compact_east now handles this before normalize_intra,
        so gaps_changed == 0 (compact did the work, intra is a no-op).
        """
        pat = _pattern_two_blocks_one_row(gap_cm=200, standard="standard1")
        result = normalize_pattern(pat, STD1)
        assert result.gaps_changed == 0
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 100

    def test_exact_gap_noop(self):
        """Gap already 100 = required (std1) -> no change."""
        pat = _pattern_two_blocks_one_row(gap_cm=100, standard="standard1")
        result = normalize_pattern(pat, STD1)
        assert result.gaps_changed == 0
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 100


class TestInterRowGap:
    """Cases 5-7: two rows of BLOCK_1, row_gap expanded/compressed/exact."""

    def test_expand_row_gap(self):
        """Row gap 0 < required 0 for two BLOCK_1s (south=0, north=0)."""
        # BLOCK_1 has no south/north zones, so required row_gap = 0+0 = 0
        pat = _pattern_two_rows(row_gap=50, standard="standard1")
        result = normalize_pattern(pat, STD1)
        # south(BLOCK_1)=0, north(BLOCK_1)=0 => required=0
        # 50 > 0 => compressed to 0
        assert pat["row_gaps_cm"][0] == 0

    def test_row_gap_with_face_blocks(self):
        """BLOCK_2_FACE: south=0, north=0 => row_gap=0."""
        pat = _pattern_two_rows(
            row_gap=100,
            block1="BLOCK_2_FACE",
            block2="BLOCK_2_FACE",
            standard="standard1",
        )
        result = normalize_pattern(pat, STD1)
        # BLOCK_2_FACE at orient 0: N/S both absent => 0
        assert pat["row_gaps_cm"][0] == 0


class TestOffsetNsUntouched:
    """Case 8: offset_ns_cm preserved by normalization step 1.

    Note: fit_room_to_pattern (step 2) may translate all blocks to
    recenter them in the positive quadrant, which shifts offset_ns_cm
    uniformly. We verify the relative difference is preserved.
    """

    def test_offset_relative_preserved(self):
        pat = _pattern_two_blocks_one_row(gap_cm=50, standard="standard1")
        pat["rows"][0]["blocks"][0]["offset_ns_cm"] = -160
        pat["rows"][0]["blocks"][1]["offset_ns_cm"] = 30
        result = normalize_pattern(pat, STD1)
        # Relative difference must be preserved (190 = 30 - (-160))
        off0 = pat["rows"][0]["blocks"][0]["offset_ns_cm"]
        off1 = pat["rows"][0]["blocks"][1]["offset_ns_cm"]
        assert off1 - off0 == 190


class TestRotatedBlocks:
    """Case 9: blocks at 90 orientation — face zones rotate."""

    def test_rotated_gap(self):
        """BLOCK_1 at 90 degrees: west zone becomes north, east->south.
        After rotation, east.total and west.total change."""
        pat = _pattern_two_blocks_one_row(
            gap_cm=0, orient1=90, orient2=90, standard="standard1",
        )
        result = normalize_pattern(pat, STD1)
        # BLOCK_1 at 90: the west face (chair+passage_single) rotates
        # to become the north face. East (absent) becomes south.
        # At 90 degrees: new_east = old_north = absent,
        #                new_west = old_south = absent
        # So gap required = 0 + 0 = 0
        # (The chair zone is now on north/south after rotation)
        gap = pat["rows"][0]["blocks"][1]["gap_cm"]
        assert gap == 0


class TestEmptyRow:
    """Case 10: empty row ignored without error."""

    def test_empty_row_skipped(self):
        pat = {
            "name": "EMPTY_ROW",
            "rows": [
                {"blocks": []},
                {"blocks": [
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 0},
                ]},
            ],
            "row_gaps_cm": [100],
            "room_width_cm": 1000,
            "room_depth_cm": 1000,
            "standard": "standard1",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        result = normalize_pattern(pat, STD1)
        assert result.gaps_changed == 0
        # Empty row has no blocks => max_south = 0
        # Second row BLOCK_1 => max_north = 0
        # Required row gap = 0
        assert pat["row_gaps_cm"][0] == 0


class TestThreeStandards:
    """Case 11: same pattern, different standard target -> different gaps."""

    def test_std1_gap(self):
        pat = _pattern_two_blocks_one_row(gap_cm=0, standard="standard1")
        normalize_pattern(pat, STD1)
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 100

    def test_std2_gap(self):
        pat = _pattern_two_blocks_one_row(gap_cm=0, standard="standard1")
        normalize_pattern(pat, STD2)
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 90

    def test_std3_gap(self):
        pat = _pattern_two_blocks_one_row(gap_cm=0, standard="standard1")
        normalize_pattern(pat, STD3)
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 90


class TestMixedBlockTypes:
    """Case 12: different block types in the same row."""

    def test_block1_and_block2face(self):
        """BLOCK_1 then BLOCK_2_FACE: gap = east_B1(0) + west_B2F(160)."""
        pat = _pattern_two_blocks_one_row(
            gap_cm=0,
            block1="BLOCK_1",
            block2="BLOCK_2_FACE",
            standard="standard1",
        )
        normalize_pattern(pat, STD1)
        # BLOCK_1 east=0, BLOCK_2_FACE west=160
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 160

    def test_block2face_and_block1(self):
        """BLOCK_2_FACE then BLOCK_1: gap = east_B2F(160) + west_B1(100)."""
        pat = _pattern_two_blocks_one_row(
            gap_cm=0,
            block1="BLOCK_2_FACE",
            block2="BLOCK_1",
            standard="standard1",
        )
        normalize_pattern(pat, STD1)
        # BLOCK_2_FACE east=160, BLOCK_1 west=100
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 260


class TestMixedRowTypes:
    """Case 13: different block types in different rows."""

    def test_block2face_over_block1(self):
        """BLOCK_2_FACE (south=0) over BLOCK_1 (north=0) => gap=0."""
        pat = _pattern_two_rows(
            row_gap=200,
            block1="BLOCK_2_FACE",
            block2="BLOCK_1",
            standard="standard1",
        )
        normalize_pattern(pat, STD1)
        # Both have no N/S zones at orientation 0
        assert pat["row_gaps_cm"][0] == 0


class TestStandardUpdate:
    """Case 14: pattern["standard"] is updated to the target standard."""

    def test_standard_updated(self):
        pat = _pattern_single_block(standard="standard1")
        result = normalize_pattern(pat, STD2)
        assert pat["standard"] == "standard2"
        assert result.old_standard == "standard1"
        assert result.new_standard == "standard2"


class TestCrossStandardExpand:
    """Case 15: pattern in std1, target std3 — gap sufficient for std1
    but insufficient for std3 if face zones differ."""

    def test_std1_to_std2_gap_change(self):
        """std1 access_single=100 => west=100, std2 access_single=90 => west=90.
        Two BLOCK_1s: gap should be 90 under std2 vs 100 under std1."""
        pat = _pattern_two_blocks_one_row(
            gap_cm=100, standard="standard1",
        )
        normalize_pattern(pat, STD2)
        # Under std2: west = 70 + (90-70) = 90, east = 0
        # Required gap = 0 + 90 = 90
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 90
        assert pat["standard"] == "standard2"


class TestCrossStandardCompress:
    """Case 16: pattern in std3 (generous gaps), target std1 — compress."""

    def test_std3_to_std1(self):
        """std3 west=90, std1 west=100. Gap at 90 needs expansion to 100."""
        pat = _pattern_two_blocks_one_row(
            gap_cm=90, standard="standard3",
        )
        normalize_pattern(pat, STD1)
        # Under std1: west = 100, east = 0 => required = 100
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 100
        assert pat["standard"] == "standard1"


class TestNormalizePatternCanonicalizes:
    """D-213 regression: normalize_pattern canonicalizes before gap normalization.

    User pattern 460x300_Site_1: two BLOCK_1s with negative gap producing
    reversed spatial order. After normalize_pattern (Compact), blocks must
    be in spatial order with chairs INWARD and correct gap.
    """

    def test_compact_inward_chairs(self):
        """Compact on reversed-gap pattern -> chairs inward, correct room."""
        pat = {
            "name": "460x300_Site_1",
            "rows": [{
                "blocks": [
                    {
                        "type": "BLOCK_1", "orientation": 0,
                        "gap_cm": 380, "offset_ns_cm": 0,
                        "sticks": ["N", "E"],
                    },
                    {
                        "type": "BLOCK_1", "orientation": 180,
                        "gap_cm": -460, "offset_ns_cm": 0,
                    },
                ],
            }],
            "row_gaps_cm": [],
            "room_width_cm": 460,
            "room_depth_cm": 300,
            "standard": "standard3",
        }
        result = normalize_pattern(pat, STD3)
        blocks = pat["rows"][0]["blocks"]

        # After canonicalize: orient-180 first (x=0), orient-0 second (x=380)
        # After intra-row normalize (STD3):
        #   orient-180 BLOCK_1: west(orig) rotated to east -> east.total = 90
        #   orient-0 BLOCK_1: west.total = 90
        #   required_gap = 90 + 90 = 180
        assert blocks[0]["orientation"] == 180
        assert blocks[1]["orientation"] == 0
        assert blocks[1]["gap_cm"] == 180

        # Chairs INWARD: orient-180 has chair on east, orient-0 has chair
        # on west -> they face each other. Verified by gap being 180 (not 0).

        # Room dimensions: fit_room_to_pattern computes min room
        # Block 0 at x=0 (eo=80), block 1 at x=0+80+180=260 (eo=80)
        # Total EO = 260+80 = 340. With dtw=0 (Site), room width = 340.
        assert pat["room_width_cm"] == 340


class TestInterRowOffset:
    """D-216: inter-row gap accounts for offset_ns_cm via pair-by-pair X projection."""

    def test_negative_offset_user_case(self):
        """480x500_Site_1: offset_ns_cm=-40 on row 1 block causes overlap.

        After canonicalize, row 0 = [BLOCK_1 orient 180 gap=0, BLOCK_1 orient 0].
        Row 1 = [BLOCK_1 orient 0 gap=400 offset_ns_cm=-40].
        row_gaps_cm=[180] originally.

        With STD3 (Site): after intra-row normalize, row 0 gap becomes 180
        (east[180]=90 + west[0]=90). After inter-row normalize, row_gap[0]
        must be >= 40 to prevent WS03 from overlapping WS02.

        Formula: pair_required = offset_ns[b] + ns[b] + south[b] - max_ns_upper
                                 - offset_ns[b'] + north[b']
        For (WS02, WS03): 0 + 180 + 0 - 180 - (-40) + 0 = 40.
        """
        pat = {
            "name": "480x500_Site_1",
            "rows": [
                {"blocks": [
                    {
                        "type": "BLOCK_1", "orientation": 180,
                        "gap_cm": 0, "offset_ns_cm": 0,
                        "sticks": ["N"],
                    },
                    {
                        "type": "BLOCK_1", "orientation": 0,
                        "gap_cm": 310, "offset_ns_cm": 0,
                    },
                ]},
                {"blocks": [
                    {
                        "type": "BLOCK_1", "orientation": 0,
                        "gap_cm": 400, "offset_ns_cm": -40,
                    },
                ]},
            ],
            "row_gaps_cm": [180],
            "room_width_cm": 480,
            "room_depth_cm": 500,
            "standard": "standard3",
        }
        result = normalize_pattern(pat, STD3)
        # Required row_gap must be at least 40 to avoid overlap
        assert pat["row_gaps_cm"][0] == 40

    def test_no_offset_unchanged(self):
        """All offset_ns_cm=0: row_gap same as old max_south + max_north.

        Two BLOCK_1 orient 0 (south=0, north=0) => required_gap = 0.
        """
        pat = _pattern_two_rows(row_gap=100, standard="standard1")
        result = normalize_pattern(pat, STD1)
        # BLOCK_1 orient 0: south=0, north=0 => required=0
        assert pat["row_gaps_cm"][0] == 0

    def test_positive_offset_upper(self):
        """Block in row 0 with offset_ns_cm=+50, faces N/S absent.

        BLOCK_1 orient 0: ns=180, south=0, north=0. max_ns_upper=180.
        pair_required = 50 + 180 + 0 - 180 - 0 + 0 = 50.
        """
        pat = _pattern_two_rows(row_gap=0, standard="standard3")
        pat["rows"][0]["blocks"][0]["offset_ns_cm"] = 50
        result = normalize_pattern(pat, STD3)
        assert pat["row_gaps_cm"][0] == 50

    def test_no_x_overlap(self):
        """Two blocks in row 0 and 1 block in row 1 with no X overlap.

        Row 0: BLOCK_1 orient 0 at gap=0 (x=0, eo=80, west=90 -> eff [-90,80]).
        Row 1: BLOCK_1 orient 0 at gap=500 (x=500, eo=80, west=90 -> eff [410,580]).
        No X overlap => row_gap = 0.
        """
        pat = {
            "name": "NO_OVERLAP",
            "rows": [
                {"blocks": [
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 0},
                ]},
                {"blocks": [
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 500},
                ]},
            ],
            "row_gaps_cm": [100],
            "room_width_cm": 1000,
            "room_depth_cm": 1000,
            "standard": "standard3",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        result = normalize_pattern(pat, STD3)
        assert pat["row_gaps_cm"][0] == 0

    def test_extreme_offset_warning(self):
        """offset_ns_cm=-200 triggers a warning in normalize result."""
        pat = _pattern_two_rows(row_gap=0, standard="standard3")
        pat["rows"][1]["blocks"][0]["offset_ns_cm"] = -200
        result = normalize_pattern(pat, STD3)
        extreme_warnings = [
            w for w in result.warnings if "extreme offset_ns_cm" in w
        ]
        assert len(extreme_warnings) >= 1
        assert "-200" in extreme_warnings[0]

    def test_combined_offset_face_zones(self):
        """Combination: offset_ns_cm + active south face zone on upper block.

        Row 0: BLOCK_1 orient 90 at gap=0. At orient 90, N/S faces are active
        (original W/E become N/S after rotation). south_zone = old east = 0,
        north_zone = old west = chair+passage = 90 (STD3).
        Actually at orient 90: new_south = old_east = absent(0),
        new_north = old_west = 90. ns = eo_orig = 80.
        offset_ns_cm = +30.
        max_ns_upper = 80 (orient 90: ns = eo_orig = 80).

        Row 1: BLOCK_1 orient 90, offset_ns_cm = 0.
        north_zone = old_west = 90.

        pair_required = 30 + 80 + 0 - 80 - 0 + 90 = 120.
        """
        pat = {
            "name": "COMBINED",
            "rows": [
                {"blocks": [
                    {
                        "type": "BLOCK_1", "orientation": 90,
                        "gap_cm": 0, "offset_ns_cm": 30,
                    },
                ]},
                {"blocks": [
                    {
                        "type": "BLOCK_1", "orientation": 90,
                        "gap_cm": 0, "offset_ns_cm": 0,
                    },
                ]},
            ],
            "row_gaps_cm": [0],
            "room_width_cm": 1000,
            "room_depth_cm": 1000,
            "standard": "standard3",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        result = normalize_pattern(pat, STD3)
        assert pat["row_gaps_cm"][0] == 120

    def test_3_rows_independent(self):
        """3 rows, 2 row_gaps: each gap computed independently.

        Row 0: BLOCK_1 orient 0, offset_ns=0. ns=180.
        Row 1: BLOCK_1 orient 0, offset_ns=-30. ns=180.
        Row 2: BLOCK_1 orient 0, offset_ns=-50. ns=180.

        All at gap=0, same X position => all pairs have X overlap.
        max_ns per row = 180.

        row_gap[0]: pair (row0, row1).
          pair_required = 0 + 180 + 0 - 180 - (-30) + 0 = 30.
        row_gap[1]: pair (row1, row2).
          pair_required = -30 + 180 + 0 - 180 - (-50) + 0 = 20.
        """
        pat = {
            "name": "THREE_ROWS",
            "rows": [
                {"blocks": [
                    {
                        "type": "BLOCK_1", "orientation": 0,
                        "gap_cm": 0, "offset_ns_cm": 0,
                    },
                ]},
                {"blocks": [
                    {
                        "type": "BLOCK_1", "orientation": 0,
                        "gap_cm": 0, "offset_ns_cm": -30,
                    },
                ]},
                {"blocks": [
                    {
                        "type": "BLOCK_1", "orientation": 0,
                        "gap_cm": 0, "offset_ns_cm": -50,
                    },
                ]},
            ],
            "row_gaps_cm": [200, 200],
            "room_width_cm": 1000,
            "room_depth_cm": 1000,
            "standard": "standard3",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        result = normalize_pattern(pat, STD3)
        assert pat["row_gaps_cm"][0] == 30
        assert pat["row_gaps_cm"][1] == 20


class TestNormalizeCatalogue:
    """normalize_catalogue processes multiple patterns."""

    def test_batch(self):
        pats = [
            _pattern_two_blocks_one_row(gap_cm=0, standard="standard1"),
            _pattern_single_block(standard="standard1"),
        ]
        pats[0]["name"] = "PAT_A"
        pats[1]["name"] = "PAT_B"
        results = normalize_catalogue(pats, STD1)
        assert len(results) == 2
        assert results[0].name == "PAT_A"
        assert results[1].name == "PAT_B"
        # All patterns now have standard1
        assert pats[0]["standard"] == "standard1"
        assert pats[1]["standard"] == "standard1"
