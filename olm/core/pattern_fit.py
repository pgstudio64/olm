"""Pattern fit — compute and apply minimum valid room dimensions.

Computes the minimum room (width_cm, depth_cm) that can accommodate
a pattern at its standard, then applies those dimensions.
The operation is bidirectional: it shrinks oversize rooms and
expands undersize rooms to the same minimum.

All rectangles (workstation footprints AND door exclusion zones)
are treated uniformly: Fit computes the tightest bounding box
that contains every rectangle, then moves walls to match.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from typing import Literal

from olm.core.catalogue_matcher import (
    _BLOCK_REGISTRY,
    BlockPosition,
    compute_block_positions,
)
from olm.core.matching_config import GRID_CELL_CM
from olm.core.pattern_generator import (
    FaceCandidates,
    FaceZone,
    rotate_face_candidates,
)
from olm.core.spacing_config import SpacingConfig, build_block_defs

logger = logging.getLogger(__name__)

# Minimum semantic door width (AFNOR NF P01-005).
MIN_DOOR_WIDTH_CM = 90

# Room dimensions snap step (cm, round up).
SNAP_CM = 10


# Re-exported from olm.core.exceptions to avoid circular imports while keeping
# the legacy import path ``from olm.core.pattern_fit import PatternStructurallyInvalid``.
from olm.core.exceptions import PatternStructurallyInvalid  # noqa: F401, E402


@dataclass
class FitResult:
    """Result of a fit operation."""

    old_width: int
    old_depth: int
    new_width: int
    new_depth: int
    direction: Literal["shrink", "expand", "noop"]
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fit_room_to_pattern(
    pattern: dict,
    spacing: SpacingConfig,
) -> FitResult:
    """Compute and apply the minimum valid room for a pattern.

    Mutates ``pattern`` in place: updates ``room_width_cm``,
    ``room_depth_cm``, and may clip or drop features
    (windows / openings / exclusions).

    Args:
        pattern: Catalogue pattern (JSON dict).
        spacing: Spacing config for the pattern's standard.

    Returns:
        FitResult with old/new dimensions and direction.

    Raises:
        PatternStructurallyInvalid: Blocks physically overlap.
    """
    old_w = pattern.get("room_width_cm", 0)
    old_d = pattern.get("room_depth_cm", 0)

    new_w, new_d, warnings = _compute_min_room(pattern, spacing)

    pattern["room_width_cm"] = new_w
    pattern["room_depth_cm"] = new_d

    # Re-validate features against the new room
    feat_warnings = _revalidate_features(pattern, new_w, new_d, old_w, old_d)
    warnings.extend(feat_warnings)

    direction = _determine_direction(old_w, old_d, new_w, new_d)

    return FitResult(
        old_width=old_w,
        old_depth=old_d,
        new_width=new_w,
        new_depth=new_d,
        direction=direction,
        warnings=warnings,
    )


# Module-level cache for circulation-aware min-room.
# Key: content fingerprint (hash of structural pattern data + standard).
# Value: (min_w, min_d, shrink_w, shrink_n).
_MIN_ROOM_CACHE: dict[str, tuple[int, int, int, int]] = {}


def compute_min_room_circ(
    pattern: dict,
    spacing: SpacingConfig,
) -> tuple[int, int]:
    """Compute minimum room dimensions with circulation margins.

    Pure function — does NOT mutate *pattern*.  Cached by content
    fingerprint + standard name.

    Starts from the declared room and shrinks margins while all
    desks remain reachable and min passage >= walking_margin_cm.
    Falls back to footprint-only dimensions when the pattern has
    no doors or when circulation fails at the declared room size.

    Args:
        pattern: Catalogue pattern (JSON dict).
        spacing: Spacing config for the pattern's standard.

    Returns:
        (min_width_cm, min_depth_cm) snapped to SNAP_CM.
    """
    key = _min_room_cache_key(pattern, spacing)
    cached = _MIN_ROOM_CACHE.get(key)
    if cached is not None:
        return cached[0], cached[1]
    result = _compute_min_room_circ_impl(pattern, spacing)
    _MIN_ROOM_CACHE[key] = result
    return result[0], result[1]


def clear_min_room_cache() -> None:
    """Clear the circulation-aware min-room cache."""
    _MIN_ROOM_CACHE.clear()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _determine_direction(
    old_w: int, old_d: int, new_w: int, new_d: int,
) -> Literal["shrink", "expand", "noop"]:
    """Classify the fit as shrink, expand, or noop."""
    if new_w == old_w and new_d == old_d:
        return "noop"
    if new_w * new_d >= old_w * old_d:
        return "expand"
    return "shrink"


def compute_pattern_footprint(
    pattern: dict,
    spacing: SpacingConfig,
) -> tuple[int, int, int, int]:
    """Compute the raw bounding box of all pattern obstacles.

    Pure function — does not mutate the pattern, does not snap, does
    not translate. Returns the bbox in the pattern's own coordinate
    system (may include negative values when face zones extend west/
    north beyond the block body).

    Single source of truth for the pattern footprint, used by:
    - ``fit_room_to_pattern`` (computes min room, then snaps + translates)
    - ``is_pattern_valid`` (checks footprint fits in room_width/depth)
    - frontend mirror function (PE info panel, overflow indicator)

    The bbox includes:
    - block bodies
    - face zones (chair clearance + circulation) on all 4 sides
    - door swing areas as 2D obstacles (perpendicular pushback for
      every block that overlaps the door laterally)

    Args:
        pattern: Catalogue pattern dict.
        spacing: Spacing config for the pattern's standard.

    Returns:
        (x_min, x_max, y_min, y_max) in cm.

    Raises:
        PatternStructurallyInvalid: blocks physically overlap.
    """
    block_defs = build_block_defs(spacing)
    positions = compute_block_positions(pattern)

    if not positions:
        rw = pattern.get("room_width_cm", 0)
        rd = pattern.get("room_depth_cm", 0)
        return 0, rw, 0, rd

    # Block footprints (body + face zones).
    # D-229: faces without chairs can touch the wall (eff = 0).
    x_mins: list[int] = []
    x_maxs: list[int] = []
    y_mins: list[int] = []
    y_maxs: list[int] = []
    for bp in positions:
        fc = get_face_zones(bp.block_type, bp.orientation, block_defs)
        x_mins.append(bp.x_cm - fc.west.outer_cm)
        x_maxs.append(bp.x_cm + bp.eo_cm + fc.east.outer_cm)
        y_mins.append(bp.y_cm - fc.north.outer_cm)
        y_maxs.append(bp.y_cm + bp.ns_cm + fc.south.outer_cm)

    # Door swing areas as 2D obstacles.
    _apply_door_obstacles(
        pattern, spacing, positions, block_defs,
        x_mins, x_maxs, y_mins, y_maxs,
    )

    return min(x_mins), max(x_maxs), min(y_mins), max(y_maxs)


def is_pattern_valid(
    pattern: dict,
    spacing: SpacingConfig,
) -> bool:
    """Return True if the pattern's footprint fits in its declared room.

    A pattern is invalid when its true footprint (body + face zones +
    door swing areas) exceeds ``room_width_cm`` × ``room_depth_cm`` —
    either because the bbox is wider/deeper than the room, or because
    the bbox extends into negative coordinates (block placed past the
    NW corner). Also invalid when blocks physically overlap.

    Used by the Office matcher (filters invalid patterns out of the
    candidate set) and by ``save_as_default`` (refuses to publish an
    invalid catalogue).
    """
    rw = pattern.get("room_width_cm", 0)
    rd = pattern.get("room_depth_cm", 0)
    if rw <= 0 or rd <= 0:
        return False
    try:
        x_min, x_max, y_min, y_max = compute_pattern_footprint(
            pattern, spacing,
        )
    except PatternStructurallyInvalid:
        return False
    return x_min >= 0 and y_min >= 0 and x_max <= rw and y_max <= rd


# ---------------------------------------------------------------------------
# Circulation-aware min room helpers (D-305)
# ---------------------------------------------------------------------------


def build_circ_blocks_from_pattern(
    pattern: dict,
    shift_x: int = 0,
    shift_y: int = 0,
    positions: list[BlockPosition] | None = None,
) -> list[dict]:
    """Build blocks in circulation-analysis format from a pattern.

    Converts ``BlockPosition`` dataclasses to the dict format
    expected by ``circulation_analysis.analyse``.  Optionally
    shifts all positions by ``(-shift_x, -shift_y)`` to model a
    shrunk room whose origin moved.

    Args:
        pattern: Catalogue pattern (JSON dict).
        shift_x: Subtract from each block's x_cm.
        shift_y: Subtract from each block's y_cm.
        positions: Pre-computed positions (avoids recomputation).

    Returns:
        List of block dicts for circulation analysis.
    """
    if positions is None:
        positions = compute_block_positions(pattern)
    return [
        {
            "type": bp.block_type,
            "orientation": bp.orientation,
            "x_cm": bp.x_cm - shift_x,
            "y_cm": bp.y_cm - shift_y,
            "eo_cm": bp.eo_cm,
            "ns_cm": bp.ns_cm,
        }
        for bp in positions
    ]


def _build_circ_format(
    pattern: dict,
    room_w: int,
    room_d: int,
    shift_x: int = 0,
    shift_y: int = 0,
    positions: list[BlockPosition] | None = None,
) -> tuple[dict, list[dict]]:
    """Build ``(room_dict, blocks)`` for circulation analysis.

    Doors are extracted from ``pattern["room_openings"]``: entries
    with ``has_door``, falling back to all openings, then to a
    synthetic 90 cm south door.

    Args:
        pattern: Catalogue pattern.
        room_w: Candidate room width (cm).
        room_d: Candidate room depth (cm).
        shift_x: West-side shrink (subtracted from block x and
            door offsets on north/south walls).
        shift_y: North-side shrink (subtracted from block y and
            door offsets on east/west walls).
        positions: Pre-computed BlockPositions (optional).

    Returns:
        ``(room_dict, blocks_list)`` for
        ``circulation_analysis.analyse``.
    """
    openings = pattern.get("room_openings", [])
    entries = [o for o in openings if o.get("has_door")] or list(openings)

    doors: list[dict] = []
    for o in entries:
        face = o.get("face", "")
        offset = o.get("offset_cm", 0)
        width = o.get("width_cm", 0)
        if face in ("north", "south"):
            offset -= shift_x
            wall_len = room_w
        elif face in ("east", "west"):
            offset -= shift_y
            wall_len = room_d
        else:
            wall_len = room_w
        offset = max(0, offset)
        if offset + width > wall_len:
            offset = max(0, wall_len - width)
        doors.append({
            "wall": face,
            "position_cm": offset,
            "width_cm": min(width, wall_len),
        })

    if not doors:
        doors.append({
            "wall": "south",
            "position_cm": 0,
            "width_cm": min(90, room_w),
        })

    room_dict = {
        "eo_cm": room_w, "ns_cm": room_d, "doors": doors,
    }
    blocks = build_circ_blocks_from_pattern(
        pattern, shift_x, shift_y, positions,
    )
    return room_dict, blocks


def _circulation_ok(
    pattern: dict,
    room_w: int,
    room_d: int,
    shift_x: int,
    shift_y: int,
    spacing: SpacingConfig,
    positions: list[BlockPosition] | None = None,
) -> bool:
    """Return True if circulation passes for a candidate room.

    Criteria (D-305): **all** desks reachable (non-empty BFS path)
    AND ``min(path_widths) >= spacing.walking_margin_cm``.
    """
    from olm.core.circulation_analysis import (
        analyse as _circ_analyse,
    )

    room_dict, blocks = _build_circ_format(
        pattern, room_w, room_d, shift_x, shift_y, positions,
    )
    circ = _circ_analyse(
        room_dict, blocks, spacing.door_exclusion_depth_cm,
    )
    if not circ.path_widths:
        return False
    if any(len(p) == 0 for p in circ.paths):
        return False
    return min(circ.path_widths) >= spacing.walking_margin_cm


def _min_room_cache_key(
    pattern: dict, spacing: SpacingConfig,
) -> str:
    """Content-based fingerprint for the min-room cache."""
    rows_json = json.dumps(
        pattern.get("rows", []), sort_keys=True,
    )
    row_gaps_json = json.dumps(pattern.get("row_gaps_cm", []))
    openings_json = json.dumps(
        pattern.get("room_openings", []), sort_keys=True,
    )
    raw = (
        f"{spacing.name}\n"
        f"{pattern.get('room_width_cm', 0)}\n"
        f"{pattern.get('room_depth_cm', 0)}\n"
        f"{rows_json}\n{row_gaps_json}\n{openings_json}"
    )
    return hashlib.md5(raw.encode()).hexdigest()


def _compute_min_room_circ_impl(
    pattern: dict,
    spacing: SpacingConfig,
    bbox: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int]:
    """Shrink-from-declared implementation of circ-aware min room.

    Returns ``(min_w, min_d, shrink_west, shrink_north)`` snapped
    to ``SNAP_CM``.  Falls back to footprint-only dimensions when
    circulation cannot be evaluated (no doors, no blocks, or the
    declared room itself fails the circulation check).
    """
    room_w = pattern.get("room_width_cm", 0)
    room_d = pattern.get("room_depth_cm", 0)
    if room_w <= 0 or room_d <= 0:
        return room_w, room_d, 0, 0

    positions = compute_block_positions(pattern)
    if not positions:
        return room_w, room_d, 0, 0

    if bbox is None:
        try:
            bbox = compute_pattern_footprint(pattern, spacing)
        except PatternStructurallyInvalid:
            return room_w, room_d, 0, 0
    fp_x_min, fp_x_max, fp_y_min, fp_y_max = bbox

    # Margins between footprint and declared walls
    margin_n = max(0, fp_y_min)
    margin_s = max(0, room_d - fp_y_max)
    margin_w = max(0, fp_x_min)
    margin_e = max(0, room_w - fp_x_max)

    if margin_n + margin_s + margin_w + margin_e == 0:
        return room_w, room_d, 0, 0

    # Guard: need at least one suitable door/opening for circ
    openings = pattern.get("room_openings", [])
    has_entries = len(openings) > 0
    if not has_entries:
        return _circ_footprint_fallback(bbox)

    # Declared room must pass circulation to start shrinking
    if not _circulation_ok(
        pattern, room_w, room_d, 0, 0, spacing, positions,
    ):
        return _circ_footprint_fallback(bbox)

    # Shrink each side: north, east, west, south (corridor last)
    shrinks = {"north": 0, "south": 0, "east": 0, "west": 0}
    max_s = {
        "north": (margin_n // GRID_CELL_CM) * GRID_CELL_CM,
        "south": (margin_s // GRID_CELL_CM) * GRID_CELL_CM,
        "east": (margin_e // GRID_CELL_CM) * GRID_CELL_CM,
        "west": (margin_w // GRID_CELL_CM) * GRID_CELL_CM,
    }

    for side in ("north", "east", "west", "south"):
        while shrinks[side] + GRID_CELL_CM <= max_s[side]:
            shrinks[side] += GRID_CELL_CM
            cw = room_w - shrinks["west"] - shrinks["east"]
            cd = room_d - shrinks["north"] - shrinks["south"]
            if not _circulation_ok(
                pattern, cw, cd,
                shrinks["west"], shrinks["north"],
                spacing, positions,
            ):
                shrinks[side] -= GRID_CELL_CM
                break

    min_w = room_w - shrinks["west"] - shrinks["east"]
    min_d = room_d - shrinks["north"] - shrinks["south"]
    min_w = math.ceil(min_w / SNAP_CM) * SNAP_CM
    min_d = math.ceil(min_d / SNAP_CM) * SNAP_CM
    return min_w, min_d, shrinks["west"], shrinks["north"]


def _circ_footprint_fallback(
    bbox: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Fallback: footprint-only min room (no circ margins)."""
    fp_x_min, fp_x_max, fp_y_min, fp_y_max = bbox
    fp_w = math.ceil(
        (fp_x_max - fp_x_min) / SNAP_CM,
    ) * SNAP_CM
    fp_d = math.ceil(
        (fp_y_max - fp_y_min) / SNAP_CM,
    ) * SNAP_CM
    return fp_w, fp_d, max(0, fp_x_min), max(0, fp_y_min)


