"""Generate scaled plan variants from a preprocessed source plan.

Usage::

    python scripts/generate_plan_variants.py \\
        --source big_pillars \\
        --output-dir project/plans/

Produces test_office_{1,2,3}.json + test_office_{1,2,3}-SD.png.
Idempotent: two successive runs yield byte-identical files.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import statistics
import sys
from typing import Any

from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARC_STROKE_PX = 2
"""Stroke width (pixels) for door arc drawings."""

SEED_INSET_PX = 50
"""How far inside the room (pixels) to place generated door seeds."""

WALL_COLOR_RGB = (0, 0, 0)
"""Color used to paint walls (black)."""

DOOR_GAP_COLOR_RGB = (220, 220, 220)
"""Color used to paint door/opening/window gaps (light grey)."""

INTERIOR_COLOR_RGB = (255, 255, 255)
"""Color used to paint room interiors (white)."""

DEFAULT_VARIANT_NAMES = ("test_office_1", "test_office_2", "test_office_3")
"""Default output variant basenames."""

VARIANT_SCALE_MULTIPLIERS = (1.0, 1.2, 1.44)
"""Cumulative multipliers applied on top of factor_v1 for V1, V2, V3."""

SOURCE_PREFIX = "test_floorplan_preprocessed_"
"""Naming convention prefix for source plan files."""

_WALL_DARK_THRESHOLD = 128
"""Per-channel RGB threshold below which a pixel is considered wall."""

_WALL_SAMPLE_FRACTIONS = (0.2, 0.4, 0.6, 0.8)
"""Fractional positions along each bbox edge where wall thickness is sampled."""

_WALL_SCAN_INSET_PX = 15
"""How far inside the room to start the scan-through measurement."""

_MAX_WALL_SCAN_PX = 50
"""Maximum scan distance (pixels) for wall measurement."""

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _parse_scale_measured(text: str) -> float:
    """Parse ``"X.XXXX cm/px"`` into a float."""
    return float(text.strip().split()[0])


def _format_scale_measured(value: float) -> str:
    """Format a cm/px float back to the canonical string."""
    return f"{value:.4f} cm/px"


def _parse_scale_text(text: str) -> int:
    """Parse ``"1 : N"`` and return N as int."""
    return int(text.strip().split(":")[-1].strip())


def _format_scale_text(n: int) -> str:
    """Format N back to ``"1 : N"``."""
    return f"1 : {n}"


def _compute_median_door_width_cm(
    rooms: dict[str, Any],
    source_scale: float,
) -> float:
    """Return median width_cm of all typed doors across rooms."""
    widths: list[float] = []
    for room in rooms.values():
        for door in room.get("doors", []):
            w_px = door.get("width_px", 0)
            if w_px > 0:
                widths.append(w_px * source_scale)
    if not widths:
        raise ValueError("No typed doors found in source — cannot compute median")
    return statistics.median(widths)


def _parse_surface(text: str) -> float:
    """Parse ``"X.XX m2"`` into a float (m²)."""
    return float(text.strip().split()[0])


def _scale_surface(source_surface: str, cumulative_factor: float) -> str:
    """Scale a source surface by cumulative_factor² (area homothétie)."""
    src_m2 = _parse_surface(source_surface)
    return f"{src_m2 * cumulative_factor ** 2:.2f} m2"


def _generate_door_seed(
    face: str,
    offset_px: int,
    width_px: int,
    bbox_px: list[int],
) -> dict[str, int]:
    """Compute a door seed point inside the room for a typed door."""
    x1, y1, x2, y2 = bbox_px
    mid = offset_px + width_px // 2
    if face == "south":
        return {"seed_x": x1 + mid, "seed_y": y2 - SEED_INSET_PX}
    elif face == "north":
        return {"seed_x": x1 + mid, "seed_y": y1 + SEED_INSET_PX}
    elif face == "east":
        return {"seed_x": x2 - SEED_INSET_PX, "seed_y": y1 + mid}
    elif face == "west":
        return {"seed_x": x1 + SEED_INSET_PX, "seed_y": y1 + mid}
    else:
        raise ValueError(f"Unknown face: {face}")


# ---------------------------------------------------------------------------
# JSON variant generation
# ---------------------------------------------------------------------------


def generate_variant_json(
    source: dict[str, Any],
    cumulative_factor: float,
    freeze_doors_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a scaled variant of *source* JSON.

    Args:
        source: the original plan JSON (not mutated).
        cumulative_factor: total scale multiplier vs source.
        freeze_doors_from: if provided, a previously generated variant
            JSON from which door offset_cm values are frozen (V2/V3).

    Returns:
        New plan JSON dict.
    """
    variant = copy.deepcopy(source)
    source_scale = _parse_scale_measured(source["drawing_scale_measured"])
    source_n = _parse_scale_text(source["drawing_scale_text"])

    new_scale = source_scale * cumulative_factor
    variant["drawing_scale_measured"] = _format_scale_measured(new_scale)
    variant["drawing_scale_text"] = _format_scale_text(
        round(source_n * cumulative_factor),
    )

    for rid, room in variant.get("rooms", {}).items():
        bbox_px = room.get("bbox_px")
        if not bbox_px or len(bbox_px) != 4:
            continue

        # Surface: homothétie on source value (not recomputed from bbox)
        src_room = source.get("rooms", {}).get(rid, {})
        if src_room.get("surface"):
            room["surface"] = _scale_surface(
                src_room["surface"], cumulative_factor,
            )

        # Exclusion zones scaled
        for ez in room.get("exclusion_zones", []):
            for key in ("x_cm", "y_cm", "width_cm", "depth_cm"):
                if key in ez:
                    ez[key] = round(ez[key] * cumulative_factor)

        # Doors
        doors = room.get("doors", [])
        if freeze_doors_from is not None:
            # V2/V3: freeze offset_cm and width_cm from V1
            frozen_room = freeze_doors_from.get("rooms", {}).get(rid, {})
            frozen_doors = frozen_room.get("doors", [])
            for i, door in enumerate(doors):
                if i < len(frozen_doors):
                    frozen_offset_cm = (
                        frozen_doors[i].get("offset_px", 0)
                        * _parse_scale_measured(
                            freeze_doors_from["drawing_scale_measured"]
                        )
                    )
                    door["width_px"] = round(90 / new_scale)
                    door["offset_px"] = round(frozen_offset_cm / new_scale)
        else:
            # V1: homothétie pure, force width_cm = 90
            for door in doors:
                door["width_px"] = round(90 / new_scale)
                # offset_px unchanged (homothétie pure on offset)

        # Door seeds: regenerated from typed doors
        if doors:
            room["door_seeds"] = [
                _generate_door_seed(
                    d["face"], d["offset_px"], d["width_px"], bbox_px,
                )
                for d in doors
            ]
        else:
            # Convention: absent if empty
            room.pop("door_seeds", None)

    return variant


