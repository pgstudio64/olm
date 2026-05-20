"""Pattern classification — ok / tolere / reject.

Classifies a catalogue pattern based on geometric conflicts within its
declared room (room_width_cm x room_depth_cm).  No wall-pushing: the
room dimensions are taken as-is.

Classification rules (precedence: reject > tolere > ok):
- **reject**: block body outside room, door exclusion overlaps block body,
  or two block total footprints overlap.
- **tolere**: door exclusion overlaps a block's soft margin (face zones)
  but not its body.
- **ok**: no conflict.
"""
from __future__ import annotations

import logging
from typing import Literal

from olm.core.catalogue_matcher import BlockPosition, compute_block_positions
from olm.core.pattern_fit import get_face_zones, rects_overlap
from olm.core.spacing_config import SpacingConfig, build_block_defs

logger = logging.getLogger(__name__)

FitClass = Literal["ok", "tolere", "reject"]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _block_body(bp: BlockPosition) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) of the block body (desks only)."""
    return (bp.x_cm, bp.y_cm, bp.eo_cm, bp.ns_cm)


def _block_footprint(
    bp: BlockPosition,
    block_defs: dict[str, dict],
) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) of the total footprint (body + face zones)."""
    fc = get_face_zones(bp.block_type, bp.orientation, block_defs)
    x = bp.x_cm - fc.west.outer_cm
    y = bp.y_cm - fc.north.outer_cm
    w = bp.eo_cm + fc.west.outer_cm + fc.east.outer_cm
    h = bp.ns_cm + fc.north.outer_cm + fc.south.outer_cm
    return (x, y, w, h)


def _door_exclusion_rects(
    pattern: dict,
    spacing: SpacingConfig,
) -> list[tuple[float, float, float, float]]:
    """Build exclusion rectangles for doors in the pattern.

    Each rectangle is (x, y, w, h) in pattern coordinates, anchored on
    the door's wall face and extending inward by the appropriate depth.

    Args:
        pattern: Catalogue pattern dict.
        spacing: Spacing config for depth values.

    Returns:
        List of (x, y, w, h) tuples.
    """
    room_w = pattern.get("room_width_cm", 0)
    room_d = pattern.get("room_depth_cm", 0)
    rects: list[tuple[float, float, float, float]] = []

    for feat in pattern.get("room_openings", []):
        if not feat.get("has_door", False):
            continue
        face = feat.get("face", "")
        offset = feat.get("offset_cm", 0)
        width = feat.get("width_cm", 0)

        if feat.get("opens_inward", True):
            depth = spacing.door_exclusion_depth_cm
        else:
            depth = spacing.walking_margin_cm
        if depth <= 0:
            continue

        if face == "south":
            rects.append((offset, room_d - depth, width, depth))
        elif face == "north":
            rects.append((offset, 0, width, depth))
        elif face == "west":
            rects.append((0, offset, depth, width))
        elif face == "east":
            rects.append((room_w - depth, offset, depth, width))

    return rects


# ---------------------------------------------------------------------------
# Main classification
# ---------------------------------------------------------------------------


def classify_pattern(
    pattern: dict,
    spacing: SpacingConfig,
) -> FitClass:
    """Classify a pattern as ok, tolere, or reject.

    Args:
        pattern: Catalogue pattern dict.
        spacing: Spacing config for the pattern's standard.

    Returns:
        ``"ok"``, ``"tolere"``, or ``"reject"``.
    """
    room_w = pattern.get("room_width_cm", 0)
    room_d = pattern.get("room_depth_cm", 0)
    if room_w <= 0 or room_d <= 0:
        return "ok"

    positions = compute_block_positions(pattern)
    if not positions:
        return "ok"

    block_defs = build_block_defs(spacing)
    door_rects = _door_exclusion_rects(pattern, spacing)

    # --- RED checks ---

    # R1: block body outside room
    for bp in positions:
        bx, by, bw, bh = _block_body(bp)
        if bx < 0 or by < 0 or bx + bw > room_w or by + bh > room_d:
            return "reject"

    # R2: door exclusion overlaps block body
    for bp in positions:
        bx, by, bw, bh = _block_body(bp)
        for dx, dy, dw, dh in door_rects:
            if rects_overlap(bx, by, bw, bh, dx, dy, dw, dh):
                return "reject"

    # R3: two block total footprints overlap
    footprints = [_block_footprint(bp, block_defs) for bp in positions]
    for i in range(len(footprints)):
        for j in range(i + 1, len(footprints)):
            ax, ay, aw, ah = footprints[i]
            bx, by, bw, bh = footprints[j]
            if rects_overlap(ax, ay, aw, ah, bx, by, bw, bh):
                return "reject"

    # --- GREY check ---
    # Door exclusion overlaps total footprint (but not body — R2 passed)
    for fp in footprints:
        fx, fy, fw, fh = fp
        for dx, dy, dw, dh in door_rects:
            if rects_overlap(fx, fy, fw, fh, dx, dy, dw, dh):
                return "tolere"

    return "ok"