def _compute_min_room(
    pattern: dict,
    spacing: SpacingConfig,
) -> tuple[int, int, list[str]]:
    """Compute minimum room dimensions for a pattern.

    Combines footprint-based and circulation-aware constraints
    (D-305): the room is at least large enough to contain the
    footprint (blocks + face zones + door obstacles) and all
    features (windows, openings), and additionally includes
    enough margin for circulation to pass.

    Returns:
        (width_cm, depth_cm, warnings)
    """
    warnings: list[str] = []
    positions = compute_block_positions(pattern)

    if not positions:
        return (
            pattern.get("room_width_cm", 0),
            pattern.get("room_depth_cm", 0),
            warnings,
        )

    _check_preconditions(pattern, positions, spacing, warnings)

    bbox_x_min, bbox_x_max, bbox_y_min, bbox_y_max = (
        compute_pattern_footprint(pattern, spacing)
    )

    # D-305: circulation-aware min room (shrink from declared)
    circ_w, circ_d, shrink_w, shrink_n = (
        _compute_min_room_circ_impl(
            pattern, spacing,
            bbox=(bbox_x_min, bbox_x_max, bbox_y_min, bbox_y_max),
        )
    )

    # Feature constraints (windows, non-door openings)
    fp_width = bbox_x_max - bbox_x_min
    fp_depth = bbox_y_max - bbox_y_min
    feat_w, feat_d, feat_warns = _apply_feature_constraints(
        pattern, fp_width, fp_depth,
    )
    warnings.extend(feat_warns)
    feat_w = math.ceil(feat_w / SNAP_CM) * SNAP_CM
    feat_d = math.ceil(feat_d / SNAP_CM) * SNAP_CM

    width = max(circ_w, feat_w)
    depth = max(circ_d, feat_d)

    # Translation: bring blocks into [0, width] x [0, depth].
    # Use circ shrink as origin shift when footprint is in the
    # positive quadrant; otherwise shift to clear negative bbox.
    if bbox_x_min < 0:
        shift_x = -bbox_x_min
    else:
        shift_x = -shrink_w
    if bbox_y_min < 0:
        shift_y = -bbox_y_min
    else:
        shift_y = -shrink_n

    if shift_x != 0 or shift_y != 0:
        _translate_pattern(pattern, shift_x, shift_y)

    return width, depth, warnings


