"""
Test of the adaptive comb on test_floorplan2.png.

Full pipeline:
  1. OCR (pytesseract --psm 11, upscale x2) → find all "14" codes
  2. Syntactic parsing of label boxes → seed = geometric center, name = room number
  3. Binarize at threshold 80
  4. Erase label boxes → white
  5. Adaptive comb (dynamic stop condition) → grid of hit points
  6. Largest rectangle containing the seed
  7. Debug visualization

Usage:
  python /tmp/test_comb.py              # all rooms
  python /tmp/test_comb.py 916          # room 916 only
"""

import os
import sys
import tempfile
import logging
import numpy as np
import cv2
from PIL import Image, ImageDraw
from collections import deque

logger = logging.getLogger(__name__)

_TMP = tempfile.gettempdir()

# Import config to get parameterizable room code
try:
    from olm.core.app_config import get_room_code
except ImportError:
    def get_room_code():
        return "14"  # fallback default

# --- Parameters ---
PLAN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "project", "plans", "test_floorplan3.png"
)
BINARIZE_THRESHOLD = 110
COMB_STEP_PX = 5   # comb step in pixels
MAX_RAY_PX = 1500
CARTOUCHE_MARGIN_PX = 1


def load_image(path):
    return Image.open(path).convert("L")


def find_seeds_by_ocr(image):
    try:
        import pytesseract
    except ImportError:
        logger.warning("pytesseract not available")
        return {}, []

    room_code = get_room_code()
    logger.debug(f"OCR: searching for room code '{room_code}'")

    ocr_image = image.resize((image.width * 2, image.height * 2), Image.LANCZOS)
    data = pytesseract.image_to_data(ocr_image, config='--psm 11',
                                     output_type=pytesseract.Output.DICT)
    words = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if not text:
            continue
        x = data["left"][i] // 2
        y = data["top"][i] // 2
        w = data["width"][i] // 2
        h = data["height"][i] // 2
        words.append({
            "text": text,
            "cx": x + w // 2, "cy": y + h // 2,
            "x": x, "y": y, "w": w, "h": h,
        })

    words.sort(key=lambda w: (w["cy"], w["cx"]))
    logger.debug(f"OCR: detected {len(words)} text elements")

    seeds = {}
    cartouche_bboxes = []

    for word in words:
        if word["text"] != room_code:
            continue

        seed_cx = word["cx"]
        seed_cy = word["cy"]

        cart_words = [word]
        room_name = f"room_{seed_cx}_{seed_cy}"
        room_surface = 0.0

        for other in words:
            if other is word:
                continue
            if (other["cy"] > seed_cy and
                other["cy"] < seed_cy + 80 and
                abs(other["cx"] - seed_cx) < 30):
                cart_words.append(other)
                if other["text"].isdigit() and len(other["text"]) == 3:
                    room_name = other["text"]
                # Parse surface (decimal number like "14.28" or "9.8")
                try:
                    val = float(other["text"].replace(",", "."))
                    if 1.0 < val < 200.0 and "." in other["text"].replace(",", "."):
                        room_surface = val
                except ValueError:
                    pass

        all_x0 = min(w["x"] for w in cart_words)
        all_y0 = min(w["y"] for w in cart_words)
        all_x1 = max(w["x"] + w["w"] for w in cart_words)
        all_y1 = max(w["y"] + w["h"] for w in cart_words)
        cartouche_bboxes.append((
            all_x0 - CARTOUCHE_MARGIN_PX,
            all_y0 - CARTOUCHE_MARGIN_PX,
            all_x1 + CARTOUCHE_MARGIN_PX,
            all_y1 + CARTOUCHE_MARGIN_PX,
        ))

        seed_cx = (all_x0 + all_x1) // 2
        seed_cy = (all_y0 + all_y1) // 2
        seeds[room_name] = (seed_cx, seed_cy, room_surface)
        logger.debug(f"  seed '{room_name}' at ({seed_cx}, {seed_cy}), surface={room_surface:.2f} m²")

    if not seeds:
        logger.warning(f"No seeds found. Did you search for the correct room code '{room_code}'?")
    else:
        logger.info(f"OCR: found {len(seeds)} room(s): {', '.join(seeds.keys())}")

    return seeds, cartouche_bboxes


def erase_cartouches(gray_arr, cartouche_bboxes):
    cleaned = gray_arr.copy()
    for x0, y0, x1, y1 in cartouche_bboxes:
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(cleaned.shape[1], x1)
        y1 = min(cleaned.shape[0], y1)
        cleaned[y0:y1, x0:x1] = 255
    return cleaned


def binarize(gray_arr, threshold=BINARIZE_THRESHOLD):
    return gray_arr < threshold


