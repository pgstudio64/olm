"""Tests for room_model.py."""
from olm.core.room_model import (
    Face, HingeSide, WindowSpec, OpeningSpec, ExclusionZone, RoomSpec, FloorPlan,
)


def test_room_area_m2():
    room = RoomSpec(width_cm=550, depth_cm=500)
    assert room.area_m2 == 27.5


def test_room_net_area_with_exclusion():
    room = RoomSpec(
        width_cm=600,
        depth_cm=500,
        exclusion_zones=[ExclusionZone(x_cm=0, y_cm=0, width_cm=200, depth_cm=200)],
    )
    assert room.area_m2 == 30.0
    assert room.net_area_m2 == 26.0


def test_room_defaults():
    room = RoomSpec(width_cm=400, depth_cm=300)
    assert room.windows == []
    assert room.openings == []
    assert room.exclusion_zones == []
    assert room.code == "14"
    assert room.direction is None


def test_opening_defaults():
    op = OpeningSpec(face=Face.SOUTH, offset_cm=200)
    assert op.width_cm == 90
    assert op.has_door is True
    assert op.opens_inward is True
    assert op.hinge_side == HingeSide.LEFT


def test_opening_free():
    op = OpeningSpec(face=Face.SOUTH, offset_cm=100, width_cm=150, has_door=False)
    assert op.has_door is False


def test_window_spec():
    w = WindowSpec(face=Face.NORTH, offset_cm=50, width_cm=200)
    assert w.face == Face.NORTH
    assert w.offset_cm == 50


def test_opening_origin_default_none():
    op = OpeningSpec(face=Face.SOUTH, offset_cm=200)
    assert op.origin is None


def test_opening_origin_manual():
    op = OpeningSpec(face=Face.SOUTH, offset_cm=200, origin="manual")
    assert op.origin == "manual"


def test_window_origin_manual():
    w = WindowSpec(face=Face.NORTH, offset_cm=50, width_cm=200, origin="manual")
    assert w.origin == "manual"


def test_exclusion_zone_physical():
    z = ExclusionZone(x_cm=100, y_cm=100, width_cm=80, depth_cm=80)
    assert z.physical is True


def test_exclusion_zone_fictive():
    z = ExclusionZone(x_cm=0, y_cm=0, width_cm=300, depth_cm=200, physical=False)
    assert z.physical is False


def test_floor_plan_defaults():
    fp = FloorPlan()
    assert fp.rooms == []
    assert fp.building_angle_deg == 0.0
    assert fp.scale_cm_per_px == 0.0


def test_room_raster_defaults():
    room = RoomSpec(width_cm=400, depth_cm=300)
    assert room.raster_nw_x_px == 0
    assert room.raster_nw_y_px == 0


def test_room_raster_position():
    room = RoomSpec(width_cm=400, depth_cm=300, raster_nw_x_px=150, raster_nw_y_px=220)
    assert room.raster_nw_x_px == 150
    assert room.raster_nw_y_px == 220


def test_complete_room():
    """Realistic room with windows, door, and exclusion zone."""
    room = RoomSpec(
        width_cm=550,
        depth_cm=500,
        windows=[
            WindowSpec(face=Face.NORTH, offset_cm=50, width_cm=200),
            WindowSpec(face=Face.NORTH, offset_cm=300, width_cm=200),
        ],
        openings=[
            OpeningSpec(face=Face.SOUTH, offset_cm=230, width_cm=90,
                        has_door=True, opens_inward=True, hinge_side=HingeSide.LEFT),
        ],
        exclusion_zones=[
            ExclusionZone(x_cm=250, y_cm=200, width_cm=50, depth_cm=50, physical=True),
        ],
        name="B.4.12",
        code="14",
        direction=Face.NORTH,
    )
    assert room.area_m2 == 27.5
    assert len(room.windows) == 2
    assert len(room.openings) == 1
    assert room.openings[0].hinge_side == HingeSide.LEFT
    assert len(room.exclusion_zones) == 1
    assert room.exclusion_zones[0].physical is True
