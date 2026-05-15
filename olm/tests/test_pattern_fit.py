"""Tests for olm.core.pattern_fit — fit room to pattern."""
from __future__ import annotations

import copy

import pytest

from olm.core.pattern_fit import (
    MIN_DOOR_WIDTH_CM,
    SNAP_CM,
    FitResult,
    PatternStructurallyInvalid,
    fit_room_to_pattern,
)
from olm.core.spacing_config import SpacingConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spacing(**overrides) -> SpacingConfig:
    """Build a SpacingConfig with sensible defaults."""
    defaults = {
        "name": "test_std",
        "chair_clearance_cm": 70,
        "front_access_cm": 120,
        "access_single_desk_cm": 100,
        "passage_behind_one_row_cm": 160,
        "passage_between_back_to_back_cm": 140,
        "passage_cm": 90,
        "door_exclusion_depth_cm": 180,
        "desk_to_wall_cm": 20,
        "max_island_size": 6,
        "min_block_separation_cm": 90,
        "main_corridor_cm": 160,
    }
    defaults.update(overrides)
    return SpacingConfig(**defaults)


def _pattern(
    block_type: str = "BLOCK_4_FACE",
    orientation: int = 0,
    room_w: int = 800,
    room_d: int = 600,
    windows: list | None = None,
    openings: list | None = None,
    exclusions: list | None = None,
    extra_blocks: list | None = None,
    row_gaps: list | None = None,
) -> dict:
    """Build a single-row pattern with one or more blocks."""
    blocks = [{"type": block_type, "orientation": orientation}]
    if extra_blocks:
        blocks.extend(extra_blocks)
    rows = [{"blocks": blocks}]
    if row_gaps is not None and extra_blocks:
        # Two-row pattern: split blocks
        rows = [
            {"blocks": [{"type": block_type, "orientation": orientation}]},
            {"blocks": extra_blocks},
        ]
    return {
        "name": "TEST",
        "rows": rows,
        "row_gaps_cm": row_gaps or [],
        "room_width_cm": room_w,
        "room_depth_cm": room_d,
        "standard": "test_std",
        "room_windows": windows or [],
        "room_openings": openings or [],
        "room_exclusions": exclusions or [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFitShrinksOversizeRoom:
    """Oversize room is shrunk to the minimum."""

    def test_shrinks(self):
        # BLOCK_4_FACE: eo=160, ns=360 at orientation 0.
        # With default spacing (chair=70, passage=90), E/W faces have
        # non_superposable=70 + candidate=90 = 160 cm each.
        # N/S faces are absent -> desk_to_wall=20 cm.
        # Expected width = 160 (west zone) + 160 (block eo) + 160 (east zone)
        #                = 480 -> snap = 480
        # Expected depth = 20 (north d2w) + 360 (block ns) + 20 (south d2w)
        #                = 400 -> snap = 400
        pat = _pattern(room_w=800, room_d=600)
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)

        assert result.direction == "shrink"
        assert result.new_width == 480
        assert result.new_depth == 400
        assert pat["room_width_cm"] == 480
        assert pat["room_depth_cm"] == 400


class TestFitExpandsUndersizeRoom:
    """Undersize room is expanded to the minimum."""

    def test_expands(self):
        pat = _pattern(room_w=200, room_d=200)
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)

        assert result.direction == "expand"
        assert result.new_width > 200
        assert result.new_depth > 200


class TestFitNoopWhenAlreadyMin:
    """Room already at minimum -> noop."""

    def test_noop(self):
        pat = _pattern(room_w=800, room_d=600)
        sp = _spacing()
        # First fit to get the minimum
        r1 = fit_room_to_pattern(pat, sp)
        # Second fit on the same (now minimal) pattern
        pat2 = copy.deepcopy(pat)
        r2 = fit_room_to_pattern(pat2, sp)

        assert r2.direction == "noop"
        assert r2.new_width == r1.new_width
        assert r2.new_depth == r1.new_depth


