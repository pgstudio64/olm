"""Tests for infer_rows_from_positions (D-267).

Three idempotence tests (A/B/C) and edge-case tests for row clustering,
vertical move, reorder, empty row removal, transitive clustering, and
attribute preservation.
"""
from __future__ import annotations

import copy

import pytest

from olm.core.catalogue_matcher import compute_block_positions
from olm.core.pattern_canonicalize import infer_rows_from_positions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _positions_to_flat_blocks(pattern: dict) -> list[dict]:
    """Convert a pattern to a flat list of blocks with absolute positions."""
    positions = compute_block_positions(pattern)
    flat: list[dict] = []
    for bp in positions:
        row = pattern["rows"][bp.row_idx]
        block = row["blocks"][bp.block_idx]
        b = {}
        for k, v in block.items():
            if k in ("gap_cm", "offset_ns_cm"):
                continue
            b[k] = v
        b["x_cm"] = bp.x_cm
        b["y_cm"] = bp.y_cm
        flat.append(b)
    return flat


def _round_trip(pattern: dict) -> dict:
    """Convert pattern → flat → infer → rebuilt pattern."""
    flat = _positions_to_flat_blocks(pattern)
    result = infer_rows_from_positions(flat)
    return {
        "rows": result.rows,
        "row_gaps_cm": result.row_gaps_cm,
    }


# ---------------------------------------------------------------------------
# Fixtures — realistic patterns
# ---------------------------------------------------------------------------

@pytest.fixture
def mono_row_pattern():
    """Single row with 2 BLOCK_1 blocks."""
    return {
        "rows": [
            {
                "blocks": [
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 0},
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 20},
                ],
            },
        ],
        "row_gaps_cm": [],
    }


@pytest.fixture
def two_row_pattern():
    """Two rows with gap, blocks have different types."""
    return {
        "rows": [
            {
                "blocks": [
                    {"type": "BLOCK_2_FACE", "orientation": 0, "gap_cm": 10},
                ],
            },
            {
                "blocks": [
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 30},
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 10},
                ],
            },
        ],
        "row_gaps_cm": [50],
    }


@pytest.fixture
def offset_ns_pattern():
    """Row with offset_ns_cm on one block."""
    return {
        "rows": [
            {
                "blocks": [
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 0},
                    {
                        "type": "BLOCK_1", "orientation": 0,
                        "gap_cm": 20, "offset_ns_cm": 40,
                    },
                ],
            },
        ],
        "row_gaps_cm": [],
    }


@pytest.fixture
def ortho_pattern():
    """Pattern with a rotated block (orientation=90)."""
    return {
        "rows": [
            {
                "blocks": [
                    {"type": "BLOCK_1", "orientation": 90, "gap_cm": 0},
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 10},
                ],
            },
        ],
        "row_gaps_cm": [],
    }


# ---------------------------------------------------------------------------
# Test A — positions round-trip: positions(infer(positions(P))) == positions(P)
# ---------------------------------------------------------------------------

class TestIdempotenceA:
    """Positions round-trip: absolute positions are preserved."""

    def _check_positions_match(self, original: dict) -> None:
        original_positions = compute_block_positions(original)
        rebuilt = _round_trip(original)
        rebuilt_positions = compute_block_positions(rebuilt)

        assert len(rebuilt_positions) == len(original_positions)
        for op, rp in zip(original_positions, rebuilt_positions):
            assert op.x_cm == rp.x_cm, f"x_cm mismatch: {op.x_cm} != {rp.x_cm}"
            assert op.y_cm == rp.y_cm, f"y_cm mismatch: {op.y_cm} != {rp.y_cm}"
            assert op.eo_cm == rp.eo_cm
            assert op.ns_cm == rp.ns_cm

    def test_mono_row(self, mono_row_pattern):
        self._check_positions_match(mono_row_pattern)

    def test_two_rows(self, two_row_pattern):
        self._check_positions_match(two_row_pattern)

    def test_offset_ns(self, offset_ns_pattern):
        self._check_positions_match(offset_ns_pattern)

    def test_ortho(self, ortho_pattern):
        self._check_positions_match(ortho_pattern)


# ---------------------------------------------------------------------------
# Test B — point fixe: infer(infer(P)) == infer(P)
# ---------------------------------------------------------------------------

