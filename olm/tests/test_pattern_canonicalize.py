"""Tests for olm.core.pattern_canonicalize — block spatial reordering.

D-213: blocks within each row are sorted by ascending x_cm,
gap_cm recomputed to preserve positions. Negative gaps eliminated.
"""
from __future__ import annotations

import copy

import olm.core.pattern_generator as pg
from olm.core.pattern_canonicalize import CanonicalizeResult, canonicalize_blocks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pattern_user_460x300() -> dict:
    """Reproduce the user's 460x300_Site_1 pattern with negative gap.

    JSON order: block 0 (orient 0, gap=380) at x=380,
                block 1 (orient 180, gap=-460) at x=0.
    Spatially: block 1 is LEFT of block 0.
    """
    return {
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


def _pattern_already_canonical() -> dict:
    """Two blocks in correct spatial order, no negative gaps."""
    return {
        "name": "CANONICAL",
        "rows": [{
            "blocks": [
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 0},
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 100},
            ],
        }],
        "row_gaps_cm": [],
        "room_width_cm": 500,
        "room_depth_cm": 300,
        "standard": "standard1",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCanonicalizeNoop:
    """Pattern already in spatial order -> unchanged."""

    def test_noop(self):
        pat = _pattern_already_canonical()
        original = copy.deepcopy(pat)
        result = canonicalize_blocks(pat)

        assert isinstance(result, CanonicalizeResult)
        assert result.n_reorderings == 0
        assert pat["rows"][0]["blocks"][0]["gap_cm"] == 0
        assert pat["rows"][0]["blocks"][1]["gap_cm"] == 100


class TestCanonicalizeNegativeGap:
    """User pattern 460x300_Site_1 with negative gap -> reordered."""

    def test_reorder(self):
        pat = _pattern_user_460x300()
        result = canonicalize_blocks(pat)

        assert result.n_reorderings == 1
        blocks = pat["rows"][0]["blocks"]

        # After reorder: block at x=0 (orient 180) is first
        assert blocks[0]["orientation"] == 180
        assert blocks[0]["gap_cm"] == 0

        # Block at x=380 (orient 0) is second
        # gap = x_cm[1] - (x_cm[0] + eo[0])
        # BLOCK_1 eo=80 at orient 180 -> eo still 80 (no swap)
        # gap = 380 - (0 + 80) = 300
        assert blocks[1]["orientation"] == 0
        assert blocks[1]["gap_cm"] == 300

    def test_sticks_follow_block(self):
        """Sticks travel with their block object after reorder."""
        pat = _pattern_user_460x300()
        canonicalize_blocks(pat)
        blocks = pat["rows"][0]["blocks"]

        # orient-0 block had sticks=["N","E"], now at index 1
        assert blocks[1].get("sticks") == ["N", "E"]
        # orient-180 block had no sticks
        assert blocks[0].get("sticks") is None


class TestCanonicalizeMultiRow:
    """Two rows, each with reversed order -> each canonicalized."""

    def test_multi_row(self):
        pat = {
            "name": "MULTI",
            "rows": [
                {"blocks": [
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 200},
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": -280},
                ]},
                {"blocks": [
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 100},
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": -180},
                ]},
            ],
            "row_gaps_cm": [160],
            "room_width_cm": 500,
            "room_depth_cm": 500,
            "standard": "standard1",
        }
        result = canonicalize_blocks(pat)
        assert result.n_reorderings == 2

        # Row 0: block at x=200, block at x=0 -> reorder
        r0 = pat["rows"][0]["blocks"]
        assert r0[0]["gap_cm"] == 0   # was at x=0
        # gap[1] = 200 - (0 + 80) = 120
        assert r0[1]["gap_cm"] == 120

        # Row 1: block at x=100, block at x=0 -> reorder
        r1 = pat["rows"][1]["blocks"]
        assert r1[0]["gap_cm"] == 0
        # gap[1] = 100 - (0 + 80) = 20
        assert r1[1]["gap_cm"] == 20


