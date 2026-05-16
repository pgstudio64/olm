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


# ---------------------------------------------------------------------------
# Door exclusion zone tests (Anomaly 3, D-208)
# ---------------------------------------------------------------------------


def _door_opening(
    face: str,
    offset_cm: int = 0,
    width_cm: int = 90,
) -> dict:
    """Build a door opening dict for test patterns."""
    return {
        "face": face,
        "offset_cm": offset_cm,
        "width_cm": width_cm,
        "has_door": True,
        "opens_inward": True,
        "hinge_side": "left",
    }


class TestDoorExclusionSouth:
    """Case 7: door on south face — room depth extended."""

    def test_block_in_door_band_extends_depth(self):
        """BLOCK_4_FACE at origin with door on south face.
        Block occupies the band x=[0, 360].
        Door at offset=0, width=90 overlaps the band.
        Depth must accommodate block + face zones + exclusion."""
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("south", offset_cm=0, width_cm=90)],
        )
        sp = _spacing()
        # Without door exclusion: depth = 400 (20 + 360 + 20)
        # With door exclusion 180: the block's y_max (with eff_s=20)
        # is at y=20+360+20=400. Door extends to 400+180=580.
        # Snap: 580 -> 580 (already aligned).
        result = fit_room_to_pattern(pat, sp)
        assert result.new_depth >= 580
        assert any("door" in w.lower() for w in result.warnings)


class TestDoorExclusionNorth:
    """Case 8: door on north face — room depth extended."""

    def test_block_in_door_band_extends_north(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("north", offset_cm=0, width_cm=360)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        # Block with eff_n=20 has y_min at -20 (relative).
        # Door extends to y_min - 180 = -200. bbox_y_min = -200.
        # Total depth increases by 180.
        assert result.new_depth >= 580


class TestDoorExclusionEast:
    """Case 9: door on east face — room width extended."""

    def test_extends_width(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("east", offset_cm=0, width_cm=360)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        # Block east zone = 160, x_max = 0+160+160 = 320.
        # Door on east: max_x_in_band = 320, required = 320+180 = 500.
        # Total width = 500 - (-160) = 660 -> snap 660.
        assert result.new_width >= 660


class TestDoorExclusionWest:
    """Case 10: door on west face — room width extended."""

    def test_extends_width(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("west", offset_cm=0, width_cm=360)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        # Block west zone = 160, x_min = -160.
        # Door on west: min_x_in_band = -160, required = -160-180 = -340.
        # Total width = 320 - (-340) = 660 -> snap 660.
        assert result.new_width >= 660


class TestOpeningWithoutDoor:
    """Case 11: opening without has_door — no exclusion zone."""

    def test_no_extension(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[{
                "face": "south", "offset_cm": 0, "width_cm": 90,
                "has_door": False,
            }],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        # Same as without any door: 480x400
        assert result.new_width == 480
        assert result.new_depth == 400


class TestNoDoorRegression:
    """Case 12: pattern without doors — original behavior preserved."""

    def test_no_door_same_as_before(self):
        pat = _pattern(room_w=800, room_d=600)
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width == 480
        assert result.new_depth == 400


class TestDoorAtCorner:
    """Case 13: door at offset=0 (corner) with block at x=0."""

    def test_corner_door(self):
        # BLOCK_1 at x=0: eo=80, west zone=100, east zone=20
        # Door south at offset=0, width=90.
        # Block effective x range: [-100, 100]. Overlaps [0, 90].
        # Block y_max with eff_s=20: 0+180+20=200.
        # Required: 200+180=380. Depth >= 380.
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=800,
            room_d=800,
            openings=[_door_opening("south", offset_cm=0, width_cm=90)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        assert result.new_depth >= 380


class TestDoorFullWidth:
    """Case 14: door covering the entire face width."""

    def test_full_width_door(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("south", offset_cm=0, width_cm=800)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        # All blocks are in the band. Same as case 7.
        assert result.new_depth >= 580


class TestMultipleDoorsOnSameFace:
    """Case 15: two doors on the same face — most constraining wins."""

    def test_two_doors_south(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[
                _door_opening("south", offset_cm=0, width_cm=90),
                _door_opening("south", offset_cm=200, width_cm=90),
            ],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        # Both doors overlap the block band [offset-100, offset+eo+160].
        # Both require depth >= 580.
        assert result.new_depth >= 580


class TestDoorNoBlockInBand:
    """Case 16: door on a face with no block in the door's band."""

    def test_no_extension_when_no_block_in_band(self):
        # BLOCK_1 at x=0 (effective x range [-100, 100]).
        # Door south at offset=500, width=90 (band [500, 590]).
        # No block overlaps this band => no extension.
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=800,
            room_d=800,
            openings=[_door_opening("south", offset_cm=500, width_cm=90)],
        )
        sp = _spacing()
        # Without door exclusion: width=200, depth=220 (snap).
        # Door at offset 500 forces width via feature_constraints (500+90=590).
        # But no block in door band => no depth extension beyond 220.
        result = fit_room_to_pattern(pat, sp)
        assert result.new_depth == 220
