"""Tests for olm.core.pattern_fit — fit room to pattern."""
from __future__ import annotations

import copy

import pytest

from olm.core.pattern_fit import (
    MIN_DOOR_WIDTH_CM,
    SNAP_CM,
    FitResult,
    PatternStructurallyInvalid,
    compute_pattern_footprint,
    fit_room_to_pattern,
    is_pattern_valid,
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
        # D-244: E/W faces have non_superposable=70, candidate=30 (slip-in).
        # N/S faces absent -> 0.
        # Expected width = 100 + 160 + 100 = 360
        # Expected depth = 0 + 360 + 0 = 360
        pat = _pattern(room_w=800, room_d=600)
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)

        assert result.direction == "shrink"
        assert result.new_width == 360
        assert result.new_depth == 360
        assert pat["room_width_cm"] == 360
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
    """South door becomes a 2D obstacle: blocks in the door's lateral
    range must clear ``door_exclusion_depth_cm`` from the south wall."""

    def test_south_door_pushes_depth_for_block_in_band(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("south", offset_cm=0, width_cm=90)],
        )
        sp = _spacing()
        # Block: x=[-100, 260], y=[0, 360]. Door lat=[0,90] overlaps block
        # lat → south wall pushed: y_max = 360 + 0 + 180 = 540.
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width == 360
        assert result.new_depth == 540


class TestDoorExclusionNorth:
    """North door pushes the north wall away from blocks in its band."""

    def test_door_rect_north(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("north", offset_cm=0, width_cm=360)],
        )
        sp = _spacing()
        # Block lat [-100,260] overlaps door [0,360]: y_min = -180.
        # Width: x_max = max(block 260, door 360) = 360.
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width == 460
        assert result.new_depth == 540


class TestDoorExclusionEast:
    """East door pushes the east wall away from blocks in its band."""

    def test_east_door_pushes_width_for_block_in_band(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("east", offset_cm=0, width_cm=360)],
        )
        sp = _spacing()
        # Block lat (y) [0,360] overlaps door [0,360]: x_max pushed to
        # 0 + 160 + 100 + 180 = 440. Width = 440 - (-100) = 540.
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width == 540
        assert result.new_depth == 360


class TestDoorExclusionWest:
    """West door pushes the west wall away from blocks in its band."""

    def test_door_rect_west(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800,
            room_d=800,
            openings=[_door_opening("west", offset_cm=0, width_cm=360)],
        )
        sp = _spacing()
        # Block lat (y) [0,360] overlaps door [0,360]: x_min pushed to
        # 0 - 100 - 180 = -280. Width = 260 - (-280) = 540.
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width == 540


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
        # Same as without any door: 360x360 (D-244)
        assert result.new_width == 360
        assert result.new_depth == 360


class TestNoDoorRegression:
    """Case 12: pattern without doors — original behavior preserved."""

    def test_no_door_same_as_before(self):
        pat = _pattern(room_w=800, room_d=600)
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width == 360
        assert result.new_depth == 360


class TestDoorAtCorner:
    """Door at offset=0 (corner) with block at x=0: south wall pushed."""

    def test_corner_door(self):
        # BLOCK_1 x=[-100,80] y=[0,180]. Door south [0,90] overlaps block
        # → y_max pushed to 0+180+0+180 = 360. Width = max(80,90)-(-100)=190.
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=800,
            room_d=800,
            openings=[_door_opening("south", offset_cm=0, width_cm=90)],
        )
        sp = _spacing()
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width == 190
        assert result.new_depth == 360


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
        # Block lat [-100,260] overlaps both door bands. Both push y_max
        # to 540 (same value). Width: door2 [200,290] extends x_max to 290.
        # Width = 290 - (-100) = 390.
        result = fit_room_to_pattern(pat, sp)
        assert result.new_width == 390
        assert result.new_depth == 540


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


class TestComputePatternFootprintPure:
    """The pure footprint function does not mutate the pattern and
    returns the raw bbox (no snap, no translation)."""

    def test_returns_raw_bbox(self):
        pat = _pattern(block_type="BLOCK_4_FACE", room_w=800, room_d=800)
        sp = _spacing()
        snapshot = copy.deepcopy(pat)
        x_min, x_max, y_min, y_max = compute_pattern_footprint(pat, sp)
        # BLOCK_4_FACE: body 160x360, west/east chair=70+slip=30=100.
        assert (x_min, x_max, y_min, y_max) == (-100, 260, 0, 360)
        # Pure: no mutation.
        assert pat == snapshot

    def test_door_pushback_in_footprint(self):
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800, room_d=800,
            openings=[_door_opening("south", offset_cm=0, width_cm=90)],
        )
        sp = _spacing()
        x_min, x_max, y_min, y_max = compute_pattern_footprint(pat, sp)
        # South door overlaps block lat → y_max = 360 + 180 = 540.
        assert y_max == 540