def _apply_door_obstacles(
    pattern: dict,
    spacing: SpacingConfig,
    positions: list[BlockPosition],
    block_defs: dict[str, dict],
    x_mins: list[int],
    x_maxs: list[int],
    y_mins: list[int],
    y_maxs: list[int],
) -> None:
    """Add door swing areas as 2D obstacles to the bbox lists.

    Two effects per door:

    1. **Lateral fit on wall**: the door's lateral span (offset →
       offset + width) is appended to the bbox along the wall axis,
       ensuring the room is wide/deep enough to host the door.

    2. **Perpendicular pushback**: for every block (body + face zones)
       whose lateral footprint overlaps the door's lateral span, the
       wall is pushed away from the block by ``excl_depth`` cm so the
       block cannot sit inside the door swing area.

    Args:
        pattern: Catalogue pattern.
        spacing: Spacing config (provides door_exclusion_depth_cm).
        positions: Block positions in the pattern.
        block_defs: Block defs for the pattern's standard.
        x_mins..y_maxs: Bbox extent lists (mutated in place).
    """
    for feat in pattern.get("room_openings", []):
        if not feat.get("has_door", False):
            continue
        face = feat.get("face", "")
        do = feat.get("offset_cm", 0)
        dw = feat.get("width_cm", 0)
        d_lo = do
        d_hi = do + dw

        # 1. Lateral extent on wall (always, regardless of excl_depth)
        if face in ("south", "north"):
            x_mins.append(d_lo)
            x_maxs.append(d_hi)
        elif face in ("east", "west"):
            y_mins.append(d_lo)
            y_maxs.append(d_hi)

        # D-243 F1: per-door exclusion depth
        if feat.get("opens_inward", True):
            excl_depth = spacing.door_exclusion_depth_cm
        else:
            excl_depth = spacing.walking_margin_cm
        if excl_depth <= 0:
            continue

        # 2. Perpendicular pushback for blocks in door's lateral range
        for bp in positions:
            fc = get_face_zones(bp.block_type, bp.orientation, block_defs)
            if face in ("south", "north"):
                bp_lat_lo = bp.x_cm - fc.west.outer_cm
                bp_lat_hi = bp.x_cm + bp.eo_cm + fc.east.outer_cm
                if bp_lat_hi <= d_lo or bp_lat_lo >= d_hi:
                    continue
                if face == "south":
                    y_maxs.append(
                        bp.y_cm + bp.ns_cm + fc.south.outer_cm
                        + excl_depth
                    )
                else:
                    y_mins.append(
                        bp.y_cm - fc.north.outer_cm - excl_depth
                    )
            else:
                bp_lat_lo = bp.y_cm - fc.north.outer_cm
                bp_lat_hi = bp.y_cm + bp.ns_cm + fc.south.outer_cm
                if bp_lat_hi <= d_lo or bp_lat_lo >= d_hi:
                    continue
                if face == "east":
                    x_maxs.append(
                        bp.x_cm + bp.eo_cm + fc.east.outer_cm
                        + excl_depth
                    )
                else:
                    x_mins.append(
                        bp.x_cm - fc.west.outer_cm - excl_depth
                    )


