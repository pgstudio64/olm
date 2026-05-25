"""Tests for D-315 — door/window overflow clamping.

(3) room_from_json snaps offset+width <= wall length.
(2) _pattern_to_circulation_format clamps door entry defensively.
Non-regression: overflowing door no longer kills all candidates.
"""
from __future__ import annotations

from olm.core.catalogue_matcher import (
    _pattern_to_circulation_format,
    score_candidate,
)
from olm.core.room_model import Face, OpeningSpec, RoomSpec
from olm.server.services.serialization import room_from_json

# ---------------------------------------------------------------------------
# (3) room_from_json — snap windows and openings
# ---------------------------------------------------------------------------

class TestRoomFromJsonSnap:
    """Snap: offset+width <= wall for windows and openings."""

    def test_valid_opening_unchanged(self):
        """An opening that fits within the wall is untouched."""
        data = {
            "width_cm": 400, "depth_cm": 300,
            "openings": [{"face": "south", "offset_cm": 100, "width_cm": 90}],
        }
        room = room_from_json(data)
        o = room.openings[0]
        assert o.offset_cm == 100
        assert o.width_cm == 90

    def test_valid_window_unchanged(self):
        """A window that fits within the wall is untouched."""
        data = {
            "width_cm": 400, "depth_cm": 300,
            "windows": [{"face": "north", "offset_cm": 50, "width_cm": 200}],
        }
        room = room_from_json(data)
        w = room.windows[0]
        assert w.offset_cm == 50
        assert w.width_cm == 200

    def test_opening_overflow_south_snapped(self):
        """Opening on south wall (wall=width): offset slides to fit."""
        # wall=267, offset=180, width=89 → 180+89=269 > 267
        # Expected: width=89 (preserved), offset=min(180, 267-89)=178
        data = {
            "width_cm": 267, "depth_cm": 400,
            "openings": [{"face": "south", "offset_cm": 180, "width_cm": 89}],
        }
        room = room_from_json(data)
        o = room.openings[0]
        assert o.width_cm == 89
        assert o.offset_cm == 178
        assert o.offset_cm + o.width_cm == 267

    def test_opening_overflow_east_snapped(self):
        """Opening on east wall (wall=depth): offset slides to fit."""
        # wall=depth=300, offset=250, width=90 → 250+90=340 > 300
        # Expected: width=90, offset=min(250, 300-90)=210
        data = {
            "width_cm": 400, "depth_cm": 300,
            "openings": [{"face": "east", "offset_cm": 250, "width_cm": 90}],
        }
        room = room_from_json(data)
        o = room.openings[0]
        assert o.width_cm == 90
        assert o.offset_cm == 210
        assert o.offset_cm + o.width_cm == 300

    def test_window_overflow_north_snapped(self):
        """Window on north wall (wall=width): offset slides to fit."""
        # wall=width=300, offset=200, width=150 → 200+150=350 > 300
        # Expected: width=150, offset=min(200, 300-150)=150
        data = {
            "width_cm": 300, "depth_cm": 400,
            "windows": [{"face": "north", "offset_cm": 200, "width_cm": 150}],
        }
        room = room_from_json(data)
        w = room.windows[0]
        assert w.width_cm == 150
        assert w.offset_cm == 150
        assert w.offset_cm + w.width_cm == 300

    def test_window_overflow_west_snapped(self):
        """Window on west wall (wall=depth): offset slides to fit."""
        # wall=depth=250, offset=200, width=100 → 200+100=300 > 250
        # Expected: width=100, offset=min(200, 250-100)=150
        data = {
            "width_cm": 400, "depth_cm": 250,
            "windows": [{"face": "west", "offset_cm": 200, "width_cm": 100}],
        }
        room = room_from_json(data)
        w = room.windows[0]
        assert w.width_cm == 100
        assert w.offset_cm == 150
        assert w.offset_cm + w.width_cm == 250

    def test_width_exceeds_wall_truncated(self):
        """A door wider than the wall is truncated, offset=0."""
        # wall=200, width=300, offset=50
        # Expected: width=min(300,200)=200, offset=min(50, 200-200)=0
        data = {
            "width_cm": 200, "depth_cm": 400,
            "openings": [{"face": "south", "offset_cm": 50, "width_cm": 300}],
        }
        room = room_from_json(data)
        o = room.openings[0]
        assert o.width_cm == 200
        assert o.offset_cm == 0

    def test_negative_offset_clamped(self):
        """A negative offset is clamped to 0."""
        data = {
            "width_cm": 400, "depth_cm": 300,
            "openings": [{"face": "south", "offset_cm": -20, "width_cm": 90}],
        }
        room = room_from_json(data)
        o = room.openings[0]
        assert o.offset_cm == 0
        assert o.width_cm == 90

    def test_zero_wall_degenerate(self):
        """Degenerate room (wall=0) → opening has width=0, offset=0."""
        data = {
            "width_cm": 0, "depth_cm": 300,
            "openings": [{"face": "south", "offset_cm": 10, "width_cm": 90}],
        }
        room = room_from_json(data)
        o = room.openings[0]
        assert o.width_cm == 0
        assert o.offset_cm == 0


