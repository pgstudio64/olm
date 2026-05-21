"""D-260 regression tests for export decanonicalization.

The export rebuilds each desk's absolute position and chair side from the
canonical pattern. Two bugs affected east/west (side) corridors only:
  1. ``_draw_room_desks`` passed the room's *actual* dims to
     ``_decanon_rect``, which needs the *canonical* dims (swapped for
     east/west) → desks shifted out of place.
  2. The hardcoded chair-side table was inverted for east/west.

These tests verify, for all four corridor orientations, that:
  - a rect round-trips (canonicalize → decanonicalize) to its original, and
  - the chair-side decanon matches the editor's rotation (canonAngle CW).
"""
from olm.core.canonical import canonicalize_room
from olm.server.services.export_service import _decanon_chair_side, _decanon_rect

# Editor ground truth: it rotates the canonical layout canonAngle° CW.
_CANON_ANGLE = {"south": 0, "east": 90, "north": 180, "west": 270}
_SIDE_CW = {"N": "E", "E": "S", "S": "W", "W": "N"}

_ORIG = {"x_cm": 10, "y_cm": 20, "width_cm": 80, "depth_cm": 180}
_FACES = ["south", "north", "east", "west"]


def _screen_chair(side: str, cf: str) -> str:
    """Chair side as the editor displays it (canonAngle CW rotation)."""
    s = side
    for _ in range((_CANON_ANGLE[cf] // 90) % 4):
        s = _SIDE_CW[s]
    return s


def _canonical_dims(room: dict, cf: str) -> tuple[int, int]:
    """Canonical (corridor-south) dims: swapped for east/west corridors."""
    if cf in ("east", "west"):
        return room["depth_cm"], room["width_cm"]
    return room["width_cm"], room["depth_cm"]


def test_decanon_rect_roundtrip_all_corridors():
    """A rect survives canonicalize → _decanon_rect for every corridor."""
    for cf in _FACES:
        room = {
            "width_cm": 300, "depth_cm": 500, "corridor_face": cf,
            "windows": [], "openings": [],
            "exclusion_zones": [dict(_ORIG)],
        }
        canon = canonicalize_room(room)
        cz = canon["exclusion_zones"][0]
        canon_w, canon_d = _canonical_dims(room, cf)
        got = _decanon_rect(
            cz["x_cm"], cz["y_cm"], cz["width_cm"], cz["depth_cm"],
            canon_w, canon_d, cf,
        )
        expected = (_ORIG["x_cm"], _ORIG["y_cm"],
                    _ORIG["width_cm"], _ORIG["depth_cm"])
        assert got == expected, f"corridor {cf}: {got} != {expected}"


def test_decanon_chair_side_matches_editor_all_corridors():
    """Chair-side decanon matches the editor rotation for every corridor."""
    for cf in _FACES:
        for side in "NESW":
            assert _decanon_chair_side(side, cf) == _screen_chair(side, cf), (
                f"corridor {cf}, side {side}: "
                f"{_decanon_chair_side(side, cf)} != {_screen_chair(side, cf)}"
            )


def test_decanon_chair_side_default_face():
    """Empty/None corridor face behaves like south (identity)."""
    for side in "NESW":
        assert _decanon_chair_side(side, "") == side