class TestIdempotenceB:
    """Point fixe: two passes produce the same result."""

    def _check_point_fixe(self, original: dict) -> None:
        flat1 = _positions_to_flat_blocks(original)
        result1 = infer_rows_from_positions(flat1)
        rebuilt1 = {
            "rows": result1.rows,
            "row_gaps_cm": result1.row_gaps_cm,
        }

        flat2 = _positions_to_flat_blocks(rebuilt1)
        result2 = infer_rows_from_positions(flat2)

        assert len(result1.rows) == len(result2.rows)
        assert result1.row_gaps_cm == result2.row_gaps_cm
        for r1, r2 in zip(result1.rows, result2.rows):
            assert len(r1["blocks"]) == len(r2["blocks"])
            for b1, b2 in zip(r1["blocks"], r2["blocks"]):
                assert b1["gap_cm"] == b2["gap_cm"]
                assert b1.get("offset_ns_cm", 0) == b2.get("offset_ns_cm", 0)

    def test_mono_row(self, mono_row_pattern):
        self._check_point_fixe(mono_row_pattern)

    def test_two_rows(self, two_row_pattern):
        self._check_point_fixe(two_row_pattern)

    def test_offset_ns(self, offset_ns_pattern):
        self._check_point_fixe(offset_ns_pattern)

    def test_ortho(self, ortho_pattern):
        self._check_point_fixe(ortho_pattern)


# ---------------------------------------------------------------------------
# Test C — brute equality on canonical patterns (gap_cm, offset_ns, row_gaps)
# ---------------------------------------------------------------------------

