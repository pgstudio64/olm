"""Room DSL parser and serializer.

Grammar:
    ROOM <width> x <depth>
    WINDOW <face> <offset> <width>
    DOOR <face> <offset> <width> INT|EXT L|R
    OPENING <face> <offset> <width>
    EXCLUSION <x> <y> <width> <depth>
    TRANSPARENT <x> <y> <width> <depth>

Comments: ``--`` until end of line.
"""
from __future__ import annotations

from olm.core.dsl_common import DSLError, parse_int, strip_comment
from olm.core.room_model import (
    ExclusionZone,
    Face,
    HingeSide,
    OpeningSpec,
    RoomSpec,
    WindowSpec,
)

_FACE_MAP: dict[str, Face] = {
    "N": Face.NORTH,
    "S": Face.SOUTH,
    "E": Face.EAST,
    "W": Face.WEST,
}

_FACE_REV: dict[Face, str] = {v: k for k, v in _FACE_MAP.items()}

_HINGE_MAP: dict[str, HingeSide] = {
    "L": HingeSide.LEFT,
    "R": HingeSide.RIGHT,
}

_HINGE_REV: dict[HingeSide, str] = {v: k for k, v in _HINGE_MAP.items()}


class RoomDSLError(DSLError):
    """Syntax or semantic error in the room DSL."""


def _parse_face(token: str, line_no: int) -> Face:
    """Convert a face token to a Face enum."""
    face = _FACE_MAP.get(token.upper())
    if face is None:
        raise RoomDSLError(
            f"Line {line_no}: invalid face '{token}' "
            f"(expected: {', '.join(_FACE_MAP)})"
        )
    return face


def _parse_int(token: str, name: str, line_no: int) -> int:
    """Convert a token to int with a clear error message.

    Delegates to ``dsl_common.parse_int`` with line context.
    Raises ``RoomDSLError`` for caller compatibility.
    """
    try:
        return parse_int(token, name, context=f"Line {line_no}")
    except DSLError as exc:
        raise RoomDSLError(str(exc)) from None


