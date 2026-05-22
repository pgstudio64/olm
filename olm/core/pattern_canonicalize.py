"""Pattern canonicalization and row inference from absolute positions.

D-213: blocks in a row may be stored in JSON in an order that does not
match their spatial left-to-right position (e.g. via negative gap_cm).
This module reorders blocks by ascending x_cm and recomputes gap_cm
so that the pattern's spatial layout is preserved but the JSON order
matches the visual order.

D-267: ``infer_rows_from_positions`` rebuilds ``rows[]`` + ``row_gaps_cm``
from a flat list of blocks with absolute positions, using vertical-overlap
clustering (Union-Find, transitive closure).

Canonical form guarantees:
- blocks sorted by ascending x_cm within each row
- gap_cm[0] = x_cm of the first block (distance from origin)
- gap_cm[i] = x_cm[i] - (x_cm[i-1] + eo_effective[i-1])  for i > 0
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from olm.core.catalogue_matcher import (
    BlockPosition,
    _block_ns_extent,
    compute_block_positions,
)

logger = logging.getLogger(__name__)

# Minimum vertical overlap (fraction of the smaller body height) for two
# blocks to be considered in the same row.  D-267 §3.1.
ROW_CLUSTER_OVERLAP_RATIO = 0.5


@dataclass
class CanonicalizeResult:
    """Result of a canonicalize operation.

    Attributes:
        n_reorderings: Number of rows whose block order changed.
    """

    n_reorderings: int


# ---------------------------------------------------------------------------
# Shared helper — recompute gap_cm from sorted (x_cm, eo_cm) positions
# ---------------------------------------------------------------------------

def _recompute_gaps(
    blocks: list[dict],
    sorted_positions: list[tuple[int, int]],
) -> None:
    """Rewrite ``gap_cm`` on *blocks* to match *sorted_positions*.

    Args:
        blocks: Block dicts (mutated in place). Must be in the same order
            as *sorted_positions*.
        sorted_positions: ``[(x_cm, eo_cm), ...]`` sorted by ``x_cm``.
    """
    for i, (x_cm, eo_cm) in enumerate(sorted_positions):
        if i == 0:
            # D-268: allow negative gap (block outside room to the west)
            blocks[i]["gap_cm"] = x_cm
        else:
            prev_x, prev_eo = sorted_positions[i - 1]
            blocks[i]["gap_cm"] = max(0, x_cm - (prev_x + prev_eo))


# ---------------------------------------------------------------------------
# Canonicalize — D-213
# ---------------------------------------------------------------------------

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

        # Collect (x_cm, eo_cm, block_idx) for each block in this row
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
        sorted_xy = [(x, eo) for x, eo, _ in row_positions]
        _recompute_gaps(sorted_blocks, sorted_xy)

        row["blocks"] = sorted_blocks
        n_reorderings += 1
        logger.debug(
            "Row %d: reordered blocks %s -> %s",
            ri, list(range(len(blocks))), current_order,
        )

    return CanonicalizeResult(n_reorderings=n_reorderings)


# ---------------------------------------------------------------------------
# Infer rows from absolute positions — D-267
# ---------------------------------------------------------------------------

def _body_extent(block: dict) -> tuple[int, int]:
    """Return (eo_cm, ns_cm) of the block body at its orientation."""
    from olm.core.catalogue_matcher import _BLOCK_REGISTRY
    btype = block.get("type", "")
    orient = block.get("orientation", 0)
    eo, ns, _ = _BLOCK_REGISTRY.get(btype, (0, 0, 0))
    if orient in (90, 270):
        return ns, eo
    return eo, ns


def _uf_find(parent: list[int], i: int) -> int:
    """Union-Find: find with path compression."""
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _uf_union(parent: list[int], rank: list[int], a: int, b: int) -> None:
    """Union-Find: union by rank."""
    ra, rb = _uf_find(parent, a), _uf_find(parent, b)
    if ra == rb:
        return
    if rank[ra] < rank[rb]:
        ra, rb = rb, ra
    parent[rb] = ra
    if rank[ra] == rank[rb]:
        rank[ra] += 1


@dataclass
class InferRowsResult:
    """Result of ``infer_rows_from_positions``.

    Attributes:
        rows: Rebuilt list of row dicts.
        row_gaps_cm: Rebuilt inter-row gaps.
        n_rows: Number of rows after inference.
    """
    rows: list[dict]
    row_gaps_cm: list[int]
    n_rows: int


def infer_rows_from_positions(
    blocks: list[dict],
) -> InferRowsResult:
    """Rebuild rows/row_gaps_cm from a flat list of blocks with absolute positions.

    Each block dict must contain at least:
    - ``type``, ``orientation`` (block identity)
    - ``x_cm``, ``y_cm`` (absolute position, NW corner of body)
    - any other attributes (``sticks``, ``offset_ns_cm``, …) are preserved.

    The ``offset_ns_cm`` field is **rewritten** (relative to the new row
    baseline).  ``gap_cm`` is **rewritten** to encode inter-block spacing.

    Algorithm (D-267 §3):
    1. Cluster blocks into rows by vertical body overlap (Union-Find,
       transitive closure, threshold = 50 % of smaller body height).
    2. Sort rows top-to-bottom (by minimum y), blocks left-to-right (by x).
    3. Recompute gap_cm, offset_ns_cm, row_gaps_cm for exact round-trip.

    Args:
        blocks: Flat list of block dicts with absolute positions.

    Returns:
        InferRowsResult with rebuilt rows and row_gaps_cm.
    """
    n = len(blocks)
    if n == 0:
        return InferRowsResult(rows=[], row_gaps_cm=[], n_rows=0)

    # -- 1. Compute body extents and y-intervals --
    extents = []  # (eo_cm, ns_cm)
    y_intervals = []  # (y_top, y_bottom)
    for b in blocks:
        eo, ns = _body_extent(b)
        y_top = b["y_cm"]
        y_bot = y_top + ns
        extents.append((eo, ns))
        y_intervals.append((y_top, y_bot))

    # -- 2. Union-Find clustering by vertical overlap --
    parent = list(range(n))
    rank = [0] * n

    for i in range(n):
        for j in range(i + 1, n):
            top_i, bot_i = y_intervals[i]
            top_j, bot_j = y_intervals[j]
            overlap = max(0, min(bot_i, bot_j) - max(top_i, top_j))
            min_h = min(extents[i][1], extents[j][1])
            if min_h > 0 and overlap >= ROW_CLUSTER_OVERLAP_RATIO * min_h:
                _uf_union(parent, rank, i, j)

    # -- 3. Group blocks by cluster --
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = _uf_find(parent, i)
        clusters.setdefault(root, []).append(i)

    # -- 4. Sort clusters top-to-bottom (by min y_top) --
    sorted_clusters = sorted(
        clusters.values(),
        key=lambda idxs: min(y_intervals[i][0] for i in idxs),
    )

    # -- 5. Build rows --
    result_rows: list[dict] = []
    row_baselines: list[int] = []

    for ci, cluster_idxs in enumerate(sorted_clusters):
        # Sort blocks left-to-right within the cluster
        cluster_idxs.sort(key=lambda i: blocks[i]["x_cm"])

        # Baseline convention (D-267 §3.3):
        # Row 0 baseline = 0  (y_abs of blocks expressed as offset_ns)
        # Row i>0 baseline = min(y_abs) in the row
        if ci == 0:
            baseline = 0
        else:
            baseline = min(blocks[i]["y_cm"] for i in cluster_idxs)
        row_baselines.append(baseline)

        # Build row blocks with recomputed gap_cm and offset_ns_cm
        row_blocks: list[dict] = []
        sorted_xy: list[tuple[int, int]] = []
        for idx in cluster_idxs:
            b = blocks[idx]
            eo, ns = extents[idx]
            # Copy all attributes except x_cm/y_cm (absolute) and
            # gap_cm/offset_ns_cm (recomputed)
            new_block = {}
            for k, v in b.items():
                if k in ("x_cm", "y_cm", "gap_cm", "offset_ns_cm"):
                    continue
                new_block[k] = v
            new_block["offset_ns_cm"] = b["y_cm"] - baseline
            row_blocks.append(new_block)
            sorted_xy.append((b["x_cm"], eo))

        _recompute_gaps(row_blocks, sorted_xy)
        result_rows.append({"blocks": row_blocks})

    # -- 6. Compute row_gaps_cm --
    # The decode (compute_block_positions) advances row_y by max body NS
    # (_block_ns_extent, WITHOUT offset_ns). Row gaps must be measured from
    # baseline + max(body ns), NOT from max(y_abs + ns): using y_abs+ns would
    # over-count a block's positive offset and shift the next row up on
    # re-decode, breaking idempotence (D-267).
    row_gaps: list[int] = []
    for ci in range(len(sorted_clusters) - 1):
        row_max_ns = max(extents[idx][1] for idx in sorted_clusters[ci])
        row_bottom = row_baselines[ci] + row_max_ns
        row_top = row_baselines[ci + 1]
        # D-268: allow negative row_gap (block outside room to the north
        # pushes baseline of row 0 below the top of row 1)
        row_gaps.append(row_top - row_bottom)

    return InferRowsResult(
        rows=result_rows,
        row_gaps_cm=row_gaps,
        n_rows=len(result_rows),
    )
