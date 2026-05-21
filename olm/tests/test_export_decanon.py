"""D-260/D-261 regression tests for export decanonicalization.

The export rebuilds each desk's absolute position and chair side from the
canonical pattern. It MUST mirror the editor/screen convention
(``canonical_io.js``), not the server ``canonical.py`` — the two use
OPPOSITE east/west rotations, and the screen is the source of truth
(D-261). Bugs that affected east/west (side) corridors only:
  1. ``_draw_room_desks`` passed the room's *actual* dims instead of the
     *canonical* dims (swapped for east/west) → desks shifted.
  2. The decanon rect/chair used the server convention (opposite to the
     screen for east/west) → desks placed on the wrong side, "between
     rooms" instead of where the editor shows them.

These tests verify, for all four corridor orientations, that the export
decanon is the exact inverse of the FRONT (canonical_io.js) transforms.
"""
from olm.server.services.export_service import _decanon_chair_side, _decanon_rect

_FACES = ["south", "north", "east", "west"]
_ABS_W, _ABS_D = 300, 500
_ORIG = (10, 20, 80, 180)  # x, y, w, d (absolute)


# ── canonical_io.js ground truth (abs → canon), replicated ──────────────
def _front_rotate_rect(x, y, w, d, cf, abs_w, abs_d):
    if cf == "north":
        return (abs_w - x - w, abs_d - y - d, w, d)
    if cf == "east":
        return (abs_d - y - d, x, d, w)
    if cf == "west":
        return (y, abs_w - x - w, d, w)
    return (x, y, w, d)


_FRONT_FACE = {
    "north": {"north": "south", "south": "north", "east": "west", "west": "east"},
    "east":  {"north": "east",  "east": "south",  "south": "west", "west": "north"},
    "west":  {"north": "west",  "west": "south",  "south": "east", "east": "north"},
}
_LONG = {"N": "north", "S": "south", "E": "east", "W": "west"}
_SHORT = {v: k for k, v in _LONG.items()}


def _front_rotate_dir(side, cf):
    if cf not in _FRONT_FACE:
        return side
    return _SHORT[_FRONT_FACE[cf][_LONG[side]]]


def _canonical_dims(cf):
    """Canonical dims (corridor south): swapped for east/west corridors."""
    if cf in ("east", "west"):
        return _ABS_D, _ABS_W
    return _ABS_W, _ABS_D


def test_decanon_rect_inverts_front_rotate_rect():
    """_decanon_rect is the exact inverse of canonical_io.js rotateRect."""
    for cf in _FACES:
        canon = _front_rotate_rect(*_ORIG, cf, _ABS_W, _ABS_D)
        canon_w, canon_d = _canonical_dims(cf)
        back = _decanon_rect(canon[0], canon[1], canon[2], canon[3],
                             canon_w, canon_d, cf)
        assert back == _ORIG, f"corridor {cf}: {back} != {_ORIG}"


def test_decanon_chair_inverts_front_rotate_dir():
    """_decanon_chair_side is the exact inverse of canonical_io.js rotateDir."""
    for cf in _FACES:
        for side in "NESW":
            canon = _front_rotate_dir(side, cf)
            assert _decanon_chair_side(canon, cf) == side, (
                f"corridor {cf}, side {side}: "
                f"{_decanon_chair_side(canon, cf)} != {side}"
            )


def test_draw_room_desks_west_room_in_bounds():
    """D-265: a west-corridor room's desks must stay inside the room.

    Room payload dims are already canonical; D-260's east/west swap
    double-swapped them and pushed a desk to x=-34 ("between rooms").
    Real data (room 427): canonical 288x442, a desk at canon y=162.
    """
    from PIL import Image, ImageDraw, ImageFont

    from olm.server.services.export_service import _draw_room_desks, _EXPORT_DEBUG

    _EXPORT_DEBUG.clear()
    img = Image.new("RGBA", (4000, 3000), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    candidate = {
        "desks": [
            {"x_cm": 110, "y_cm": 6, "width_cm": 80, "depth_cm": 160,
             "chair_side": "E"},
            {"x_cm": 100, "y_cm": 162, "width_cm": 80, "depth_cm": 160,
             "chair_side": "W"},
        ],
        "pattern": {"room_width_cm": 288, "room_depth_cm": 442},
    }
    room = {
        "name": "427", "width_cm": 288, "depth_cm": 442,
        "corridor_face_abs": "west", "bbox_px": [2454, 1519, 2663, 1655],
        "candidate": candidate,
    }
    _draw_room_desks(draw, font, room, 2.1166666666666667)
    assert _EXPORT_DEBUG, "no diagnostic captured"
    assert not any("abs=(-" in line for line in _EXPORT_DEBUG), (
        "desk decanonicalised to a negative coordinate (out of room): "
        + " | ".join(_EXPORT_DEBUG)
    )


def test_decanon_default_face_identity():
    """Empty/None corridor face behaves like south (identity)."""
    assert _decanon_rect(10, 20, 80, 180, 300, 500, "") == (10, 20, 80, 180)
    for side in "NESW":
        assert _decanon_chair_side(side, "") == side