def remove_non_ortho(binary):
    """Remove non-orthogonal elements (door arcs, dimension lines).

    Analyses each connected component via minAreaRect. If the dominant
    orientation is neither ~0° nor ~90° (tolerance 5°), the component is removed.
    """
    binary_u8 = binary.astype(np.uint8) * 255
    num, labels = cv2.connectedComponents(binary_u8)

    for label_id in range(1, num):
        component = np.argwhere(labels == label_id)
        if len(component) < 5:
            continue
        rect = cv2.minAreaRect(component[:, ::-1].astype(np.float32))
        angle = rect[2] % 90
        if 5 < angle < 85:
            binary[labels == label_id] = False

    return binary


def ray_single(binary, x, y, dx, dy, max_dist=MAX_RAY_PX):
    """Return the distance to the last white pixel before the wall.

    Returns:
        Distance to last white pixel (= wall distance - 1), or
        -1 if the start point is on a wall.
    """
    h, w = binary.shape
    if 0 <= x < w and 0 <= y < h and binary[y, x]:
        return -1
    px, py = x, y
    for d in range(1, max_dist + 1):
        px += dx
        py += dy
        if px < 0 or px >= w or py < 0 or py >= h:
            return d - 1
        if binary[py, px]:
            return d - 1
    return max_dist


COARSE_STEP_PX = 30  # phase 1: coarse scan to find room walls
RAY_MARGIN_PX = 10   # margin beyond coarse distance for fine rays


def comb_collect_hits(binary, cx, cy, step_px, other_seeds=None):
    """Adaptive two-pass comb.

    Phase 1 (coarse): rays at wide step (COARSE_STEP_PX) from the seed
    to detect the 4 immediate walls → distances by direction.

    Phase 2 (fine): rays at step_px, bounded in position (phase 1 bbox)
    AND in range (phase 1 distance + margin). No ray goes past the walls
    detected in phase 1.

    Returns (all_hits, dir_hits):
      all_hits = flat list [(px, py), ...]
      dir_hits = {'north': [...], 'south': [...], 'east': [...], 'west': [...]}
    """
    # === Phase 1: coarse distances by direction (mode, not max) ===
    coarse_dists = {'north': [], 'south': [], 'west': [], 'east': []}

    # Rays initiaux
    for name, dx, dy in [('north', 0, -1), ('south', 0, 1),
                          ('west', -1, 0), ('east', 1, 0)]:
        d = ray_single(binary, cx, cy, dx, dy)
        if d > 0:
            coarse_dists[name].append(d)

    max_ns = max((coarse_dists['north'] + coarse_dists['south']) or [0])
    max_ew = max((coarse_dists['west'] + coarse_dists['east']) or [0])

    # Coarse vertical comb → collect north/south distances
    step = 1
    while True:
        offset = step * COARSE_STEP_PX
        if offset > max_ew:
            break
        for rx in (cx - offset, cx + offset):
            d = ray_single(binary, rx, cy, 0, -1)
            if d > 0:
                coarse_dists['north'].append(d)
                max_ns = max(max_ns, d)
            d = ray_single(binary, rx, cy, 0, 1)
            if d > 0:
                coarse_dists['south'].append(d)
                max_ns = max(max_ns, d)
        step += 1

    # Coarse horizontal comb → collect west/east distances
    step = 1
    while True:
        offset = step * COARSE_STEP_PX
        if offset > max_ns:
            break
        for ry in (cy - offset, cy + offset):
            d = ray_single(binary, cx, ry, -1, 0)
            if d > 0:
                coarse_dists['west'].append(d)
                max_ew = max(max_ew, d)
            d = ray_single(binary, cx, ry, 1, 0)
            if d > 0:
                coarse_dists['east'].append(d)
                max_ew = max(max_ew, d)
        step += 1

    # Mode per direction = dominant wall distance (outliers = door traversals)
    def _mode_dist(dists):
        if not dists:
            return 0
        vals, counts = np.unique(dists, return_counts=True)
        return int(vals[np.argmax(counts)])

    coarse_mode = {d: _mode_dist(coarse_dists[d]) for d in coarse_dists}
    coarse_max = {d: max(coarse_dists[d]) if coarse_dists[d] else 0
                  for d in coarse_dists}
    coarse_ns = max(coarse_mode['north'], coarse_mode['south'])
    coarse_ew = max(coarse_mode['west'], coarse_mode['east'])

    # Bbox (start positions) = based on mode (dominant wall)
    bbox_x0 = cx - coarse_ew
    bbox_x1 = cx + coarse_ew
    bbox_y0 = cy - coarse_ns
    bbox_y1 = cy + coarse_ns
    # Ray range = based on max (to traverse doors)
    max_north = coarse_max['north'] + RAY_MARGIN_PX
    max_south = coarse_max['south'] + RAY_MARGIN_PX
    max_west = coarse_max['west'] + RAY_MARGIN_PX
    max_east = coarse_max['east'] + RAY_MARGIN_PX

    # === Phase 2: fine comb, bounded in position AND range ===
    dir_hits = {'north': [], 'south': [], 'east': [], 'west': []}

    # Vertical rays (N and S)
    rx = cx
    while rx >= bbox_x0:
        d = ray_single(binary, rx, cy, 0, -1, max_dist=max_north)
        if d > 0:
            dir_hits['north'].append((rx, cy - d))
        d = ray_single(binary, rx, cy, 0, 1, max_dist=max_south)
        if d > 0:
            dir_hits['south'].append((rx, cy + d))
        rx -= step_px
    rx = cx + step_px
    while rx <= bbox_x1:
        d = ray_single(binary, rx, cy, 0, -1, max_dist=max_north)
        if d > 0:
            dir_hits['north'].append((rx, cy - d))
        d = ray_single(binary, rx, cy, 0, 1, max_dist=max_south)
        if d > 0:
            dir_hits['south'].append((rx, cy + d))
        rx += step_px

    # Horizontal rays (E and W)
    ry = cy
    while ry >= bbox_y0:
        d = ray_single(binary, cx, ry, -1, 0, max_dist=max_west)
        if d > 0:
            dir_hits['west'].append((cx - d, ry))
        d = ray_single(binary, cx, ry, 1, 0, max_dist=max_east)
        if d > 0:
            dir_hits['east'].append((cx + d, ry))
        ry -= step_px
    ry = cy + step_px
    while ry <= bbox_y1:
        d = ray_single(binary, cx, ry, -1, 0, max_dist=max_west)
        if d > 0:
            dir_hits['west'].append((cx - d, ry))
        d = ray_single(binary, cx, ry, 1, 0, max_dist=max_east)
        if d > 0:
            dir_hits['east'].append((cx + d, ry))
        ry += step_px

    # Filter hits that go beyond a neighboring seed.
    # A hit is invalid if it passes a neighbor's seed in the ray direction:
    #   - east hit at hx: invalid if there's a seed with ox < hx (hit went past it)
    #   - west hit at hx: invalid if there's a seed with ox > hx
    #   - south hit at hy: invalid if there's a seed with oy < hy
    #   - north hit at hy: invalid if there's a seed with oy > hy
    # Only consider seeds that are roughly aligned with the ray (within bbox).
    if other_seeds:
        def _not_past_seed(hx, hy, direction):
            for ox, oy in other_seeds:
                if direction == 'east' and ox > cx and hx > ox:
                    # Hit went east past a seed that's east of us
                    if abs(hy - oy) < abs(hy - cy) * 2:  # roughly aligned
                        return False
                elif direction == 'west' and ox < cx and hx < ox:
                    if abs(hy - oy) < abs(hy - cy) * 2:
                        return False
                elif direction == 'south' and oy > cy and hy > oy:
                    if abs(hx - ox) < abs(hx - cx) * 2:
                        return False
                elif direction == 'north' and oy < cy and hy < oy:
                    if abs(hx - ox) < abs(hx - cx) * 2:
                        return False
            return True

        for direction in dir_hits:
            dir_hits[direction] = [(hx, hy) for hx, hy in dir_hits[direction]
                                   if _not_past_seed(hx, hy, direction)]

    all_hits = [h for hits in dir_hits.values() for h in hits]
    return all_hits, dir_hits


