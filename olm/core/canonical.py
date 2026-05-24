"""D-83: Canonical room orientation — corridor at bottom (south).

Port Python de la logique JS (canonical_io.js) pour usage côté serveur et tests.
Une pièce est «canonicalisée» en pivotant sa description (faces, ouvertures,
portes, exclusions, zones transparentes) de sorte que le corridor soit toujours
au sud.

B-F5 résolu (D-274 Passe 1.5b-1) : hinge_side corrigé via
_flip_hinge_on_rotation — tient compte de l'inversion de polarité
de la face "west" (left = high y).
"""

from __future__ import annotations

import copy
from typing import Any

# Face → face après rotation pour placer le corridor au sud
_FACE_MAPS: dict[str, dict[str, str]] = {
    "north": {"north": "south", "south": "north", "east": "west", "west": "east"},
    "east":  {"north": "east",  "east": "south",  "south": "west", "west": "north"},
    "west":  {"north": "west",  "west": "south",  "south": "east", "east": "north"},
}

# Inverse : face locale → face absolue
_INV_FACE_MAPS: dict[str, dict[str, str]] = {
    cf: {v: k for k, v in mapping.items()}
    for cf, mapping in _FACE_MAPS.items()
}


def _flip_from(cf: str, abs_face: str) -> bool:
    """True si l'offset doit être retourné en abs→canon.

    90° CW (east) : flip faces verticales abs (east, west) uniquement.
    90° CCW (west) : flip faces horizontales abs (north, south) uniquement.
    180° (north) : flip toutes les faces.
    """
    if cf == "north":
        return True
    is_v = abs_face in ("east", "west")
    if cf == "east":
        return is_v
    if cf == "west":
        return not is_v
    return False


def _flip_to(ocf: str, canon_face: str) -> bool:
    """True si l'offset doit être retourné en canon→abs.

    90° CW (east) : flip faces horizontales canon (north, south).
    90° CCW (west) : flip faces verticales canon (east, west).
    180° (north) : flip toutes les faces.
    """
    if ocf == "north":
        return True
    is_h = canon_face in ("north", "south")
    if ocf == "east":
        return is_h
    if ocf == "west":
        return not is_h
    return False


def _left_is_low(face: str) -> bool:
    """True si "left" correspond au côté low-coord sur cette face.

    Toutes les faces sauf "west" : left = low x ou low y.
    "west" : left = high y (polarité inversée).
    """
    return face != "west"


def _flip_hinge_on_rotation(
    hinge_side: str,
    src_face: str,
    dst_face: str,
    offset_flipped: bool,
) -> str:
    """Détermine si hinge_side doit être inversé lors d'une rotation.

    Formule : flip = offset_flipped XOR (left_is_low(src) != left_is_low(dst)).
    Gère la polarité inversée de la face "west" (B-F5).

    Args:
        hinge_side: "left" ou "right" (ou vide → retourné tel quel).
        src_face: Face avant mapping.
        dst_face: Face après mapping.
        offset_flipped: True si l'offset a été retourné.

    Returns:
        hinge_side corrigé.
    """
    if not hinge_side:
        return hinge_side
    polarity_diff = _left_is_low(src_face) != _left_is_low(dst_face)
    if offset_flipped != polarity_diff:
        return "right" if hinge_side == "left" else "left"
    return hinge_side


def _xform_zone_forward(
    e: dict[str, Any],
    cf: str,
    w: float,
    d: float,
) -> dict[str, Any]:
    """Transforme une zone (exclusion ou transparente) abs → canon.

    Convention alignée sur canonical_io.js (D-274 Lot 2a, fix B-F6).
    """
    ex = dict(e)
    if cf == "north":
        ex["x_cm"] = w - e["x_cm"] - e["width_cm"]
        ex["y_cm"] = d - e["y_cm"] - e["depth_cm"]
    elif cf == "east":
        ex["x_cm"] = d - e["y_cm"] - e["depth_cm"]
        ex["y_cm"] = e["x_cm"]
        ex["width_cm"] = e["depth_cm"]
        ex["depth_cm"] = e["width_cm"]
    elif cf == "west":
        ex["x_cm"] = e["y_cm"]
        ex["y_cm"] = w - e["x_cm"] - e["width_cm"]
        ex["width_cm"] = e["depth_cm"]
        ex["depth_cm"] = e["width_cm"]
    return ex


def _xform_zone_back(
    e: dict[str, Any],
    ocf: str,
    w: float,
    d: float,
) -> dict[str, Any]:
    """Transforme une zone (exclusion ou transparente) canon → abs.

    Inverse exact de _xform_zone_forward.
    w, d = dimensions canoniques (room["width_cm"], room["depth_cm"]).
    """
    ex = dict(e)
    if ocf == "north":
        ex["x_cm"] = w - e["x_cm"] - e["width_cm"]
        ex["y_cm"] = d - e["y_cm"] - e["depth_cm"]
    elif ocf == "east":
        ex["x_cm"] = e["y_cm"]
        ex["y_cm"] = w - e["x_cm"] - e["width_cm"]
        ex["width_cm"] = e["depth_cm"]
        ex["depth_cm"] = e["width_cm"]
    elif ocf == "west":
        ex["x_cm"] = d - e["y_cm"] - e["depth_cm"]
        ex["y_cm"] = e["x_cm"]
        ex["width_cm"] = e["depth_cm"]
        ex["depth_cm"] = e["width_cm"]
    return ex


