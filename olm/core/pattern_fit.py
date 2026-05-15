"""Pattern fit — compute and apply minimum valid room dimensions.

Computes the minimum room (width_cm, depth_cm) that can accommodate
a pattern at its standard, then applies those dimensions.
The operation is bidirectional: it shrinks oversize rooms and
expands undersize rooms to the same minimum.
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

    # Step 8: re-validate features against the new room
    feat_warnings = _revalidate_features(pattern, new_w, new_d)
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

    May mutate pattern DSL coordinates (offset_ns_cm, gap_cm)
    to translate blocks into the positive quadrant.

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

    # Steps 2-4 merged: effective footprints
    # Each block claims either its face zone or desk_to_wall_cm (whichever
    # applies) on every face.
    desk_to_wall = spacing.desk_to_wall_cm

    x_mins: list[int] = []
    x_maxs: list[int] = []
    y_mins: list[int] = []
    y_maxs: list[int] = []

    for bp in positions:
        fc = _get_face_zones(bp.block_type, bp.orientation, block_defs)
        eff_w = fc.west.total_cm if fc.west.total_cm > 0 else desk_to_wall
        eff_e = fc.east.total_cm if fc.east.total_cm > 0 else desk_to_wall
        eff_n = fc.north.total_cm if fc.north.total_cm > 0 else desk_to_wall
        eff_s = fc.south.total_cm if fc.south.total_cm > 0 else desk_to_wall

        x_mins.append(bp.x_cm - eff_w)
        x_maxs.append(bp.x_cm + bp.eo_cm + eff_e)
        y_mins.append(bp.y_cm - eff_n)
        y_maxs.append(bp.y_cm + bp.ns_cm + eff_s)

    bbox_x_min = min(x_mins)
    bbox_x_max = max(x_maxs)
    bbox_y_min = min(y_mins)
    bbox_y_max = max(y_maxs)

    width = bbox_x_max - bbox_x_min
    depth = bbox_y_max - bbox_y_min

    # Step 5: feature constraint
    width, depth, feat_warns = _apply_feature_constraints(
        pattern, width, depth,
    )
    warnings.extend(feat_warns)

    # Step 6: snap
    width = math.ceil(width / SNAP_CM) * SNAP_CM
    depth = math.ceil(depth / SNAP_CM) * SNAP_CM

    # Translation: bring all blocks into [0, width] x [0, depth]
    shift_x = -bbox_x_min
    shift_y = -bbox_y_min
    if shift_x != 0 or shift_y != 0:
        _translate_blocks(pattern, shift_x, shift_y)

    return width, depth, warnings


def _get_face_zones(
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
    """Step 1: check block collisions (hard) and soft violations.

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
    """Step 5: ensure room faces can accommodate features.

    Returns:
        (adjusted_width, adjusted_depth, warnings)
    """
    warnings: list[str] = []

    for feature_key in ("room_windows", "room_openings"):
        for feat in pattern.get(feature_key, []):
            face = feat.get("face", "")
            extent = feat.get("offset_cm", 0) + feat.get("width_cm", 0)

            if face in ("north", "south"):
                if extent > width:
                    warnings.append(
                        f"Feature on {face} (offset={feat.get('offset_cm')}"
                        f" + width={feat.get('width_cm')}) forced room "
                        f"width from {width} to {extent} cm"
                    )
                    width = extent
            elif face in ("east", "west"):
                if extent > depth:
                    warnings.append(
                        f"Feature on {face} (offset={feat.get('offset_cm')}"
                        f" + width={feat.get('width_cm')}) forced room "
                        f"depth from {depth} to {extent} cm"
                    )
                    depth = extent

    return width, depth, warnings


def _revalidate_features(
    pattern: dict,
    room_width: int,
    room_depth: int,
) -> list[str]:
    """Step 8: clip or drop features that no longer fit.

    Mutates the pattern's feature lists in place.

    Returns:
        List of warning strings.
    """
    warnings: list[str] = []

    for feature_key in ("room_windows", "room_openings"):
        to_drop: list[int] = []
        for idx, feat in enumerate(pattern.get(feature_key, [])):
            face = feat.get("face", "")
            face_len = (
                room_width if face in ("north", "south") else room_depth
            )
            offset = feat.get("offset_cm", 0)
            w = feat.get("width_cm", 0)

            if offset + w <= face_len:
                continue

            max_w = face_len - offset
            is_door = feat.get("has_door", False)

            if max_w < 0:
                to_drop.append(idx)
                warnings.append(
                    f"{feature_key[5:]} on {face} at offset {offset}: "
                    f"dropped (offset beyond face length {face_len} cm)"
                )
            elif is_door and max_w < MIN_DOOR_WIDTH_CM:
                to_drop.append(idx)
                warnings.append(
                    f"Door on {face} at offset {offset}: "
                    f"dropped (clipped width {max_w} cm < "
                    f"minimum {MIN_DOOR_WIDTH_CM} cm)"
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


def _translate_blocks(
    pattern: dict,
    shift_x: int,
    shift_y: int,
) -> None:
    """Translate all blocks by (shift_x, shift_y) in DSL coordinates.

    - shift_y is added to every block's offset_ns_cm.
    - shift_x is added to the first block's gap_cm in each row.
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
