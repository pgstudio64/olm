"""
Room extraction from a raster floor plan using OCR + ray-cast.

Pipeline:
  1. OCR: detect text positions ("14", labels, surfaces)
  2. Clean: erase text from image
  3. Binarize: adaptive threshold → black walls / white interior
  3b. Remove non-orthogonal elements (door arcs, annotations) — H-04
  4. Ray-cast: fan of rays from each "14" centroid → bbox, openings, obstacles
  5. Wall texture analysis: classify wall/window/opening/door
  6. Assemble rooms JSON

Dependencies: Pillow, numpy.
Optional: easyocr (for real OCR — falls back to ground truth positions).
"""

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BINARIZE_THRESHOLD = 180     # grayscale threshold (< = wall)
MORPH_DILATE_PX = 1          # morphological dilation for closing micro-gaps
RAY_FAN_STEP = 3             # sample every N pixels along the fan (3 = 3x faster)
WALL_DEPTH_PX = 8            # how far to probe into the wall for texture (~30cm)
MIN_OPENING_PX = 15          # minimum width of a detected opening in px
MIN_OBSTACLE_PX = 10         # minimum width of a detected obstacle
DOOR_ARC_R2_THRESHOLD = 0.7  # R² threshold for arc detection
MODE_TOLERANCE_PX = 5        # distance from mode to count as "wall"
SNAP_SEARCH_PX = 6           # search ±6px around current edge for wall snap
ORTHO_ANGLE_TOLERANCE = 5    # degrees tolerance for orthogonal filter


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class DetectedText:
    text: str
    bbox_px: tuple  # (x_min, y_min, x_max, y_max)
    center_px: tuple  # (cx, cy)
    confidence: float = 1.0


@dataclass
class WallSegment:
    """A classified segment along one wall of a room."""
    start_px: int       # position along the wall (from NW corner)
    end_px: int
    kind: str           # "wall", "window", "opening", "door"
    # Door-specific
    has_arc: bool = False
    hinge_side: str = ""       # "left" or "right"
    opens_inward: bool = True


@dataclass
class DetectedRoom:
    """Result of ray-cast extraction for one room."""
    seed_px: tuple          # (cx, cy) of the "14" text
    bbox_px: tuple          # (x0, y0, x1, y1)
    label: str = ""
    surface_m2: float = 0.0
    walls: dict = field(default_factory=dict)  # face → list[WallSegment]
    exclusions: list = field(default_factory=list)
    corridor_face: str = ""
    exterior_faces: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 1 — OCR (or ground truth fallback)
# ---------------------------------------------------------------------------

def detect_text_ocr(image: Image.Image) -> list[DetectedText]:
    """Detect text using easyocr. Falls back to empty list if unavailable."""
    try:
        import easyocr
        reader = easyocr.Reader(["en", "fr"], gpu=False, verbose=False)
        gray_np = np.array(image.convert("L"))
        results = reader.readtext(gray_np)
        texts = []
        for bbox, text, conf in results:
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x_min, x_max = int(min(xs)), int(max(xs))
            y_min, y_max = int(min(ys)), int(max(ys))
            cx = (x_min + x_max) // 2
            cy = (y_min + y_max) // 2
            texts.append(DetectedText(
                text=text.strip(),
                bbox_px=(x_min, y_min, x_max, y_max),
                center_px=(cx, cy),
                confidence=conf,
            ))
        return texts
    except ImportError:
        logger.warning("easyocr not installed — using ground truth fallback")
        return []


def detect_text_from_ground_truth(ground_truth: dict) -> list[DetectedText]:
    """Build text list from ground truth (for testing without OCR)."""
    texts = []
    for room in ground_truth["rooms"]:
        x0, y0, x1, y1 = room["bbox_px"]
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        # Code "14"
        texts.append(DetectedText(
            text=room["code"],
            bbox_px=(cx - 15, cy - 25, cx + 15, cy - 5),
            center_px=(cx, cy - 15),
        ))
        # Label
        texts.append(DetectedText(
            text=room["name"],
            bbox_px=(cx - 30, cy - 55, cx + 30, cy - 35),
            center_px=(cx, cy - 45),
        ))
        # Surface
        surf = f"{room['surface_m2']:.1f}"
        texts.append(DetectedText(
            text=surf,
            bbox_px=(cx - 15, cy + 5, cx + 15, cy + 20),
            center_px=(cx, cy + 12),
        ))
    return texts


def classify_texts(texts: list[DetectedText]) -> dict:
    """Classify detected texts into codes, labels, and surfaces."""
    from olm.core.app_config import get_room_code
    codes = []     # room code instances
    labels = []    # alphanumeric room labels
    surfaces = []  # decimal numbers (m²)

    for t in texts:
        stripped = t.text.strip()
        if stripped == get_room_code():
            codes.append(t)
        elif _is_decimal(stripped):
            surfaces.append(t)
        elif _is_room_label(stripped):
            labels.append(t)
    return {"codes": codes, "labels": labels, "surfaces": surfaces}


def _is_decimal(s: str) -> bool:
    try:
        v = float(s)
        return "." in s and v > 0
    except ValueError:
        return False


def _is_room_label(s: str) -> bool:
    return any(c.isalpha() for c in s) and any(c.isdigit() for c in s)


# ---------------------------------------------------------------------------
# Step 2 — Clean image (erase text)
# ---------------------------------------------------------------------------

def clean_text_from_image(image: Image.Image,
                          texts: list[DetectedText],
                          margin_px: int = 3) -> Image.Image:
    """Erase detected text regions by filling with surrounding median."""
    img = image.copy()
    draw = ImageDraw.Draw(img)
    pixels = np.array(img)

    for t in texts:
        x0, y0, x1, y1 = t.bbox_px
        x0 = max(0, min(t.bbox_px[0], t.bbox_px[2]) - margin_px)
        y0 = max(0, min(t.bbox_px[1], t.bbox_px[3]) - margin_px)
        x1 = min(img.width - 1, max(t.bbox_px[0], t.bbox_px[2]) + margin_px)
        y1 = min(img.height - 1, max(t.bbox_px[1], t.bbox_px[3]) + margin_px)
        if x1 <= x0 or y1 <= y0:
            continue

        # Compute median of surrounding pixels (border ring)
        ring_pixels = []
        for x in range(x0, x1 + 1):
            for dy in [0, y1 - y0]:
                if 0 <= y0 + dy < img.height:
                    ring_pixels.append(pixels[y0 + dy, x])
        for y in range(y0, y1 + 1):
            for dx in [0, x1 - x0]:
                if 0 <= x0 + dx < img.width:
                    ring_pixels.append(pixels[y, x0 + dx])

        fill_val = int(np.median(ring_pixels)) if ring_pixels else 255
        draw.rectangle([x0, y0, x1, y1], fill=fill_val)

    return img


# ---------------------------------------------------------------------------
# Step 3 — Binarize
# ---------------------------------------------------------------------------

