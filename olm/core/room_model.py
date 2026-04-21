"""Canonical room model.

Source of truth for room descriptions in the static pipeline.
Aligned with the glossary (specs/GLOSSARY.md) and the NW-origin coordinate
convention (x EAST, y SOUTH). All dimensions in centimetres.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Face(str, Enum):
    """Face of a room (wall carrying a window, door or opening)."""
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"


class HingeSide(str, Enum):
    """Hinge side as seen from inside the room."""
    LEFT = "left"
    RIGHT = "right"


@dataclass
class WindowSpec:
    """Window on a room face.

    Attributes:
        face: Wall carrying the window.
        offset_cm: Distance from the west end (N/S faces) or north end (E/W faces).
        width_cm: Window width.
        origin: "auto" (detected) or "manual" (user-edited). D-131: persisted
            in JSON v3 so that Re-analyze preserves user edits across sessions.
    """
    face: Face
    offset_cm: int
    width_cm: int
    origin: str | None = None


@dataclass
class OpeningSpec:
    """Opening in a wall (hinged door or free passage).

    Attributes:
        face: Wall carrying the opening.
        offset_cm: Distance from the west end (N/S faces) or north end (E/W faces).
        width_cm: Opening width (default 90 cm).
        has_door: True if hinged door, False if free passage.
        opens_inward: Opening direction (True = inward). Ignored if has_door=False.
        hinge_side: Hinge side as seen from inside. Ignored if has_door=False.
        origin: "auto" (detected) or "manual" (user-edited). D-131.
    """
    face: Face
    offset_cm: int
    width_cm: int = 90
    has_door: bool = True
    opens_inward: bool = True
    hinge_side: HingeSide = HingeSide.LEFT
    origin: str | None = None


@dataclass
class ExclusionZone:
    """Zone forbidden for desk placement and circulation.

    Three possible origins:
    - Physical obstacle (column, technical shaft)
    - Geometric virtual zone (L/T/U-shaped room inscribed in its bounding rectangle)
    - Door swing zone (generated automatically by the pipeline)

    Attributes:
        x_cm: North-west corner, east axis.
        y_cm: North-west corner, south axis.
        width_cm: Dimension west to east.
        depth_cm: Dimension north to south.
        physical: True = physical obstacle; False = geometric virtual zone.
    """
    x_cm: int
    y_cm: int
    width_cm: int
    depth_cm: int
    physical: bool = True


@dataclass
class RoomSpec:
    """Complete room specification in centimetres.

    Local coordinate system: origin = north-west corner, x east, y south.
    Convention: main windows face north, corridor/door faces south.

    Attributes:
        width_cm: Dimension west to east.
        depth_cm: Dimension north to south.
        windows: Windows of the room.
        openings: Openings (hinged doors or free passages).
        exclusion_zones: Zones excluded from desk placement.
        name: Free-form name (e.g. "B.4.12").
        code: Regulatory code ("14" = open-space candidate).
        direction: Orientation of main windows in the building plan.
        raster_nw_x_px: North-west corner in the global raster frame, east axis (pixels).
        raster_nw_y_px: North-west corner in the global raster frame, south axis (pixels).
    """
    width_cm: int
    depth_cm: int
    windows: list[WindowSpec] = field(default_factory=list)
    openings: list[OpeningSpec] = field(default_factory=list)
    exclusion_zones: list[ExclusionZone] = field(default_factory=list)
    transparent_zones: list[ExclusionZone] = field(default_factory=list)
    name: str = ""
    code: str = "14"
    direction: Face | None = None
    raster_nw_x_px: int = 0
    raster_nw_y_px: int = 0

    @property
    def area_m2(self) -> float:
        """Gross area in m²."""
        return (self.width_cm * self.depth_cm) / 10_000

    @property
    def net_area_m2(self) -> float:
        """Net area (gross minus exclusion zones) in m²."""
        excluded = sum(z.width_cm * z.depth_cm for z in self.exclusion_zones)
        return (self.width_cm * self.depth_cm - excluded) / 10_000


@dataclass
class FloorPlan:
    """Set of rooms on a floor.

    Attributes:
        rooms: Rooms on the floor.
        building_angle_deg: Building angle relative to true north (degrees).
        scale_cm_per_px: Scale of the raster plan.
    """
    rooms: list[RoomSpec] = field(default_factory=list)
    building_angle_deg: float = 0.0
    scale_cm_per_px: float = 0.0
