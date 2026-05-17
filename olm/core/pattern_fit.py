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

import logging
import math
from dataclasses import dataclass, field
from typing import Literal

from olm.core.catalogue_matcher import (
    BlockPosition,
    _BLOCK_REGISTRY,
    compute_block_positions,
)
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


class PatternStructurallyInvalid(Exception):
    """Blocks have physical collisions — pattern cannot be fitted."""


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


def _compute_min_room(
    pattern: dict,
    spacing: SpacingConfig,
) -> tuple[int, int, list[str]]:
    """Compute minimum room dimensions for a pattern.

    Collects all obstacle rectangles (workstation footprints and door
    exclusion zones), computes the tightest bounding box, then snaps
    to grid.  May mutate pattern DSL coordinates (offset_ns_cm, gap_cm,
    door offsets) to translate into the positive quadrant.

    Returns:
        (width_cm, depth_cm, warnings)
    """
    warnings: list[str] = []
    block_defs = build_block_defs(spacing)
    positions = compute_block_positions(pattern)

    if not positions:
        return (
            pattern.get("room_width_cm", 0),
            pattern.get("room_depth_cm", 0),
            warnings,
        )

    # Step 1: preconditions
    _check_preconditions(pattern, positions, spacing, warnings)

    # Steps 2-4: collect all obstacle rectangles
    desk_to_wall = spacing.desk_to_wall_cm

    x_mins: list[int] = []
    x_maxs: list[int] = []
    y_mins: list[int] = []
    y_maxs: list[int] = []

    # Workstation block footprints (body + face zones)
    for bp in positions:
        fc = get_face_zones(bp.block_type, bp.orientation, block_defs)
        eff_w = fc.west.total_cm if fc.west.total_cm > 0 else desk_to_wall
        eff_e = fc.east.total_cm if fc.east.total_cm > 0 else desk_to_wall
        eff_n = fc.north.total_cm if fc.north.total_cm > 0 else desk_to_wall
        eff_s = fc.south.total_cm if fc.south.total_cm > 0 else desk_to_wall

        x_mins.append(bp.x_cm - eff_w)
        x_maxs.append(bp.x_cm + bp.eo_cm + eff_e)
        y_mins.append(bp.y_cm - eff_n)
        y_maxs.append(bp.y_cm + bp.ns_cm + eff_s)

    # Door exclusion zone rectangles (same coordinate system as blocks)
    _collect_door_exclusion_rects(
        pattern, spacing, x_mins, x_maxs, y_mins, y_maxs,
    )

    bbox_x_min = min(x_mins)
    bbox_x_max = max(x_maxs)
    bbox_y_min = min(y_mins)
    bbox_y_max = max(y_maxs)

    width = bbox_x_max - bbox_x_min
    depth = bbox_y_max - bbox_y_min

    # Feature constraint (windows, non-door openings)
    width, depth, feat_warns = _apply_feature_constraints(
        pattern, width, depth,
    )
    warnings.extend(feat_warns)

    # Snap
    width = math.ceil(width / SNAP_CM) * SNAP_CM
    depth = math.ceil(depth / SNAP_CM) * SNAP_CM

    # Translation: bring everything into [0, width] x [0, depth]
    shift_x = -bbox_x_min
    shift_y = -bbox_y_min
    if shift_x != 0 or shift_y != 0:
        _translate_pattern(pattern, shift_x, shift_y)

    return width, depth, warnings


def _collect_door_exclusion_rects(
    pattern: dict,
    spacing: SpacingConfig,
    x_mins: list[int],
    x_maxs: list[int],
    y_mins: list[int],
    y_maxs: list[int],
) -> None:
    """Add door exclusion zone footprints to the obstacle lists.

    Only constrains the axis PERPENDICULAR to the door's wall:
    - South/North doors: constrain X (offset → offset + width).
    - East/West doors: constrain Y (offset → offset + width).

    The axis parallel to the door face (depth from the wall) is NOT
    constrained because the door moves with its wall when the room
    shrinks or expands.

    Args:
        pattern: Catalogue pattern.
        spacing: Spacing config (provides door_exclusion_depth_cm).
        x_mins..y_maxs: Obstacle extent lists (mutated in place).
    """
    excl_depth = spacing.door_exclusion_depth_cm
    if excl_depth <= 0:
        return

    for feat in pattern.get("room_openings", []):
        if not feat.get("has_door", False):
            continue

        face = feat.get("face", "")
        offset = feat.get("offset_cm", 0)
        w = feat.get("width_cm", 0)

        if face in ("south", "north"):
            x_mins.append(offset)
            x_maxs.append(offset + w)
        elif face in ("east", "west"):
            y_mins.append(offset)
            y_maxs.append(offset + w)


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
        ),
        south=FaceZone(
            faces["south"]["non_superposable_cm"],
            faces["south"]["candidate_cm"],
        ),
        east=FaceZone(
            faces["east"]["non_superposable_cm"],
            faces["east"]["candidate_cm"],
        ),
        west=FaceZone(
            faces["west"]["non_superposable_cm"],
            faces["west"]["candidate_cm"],
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
            if _rects_overlap(
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

    # Soft: min_block_separation within rows
    by_row: dict[int, list[BlockPosition]] = {}
    for bp in positions:
        by_row.setdefault(bp.row_idx, []).append(bp)
    for ri, bps in by_row.items():
        sorted_bps = sorted(bps, key=lambda b: b.x_cm)
        for k in range(len(sorted_bps) - 1):
            a = sorted_bps[k]
            b = sorted_bps[k + 1]
            gap = b.x_cm - (a.x_cm + a.eo_cm)
            if gap < spacing.min_block_separation_cm:
                warnings.append(
                    f"Row {ri}: gap {gap} cm between blocks "
                    f"{a.block_idx} and {b.block_idx} < "
                    f"min_block_separation "
                    f"{spacing.min_block_separation_cm} cm"
                )

    # Soft: row gaps
    for i, gap in enumerate(pattern.get("row_gaps_cm", [])):
        if gap < spacing.min_block_separation_cm:
            warnings.append(
                f"Row gap {i}: {gap} cm < "
                f"min_block_separation "
                f"{spacing.min_block_separation_cm} cm"
            )


def _rects_overlap(
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

    Returns:
        (adjusted_width, adjusted_depth, warnings)
    """
    warnings: list[str] = []
    room_w = pattern.get("room_width_cm", 0)
    room_d = pattern.get("room_depth_cm", 0)

    for feature_key in ("room_windows", "room_openings"):
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
