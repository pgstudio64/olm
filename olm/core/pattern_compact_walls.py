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


_MAX_EAST_ITER = 100


def _compact_east(
    pattern: dict,
    spacing: SpacingConfig,
    block_defs: dict[str, dict],
) -> int:
    """Move east wall inward using iterative catch-distance.

    The virtual east wall starts at max(eff_east_edge) across all blocks.
    Each iteration, the wall advances toward blocks that are not yet
    touching it (catch distance). Once a block is caught, it moves with
    the wall on subsequent iterations. The loop terminates when no row
    has recoverable slack.

    Returns:
        Number of gap_cm values modified (cumulative across iterations).
    """
    rows = pattern.get("rows", [])
    if not rows:
        return 0

    desk_to_wall = spacing.desk_to_wall_cm
    changes_total = 0

    for iteration in range(_MAX_EAST_ITER):
        positions = compute_block_positions(pattern)
        if not positions:
            break

        # Effective east edge per block
        block_east_edges: list[int] = []
        for bp in positions:
            fc = get_face_zones(bp.block_type, bp.orientation, block_defs)
            eff_e = fc.east.total_cm if fc.east.total_cm > 0 else desk_to_wall
            block_east_edges.append(bp.x_cm + bp.eo_cm + eff_e)

        # Virtual wall = max effective east edge
        wall = max(block_east_edges)
        if wall <= 0:
            break

        # Touching = blocks whose eff east edge == wall
        touching_set: set[int] = {
            i for i, edge in enumerate(block_east_edges) if edge == wall
        }
        if not touching_set:
            break

        # Group positions by row
        rows_positions: dict[int, list[tuple[int, object]]] = {}
        for i, bp in enumerate(positions):
            rows_positions.setdefault(bp.row_idx, []).append((i, bp))

        # Compute margin per row
        margins: list[int] = []
        for ri, row_bps in rows_positions.items():
            row_bps_sorted = sorted(row_bps, key=lambda t: t[1].x_cm)

            # Does this row have a touching block?
            row_touching = [
                (i, bp) for i, bp in row_bps_sorted if i in touching_set
            ]

            if not row_touching:
                # Catch distance: wall - rightmost eff east edge of row
                max_edge = max(block_east_edges[i] for i, _ in row_bps_sorted)
                margins.append(wall - max_edge)
            else:
                # Slack of first touching block
                first_idx, first_bp = row_touching[0]
                block_idx = first_bp.block_idx
                block = rows[ri]["blocks"][block_idx]

                if block_idx == 0:
                    fc = get_face_zones(
                        first_bp.block_type, first_bp.orientation, block_defs,
                    )
                    eff_w = (
                        fc.west.total_cm if fc.west.total_cm > 0
                        else desk_to_wall
                    )
                    min_gap = eff_w
                else:
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
                        first_bp.block_type, first_bp.orientation, block_defs,
                    )
                    min_gap = fc_prev.east.total_cm + fc_this.west.total_cm

                current_gap = block.get("gap_cm", 0)
                margins.append(max(0, current_gap - min_gap))

        if not margins:
            break

        delta = min(margins)
        if delta <= 0:
            break

        # Apply: reduce gap_cm of each touching block
        for idx in touching_set:
            bp = positions[idx]
            block = rows[bp.row_idx]["blocks"][bp.block_idx]
            block["gap_cm"] = block.get("gap_cm", 0) - delta
            changes_total += 1

        logger.debug(
            "compact_east iter %d: wall=%d delta=%d touching=%d",
            iteration, wall, delta, len(touching_set),
        )

    return changes_total


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