class TestFitRaisesOnStructuralInvalid:
    """Two blocks at the same position -> PatternStructurallyInvalid."""

    def test_collision(self):
        # Two BLOCK_4_FACE at the same position (gap_cm=0, same row)
        pat = {
            "name": "COLLISION",
            "rows": [{"blocks": [
                {"type": "BLOCK_4_FACE", "orientation": 0},
                {"type": "BLOCK_4_FACE", "orientation": 0, "gap_cm": -160},
            ]}],
            "row_gaps_cm": [],
            "room_width_cm": 800,
            "room_depth_cm": 600,
            "standard": "test_std",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        sp = _spacing()
        with pytest.raises(PatternStructurallyInvalid):
            fit_room_to_pattern(pat, sp)


class TestFitRespectsDoorMinWidth:
    """Room cannot shrink below door minimum on a face."""

    def test_door_preserved(self):
        # Door on south face at offset 0, width 90 cm.
        # The fit must produce a room at least 90 cm wide (south face).
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=800,
            room_d=600,
            openings=[{
                "face": "south",
                "offset_cm": 0,
                "width_cm": 90,
                "has_door": True,
                "opens_inward": True,
                "hinge_side": "left",
            }],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)

        assert result.new_width >= MIN_DOOR_WIDTH_CM
        # Door should still be present
        assert len(pat["room_openings"]) == 1
        assert pat["room_openings"][0]["width_cm"] >= MIN_DOOR_WIDTH_CM


class TestFitClipsOversizeWindow:
    """Window wider than the new face is clipped with a warning."""

    def test_clips_window(self):
        # BLOCK_1: eo=80, ns=180 at orientation 0.
        # With spacing desk_to_wall=20, west face zone = 100 (70+30).
        # Min width = 100 (west) + 80 (eo) + 20 (east d2w) = 200 -> snap 200.
        # Window of 500 on north face at offset 0 forces width to 500.
        # But after fit, window of 500 > min 200.
        # To test clipping, we need a window whose offset+width > the
        # minimum room width AND that is NOT picked up by step 5 (which
        # increases the room to fit the feature).
        # Solution: put the window at a large offset so step 5 extends the
        # room, then the snap doesn't change it, but the window offset is
        # beyond the face.  Actually, step 5 always makes room >= feature.
        # Clipping only happens in step 8 when the pattern mutates the room
        # AFTER step 5 — which only occurs when a door is dropped or when
        # the feature constraint was at the exact snap boundary.
        #
        # Simplest scenario: test _revalidate_features directly with a
        # room that is SMALLER than the feature.
        from olm.core.pattern_fit import _revalidate_features

        pat = {
            "room_windows": [
                {"face": "north", "offset_cm": 0, "width_cm": 700},
            ],
            "room_openings": [],
            "room_exclusions": [],
        }
        warnings = _revalidate_features(pat, 400, 400)

        assert len(pat["room_windows"]) == 1
        assert pat["room_windows"][0]["width_cm"] == 400
        assert any("clipped" in w.lower() for w in warnings)


class TestFitSnapsTo10cm:
    """Output dimensions are always multiples of SNAP_CM."""

    def test_snap(self):
        pat = _pattern(room_w=800, room_d=600)
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)

        assert result.new_width % SNAP_CM == 0
        assert result.new_depth % SNAP_CM == 0


class TestFitTranslatesNegativeCoords:
    """Blocks with negative offsets are translated into [0, room]."""

    def test_negative_offset(self):
        pat = {
            "name": "NEG_OFFSET",
            "rows": [{"blocks": [
                {"type": "BLOCK_1", "orientation": 0,
                 "offset_ns_cm": -200},
            ]}],
            "row_gaps_cm": [],
            "room_width_cm": 500,
            "room_depth_cm": 500,
            "standard": "test_std",
            "room_windows": [],
            "room_openings": [],
            "room_exclusions": [],
        }
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)

        assert result.new_width > 0
        assert result.new_depth > 0
        assert result.new_width % SNAP_CM == 0
        assert result.new_depth % SNAP_CM == 0
        # After fit, the block should have a non-negative offset
        block = pat["rows"][0]["blocks"][0]
        assert block.get("offset_ns_cm", 0) >= 0


class TestFitSoftWarnings:
    """Soft violations produce warnings but don't block the fit."""

    def test_max_island_warning(self):
        pat = _pattern(block_type="BLOCK_6_FACE", room_w=800, room_d=800)
        sp = _spacing(max_island_size=4)  # 6 desks > 4
        result = fit_room_to_pattern(pat, sp)

        assert result.direction in ("shrink", "expand", "noop")
        assert any("max_island_size" in w for w in result.warnings)