class TestIsPatternValid:
    """is_pattern_valid: footprint must fit inside room dimensions."""

    def test_valid_when_room_covers_footprint(self):
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=300, room_d=300,
        )
        # Shift block east so chair+slip zone stays inside the room.
        pat["rows"][0]["blocks"][0]["gap_cm"] = 100
        assert is_pattern_valid(pat, _spacing())

    def test_invalid_when_chair_extends_past_wall(self):
        # BLOCK_1 at gap_cm=0: chair extends to x=-70, outside the room.
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=300, room_d=300,
        )
        assert not is_pattern_valid(pat, _spacing())

    def test_invalid_when_door_pushback_overflows(self):
        # South door pushes y_max by 180. Room must be at least 360.
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=300, room_d=200,  # depth too small
            openings=[_door_opening("south", offset_cm=80, width_cm=90)],
        )
        pat["rows"][0]["blocks"][0]["gap_cm"] = 70
        assert not is_pattern_valid(pat, _spacing())

    def test_invalid_on_structural_overlap(self):
        pat = _pattern(
            block_type="BLOCK_1",
            room_w=500, room_d=500,
            extra_blocks=[{"type": "BLOCK_1", "gap_cm": -40}],
        )
        assert not is_pattern_valid(pat, _spacing())


# ---------------------------------------------------------------------------
# D-241: ORTHO internal face zones
# ---------------------------------------------------------------------------


class TestOrthoInternalFaceZones:
    """ORTHO blocks with internal faces pass is_pattern_valid."""

    def test_ortho_r_no_east_outer_clearance(self):
        """ORTHO_R east face is internal → does NOT extend footprint east."""
        # BLOCK_2_ORTHO_R: eo=180, ns=260. chair+slip=100.
        # North face (external): extends 100 north
        # East face (internal): 0 outer → NO east extension
        pat = _pattern(
            block_type="BLOCK_2_ORTHO_R",
            room_w=180, room_d=360,
        )
        sp = _spacing()
        x_min, x_max, y_min, y_max = compute_pattern_footprint(pat, sp)
        assert x_min == 0
        assert x_max == 180  # no east clearance (internal)
        assert y_min == -100  # north chair+slip clearance
        assert y_max == 260  # no south clearance

    def test_ortho_r_valid_tight_room(self):
        """ORTHO_R fits in a room with no east margin."""
        pat = _pattern(
            block_type="BLOCK_2_ORTHO_R",
            room_w=180, room_d=360,
        )
        sp = _spacing()
        x_min, x_max, y_min, y_max = compute_pattern_footprint(pat, sp)
        fp_w = x_max - x_min  # 180
        fp_d = y_max - y_min  # 360
        assert fp_w <= 180
        assert fp_d <= 360

    def test_ortho_l_no_west_outer_clearance(self):
        """ORTHO_L west face is internal → does NOT extend footprint west."""
        pat = _pattern(
            block_type="BLOCK_2_ORTHO_L",
            room_w=180, room_d=360,
        )
        sp = _spacing()
        x_min, x_max, y_min, y_max = compute_pattern_footprint(pat, sp)
        assert x_min == 0   # no west clearance (internal)
        assert x_max == 180
        assert y_min == -100  # north chair+slip clearance
        assert y_max == 260


# ---------------------------------------------------------------------------
# D-243 F1: outward door uses walking_margin_cm
# ---------------------------------------------------------------------------


class TestOutwardDoorExclusion:
    """An outward door uses walking_margin_cm instead of
    door_exclusion_depth_cm for its perpendicular pushback."""

    def test_outward_south_door_uses_walking_margin(self):
        """Outward south door: pushback = walking_margin_cm (90),
        not door_exclusion_depth_cm (180)."""
        door = _door_opening("south", offset_cm=0, width_cm=90)
        door["opens_inward"] = False
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800, room_d=800,
            openings=[door],
        )
        sp = _spacing()  # walking_margin_cm=90, door_exclusion_depth_cm=180
        x_min, x_max, y_min, y_max = compute_pattern_footprint(pat, sp)
        # Inward would give y_max = 360 + 180 = 540.
        # Outward gives y_max = 360 + 90 = 450.
        assert y_max == 450

    def test_inward_south_door_still_uses_excl_depth(self):
        """Inward south door: pushback = door_exclusion_depth_cm (180)."""
        pat = _pattern(
            block_type="BLOCK_4_FACE",
            room_w=800, room_d=800,
            openings=[_door_opening("south", offset_cm=0, width_cm=90)],
        )
        sp = _spacing()
        x_min, x_max, y_min, y_max = compute_pattern_footprint(pat, sp)
        assert y_max == 540
