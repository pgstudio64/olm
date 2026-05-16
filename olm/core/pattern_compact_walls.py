"""Pattern compact walls — shrink room by moving east/south walls inward.

D-217: Blocks touching a wall (by lock or accidental contact) move with it.
The NW corner (origin) is fixed; only east and south walls move inward.

Pipeline position: after canonicalize, before normalize_intra/inter and fit.
This module modifies gap_cm and row_gaps_cm only — never room dimensions.
"""
from __future__ import annotations

import logging

from olm.core.catalogue_matcher import compute_block_positions
from olm.core.pattern_fit import get_face_zones
from olm.core.spacing_config import SpacingConfig, build_block_defs

logger = logging.getLogger(__name__)


def compact_walls(pattern: dict, spacing: SpacingConfig) -> int:
    """Move east and south walls inward, dragging attached blocks.

    Modifies ``pattern`` in place: adjusts ``gap_cm`` (east axis) and
    ``row_gaps_cm`` (south axis). Does NOT modify room_width_cm or
    room_depth_cm — that is fit_room_to_pattern's responsibility.

    Args:
        pattern: Catalogue pattern (JSON dict). Mutated in place.
        spacing: Target spacing configuration.

    Returns:
        Number of gap_cm / row_gaps_cm values modified.
    """
    block_defs = build_block_defs(spacing)
    changes = 0

    changes += _compact_east(pattern, spacing, block_defs)
    changes += _compact_south(pattern, spacing, block_defs)

    return changes


# ---------------------------------------------------------------------------
# East wall compact
# ---------------------------------------------------------------------------


def _compact_east(
    pattern: dict,
    spacing: SpacingConfig,
    block_defs: dict[str, dict],
) -> int:
    """Move east wall inward by reducing gap_cm of touching blocks.

    For each row, compute how much the east wall can move (margin).
    Global delta = min margin across all rows.
    Then reduce gap_cm of each touching block by delta.

    Returns:
        Number of gap_cm values modified.
    """
    room_width = pattern.get("room_width_cm", 0)
    if room_width <= 0:
        return 0

    positions = compute_block_positions(pattern)
    if not positions:
        return 0

    rows = pattern.get("rows", [])
    desk_to_wall = spacing.desk_to_wall_cm

    # Compute effective east edge for each block
    block_east_edges: list[int] = []
    for bp in positions:
        fc = get_face_zones(bp.block_type, bp.orientation, block_defs)
        eff_e = fc.east.total_cm if fc.east.total_cm > 0 else desk_to_wall
        block_east_edges.append(bp.x_cm + bp.eo_cm + eff_e)

    # Identify touching blocks (effective east edge == room_width)
    touching_indices = [
        i for i, edge in enumerate(block_east_edges)
        if edge == room_width
    ]

    if not touching_indices:
        return 0

    # Compute margin per row (how much the east wall can move)
    # For each row, the constraint comes from the gap between the last
    # non-moving block and the first moving block in that row.
    margins = _compute_east_margins(
        pattern, positions, block_defs, spacing, touching_indices, room_width,
    )

    if not margins:
        return 0

    delta = min(margins)
    if delta <= 0:
        return 0

    # Apply: reduce gap_cm of each touching block by delta
    changes = 0
    for idx in touching_indices:
        bp = positions[idx]
        row = rows[bp.row_idx]
        block = row["blocks"][bp.block_idx]
        old_gap = block.get("gap_cm", 0)
        block["gap_cm"] = old_gap - delta
        changes += 1

    logger.debug("compact_east: delta=%d, %d blocks moved", delta, changes)
    return changes