# ---------------------------------------------------------------------------
# Wall measurement
# ---------------------------------------------------------------------------


def _is_wall_pixel(pixel: tuple[int, ...]) -> bool:
    """Return True if the pixel is dark enough to be part of a wall."""
    return all(c < _WALL_DARK_THRESHOLD for c in pixel[:3])


def _scan_through_wall(
    pixels: Any,
    start_x: int,
    start_y: int,
    dx: int,
    dy: int,
    img_w: int,
    img_h: int,
) -> int:
    """Scan from a bright interior point through a wall to the exterior.

    Expects to start in a bright zone (room interior), pass through a
    dark zone (wall), and exit into another bright zone (corridor or
    adjacent room). Returns the width of the dark zone in pixels.

    Args:
        pixels: PIL PixelAccess object.
        start_x, start_y: starting point inside the room.
        dx, dy: scan direction (one of them must be 0, the other ±1).
        img_w, img_h: image dimensions.

    Returns:
        Width of the wall in pixels, or 0 if no wall found.
    """
    wall_start = -1
    wall_end = -1

    for step in range(_MAX_WALL_SCAN_PX):
        nx = start_x + dx * step
        ny = start_y + dy * step
        if not (0 <= nx < img_w and 0 <= ny < img_h):
            break

        is_dark = _is_wall_pixel(pixels[nx, ny])

        if wall_start < 0:
            if is_dark:
                wall_start = step
        else:
            if not is_dark:
                wall_end = step
                break

    if wall_start >= 0 and wall_end > wall_start:
        return wall_end - wall_start
    return 0


