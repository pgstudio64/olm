"""Export service — compose annotated plan image + CSV.

Generates plan export as PNG/PDF with workstation overlay and data CSV.
All desk positions come from the frontend payload (source of truth = what
the user sees). For amendments where desks are absent, positions are
recomputed from the pattern via ``compute_desk_positions``.
"""
from __future__ import annotations

import csv
import logging
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from olm.core.catalogue_matcher import compute_desk_positions
from olm.server.services.config_service import (
    PROJECT_ROOT,
    get_corridor_rgb,
    get_exterior_rgb,
    get_plans_dir,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chair side helpers — mirrors JS getDeskRects (block_geometry.js)
# ---------------------------------------------------------------------------

_SYMMETRIC_BLOCKS = frozenset({"BLOCK_2_FACE", "BLOCK_4_FACE", "BLOCK_6_FACE"})
_ORTHO_CHAIR_SIDES: dict[str, dict[int, str]] = {
    "BLOCK_2_ORTHO_R": {0: "N", 1: "E"},
    "BLOCK_2_ORTHO_L": {0: "N", 1: "W"},
}
_SIDE_ROTATE: dict[int, dict[str, str]] = {
    90:  {"N": "E", "E": "S", "S": "W", "W": "N"},
    180: {"N": "S", "S": "N", "E": "W", "W": "E"},
    270: {"N": "W", "W": "S", "S": "E", "E": "N"},
}


def _desk_chair_side_base(block_type: str, desk_idx: int) -> str:
    """Chair side at orientation 0 for a desk within a block type."""
    if block_type in _SYMMETRIC_BLOCKS:
        return "W" if desk_idx % 2 == 0 else "E"
    if block_type in _ORTHO_CHAIR_SIDES:
        return _ORTHO_CHAIR_SIDES[block_type].get(desk_idx, "W")
    return "W"


def _rotate_side(side: str, degrees: int) -> str:
    """Rotate a side direction by *degrees* (CW)."""
    if degrees % 360 == 0:
        return side
    m = _SIDE_ROTATE.get(degrees % 360)
    return m[side] if m else side


# ---------------------------------------------------------------------------
# Decanonicalization helpers
# ---------------------------------------------------------------------------

# Canonical chair_side (pattern coords) → absolute (image coords).
_CHAIR_DECANON: dict[str, dict[str, str]] = {
    "south": {"N": "N", "S": "S", "E": "E", "W": "W"},
    "north": {"N": "S", "S": "N", "E": "W", "W": "E"},
    "east":  {"N": "W", "S": "E", "E": "N", "W": "S"},
    "west":  {"N": "E", "S": "W", "E": "S", "W": "N"},
}


def _decanon_rect(
    x: float, y: float, w: float, d: float,
    room_w: float, room_d: float,
    corridor_face_abs: str,
) -> tuple[float, float, float, float]:
    """Decanonicalize a rect from canonical (corridor-south) to absolute.

    Same transform as ``decanonicalize_room`` for exclusion zones.
    *room_w* / *room_d* are the **canonical** room dimensions.

    Returns:
        ``(abs_x, abs_y, abs_w, abs_d)`` in the absolute (image) frame.
    """
    cf = corridor_face_abs
    if not cf or cf == "south":
        return x, y, w, d
    if cf == "north":
        return room_w - x - w, room_d - y - d, w, d
    if cf == "east":
        return room_d - y - d, x, d, w
    if cf == "west":
        return y, room_w - x - w, d, w
    return x, y, w, d


def _decanon_chair_side(side: str, corridor_face_abs: str) -> str:
    """Convert canonical chair side to absolute orientation."""
    m = _CHAIR_DECANON.get(corridor_face_abs or "south")
    return m.get(side, side) if m else side


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
    positions = compute_desk_positions(pattern)
    removed_set: set[tuple[int, int, int]] = set()
    for rd in pattern.get("_removed_desks", []):
        removed_set.add((rd["row"], rd["block"], rd["desk"]))

    # Build orientation lookup: (row_idx, block_idx) → orientation
    orient_map: dict[tuple[int, int], int] = {}
    for ri, row in enumerate(pattern.get("rows", [])):
        for bi, block in enumerate(row.get("blocks", [])):
            orient_map[(ri, bi)] = block.get("orientation", 0)

    desks: list[dict] = []
    for p in positions:
        orient = orient_map.get((p.row_idx, p.block_idx), 0)
        base_side = _desk_chair_side_base(p.block_type, p.desk_idx)
        chair_side = _rotate_side(base_side, orient)
        desks.append({
            "x_cm": p.x_cm,
            "y_cm": p.y_cm,
            "width_cm": p.width_cm,
            "depth_cm": p.depth_cm,
            "removed": (p.row_idx, p.block_idx, p.desk_idx) in removed_set,
            "chair_side": chair_side,
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

# Chair seat geometry (mirror of olm/static/block_constants.js CHAIR_W_CM).
# The chair is drawn as a semicircle of seat-width diameter centered on
# the chair side of the desk.
_CHAIR_SEAT_WIDTH_CM = 65

# Screen geometry — mirrors olm/static/block_svg.js.
# Black thin bar on the desk side opposite to the chair, length ratio of
# the perpendicular desk dimension. Inset from desk edge so the screen
# sits visually inside the desk.
_SCREEN_THICK_PX = 3
_SCREEN_LEN_RATIO = 0.55
_SCREEN_INSET_PX = 3
_OPPOSITE_SIDE = {"W": "E", "E": "W", "N": "S", "S": "N"}

# PIL arc angles (CW from 3 o'clock) for each absolute chair side.
_ARC_ANGLES: dict[str, tuple[int, int]] = {
    "W": (90, 270),
    "E": (270, 90),
    "N": (180, 360),
    "S": (0, 180),
}


# ---------------------------------------------------------------------------
# compose_plan_image
# ---------------------------------------------------------------------------


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
    ext_rgb = get_exterior_rgb()
    cor_rgb = get_corridor_rgb()
    arr = np.array(img)
    for rgb in (ext_rgb, cor_rgb):
        mask = (arr[:, :, :3] == np.array(rgb, dtype=np.uint8)).all(axis=2)
        arr[mask] = _WHITE
    img = Image.fromarray(arr)

    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    for room in rooms_payload:
        _draw_room_desks(draw, font, room, scale_cm_per_px)

    return img


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

    # Get desks — recompute for amendments if needed
    desks = candidate.get("desks")
    if not desks and candidate.get("pattern"):
        desks = _compute_desks_with_chair_side(candidate["pattern"])
    if not desks:
        logger.warning("Room %s: no desks to render", room.get("name"))
        return

    desk_local_idx = 0
    for desk in desks:
        if desk.get("removed"):
            continue
        desk_local_idx += 1

        # Decanonicalize rect → absolute coords (cm)
        ax, ay, aw, ad = _decanon_rect(
            desk["x_cm"], desk["y_cm"],
            desk["width_cm"], desk["depth_cm"],
            room_w, room_d, cf_abs,
        )

        # Convert cm → image px
        x1 = bbox[0] + ax / scale
        y1 = bbox[1] + ay / scale
        x2 = x1 + aw / scale
        y2 = y1 + ad / scale

        # Desk rectangle
        draw.rectangle(
            [x1, y1, x2, y2],
            outline=_DESK_OUTLINE,
            fill=_DESK_FILL,
            width=_DESK_STROKE_WIDTH,
        )

        # Chair side: canonical → absolute
        cs_canon = desk.get("chair_side", "W")
        cs_abs = _decanon_chair_side(cs_canon, cf_abs)

        # Chair arc (semicircle on the chair side).
        # Radius = half the chair-seat width, NOT the desk depth.
        arc_r_px = (_CHAIR_SEAT_WIDTH_CM / 2) / scale
        if cs_abs == "W":
            cx, cy = x1, (y1 + y2) / 2
        elif cs_abs == "E":
            cx, cy = x2, (y1 + y2) / 2
        elif cs_abs == "N":
            cx, cy = (x1 + x2) / 2, y1
        else:
            cx, cy = (x1 + x2) / 2, y2
        arc_bbox = [cx - arc_r_px, cy - arc_r_px,
                    cx + arc_r_px, cy + arc_r_px]
        angles = _ARC_ANGLES.get(cs_abs, (90, 270))
        draw.arc(arc_bbox, angles[0], angles[1],
                 fill=_CHAIR_ARC_OUTLINE, width=1)

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

    img = compose_plan_image(plan_id, rooms_payload, scale_cm_per_px)

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
