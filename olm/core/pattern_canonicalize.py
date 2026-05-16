"""Pattern canonicalization — sort blocks by spatial order within each row.

D-213: blocks in a row may be stored in JSON in an order that does not
match their spatial left-to-right position (e.g. via negative gap_cm).
This module reorders blocks by ascending x_cm and recomputes gap_cm
so that the pattern's spatial layout is preserved but the JSON order
matches the visual order.

Canonical form guarantees:
- blocks sorted by ascending x_cm within each row
- gap_cm[0] = x_cm of the first block (distance from origin)
- gap_cm[i] = x_cm[i] - (x_cm[i-1] + eo_effective[i-1])  for i > 0
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from olm.core.catalogue_matcher import compute_block_positions

logger = logging.getLogger(__name__)


@dataclass
class CanonicalizeResult:
    """Result of a canonicalize operation.

    Attributes:
        n_reorderings: Number of rows whose block order changed.
    """

    n_reorderings: int


def canonicalize_blocks(pattern: dict) -> CanonicalizeResult:
    """Sort blocks within each row by ascending x_cm, recompute gap_cm.

    Mutates ``pattern`` in place. Preserves all block attributes
    (type, orientation, offset_ns_cm, sticks, etc.) — only the order
    in the ``blocks`` list and ``gap_cm`` values change.

    Args:
        pattern: Catalogue pattern (JSON dict). Mutated in place.

    Returns:
        CanonicalizeResult with the number of rows reordered.
    """
    positions = compute_block_positions(pattern)
    rows = pattern.get("rows", [])
    n_reorderings = 0

    for ri, row in enumerate(rows):
        blocks = row.get("blocks", [])
        if len(blocks) <= 1:
            continue

        # Collect (x_cm, eo_cm) for each block in this row
        row_positions = [
            (bp.x_cm, bp.eo_cm, bp.block_idx)
            for bp in positions
            if bp.row_idx == ri
        ]
        row_positions.sort(key=lambda t: t[0])

        # Check if reordering is needed
        current_order = [t[2] for t in row_positions]
        if current_order == list(range(len(blocks))):
            continue

        # Reorder blocks and recompute gap_cm
        sorted_blocks = [blocks[t[2]] for t in row_positions]
        for i, (x_cm, eo_cm, _orig_idx) in enumerate(row_positions):
            if i == 0:
                sorted_blocks[i]["gap_cm"] = x_cm
            else:
                prev_x, prev_eo, _ = row_positions[i - 1]
                sorted_blocks[i]["gap_cm"] = x_cm - (prev_x + prev_eo)

        row["blocks"] = sorted_blocks
        n_reorderings += 1
        logger.debug(
            "Row %d: reordered blocks %s -> %s",
            ri, list(range(len(blocks))), current_order,
        )

    return CanonicalizeResult(n_reorderings=n_reorderings)