def _measure_wall_thickness(
    img: Image.Image,
    rooms: dict[str, Any],
) -> int:
    """Auto-measure wall thickness from the source image.

    For each room with a bbox, scans from inside the room outward
    through each wall, measuring the width of the dark pixel band.
    Returns the median of all non-zero measurements.
    """
    pixels = img.load()
    img_w, img_h = img.size
    measurements: list[int] = []

    for room in rooms.values():
        bbox = room.get("bbox_px")
        if not bbox or len(bbox) != 4:
            continue
        bx1, by1, bx2, by2 = bbox
        inset = _WALL_SCAN_INSET_PX

        for frac in _WALL_SAMPLE_FRACTIONS:
            sx = int(bx1 + (bx2 - bx1) * frac)
            sy = int(by1 + (by2 - by1) * frac)

            # North wall: scan upward from inside.
            w = _scan_through_wall(
                pixels, sx, by1 + inset, 0, -1, img_w, img_h,
            )
            if w > 0:
                measurements.append(w)

            # South wall: scan downward from inside.
            w = _scan_through_wall(
                pixels, sx, by2 - inset, 0, 1, img_w, img_h,
            )
            if w > 0:
                measurements.append(w)

            # West wall: scan leftward from inside.
            w = _scan_through_wall(
                pixels, bx1 + inset, sy, -1, 0, img_w, img_h,
            )
            if w > 0:
                measurements.append(w)

            # East wall: scan rightward from inside.
            w = _scan_through_wall(
                pixels, bx2 - inset, sy, 1, 0, img_w, img_h,
            )
            if w > 0:
                measurements.append(w)

    if not measurements:
        raise ValueError(
            "No wall measurements obtained from source image",
        )

    result = round(statistics.median(measurements))
    logger.info(
        "Auto-measured wall thickness: %d px (from %d samples)",
        result, len(measurements),
    )
    return result


# ---------------------------------------------------------------------------
# PNG variant generation
# ---------------------------------------------------------------------------


def _gap_region(
    face: str,
    bbox_px: list[int],
    offset_px: int,
    width_px: int,
    half_wall: int,
) -> tuple[int, int, int, int]:
    """Return (x0, y0, x1, y1) for a gap on the wall band.

    The gap is ``width_px`` wide along the wall and spans the full
    wall thickness centered on the bbox edge.
    """
    bx1, by1, bx2, by2 = bbox_px
    if face == "south":
        return (bx1 + offset_px, by2 - half_wall,
                bx1 + offset_px + width_px, by2 + half_wall)
    elif face == "north":
        return (bx1 + offset_px, by1 - half_wall,
                bx1 + offset_px + width_px, by1 + half_wall)
    elif face == "east":
        return (bx2 - half_wall, by1 + offset_px,
                bx2 + half_wall, by1 + offset_px + width_px)
    elif face == "west":
        return (bx1 - half_wall, by1 + offset_px,
                bx1 + half_wall, by1 + offset_px + width_px)
    else:
        raise ValueError(f"Unknown face: {face}")


def _draw_door_arc(
    draw: ImageDraw.Draw,
    face: str,
    bbox_px: list[int],
    offset_px: int,
    width_px: int,
    hinge_side: str,
    opens_inward: bool,
) -> None:
    """Draw a door arc + panel line at the given position.

    Convention (absolute/image coordinates):
      - hinge_side is "left"/"right" as seen from OUTSIDE the room
        looking at the wall.
      - opens_inward = True means arc + panel extend toward the room
        interior.

    Pillow angle convention: 0 = east (3 o'clock), increasing clockwise.
    """
    bx1, by1, bx2, by2 = bbox_px
    r = width_px  # Arc radius = door width.

    # Compute hinge center (cx, cy), panel endpoint (px_, py_),
    # and arc angles.
    #
    # Horizontal faces (south/north):
    #   xs = bx1 + offset_px  (start of gap along wall)
    #   xe = xs + r            (end of gap along wall)
    #
    # Vertical faces (east/west):
    #   ys = by1 + offset_px
    #   ye = ys + r

    if face == "south":
        xs, xe, wy = bx1 + offset_px, bx1 + offset_px + r, by2
        if hinge_side == "left":
            # Left from outside south = west = xs.
            cx, cy = xs, wy
            px_, py_ = xs, (wy - r if opens_inward else wy + r)
            angles = (270, 360) if opens_inward else (0, 90)
        else:
            cx, cy = xe, wy
            px_, py_ = xe, (wy - r if opens_inward else wy + r)
            angles = (180, 270) if opens_inward else (90, 180)

    elif face == "north":
        xs, xe, wy = bx1 + offset_px, bx1 + offset_px + r, by1
        if hinge_side == "left":
            # Left from outside north = east = xe.
            cx, cy = xe, wy
            px_, py_ = xe, (wy + r if opens_inward else wy - r)
            angles = (90, 180) if opens_inward else (180, 270)
        else:
            # Right from outside north = west = xs.
            cx, cy = xs, wy
            px_, py_ = xs, (wy + r if opens_inward else wy - r)
            angles = (0, 90) if opens_inward else (270, 360)

    elif face == "east":
        ys, ye, wx = by1 + offset_px, by1 + offset_px + r, bx2
        if hinge_side == "left":
            # Left from outside east = south = ye.
            cx, cy = wx, ye
            px_, py_ = (wx - r if opens_inward else wx + r), ye
            angles = (180, 270) if opens_inward else (270, 360)
        else:
            # Right from outside east = north = ys.
            cx, cy = wx, ys
            px_, py_ = (wx - r if opens_inward else wx + r), ys
            angles = (90, 180) if opens_inward else (0, 90)

    elif face == "west":
        ys, ye, wx = by1 + offset_px, by1 + offset_px + r, bx1
        if hinge_side == "left":
            # Left from outside west = north = ys.
            cx, cy = wx, ys
            px_, py_ = (wx + r if opens_inward else wx - r), ys
            angles = (0, 90) if opens_inward else (90, 180)
        else:
            # Right from outside west = south = ye.
            cx, cy = wx, ye
            px_, py_ = (wx + r if opens_inward else wx - r), ye
            angles = (270, 360) if opens_inward else (180, 270)

    else:
        raise ValueError(f"Unknown face: {face}")

    # Draw panel (line from hinge to panel end).
    draw.line(
        [(cx, cy), (px_, py_)],
        fill=WALL_COLOR_RGB,
        width=ARC_STROKE_PX,
    )

    # Draw arc.
    arc_bbox = (cx - r, cy - r, cx + r, cy + r)
    draw.arc(
        arc_bbox, angles[0], angles[1],
        fill=WALL_COLOR_RGB, width=ARC_STROKE_PX,
    )


