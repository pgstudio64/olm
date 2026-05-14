"""Wall texture classification for room boundary analysis.

Classifies wall segments along room boundaries as wall, window, opening
or door by probing the binary image texture perpendicular to the wall.

Extracted from extract.py to break the circular dependency between
extract.py and comb_detection.py (P1.1 / D-189).
"""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _probe_wall_texture(binary: np.ndarray, wall_x: int, wall_y: int,
                        dx: int, dy: int, depth: int,
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
    """Count black->white transitions in a texture profile."""
    count = 0
    for i in range(1, len(profile)):
        if profile[i - 1] and not profile[i]:
            count += 1
    return count


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
                             max_absorb_px: int = 60) -> list[WallSegment]:
    """Merge segments of the same kind separated by small intermediate segments.

    Args:
        max_absorb_px: max gap to absorb. Default 60 px (= max_absorb_cm
            30 at 0.5 cm/px). Callers should pass ``cfg.max_absorb_px``.

    Two-pass approach:
      Pass 1: Absorb small intermediate segments into their neighbors.
              e.g. [window(200), wall(15), window(200)] -> [window(415)]
              A small segment (< max_absorb_px) between two segments of
              the same kind is absorbed by the surrounding kind.
      Pass 2: Merge directly adjacent segments of the same kind.
    """
    if len(segments) <= 1:
        return segments

    # Pass 1: absorb small intermediate segments
    # Look for pattern: A(kind1) - B(small, any kind) - C(kind1) -> merge
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


# ---------------------------------------------------------------------------
# Main classification function
# ---------------------------------------------------------------------------

def _classify_wall_direct(binary: np.ndarray, binary_raw: np.ndarray,
                          bbox: tuple, direction: str, step_px: int,
                          text_bboxes: list = None,
                          scale_cm_per_px: float = 0.5,
                          ) -> tuple:
    """Classify a wall by probing texture directly at known wall positions.

    No ray-cast needed -- the wall position comes from the bbox (phase 2).
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
        # lines and the wall -- dilation closes this gap and prevents
        # multi-line window detection.
        has_wall = False
        _snap_r = _cfg_local.snap_search_px
        for delta in range(-_snap_r, _snap_r + 1):
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

        # Check if inside a text bbox -> skip
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
    # Last segment -- clamp end to actual face length so the last segment
    # does not overshoot the bbox when step_px does not divide evenly.
    face_len = (x1 - x0) if direction in ("north", "south") else (y1 - y0)
    px_start = seg_start * step_px
    px_end = min(len(ray_kinds) * step_px, face_len)
    if px_end - px_start >= step_px:
        segments.append(WallSegment(
            start_px=px_start,
            end_px=px_end,
            kind=seg_kind,
        ))

    # Merge adjacent segments (absorb openings < max_absorb_cm).
    # Seuils (reutilise le cfg calcule en tete de fonction).
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
