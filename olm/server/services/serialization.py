"""Serialization helpers — RoomSpec ↔ JSON conversion.

Factorizes the duplicated conversion code formerly in ``app.py``
(``api_floor_plan_match`` and ``api_coverage``).
"""
from __future__ import annotations

from olm.core.room_model import (
    ExclusionZone,
    Face,
    HingeSide,
    OpeningSpec,
    RoomSpec,
    WindowSpec,
)


def room_from_json(data: dict) -> RoomSpec:
    """Build a ``RoomSpec`` from a JSON dict (API payload format).

    Skips windows/openings entries without a ``face`` key (D-141: entries
    not yet enriched by the detection pipeline).

    Args:
        data: dict with ``width_cm``, ``depth_cm``, and optional
              ``windows``, ``openings``, ``exclusion_zones``, ``name``.

    Returns:
        Fully constructed ``RoomSpec``.
    """
    room_w = data["width_cm"]
    room_d = data["depth_cm"]

    windows = []
    for w in data.get("windows", []):
        if "face" not in w or "offset_cm" not in w or "width_cm" not in w:
            continue
        face = Face(w["face"])
        wall = room_w if face in (Face.NORTH, Face.SOUTH) else room_d
        width = min(w["width_cm"], wall)
        offset = max(0, min(w["offset_cm"], wall - width))
        windows.append(WindowSpec(face, offset, width, origin=w.get("origin")))

    openings = []
    for o in data.get("openings", []):
        if "face" not in o or "offset_cm" not in o:
            continue
        face = Face(o["face"])
        wall = room_w if face in (Face.NORTH, Face.SOUTH) else room_d
        width = min(o.get("width_cm", 90), wall)
        offset = max(0, min(o["offset_cm"], wall - width))
        openings.append(OpeningSpec(
            face, offset, width,
            o.get("has_door", True),
            o.get("opens_inward", True),
            HingeSide(o.get("hinge_side", "left")),
            origin=o.get("origin"),
        ))
    exclusions = [
        ExclusionZone(
            x_cm=z["x_cm"], y_cm=z["y_cm"],
            width_cm=z["width_cm"], depth_cm=z["depth_cm"],
        )
        for z in data.get("exclusion_zones", [])
    ]
    return RoomSpec(
        width_cm=data["width_cm"], depth_cm=data["depth_cm"],
        windows=windows, openings=openings,
        exclusion_zones=exclusions, name=data.get("name", ""),
    )


def room_to_json(room: RoomSpec) -> dict:
    """Serialize a ``RoomSpec`` to a JSON-compatible dict.

    Args:
        room: the room to serialize.

    Returns:
        Dict with ``name``, ``width_cm``, ``depth_cm``, ``windows``,
        ``openings``, ``exclusion_zones``.
    """
    return {
        "name": room.name,
        "width_cm": room.width_cm,
        "depth_cm": room.depth_cm,
        "windows": [
            {"face": w.face.value, "offset_cm": w.offset_cm,
             "width_cm": w.width_cm,
             **({"origin": w.origin} if w.origin else {})}
            for w in room.windows
        ],
        "openings": [
            {"face": o.face.value, "offset_cm": o.offset_cm,
             "width_cm": o.width_cm, "has_door": o.has_door,
             "opens_inward": o.opens_inward,
             "hinge_side": o.hinge_side.value,
             **({"origin": o.origin} if o.origin else {})}
            for o in room.openings
        ],
        "exclusion_zones": [
            {"x_cm": z.x_cm, "y_cm": z.y_cm,
             "width_cm": z.width_cm, "depth_cm": z.depth_cm}
            for z in room.exclusion_zones
        ],
    }