def generate_variant_png(
    source_img: Image.Image,
    source_json: dict[str, Any],
    variant_json: dict[str, Any],
) -> Image.Image:
    """Create a variant PNG by repainting each room from scratch.

    Option C approach: start from source image copy (corridors and
    exterior preserved), then for each room: paint white interior,
    redraw black walls, paint gaps, paint exclusion zones, draw arcs.
    """
    img = source_img.copy()
    draw = ImageDraw.Draw(img)

    source_rooms = source_json.get("rooms", {})
    variant_rooms = variant_json.get("rooms", {})

    # Auto-measure wall thickness from source image.
    wall_thickness = _measure_wall_thickness(img, source_rooms)
    half_wall = wall_thickness // 2

    variant_scale = _parse_scale_measured(
        variant_json["drawing_scale_measured"],
    )

    for rid, v_room in variant_rooms.items():
        s_room = source_rooms.get(rid, {})
        bbox = v_room.get("bbox_px")
        if not bbox or len(bbox) != 4:
            continue

        bx1, by1, bx2, by2 = bbox

        # --- Step 1: erase source walls + interior. ---
        # Paint a white rectangle covering bbox + margin to remove
        # leftover source wall pixels (anti-aliasing, transitions).
        # The wall bands painted in step 2 will restore the walls.
        erase_margin = wall_thickness + 2
        draw.rectangle(
            (bx1 - erase_margin, by1 - erase_margin,
             bx2 + erase_margin, by2 + erase_margin),
            fill=INTERIOR_COLOR_RGB,
        )

        # --- Step 2: paint 4 wall bands centered on bbox edges. ---
        # North wall.
        draw.rectangle(
            (bx1 - half_wall, by1 - half_wall,
             bx2 + half_wall, by1 + half_wall),
            fill=WALL_COLOR_RGB,
        )
        # South wall.
        draw.rectangle(
            (bx1 - half_wall, by2 - half_wall,
             bx2 + half_wall, by2 + half_wall),
            fill=WALL_COLOR_RGB,
        )
        # West wall.
        draw.rectangle(
            (bx1 - half_wall, by1 - half_wall,
             bx1 + half_wall, by2 + half_wall),
            fill=WALL_COLOR_RGB,
        )
        # East wall.
        draw.rectangle(
            (bx2 - half_wall, by1 - half_wall,
             bx2 + half_wall, by2 + half_wall),
            fill=WALL_COLOR_RGB,
        )

        # --- Step 3: paint variant door gaps. ---
        for door in v_room.get("doors", []):
            region = _gap_region(
                door["face"], bbox,
                door["offset_px"], door["width_px"],
                half_wall,
            )
            draw.rectangle(region, fill=DOOR_GAP_COLOR_RGB)

        # --- Step 4: paint source opening gaps (unchanged). ---
        for opening in s_room.get("openings", []):
            if "offset_px" in opening and "width_px" in opening:
                region = _gap_region(
                    opening["face"], bbox,
                    opening["offset_px"], opening["width_px"],
                    half_wall,
                )
                draw.rectangle(region, fill=DOOR_GAP_COLOR_RGB)

        # --- Step 5: paint source window gaps (unchanged). ---
        for window in s_room.get("windows", []):
            if "offset_px" in window and "width_px" in window:
                region = _gap_region(
                    window["face"], bbox,
                    window["offset_px"], window["width_px"],
                    half_wall,
                )
                draw.rectangle(region, fill=DOOR_GAP_COLOR_RGB)

        # --- Step 6: paint exclusion zones as black rectangles. ---
        for ez in v_room.get("exclusion_zones", []):
            ex_x = round(ez["x_cm"] / variant_scale)
            ex_y = round(ez["y_cm"] / variant_scale)
            ex_w = round(ez["width_cm"] / variant_scale)
            ex_d = round(ez["depth_cm"] / variant_scale)
            draw.rectangle(
                (bx1 + ex_x, by1 + ex_y,
                 bx1 + ex_x + ex_w - 1, by1 + ex_y + ex_d - 1),
                fill=WALL_COLOR_RGB,
            )

        # --- Step 7: draw door arcs at variant positions. ---
        for door in v_room.get("doors", []):
            hinge = door.get("hinge_side", "left")
            inward = door.get("opens_inward", True)
            _draw_door_arc(
                draw, door["face"], bbox,
                door["offset_px"], door["width_px"],
                hinge, inward,
            )

    return img


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def generate_variants(
    source_basename: str,
    output_dir: str,
    variant_names: tuple[str, ...] = DEFAULT_VARIANT_NAMES,
) -> list[str]:
    """Generate all plan variants from a source plan.

    Args:
        source_basename: e.g. ``"big_pillars"`` — used to build file paths.
        output_dir: directory for output files.
        variant_names: tuple of variant basenames.

    Returns:
        List of generated file paths.
    """
    source_json_path = os.path.join(
        output_dir, f"{SOURCE_PREFIX}{source_basename}.json",
    )
    source_png_path = os.path.join(
        output_dir, f"{SOURCE_PREFIX}{source_basename}-SD.png",
    )

    if not os.path.exists(source_json_path):
        raise FileNotFoundError(
            f"Source JSON not found: {source_json_path}",
        )
    if not os.path.exists(source_png_path):
        raise FileNotFoundError(
            f"Source PNG not found: {source_png_path}",
        )

    with open(source_json_path) as f:
        source_json = json.load(f)

    source_img = Image.open(source_png_path).convert("RGB")

    source_scale = _parse_scale_measured(
        source_json["drawing_scale_measured"],
    )
    median_width_cm = _compute_median_door_width_cm(
        source_json["rooms"], source_scale,
    )
    factor_v1 = 90.0 / median_width_cm
    logger.info(
        "Median door width: %.2f cm — factor_v1 = %.4f",
        median_width_cm, factor_v1,
    )

    generated_files: list[str] = []
    v1_json: dict[str, Any] | None = None
    empty_pnginfo = PngInfo()

    for idx, (name, mult) in enumerate(
        zip(variant_names, VARIANT_SCALE_MULTIPLIERS),
    ):
        cumulative = factor_v1 * mult
        logger.info(
            "Generating %s: cumulative_factor=%.4f", name, cumulative,
        )

        freeze_from = v1_json if idx > 0 else None
        variant_json = generate_variant_json(
            source_json, cumulative, freeze_from,
        )

        if idx == 0:
            v1_json = variant_json

        # Write JSON
        json_path = os.path.join(output_dir, f"{name}.json")
        with open(json_path, "w") as f:
            json.dump(variant_json, f, indent=2, sort_keys=True)
            f.write("\n")
        generated_files.append(json_path)

        # Write PNG
        png_path = os.path.join(output_dir, f"{name}-SD.png")
        variant_img = generate_variant_png(
            source_img, source_json, variant_json,
        )
        variant_img.save(png_path, pnginfo=empty_pnginfo)
        generated_files.append(png_path)

    logger.info("Generated %d files.", len(generated_files))
    return generated_files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s  %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Generate scaled plan variants from a preprocessed"
        " source.",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Source plan basename (e.g. 'big_pillars').",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory containing source files and receiving outputs.",
    )
    parser.add_argument(
        "--variants",
        default=",".join(DEFAULT_VARIANT_NAMES),
        help="Comma-separated variant names (default: %(default)s).",
    )
    args = parser.parse_args()

    variant_names = tuple(v.strip() for v in args.variants.split(","))
    generate_variants(args.source, args.output_dir, variant_names)


if __name__ == "__main__":
    main()