def get_face_zones(
    block_type: str,
    orientation: int,
    block_defs: dict[str, dict],
) -> FaceCandidates:
    """Get rotated face zones for a block at a given orientation."""
    bd = block_defs.get(block_type)
    if bd is None:
        return FaceCandidates(
            north=FaceZone.absent(),
            south=FaceZone.absent(),
            east=FaceZone.absent(),
            west=FaceZone.absent(),
        )
    faces = bd["faces"]
    fc = FaceCandidates(
        north=FaceZone(
            faces["north"]["non_superposable_cm"],
            faces["north"]["candidate_cm"],
            internal=faces["north"].get("internal", False),
        ),
        south=FaceZone(
            faces["south"]["non_superposable_cm"],
            faces["south"]["candidate_cm"],
            internal=faces["south"].get("internal", False),
        ),
        east=FaceZone(
            faces["east"]["non_superposable_cm"],
            faces["east"]["candidate_cm"],
            internal=faces["east"].get("internal", False),
        ),
        west=FaceZone(
            faces["west"]["non_superposable_cm"],
            faces["west"]["candidate_cm"],
            internal=faces["west"].get("internal", False),
        ),
    )
    if orientation != 0:
        fc = rotate_face_candidates(fc, orientation)
    return fc


def _check_preconditions(
    pattern: dict,
    positions: list[BlockPosition],
    spacing: SpacingConfig,
    warnings: list[str],
) -> None:
    """Check block collisions (hard) and soft violations.

    Raises:
        PatternStructurallyInvalid: on physical block overlap.
    """
    # Hard: physical collision between any two blocks
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            a, b = positions[i], positions[j]
            if rects_overlap(
                a.x_cm, a.y_cm, a.eo_cm, a.ns_cm,
                b.x_cm, b.y_cm, b.eo_cm, b.ns_cm,
            ):
                raise PatternStructurallyInvalid(
                    f"Blocks ({a.row_idx},{a.block_idx}) "
                    f"{a.block_type} and ({b.row_idx},{b.block_idx}) "
                    f"{b.block_type} overlap physically"
                )

    # Soft: max_island_size
    for bp in positions:
        _, _, n_desks = _BLOCK_REGISTRY.get(bp.block_type, (0, 0, 0))
        if n_desks > spacing.max_island_size:
            warnings.append(
                f"Block ({bp.row_idx},{bp.block_idx}) "
                f"{bp.block_type}: {n_desks} desks > "
                f"max_island_size {spacing.max_island_size}"
            )

    # Soft: walking_margin between blocks within rows
    by_row: dict[int, list[BlockPosition]] = {}
    for bp in positions:
        by_row.setdefault(bp.row_idx, []).append(bp)
    for ri, bps in by_row.items():
        sorted_bps = sorted(bps, key=lambda b: b.x_cm)
        for k in range(len(sorted_bps) - 1):
            a = sorted_bps[k]
            b = sorted_bps[k + 1]
            gap = b.x_cm - (a.x_cm + a.eo_cm)
            if gap < spacing.walking_margin_cm:
                warnings.append(
                    f"Row {ri}: gap {gap} cm between blocks "
                    f"{a.block_idx} and {b.block_idx} < "
                    f"walking_margin "
                    f"{spacing.walking_margin_cm} cm"
                )

    # Soft: row gaps
    for i, gap in enumerate(pattern.get("row_gaps_cm", [])):
        if gap < spacing.walking_margin_cm:
            warnings.append(
                f"Row gap {i}: {gap} cm < "
                f"walking_margin "
                f"{spacing.walking_margin_cm} cm"
            )