class TestCanonicalizePreservesAttributes:
    """offset_ns_cm, orientation, sticks, type intact after reorder."""

    def test_attributes_preserved(self):
        pat = {
            "name": "ATTRS",
            "rows": [{
                "blocks": [
                    {
                        "type": "BLOCK_2_FACE", "orientation": 90,
                        "gap_cm": 400, "offset_ns_cm": 15,
                        "sticks": ["S"],
                    },
                    {
                        "type": "BLOCK_1", "orientation": 0,
                        "gap_cm": -400, "offset_ns_cm": 10,
                    },
                ],
            }],
            "row_gaps_cm": [],
            "room_width_cm": 600,
            "room_depth_cm": 400,
            "standard": "standard1",
        }
        canonicalize_blocks(pat)
        blocks = pat["rows"][0]["blocks"]

        # BLOCK_1 at x=0 now first
        assert blocks[0]["type"] == "BLOCK_1"
        assert blocks[0]["orientation"] == 0
        assert blocks[0]["offset_ns_cm"] == 10

        # BLOCK_2_FACE at x=400 now second
        assert blocks[1]["type"] == "BLOCK_2_FACE"
        assert blocks[1]["orientation"] == 90
        assert blocks[1]["offset_ns_cm"] == 15
        assert blocks[1].get("sticks") == ["S"]


class TestCanonicalizeWithOrient:
    """Orient 90/270 swaps eo/ns — positions must use effective eo."""

    def test_orient_90(self):
        # BLOCK_1: eo=80, ns=180. At orient 90: effective eo=180, ns=80.
        # Block 0 (orient 90, gap=300): x=300, eo_eff=180 -> block_x ends 480
        # Block 1 (orient 0, gap=-300): x=480-300=180, eo_eff=80
        # Spatial order: block 1 (x=180) < block 0 (x=300)
        pat = {
            "name": "ORIENT90",
            "rows": [{
                "blocks": [
                    {
                        "type": "BLOCK_1", "orientation": 90,
                        "gap_cm": 300,
                    },
                    {
                        "type": "BLOCK_1", "orientation": 0,
                        "gap_cm": -300,
                    },
                ],
            }],
            "row_gaps_cm": [],
            "room_width_cm": 600,
            "room_depth_cm": 300,
            "standard": "standard1",
        }
        result = canonicalize_blocks(pat)
        assert result.n_reorderings == 1

        blocks = pat["rows"][0]["blocks"]
        # orient-0 block at x=W is first (W = ns of orient-90 BLOCK_1)
        assert blocks[0]["orientation"] == 0
        assert blocks[0]["gap_cm"] == pg.DESK_W_CM

        # orient-90 block at x=300 is second
        # eo of orient-0 BLOCK_1 = D
        # gap = 300 - (W + D)
        assert blocks[1]["orientation"] == 90
        assert blocks[1]["gap_cm"] == 300 - pg.DESK_W_CM - pg.DESK_D_CM


class TestCanonicalizeEmptyRow:
    """Row with zero or one block -> no crash, no reordering."""

    def test_empty_row(self):
        pat = {
            "name": "EMPTY",
            "rows": [{"blocks": []}],
            "row_gaps_cm": [],
            "room_width_cm": 100,
            "room_depth_cm": 100,
            "standard": "standard1",
        }
        result = canonicalize_blocks(pat)
        assert result.n_reorderings == 0

    def test_single_block(self):
        pat = {
            "name": "SINGLE",
            "rows": [{"blocks": [
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 50},
            ]}],
            "row_gaps_cm": [],
            "room_width_cm": 200,
            "room_depth_cm": 200,
            "standard": "standard1",
        }
        result = canonicalize_blocks(pat)
        assert result.n_reorderings == 0
        assert pat["rows"][0]["blocks"][0]["gap_cm"] == 50