def binarize(image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Binarize image into two variants.

    Returns:
        binary_dilated: walls dilated (for ray-cast — closes micro-gaps)
        binary_raw: no dilation (for texture analysis — preserves
                    multi-line window patterns)
    """
    gray = np.array(image.convert("L"))
    binary_raw = gray < BINARIZE_THRESHOLD

    # Dilated version for ray-cast
    binary_dilated = binary_raw.copy()
    if MORPH_DILATE_PX > 0:
        bin_img = Image.fromarray((binary_raw * 255).astype(np.uint8))
        for _ in range(MORPH_DILATE_PX):
            bin_img = bin_img.filter(ImageFilter.MaxFilter(3))
        binary_dilated = np.array(bin_img) > 127

    return binary_dilated, binary_raw


def remove_non_ortho(binary: np.ndarray,
                     tolerance_deg: float = ORTHO_ANGLE_TOLERANCE,
                     min_component_px: int = 5) -> np.ndarray:
    """Remove non-orthogonal elements from binary image (H-04).

    Analyses each connected component via minAreaRect. Components whose
    dominant orientation is not ~0° or ~90° (within tolerance) are erased.
    This removes door arcs, diagonal annotations, hatching, etc.

    Args:
        binary: wall mask (True = wall)
        tolerance_deg: angle tolerance in degrees
        min_component_px: ignore components smaller than this

    Returns:
        Cleaned binary mask (True = wall, non-ortho removed).
    """
    binary_u8 = binary.astype(np.uint8) * 255
    num, labels = cv2.connectedComponents(binary_u8)
    cleaned = binary.copy()

    for label_id in range(1, num):
        component = np.argwhere(labels == label_id)
        if len(component) < min_component_px:
            continue
        rect = cv2.minAreaRect(component[:, ::-1].astype(np.float32))
        angle = rect[2] % 90
        if tolerance_deg < angle < (90 - tolerance_deg):
            cleaned[labels == label_id] = False

    logger.info("remove_non_ortho: %d components, removed %d non-ortho",
                num - 1, int(np.sum(binary) - np.sum(cleaned)))
    return cleaned


# ---------------------------------------------------------------------------
# Step 4 — Ray-cast fan
# ---------------------------------------------------------------------------

def _ray_fan(binary: np.ndarray, cx: int, cy: int,
             direction: str, fan_width: int,
             step: int = RAY_FAN_STEP,
             max_dist: int = 1500) -> np.ndarray:
    """Cast a fan of parallel rays in a cardinal direction (vectorized).

    Extracts a 2D slice from the binary image and finds the first True
    pixel along the ray axis using numpy — no Python loops over pixels.

    Args:
        binary: wall mask (True = wall)
        cx, cy: seed point
        direction: "north", "south", "east", "west"
        fan_width: total width of the fan in pixels
        step: sample every N pixels (performance tuning)
        max_dist: maximum ray travel distance

    Returns:
        distances: array of shape (fan_width,) — distance to first wall
                   for each ray position (interpolated back to full width)
    """
    h, w = binary.shape
    half = fan_width // 2

    # Sample positions along the fan axis
    sample_positions = np.arange(0, fan_width, step)
    n_samples = len(sample_positions)

    if direction in ("north", "south"):
        # Rays go vertically; fan spans horizontally
        xs = np.clip(cx - half + sample_positions, 0, w - 1).astype(int)
        if direction == "north":
            y_start = cy - 1
            y_end = max(0, cy - max_dist)
            if y_start < 0:
                return np.full(fan_width, 0, dtype=np.int32)
            # Extract a slice: rows [y_end..y_start] at columns xs
            slab = binary[y_end:y_start + 1, :][:, xs]  # shape (depth, n_samples)
            slab = slab[::-1, :]  # flip so index 0 = closest to seed
        else:  # south
            y_start = cy + 1
            y_end = min(h - 1, cy + max_dist)
            if y_start >= h:
                return np.full(fan_width, 0, dtype=np.int32)
            slab = binary[y_start:y_end + 1, :][:, xs]
    else:
        # Rays go horizontally; fan spans vertically
        ys = np.clip(cy - half + sample_positions, 0, h - 1).astype(int)
        if direction == "west":
            x_start = cx - 1
            x_end = max(0, cx - max_dist)
            if x_start < 0:
                return np.full(fan_width, 0, dtype=np.int32)
            slab = binary[:, x_end:x_start + 1][ys, :]  # shape (n_samples, depth)
            slab = slab[:, ::-1].T  # shape (depth, n_samples)
        else:  # east
            x_start = cx + 1
            x_end = min(w - 1, cx + max_dist)
            if x_start >= w:
                return np.full(fan_width, 0, dtype=np.int32)
            slab = binary[:, x_start:x_end + 1][ys, :]
            slab = slab.T  # shape (depth, n_samples)

    # Find first True pixel along depth axis for each sample ray
    depth = slab.shape[0]
    # argmax on a bool array returns index of first True; if no True, returns 0
    first_hit = np.argmax(slab, axis=0)  # shape (n_samples,)
    # Distinguish "hit at index 0" from "no hit"
    has_hit = slab[0, :] | (first_hit > 0)
    sample_distances = np.where(has_hit, first_hit + 1, depth)

    # Interpolate back to full fan width
    if step == 1:
        distances = sample_distances
    else:
        full_positions = np.arange(fan_width)
        distances = np.interp(full_positions, sample_positions,
                              sample_distances).astype(np.int32)

    return distances


def _compute_mode(distances: np.ndarray) -> int:
    """Compute the wall distance using a robust estimator.

    Uses a two-step approach:
    1. Compute histogram mode (most frequent distance)
    2. If mode captures < 30% of rays, fall back to the 90th percentile
       (robust against obstacles blocking a significant portion of rays)
    """
    if len(distances) == 0:
        return 0
    vals, counts = np.unique(distances, return_counts=True)
    mode_val = int(vals[np.argmax(counts)])
    mode_count = int(np.max(counts))

    # Check if mode is dominant enough
    total = len(distances)
    if mode_count / total < 0.3:
        # Mode is not reliable — use 90th percentile as fallback
        # (most rays hit the wall; obstacles are a minority)
        return int(np.percentile(distances, 90))

    return mode_val


def _measure_wall_thickness(binary: np.ndarray, x: int, y: int,
                            dx: int, dy: int, max_depth: int = 30) -> int:
    """Measure how many contiguous black pixels in a given direction."""
    h, w = binary.shape
    thickness = 0
    px, py = x, y
    for _ in range(max_depth):
        if 0 <= px < w and 0 <= py < h and binary[py, px]:
            thickness += 1
            px += dx
            py += dy
        else:
            break
    return thickness


# ---------------------------------------------------------------------------
# Three-phase room detection
# ---------------------------------------------------------------------------
# Phase 1 — Coarse bbox: wide fan, large step (20 cm), find 4 walls
# Phase 2 — Refined bbox: fan = room width/height, medium step (5 cm)
# Phase 3 — Wall classification: fine step (1.5 cm) along each wall only
# ---------------------------------------------------------------------------

PHASE1_STEP_CM = 20   # coarse scan: 1 ray every 20 cm
PHASE2_STEP_CM = 5    # refined scan: 1 ray every 5 cm
PHASE3_STEP_CM = 10   # classification: 1 probe every 10 cm (= solver grid)


def detect_room_three_phase(binary: np.ndarray, binary_raw: np.ndarray,
                            cx: int, cy: int,
                            scale_cm_per_px: float,
                            text_bboxes: list = None,
                            ) -> tuple:
    """Three-phase room detection from a seed point.

    Phase 1: Coarse bbox detection (large step, wide fan)
    Phase 2: Refined bbox with wall thickness compensation (medium step)
    Phase 3: Wall classification — texture probes along each wall (fine step)

    Args:
        binary: dilated binary image (for ray-cast)
        binary_raw: raw binary (for texture probes)
        cx, cy: seed point (center of "14" text)
        scale_cm_per_px: cm per pixel
        text_bboxes: text regions to skip during texture probing

    Returns:
        (bbox, walls) where:
          bbox = (x0, y0, x1, y1) in pixels
          walls = dict of direction → list[WallSegment]
    """
    px_per_cm = 1.0 / scale_cm_per_px
    phase1_step = max(1, round(PHASE1_STEP_CM * px_per_cm))
    phase2_step = max(1, round(PHASE2_STEP_CM * px_per_cm))
    phase3_step = max(1, round(PHASE3_STEP_CM * px_per_cm))

    # === Phase 1: Coarse bbox ===
    coarse_fan = 800
    modes = {}
    for direction in ("north", "south", "east", "west"):
        distances = _ray_fan(binary, cx, cy, direction, coarse_fan,
                             step=phase1_step)
        modes[direction] = _compute_mode(distances)

    est_w = modes["west"] + modes["east"]
    est_h = modes["north"] + modes["south"]

    # === Phase 2: Refined bbox ===
    refined_modes = {}
    for direction in ("north", "south"):
        fan_w = max(20, est_w)
        distances = _ray_fan(binary, cx, cy, direction, fan_w,
                             step=phase2_step)
        refined_modes[direction] = _compute_mode(distances)

    for direction in ("east", "west"):
        fan_w = max(20, est_h)
        distances = _ray_fan(binary, cx, cy, direction, fan_w,
                             step=phase2_step)
        refined_modes[direction] = _compute_mode(distances)

    # Wall thickness compensation
    n_thick = _measure_wall_thickness(binary, cx,
                                      cy - refined_modes["north"], 0, -1)
    s_thick = _measure_wall_thickness(binary, cx,
                                      cy + refined_modes["south"], 0, 1)
    w_thick = _measure_wall_thickness(binary,
                                      cx - refined_modes["west"], cy, -1, 0)
    e_thick = _measure_wall_thickness(binary,
                                      cx + refined_modes["east"], cy, 1, 0)

    x0 = cx - refined_modes["west"] - (w_thick // 2)
    y0 = cy - refined_modes["north"] - (n_thick // 2)
    x1 = cx + refined_modes["east"] + (e_thick // 2)
    y1 = cy + refined_modes["south"] + (s_thick // 2)
    bbox = (x0, y0, x1, y1)

    # === Phase 3: Wall classification ===
    # Probe texture directly along each wall (no ray-cast needed —
    # wall positions are known from phase 2).
    room_w = x1 - x0
    room_h = y1 - y0

    walls = {}
    profiles = {}
    for direction in ("north", "south", "east", "west"):
        segments, mode = _classify_wall_direct(
            binary, binary_raw, bbox, direction, phase3_step,
            text_bboxes=text_bboxes)
        walls[direction] = segments
        profiles[direction] = (None, mode)

    return bbox, walls, profiles


# ---------------------------------------------------------------------------
# Step 5 — Wall texture analysis (window detection)
# ---------------------------------------------------------------------------

def _probe_wall_texture(binary: np.ndarray, wall_x: int, wall_y: int,
                        dx: int, dy: int, depth: int = WALL_DEPTH_PX
                        ) -> list[bool]:
    """Probe pixels through the wall cross-section to get the texture profile.

    Starts AT the first black pixel (wall_x, wall_y) and continues in
    the ray direction for `depth` steps. Returns a list of bool
    (True = wall/black pixel).

    A plain wall has 1 contiguous black band.
    A window has 2-3 thin black bands separated by white gaps.
    """
    h, w = binary.shape
    profile = []
    x, y = wall_x, wall_y

    # Include starting pixel
    if 0 <= x < w and 0 <= y < h:
        profile.append(bool(binary[y, x]))

    for _ in range(depth):
        x += dx
        y += dy
        if 0 <= x < w and 0 <= y < h:
            profile.append(bool(binary[y, x]))
        else:
            profile.append(False)
    return profile


def _count_transitions(profile: list[bool]) -> int:
    """Count black→white transitions in a texture profile."""
    count = 0
    for i in range(1, len(profile)):
        if profile[i - 1] and not profile[i]:
            count += 1
    return count


def classify_wall_segments(binary: np.ndarray, binary_raw: np.ndarray,
                           cx: int, cy: int,
                           direction: str, distances: np.ndarray,
                           mode: int,
                           text_bboxes: list = None) -> list[WallSegment]:
    """Classify segments along one wall into wall/window/opening/door.

    Uses:
      - distance profile (§6.4): openings (> mode), obstacles (< mode)
      - texture profile on binary_raw (§6.6): wall vs window
      - arc detection (§6.5): curved profile near openings

    Args:
        binary: dilated binary (used for distance-based classification)
        binary_raw: raw binary without dilation (preserves window lines)
        text_bboxes: list of (x0, y0, x1, y1) text regions to skip
    """
    n = len(distances)
    half = n // 2
    tolerance = MODE_TOLERANCE_PX
    if text_bboxes is None:
        text_bboxes = []

    # Classify each ray position
    ray_kinds = []  # "wall", "window", "opening", "short" (obstacle/arc)
    for i in range(n):
        d = distances[i]
        if d > mode + tolerance:
            ray_kinds.append("opening")
        elif d < mode - tolerance:
            ray_kinds.append("short")
        else:
            # Compute the wall hit point
            if direction == "north":
                wall_x = cx - half + i
                wall_y = cy - d
            elif direction == "south":
                wall_x = cx - half + i
                wall_y = cy + d
            elif direction == "west":
                wall_x = cx - d
                wall_y = cy - half + i
            else:  # east
                wall_x = cx + d
                wall_y = cy - half + i

            # Skip texture probe if wall hit is inside a text bbox
            # (text cleaning may have erased window lines there)
            in_text = False
            for tx0, ty0, tx1, ty1 in text_bboxes:
                if tx0 <= wall_x <= tx1 and ty0 <= wall_y <= ty1:
                    in_text = True
                    break

            if in_text:
                ray_kinds.append("skip")  # will inherit from neighbors
            else:
                if direction == "north":
                    texture = _probe_wall_texture(binary_raw, wall_x, wall_y, 0, -1)
                elif direction == "south":
                    texture = _probe_wall_texture(binary_raw, wall_x, wall_y, 0, 1)
                elif direction == "west":
                    texture = _probe_wall_texture(binary_raw, wall_x, wall_y, -1, 0)
                else:
                    texture = _probe_wall_texture(binary_raw, wall_x, wall_y, 1, 0)

                transitions = _count_transitions(texture)
                if transitions >= 2:
                    ray_kinds.append("window")
                else:
                    ray_kinds.append("wall")

    # Fill "skip" rays with the nearest non-skip neighbor's kind
    _fill_skips(ray_kinds)

    # Group contiguous same-kind rays into segments
    segments = []
    if not ray_kinds:
        return segments

    seg_start = 0
    seg_kind = ray_kinds[0]
    for i in range(1, n):
        if ray_kinds[i] != seg_kind:
            if i - seg_start >= 3:  # minimum segment width
                segments.append(WallSegment(
                    start_px=seg_start,
                    end_px=i,
                    kind=seg_kind,
                ))
            seg_start = i
            seg_kind = ray_kinds[i]
    # Last segment
    if n - seg_start >= 3:
        segments.append(WallSegment(
            start_px=seg_start,
            end_px=n,
            kind=seg_kind,
        ))

    # Refine: check for door arcs adjacent to openings
    for idx, seg in enumerate(segments):
        if seg.kind != "opening":
            continue
        # Check left neighbor for arc
        if idx > 0 and segments[idx - 1].kind == "short":
            arc_seg = segments[idx - 1]
            if _detect_arc_profile(distances, arc_seg.start_px,
                                   arc_seg.end_px, mode):
                seg.has_arc = True
                seg.hinge_side = "left"
                seg.kind = "door"
                arc_seg.kind = "door_arc"
        # Check right neighbor for arc
        if idx < len(segments) - 1 and segments[idx + 1].kind == "short":
            arc_seg = segments[idx + 1]
            if _detect_arc_profile(distances, arc_seg.start_px,
                                   arc_seg.end_px, mode):
                if not seg.has_arc:  # not already assigned from left
                    seg.has_arc = True
                    seg.hinge_side = "right"
                    seg.kind = "door"
                arc_seg.kind = "door_arc"

    # TODO: obstacle detection disabled — needs a second pass after
    # room contours are established (not during wall classification)
    # Convert remaining "short" segments to "wall" for now
    for seg in segments:
        if seg.kind == "short":
            seg.kind = "wall"

    # Filter out arc segments and very small segments
    result = [s for s in segments
              if s.kind in ("wall", "window", "opening", "door")
              and ((s.end_px - s.start_px) >= MIN_OPENING_PX
                   or s.kind == "wall")]

    # Merge adjacent segments of the same kind (fixes fragmentation
    # caused by text cleaning gaps in the middle of windows/walls)
    result = _merge_adjacent_segments(result)

    return result


def _classify_wall_direct(binary: np.ndarray, binary_raw: np.ndarray,
                          bbox: tuple, direction: str, step_px: int,
                          text_bboxes: list = None,
                          scale_cm_per_px: float = 0.5,
                          ) -> tuple:
    """Classify a wall by probing texture directly at known wall positions.

    No ray-cast needed — the wall position comes from the bbox (phase 2).
    Probes the texture perpendicular to the wall at each sample point.

    Returns:
        (segments, wall_distance) where segments is list[WallSegment]
        and wall_distance is a nominal mode value for compatibility.
    """
    from olm.core.detection_config import DEFAULT_DETECTION_CONFIG_CM
    _cfg_local = DEFAULT_DETECTION_CONFIG_CM.to_px(scale_cm_per_px)
    x0, y0, x1, y1 = bbox
    if text_bboxes is None:
        text_bboxes = []

    # Determine wall position and probe direction
    # Also determine sample positions along the wall
    if direction == "north":
        wall_y = y0
        probe_dx, probe_dy = 0, -1
        positions = list(range(x0, x1, step_px))
        def wall_point(pos): return (pos, wall_y)
    elif direction == "south":
        wall_y = y1
        probe_dx, probe_dy = 0, 1
        positions = list(range(x0, x1, step_px))
        def wall_point(pos): return (pos, wall_y)
    elif direction == "west":
        wall_x = x0
        probe_dx, probe_dy = -1, 0
        positions = list(range(y0, y1, step_px))
        def wall_point(pos): return (wall_x, pos)
    elif direction == "east":
        wall_x = x1
        probe_dx, probe_dy = 1, 0
        positions = list(range(y0, y1, step_px))
        def wall_point(pos): return (wall_x, pos)
    else:
        return [], 0

    # Check each wall position: is there a wall? what texture?
    ray_kinds = []
    for pos in positions:
        wx, wy = wall_point(pos)
        h, w = binary.shape

        # Check if there's a wall at this position (look for black pixels
        # in a small neighborhood around the wall coordinate).
        # Use binary_raw (not dilated) to preserve the gap between window
        # lines and the wall — dilation closes this gap and prevents
        # multi-line window detection.
        has_wall = False
        for delta in range(-3, 4):  # search ±3 px around wall position
            px = wx + probe_dx * delta
            py = wy + probe_dy * delta
            if 0 <= px < w and 0 <= py < h and binary_raw[py, px]:
                has_wall = True
                # Snap to actual wall position for texture probe
                wx, wy = px, py
                break

        if not has_wall:
            ray_kinds.append("opening")
            continue

        # Check if inside a text bbox → skip
        in_text = False
        for tx0, ty0, tx1, ty1 in text_bboxes:
            if tx0 <= wx <= tx1 and ty0 <= wy <= ty1:
                in_text = True
                break

        if in_text:
            ray_kinds.append("skip")
            continue

        # Probe texture at this wall point
        texture = _probe_wall_texture(binary_raw, wx, wy,
                                      probe_dx, probe_dy,
                                      depth=_cfg_local.wall_depth_px)
        transitions = _count_transitions(texture)
        if transitions >= 2:
            ray_kinds.append("window")
        else:
            ray_kinds.append("wall")

    # Fill skips with neighbor values
    _fill_skips(ray_kinds)

    # Convert to segments (positions are in step_px increments)
    segments = []
    if not ray_kinds:
        return segments, 0

    seg_start = 0
    seg_kind = ray_kinds[0]
    for i in range(1, len(ray_kinds)):
        if ray_kinds[i] != seg_kind:
            px_start = seg_start * step_px
            px_end = i * step_px
            if px_end - px_start >= step_px:
                segments.append(WallSegment(
                    start_px=px_start,
                    end_px=px_end,
                    kind=seg_kind,
                ))
            seg_start = i
            seg_kind = ray_kinds[i]
    # Last segment
    px_start = seg_start * step_px
    px_end = len(ray_kinds) * step_px
    if px_end - px_start >= step_px:
        segments.append(WallSegment(
            start_px=px_start,
            end_px=px_end,
            kind=seg_kind,
        ))

    # TODO: obstacle detection disabled
    for seg in segments:
        if seg.kind == "short":
            seg.kind = "wall"

    # Merge adjacent segments (absorb openings < max_absorb_cm).
    # Seuils (réutilise le cfg calculé en tête de fonction).
    _cfg_px = _cfg_local
    MIN_OPENING_WIDTH_PX = _cfg_px.min_opening_width_px
    MIN_OPENING_DEPTH_PX = _cfg_px.min_opening_depth_px
    MIN_WINDOW_WIDTH_PX = _cfg_px.min_window_width_px

    segments = _merge_adjacent_segments(segments,
                                        max_absorb_px=_cfg_px.max_absorb_px)
    filtered = []
    for seg in segments:
        if seg.kind == "window":
            if seg.end_px - seg.start_px < MIN_WINDOW_WIDTH_PX:
                seg.kind = "wall"
        elif seg.kind == "opening":
            width_px = seg.end_px - seg.start_px
            if width_px < MIN_OPENING_WIDTH_PX:
                seg.kind = "wall"
        filtered.append(seg)
    segments = filtered

    # Re-merge after reclassification
    segments = _merge_adjacent_segments(segments,
                                        max_absorb_px=_cfg_px.max_absorb_px)

    return segments, 0


def _fill_skips(ray_kinds: list[str]):
    """Replace 'skip' entries with the nearest non-skip neighbor's kind."""
    n = len(ray_kinds)
    for i in range(n):
        if ray_kinds[i] != "skip":
            continue
        # Look left
        left = ""
        for j in range(i - 1, -1, -1):
            if ray_kinds[j] != "skip":
                left = ray_kinds[j]
                break
        # Look right
        right = ""
        for j in range(i + 1, n):
            if ray_kinds[j] != "skip":
                right = ray_kinds[j]
                break
        # Prefer window (more likely to be interrupted by text)
        if left == "window" or right == "window":
            ray_kinds[i] = "window"
        elif left:
            ray_kinds[i] = left
        elif right:
            ray_kinds[i] = right
        else:
            ray_kinds[i] = "wall"


def _merge_adjacent_segments(segments: list[WallSegment],
                             max_absorb_px: int = 120) -> list[WallSegment]:
    """Merge segments of the same kind separated by small intermediate segments.

    Two-pass approach:
      Pass 1: Absorb small intermediate segments into their neighbors.
              e.g. [window(200), wall(15), window(200)] → [window(415)]
              A small segment (< max_absorb_px) between two segments of
              the same kind is absorbed by the surrounding kind.
      Pass 2: Merge directly adjacent segments of the same kind.
    """
    if len(segments) <= 1:
        return segments

    # Pass 1: absorb small intermediate segments
    # Look for pattern: A(kind1) - B(small, any kind) - C(kind1) → merge all as kind1
    absorbed = list(segments)
    changed = True
    while changed:
        changed = False
        new_list = []
        i = 0
        while i < len(absorbed):
            if (i + 2 < len(absorbed)
                    and absorbed[i].kind == absorbed[i + 2].kind
                    and absorbed[i].kind == "wall"
                    and absorbed[i + 1].kind == "opening"
                    and (absorbed[i + 1].end_px - absorbed[i + 1].start_px)
                    <= max_absorb_px):
                # Absorb middle segment
                new_list.append(WallSegment(
                    start_px=absorbed[i].start_px,
                    end_px=absorbed[i + 2].end_px,
                    kind=absorbed[i].kind,
                    has_arc=absorbed[i].has_arc or absorbed[i + 2].has_arc,
                    hinge_side=(absorbed[i].hinge_side
                                or absorbed[i + 2].hinge_side),
                    opens_inward=absorbed[i].opens_inward,
                ))
                i += 3
                changed = True
            else:
                new_list.append(absorbed[i])
                i += 1
        absorbed = new_list

    # Pass 2: merge directly adjacent same-kind segments
    merged = [absorbed[0]]
    for seg in absorbed[1:]:
        prev = merged[-1]
        if seg.kind == prev.kind:
            merged[-1] = WallSegment(
                start_px=prev.start_px,
                end_px=seg.end_px,
                kind=prev.kind,
                has_arc=prev.has_arc or seg.has_arc,
                hinge_side=prev.hinge_side or seg.hinge_side,
                opens_inward=prev.opens_inward,
            )
        else:
            merged.append(seg)

    return merged


def _detect_arc_profile(distances: np.ndarray, start: int, end: int,
                        mode: int) -> bool:
    """Check if a 'short' segment has a circular arc profile.

    Fits sqrt(R² - p²) and checks R² goodness of fit.
    """
    segment = distances[start:end]
    if len(segment) < 5:
        return False

    # Normalize: deviation from mode
    deviations = mode - segment  # positive = closer than mode
    deviations = np.clip(deviations, 0, None)

    # Expected arc: deviation = sqrt(R² - p²) for p from 0 to len
    n = len(deviations)
    R_est = max(deviations) if max(deviations) > 0 else n
    if R_est == 0:
        return False

    p = np.arange(n, dtype=float)
    # Scale p to [0, R_est]
    p_scaled = p * R_est / n

    expected = np.sqrt(np.clip(R_est**2 - p_scaled**2, 0, None))
    # Normalize both for comparison
    if np.std(expected) == 0 or np.std(deviations) == 0:
        return False

    corr = np.corrcoef(deviations, expected)[0, 1]
    r2 = corr ** 2 if not np.isnan(corr) else 0

    return r2 > DOOR_ARC_R2_THRESHOLD


# ---------------------------------------------------------------------------
# Step 6 — Derive exterior faces from wall classification
# ---------------------------------------------------------------------------

def _derive_exterior_faces(walls: dict) -> list[str]:
    """Derive exterior faces from wall classification.

    A face is exterior if it contains at least one window segment.
    Windows are detected by texture (multi-line pattern) during wall
    classification — no need to probe beyond the wall.
    """
    exterior = []
    for face, segments in walls.items():
        for seg in segments:
            if seg.kind == "window":
                exterior.append(face)
                break
    return exterior


# ---------------------------------------------------------------------------
# Full extraction pipeline
# ---------------------------------------------------------------------------

def extract_rooms(image: Image.Image,
                  ground_truth: dict | None = None,
                  scale_cm_per_px: float = 0.5) -> list[DetectedRoom]:
    """Run the full extraction pipeline on a floor plan image.

    Args:
        image: grayscale floor plan image
        ground_truth: if provided, used for text positions (skip OCR)
        scale_cm_per_px: conversion factor (default for SCALE=2)

    Returns:
        List of detected rooms.
    """
    # Step 1: OCR
    if ground_truth:
        texts = detect_text_from_ground_truth(ground_truth)
        logger.info("Using ground truth text positions (%d texts)", len(texts))
    else:
        texts = detect_text_ocr(image)
        logger.info("OCR detected %d texts", len(texts))

    classified = classify_texts(texts)
    logger.info("Codes: %d, Labels: %d, Surfaces: %d",
                len(classified["codes"]),
                len(classified["labels"]),
                len(classified["surfaces"]))

    # Step 2: Clean image
    cleaned = clean_text_from_image(image, texts)

    # Step 3: Binarize (two versions)
    binary, binary_raw = binarize(cleaned)
    logger.info("Binarized image: %s, wall pixels: %d (dilated), %d (raw)",
                binary.shape, np.sum(binary), np.sum(binary_raw))

    # Step 3b: Remove non-orthogonal elements (door arcs, annotations)
    binary = remove_non_ortho(binary)
    binary_raw = remove_non_ortho(binary_raw)

    # Build expanded text bboxes for skip zones (margin accounts for
    # cleaning area that may have erased window lines)
    text_margin = 10
    text_bboxes = [
        (min(t.bbox_px[0], t.bbox_px[2]) - text_margin,
         min(t.bbox_px[1], t.bbox_px[3]) - text_margin,
         max(t.bbox_px[0], t.bbox_px[2]) + text_margin,
         max(t.bbox_px[1], t.bbox_px[3]) + text_margin)
        for t in texts
    ]

    # Three-phase detection for each "14"
    rooms = []
    for code_text in classified["codes"]:
        cx, cy = code_text.center_px
        logger.info("Processing room at seed (%d, %d)", cx, cy)

        # All 3 phases in one call
        bbox, walls, profiles = detect_room_three_phase(
            binary, binary_raw, cx, cy, scale_cm_per_px,
            text_bboxes=text_bboxes)
        x0, y0, x1, y1 = bbox
        logger.info("  bbox: (%d, %d, %d, %d) → %d x %d px",
                     x0, y0, x1, y1, x1 - x0, y1 - y0)
        for direction, segs in walls.items():
            seg_summary = [(s.kind, s.end_px - s.start_px) for s in segs]
            logger.info("  %s wall: %s", direction, seg_summary)

        # Derive exterior faces from window detection
        exterior = _derive_exterior_faces(walls)
        logger.info("  exterior faces: %s", exterior)

        # Determine corridor face (face with a door opening)
        corridor_face = ""
        for face, segs in walls.items():
            for s in segs:
                if s.kind in ("door", "opening"):
                    corridor_face = face
                    break
            if corridor_face:
                break

        # TODO: exclusion detection disabled — second pass needed
        exclusions = []

        # Associate nearest label
        label = _find_nearest(classified["labels"], cx, cy)
        surface = _find_nearest(classified["surfaces"], cx, cy)

        room = DetectedRoom(
            seed_px=(cx, cy),
            bbox_px=bbox,
            label=label.text if label else "",
            surface_m2=float(surface.text) if surface else 0.0,
            walls=walls,
            exclusions=exclusions,
            corridor_face=corridor_face,
            exterior_faces=exterior,
        )
        rooms.append(room)

    return rooms


def _build_exclusions(walls: dict, bbox: tuple, cx: int, cy: int,
                      profiles: dict, scale: float) -> list[dict]:
    """Convert 'obstacle' wall segments into exclusion zone dicts.

    An obstacle segment on a wall means rays hit something closer than
    the wall. The exclusion zone is between the obstacle hit distance
    and the wall, at the position along the wall.
    """
    x0, y0, x1, y1 = bbox
    room_w = x1 - x0
    room_h = y1 - y0
    exclusions = []

    for face, segments in walls.items():
        distances, mode = profiles[face]
        n = len(distances)

        for seg in segments:
            if seg.kind != "obstacle":
                continue

            # Average distance of the obstacle rays
            seg_distances = distances[seg.start_px:seg.end_px]
            if len(seg_distances) == 0:
                continue
            obs_dist = int(np.mean(seg_distances))
            obs_depth = mode - obs_dist  # how far the obstacle protrudes

            if obs_depth < MIN_OBSTACLE_PX:
                continue

            half = n // 2
            if face in ("north", "south"):
                # Position along x axis
                ex_x0 = cx - half + seg.start_px - x0
                ex_w = seg.end_px - seg.start_px
                if face == "north":
                    ex_y0 = 0
                else:
                    ex_y0 = room_h - obs_depth
                ex_h = obs_depth
                exclusions.append({
                    "x_cm": round(ex_x0 * scale),
                    "y_cm": round(ex_y0 * scale),
                    "width_cm": round(ex_w * scale),
                    "depth_cm": round(ex_h * scale),
                })
            else:  # east, west
                ex_y0 = cy - half + seg.start_px - y0
                ex_h = seg.end_px - seg.start_px
                if face == "west":
                    ex_x0 = 0
                else:
                    ex_x0 = room_w - obs_depth
                ex_w = obs_depth
                exclusions.append({
                    "x_cm": round(ex_x0 * scale),
                    "y_cm": round(ex_y0 * scale),
                    "width_cm": round(ex_w * scale),
                    "depth_cm": round(ex_h * scale),
                })

    return exclusions


def _find_nearest(texts: list[DetectedText], cx: int, cy: int,
                  max_dist: float = 500) -> DetectedText | None:
    """Find the nearest text to a given point."""
    best = None
    best_dist = max_dist
    for t in texts:
        d = math.hypot(t.center_px[0] - cx, t.center_px[1] - cy)
        if d < best_dist:
            best = t
            best_dist = d
    return best


# ---------------------------------------------------------------------------
# Convert to OLO JSON format
# ---------------------------------------------------------------------------

def rooms_to_olo_json(rooms: list[DetectedRoom],
                      scale_cm_per_px: float) -> dict:
    """Convert detected rooms to the OLO JSON format (VISION_LLM_IO_SPEC §3)."""
    olo_rooms = []
    for room in rooms:
        x0, y0, x1, y1 = room.bbox_px
        width_cm = round((x1 - x0) * scale_cm_per_px)
        depth_cm = round((y1 - y0) * scale_cm_per_px)

        windows = []
        openings = []
        for face, segments in room.walls.items():
            for seg in segments:
                seg_offset_cm = round(seg.start_px * scale_cm_per_px)
                seg_width_cm = round((seg.end_px - seg.start_px)
                                     * scale_cm_per_px)
                if seg.kind == "window":
                    windows.append({
                        "face": face,
                        "offset_cm": seg_offset_cm,
                        "width_cm": seg_width_cm,
                    })
                elif seg.kind in ("door", "opening"):
                    openings.append({
                        "face": face,
                        "offset_cm": seg_offset_cm,
                        "width_cm": seg_width_cm,
                        "has_door": seg.has_arc,
                        "opens_inward": seg.opens_inward,
                        "hinge_side": seg.hinge_side if seg.has_arc else "",
                    })

        olo_room = {
            "name": room.label,
            "width_cm": width_cm,
            "depth_cm": depth_cm,
            "bbox_px": list(room.bbox_px),
            "windows": windows,
            "openings": openings,
            "exclusion_zones": room.exclusions,
            "exterior_faces": room.exterior_faces,
            "corridor_face": room.corridor_face,
        }
        olo_rooms.append(olo_room)

    return {"rooms": olo_rooms}


# ---------------------------------------------------------------------------
# Mode Préprocessé — extraction depuis JSON + PNG
# ---------------------------------------------------------------------------

# Regex pour parser la surface dans line2.text (ex: "14.28 m2", "14,28 m²")
_RE_SURFACE_M2 = re.compile(r"(\d+[.,]?\d*)\s*m[²2]", re.IGNORECASE)
# Regex pour parser plan_scale (ex: "1:100", "1 : 50")
_RE_PLAN_SCALE = re.compile(r"1\s*:\s*(\d+)")
# Constante de conversion inch → cm
_INCH_TO_CM = 2.54


def _parse_surface_m2(text: str) -> float:
    """Extrait la surface en m² depuis un texte OCR (ex: '14.28 m2' → 14.28)."""
    if not text:
        return 0.0
    m = _RE_SURFACE_M2.search(text)
    if not m:
        return 0.0
    return float(m.group(1).replace(",", "."))


def _parse_plan_scale_ratio(plan_scale: str) -> float:
    """Parse 'plan_scale' (ex: '1:100') → ratio N (100.0). Retourne 0 si invalide."""
    if not plan_scale:
        return 0.0
    m = _RE_PLAN_SCALE.search(str(plan_scale))
    return float(m.group(1)) if m else 0.0


def _cm_per_px_from_metadata(dpi: int, plan_scale_ratio: float) -> float:
    """Calcule le facteur cm réel / pixel depuis dpi + ratio plan_scale.

    Formule : cm_per_px = (2.54 / dpi) * plan_scale_ratio
      - 2.54 / dpi : cm de plan imprimé par pixel
      - * plan_scale_ratio : conversion cm plan → cm réel (ex: 1:100 → ×100)
    """
    if dpi <= 0 or plan_scale_ratio <= 0:
        return 0.0
    return (_INCH_TO_CM / float(dpi)) * plan_scale_ratio


def _room_center_from_lines(line1: dict, line2: dict, line3: dict) -> tuple[float, float]:
    """Calcule le centre (pixels) d'un cartouche depuis ses 3 lignes.

    - x : moyenne des pixels_x des 3 lignes (les lignes sont empilées verticalement)
    - y : pixels_y de surface_line2 (ligne du milieu par définition)
    """
    xs = [float(ln["pixels_x"]) for ln in (line1, line2, line3) if ln and "pixels_x" in ln]
    cx = sum(xs) / len(xs) if xs else 0.0
    cy = float(line2["pixels_y"]) if line2 and "pixels_y" in line2 else 0.0
    return cx, cy


def _detect_face_colors(
    img_array: np.ndarray,
    bbox_px: tuple,
    corridor_rgb: tuple[int, int, int],
    exterior_rgb: tuple[int, int, int],
    margin_px: int = 8,
    tolerance: int = 40,
) -> dict:
    """Sample pixels just outside each face of a room bbox to detect color zones.

    Returns dict with keys: corridor_face, exterior_faces.
    """
    h, w = img_array.shape[:2]
    x0, y0, x1, y1 = bbox_px

    def _dominant_color(samples: np.ndarray, target_rgb: tuple, tol: int) -> bool:
        if len(samples) == 0:
            return False
        diffs = np.abs(samples.astype(int) - np.array(target_rgb, dtype=int))
        matches = np.all(diffs <= tol, axis=1)
        return np.sum(matches) > len(samples) * 0.3

    faces = {}
    # Sample strip just outside each face
    strip = margin_px
    regions = {
        "north": img_array[max(0, y0 - strip):y0, x0:x1],
        "south": img_array[y1:min(h, y1 + strip), x0:x1],
        "west":  img_array[y0:y1, max(0, x0 - strip):x0],
        "east":  img_array[y0:y1, x1:min(w, x1 + strip)],
    }

    corridor_face = ""
    exterior_faces = []
    for face, region in regions.items():
        if region.size == 0:
            continue
        pixels = region.reshape(-1, 3)
        if _dominant_color(pixels, corridor_rgb, tolerance):
            if not corridor_face:
                corridor_face = face
            faces[face] = "corridor"
        elif _dominant_color(pixels, exterior_rgb, tolerance):
            exterior_faces.append(face)
            faces[face] = "exterior"

    return {"corridor_face": corridor_face, "exterior_faces": exterior_faces}


def _face_borders_color(
    img_array: np.ndarray,
    bbox_px: tuple,
    face: str,
    target_rgb: tuple,
    margin_px: int = 8,
    tolerance: int = 40,
) -> bool:
    """True si la bande juste à l'extérieur de `face` du bbox est dominée
    par `target_rgb` (plus de 30% de pixels matching à ±tolerance)."""
    h, w = img_array.shape[:2]
    x0, y0, x1, y1 = bbox_px
    if face == "north":
        region = img_array[max(0, y0 - margin_px):y0, x0:x1]
    elif face == "south":
        region = img_array[y1:min(h, y1 + margin_px), x0:x1]
    elif face == "west":
        region = img_array[y0:y1, max(0, x0 - margin_px):x0]
    elif face == "east":
        region = img_array[y0:y1, x1:min(w, x1 + margin_px)]
    else:
        return False
    if region.size == 0:
        return False
    pixels = region.reshape(-1, 3)
    diffs = np.abs(pixels.astype(int) - np.array(target_rgb, dtype=int))
    matches = np.all(diffs <= tolerance, axis=1)
    return int(np.sum(matches)) > len(pixels) * 0.3


def extract_rooms_from_preprocessed(
    json_data: dict,
    enhanced_png_path: str,
    overlay_png_path: str,
) -> list:
    """Parse les pièces depuis un JSON preprocessé v3 + PNG enhanced/overlay.

    Format JSON v3 attendu — voir `docs/specs/PREPROCESSED_JSON_SPEC.md`
    (référence unique). Résumé minimal pour lecture :

        {
          "file": str,
          "building_id": str (optional),
          "floor_id": str (optional),
          "north_angle_deg": float (optional, default 0),
          "page_width_px": int,
          "page_height_px": int,
          "rooms": {                      # objet indexé par room_id
            "237": {
              "surface": "14.28 m2",       # obligatoire (string)
              "seed_x": 1234,              # obligatoire (scalar int)
              "seed_y": 575,               # obligatoire (scalar int)
              "bbox_px": [x0,y0,x1,y1],    # optionnel (Save-only)
              "canonical_top_face": "north",  # optionnel (Save-only)
              "doors": [...],              # optionnel
              "openings": [...],           # Save-only
              "windows": [...]             # Save-only
            },
            ...
          }
        }

    L'échelle `cm_per_px` est déduite de la médiane des surfaces m² détectées
    (pas besoin de `plan_scale`/`dpi` dans le JSON).

    Convention d'omission : tout champ non renseigné est ABSENT du JSON.
    Ne pas tester `if field` mais `if "field" in obj` avant accès.

    Args:
        json_data: dict au format v3 décrit ci-dessus.
        enhanced_png_path: chemin fichier PNG `<plan_id>-SD.png`
            (sans description / cartouches effacés, extérieur bleu, couloirs verts).
        overlay_png_path: chemin fichier PNG `<plan_id>.png` (plan officiel).

    Returns:
        list[dict] : liste de dicts pièces compatibles avec le pipeline UI,
            format identique à extract_all_rooms (test_comb).

    Raises:
        ValueError: si JSON mal formé ou fichiers PNG manquants.
    """
    import os as _os

    if "rooms" not in json_data:
        raise ValueError("JSON mal formé : clé 'rooms' manquante")
    rooms_raw = json_data["rooms"]
    _V2_LEGACY_KEYS = ("code_line1", "surface_line2", "id_line3")
    if isinstance(rooms_raw, list):
        # Any list-shaped rooms → legacy v2 format (v3 is always a dict)
        raise ValueError(
            "JSON v2 (legacy) format detected. Only v3 is supported — "
            "see docs/specs/PREPROCESSED_JSON_SPEC.md. "
            "Please regenerate the JSON."
        )
    if isinstance(rooms_raw, dict) and rooms_raw:
        _first_val = next(iter(rooms_raw.values()))
        if isinstance(_first_val, dict) and any(k in _first_val for k in _V2_LEGACY_KEYS):
            raise ValueError(
                "JSON v2 (legacy) format detected. Only v3 is supported — "
                "see docs/specs/PREPROCESSED_JSON_SPEC.md. "
                "Please regenerate the JSON."
            )
    if not isinstance(rooms_raw, dict):
        raise ValueError(
            "JSON v3 mal formé : 'rooms' doit être un objet indexé par room_id, "
            f"reçu {type(rooms_raw).__name__}"
        )
    if not _os.path.isfile(overlay_png_path):
        raise ValueError(f"Fichier PNG overlay introuvable : {overlay_png_path}")
    # enhanced_png_path est optionnel : certains plans n'ont pas de version enhanced
    if enhanced_png_path and not _os.path.isfile(enhanced_png_path):
        logger.warning(
            "JSON preprocessed : PNG enhanced absent (%s) — ray-cast désactivé",
            enhanced_png_path,
        )
        enhanced_png_path = ""

    # Première passe : parser chaque room et collecter les surfaces pour
    # déduire cm_per_px par médiane.
    parsed_rooms = []
    for room_id, r in rooms_raw.items():
        if not isinstance(r, dict):
            raise ValueError(f"Room '{room_id}' : doit être un objet, reçu {type(r).__name__}")

        if "seed_x" not in r or "seed_y" not in r:
            raise ValueError(
                f"Room '{room_id}' : champs 'seed_x' et 'seed_y' obligatoires"
            )
        if "surface" not in r:
            raise ValueError(f"Room '{room_id}' : champ 'surface' obligatoire")

        seed_x = int(r["seed_x"])
        seed_y = int(r["seed_y"])
        surface_m2 = _parse_surface_m2(str(r["surface"]))
        if surface_m2 <= 0:
            logger.warning(
                "Room %s : surface introuvable dans 'surface'=%r — défaut 0",
                room_id, r.get("surface"),
            )

        # bbox_px Save-only : présent si le plan a déjà été ray-casté
        bbox_px_opt = r.get("bbox_px")
        has_bbox = (
            isinstance(bbox_px_opt, (list, tuple))
            and len(bbox_px_opt) == 4
        )

        parsed_rooms.append({
            "room_id": str(room_id),
            "seed_x": seed_x,
            "seed_y": seed_y,
            "surface_m2": surface_m2,
            "bbox_px_opt": tuple(int(v) for v in bbox_px_opt) if has_bbox else None,
            "doors_raw": r.get("doors") or [],
            "openings_raw": r.get("openings") or [],
            "windows_raw": r.get("windows") or [],
            "canonical_top_face": r.get("canonical_top_face"),
        })

    # Déduction cm_per_px par médiane des pièces déjà bboxées (Save-only).
    # Les nouvelles pièces (Input pur) n'ont pas de bbox — on ne peut pas
    # calculer l'échelle avant le ray-cast. On tente sur ce qui est dispo.
    scale_samples = []
    for p in parsed_rooms:
        if p["bbox_px_opt"] and p["surface_m2"] > 0:
            x0, y0, x1, y1 = p["bbox_px_opt"]
            w_px = max(1, x1 - x0)
            h_px = max(1, y1 - y0)
            area_px = w_px * h_px
            area_cm2 = p["surface_m2"] * 10_000.0
            if area_px > 0:
                scale_samples.append(math.sqrt(area_cm2 / area_px))
    # Priority: explicit scale override (from drawing_scale UI) > median > fallback
    override_scale = json_data.get("_override_cm_per_px")
    if override_scale and float(override_scale) > 0:
        scale_cm_per_px = float(override_scale)
        logger.info(
            "JSON preprocessed v3 : cm_per_px=%.4f (drawing_scale override)",
            scale_cm_per_px,
        )
    elif scale_samples:
        scale_samples.sort()
        scale_cm_per_px = scale_samples[len(scale_samples) // 2]
        logger.info(
            "JSON preprocessed v3 : cm_per_px=%.4f déduit de %d échantillon(s)",
            scale_cm_per_px, len(scale_samples),
        )
    else:
        scale_cm_per_px = 0.5
        logger.warning(
            "JSON preprocessed v3 : aucun bbox_px Save-enriched pour calibrer "
            "l'échelle — fallback cm_per_px=0.5 (ray-cast requis pour affiner)"
        )

    result = []
    for p in parsed_rooms:
        seed_x, seed_y = p["seed_x"], p["seed_y"]
        surface_m2 = p["surface_m2"]
        area_cm2 = surface_m2 * 10_000.0

        # Si bbox_px fourni dans le JSON → skip ray-cast, utiliser tel quel.
        # Sinon → bbox dégénérée (seed seul), le ray-cast s'exécutera en aval.
        if p["bbox_px_opt"]:
            bbox_px = p["bbox_px_opt"]
            w_px = max(1, bbox_px[2] - bbox_px[0])
            h_px = max(1, bbox_px[3] - bbox_px[1])
            width_cm = int(round(w_px * scale_cm_per_px))
            depth_cm = int(round(h_px * scale_cm_per_px))
        else:
            # Dimensions estimées : pièce carrée depuis la surface
            side_cm = math.sqrt(max(area_cm2, 1.0))
            width_cm = int(round(side_cm))
            depth_cm = int(round(side_cm))
            if scale_cm_per_px > 0 and side_cm > 0:
                half_px = (side_cm / scale_cm_per_px) / 2.0
                bbox_px = (
                    int(seed_x - half_px),
                    int(seed_y - half_px),
                    int(seed_x + half_px),
                    int(seed_y + half_px),
                )
            else:
                bbox_px = (seed_x, seed_y, seed_x, seed_y)

        # Doors : transfère tels quels s'ils ont déjà les champs enrichis (face,
        # offset_px, width_px, etc.), sinon laisse la structure minimale Input.
        doors = []
        for d in p["doors_raw"]:
            if not isinstance(d, dict):
                continue
            dd = {}
            # Champs enrichis Save
            for k in ("face", "offset_px", "width_px", "hinge_side", "opens_inward"):
                if k in d:
                    dd[k] = d[k]
            # Champs Input (seed de porte) — convention uniforme avec le
            # seed de pièce (seed_x/seed_y, cf. PREPROCESSED_JSON_SPEC §2.3).
            if "seed_x" in d and "seed_y" in d:
                dd["seed_x"] = int(d["seed_x"])
                dd["seed_y"] = int(d["seed_y"])
            doors.append(dd)

        def _enrich_px_cm(e: dict) -> dict:
            """Enrichit {offset_px, width_px} avec {offset_cm, width_cm} si absents.

            Nécessaire pour que fromStorage frontend trouve toujours offset_cm
            cohérent (R-12). Le JSON v3 source ne porte que les _px ; la
            version cm permet une canonicalisation propre côté consommateur.
            """
            out = dict(e)
            if "offset_cm" not in out and "offset_px" in out:
                out["offset_cm"] = int(round(out["offset_px"] * scale_cm_per_px))
            if "width_cm" not in out and "width_px" in out:
                out["width_cm"] = int(round(out["width_px"] * scale_cm_per_px))
            return out

        openings = [_enrich_px_cm(o) for o in p["openings_raw"] if isinstance(o, dict)]
        windows = [_enrich_px_cm(w) for w in p["windows_raw"] if isinstance(w, dict)]
        doors = [_enrich_px_cm(d) for d in doors]

        # surface_m2      = valeur cartouche PDF (vérité terrain, figée).
        # surface_m2_bbox = calculée depuis le bbox courant (dérive si bbox
        # change). Les deux coexistent pour gérer les pièces non-rectangulaires
        # où cartouche ≠ bbox (D-115).
        surface_m2_bbox = round((width_cm * depth_cm) / 10_000.0, 2)

        room_dict = {
            "name": p["room_id"],
            "seed_px": (seed_x, seed_y),
            "bbox_px": bbox_px,
            "width_cm": width_cm,
            "depth_cm": depth_cm,
            "surface_m2": surface_m2,
            "surface_m2_bbox": surface_m2_bbox,
            "windows": windows,
            "openings": openings,
            "doors": doors,
            "exterior_faces": [],
            # corridor_face : dérivé uniquement d'une porte explicite
            # (source fiable). Les openings ne permettent pas d'inférer le
            # corridor de façon fiable (openings[0] peut être n'importe
            # quelle ouverture — ex: pièce 903 avec openings[north] alors
            # que le corridor est au sud). Sans porte, laisser vide ; la
            # détection couleur par _detect_face_colors prendra le relai.
            "corridor_face": (
                doors[0]["face"] if doors and "face" in doors[0] else ""
            ),
        }
        if p["canonical_top_face"]:
            room_dict["canonical_top_face"] = p["canonical_top_face"]
        result.append(room_dict)

    # Detect corridor/exterior faces from enhanced PNG colors
    if enhanced_png_path:
        try:
            _enh_img = np.array(Image.open(enhanced_png_path).convert("RGB"))
            _corridor_rgb = tuple(json_data.get("corridor_rgb", [193, 247, 179]))
            _exterior_rgb = tuple(json_data.get("exterior_rgb", [135, 206, 235]))
            _OPPOSITE = {"north": "south", "south": "north",
                         "east": "west", "west": "east"}
            for room_dict in result:
                bb = room_dict["bbox_px"]
                if bb and bb[2] > bb[0] and bb[3] > bb[1]:
                    colors = _detect_face_colors(
                        _enh_img, bb, _corridor_rgb, _exterior_rgb,
                    )
                    # canonical_top_face in JSON → override color detection
                    # (corridor_face = opposite).
                    manual_top = room_dict.get("canonical_top_face")
                    if manual_top:
                        room_dict["corridor_face"] = _OPPOSITE.get(
                            manual_top, room_dict.get("corridor_face", "")
                        )
                    elif colors["corridor_face"]:
                        room_dict["corridor_face"] = colors["corridor_face"]
                    if colors["exterior_faces"]:
                        room_dict["exterior_faces"] = colors["exterior_faces"]
        except Exception as e:
            logger.warning("Face color detection failed: %s", e)

    logger.info(
        "extract_rooms_from_preprocessed v3 : %d room(s) chargée(s) "
        "(cm_per_px=%.4f)",
        len(result), scale_cm_per_px,
    )
    return result


# ---------------------------------------------------------------------------
# Targeted single-room feature re-analysis (R-04 Review — re-analyze)
# ---------------------------------------------------------------------------

def extract_room_features(
    image: "Image.Image",
    seed_px: tuple,
    bbox_px: tuple | None,
    scale_cm_per_px: float,
    transparent_zones_cm: list | None = None,
    doors_px: list | None = None,
    door_width_cm: int = 90,
    threshold: int = 110,
    step_px: int = 5,
    binary_precomputed: np.ndarray | None = None,
    clip_to_bbox: bool = False,
) -> dict:
    """Ré-analyse complète d'UNE pièce (D-104 / D-105).

    Pipeline :
    1. Peint en blanc les zones transparentes utilisateur + des zones auto
       à chaque porte (largeur=profondeur=`door_width_cm`, centrées sur le
       milieu de la porte, débordant inside pour couvrir l'arc).
    2. Binarise.
    3. Ray-cast depuis `seed_px` via `detect_room_three_phase` → nouveau
       bbox + classification murs.
    4. Extrait windows (texture) / openings (détectées par la classif).
    5. Fallback couleur : fenêtre unique full-face pour toute face qui
       borde du bleu extérieur et n'a aucune fenêtre détectée.

    Args:
        image: image `-SD` (PIL, mode convertible en "L").
        seed_px: (x, y) seed de la pièce en coords image.
        bbox_px: (x0, y0, x1, y1) bbox initial — utilisé uniquement pour
            positionner les masques (portes et zones transparentes). Peut
            être None si transparent_zones_cm et doors_px sont vides.
        scale_cm_per_px: conversion cm↔px.
        transparent_zones_cm: liste {x_cm, y_cm, width_cm, depth_cm} en
            coord room-local (NW = 0,0 du bbox).
        doors_px: portes enrichies {face, offset_px, width_px} offsets
            relatifs à bbox_px.
        door_width_cm: largeur (et profondeur) de la zone transparente
            auto aux portes. Défaut = `default_door_width_cm` = 90.
        threshold: seuil binarisation.
        step_px: pas de classify_wall_direct.
        binary_precomputed: (OPT, D-123 perf) binaire global (bool ndarray
            H×W) déjà cleaned par `remove_non_ortho`. Si fourni, cet
            appel saute binarisation + remove_non_ortho (gain dominant
            en batch). Les masques room-locaux (doors + transparent_zones)
            sont appliqués par zéro-out sur une copie locale — pas de
            re-binarisation globale ni de re-clean. Voir
            `/api/room/reanalyze_batch`.
        clip_to_bbox: (D-132) Si True, les pixels hors de `bbox_px` sont
            forcés solides (True) dans le binary local avant ray-cast.
            Les rays s'arrêtent donc aux bords du bbox utilisateur au lieu
            de trouver les vrais murs au-delà. Use case : Lock bbox depuis
            le frontend après un resize manuel de pièce. Default False
            pour non-régression sur le pipeline d'ingestion initial.

    Returns:
        {
          "bbox_px": [x0, y0, x1, y1],
          "seed_px": [sx, sy],
          "windows": [...],
          "openings": [...],
          "hits": [[x,y], ...],
        }
    """
    from PIL import ImageDraw as _PILDraw

    if image.mode != "L":
        image = image.convert("L")
    seed_x, seed_y = int(seed_px[0]), int(seed_px[1])
    px_per_cm = 1.0 / scale_cm_per_px
    door_dw_px = max(1, int(round(door_width_cm * px_per_cm)))

    # --- 1. Collecte des rectangles de masque (portes + zones transparentes) ---
    # D-123 : rassemblés dans une liste unique, appliqués soit via PIL
    # (pipeline classique) soit via zéro-out numpy (pipeline batch partagé).
    mask_rects_px: list[tuple[int, int, int, int]] = []
    auto_door_rects_px: list[list[int]] = []

    if bbox_px and doors_px:
        bx0, by0, bx1, by1 = bbox_px
        for d in doors_px:
            face = d.get("face")
            off_px = d.get("offset_px", 0)
            wpx = d.get("width_px", door_dw_px)
            if face == "south":
                cx = bx0 + off_px + wpx / 2
                rect = (cx - door_dw_px / 2, by1 - door_dw_px,
                        cx + door_dw_px / 2, by1)
            elif face == "north":
                cx = bx0 + off_px + wpx / 2
                rect = (cx - door_dw_px / 2, by0,
                        cx + door_dw_px / 2, by0 + door_dw_px)
            elif face == "west":
                cy = by0 + off_px + wpx / 2
                rect = (bx0, cy - door_dw_px / 2,
                        bx0 + door_dw_px, cy + door_dw_px / 2)
            elif face == "east":
                cy = by0 + off_px + wpx / 2
                rect = (bx1 - door_dw_px, cy - door_dw_px / 2,
                        bx1, cy + door_dw_px / 2)
            else:
                continue
            mask_rects_px.append(rect)
            auto_door_rects_px.append([
                int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
            ])

    if bbox_px and transparent_zones_cm:
        bx0, by0 = bbox_px[0], bbox_px[1]
        for z in transparent_zones_cm:
            zx_abs = int(round(z.get("x_cm", 0) * px_per_cm)) + bx0
            zy_abs = int(round(z.get("y_cm", 0) * px_per_cm)) + by0
            zw = int(round(z.get("width_cm", 0) * px_per_cm))
            zh = int(round(z.get("depth_cm", 0) * px_per_cm))
            if zw > 0 and zh > 0:
                mask_rects_px.append(
                    (zx_abs, zy_abs, zx_abs + zw, zy_abs + zh))

    # --- 2. Binarisation ---
    if binary_precomputed is not None:
        # D-123 : base binaire déjà cleaned partagée → copie + zéro-out local.
        # Les masques sont forcés à False dans la copie room-scoped ; c'est
        # équivalent fonctionnellement à drawr.rectangle(fill=255) avant
        # binarisation + remove_non_ortho, sauf pour un cas-limite : un
        # composant non-orthogonal partiellement recouvert par un masque.
        # Dans le pipeline classique, le masque coupe le composant avant
        # remove_non_ortho et le reste peut devenir orthogonal ; ici, si
        # le composant était non-ortho dans la base, il a déjà été retiré
        # globalement. Diff négligeable sur des plans réels (masques petits).
        binary = binary_precomputed.copy()
        if mask_rects_px:
            H, W = binary.shape
            for (x0, y0, x1, y1) in mask_rects_px:
                ix0 = max(0, int(round(x0)))
                iy0 = max(0, int(round(y0)))
                ix1 = min(W, int(round(x1)))
                iy1 = min(H, int(round(y1)))
                if ix1 > ix0 and iy1 > iy0:
                    binary[iy0:iy1, ix0:ix1] = False
        binary_raw = binary
    else:
        # Pipeline classique : copie PIL + drawing + binarisation + cleanup.
        working = image.copy()
        draw = _PILDraw.Draw(working)
        for rect in mask_rects_px:
            draw.rectangle(rect, fill=255)
        gray = np.asarray(working)
        binary_raw = gray < threshold
        binary = remove_non_ortho(binary_raw)
        binary_raw = binary

    # --- D-132 : clip_to_bbox — force solides tous les pixels hors bbox_px
    # pour que les rays de detect_room s'arrêtent aux bords du bbox user au
    # lieu de trouver les vrais murs au-delà. Copie locale pour ne pas
    # polluer binary_precomputed (partagé en batch).
    if clip_to_bbox and bbox_px:
        H, W = binary.shape
        bx0 = max(0, int(bbox_px[0]))
        by0 = max(0, int(bbox_px[1]))
        bx1 = min(W, int(bbox_px[2]))
        by1 = min(H, int(bbox_px[3]))
        if bx1 > bx0 and by1 > by0:
            binary = binary.copy()
            if by0 > 0:         binary[:by0, :]       = True
            if by1 < H:         binary[by1:, :]       = True
            if bx0 > 0:         binary[by0:by1, :bx0] = True
            if bx1 < W:         binary[by0:by1, bx1:] = True
            binary_raw = binary

    # --- 3. Detection du bbox via l'algo comb (test_comb.detect_room,
    # même algo que l'import OCR — éprouvé et plus robuste que
    # detect_room_three_phase).
    from olm.ingestion.test_comb import detect_room as _comb_detect_room
    px_per_cm_f = 1.0 / scale_cm_per_px
    step_cm = 10
    comb_step_px = max(1, int(round(step_cm * px_per_cm_f)))
    door_px = max(1, int(round(door_width_cm * px_per_cm_f)))
    bbox_new, all_hits, _doors_detected = _comb_detect_room(
        binary, seed_x, seed_y, comb_step_px,
        door_width_px=door_px, other_seeds=None,
        scale_cm_per_px=scale_cm_per_px,
    )
    nx0, ny0, nx1, ny1 = bbox_new

    # --- Classification murs sur le bbox détecté ---
    walls: dict[str, list] = {}
    for face in ("north", "south", "east", "west"):
        segs, _ = _classify_wall_direct(
            binary, binary_raw, bbox_new, face, step_px,
            scale_cm_per_px=scale_cm_per_px,
        )
        walls[face] = segs

    # --- 4. Classification murs → windows / openings ---
    # seg.start_px / end_px sont DÉJÀ relatifs au début de la face
    # (index_in_positions × step_px). Pas de soustraction de face_origin.
    windows: list[dict] = []
    openings: list[dict] = []
    rgb_arr: np.ndarray | None = None
    for face in ("north", "south", "east", "west"):
        segs = walls.get(face, [])
        any_window = False
        for seg in segs:
            if seg.kind not in ("window", "opening"):
                continue
            off = seg.start_px
            w = seg.end_px - seg.start_px
            if w <= 0:
                continue
            entry = {
                "face": face,
                "offset_px": int(off),
                "width_px": int(w),
                "offset_cm": int(round(off * scale_cm_per_px)),
                "width_cm": int(round(w * scale_cm_per_px)),
            }
            if seg.kind == "window":
                windows.append(entry)
                any_window = True
            else:
                openings.append(entry)

        # --- 5. Fallback couleur bleue : fenêtre unique full-face ---
        if not any_window:
            if rgb_arr is None:
                try:
                    rgb_arr = np.array(image.convert("RGB"))
                except Exception:
                    rgb_arr = np.zeros((1, 1, 3), dtype=np.uint8)
            if _face_borders_color(rgb_arr, bbox_new, face, (135, 206, 235)):
                full_w = (nx1 - nx0) if face in ("north", "south") else (ny1 - ny0)
                windows.append({
                    "face": face,
                    "offset_px": 0,
                    "width_px": int(full_w),
                    "offset_cm": 0,
                    "width_cm": int(round(full_w * scale_cm_per_px)),
                })

    # Règle métier : une face ne peut pas avoir à la fois fenêtres et
    # openings. Si les deux coexistent, les openings sont des artefacts du
    # dessin de fenêtre (double trait + décalage au mur). On les supprime.
    faces_with_windows = {w["face"] for w in windows}
    openings = [o for o in openings if o["face"] not in faces_with_windows]

    # Hits issus du comb (réels, pas juste les 4 coins du bbox).
    hits = [[int(h[0]), int(h[1])] for h in (all_hits or [])]

    # Portes détectées par l'expansion d'arcs du comb. On les remonte
    # uniquement si l'appelant n'en a pas fourni — principe : à minima
    # faire ce que fait l'import OCR. Si l'appelant a déjà des portes
    # (JSON existant), on les préserve côté frontend.
    doors_out: list[dict] = []
    if not doors_px:
        for d in (_doors_detected or []):
            off = int(d.get("offset_px", 0))
            wpx = int(d.get("width_px", 0))
            doors_out.append({
                "face": d.get("face"),
                "offset_px": off,
                "width_px": wpx,
                "offset_cm": int(round(off * scale_cm_per_px)),
                "width_cm": int(round(wpx * scale_cm_per_px)),
                "hinge_side": d.get("hinge_side"),
                "opens_inward": bool(d.get("opens_inward", True)),
            })

    return {
        "bbox_px": [int(nx0), int(ny0), int(nx1), int(ny1)],
        "seed_px": [seed_x, seed_y],
        "windows": windows,
        "openings": openings,
        "doors": doors_out,
        "hits": hits,
        "auto_door_masks_px": auto_door_rects_px,
    }