def _innermost_with_support(coords, direction, min_support=3, tolerance=2):
    """Find the innermost coordinate with sufficient ray support.

    Scans from the room interior outward. Returns the first coordinate
    where at least min_support rays hit within ±tolerance pixels.

    Args:
        coords: list of wall coordinates (y for N/S, x for E/W)
        direction: 'max' for N/W faces (innermost = largest value),
                   'min' for S/E faces (innermost = smallest value)
        min_support: minimum number of rays for a valid wall
        tolerance: max distance in px for hits to be grouped

    Returns:
        Wall coordinate, or None if no supported value found.
    """
    if not coords:
        return None
    if direction == 'max':
        sorted_c = sorted(coords, reverse=True)
    else:
        sorted_c = sorted(coords)

    for c in sorted_c:
        support = sum(1 for other in coords if abs(other - c) <= tolerance)
        if support >= min_support:
            return c

    # Fallback: mode
    vals, counts = np.unique(coords, return_counts=True)
    return int(vals[np.argmax(counts)])


def rect_from_directional_hits(dir_hits, cx, cy):
    """Compute rectangle from directional hits.

    For each face, find the innermost wall position with sufficient
    support. This aligns the rectangle with window lines (innermost
    feature) and is robust to outlier hits.

    The innermost wall for each face is:
      north: largest hy (closest to seed from above)
      south: smallest hy (closest to seed from below)
      west:  largest hx (closest to seed from left)
      east:  smallest hx (closest to seed from right)
    """
    north_ys = [hy for _, hy in dir_hits['north']]
    south_ys = [hy for _, hy in dir_hits['south']]
    west_xs = [hx for hx, _ in dir_hits['west']]
    east_xs = [hx for hx, _ in dir_hits['east']]

    y0 = _innermost_with_support(north_ys, 'max')
    y1 = _innermost_with_support(south_ys, 'min')
    x0 = _innermost_with_support(west_xs, 'max')
    x1 = _innermost_with_support(east_xs, 'min')

    # Fallbacks
    if y0 is None: y0 = cy - 1
    if y1 is None: y1 = cy + 1
    if x0 is None: x0 = cx - 1
    if x1 is None: x1 = cx + 1

    return (x0, y0, x1, y1)