def _compute_east_margins(
    pattern: dict,
    positions: list,
    block_defs: dict[str, dict],
    spacing: SpacingConfig,
    touching_indices: list[int],
    room_width: int,
) -> list[int]:
    """Compute per-row margin for east wall movement.

    For each row:
    - If no block touches east, margin = room_width - max_effective_east_edge.
    - If a block touches east, margin = that block's gap_cm - min_gap.
      Where min_gap depends on whether it's the first block (uses west face
      zone as minimum offset) or has a predecessor (uses inter-block min gap).

    Returns:
        List of margins (one per row). Empty if no rows.
    """
    rows = pattern.get("rows", [])
    desk_to_wall = spacing.desk_to_wall_cm
    touching_set = set(touching_indices)

    # Group positions by row
    rows_positions: dict[int, list] = {}
    for i, bp in enumerate(positions):
        rows_positions.setdefault(bp.row_idx, []).append((i, bp))

    margins: list[int] = []

    for ri in range(len(rows)):
        row_bps = rows_positions.get(ri, [])
        if not row_bps:
            margins.append(room_width)
            continue

        # Sort by x_cm within row
        row_bps_sorted = sorted(row_bps, key=lambda t: t[1].x_cm)

        # Find touching blocks in this row
        row_touching = [(i, bp) for i, bp in row_bps_sorted if i in touching_set]

        if not row_touching:
            # No block touches east in this row — margin = distance from
            # rightmost effective edge to the wall
            max_edge = max(
                bp.x_cm + bp.eo_cm + (
                    get_face_zones(bp.block_type, bp.orientation, block_defs)
                    .east.total_cm
                    or desk_to_wall
                )
                for _, bp in row_bps_sorted
            )
            margins.append(room_width - max_edge)
        else:
            # The leftmost touching block determines the constraint.
            # All touching blocks move together by delta, so the gap
            # compression happens at the junction between the last
            # non-touching block and the first touching block.
            first_touching_idx, first_touching_bp = row_touching[0]
            block_idx = first_touching_bp.block_idx
            row_blocks = rows[ri]["blocks"]
            block = row_blocks[block_idx]

            if block_idx == 0:
                # First block in row — min gap = west extreme face zone
                fc = get_face_zones(
                    first_touching_bp.block_type,
                    first_touching_bp.orientation,
                    block_defs,
                )
                eff_w = fc.west.total_cm if fc.west.total_cm > 0 else desk_to_wall
                min_gap = eff_w
            else:
                # Has a predecessor — min gap = prev.east + this.west
                prev_bp = None
                for _, bp in row_bps_sorted:
                    if bp.block_idx == block_idx - 1:
                        prev_bp = bp
                        break
                if prev_bp is None:
                    margins.append(0)
                    continue

                fc_prev = get_face_zones(
                    prev_bp.block_type, prev_bp.orientation, block_defs,
                )
                fc_this = get_face_zones(
                    first_touching_bp.block_type,
                    first_touching_bp.orientation,
                    block_defs,
                )
                min_gap = fc_prev.east.total_cm + fc_this.west.total_cm

            current_gap = block.get("gap_cm", 0)
            margin = current_gap - min_gap
            margins.append(max(0, margin))

    return margins


# ---------------------------------------------------------------------------
# South wall compact
# ---------------------------------------------------------------------------


def _compact_south(
    pattern: dict,
    spacing: SpacingConfig,
    block_defs: dict[str, dict],
) -> int:
    """Move south wall inward by reducing row_gaps_cm.

    Computes minimum achievable row_gaps (using D-216 pair-by-pair X
    projection) and reduces each row_gap toward its minimum.

    The total south delta = sum of (current_gap - min_gap) over all row gaps.

    Returns:
        Number of row_gaps_cm values modified.
    """
    row_gaps = pattern.get("row_gaps_cm", [])
    if not row_gaps:
        return 0

    room_depth = pattern.get("room_depth_cm", 0)
    if room_depth <= 0:
        return 0

    # Recompute positions after east compact (gap_cm may have changed)
    positions = compute_block_positions(pattern)
    if not positions:
        return 0

    desk_to_wall = spacing.desk_to_wall_cm

    # Check if any block touches south wall
    south_touching = False
    for bp in positions:
        fc = get_face_zones(bp.block_type, bp.orientation, block_defs)
        eff_s = fc.south.total_cm if fc.south.total_cm > 0 else desk_to_wall
        if bp.y_cm + bp.ns_cm + eff_s == room_depth:
            south_touching = True
            break

    if not south_touching:
        return 0

    # Compute minimum row_gaps using D-216 pair-by-pair X projection
    min_gaps = _compute_min_row_gaps(pattern, positions, block_defs)

    # Reduce each row_gap to its minimum (compact as much as possible)
    changes = 0
    for i in range(len(row_gaps)):
        if i >= len(min_gaps):
            break
        current = row_gaps[i]
        minimum = min_gaps[i]
        if current > minimum:
            row_gaps[i] = minimum
            changes += 1

    if changes > 0:
        pattern["row_gaps_cm"] = row_gaps
        logger.debug("compact_south: %d row_gaps reduced", changes)

    return changes