def rects_overlap(
    x1: int, y1: int, w1: int, h1: int,
    x2: int, y2: int, w2: int, h2: int,
) -> bool:
    """Check whether two axis-aligned rectangles overlap."""
    return (
        x1 < x2 + w2 and x1 + w1 > x2
        and y1 < y2 + h2 and y1 + h1 > y2
    )


def _apply_feature_constraints(
    pattern: dict,
    width: int,
    depth: int,
) -> tuple[int, int, list[str]]:
    """Ensure room faces can accommodate features.

    Full-width features (offset=0, width=face_length) are treated as
    extensible: they shrink/expand with the room and do not block fit.

    D-314: only openings/doors are placement constraints (they need wall
    width and create exclusion zones). Windows are a *preference* (desks
    near windows score higher via _compute_dim_light), never a constraint —
    so room_windows is excluded here.

    Returns:
        (adjusted_width, adjusted_depth, warnings)
    """
    warnings: list[str] = []
    room_w = pattern.get("room_width_cm", 0)
    room_d = pattern.get("room_depth_cm", 0)

    for feature_key in ("room_openings",):
        for feat in pattern.get(feature_key, []):
            face = feat.get("face", "")
            offset = feat.get("offset_cm", 0)
            feat_w = feat.get("width_cm", 0)
            extent = offset + feat_w

            # Skip full-width features — they adapt to the room
            if face in ("north", "south") and offset == 0 and feat_w == room_w:
                continue
            if face in ("east", "west") and offset == 0 and feat_w == room_d:
                continue

            # Doors: ensure face is at least as wide as the door.
            # Position is already accounted for via door exclusion rects.
            if feat.get("has_door", False):
                if face in ("north", "south") and feat_w > width:
                    warnings.append(
                        f"Door on {face}: forced width from "
                        f"{width} to {feat_w} cm"
                    )
                    width = feat_w
                elif face in ("east", "west") and feat_w > depth:
                    warnings.append(
                        f"Door on {face}: forced depth from "
                        f"{depth} to {feat_w} cm"
                    )
                    depth = feat_w
                continue

            if face in ("north", "south"):
                if extent > width:
                    warnings.append(
                        f"Feature on {face} (offset={offset}"
                        f" + width={feat_w}) forced room "
                        f"width from {width} to {extent} cm"
                    )
                    width = extent
            elif face in ("east", "west"):
                if extent > depth:
                    warnings.append(
                        f"Feature on {face} (offset={offset}"
                        f" + width={feat_w}) forced room "
                        f"depth from {depth} to {extent} cm"
                    )
                    depth = extent

    return width, depth, warnings


