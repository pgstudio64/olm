"""Tests for olm.core.pattern_classify."""
from __future__ import annotations

import pytest

from olm.core.pattern_classify import classify_pattern
from olm.core.spacing_config import SpacingConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _spacing(**overrides) -> SpacingConfig:
    """Return a test SpacingConfig with sensible defaults."""
    defaults = dict(
        name="test",
        chair_clearance_cm=60,
        walking_margin_cm=80,
        slip_in_margin_cm=30,
        main_corridor_cm=120,
        door_exclusion_depth_cm=150,
        max_island_size=6,
    )
    defaults.update(overrides)
    return SpacingConfig(**defaults)


def _pattern(
    room_w: int = 500,
    room_d: int = 400,
    blocks: list[dict] | None = None,
    openings: list[dict] | None = None,
    row_gaps: list[int] | None = None,
) -> dict:
    """Build a minimal pattern dict for classification tests.

    Single row by default with given blocks at orientation 0.
    BLOCK_1 = 80 eo x 180 ns (desk_d x desk_w).
    """
    if blocks is None:
        blocks = [{"type": "BLOCK_1", "orientation": 0}]
    pat: dict = {
        "name": "test",
        "room_width_cm": room_w,
        "room_depth_cm": room_d,
        "standard": "test",
        "rows": [{"blocks": blocks}],
    }
    if row_gaps is not None:
        pat["row_gaps_cm"] = row_gaps
    if openings is not None:
        pat["room_openings"] = openings
    return pat


# ---------------------------------------------------------------------------
# Tests — ok
# ---------------------------------------------------------------------------

class TestOk:
    """Pattern fits cleanly in the room."""

    def test_single_block_fits(self):
        # BLOCK_1 = 80x180, room 500x400 → plenty of space
        assert classify_pattern(_pattern(), _spacing()) == "ok"

    def test_empty_rows(self):
        pat = _pattern()
        pat["rows"] = []
        assert classify_pattern(pat, _spacing()) == "ok"

    def test_no_room_dimensions(self):
        pat = _pattern(room_w=0, room_d=0)
        assert classify_pattern(pat, _spacing()) == "ok"


# ---------------------------------------------------------------------------
# Tests — reject: R1 body outside room
# ---------------------------------------------------------------------------

class TestRejectBodyOutside:
    """Block body extends beyond room boundaries."""

    def test_block_too_wide(self):
        # BLOCK_1 at orient 0: eo=80, ns=180.  Room width=70 → body overflows
        assert classify_pattern(
            _pattern(room_w=70, room_d=300), _spacing(),
        ) == "reject"

    def test_block_too_deep(self):
        # Room depth=100, BLOCK_1 ns=180 → body overflows
        assert classify_pattern(
            _pattern(room_w=200, room_d=100), _spacing(),
        ) == "reject"


# ---------------------------------------------------------------------------
# Tests — reject: R2 door exclusion overlaps block body
# ---------------------------------------------------------------------------

class TestRejectDoorBody:
    """Door exclusion zone overlaps a block body."""

    def test_inward_door_over_block(self):
        # Block at (0,0), 80x180.  Inward door on south face at offset=0,
        # width=100.  Door exclusion: (0, room_d - depth, 100, depth).
        # With room_d=200, depth=150 → rect (0, 50, 100, 150).
        # Block body: (0, 0, 80, 180).  Overlap y=[50,180] x=[0,80] → reject.
        pat = _pattern(
            room_w=300, room_d=200,
            openings=[{
                "face": "south", "offset_cm": 0, "width_cm": 100,
                "has_door": True, "opens_inward": True,
            }],
        )
        assert classify_pattern(pat, _spacing()) == "reject"


# ---------------------------------------------------------------------------
# Tests — reject: R3 two block footprints overlap
# ---------------------------------------------------------------------------

class TestRejectFootprintOverlap:
    """Two block total footprints (body + face zones) overlap."""

    def test_two_blocks_squeezed(self):
        # Two BLOCK_1 side by side with 0 gap in same row.
        # BLOCK_1 eo=80, face zones add ~60 east + ~60 west.
        # Total footprint width per block ≈ 80 + 60 + 60 = 200.
        # Block 1 at x=0, Block 2 at x=80 → footprints overlap.
        pat = _pattern(
            room_w=600, room_d=400,
            blocks=[
                {"type": "BLOCK_1", "orientation": 0},
                {"type": "BLOCK_1", "orientation": 0},
            ],
        )
        result = classify_pattern(pat, _spacing())
        assert result == "reject"


# ---------------------------------------------------------------------------
# Tests — tolere: door exclusion overlaps soft margin only
# ---------------------------------------------------------------------------

class TestTolere:
    """Door exclusion touches face zones but not body."""

    def test_door_over_face_zone_only(self):
        # BLOCK_1 at orient 0: body 80x180, west face zone outer=90.
        # Place block at x=100 (gap_cm=100): body (100,0,80,180),
        # footprint (10,0,170,180).
        # Outward door on west face: depth=walking_margin=80,
        # rect (0, 0, 80, 200).
        # Body vs door: x=[100,180] vs x=[0,80] → no overlap → not R2.
        # Footprint vs door: x=[10,180] vs x=[0,80] → overlap → tolere.
        pat = _pattern(
            room_w=400, room_d=300,
            blocks=[{"type": "BLOCK_1", "orientation": 0, "gap_cm": 100}],
            openings=[{
                "face": "west", "offset_cm": 0, "width_cm": 200,
                "has_door": True, "opens_inward": False,
            }],
        )
        result = classify_pattern(pat, _spacing())
        assert result == "tolere"


# ---------------------------------------------------------------------------
# Tests — integration with catalogue_service
# ---------------------------------------------------------------------------

class TestListPatternsAddsClass:
    """list_patterns annotates patterns with fit_class."""

    def test_fit_class_present(self, monkeypatch):
        dummy = _pattern()
        dummy["standard"] = "standard1"
        monkeypatch.setattr(
            "olm.server.services.catalogue_service.load_catalogue",
            lambda: [dummy],
        )
        from olm.server.services.catalogue_service import list_patterns
        result = list_patterns()
        assert "fit_class" in result["patterns"][0]
        assert result["patterns"][0]["fit_class"] in ("ok", "tolere", "reject")
