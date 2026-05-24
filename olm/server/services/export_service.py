"""Export service — compose annotated plan image + CSV.

Generates plan export as PNG/PDF with workstation overlay and data CSV.
All desk positions come from the frontend payload (source of truth = what
the user sees). For amendments where desks are absent, positions are
recomputed from the pattern via ``compute_desk_positions``.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from olm.core.catalogue_matcher import compute_desk_positions
import olm.core.pattern_generator as _pg
from olm.server.services.config_service import (
    PROJECT_ROOT,
    get_corridor_rgb,
    get_exterior_rgb,
    get_plans_dir,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Decanonicalization helpers — mirror canonical_io.js (the FRONT / screen).
# ---------------------------------------------------------------------------
# The server's canonical.py uses the OPPOSITE east/west convention for rect
# positions, so reusing it placed export desks on the wrong side for
# side-corridor rooms. The editor (screen) is the source of truth, so the
# export mirrors canonical_io.js exactly (D-261).

# Canonical face → absolute face (inverse of canonical_io.js FACE_MAPS).
_FRONT_INV_FACE: dict[str, dict[str, str]] = {
    "north": {"north": "south", "south": "north", "east": "west",  "west": "east"},
    "east":  {"north": "west",  "east":  "north", "south": "east", "west": "south"},
    "west":  {"north": "east",  "east":  "south", "south": "west", "west": "north"},
}
_LONG_SIDE = {"N": "north", "S": "south", "E": "east", "W": "west"}
_SHORT_SIDE = {"north": "N", "south": "S", "east": "E", "west": "W"}


def _decanon_rect(
    x: float, y: float, w: float, d: float,
    canon_w: float, canon_d: float,
    corridor_face_abs: str,
) -> tuple[float, float, float, float]:
    """Decanonicalize a rect from canonical (corridor-south) to absolute.

    Inverse of canonical_io.js ``rotateRect`` — the FRONT/screen convention
    (the server's canonical.py uses the opposite east/west rotation, D-261).
    *canon_w* / *canon_d* are the **canonical** room dimensions.

    Returns:
        ``(abs_x, abs_y, abs_w, abs_d)`` in the absolute (image) frame.
    """
    cf = corridor_face_abs
    if not cf or cf == "south":
        return x, y, w, d
    if cf == "north":
        return canon_w - x - w, canon_d - y - d, w, d
    if cf == "east":
        return y, canon_w - x - w, d, w
    if cf == "west":
        return canon_d - y - d, x, d, w
    return x, y, w, d


def _decanon_chair_side(side: str, corridor_face_abs: str) -> str:
    """Convert a canonical chair side to absolute, mirroring the screen.

    Inverse of canonical_io.js ``rotateDir`` (uses INV_FACE_MAPS), so the
    chair sits on the same edge the editor shows (D-261). The previous
    server-derived convention was inverted for east/west.
    """
    m = _FRONT_INV_FACE.get(corridor_face_abs or "south")
    if not m:
        return side
    long = _LONG_SIDE.get(side)
    return _SHORT_SIDE.get(m.get(long, long), side) if long else side


# ---------------------------------------------------------------------------
# Desk computation for amendments (candidate.desks empty, pattern present)
# ---------------------------------------------------------------------------


def _compute_desks_with_chair_side(pattern: dict) -> list[dict]:
    """Compute desk positions from a pattern, including ``chair_side``.

    Args:
        pattern: Adapted pattern dict (from amendment or matching).

    Returns:
        List of desk dicts compatible with the export payload format.
    """
    removed_set: set[tuple[int, int, int]] = set()
    for rd in pattern.get("_removed_desks", []):
        removed_set.add((rd["row"], rd["block"], rd["desk"]))

    # D-260: compute_desk_positions is the single source of truth — it
    # already returns each desk's chair_side (block orientation applied).
    # Do NOT re-derive it here (a duplicate that drifts from the editor).
    desks: list[dict] = []
    for p in compute_desk_positions(pattern):
        desks.append({
            "x_cm": p.x_cm,
            "y_cm": p.y_cm,
            "width_cm": p.width_cm,
            "depth_cm": p.depth_cm,
            "removed": (p.row_idx, p.block_idx, p.desk_idx) in removed_set,
            "chair_side": p.chair_side,
        })
    return desks


# ---------------------------------------------------------------------------
# Drawing constants
# ---------------------------------------------------------------------------

_DESK_OUTLINE = (0, 0, 0, 255)
_DESK_FILL = (255, 255, 255, 255)
_DESK_STROKE_WIDTH = 2
_CHAIR_ARC_OUTLINE = (0, 0, 0, 255)
_SCREEN_FILL = (0, 0, 0, 255)
_LABEL_COLOR = (0, 0, 0, 255)
_WHITE = [255, 255, 255, 255]

# Chair seat geometry (mirror of olm/static/block_constants.js
# CHAIR_W_CM / CHAIR_D_CM). The chair is drawn as a wireframe rounded
# seat + backrest arc on the chair side of the desk (D-260).
_CHAIR_SEAT_WIDTH_CM = 65
_CHAIR_SEAT_DEPTH_CM = 60

# Screen geometry — mirrors olm/static/block_svg.js.
# Black thin bar on the desk side opposite to the chair, length ratio of
# the perpendicular desk dimension. Inset from desk edge so the screen
# sits visually inside the desk.
_SCREEN_THICK_PX = 3
_SCREEN_LEN_RATIO = 0.55
_SCREEN_INSET_PX = 3
_OPPOSITE_SIDE = {"W": "E", "E": "W", "N": "S", "S": "N"}

# Floor-summary cartouche (top-left of exported image).
# Position (x/y px) and font sizes (pt) are configurable via Settings;
# these are the fallback defaults if the config keys are absent.
_CARTOUCHE_TITLE_PT_DEFAULT = 22
_CARTOUCHE_BODY_PT_DEFAULT = 20
_CARTOUCHE_X_PX_DEFAULT = 120
_CARTOUCHE_Y_PX_DEFAULT = 120
_CARTOUCHE_PADDING = 8
_CARTOUCHE_BG = (255, 255, 255, 210)
_CARTOUCHE_BORDER = (0, 0, 0, 255)
_CARTOUCHE_BORDER_W = 1
_CARTOUCHE_TEXT = (0, 0, 0, 255)
_CARTOUCHE_LINE_SPACING = 12
# Footer line ("Export done on …") drawn smaller than the body text.
_CARTOUCHE_FOOTER_PT_DROP = 6


def _cartouche_font(pt: int) -> ImageFont.ImageFont:
    """Load a scalable default font at the given point size.

    Falls back to the fixed bitmap default on old Pillow versions that
    do not accept a size argument.
    """
    try:
        return ImageFont.load_default(size=pt)
    except (TypeError, AttributeError):
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# compose_plan_image
# ---------------------------------------------------------------------------


def neutralize_detection_colors(img: Image.Image) -> Image.Image:
    """Replace exterior + corridor detection colours with white.

    Cartouches and plan content are preserved. Shared by the export composer
    and by ``/api/image?clean=1`` (hide-detection-colors toggle, D-247).

    Args:
        img: Source plan image.

    Returns:
        New RGBA image with detection colours neutralised.
    """
    ext_rgb = get_exterior_rgb()
    cor_rgb = get_corridor_rgb()
    arr = np.array(img.convert("RGBA"))
    white = np.array(_WHITE, dtype=np.uint8)
    for rgb in (ext_rgb, cor_rgb):
        mask = (arr[:, :, :3] == np.array(rgb, dtype=np.uint8)).all(axis=2)
        arr[mask] = white
    return Image.fromarray(arr)


def compose_plan_image(
    plan_id: str,
    rooms_payload: list[dict],
    scale_cm_per_px: float,
) -> Image.Image:
    """Compose an annotated plan image with workstation overlay.

    Opens ``<plan_id>-SD.png``, neutralises detection colours, and draws
    desk rectangles, chair arcs, clearance zones, and labels.

    Args:
        plan_id: Plan identifier (resolves to ``<plan_id>-SD.png``).
        rooms_payload: Room dicts with ``candidate``, ``bbox_px``, etc.
        scale_cm_per_px: cm per pixel.

    Returns:
        RGBA ``PIL.Image.Image``.
    """
    plans_dir = get_plans_dir()
    sd_path = os.path.join(plans_dir, f"{plan_id}-SD.png")
    img = Image.open(sd_path).convert("RGBA")

    # Neutralize detection colours → white
    img = neutralize_detection_colors(img)

    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    for room in rooms_payload:
        _draw_room_desks(draw, font, room, scale_cm_per_px)

    # Floor-summary cartouche (top-left, drawn last = on top)
    summary = _compute_floor_summary(
        plan_id, rooms_payload, scale_cm_per_px,
    )
    _draw_cartouche(img, summary)

    return img


def _get_active_desks(candidate: dict) -> list[dict]:
    """Return non-removed desks from a candidate, recomputing if needed.

    Args:
        candidate: Room candidate dict with ``desks`` and/or ``pattern``.

    Returns:
        List of active (non-removed) desk dicts.
    """
    desks = candidate.get("desks")
    if not desks and candidate.get("pattern"):
        desks = _compute_desks_with_chair_side(candidate["pattern"])
    if not desks:
        return []
    return [d for d in desks if not d.get("removed")]


def _draw_chair(
    draw: ImageDraw.ImageDraw,
    x1: float, y1: float, x2: float, y2: float,
    cs: str, scale: float,
) -> None:
    """Draw a wireframe (B&W) chair on the *cs* side of a desk.

    Mirrors the editor (block_svg.js renderDesk): a rounded-rectangle seat
    overlapping the desk edge plus a curved backrest, drawn as a black
    outline on white (no colour). Call BEFORE the desk rectangle so the
    desk overlaps the seat, as on screen (chair z < desk z). D-260.
    """
    dw, dh = x2 - x1, y2 - y1
    is_horiz = cs in ("W", "E")
    chw = (_CHAIR_SEAT_DEPTH_CM if is_horiz else _CHAIR_SEAT_WIDTH_CM) / scale
    chh = (_CHAIR_SEAT_WIDTH_CM if is_horiz else _CHAIR_SEAT_DEPTH_CM) / scale
    seat_r = max(1.0, min(chw, chh) * 0.24)
    overlap = chw * 0.4
    back_inset = chw * 0.10
    arc_curve = chw * 0.16
    arc_pad = chh * 0.125

    if cs == "W":
        chx, chy = x1 - chw + overlap, y1 + (dh - chh) / 2
        a = chx + back_inset
        p0, ctrl, p2 = ((a, chy + arc_pad),
                        (a - arc_curve, chy + chh / 2),
                        (a, chy + chh - arc_pad))
    elif cs == "E":
        chx, chy = x2 - overlap, y1 + (dh - chh) / 2
        a = chx + chw - back_inset
        p0, ctrl, p2 = ((a, chy + arc_pad),
                        (a + arc_curve, chy + chh / 2),
                        (a, chy + chh - arc_pad))
    elif cs == "N":
        chx, chy = x1 + (dw - chw) / 2, y1 - chh + chh * 0.6
        a = chy + back_inset
        p0, ctrl, p2 = ((chx + arc_pad, a),
                        (chx + chw / 2, a - arc_curve),
                        (chx + chw - arc_pad, a))
    else:  # S
        chx, chy = x1 + (dw - chw) / 2, y2 - chh * 0.6
        a = chy + chh - back_inset
        p0, ctrl, p2 = ((chx + arc_pad, a),
                        (chx + chw / 2, a + arc_curve),
                        (chx + chw - arc_pad, a))

    draw.rounded_rectangle(
        [chx, chy, chx + chw, chy + chh], radius=seat_r,
        outline=_DESK_OUTLINE, fill=_DESK_FILL, width=1,
    )
    # Backrest: quadratic Bézier sampled as a polyline.
    pts = []
    steps = 12
    for i in range(steps + 1):
        t = i / steps
        mt = 1.0 - t
        bx = mt * mt * p0[0] + 2 * mt * t * ctrl[0] + t * t * p2[0]
        by = mt * mt * p0[1] + 2 * mt * t * ctrl[1] + t * t * p2[1]
        pts.append((bx, by))
    draw.line(pts, fill=_CHAIR_ARC_OUTLINE, width=2, joint="curve")


# D-264 (temporary): per-export diagnostic capture. export_plan clears this
# at the start and writes it to {plan}_DEBUG.txt next to the PNG, so a remote
# user can paste the exact desk coordinates without server log access.
_EXPORT_DEBUG: list[str] = []


def _draw_room_desks(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont,
    room: dict,
    scale: float,
) -> None:
    """Draw all desks for a single room onto the plan image."""
    candidate = room.get("candidate")
    if not candidate:
        return
    bbox = room.get("bbox_px")
    cf_abs = room.get("corridor_face_abs", "south")
    if not bbox or len(bbox) < 4:
        return
    room_w = room.get("width_cm", 0)
    room_d = room.get("depth_cm", 0)
    if not room_w or not room_d:
        return

    active = _get_active_desks(candidate)
    furniture = candidate.get("furniture") or []
    if not active and not furniture:
        logger.warning("Room %s: no desks to render", room.get("name"))
        return

    # D-265: the room payload dims (room.width_cm/depth_cm) are ALREADY in
    # CANONICAL (corridor-south) coordinates — the frontend canonicalises the
    # room before matching, and the desks live in that same canonical frame
    # (room == pattern dims, proven on real data). D-260's east/west swap was
    # wrong: it DOUBLE-swapped, shifting desks by (depth − width) and pushing
    # them out of the room (e.g. x = −34, "between rooms"). No swap.
    canon_w, canon_d = room_w, room_d

    # D-264 diagnostic (temporary)
    _pat = candidate.get("pattern") or {}
    _EXPORT_DEBUG.append(
        f"ROOM {room.get('name')} cf={cf_abs} room={room_w}x{room_d} "
        f"canon={canon_w}x{canon_d} "
        f"pattern={_pat.get('room_width_cm')}x{_pat.get('room_depth_cm')} "
        f"bbox_px={bbox} scale={scale} "
        f"desks_stored={len(candidate.get('desks') or [])} active={len(active)} "
        f"saved={candidate.get('saved')} amended={candidate.get('amended')}"
    )

    for desk_local_idx, desk in enumerate(active, start=1):
        # Decanonicalize rect → absolute coords (cm)
        ax, ay, aw, ad = _decanon_rect(
            desk["x_cm"], desk["y_cm"],
            desk["width_cm"], desk["depth_cm"],
            canon_w, canon_d, cf_abs,
        )

        # Convert cm → image px
        x1 = bbox[0] + ax / scale
        y1 = bbox[1] + ay / scale
        x2 = x1 + aw / scale
        y2 = y1 + ad / scale

        # Chair side: canonical → absolute
        cs_canon = desk.get("chair_side", "W")
        cs_abs = _decanon_chair_side(cs_canon, cf_abs)

        # D-264 diagnostic (temporary)
        _EXPORT_DEBUG.append(
            f"  desk{desk_local_idx} "
            f"canon=({desk['x_cm']},{desk['y_cm']},{desk['width_cm']},"
            f"{desk['depth_cm']}) chair={cs_canon} -> "
            f"abs=({round(ax)},{round(ay)},{round(aw)},{round(ad)}) "
            f"chair={cs_abs} px=({round(x1)},{round(y1)})"
        )

        # Chair first (behind the desk, as on screen), then the desk on top
        # so the desk overlaps the seat (mirrors editor z-order).
        _draw_chair(draw, x1, y1, x2, y2, cs_abs, scale)
        draw.rectangle(
            [x1, y1, x2, y2],
            outline=_DESK_OUTLINE,
            fill=_DESK_FILL,
            width=_DESK_STROKE_WIDTH,
        )

        # Screen — thin black bar on the desk side opposite the chair
        scr_side = _OPPOSITE_SIDE.get(cs_abs, "E")
        desk_w_px = x2 - x1
        desk_h_px = y2 - y1
        if scr_side in ("W", "E"):
            scr_h = desk_h_px * _SCREEN_LEN_RATIO
            scr_y1 = (y1 + y2) / 2 - scr_h / 2
            scr_y2 = scr_y1 + scr_h
            if scr_side == "W":
                scr_x1 = x1 + _SCREEN_INSET_PX
            else:
                scr_x1 = x2 - _SCREEN_INSET_PX - _SCREEN_THICK_PX
            scr_x2 = scr_x1 + _SCREEN_THICK_PX
        else:
            scr_w = desk_w_px * _SCREEN_LEN_RATIO
            scr_x1 = (x1 + x2) / 2 - scr_w / 2
            scr_x2 = scr_x1 + scr_w
            if scr_side == "N":
                scr_y1 = y1 + _SCREEN_INSET_PX
            else:
                scr_y1 = y2 - _SCREEN_INSET_PX - _SCREEN_THICK_PX
            scr_y2 = scr_y1 + _SCREEN_THICK_PX
        draw.rectangle([scr_x1, scr_y1, scr_x2, scr_y2],
                       fill=_SCREEN_FILL)

        # Label centered in desk
        label = f"{room['name']}.{desk_local_idx}"
        tb = draw.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        draw.text(
            ((x1 + x2) / 2 - tw / 2, (y1 + y2) / 2 - th / 2),
            label, fill=_LABEL_COLOR, font=font,
        )

    # D-266: Draw cabinets (furniture) as B&W rectangles — no chair/screen/label
    for item in furniture:
        if item.get("type") != "CABINET":
            continue
        f_w = _pg.CABINET_W_CM
        f_d = _pg.CABINET_D_CM
        if item.get("orientation") == 90:
            f_w, f_d = f_d, f_w
        ax, ay, aw, ad = _decanon_rect(
            item["x_cm"], item["y_cm"], f_w, f_d,
            canon_w, canon_d, cf_abs,
        )
        x1 = bbox[0] + ax / scale
        y1 = bbox[1] + ay / scale
        x2 = x1 + aw / scale
        y2 = y1 + ad / scale
        draw.rectangle(
            [x1, y1, x2, y2],
            outline=_DESK_OUTLINE,
            fill=_DESK_FILL,
            width=_DESK_STROKE_WIDTH,
        )


# ---------------------------------------------------------------------------
# Floor-summary cartouche
# ---------------------------------------------------------------------------

_SURFACE_RE = re.compile(r"([\d.]+)")


def _parse_surface_m2(surface_str: str) -> float | None:
    """Parse a surface string like ``'16.84 m2'`` to float.

    Returns:
        Parsed value, or ``None`` if unparseable.
    """
    m = _SURFACE_RE.match(surface_str)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _compute_floor_summary(
    plan_id: str,
    rooms_payload: list[dict],
    scale_cm_per_px: float,
) -> dict:
    """Aggregate floor-level statistics for the export cartouche.

    Args:
        plan_id: Plan identifier (resolves to ``<plan_id>.json``).
        rooms_payload: Room dicts from the UI.
        scale_cm_per_px: cm per pixel.

    Returns:
        Dict with keys ``furnished_offices``, ``total_offices``,
        ``furnished_area``, ``total_area``, ``total_workstations``,
        ``avg_area``.
    """
    plans_dir = get_plans_dir()
    json_path = os.path.join(plans_dir, f"{plan_id}.json")

    # Load JSON plan for total rooms + annotated surfaces
    plan_rooms: dict[str, dict] = {}
    if os.path.isfile(json_path):
        try:
            with open(json_path, encoding="utf-8") as f:
                plan_data = json.load(f)
            plan_rooms = plan_data.get("rooms", {})
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cannot load plan JSON %s: %s", json_path, exc)
    else:
        logger.warning("Plan JSON not found: %s", json_path)

    # Build payload lookup by name
    payload_by_name: dict[str, dict] = {}
    for room in rooms_payload:
        name = room.get("name", "")
        if name:
            payload_by_name[name] = room

    # Union of all room identifiers
    all_names = set(plan_rooms.keys()) | set(payload_by_name.keys())

    # Surface helper for a room in the union
    def _surface(name: str) -> float:
        # 1. JSON annotated surface
        jr = plan_rooms.get(name)
        if jr:
            s = _parse_surface_m2(jr.get("surface", ""))
            if s is not None:
                return s
        # 2. Payload bbox (width_cm * depth_cm)
        pr = payload_by_name.get(name)
        if pr:
            w = pr.get("width_cm", 0)
            d = pr.get("depth_cm", 0)
            if w and d:
                return round(w * d / 10000, 2)
        # 3. JSON bbox_px + scale
        if jr and scale_cm_per_px > 0:
            bbox = jr.get("bbox_px")
            if bbox and len(bbox) >= 4:
                w_px = bbox[2] - bbox[0]
                h_px = bbox[3] - bbox[1]
                w_cm = w_px * scale_cm_per_px
                d_cm = h_px * scale_cm_per_px
                return round(w_cm * d_cm / 10000, 2)
        return 0.0

    # Aggregate
    furnished_offices = 0
    furnished_area = 0.0
    total_workstations = 0

    for room in rooms_payload:
        candidate = room.get("candidate")
        if not candidate:
            continue
        furnished_offices += 1
        name = room.get("name", "")
        furnished_area += _surface(name)
        total_workstations += len(_get_active_desks(candidate))

    total_offices = len(all_names)
    total_area = sum(_surface(n) for n in all_names)
    avg_area: float | None = None
    if total_workstations > 0:
        avg_area = round(furnished_area / total_workstations, 2)

    return {
        "furnished_offices": furnished_offices,
        "total_offices": total_offices,
        "furnished_area": round(furnished_area, 1),
        "total_area": round(total_area, 1),
        "total_workstations": total_workstations,
        "avg_area": avg_area,
    }


def _draw_cartouche(
    img: Image.Image,
    summary: dict,
) -> None:
    """Draw the floor-summary cartouche in the top-left corner.

    Composites a semi-opaque background onto *img* in-place, then draws
    text lines on top. Font sizes (title/body, in points) and the (x, y)
    pixel position are read from app config (Settings), with fallbacks.

    Args:
        img: RGBA PIL image (modified in-place).
        summary: Dict from ``_compute_floor_summary``.
    """
    from datetime import date

    from olm.core import app_config
    title_pt = max(6, int(app_config.get(
        "cartouche_title_pt", _CARTOUCHE_TITLE_PT_DEFAULT)
        or _CARTOUCHE_TITLE_PT_DEFAULT))
    body_pt = max(6, int(app_config.get(
        "cartouche_body_pt", _CARTOUCHE_BODY_PT_DEFAULT)
        or _CARTOUCHE_BODY_PT_DEFAULT))
    x0 = max(0, int(app_config.get(
        "cartouche_x_px", _CARTOUCHE_X_PX_DEFAULT)))
    y0 = max(0, int(app_config.get(
        "cartouche_y_px", _CARTOUCHE_Y_PX_DEFAULT)))
    title_font = _cartouche_font(title_pt)
    body_font = _cartouche_font(body_pt)
    footer_font = _cartouche_font(max(6, body_pt - _CARTOUCHE_FOOTER_PT_DROP))

    avg_str = (
        f"{summary['avg_area']:.1f}" if summary["avg_area"] is not None
        else "n/a"
    )
    # (text, font) per line — title in the larger font, the rest in body.
    items = [
        ("Floor Layout", title_font),
        (f"Furnished offices: {summary['furnished_offices']}"
         f" / {summary['total_offices']}", body_font),
        (f"Furnished area: {summary['furnished_area']:.1f}"
         f" / {summary['total_area']:.1f} m2", body_font),
        (f"Total workstations: {summary['total_workstations']}", body_font),
        (f"Avg area / workstation: {avg_str} m2", body_font),
        (f"Export done on {date.today().isoformat()}", footer_font),
    ]

    # Measure text extents
    tmp_draw = ImageDraw.Draw(img)
    line_heights: list[int] = []
    max_width = 0
    for text, fnt in items:
        tb = tmp_draw.textbbox((0, 0), text, font=fnt)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        line_heights.append(th)
        if tw > max_width:
            max_width = tw

    total_text_h = (
        sum(line_heights)
        + _CARTOUCHE_LINE_SPACING * (len(items) - 1)
    )
    box_w = max_width + _CARTOUCHE_PADDING * 2
    box_h = total_text_h + _CARTOUCHE_PADDING * 2

    # Semi-opaque background via overlay + alpha_composite
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.rectangle(
        [x0, y0, x0 + box_w, y0 + box_h],
        fill=_CARTOUCHE_BG,
        outline=_CARTOUCHE_BORDER,
        width=_CARTOUCHE_BORDER_W,
    )
    composited = Image.alpha_composite(img, overlay)
    img.paste(composited)

    # Text lines (on top of the composited background)
    draw = ImageDraw.Draw(img)
    ty = y0 + _CARTOUCHE_PADDING
    for i, (text, fnt) in enumerate(items):
        draw.text(
            (x0 + _CARTOUCHE_PADDING, ty),
            text, fill=_CARTOUCHE_TEXT, font=fnt,
        )
        ty += line_heights[i] + _CARTOUCHE_LINE_SPACING


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

_CSV_HEADER = [
    "room_code", "width_cm", "depth_cm", "surface_m2",
    "selected_pattern", "standard", "n_desks", "m2_per_desk",
    "circulation_grade", "connectivity_pct", "min_passage_cm",
    "worst_detour", "largest_free_rect_m2", "removed_desks_count",
    "manual_amendments",
]


def write_csv(rooms_payload: list[dict], output_path: str) -> str:
    """Write room data as a semicolon-separated CSV.

    Args:
        rooms_payload: Room dicts with ``candidate`` info.
        output_path: Absolute path for the CSV file.

    Returns:
        Absolute path of the written file.
    """
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(_CSV_HEADER)
        for room in rooms_payload:
            name = room.get("name", "")
            w_cm = room.get("width_cm", 0)
            d_cm = room.get("depth_cm", 0)
            surface = round(w_cm * d_cm / 10000, 2)
            candidate = room.get("candidate")
            if not candidate:
                writer.writerow([name, w_cm, d_cm, surface] + [""] * 11)
                continue
            desks = candidate.get("desks") or []
            removed = sum(1 for dk in desks if dk.get("removed"))
            is_amended = "yes" if room.get("is_amended") else "no"
            writer.writerow([
                name, w_cm, d_cm, surface,
                candidate.get("pattern_name", ""),
                candidate.get("standard", ""),
                candidate.get("n_desks", ""),
                candidate.get("m2_per_desk", ""),
                candidate.get("circulation_grade", ""),
                candidate.get("connectivity_pct", ""),
                candidate.get("min_passage_cm", ""),
                candidate.get("worst_detour", ""),
                candidate.get("largest_free_rect_m2", ""),
                removed,
                is_amended,
            ])
    return os.path.abspath(output_path)


# ---------------------------------------------------------------------------
# export_plan — orchestrator
# ---------------------------------------------------------------------------


def export_plan(
    plan_id: str,
    rooms_payload: list[dict],
    scale_cm_per_px: float,
    fmt: str,
) -> dict:
    """Export plan image (PNG or PDF) + CSV to disk.

    Args:
        plan_id: Plan identifier.
        rooms_payload: Room dicts (source of truth from the UI).
        scale_cm_per_px: Scale factor.
        fmt: ``"png"`` or ``"pdf"``.

    Returns:
        ``{"plan_path": <abs>, "csv_path": <abs>, "n_rooms": N}``.
    """
    output_dir = os.path.join(PROJECT_ROOT, "project", "exports", plan_id)
    os.makedirs(output_dir, exist_ok=True)

    # D-262: purge previous outputs for this plan before writing, so the
    # folder always reflects a single, consistent export. Otherwise the
    # format NOT re-exported (e.g. an old PNG when exporting a PDF) keeps its
    # stale date, which looks wrong next to the freshly-written CSV. Removing
    # then recreating the file also refreshes its date (Windows preserves a
    # file's creation date when it is overwritten in place).
    for _ext in ("png", "pdf", "csv"):
        try:
            os.remove(os.path.join(output_dir, f"{plan_id}.{_ext}"))
        except FileNotFoundError:
            pass

    _EXPORT_DEBUG.clear()
    img = compose_plan_image(plan_id, rooms_payload, scale_cm_per_px)
    # D-264 diagnostic file (temporary) — dropped next to the export.
    try:
        with open(os.path.join(output_dir, f"{plan_id}_DEBUG.txt"),
                  "w", encoding="utf-8") as _df:
            _df.write("\n".join(_EXPORT_DEBUG) + "\n")
    except OSError:
        pass

    if fmt == "png":
        plan_path = os.path.join(output_dir, f"{plan_id}.png")
        img.save(plan_path, "PNG")
    else:
        # Pillow's PDF writer embeds the image with proper compression
        # (JPEG for RGB, FlateDecode for RGBA) — file size stays close
        # to the PNG. pymupdf's insert_image used to re-encode the image
        # as raw flate-compressed RGB, blowing the file up 30-80x.
        plan_path = os.path.join(output_dir, f"{plan_id}.pdf")
        img.save(plan_path, "PDF", resolution=100.0)

    csv_path = os.path.join(output_dir, f"{plan_id}.csv")
    write_csv(rooms_payload, csv_path)

    return {
        "plan_path": os.path.abspath(plan_path),
        "csv_path": os.path.abspath(csv_path),
        "exports_dir": os.path.abspath(output_dir),
        "n_rooms": len(rooms_payload),
    }