def _revalidate_features(
    pattern: dict,
    room_width: int,
    room_depth: int,
    old_room_w: int = 0,
    old_room_d: int = 0,
) -> list[str]:
    """Clip or drop features that no longer fit.

    Mutates the pattern's feature lists in place.

    Returns:
        List of warning strings.
    """
    warnings: list[str] = []

    for feature_key in ("room_windows", "room_openings"):
        to_drop: list[int] = []
        for idx, feat in enumerate(pattern.get(feature_key, [])):
            face = feat.get("face", "")
            old_face_len = (
                old_room_w if face in ("north", "south") else old_room_d
            )
            face_len = (
                room_width if face in ("north", "south") else room_depth
            )
            offset = feat.get("offset_cm", 0)
            w = feat.get("width_cm", 0)

            # Full-width features adapt silently to the new room size
            if offset == 0 and w == old_face_len:
                feat["width_cm"] = face_len
                continue

            if offset + w <= face_len:
                continue

            is_door = feat.get("has_door", False)

            # Doors: reposition to fit within the new face length
            if is_door and w <= face_len:
                new_offset = face_len - w
                warnings.append(
                    f"Door on {face}: repositioned from offset "
                    f"{offset} to {new_offset} cm"
                )
                feat["offset_cm"] = new_offset
                continue

            max_w = face_len - offset

            if max_w < 0:
                if is_door:
                    # Door wider than face — reposition at 0
                    feat["offset_cm"] = 0
                    feat["width_cm"] = min(w, face_len)
                    warnings.append(
                        f"Door on {face}: repositioned to offset 0, "
                        f"width clipped to {feat['width_cm']} cm"
                    )
                else:
                    to_drop.append(idx)
                    warnings.append(
                        f"{feature_key[5:]} on {face} at offset "
                        f"{offset}: dropped (offset beyond face "
                        f"length {face_len} cm)"
                    )
            elif is_door and max_w < MIN_DOOR_WIDTH_CM:
                # Reposition door to fit
                new_offset = max(0, face_len - w)
                feat["offset_cm"] = new_offset
                warnings.append(
                    f"Door on {face}: repositioned from offset "
                    f"{offset} to {new_offset} cm"
                )
            else:
                warnings.append(
                    f"{feature_key[5:]} on {face} at offset {offset}: "
                    f"clipped from {w} to {max_w} cm"
                )
                feat["width_cm"] = max_w

        # Drop in reverse order to preserve indices
        features_list = pattern.get(feature_key, [])
        for idx in reversed(to_drop):
            features_list.pop(idx)

    # Exclusion zones: clip to room bounds
    for excl in pattern.get("room_exclusions", []):
        x = excl.get("x_cm", 0)
        y = excl.get("y_cm", 0)
        w = excl.get("width_cm", 0)
        d = excl.get("depth_cm", 0)

        if x + w > room_width:
            old_w = w
            excl["width_cm"] = max(0, room_width - x)
            if excl["width_cm"] != old_w:
                warnings.append(
                    f"Exclusion at ({x},{y}): width clipped "
                    f"from {old_w} to {excl['width_cm']} cm"
                )
        if y + d > room_depth:
            old_d = d
            excl["depth_cm"] = max(0, room_depth - y)
            if excl["depth_cm"] != old_d:
                warnings.append(
                    f"Exclusion at ({x},{y}): depth clipped "
                    f"from {old_d} to {excl['depth_cm']} cm"
                )

    return warnings