def largest_rect_no_hits(hits, cx, cy, return_all=False):
    """Largest rectangle containing (cx,cy) with no hits strictly inside.

    Hits may lie on the rectangle edges.
    Approach: for each pair of y bounds (top, bottom) defined by
    the hits, find the widest x bounds such that no hit is strictly
    inside.

    Args:
        return_all: if True, return (best_rect, all_candidates) where
            all_candidates is a list of (rect, area) sorted by area desc.
    """
    if not hits:
        r = (cx - 1, cy - 1, cx + 1, cy + 1)
        return (r, [(r, 4)]) if return_all else r

    # Collect all unique y coordinates of hits
    ys = sorted(set(h[1] for h in hits))

    best_area = 0
    best_rect = None
    all_candidates = [] if return_all else None

    # For each pair (y_top, y_bottom) containing cy
    for i, y_top in enumerate(ys):
        if y_top > cy:
            break
        for j in range(len(ys) - 1, -1, -1):
            y_bot = ys[j]
            if y_bot < cy:
                break
            h = y_bot - y_top
            if h <= 0:
                continue

            # Find x bounds: hits within the band
            # y_top <= hit_y <= y_bot constrain x
            x_left = -999999
            x_right = 999999

            for hx, hy in hits:
                if y_top <= hy <= y_bot:
                    # This hit is in the band (edges included)
                    if hx <= cx:
                        x_left = max(x_left, hx)
                    if hx >= cx:
                        x_right = min(x_right, hx)

            if x_left == -999999 or x_right == 999999:
                continue
            w = x_right - x_left
            if w <= 0:
                continue

            area = w * h
            rect = (x_left, y_top, x_right, y_bot)
            if return_all:
                all_candidates.append((rect, area))
            if area > best_area:
                best_area = area
                best_rect = rect

    if return_all:
        all_candidates.sort(key=lambda c: c[1], reverse=True)
        return best_rect, all_candidates
    return best_rect


SNAP_SEARCH_PX = 6  # search ±6px around current edge for wall snap


def snap_rect_to_walls(binary, rect, search_px=SNAP_SEARCH_PX):
    """Snap rectangle edges to the modal wall position on each face.

    After largest_rect_no_hits, edges may be off by ±2-3px because the
    comb rays (spaced at COMB_STEP_PX) hit different wall features
    (window panes, wall segments) depending on seed position.

    Fix: for each face, densely scan along the edge and find the first
    wall pixel searching from the room interior outward. The mode across
    all samples = true inner wall position. This ensures we stop at the
    innermost wall feature (window line) rather than overshooting to the
    outer wall.
    """
    x0, y0, x1, y1 = rect
    margin = 3  # skip corners where perpendicular walls interfere

    # North face: search from interior (increasing y) toward exterior (decreasing y)
    y0 = _snap_edge(binary, list(range(x0 + margin, x1 - margin)),
                    y0, axis='y', direction=-1, search_px=search_px)
    # South face: search from interior (decreasing y) toward exterior (increasing y)
    y1 = _snap_edge(binary, list(range(x0 + margin, x1 - margin)),
                    y1, axis='y', direction=+1, search_px=search_px)
    # West face: search from interior (increasing x) toward exterior (decreasing x)
    x0 = _snap_edge(binary, list(range(y0 + margin, y1 - margin)),
                    x0, axis='x', direction=-1, search_px=search_px)
    # East face: search from interior (decreasing x) toward exterior (increasing x)
    x1 = _snap_edge(binary, list(range(y0 + margin, y1 - margin)),
                    x1, axis='x', direction=+1, search_px=search_px)

    return (x0, y0, x1, y1)


def _snap_edge(binary, scan_positions, edge_val, axis, direction,
               search_px):
    """Find modal wall position along one edge by searching from interior.

    For each position along the edge, search from the room interior
    outward and record the first wall pixel found. The mode of these
    positions = true inner wall surface.

    Args:
        binary: wall mask (True = wall)
        scan_positions: coordinates along the edge (x for N/S, y for E/W)
        edge_val: current edge coordinate (y for N/S, x for E/W)
        axis: 'y' for N/S faces, 'x' for E/W faces
        direction: +1 or -1 — outward direction from the room interior
        search_px: search range in pixels

    Returns:
        Snapped edge coordinate (mode of first wall hits from interior).
    """
    h, w = binary.shape
    wall_hits = []

    # Search from interior toward exterior:
    # Start at edge_val - direction*search_px (deep inside room)
    # End at edge_val + direction*search_px (past the wall)
    for pos in scan_positions:
        for step in range(-search_px, search_px + 1):
            coord = edge_val + direction * step
            if axis == 'y':
                px, py = pos, coord
            else:
                px, py = coord, pos
            if 0 <= px < w and 0 <= py < h and binary[py, px]:
                wall_hits.append(coord)
                break

    if not wall_hits:
        return edge_val

    vals, counts = np.unique(wall_hits, return_counts=True)
    return int(vals[np.argmax(counts)])


