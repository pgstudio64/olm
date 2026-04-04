"""Parseur et sérialiseur DSL pour les pièces — solver_lab.

Grammaire :
    PIECE <width> x <depth>
    FEN <face> <offset> <width>
    PORTE <face> <offset> <width> INT|EXT G|D
    BAIE <face> <offset> <width>
    EXCL <x> <y> <width> <depth>

Commentaires : ``--`` jusqu'à fin de ligne.
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
    "O": Face.WEST,
}

_FACE_REV: dict[Face, str] = {v: k for k, v in _FACE_MAP.items()}

_HINGE_MAP: dict[str, HingeSide] = {
    "G": HingeSide.LEFT,
    "D": HingeSide.RIGHT,
}

_HINGE_REV: dict[HingeSide, str] = {v: k for k, v in _HINGE_MAP.items()}


class RoomDSLError(DSLError):
    """Erreur de syntaxe ou de sémantique dans le DSL pièce."""


def _parse_face(token: str, line_no: int) -> Face:
    """Convertit un token de face en enum Face."""
    face = _FACE_MAP.get(token.upper())
    if face is None:
        raise RoomDSLError(
            f"Ligne {line_no} : face invalide '{token}' "
            f"(attendu : {', '.join(_FACE_MAP)})"
        )
    return face


def _parse_int(token: str, name: str, line_no: int) -> int:
    """Convertit un token en entier avec message d'erreur clair.

    Délègue à ``dsl_common.parse_int`` en ajoutant le contexte de ligne.
    Relève ``RoomDSLError`` pour compatibilité avec le code appelant.
    """
    try:
        return parse_int(token, name, context=f"Ligne {line_no}")
    except DSLError as exc:
        raise RoomDSLError(str(exc)) from None


def parse_room_dsl(text: str) -> RoomSpec:
    """Parse un texte DSL et retourne un RoomSpec.

    Args:
        text: Texte DSL multi-lignes.

    Returns:
        RoomSpec correspondant.

    Raises:
        RoomDSLError: Si la syntaxe est invalide ou PIECE manquant.
    """
    room: RoomSpec | None = None
    windows: list[WindowSpec] = []
    openings: list[OpeningSpec] = []
    exclusions: list[ExclusionZone] = []

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw_line)
        if not line:
            continue

        tokens = line.split()
        keyword = tokens[0].upper()

        if keyword == "PIECE":
            if room is not None:
                raise RoomDSLError(
                    f"Ligne {line_no} : PIECE dupliqué"
                )
            if len(tokens) != 2:
                raise RoomDSLError(
                    f"Ligne {line_no} : PIECE attend <largeur>x<profondeur>"
                )
            parts = tokens[1].lower().split("x")
            if len(parts) != 2:
                raise RoomDSLError(
                    f"Ligne {line_no} : format PIECE invalide "
                    f"(attendu : LARGxPROF)"
                )
            w = _parse_int(parts[0], "largeur", line_no)
            d = _parse_int(parts[1], "profondeur", line_no)
            room = RoomSpec(width_cm=w, depth_cm=d)

        elif keyword == "FEN":
            if room is None:
                raise RoomDSLError(
                    f"Ligne {line_no} : PIECE doit apparaître "
                    f"avant FEN"
                )
            if len(tokens) < 2 or len(tokens) > 4:
                raise RoomDSLError(
                    f"Ligne {line_no} : FEN attend <face> [<offset> <largeur>]"
                )
            face = _parse_face(tokens[1], line_no)
            if len(tokens) == 2:
                # Pleine largeur du mur
                offset = 0
                if face in (Face.NORTH, Face.SOUTH):
                    width = room.width_cm
                else:
                    width = room.depth_cm
            else:
                offset = _parse_int(tokens[2], "offset", line_no)
                width = _parse_int(tokens[3], "largeur", line_no)
            windows.append(WindowSpec(
                face=face, offset_cm=offset, width_cm=width,
            ))

        elif keyword == "PORTE":
            if room is None:
                raise RoomDSLError(
                    f"Ligne {line_no} : PIECE doit apparaître "
                    f"avant PORTE"
                )
            if len(tokens) != 6:
                raise RoomDSLError(
                    f"Ligne {line_no} : PORTE attend "
                    f"<face> <offset> <largeur> INT|EXT G|D"
                )
            face = _parse_face(tokens[1], line_no)
            offset = _parse_int(tokens[2], "offset", line_no)
            width = _parse_int(tokens[3], "largeur", line_no)
            dir_token = tokens[4].upper()
            if dir_token == "INT":
                opens_inward = True
            elif dir_token == "EXT":
                opens_inward = False
            else:
                raise RoomDSLError(
                    f"Ligne {line_no} : direction invalide "
                    f"'{tokens[4]}' (attendu : INT ou EXT)"
                )
            hinge_token = tokens[5].upper()
            hinge = _HINGE_MAP.get(hinge_token)
            if hinge is None:
                raise RoomDSLError(
                    f"Ligne {line_no} : gond invalide "
                    f"'{tokens[5]}' (attendu : G ou D)"
                )
            openings.append(OpeningSpec(
                face=face,
                offset_cm=offset,
                width_cm=width,
                has_door=True,
                opens_inward=opens_inward,
                hinge_side=hinge,
            ))

        elif keyword == "BAIE":
            if room is None:
                raise RoomDSLError(
                    f"Ligne {line_no} : PIECE doit apparaître "
                    f"avant BAIE"
                )
            if len(tokens) != 4:
                raise RoomDSLError(
                    f"Ligne {line_no} : BAIE attend "
                    f"<face> <offset> <largeur>"
                )
            face = _parse_face(tokens[1], line_no)
            offset = _parse_int(tokens[2], "offset", line_no)
            width = _parse_int(tokens[3], "largeur", line_no)
            openings.append(OpeningSpec(
                face=face,
                offset_cm=offset,
                width_cm=width,
                has_door=False,
                opens_inward=True,
                hinge_side=HingeSide.LEFT,
            ))

        elif keyword == "EXCL":
            if room is None:
                raise RoomDSLError(
                    f"Ligne {line_no} : PIECE doit apparaître "
                    f"avant EXCL"
                )
            if len(tokens) != 5:
                raise RoomDSLError(
                    f"Ligne {line_no} : EXCL attend "
                    f"<x> <y> <largeur> <profondeur>"
                )
            x = _parse_int(tokens[1], "x", line_no)
            y = _parse_int(tokens[2], "y", line_no)
            w = _parse_int(tokens[3], "largeur", line_no)
            d = _parse_int(tokens[4], "profondeur", line_no)
            exclusions.append(ExclusionZone(
                x_cm=x, y_cm=y, width_cm=w, depth_cm=d, physical=True,
            ))

        else:
            raise RoomDSLError(
                f"Ligne {line_no} : mot-clé inconnu '{tokens[0]}'"
            )

    if room is None:
        raise RoomDSLError("PIECE manquant dans le DSL")

    room.windows = windows
    room.openings = openings
    room.exclusion_zones = exclusions
    return room


def to_room_dsl(room: RoomSpec) -> str:
    """Sérialise un RoomSpec en texte DSL.

    Args:
        room: Spécification de la pièce.

    Returns:
        Texte DSL multi-lignes.
    """
    lines: list[str] = []
    lines.append(f"PIECE {room.width_cm}x{room.depth_cm}")

    for w in room.windows:
        face = _FACE_REV[w.face]
        # Forme courte si pleine largeur du mur
        wall_len = (room.width_cm if w.face in (Face.NORTH, Face.SOUTH)
                    else room.depth_cm)
        if w.offset_cm == 0 and w.width_cm == wall_len:
            lines.append(f"FEN {face}")
        else:
            lines.append(f"FEN {face} {w.offset_cm} {w.width_cm}")

    for o in room.openings:
        face = _FACE_REV[o.face]
        if o.has_door:
            direction = "INT" if o.opens_inward else "EXT"
            hinge = _HINGE_REV[o.hinge_side]
            lines.append(
                f"PORTE {face} {o.offset_cm} {o.width_cm} "
                f"{direction} {hinge}"
            )
        else:
            lines.append(
                f"BAIE {face} {o.offset_cm} {o.width_cm}"
            )

    for z in room.exclusion_zones:
        lines.append(
            f"EXCL {z.x_cm} {z.y_cm} {z.width_cm} {z.depth_cm}"
        )

    return "\n".join(lines) + "\n"