class TestIdempotenceC:
    """Brute equality: gap_cm / offset_ns_cm / row_gaps_cm match original."""

    def _check_brute_equality(self, original: dict) -> None:
        rebuilt = _round_trip(original)
        assert len(rebuilt["rows"]) == len(original["rows"])
        assert rebuilt["row_gaps_cm"] == original.get("row_gaps_cm", [])
        for ri, (orig_row, reb_row) in enumerate(
            zip(original["rows"], rebuilt["rows"])
        ):
            orig_blocks = orig_row["blocks"]
            reb_blocks = reb_row["blocks"]
            assert len(reb_blocks) == len(orig_blocks), f"Row {ri} block count"
            for bi, (ob, rb) in enumerate(zip(orig_blocks, reb_blocks)):
                assert ob.get("gap_cm", 0) == rb.get("gap_cm", 0), (
                    f"Row {ri} block {bi} gap_cm: "
                    f"{ob.get('gap_cm', 0)} != {rb.get('gap_cm', 0)}"
                )
                assert ob.get("offset_ns_cm", 0) == rb.get("offset_ns_cm", 0), (
                    f"Row {ri} block {bi} offset_ns_cm"
                )

    def test_mono_row(self, mono_row_pattern):
        self._check_brute_equality(mono_row_pattern)

    def test_two_rows(self, two_row_pattern):
        self._check_brute_equality(two_row_pattern)

    def test_offset_ns(self, offset_ns_pattern):
        self._check_brute_equality(offset_ns_pattern)

    def test_ortho(self, ortho_pattern):
        self._check_brute_equality(ortho_pattern)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Functional edge cases for infer_rows_from_positions."""

    def test_empty(self):
        """Empty block list → empty result."""
        result = infer_rows_from_positions([])
        assert result.rows == []
        assert result.row_gaps_cm == []
        assert result.n_rows == 0

    def test_single_block(self):
        """Single block → one row, gap_cm = x_cm."""
        flat = [{"type": "BLOCK_1", "orientation": 0, "x_cm": 50, "y_cm": 0}]
        result = infer_rows_from_positions(flat)
        assert result.n_rows == 1
        assert len(result.rows[0]["blocks"]) == 1
        assert result.rows[0]["blocks"][0]["gap_cm"] == 50

    def test_vertical_move_creates_new_row(self):
        """Moving a block far down creates a second row."""
        flat = [
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 0, "y_cm": 0},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 100, "y_cm": 300},
        ]
        result = infer_rows_from_positions(flat)
        assert result.n_rows == 2
        assert len(result.rows[0]["blocks"]) == 1
        assert len(result.rows[1]["blocks"]) == 1

    def test_horizontal_reorder(self):
        """Blocks reordered left-to-right → gap_cm >= 0."""
        flat = [
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 200, "y_cm": 0},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 0, "y_cm": 0},
        ]
        result = infer_rows_from_positions(flat)
        assert result.n_rows == 1
        blocks = result.rows[0]["blocks"]
        assert len(blocks) == 2
        for b in blocks:
            assert b["gap_cm"] >= 0

    def test_transitive_clustering(self):
        """A overlaps B, B overlaps C, A∩C = ∅ → one row (transitive)."""
        # BLOCK_1 at orientation 0 has ns=180.
        # A at y=0 (0..180), B at y=80 (80..260), C at y=160 (160..340)
        # A∩B = 100 (>50% of 180=90), B∩C = 100, A∩C = 20 < 90
        flat = [
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 0, "y_cm": 0},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 100, "y_cm": 80},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 200, "y_cm": 160},
        ]
        result = infer_rows_from_positions(flat)
        # All three should be in one row via transitive closure
        assert result.n_rows == 1
        assert len(result.rows[0]["blocks"]) == 3

    def test_sticks_preserved(self):
        """Block attributes (sticks, type, orientation) are preserved."""
        flat = [
            {
                "type": "BLOCK_2_FACE", "orientation": 0,
                "x_cm": 0, "y_cm": 0,
                "sticks": ["W"],
            },
        ]
        result = infer_rows_from_positions(flat)
        block = result.rows[0]["blocks"][0]
        assert block["sticks"] == ["W"]
        assert block["type"] == "BLOCK_2_FACE"
        assert block["orientation"] == 0

    def test_gap_cm_never_negative(self):
        """Overlapping x positions → gap_cm clamped to 0."""
        # Two blocks at the same x
        flat = [
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 0, "y_cm": 0},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 10, "y_cm": 0},
        ]
        result = infer_rows_from_positions(flat)
        for b in result.rows[0]["blocks"]:
            assert b["gap_cm"] >= 0

    def test_offset_on_non_terminal_row_round_trip(self):
        """D-267 regression: an offset block on a NON-terminal row must not
        shift the next row on re-decode.

        row_gaps_cm must be measured from baseline + max(body ns), not from
        max(y_abs + ns). BLOCK_1 ns=180. Row 0 = {A y=0, B y=80} (A∩B=100 ≥
        90 → same row), B body bottom = 260 > row body height 180. Row 1 =
        {C y=320}. The buggy 'y_abs+ns' bottom gave gap=60 → C re-decoded at
        y=240 instead of 320.
        """
        flat = [
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 0, "y_cm": 0},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 100, "y_cm": 80},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 0, "y_cm": 320},
        ]
        result = infer_rows_from_positions(flat)
        assert result.n_rows == 2
        rebuilt = {"rows": result.rows, "row_gaps_cm": result.row_gaps_cm}
        got = sorted((p.x_cm, p.y_cm) for p in compute_block_positions(rebuilt))
        want = sorted((b["x_cm"], b["y_cm"]) for b in flat)
        assert got == want, f"positions shifted: {got} != {want}"


# ---------------------------------------------------------------------------
# D-268 — out-of-room placement round-trip
# ---------------------------------------------------------------------------

class TestOutOfRoom:
    """Blocks placed outside the room must round-trip through infer_rows."""

    @staticmethod
    def _check_round_trip(flat: list[dict]) -> None:
        result = infer_rows_from_positions(flat)
        rebuilt = {"rows": result.rows, "row_gaps_cm": result.row_gaps_cm}
        got = sorted(
            (p.x_cm, p.y_cm) for p in compute_block_positions(rebuilt)
        )
        want = sorted((b["x_cm"], b["y_cm"]) for b in flat)
        assert got == want, f"positions shifted: {got} != {want}"

    def test_negative_x(self):
        """Block at x < 0 (west overflow) → gap_cm negative, round-trip OK."""
        flat = [
            {"type": "BLOCK_1", "orientation": 0, "x_cm": -50, "y_cm": 0},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 100, "y_cm": 0},
        ]
        self._check_round_trip(flat)
        result = infer_rows_from_positions(flat)
        assert result.rows[0]["blocks"][0]["gap_cm"] == -50

    def test_negative_y(self):
        """Block at y < 0 (north overflow) → offset_ns negative, round-trip OK."""
        flat = [
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 0, "y_cm": -40},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 100, "y_cm": 0},
        ]
        self._check_round_trip(flat)

    def test_east_overflow(self):
        """Block beyond east wall (x + eo > room_width) — round-trip OK."""
        # Just test that positions are preserved; room bounds are irrelevant
        flat = [
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 0, "y_cm": 0},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 500, "y_cm": 0},
        ]
        self._check_round_trip(flat)

    def test_south_overflow(self):
        """Block beyond south wall (y + ns > room_depth) — round-trip OK."""
        flat = [
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 0, "y_cm": 0},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 0, "y_cm": 500},
        ]
        self._check_round_trip(flat)

    def test_fully_outside_all_directions(self):
        """Blocks outside in all 4 directions — round-trip OK.

        Blocks must be far enough apart vertically to form separate rows
        (no y-overlap between different rows).
        """
        # BLOCK_1 ns=180. Row gaps must be non-negative, so rows must not
        # overlap. y=-300 (body -300..−120), y=0 (0..180), y=500 (500..680).
        flat = [
            {"type": "BLOCK_1", "orientation": 0, "x_cm": -200, "y_cm": -300},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 0, "y_cm": 0},
            {"type": "BLOCK_1", "orientation": 0, "x_cm": 800, "y_cm": 500},
        ]
        self._check_round_trip(flat)