def _translate_pattern(
    pattern: dict,
    shift_x: int,
    shift_y: int,
) -> None:
    """Translate all blocks and door offsets by (shift_x, shift_y).

    - Blocks: shift_y added to offset_ns_cm, shift_x to first gap_cm.
    - Doors/openings on south/north: offset_cm += shift_x.
    - Doors/openings on east/west: offset_cm += shift_y.
    - Windows follow the same rule as openings.
    """
    rows = pattern.get("rows", [])
    if shift_y != 0:
        for row in rows:
            for block in row.get("blocks", []):
                block["offset_ns_cm"] = (
                    block.get("offset_ns_cm", 0) + shift_y
                )
    if shift_x != 0:
        for row in rows:
            blocks = row.get("blocks", [])
            if blocks:
                blocks[0]["gap_cm"] = (
                    blocks[0].get("gap_cm", 0) + shift_x
                )

    # Translate feature offsets along the wall they sit on.
    # Skip full-width features (offset=0, width=face_length) — they
    # adapt to the new room via _revalidate_features instead.
    room_w = pattern.get("room_width_cm", 0)
    room_d = pattern.get("room_depth_cm", 0)
    for feature_key in ("room_openings", "room_windows"):
        for feat in pattern.get(feature_key, []):
            face = feat.get("face", "")
            offset = feat.get("offset_cm", 0)
            w = feat.get("width_cm", 0)
            if face in ("south", "north") and shift_x != 0:
                face_len = room_w
                if offset == 0 and w == face_len:
                    continue
                feat["offset_cm"] = offset + shift_x
            elif face in ("east", "west") and shift_y != 0:
                face_len = room_d
                if offset == 0 and w == face_len:
                    continue
                feat["offset_cm"] = offset + shift_y