def parse_room_dsl(text: str) -> RoomSpec:
    """Parse a DSL text and return a RoomSpec.

    Args:
        text: Multi-line DSL text.

    Returns:
        Corresponding RoomSpec.

    Raises:
        RoomDSLError: If the syntax is invalid or ROOM is missing.
    """
    room: RoomSpec | None = None
    windows: list[WindowSpec] = []
    openings: list[OpeningSpec] = []
    exclusions: list[ExclusionZone] = []
    transparents: list[ExclusionZone] = []

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw_line)
        if not line:
            continue

        tokens = line.split()
        keyword = tokens[0].upper()

        if keyword == "ROOM":
            if room is not None:
                raise RoomDSLError(
                    f"Line {line_no}: duplicate ROOM"
                )
            if len(tokens) != 2:
                raise RoomDSLError(
                    f"Line {line_no}: ROOM expects <width>x<depth>"
                )
            parts = tokens[1].lower().split("x")
            if len(parts) != 2:
                raise RoomDSLError(
                    f"Line {line_no}: invalid ROOM format "
                    f"(expected: WIDTHxDEPTH)"
                )
            w = _parse_int(parts[0], "width", line_no)
            d = _parse_int(parts[1], "depth", line_no)
            room = RoomSpec(width_cm=w, depth_cm=d)

        elif keyword == "WINDOW":
            if room is None:
                raise RoomDSLError(
                    f"Line {line_no}: ROOM must appear "
                    f"before WINDOW"
                )
            if len(tokens) < 2 or len(tokens) > 4:
                raise RoomDSLError(
                    f"Line {line_no}: WINDOW expects <face> [<offset> <width>]"
                )
            face = _parse_face(tokens[1], line_no)
            if len(tokens) == 2:
                # Full wall width
                offset = 0
                if face in (Face.NORTH, Face.SOUTH):
                    width = room.width_cm
                else:
                    width = room.depth_cm
            else:
                offset = _parse_int(tokens[2], "offset", line_no)
                width = _parse_int(tokens[3], "width", line_no)
            windows.append(WindowSpec(
                face=face, offset_cm=offset, width_cm=width,
            ))

        elif keyword == "DOOR":
            if room is None:
                raise RoomDSLError(
                    f"Line {line_no}: ROOM must appear "
                    f"before DOOR"
                )
            if len(tokens) != 6:
                raise RoomDSLError(
                    f"Line {line_no}: DOOR expects "
                    f"<face> <offset> <width> INT|EXT L|R"
                )
            face = _parse_face(tokens[1], line_no)
            offset = _parse_int(tokens[2], "offset", line_no)
            width = _parse_int(tokens[3], "width", line_no)
            dir_token = tokens[4].upper()
            if dir_token == "INT":
                opens_inward = True
            elif dir_token == "EXT":
                opens_inward = False
            else:
                raise RoomDSLError(
                    f"Line {line_no}: invalid direction "
                    f"'{tokens[4]}' (expected: INT or EXT)"
                )
            hinge_token = tokens[5].upper()
            hinge = _HINGE_MAP.get(hinge_token)
            if hinge is None:
                raise RoomDSLError(
                    f"Line {line_no}: invalid hinge side "
                    f"'{tokens[5]}' (expected: L or R)"
                )
            openings.append(OpeningSpec(
                face=face,
                offset_cm=offset,
                width_cm=width,
                has_door=True,
                opens_inward=opens_inward,
                hinge_side=hinge,
            ))

        elif keyword == "OPENING":
            if room is None:
                raise RoomDSLError(
                    f"Line {line_no}: ROOM must appear "
                    f"before OPENING"
                )
            if len(tokens) != 4:
                raise RoomDSLError(
                    f"Line {line_no}: OPENING expects "
                    f"<face> <offset> <width>"
                )
            face = _parse_face(tokens[1], line_no)
            offset = _parse_int(tokens[2], "offset", line_no)
            width = _parse_int(tokens[3], "width", line_no)
            openings.append(OpeningSpec(
                face=face,
                offset_cm=offset,
                width_cm=width,
                has_door=False,
                opens_inward=True,
                hinge_side=HingeSide.LEFT,
            ))

        elif keyword == "EXCLUSION":
            if room is None:
                raise RoomDSLError(
                    f"Line {line_no}: ROOM must appear "
                    f"before EXCLUSION"
                )
            if len(tokens) != 5:
                raise RoomDSLError(
                    f"Line {line_no}: EXCLUSION expects "
                    f"<x> <y> <width> <depth>"
                )
            x = _parse_int(tokens[1], "x", line_no)
            y = _parse_int(tokens[2], "y", line_no)
            w = _parse_int(tokens[3], "width", line_no)
            d = _parse_int(tokens[4], "depth", line_no)
            exclusions.append(ExclusionZone(
                x_cm=x, y_cm=y, width_cm=w, depth_cm=d, physical=True,
            ))

        elif keyword == "TRANSPARENT":
            if room is None:
                raise RoomDSLError(
                    f"Line {line_no}: ROOM must appear "
                    f"before TRANSPARENT"
                )
            if len(tokens) != 5:
                raise RoomDSLError(
                    f"Line {line_no}: TRANSPARENT expects "
                    f"<x> <y> <width> <depth>"
                )
            x = _parse_int(tokens[1], "x", line_no)
            y = _parse_int(tokens[2], "y", line_no)
            w = _parse_int(tokens[3], "width", line_no)
            d = _parse_int(tokens[4], "depth", line_no)
            transparents.append(ExclusionZone(
                x_cm=x, y_cm=y, width_cm=w, depth_cm=d, physical=False,
            ))

        else:
            raise RoomDSLError(
                f"Line {line_no}: unknown keyword '{tokens[0]}'"
            )

    if room is None:
        raise RoomDSLError("ROOM missing in DSL")

    room.windows = windows
    room.openings = openings
    room.exclusion_zones = exclusions
    room.transparent_zones = transparents
    return room


def to_room_dsl(room: RoomSpec) -> str:
    """Serialize a RoomSpec to DSL text.

    Args:
        room: Room specification.

    Returns:
        Multi-line DSL text.
    """
    lines: list[str] = []
    lines.append(f"ROOM {room.width_cm}x{room.depth_cm}")

    for w in room.windows:
        face = _FACE_REV[w.face]
        # Short form if full wall width
        wall_len = (room.width_cm if w.face in (Face.NORTH, Face.SOUTH)
                    else room.depth_cm)
        if w.offset_cm == 0 and w.width_cm == wall_len:
            lines.append(f"WINDOW {face}")
        else:
            lines.append(f"WINDOW {face} {w.offset_cm} {w.width_cm}")

    for o in room.openings:
        face = _FACE_REV[o.face]
        if o.has_door:
            direction = "INT" if o.opens_inward else "EXT"
            hinge = _HINGE_REV[o.hinge_side]
            lines.append(
                f"DOOR {face} {o.offset_cm} {o.width_cm} "
                f"{direction} {hinge}"
            )
        else:
            lines.append(
                f"OPENING {face} {o.offset_cm} {o.width_cm}"
            )

    for z in room.exclusion_zones:
        lines.append(
            f"EXCLUSION {z.x_cm} {z.y_cm} {z.width_cm} {z.depth_cm}"
        )

    for z in getattr(room, "transparent_zones", []) or []:
        lines.append(
            f"TRANSPARENT {z.x_cm} {z.y_cm} {z.width_cm} {z.depth_cm}"
        )

    return "\n".join(lines) + "\n"