def canonicalize_room(room: dict[str, Any]) -> dict[str, Any]:
    """Convertit les coordonnées absolues d'une pièce en coordonnées locales
    avec le corridor au sud.

    Args:
        room: Dictionnaire pièce avec au minimum width_cm, depth_cm,
              corridor_face, et optionnellement windows, openings, doors,
              exclusion_zones, transparent_zones.

    Returns:
        Copie profonde avec coordonnées pivotées. Champ corridor_face = "south".
        Le corridor_face original est conservé dans _original_corridor_face.
    """
    cf = room.get("corridor_face", "")
    if not cf or cf == "south":
        return room

    face_map = _FACE_MAPS.get(cf)
    if not face_map:
        return room

    out = copy.deepcopy(room)
    w = room["width_cm"]
    d = room["depth_cm"]
    swap = cf in ("east", "west")
    if swap:
        out["width_cm"], out["depth_cm"] = d, w

    def _face_len(face: str) -> float:
        return w if face in ("north", "south") else d

    def _xform_opening(o: dict[str, Any]) -> dict[str, Any]:
        r = dict(o)
        dst = face_map.get(o["face"], o["face"])
        r["face"] = dst
        off_flip = _flip_from(cf, o["face"])
        if off_flip:
            r["offset_cm"] = (
                _face_len(o["face"])
                - o.get("offset_cm", 0)
                - o.get("width_cm", 0)
            )
        if o.get("hinge_side"):
            r["hinge_side"] = _flip_hinge_on_rotation(
                o["hinge_side"], o["face"], dst, off_flip,
            )
        return r

    out["windows"] = [_xform_opening(w_) for w_ in room.get("windows", [])]
    out["openings"] = [_xform_opening(o) for o in room.get("openings", [])]
    out["doors"] = [_xform_opening(o) for o in room.get("doors", [])]

    if room.get("exclusion_zones"):
        out["exclusion_zones"] = [
            _xform_zone_forward(e, cf, w, d)
            for e in room["exclusion_zones"]
        ]
    if room.get("transparent_zones"):
        out["transparent_zones"] = [
            _xform_zone_forward(e, cf, w, d)
            for e in room["transparent_zones"]
        ]

    out["corridor_face"] = "south"
    out["_original_corridor_face"] = cf
    return out


def decanonicalize_room(
    room: dict[str, Any],
    original_corridor_face: str,
) -> dict[str, Any]:
    """Inverse de canonicalize_room : coordonnées locales → absolues.

    Args:
        room: Pièce en coordonnées canoniques (corridor au sud).
        original_corridor_face: Face corridor d'origine ("north"/"east"/"west").

    Returns:
        Copie profonde avec coordonnées restaurées dans le repère absolu.
    """
    if not original_corridor_face or original_corridor_face == "south":
        return room

    inv_map = _INV_FACE_MAPS.get(original_corridor_face)
    if not inv_map:
        return room

    out = copy.deepcopy(room)
    w = room["width_cm"]
    d = room["depth_cm"]
    swap = original_corridor_face in ("east", "west")
    if swap:
        out["width_cm"], out["depth_cm"] = d, w

    def _local_face_len(face: str) -> float:
        return w if face in ("north", "south") else d

    def _xform_back(o: dict[str, Any]) -> dict[str, Any]:
        r = dict(o)
        dst = inv_map.get(o["face"], o["face"])
        r["face"] = dst
        off_flip = _flip_to(original_corridor_face, o["face"])
        if off_flip:
            r["offset_cm"] = (
                _local_face_len(o["face"])
                - o.get("offset_cm", 0)
                - o.get("width_cm", 0)
            )
        if o.get("hinge_side"):
            r["hinge_side"] = _flip_hinge_on_rotation(
                o["hinge_side"], o["face"], dst, off_flip,
            )
        return r

    out["windows"] = [_xform_back(w_) for w_ in room.get("windows", [])]
    out["openings"] = [_xform_back(o) for o in room.get("openings", [])]
    out["doors"] = [_xform_back(o) for o in room.get("doors", [])]

    if room.get("exclusion_zones"):
        out["exclusion_zones"] = [
            _xform_zone_back(e, original_corridor_face, w, d)
            for e in room["exclusion_zones"]
        ]
    if room.get("transparent_zones"):
        out["transparent_zones"] = [
            _xform_zone_back(e, original_corridor_face, w, d)
            for e in room["transparent_zones"]
        ]

    out["corridor_face"] = original_corridor_face
    out.pop("_original_corridor_face", None)
    return out