def _compute_min_row_gaps(
    pattern: dict,
    positions: list,
    block_defs: dict[str, dict],
) -> list[int]:
    """Compute minimum achievable row_gaps using D-216 X-projection.

    Same logic as _normalize_inter_row_gaps in pattern_normalize.py,
    but returns the minimum values without mutating the pattern.

    Returns:
        List of minimum row gap values.
    """
    rows = pattern.get("rows", [])
    row_gaps = pattern.get("row_gaps_cm", [])

    # Group positions by row_idx
    rows_positions: dict[int, list] = {}
    for bp in positions:
        rows_positions.setdefault(bp.row_idx, []).append(bp)

    # Compute max_ns per row
    max_ns_per_row: dict[int, int] = {}
    for ri, bps in rows_positions.items():
        max_ns_per_row[ri] = max((bp.ns_cm for bp in bps), default=0)

    min_gaps: list[int] = []

    for gi in range(len(row_gaps)):
        if gi >= len(rows) - 1:
            break

        upper_positions = rows_positions.get(gi, [])
        lower_positions = rows_positions.get(gi + 1, [])

        if not upper_positions or not lower_positions:
            min_gaps.append(0)
            continue

        max_ns_upper = max_ns_per_row.get(gi, 0)
        upper_row_blocks = rows[gi].get("blocks", [])
        lower_row_blocks = rows[gi + 1].get("blocks", [])

        max_required = 0

        for bp_upper in upper_positions:
            block_upper = upper_row_blocks[bp_upper.block_idx]
            fc_upper = get_face_zones(
                bp_upper.block_type, bp_upper.orientation, block_defs,
            )
            offset_ns_upper = block_upper.get("offset_ns_cm", 0)

            # Effective X footprint (body + EW face zones, no dtw)
            x_min_upper = bp_upper.x_cm - fc_upper.west.total_cm
            x_max_upper = (
                bp_upper.x_cm + bp_upper.eo_cm + fc_upper.east.total_cm
            )

            for bp_lower in lower_positions:
                block_lower = lower_row_blocks[bp_lower.block_idx]
                fc_lower = get_face_zones(
                    bp_lower.block_type, bp_lower.orientation, block_defs,
                )
                offset_ns_lower = block_lower.get("offset_ns_cm", 0)

                # Effective X footprint
                x_min_lower = bp_lower.x_cm - fc_lower.west.total_cm
                x_max_lower = (
                    bp_lower.x_cm + bp_lower.eo_cm + fc_lower.east.total_cm
                )

                # X overlap check
                if max(x_min_upper, x_min_lower) >= min(
                    x_max_upper, x_max_lower,
                ):
                    continue

                # Vertical constraint
                pair_required = (
                    offset_ns_upper + bp_upper.ns_cm
                    + fc_upper.south.total_cm
                    - max_ns_upper
                    - offset_ns_lower
                    + fc_lower.north.total_cm
                )
                max_required = max(max_required, pair_required)

        min_gaps.append(max(0, max_required))

    return min_gaps
