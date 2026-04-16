"""Colorize an enhanced PNG: flood-fill exterior (blue) and corridors (green).

Usage:
    python -m olm.tools.colorize_enhanced <enhanced.png> [--json <rooms.json>] [--output <out.png>]

Steps:
    1. Flood fill from 4 corners on white pixels → exterior → blue (135,206,235)
    2. For each remaining white connected component: if no room seed is inside
       → corridor → green (193,247,179)
    3. Save result.

Requires: Pillow, numpy.
"""

import argparse
import json
import logging
import sys

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

EXTERIOR_RGB = (135, 206, 235)
CORRIDOR_RGB = (193, 247, 179)
WHITE_THRESHOLD = 200


def _is_white(pixel: np.ndarray, threshold: int = WHITE_THRESHOLD) -> bool:
    return bool(np.all(pixel >= threshold))


def colorize(
    img_array: np.ndarray,
    room_seeds: list[tuple[int, int]] | None = None,
    room_bboxes: list[tuple[int, int, int, int]] | None = None,
    exterior_rgb: tuple[int, int, int] = EXTERIOR_RGB,
    corridor_rgb: tuple[int, int, int] = CORRIDOR_RGB,
    white_threshold: int = WHITE_THRESHOLD,
) -> np.ndarray:
    """Colorize an enhanced floor plan image in-place.

    Args:
        img_array: RGB numpy array (H, W, 3), modified in-place.
        room_seeds: list of (x, y) pixel positions inside rooms.
        room_bboxes: list of (x0, y0, x1, y1) bounding boxes of rooms.
        exterior_rgb: color for exterior zones.
        corridor_rgb: color for corridor zones.
        white_threshold: minimum channel value to consider a pixel "white".

    Returns:
        The modified img_array.
    """
    h, w = img_array.shape[:2]
    seeds = room_seeds or []

    from scipy.ndimage import label as ndlabel, binary_dilation

    # Detect corner color (exterior background — may be gray, not white)
    corner_color = img_array[0, 0].astype(int)
    logger.info("Corner color: RGB(%d,%d,%d)", *corner_color)

    # Wall mask: dark pixels (walls, text, lines)
    wall_threshold = 100
    wall_mask = np.any(img_array <= wall_threshold, axis=2)

    # Dilate walls to close door gaps before exterior flood fill
    dilated_walls = binary_dilation(wall_mask, iterations=8)

    # Non-wall on dilated image: everything that's not a dilated wall
    non_wall_dilated = ~dilated_walls

    # Step 1: flood fill exterior from 4 corners on dilated non-wall
    exterior_mask = np.zeros((h, w), dtype=bool)
    visited = np.zeros((h, w), dtype=bool)

    corner_seeds_px = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    queue = []
    for cx, cy in corner_seeds_px:
        if non_wall_dilated[cy, cx] and not visited[cy, cx]:
            queue.append((cx, cy))
            visited[cy, cx] = True

    while queue:
        batch = queue
        queue = []
        for px, py in batch:
            exterior_mask[py, px] = True
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = px + dx, py + dy
                if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and non_wall_dilated[ny, nx]:
                    visited[ny, nx] = True
                    queue.append((nx, ny))

    # Paint exterior (only non-wall pixels in the original image)
    white_mask = np.all(img_array >= white_threshold, axis=2)
    corner_tol = 30
    corner_similar = np.all(np.abs(img_array.astype(int) - corner_color) <= corner_tol, axis=2)
    paintable = (white_mask | corner_similar) & exterior_mask
    img_array[paintable] = exterior_rgb
    logger.info("Exterior: %d pixels painted", np.sum(paintable))

    # Step 2: remaining white zones (not exterior, not wall) → label components
    remaining_white = white_mask & ~exterior_mask
    labeled, n_components = ndlabel(remaining_white)
    logger.info("Found %d remaining white components", n_components)

    # Build set of component labels that overlap with any room bbox or contain a seed
    room_labels = set()
    for sx, sy in seeds:
        if 0 <= sx < w and 0 <= sy < h and labeled[sy, sx] > 0:
            room_labels.add(labeled[sy, sx])
    # Also mark any component whose centroid falls inside a room bbox
    if room_bboxes:
        from scipy.ndimage import center_of_mass
        centroids = center_of_mass(remaining_white, labeled, range(1, n_components + 1))
        for comp_id, (cy_c, cx_c) in enumerate(centroids, start=1):
            if comp_id in room_labels:
                continue
            for bx0, by0, bx1, by1 in room_bboxes:
                if bx0 <= cx_c <= bx1 and by0 <= cy_c <= by1:
                    room_labels.add(comp_id)
                    break

    # Paint non-room components as corridor (only large ones — skip artefacts)
    min_corridor_px = 500
    corridor_count = 0
    corridor_components = 0
    for comp_id in range(1, n_components + 1):
        if comp_id not in room_labels:
            comp_mask = labeled == comp_id
            size = np.sum(comp_mask)
            if size >= min_corridor_px:
                img_array[comp_mask] = corridor_rgb
                corridor_count += size
                corridor_components += 1

    logger.info("Corridors: %d pixels painted (%d components, skipped %d small)",
                corridor_count, corridor_components,
                n_components - len(room_labels) - corridor_components)

    return img_array


def main():
    parser = argparse.ArgumentParser(description="Colorize enhanced PNG")
    parser.add_argument("input", help="Path to enhanced PNG")
    parser.add_argument("--json", help="Path to rooms JSON v3 (for seed positions)")
    parser.add_argument("--output", "-o", help="Output path (default: overwrite input)")
    parser.add_argument("--exterior-rgb", default="135,206,235",
                        help="Exterior color R,G,B (default: 135,206,235)")
    parser.add_argument("--corridor-rgb", default="193,247,179",
                        help="Corridor color R,G,B (default: 193,247,179)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    ext_rgb = tuple(int(c) for c in args.exterior_rgb.split(","))
    cor_rgb = tuple(int(c) for c in args.corridor_rgb.split(","))

    img = Image.open(args.input).convert("RGB")
    arr = np.array(img)

    seeds = []
    bboxes = []
    if args.json:
        with open(args.json, encoding="utf-8") as f:
            data = json.load(f)
        rooms = data.get("rooms", {})
        bboxes = []
        if isinstance(rooms, dict):
            for r in rooms.values():
                if "seed_x" in r and "seed_y" in r:
                    seeds.append((int(r["seed_x"]), int(r["seed_y"])))
                if "bbox_px" in r:
                    bb = r["bbox_px"]
                    bboxes.append((bb[0], bb[1], bb[2], bb[3]))

    colorize(arr, room_seeds=seeds, room_bboxes=bboxes,
             exterior_rgb=ext_rgb, corridor_rgb=cor_rgb)

    out_path = args.output or args.input
    Image.fromarray(arr).save(out_path)
    logger.info("Saved to %s", out_path)


if __name__ == "__main__":
    main()
