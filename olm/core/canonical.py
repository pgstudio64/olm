"""D-83: Canonical room orientation — corridor at bottom (south).

Port Python de la logique JS (floor_plan.js) pour usage côté serveur et tests.
Une pièce est «canonicalisée» en pivotant sa description (faces, ouvertures,
exclusions) de sorte que le corridor soit toujours au sud.
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
    "north": {"north": "south", "south": "north", "east": "west", "west": "east"},
    "east":  {"north": "west",  "east": "north",  "south": "east", "west": "south"},
    "west":  {"north": "east",  "east": "south",  "south": "west", "west": "north"},
}


def canonicalize_room(room: dict[str, Any]) -> dict[str, Any]:
    """Convertit les coordonnées absolues d'une pièce en coordonnées locales
    avec le corridor au sud.

    Args:
        room: Dictionnaire pièce avec au minimum width_cm, depth_cm,
              corridor_face, et optionnellement windows, openings,
              exclusion_zones.

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
        r["face"] = face_map.get(o["face"], o["face"])
        if cf in ("north", "west"):
            r["offset_cm"] = _face_len(o["face"]) - o.get("offset_cm", 0) - o.get("width_cm", 0)
        if cf in ("north", "west") and o.get("hinge_side"):
            r["hinge_side"] = "right" if o["hinge_side"] == "left" else "left"
        return r

    out["windows"] = [_xform_opening(w_) for w_ in room.get("windows", [])]
    out["openings"] = [_xform_opening(o) for o in room.get("openings", [])]

    if room.get("exclusion_zones"):
        new_excl = []
        for e in room["exclusion_zones"]:
            ex = dict(e)
            if cf == "north":
                ex["x_cm"] = w - e["x_cm"] - e["width_cm"]
                ex["y_cm"] = d - e["y_cm"] - e["depth_cm"]
            elif cf == "east":
                ex["x_cm"] = e["y_cm"]
                ex["y_cm"] = w - e["x_cm"] - e["width_cm"]
                ex["width_cm"] = e["depth_cm"]
                ex["depth_cm"] = e["width_cm"]
            elif cf == "west":
                ex["x_cm"] = d - e["y_cm"] - e["depth_cm"]
                ex["y_cm"] = e["x_cm"]
                ex["width_cm"] = e["depth_cm"]
                ex["depth_cm"] = e["width_cm"]
            new_excl.append(ex)
        out["exclusion_zones"] = new_excl

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
        r["face"] = inv_map.get(o["face"], o["face"])
        if original_corridor_face in ("north", "west"):
            r["offset_cm"] = (
                _local_face_len(o["face"]) - o.get("offset_cm", 0) - o.get("width_cm", 0)
            )
            if o.get("hinge_side"):
                r["hinge_side"] = "right" if o["hinge_side"] == "left" else "left"
        return r

    out["windows"] = [_xform_back(w_) for w_ in room.get("windows", [])]
    out["openings"] = [_xform_back(o) for o in room.get("openings", [])]

    if room.get("exclusion_zones"):
        new_excl = []
        for e in room["exclusion_zones"]:
            ex = dict(e)
            if original_corridor_face == "north":
                abs_w = d if swap else w
                abs_d = w if swap else d
                ex["x_cm"] = abs_w - e["x_cm"] - e["width_cm"]
                ex["y_cm"] = abs_d - e["y_cm"] - e["depth_cm"]
            elif original_corridor_face == "east":
                ex["x_cm"] = d - e["y_cm"] - e["depth_cm"]
                ex["y_cm"] = e["x_cm"]
                ex["width_cm"] = e["depth_cm"]
                ex["depth_cm"] = e["width_cm"]
            elif original_corridor_face == "west":
                ex["x_cm"] = e["y_cm"]
                ex["y_cm"] = w - e["x_cm"] - e["width_cm"]
                ex["width_cm"] = e["depth_cm"]
                ex["depth_cm"] = e["width_cm"]
            new_excl.append(ex)
        out["exclusion_zones"] = new_excl

    out["corridor_face"] = original_corridor_face
    out.pop("_original_corridor_face", None)
    return out