def contract_to_interior(binary, rect, max_contract=10):
    """Contract each edge inward until no black pixel on the edge line.

    The rectangle from largest_rect_no_hits has edges ON the walls
    (first hit pixel = wall surface). Walls are 2-5px thick. This
    function moves each edge inward past the wall thickness until
    the edge line is fully white.

    To avoid false stops from perpendicular walls at the corners,
    only the middle 60% of each line/column is checked.
    """
    x0, y0, x1, y1 = rect
    h, w = binary.shape
    x_margin = max(3, (x1 - x0) // 5)
    y_margin = max(3, (y1 - y0) // 5)

    # North: contract y0 southward
    for _ in range(max_contract):
        if y0 >= y1:
            break
        if np.any(binary[y0, x0 + x_margin:x1 - x_margin]):
            y0 += 1
        else:
            break

    # South: contract y1 northward
    for _ in range(max_contract):
        if y1 <= y0:
            break
        if np.any(binary[y1, x0 + x_margin:x1 - x_margin]):
            y1 -= 1
        else:
            break

    # West: contract x0 eastward
    for _ in range(max_contract):
        if x0 >= x1:
            break
        if np.any(binary[y0 + y_margin:y1 - y_margin, x0]):
            x0 += 1
        else:
            break

    # East: contract x1 westward
    for _ in range(max_contract):
        if x1 <= x0:
            break
        if np.any(binary[y0 + y_margin:y1 - y_margin, x1]):
            x1 -= 1
        else:
            break

    return (x0, y0, x1, y1)


def snap_through_white(binary, rect, max_advance=8):
    """Expand each edge outward through fully white lines.

    For each side, check the 1px line just outside the current edge.
    If entirely white (no black pixel), advance the edge 1px outward.
    Repeat until hitting a line with at least one black pixel, or
    max_advance reached.

    Prerequisite: the rectangle must be inset from the walls (edges
    on white pixels, not on wall pixels). See largest_rect_no_hits.

    This aligns edges with the nearest wall/window feature, fixing
    ±2-3px offsets caused by comb discretization.
    """
    x0, y0, x1, y1 = rect
    h, w = binary.shape

    # North: advance y0 upward
    for _ in range(max_advance):
        if y0 <= 0:
            break
        if not np.any(binary[y0 - 1, x0:x1]):
            y0 -= 1
        else:
            break

    # South: advance y1 downward
    for _ in range(max_advance):
        if y1 >= h - 1:
            break
        if not np.any(binary[y1 + 1, x0:x1]):
            y1 += 1
        else:
            break

    # West: advance x0 leftward
    for _ in range(max_advance):
        if x0 <= 0:
            break
        if not np.any(binary[y0:y1, x0 - 1]):
            x0 -= 1
        else:
            break

    # East: advance x1 rightward
    for _ in range(max_advance):
        if x1 >= w - 1:
            break
        if not np.any(binary[y0:y1, x1 + 1]):
            x1 += 1
        else:
            break

    return (x0, y0, x1, y1)


DOOR_PROBE_PX = 4   # ~2cm, offset for probing door position
DOOR_GROUP_GAP_PX = 25  # max gap between pixels of the same arc (~door width)
WALL_MARGIN_PX = 3   # exclude pixels close to perpendicular walls


def _group_pixels(pixels, max_gap=DOOR_GROUP_GAP_PX):
    """Group contiguous pixels (with max gap)."""
    if not pixels:
        return []
    pixels = sorted(pixels)
    groups = []
    current = [pixels[0]]
    for p in pixels[1:]:
        if p - current[-1] <= max_gap:
            current.append(p)
        else:
            groups.append(current)
            current = [p]
    groups.append(current)
    return groups


def _detect_doors_on_face(binary, rect, hits, face, door_width_px, tolerance):
    """Detect door swings on one face of the rectangle.

    Returns:
        (new_edge, door_infos) or (None, []).
    """
    from collections import Counter
    x0, y0, x1, y1 = rect
    min_dist = door_width_px * (1 - tolerance)
    max_dist = door_width_px * (1 + tolerance)
    m = WALL_MARGIN_PX
    face_len = (x1 - x0) if face in ("south", "north") else (y1 - y0)

    if face == "south":
        far = [h for h in hits if h[1] > y1 and min_dist <= h[1] - y1 <= max_dist]
        if not far: return None, []
        wall, n = Counter(h[1] for h in far).most_common(1)[0]
        # Contact on the wall itself (1px beyond the rectangle edge)
        wy = y1 + 1
        contact = sum(1 for x in range(x0, x1+1) if 0<=wy<binary.shape[0] and binary[wy,x])
        if n < 3 or contact > face_len * 0.20: return None, []
        probe = wall - DOOR_PROBE_PX
        pixels = [x for x in range(x0+m, x1-m+1) if 0<=probe<binary.shape[0] and binary[probe,x]]
    elif face == "north":
        far = [h for h in hits if h[1] < y0 and min_dist <= y0 - h[1] <= max_dist]
        if not far: return None, []
        wall, n = Counter(h[1] for h in far).most_common(1)[0]
        wy = y0 - 1
        contact = sum(1 for x in range(x0, x1+1) if 0<=wy<binary.shape[0] and binary[wy,x])
        if n < 3 or contact > face_len * 0.20: return None, []
        probe = wall + DOOR_PROBE_PX
        pixels = [x for x in range(x0+m, x1-m+1) if 0<=probe<binary.shape[0] and binary[probe,x]]
    elif face == "east":
        far = [h for h in hits if h[0] > x1 and min_dist <= h[0] - x1 <= max_dist]
        if not far: return None, []
        wall, n = Counter(h[0] for h in far).most_common(1)[0]
        wx = x1 + 1
        contact = sum(1 for y in range(y0, y1+1) if 0<=wx<binary.shape[1] and binary[y,wx])
        if n < 3 or contact > face_len * 0.20: return None, []
        probe = wall - DOOR_PROBE_PX
        pixels = [y for y in range(y0+m, y1-m+1) if 0<=probe<binary.shape[1] and binary[y,probe]]
    elif face == "west":
        far = [h for h in hits if h[0] < x0 and min_dist <= x0 - h[0] <= max_dist]
        if not far: return None, []
        wall, n = Counter(h[0] for h in far).most_common(1)[0]
        wx = x0 - 1
        contact = sum(1 for y in range(y0, y1+1) if 0<=wx<binary.shape[1] and binary[y,wx])
        if n < 3 or contact > face_len * 0.20: return None, []
        probe = wall + DOOR_PROBE_PX
        pixels = [y for y in range(y0+m, y1-m+1) if 0<=probe<binary.shape[1] and binary[y,probe]]
    else:
        return None, []

    groups = _group_pixels(pixels)
    origin = x0 if face in ("south", "north") else y0
    size = (x1 - x0) if face in ("south", "north") else (y1 - y0)
    doors = []
    for g in groups:
        offset = min(g) - origin
        width = max(g) - min(g) + 1
        hinge_side = "left" if (offset < size / 2) else "right"
        # Hinge/free jamb positions (absolute px on the wall)
        jamb_hinge = min(g)
        jamb_free = max(g)
        # Door opens inward: the arc is inside the room (between seed
        # and the wall), so the rectangle had to expand outward to
        # reach the real wall behind the arc.
        doors.append({
            "face": face,
            "offset_px": offset,
            "width_px": width,
            "hinge_side": hinge_side,
            "opens_inward": True,
            "jamb_hinge_px": jamb_hinge,
            "jamb_free_px": jamb_free,
            "wall_px": wall,
        })

    return wall, doors


def expand_door_arcs(binary, rect, hits, cx, cy,
                     door_width_px=23, tolerance=0.35):
    """Phase 3: detect door swings and expand the rectangle.

    Returns:
        (expanded_rect, doors) where doors = list of door_info dicts.
    """
    x0, y0, x1, y1 = rect
    doors = []

    for face in ("south", "north", "east", "west"):
        new_edge, face_doors = _detect_doors_on_face(
            binary, (x0, y0, x1, y1), hits, face,
            door_width_px, tolerance)
        if new_edge is not None:
            if face == "south": y1 = new_edge
            elif face == "north": y0 = new_edge
            elif face == "east": x1 = new_edge
            elif face == "west": x0 = new_edge
            doors.extend(face_doors)

    return (x0, y0, x1, y1), doors


def detect_room(binary, cx, cy, step_px, door_width_px=23, other_seeds=None):
    """Detect a room rectangle: comb → hits → largest rectangle → door arc expansion."""
    all_hits, dir_hits = comb_collect_hits(binary, cx, cy, step_px,
                                           other_seeds=other_seeds)

    rect = largest_rect_no_hits(all_hits, cx, cy)

    if rect is None:
        return (cx - 1, cy - 1, cx + 1, cy + 1), all_hits, []

    # Expand each edge outward through fully white lines
    rect = snap_through_white(binary, rect)

    # Phase 3: door arc expansion
    rect, doors = expand_door_arcs(binary, rect, all_hits, cx, cy,
                                   door_width_px=door_width_px)

    return rect, all_hits, doors


# Automatic exclusion zone extension removed.
# Exclusion zones are entered manually in the Review phase.


def extract_all_rooms(image_path, scale_cm_per_px=None, threshold=None):
    """Run the full extraction pipeline on a floor plan image.

    Args:
        image_path: path to the raster floor plan image
        scale_cm_per_px: cm per pixel (estimated if not provided)
        threshold: binarization threshold (default BINARIZE_THRESHOLD)

    Returns:
        dict with:
          'rooms': list of room dicts (name, bbox_px, width_cm, depth_cm,
                   windows, openings, doors, exterior_faces, corridor_face)
          'image_size': (width, height) in pixels
          'scale_cm_per_px': used scale
          'binary': binarized image as numpy array (for visualization)
    """
    from olm.ingestion.extract import _classify_wall_direct

    thr = threshold or BINARIZE_THRESHOLD
    logger.info(f"Ingestion: loading {image_path}")
    img_gray = load_image(image_path)
    logger.debug(f"  image size: {img_gray.width} × {img_gray.height} px")

    seeds, cart_bboxes = find_seeds_by_ocr(img_gray)

    if not seeds:
        logger.error(f"ERROR: No seeds found! Check the room_code setting and cartouche text in the floor plan.")
        return {
            'rooms': [],
            'image_size': (img_gray.size[0], img_gray.size[1]),
            'scale_cm_per_px': scale_cm_per_px or 0.5,
            'threshold': thr,
        }

    logger.info(f"Ingestion: processing {len(seeds)} room(s)")
    gray_arr = np.array(img_gray)
    cleaned = erase_cartouches(gray_arr, cart_bboxes)
    binary = cleaned < thr
    logger.debug(f"  binarization: {np.sum(binary)} wall pixels (threshold={thr})")

    all_seed_positions = [(v[0], v[1]) for v in seeds.values()]

    rooms = []
    for name, seed_data in sorted(seeds.items()):
        cx, cy = seed_data[0], seed_data[1]
        surface_m2 = seed_data[2] if len(seed_data) > 2 else 0.0
        other = [(ox, oy) for ox, oy in all_seed_positions
                 if (ox, oy) != (cx, cy)]
        bbox, hits, doors = detect_room(binary, cx, cy, COMB_STEP_PX,
                                        other_seeds=other)
        x0, y0, x1, y1 = bbox
        width_px = x1 - x0
        height_px = y1 - y0

        # Classify walls
        wall_segs = {}
        for face in ('north', 'south', 'east', 'west'):
            segs, _ = _classify_wall_direct(binary, binary, bbox, face, 5)
            wall_segs[face] = segs

        # Extract windows, openings, doors from wall segments
        windows = []
        openings = []
        for face, segs in wall_segs.items():
            face_len = width_px if face in ('north', 'south') else height_px
            for seg in segs:
                if seg.kind == 'window':
                    windows.append({
                        'face': face,
                        'offset_px': seg.start_px,
                        'width_px': seg.end_px - seg.start_px,
                    })
                elif seg.kind == 'opening':
                    openings.append({
                        'face': face,
                        'offset_px': seg.start_px,
                        'width_px': seg.end_px - seg.start_px,
                    })

        # Derive exterior faces (faces with windows)
        exterior_faces = list(set(w['face'] for w in windows))

        # Corridor face (face with a door)
        corridor_face = doors[0]['face'] if doors else ''

        # Scale
        s = scale_cm_per_px or 0.5
        room = {
            'name': name,
            'seed_px': (cx, cy),
            'bbox_px': (x0, y0, x1, y1),
            'width_px': width_px,
            'height_px': height_px,
            'surface_m2': surface_m2,
            'windows': windows,
            'openings': openings,
            'doors': doors,
            'exterior_faces': exterior_faces,
            'corridor_face': corridor_face,
            'hits': [(int(hx), int(hy)) for hx, hy in hits],
        }
        logger.debug(f"  room '{name}': bbox=({x0},{y0},{x1},{y1}) {width_px}×{height_px}px, "
                     f"win={len(windows)} open={len(openings)} door={len(doors)}")
        rooms.append(room)

    # Auto-detect scale from simple rooms (1 door, no opening, surface > 0)
    if scale_cm_per_px is None:
        scale_samples = []
        for r in rooms:
            if (r['surface_m2'] > 0
                    and len(r['doors']) == 1
                    and len(r['openings']) == 0
                    and r['width_px'] > 10 and r['height_px'] > 10):
                area_cm2 = r['surface_m2'] * 10000
                area_px2 = r['width_px'] * r['height_px']
                scale_samples.append((area_cm2 / area_px2) ** 0.5)
        if scale_samples:
            scale_samples.sort()
            s = scale_samples[len(scale_samples) // 2]  # median
        else:
            s = 0.5  # fallback
    else:
        s = scale_cm_per_px

    # Apply scale to all rooms
    for r in rooms:
        r['width_cm'] = round(r['width_px'] * s)
        r['depth_cm'] = round(r['height_px'] * s)

    logger.info(f"Ingestion: SUCCESS — {len(rooms)} room(s), scale={s:.3f} cm/px")
    for r in rooms:
        logger.debug(f"  {r['name']}: {r['width_cm']}×{r['depth_cm']}cm")

    return {
        'rooms': rooms,
        'image_size': (img_gray.size[0], img_gray.size[1]),
        'scale_cm_per_px': round(s, 3),
        'threshold': thr,
    }


def draw_debug_all(image, results, output_path):
    img = image.convert("RGB").copy()
    draw = ImageDraw.Draw(img)

    colors = [
        (255, 0, 0), (0, 0, 255), (0, 180, 0), (255, 128, 0),
        (180, 0, 180), (0, 180, 180), (128, 128, 0), (255, 0, 128),
    ]

    for i, (name, bbox, cx, cy, _hits, _doors) in enumerate(results):
        x0, y0, x1, y1 = bbox
        color = colors[i % len(colors)]
        draw.rectangle([x0, y0, x1, y1], outline=color, width=2)
        draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(0, 255, 0))
        draw.text((x0, y0 - 12), name, fill=color)

    img.save(output_path)
    print(f"Debug image saved: {output_path}")


def draw_debug_single(image, binary, name, bbox, hits, cx, cy, output_path):
    x0, y0, x1, y1 = bbox
    margin = 40

    img = image.convert("RGB").copy()
    draw = ImageDraw.Draw(img)

    # Hits in red
    for hx, hy in hits:
        draw.ellipse([hx - 2, hy - 2, hx + 2, hy + 2], fill=(255, 0, 0))

    # Rectangle in blue
    draw.rectangle([x0, y0, x1, y1], outline=(0, 0, 255), width=2)
    # Seed in green
    draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(0, 255, 0))

    crop_x0 = max(0, x0 - margin)
    crop_y0 = max(0, y0 - margin)
    crop_x1 = min(img.width, x1 + margin)
    crop_y1 = min(img.height, y1 + margin)
    img.crop((crop_x0, crop_y0, crop_x1, crop_y1)).save(output_path)
    print(f"Single room debug: {output_path}")


def main():
    target_room = sys.argv[1] if len(sys.argv) > 1 else None

    print(f"Loading plan: {PLAN_PATH}")
    img_gray = load_image(PLAN_PATH)
    print(f"Image: {img_gray.size}")

    print("Step 1+2: OCR → seeds + label boxes...")
    seeds, cartouche_bboxes = find_seeds_by_ocr(img_gray)

    if not seeds:
        print("No seeds found!")
        return

    print(f"Seeds found: {len(seeds)}")

    print("Step 4: erasing label boxes...")
    gray_arr = np.array(img_gray)
    cleaned_arr = erase_cartouches(gray_arr, cartouche_bboxes)
    Image.fromarray(cleaned_arr).save(os.path.join(_TMP, "cleaned_plan.png"))

    print("Step 3: binarizing at threshold 80...")
    binary = binarize(cleaned_arr)
    print(f"  Wall pixels: {np.sum(binary)}")

    print("Step 3b: removing non-orthogonal elements...")
    # remove_non_ortho disabled — door detection works on raw geometry
    # (hits + contact pattern), non-ortho elements don't interfere
    # binary = remove_non_ortho(binary)
    print(f"  Wall pixels after: {np.sum(binary)}")

    # Save for debug
    Image.fromarray((~binary * 255).astype(np.uint8)).save(os.path.join(_TMP, "ortho_plan.png"))

    step_px = COMB_STEP_PX

    all_seed_positions = [(v[0], v[1]) for v in seeds.values()]

    if target_room:
        if target_room not in seeds:
            print(f"Room {target_room} not found. "
                  f"Available: {sorted(seeds.keys())}")
            return
        cx, cy = seeds[target_room][0], seeds[target_room][1]
        other = [(ox, oy) for ox, oy in all_seed_positions if (ox, oy) != (cx, cy)]
        print(f"\n=== {target_room} (seed {cx},{cy}) ===")
        bbox, hits, doors = detect_room(binary, cx, cy, step_px, other_seeds=other)
        x0, y0, x1, y1 = bbox
        print(f"Rectangle: ({x0},{y0}) → ({x1},{y1})")
        print(f"Size: {x1 - x0} x {y1 - y0} px")
        print(f"Hits: {len(hits)}")
        for d in doors:
            print(f"Door: face={d['face']}, offset={d['offset_px']}px, "
                  f"width={d['width_px']}px, hinge={d['hinge_side']}")
        draw_debug_single(Image.fromarray(cleaned_arr), binary,
                          target_room, bbox, hits, cx, cy,
                          os.path.join(_TMP, f"comb_{target_room}.png"))
    else:
        results = []
        for name, seed_data in sorted(seeds.items()):
            cx, cy = seed_data[0], seed_data[1]
            other = [(ox, oy) for ox, oy in all_seed_positions if (ox, oy) != (cx, cy)]
            bbox, hits, doors = detect_room(binary, cx, cy, step_px, other_seeds=other)
            x0, y0, x1, y1 = bbox
            door_str = f" | {len(doors)} door(s)" if doors else ""
            print(f"  {name}: ({x0},{y0}) → ({x1},{y1}) = "
                  f"{x1 - x0}x{y1 - y0}px{door_str}")
            results.append((name, bbox, cx, cy, hits, doors))

        draw_debug_all(Image.fromarray(cleaned_arr), results,
                       os.path.join(_TMP, "comb_all.png"))


if __name__ == "__main__":
    main()
