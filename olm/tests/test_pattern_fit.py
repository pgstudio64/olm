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
    """Build a SpacingConfig with sensible defaults (D-229)."""
    defaults = {
        "name": "test_std",
        "chair_clearance_cm": 70,
        "walking_margin_cm": 90,
        "slip_in_margin_cm": 30,
        "main_corridor_cm": 160,
        "door_exclusion_depth_cm": 180,
        "max_island_size": 6,
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
        # D-229: E/W faces have non_superposable=70, candidate=0.
        # N/S faces absent -> 0 (no desk_to_wall).
        # Expected width = 70 + 160 + 70 = 300
        # Expected depth = 0 + 360 + 0 = 360
        pat = _pattern(room_w=800, room_d=600)
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)

        assert result.direction == "shrink"
        assert result.new_width == 300
        assert result.new_depth == 360
        assert pat["room_width_cm"] == 300
        assert pat["room_depth_cm"] == 360


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
        # D-229: west face zone = 70 (chair only).
        # Min width = 70 (west) + 80 (eo) + 0 (east) = 150.
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
    """Case 7: south door constrains X axis only."""

    def test_south_door_constrains_x_not_depth(self):
        """BLOCK_4_FACE at origin with door on south face.
        Door constrains X=[0, 90] but does not extend depth
        (door moves with the south wall)."""
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("south", offset_cm=0, width_cm=90)],
        )
        sp = _spacing()
        # D-229: x=[-70, 230], y=[0, 360].
        # Door only adds x=[0, 90] — inside block range.
        result = fit_room_to_pattern(pat, sp)
        assert result.new_depth == 360
        assert result.new_width == 300


class TestDoorExclusionNorth:
    """Case 8: door on north face — door rect included in bbox."""

    def test_door_rect_north(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("north", offset_cm=0, width_cm=360)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        # D-229: Block footprint y=[0, 360]. Door rect y=[0, 180].
        # Block extends past door rect. bbox unchanged. depth=360.
        assert result.new_depth == 360


class TestDoorExclusionEast:
    """Case 9: east door constrains Y axis only."""

    def test_east_door_constrains_y_not_width(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("east", offset_cm=0, width_cm=360)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        # D-229: Door y=[0,360] inside block range [0,360].
        # width = 230-(-70) = 300.
        assert result.new_width == 300
        assert result.new_depth == 360


class TestDoorExclusionWest:
    """Case 10: door on west face — door rect included in bbox."""

    def test_door_rect_west(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("west", offset_cm=0, width_cm=360)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        # D-229: Block footprint x=[-70, 230].
        # Door rect x=[0,180] inside block range.
        # width = 230-(-70) = 300.
        assert result.new_width == 300


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
        # Same as without any door: 300x360 (D-229)
        assert result.new_width == 300
        assert result.new_depth == 360


class TestNoDoorRegression:
    """Case 12: pattern without doors — original behavior preserved."""

    def test_no_door_same_as_before(self):
        pat = _pattern(room_w=800, room_d=600)
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width == 300
        assert result.new_depth == 360


class TestDoorAtCorner:
    """Case 13: door at offset=0 (corner) with block at x=0."""

    def test_corner_door(self):
        # D-229: BLOCK_1 at x=0: eo=80, west zone=70, east=0.
        # x=[-70, 80]. Door south at offset=0, width=90.
        # Door adds x=[0, 90] — extends x_max to 90.
        # width = 90-(-70) = 160 -> snap 160. depth = 180.
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=800,
            room_d=800,
            openings=[_door_opening("south", offset_cm=0, width_cm=90)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width == 160
        assert result.new_depth == 180


class TestDoorFullWidth:
    """Case 14: full-width door — treated as extensible, no X constraint."""

    def test_full_width_door(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("south", offset_cm=0, width_cm=800)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        # Door x=[0, 800] is full-width. It extends x_maxs to 800.
        # But block footprint x=[-160, 320]. So width = 800-(-160)=960.
        # With feature_constraints: full-width door adapts → width stays.
        # Actually door is has_door=True so feature_constraints continues.
        # Door x_max=800 extends bbox. width = 960.
        assert result.new_width >= 800


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
        # D-229: block range [-70, 230]. Door2 x=[200,290] extends
        # x_max to 290. width = 290-(-70) = 360 -> snap 360.
        assert result.new_width == 360
        assert result.new_depth == 360


class TestDoorNoBlockInBand:
    """Case 16: door on a face with no block in the door's band."""

    def test_door_far_from_blocks(self):
        # D-229: BLOCK_1 at x=0 (effective x range [-70, 80]).
        # Door south at offset=500, width=90.
        # Door extends x_max to 590. width = 590-(-70) = 660.
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=800,
            room_d=800,
            openings=[_door_opening("south", offset_cm=500, width_cm=90)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width >= 590
        assert result.new_depth >= 180


class TestDoorRectWithGap:
    """Case 17: block with gap_cm>0 — door rect prevents over-shrink.

    BLOCK_1 at gap_cm=220 in a 300x300 room with a south door at
    offset=0 width=90.  Door rect at x=[0, 90] prevents the west
    wall from shrinking past x=0, keeping room wide enough for
    the door.
    """

    def test_door_rect_preserves_width(self):
        # D-229: BLOCK_1 west=70, east=0.
        # At gap_cm=220: x_cm=220. eff x=[150, 300].
        # Door rect south: x=[0, 90].
        # bbox_x_min = min(150, 0) = 0. width = 300-0 = 300.
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=300,
            room_d=300,
            openings=[_door_opening("south", offset_cm=0, width_cm=90)],
        )
        pat["rows"][0]["blocks"][0]["gap_cm"] = 220
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width >= 300, (
            f"Expected width >= 300 but got {result.new_width}"
        )


class TestDoorRectBetweenBlocks:
    """Case 18: door rect between two blocks.

    Two BLOCK_1 in one row separated by gap_cm=400.  Door south at
    offset=200 width=90.  Door rect included in bbox like any obstacle.
    """

    def test_door_rect_between_blocks(self):
        # D-229: Block 1 at x=0: bx=[-70, 80].
        # Block 2 at x=480: bx=[480, 560].
        # Door rect south: x=[200, 290].
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=800,
            room_d=800,
            extra_blocks=[{"type": "BLOCK_1", "gap_cm": 400}],
            openings=[_door_opening("south", offset_cm=200, width_cm=90)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        assert result.new_depth >= 180


class TestDoorMinFace:
    """Case 19: door wider than computed face — face forced to door width.

    D-229: BLOCK_1 alone gives width=150 (70+80+0). A south door of
    width=250 must force the room width to at least 250.
    """

    def test_face_forced_to_door_width(self):
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=800,
            room_d=800,
            openings=[_door_opening("south", offset_cm=0, width_cm=250)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        # Door rect x=[0, 250] extends bbox beyond block footprint.
        assert result.new_width >= 250, (
            f"Expected width >= 250 but got {result.new_width}"
        )