# ---------------------------------------------------------------------------
# (2) _pattern_to_circulation_format — defensive clamp
# ---------------------------------------------------------------------------

class TestCirculationFormatClamp:
    """Clamp door entry in _pattern_to_circulation_format."""

    @staticmethod
    def _make_simple_pattern() -> dict:
        """Minimal pattern with one BLOCK_1 for circulation."""
        return {
            "name": "test",
            "standard": "standard1",
            "room_width_cm": 400,
            "room_depth_cm": 400,
            "rows": [{"blocks": [
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 0,
                 "offset_ns_cm": 0},
            ]}],
        }

    def test_overflowing_door_clamped(self):
        """A door that overflows the wall has width clamped."""
        room = RoomSpec(
            width_cm=267, depth_cm=400,
            openings=[
                OpeningSpec(Face.SOUTH, offset_cm=180, width_cm=89,
                            has_door=True),
            ],
        )
        pattern = self._make_simple_pattern()
        room_dict, _ = _pattern_to_circulation_format(pattern, room)
        door = room_dict["doors"][0]
        # off = max(0, 180) = 180
        # w = min(89, max(0, 267 - 180)) = min(89, 87) = 87
        assert door["position_cm"] == 180
        assert door["width_cm"] == 87
        assert door["position_cm"] + door["width_cm"] <= 267

    def test_valid_door_unchanged(self):
        """A door within the wall is not modified."""
        room = RoomSpec(
            width_cm=400, depth_cm=300,
            openings=[
                OpeningSpec(Face.SOUTH, offset_cm=100, width_cm=90,
                            has_door=True),
            ],
        )
        pattern = self._make_simple_pattern()
        room_dict, _ = _pattern_to_circulation_format(pattern, room)
        door = room_dict["doors"][0]
        assert door["position_cm"] == 100
        assert door["width_cm"] == 90

    def test_east_door_clamped(self):
        """Door on east wall (wall=depth) is clamped."""
        room = RoomSpec(
            width_cm=400, depth_cm=300,
            openings=[
                OpeningSpec(Face.EAST, offset_cm=250, width_cm=90,
                            has_door=True),
            ],
        )
        pattern = self._make_simple_pattern()
        room_dict, _ = _pattern_to_circulation_format(pattern, room)
        door = room_dict["doors"][0]
        # off = 250, wall = 300, w = min(90, max(0, 300-250)) = min(90, 50) = 50
        assert door["position_cm"] == 250
        assert door["width_cm"] == 50


# ---------------------------------------------------------------------------
# Non-regression: overflowing door → reachability > 0 → candidates > 0
# ---------------------------------------------------------------------------

class TestOverflowingDoorNonRegression:
    """A room with an overflowing door must still produce candidates."""

    def test_overflowing_door_produces_valid_circulation(self):
        """Reproduce bug: door overflows wall → circulation entry valid.

        Room 400 wide, door S offset=350 width=90 → 350+90=440 > 400.
        After snap (3), offset becomes 310 (350→min(350,400-90)=310).
        The scored candidate must have dim_reachability > 0 (not grade F).
        """
        # Build the room via room_from_json (snap applies)
        data = {
            "width_cm": 400, "depth_cm": 400,
            "openings": [
                {"face": "south", "offset_cm": 350, "width_cm": 90,
                 "has_door": True, "opens_inward": True, "hinge_side": "left"},
            ],
        }
        room = room_from_json(data)
        # Verify snap happened
        assert room.openings[0].offset_cm == 310
        assert room.openings[0].width_cm == 90

        # Minimal pattern that fits in 400x400
        pattern = {
            "name": "1P_face_sud",
            "standard": "standard1",
            "room_width_cm": 400,
            "room_depth_cm": 400,
            "rows": [{"blocks": [
                {"type": "BLOCK_1", "orientation": 0, "gap_cm": 0,
                 "offset_ns_cm": 0},
            ]}],
            "room_openings": [
                {"face": "south", "offset_cm": 310, "width_cm": 90,
                 "has_door": True, "opens_inward": True,
                 "hinge_side": "left"},
            ],
        }

        score = score_candidate(pattern, room, "standard1")
        assert score.dim_reachability is not None
        assert score.dim_reachability > 0, (
            "Room with snapped overflowing door must have reachability > 0, "
            f"got {score.dim_reachability}"
        )
