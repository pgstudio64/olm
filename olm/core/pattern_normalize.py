"""Pattern normalization — recalibrate spacings to a target standard.

Normalizes all internal spacings (gap_cm between blocks in a row,
row_gaps_cm between rows) to the exact minimum required by the target
standard, then delegates to fit_room_to_pattern for room dimension
computation.

Philosophy: symmetric normalization (B) — gaps are expanded if too tight
and compressed if too loose, converging to the standard's exact minimum.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from olm.core.catalogue_matcher import compute_block_positions
from olm.core.pattern_canonicalize import canonicalize_blocks
from olm.core.pattern_compact_walls import compact_walls
from olm.core.pattern_fit import (
    FitResult,
    PatternStructurallyInvalid,
    fit_room_to_pattern,
    get_face_zones,
)
from olm.core.spacing_config import SpacingConfig, build_block_defs

logger = logging.getLogger(__name__)

# Threshold (cm) for emitting a warning about extreme offset_ns_cm values.
# A block whose offset extends more than this beyond its row depth triggers a warning.
_EXTREME_OFFSET_THRESHOLD_CM = 100


@dataclass
class NormalizeResult:
    """Result of a normalize operation on a single pattern.

    Attributes:
        name: Pattern name.
        gaps_changed: Number of intra-row gaps modified.
        row_gaps_changed: Number of inter-row gaps modified.
        fit: FitResult from fit_room_to_pattern (room dimensions).
        old_standard: Original standard of the pattern before normalization.
        new_standard: Target standard applied after normalization.
        warnings: Accumulated warnings from normalization + fit.
    """

    name: str
    gaps_changed: int
    row_gaps_changed: int
    fit: FitResult
    old_standard: str
    new_standard: str
    warnings: list[str] = field(default_factory=list)

    @property
    def direction(self) -> str:
        """Summary direction: 'expanded', 'compressed', or 'noop'."""
        if self.gaps_changed == 0 and self.row_gaps_changed == 0:
            if self.fit.direction == "noop":
                return "noop"
        if self.fit.direction == "expand":
            return "expanded"
        if self.fit.direction == "shrink":
            return "compressed"
        if self.gaps_changed > 0 or self.row_gaps_changed > 0:
            return "expanded"
        return "noop"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_pattern(
    pattern: dict,
    target_spacing: SpacingConfig,
) -> NormalizeResult:
    """Normalize a pattern's spacings to the target standard.

    Mutates ``pattern`` in place:
    - Canonicalizes block order (D-213): sorts blocks within each row
      by ascending x_cm and recomputes gap_cm.
    - Adjusts ``gap_cm`` between consecutive blocks in each row.
    - Adjusts ``row_gaps_cm`` between consecutive rows.
    - Updates ``pattern["standard"]`` to the target standard.
    - Delegates to ``fit_room_to_pattern`` for room dimension recompute.

    Does NOT touch ``offset_ns_cm`` (intentional design choice, not spacing).

    Args:
        pattern: Catalogue pattern (JSON dict). Mutated in place.
        target_spacing: Target spacing configuration.

    Returns:
        NormalizeResult with change counts and fit result.

    Raises:
        PatternStructurallyInvalid: If blocks overlap after normalization
            (raised by fit_room_to_pattern).
    """
    old_standard = pattern.get("standard", "")
    new_standard = target_spacing.name
    warnings: list[str] = []

    # Step 0: canonicalize block order (D-213) — sort by spatial x_cm,
    # recompute gap_cm. Must run before intra-row gap normalization
    # which assumes JSON order = spatial order.
    canon = canonicalize_blocks(pattern)
    if canon.n_reorderings > 0:
        warnings.append(
            f"Canonicalized {canon.n_reorderings} row(s) "
            f"(blocks reordered by spatial position)"
        )

    # Step 0b: compact walls (D-217) — move east/south walls inward,
    # dragging attached blocks. Modifies gap_cm and row_gaps_cm only.
    # Must run before normalize_intra/inter so that gaps of attached
    # blocks are reduced before being normalized to standard minimums.
    compact_walls(pattern, target_spacing)

    block_defs = build_block_defs(target_spacing)
    rows = pattern.get("rows", [])

    # Step 1a: normalize intra-row gaps
    gaps_changed = _normalize_intra_row_gaps(rows, block_defs, warnings)

    # Step 1b: normalize inter-row gaps
    row_gaps_changed = _normalize_inter_row_gaps(
        rows, pattern, block_defs, warnings,
    )

    # Update standard to target
    pattern["standard"] = new_standard

    # Step 2: fit room to pattern (recompute room dimensions)
    fit_result = fit_room_to_pattern(pattern, target_spacing)
    warnings.extend(fit_result.warnings)

    return NormalizeResult(
        name=pattern.get("name", "?"),
        gaps_changed=gaps_changed,
        row_gaps_changed=row_gaps_changed,
        fit=fit_result,
        old_standard=old_standard,
        new_standard=new_standard,
        warnings=warnings,
    )


def normalize_catalogue(
    patterns: list[dict],
    target_spacing: SpacingConfig,
) -> list[NormalizeResult]:
    """Normalize all patterns in a catalogue to the target standard.

    Mutates each pattern in place.

    Args:
        patterns: List of catalogue patterns (JSON dicts).
        target_spacing: Target spacing configuration.

    Returns:
        List of NormalizeResult, one per pattern.
    """
    results: list[NormalizeResult] = []
    for pat in patterns:
        try:
            result = normalize_pattern(pat, target_spacing)
            results.append(result)
        except PatternStructurallyInvalid as e:
            logger.warning(
                "Pattern '%s' structurally invalid after normalization: %s",
                pat.get("name", "?"), e,
            )
            results.append(NormalizeResult(
                name=pat.get("name", "?"),
                gaps_changed=0,
                row_gaps_changed=0,
                fit=FitResult(
                    old_width=pat.get("room_width_cm", 0),
                    old_depth=pat.get("room_depth_cm", 0),
                    new_width=pat.get("room_width_cm", 0),
                    new_depth=pat.get("room_depth_cm", 0),
                    direction="noop",
                ),
                old_standard=pat.get("standard", ""),
                new_standard=target_spacing.name,
                warnings=[f"Structurally invalid: {e}"],
            ))
    return results


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _normalize_intra_row_gaps(
    rows: list[dict],
    block_defs: dict[str, dict],
    warnings: list[str],
) -> int:
    """Normalize gap_cm between consecutive blocks within each row.

    For each pair of consecutive blocks (i, i+1) in a row:
      gap_cm[i+1] = east[i].total_cm + west[i+1].total_cm

    The first block's gap_cm is left unchanged (it is an offset from
    the origin, adjusted later by fit_room_to_pattern's translation).

    Returns:
        Number of gaps changed.
    """
    changed = 0
    for ri, row in enumerate(rows):
        blocks = row.get("blocks", [])
        if len(blocks) < 2:
            continue
        for bi in range(len(blocks) - 1):
            left = blocks[bi]
            right = blocks[bi + 1]

            left_fc = get_face_zones(
                left.get("type", ""),
                left.get("orientation", 0),
                block_defs,
            )
            right_fc = get_face_zones(
                right.get("type", ""),
                right.get("orientation", 0),
                block_defs,
            )

            required_gap = left_fc.east.total_cm + right_fc.west.total_cm
            current_gap = right.get("gap_cm", 0)

            if current_gap != required_gap:
                old_gap = current_gap
                right["gap_cm"] = required_gap
                changed += 1
                logger.debug(
                    "Row %d, blocks %d-%d: gap_cm %d -> %d",
                    ri, bi, bi + 1, old_gap, required_gap,
                )

    return changed


def _normalize_inter_row_gaps(
    rows: list[dict],
    pattern: dict,
    block_defs: dict[str, dict],
    warnings: list[str],
) -> int:
    """Normalize row_gaps_cm between consecutive rows (D-216).

    Uses pair-by-pair X-projection analysis: for each pair of blocks
    (b in row i, b' in row i+1), if their effective X footprints overlap,
    a vertical clearance constraint is imposed.

    Effective X footprint includes west_zone and east_zone (face zones),
    but NOT desk_to_wall fallback (irrelevant for inter-block spacing).

    Formula per overlapping pair:
      pair_required = offset_ns[b] + ns[b] + south_zone[b].total_cm
                    - max_ns_upper - offset_ns[b'] + north_zone[b'].total_cm

    Where max_ns_upper = max(ns_cm) over all blocks in row i.

    Returns:
        Number of row gaps changed.
    """
    row_gaps = pattern.get("row_gaps_cm", [])
    if not row_gaps:
        return 0

    # Compute block positions once (uses current gap_cm values, post intra-row
    # normalization). Positions give us x_cm, eo_cm, ns_cm per block.
    positions = compute_block_positions(pattern)

    # Group positions by row_idx
    rows_positions: dict[int, list] = {}
    for bp in positions:
        rows_positions.setdefault(bp.row_idx, []).append(bp)

    # Compute max_ns per row (same logic as compute_block_positions uses
    # to advance row_y).
    max_ns_per_row: dict[int, int] = {}
    for ri, bps in rows_positions.items():
        max_ns_per_row[ri] = max((bp.ns_cm for bp in bps), default=0)

    changed = 0

    for gi in range(len(row_gaps)):
        if gi >= len(rows) - 1:
            break

        upper_positions = rows_positions.get(gi, [])
        lower_positions = rows_positions.get(gi + 1, [])

        if not upper_positions or not lower_positions:
            # No pairs to check — gap should be 0
            required_gap = 0
        else:
            max_ns_upper = max_ns_per_row.get(gi, 0)
            required_gap = _compute_pair_required_gap(
                upper_positions, lower_positions,
                rows, gi, block_defs, max_ns_upper, warnings,
            )

        current_gap = row_gaps[gi]
        if current_gap != required_gap:
            old_gap = current_gap
            row_gaps[gi] = required_gap
            changed += 1
            logger.debug(
                "Row gap %d: %d -> %d (pair-by-pair X projection)",
                gi, old_gap, required_gap,
            )

    pattern["row_gaps_cm"] = row_gaps
    return changed


def _compute_pair_required_gap(
    upper_positions: list,
    lower_positions: list,
    rows: list[dict],
    gi: int,
    block_defs: dict[str, dict],
    max_ns_upper: int,
    warnings: list[str],
) -> int:
    """Compute required row_gap for row pair (gi, gi+1) via X projection.

    For each pair (b, b') where effective X footprints overlap,
    computes the minimum row_gap to prevent vertical collision.

    Args:
        upper_positions: BlockPositions in row gi.
        lower_positions: BlockPositions in row gi+1.
        rows: Pattern rows (JSON).
        gi: Row gap index (between row gi and gi+1).
        block_defs: Block definitions for the target standard.
        max_ns_upper: max(ns_cm) over blocks in row gi.
        warnings: Accumulated warnings list (mutated).

    Returns:
        Required gap (>= 0).
    """
    upper_row_blocks = rows[gi].get("blocks", [])
    lower_row_blocks = rows[gi + 1].get("blocks", [])

    max_required = 0

    for bp_upper in upper_positions:
        block_upper = upper_row_blocks[bp_upper.block_idx]
        fc_upper = get_face_zones(
            bp_upper.block_type, bp_upper.orientation, block_defs,
        )
        offset_ns_upper = block_upper.get("offset_ns_cm", 0)

        # Effective X footprint (body + EW face zones)
        x_min_upper = bp_upper.x_cm - fc_upper.west.total_cm
        x_max_upper = bp_upper.x_cm + bp_upper.eo_cm + fc_upper.east.total_cm

        # Extreme offset warning for upper block
        _check_extreme_offset(
            offset_ns_upper, bp_upper.ns_cm, max_ns_upper,
            gi, bp_upper.block_idx, warnings,
        )

        for bp_lower in lower_positions:
            block_lower = lower_row_blocks[bp_lower.block_idx]
            fc_lower = get_face_zones(
                bp_lower.block_type, bp_lower.orientation, block_defs,
            )
            offset_ns_lower = block_lower.get("offset_ns_cm", 0)

            # Effective X footprint (body + EW face zones)
            x_min_lower = bp_lower.x_cm - fc_lower.west.total_cm
            x_max_lower = (
                bp_lower.x_cm + bp_lower.eo_cm + fc_lower.east.total_cm
            )

            # X overlap check
            if max(x_min_upper, x_min_lower) >= min(x_max_upper, x_max_lower):
                continue  # No X overlap — no vertical constraint

            # Vertical constraint: bottom[b] <= top[b']
            pair_required = (
                offset_ns_upper + bp_upper.ns_cm
                + fc_upper.south.total_cm
                - max_ns_upper
                - offset_ns_lower
                + fc_lower.north.total_cm
            )
            max_required = max(max_required, pair_required)

    # Extreme offset warnings for lower row blocks
    max_ns_lower = max((bp.ns_cm for bp in lower_positions), default=0)
    for bp_lower in lower_positions:
        block_lower = lower_row_blocks[bp_lower.block_idx]
        offset_ns_lower = block_lower.get("offset_ns_cm", 0)
        _check_extreme_offset(
            offset_ns_lower, bp_lower.ns_cm, max_ns_lower,
            gi + 1, bp_lower.block_idx, warnings,
        )

    return max(0, max_required)


def _check_extreme_offset(
    offset_ns: int,
    ns_cm: int,
    max_ns_row: int,
    row_idx: int,
    block_idx: int,
    warnings: list[str],
) -> None:
    """Emit warning if offset_ns_cm is extreme.

    Criteria:
    - Block extends more than _EXTREME_OFFSET_THRESHOLD_CM beyond row depth.
    - Block rises more than _EXTREME_OFFSET_THRESHOLD_CM above row origin.
    """
    extends_below = offset_ns + ns_cm - max_ns_row
    if extends_below > _EXTREME_OFFSET_THRESHOLD_CM:
        warnings.append(
            f"Block at row {row_idx}, idx {block_idx} has extreme "
            f"offset_ns_cm {offset_ns} (block extends {extends_below} cm "
            f"beyond row depth)"
        )
    if offset_ns < -_EXTREME_OFFSET_THRESHOLD_CM:
        warnings.append(
            f"Block at row {row_idx}, idx {block_idx} has extreme "
            f"offset_ns_cm {offset_ns} (block rises {-offset_ns} cm "
            f"above row origin)"
        )
