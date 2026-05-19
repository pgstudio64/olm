"""Catalogue pattern matching against real rooms.

Pipeline (7 steps):
    1. Selection: footprint <= room + Pareto front (width, depth)
    2. East-West mirror
    3. Stick clamping + homothety
    4. Individual desk removal in forbidden zones
    5. Scoring (circulation + comfort + multi-dim grade D-238)
    6. Best selection per standard
    7. Residual free rectangle

Module: cross-matching 3 standards x target rooms.
"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
from dataclasses import dataclass

from olm.core.app_config import get_standard_label
from olm.core.pattern_generator import (
    BLOCK_1,
    BLOCK_2_FACE,
    BLOCK_2_ORTHO_L,
    BLOCK_2_ORTHO_R,
    BLOCK_2_SIDE,
    BLOCK_3_SIDE,
    BLOCK_4_FACE,
    BLOCK_6_FACE,
    DESK_D_CM,
    DESK_W_CM,
)
from olm.core.room_model import RoomSpec
from olm.core.spacing_config import ALL_CONFIGS

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Catalogue lives in project/catalogue/ (business data, not in generic core)
_PROJECT_DIR = os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), "project")
CATALOGUE_PATH = os.path.join(_PROJECT_DIR, "catalogue", "patterns.json")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PatternCandidate:
    """Pattern candidate from the selection step.

    Attributes:
        pattern: Raw JSON pattern data.
        name: Pattern name.
        room_width_cm: Pattern room width.
        room_depth_cm: Pattern room depth.
        standard: Layout standard.
        n_desks: Total number of desks.
    """
    pattern: dict
    name: str
    room_width_cm: int
    room_depth_cm: int
    standard: str
    n_desks: int
    oversize: bool = False


@dataclass
class SelectionResult:
    """Selection result for a given standard.

    Attributes:
        standard: Standard name.
        candidates: Patterns on the Pareto front.
        all_fitting: All patterns whose footprint fits (before Pareto).
    """
    standard: str
    candidates: list[PatternCandidate]
    all_fitting: list[PatternCandidate]


# ---------------------------------------------------------------------------
# Catalogue loading
# ---------------------------------------------------------------------------

def load_catalogue(path: str = CATALOGUE_PATH) -> list[dict]:
    """Load the pattern catalogue from the JSON file.

    Args:
        path: Path to the catalogue file.

    Returns:
        List of patterns (JSON dicts).
    """
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("patterns", [])


# ---------------------------------------------------------------------------
# Desk counting
# ---------------------------------------------------------------------------

# Canonical dimensions (eo_cm, ns_cm) and desk count per block type
_BLOCK_REGISTRY = {
    "BLOCK_1":          (BLOCK_1.eo_cm, BLOCK_1.ns_cm, 1),
    "BLOCK_2_FACE":     (BLOCK_2_FACE.eo_cm, BLOCK_2_FACE.ns_cm, 2),
    "BLOCK_2_SIDE":     (BLOCK_2_SIDE.eo_cm, BLOCK_2_SIDE.ns_cm, 2),
    "BLOCK_3_SIDE":     (BLOCK_3_SIDE.eo_cm, BLOCK_3_SIDE.ns_cm, 3),
    "BLOCK_4_FACE":     (BLOCK_4_FACE.eo_cm, BLOCK_4_FACE.ns_cm, 4),
    "BLOCK_6_FACE":     (BLOCK_6_FACE.eo_cm, BLOCK_6_FACE.ns_cm, 6),
    "BLOCK_2_ORTHO_R":  (BLOCK_2_ORTHO_R.eo_cm, BLOCK_2_ORTHO_R.ns_cm, 2),
    "BLOCK_2_ORTHO_L":  (BLOCK_2_ORTHO_L.eo_cm, BLOCK_2_ORTHO_L.ns_cm, 2),
}

_BLOCK_N_DESKS = {k: v[2] for k, v in _BLOCK_REGISTRY.items()}

# Ortho block types (mirror = swap R↔L)
_ORTHO_MIRROR = {
    "BLOCK_2_ORTHO_R": "BLOCK_2_ORTHO_L",
    "BLOCK_2_ORTHO_L": "BLOCK_2_ORTHO_R",
}


def count_desks(pattern: dict) -> int:
    """Count the total number of desks in a JSON pattern.

    Args:
        pattern: Pattern in catalogue JSON format.

    Returns:
        Number of desks.
    """
    total = 0
    for row in pattern.get("rows", []):
        for block in row.get("blocks", []):
            btype = block.get("type", "")
            total += _BLOCK_N_DESKS.get(btype, 0)
    return total


# ---------------------------------------------------------------------------
# Step 1 — Selection + Pareto front
# ---------------------------------------------------------------------------

def effective_dimensions(room: RoomSpec) -> tuple[int, int]:
    """Compute the effective dimensions of a room after peripheral exclusions.

    A peripheral exclusion runs along a full wall width or depth and reduces
    the corresponding effective dimension.

    Returns:
        (effective_width_cm, effective_depth_cm)
    """
    ew = room.width_cm
    ed = room.depth_cm

    for z in room.exclusion_zones:
        # North strip: y=0, covers full width
        if z.y_cm == 0 and z.x_cm == 0 and z.width_cm >= room.width_cm:
            ed -= z.depth_cm
        # South strip: y + depth = room depth, covers full width
        elif (z.y_cm + z.depth_cm >= room.depth_cm
              and z.x_cm == 0 and z.width_cm >= room.width_cm):
            ed -= z.depth_cm
        # West strip: x=0, covers full depth
        elif z.x_cm == 0 and z.y_cm == 0 and z.depth_cm >= room.depth_cm:
            ew -= z.width_cm
        # East strip: x + width = room width, covers full depth
        elif (z.x_cm + z.width_cm >= room.width_cm
              and z.y_cm == 0 and z.depth_cm >= room.depth_cm):
            ew -= z.width_cm

    return max(0, ew), max(0, ed)


def _fits_in_room(
    pattern: dict,
    room: RoomSpec,
    spacing: "SpacingConfig | None" = None,
) -> bool:
    """Check whether the pattern's real footprint fits the target room.

    D-242: uses ``compute_pattern_footprint`` (real emprise including
    face zones and door obstacles) instead of declared room dimensions.
    Compares footprint width/depth to effective room dimensions.

    Args:
        spacing: Spacing config for the pattern's standard. If None,
            falls back to declared room dimensions.
    """
    ew, ed = effective_dimensions(room)
    if spacing is not None:
        from olm.core.pattern_fit import compute_pattern_footprint
        try:
            x_min, x_max, y_min, y_max = compute_pattern_footprint(
                pattern, spacing,
            )
        except Exception:
            return False
        fp_w = x_max - x_min
        fp_d = y_max - y_min
        return fp_w <= ew and fp_d <= ed
    # Fallback: declared dimensions
    pw = pattern.get("room_width_cm", 0)
    pd = pattern.get("room_depth_cm", 0)
    return pw <= ew and pd <= ed


def _is_dominated(p: PatternCandidate, others: list[PatternCandidate]) -> bool:
    """Check whether p is dominated by at least one other candidate.

    Pattern P1 dominates P2 if:
        P1.room_width_cm >= P2.room_width_cm AND
        P1.room_depth_cm >= P2.room_depth_cm AND
        at least one inequality is strict.
    """
    for o in others:
        if o is p:
            continue
        if (o.room_width_cm >= p.room_width_cm
                and o.room_depth_cm >= p.room_depth_cm
                and (o.room_width_cm > p.room_width_cm
                     or o.room_depth_cm > p.room_depth_cm)):
            return True
    return False


def pareto_front(candidates: list[PatternCandidate]) -> list[PatternCandidate]:
    """Extract the Pareto front on (width, depth).

    Patterns dominated in both width AND depth by another are excluded.

    Args:
        candidates: List of candidates whose footprint fits in the room.

    Returns:
        Sub-list of non-dominated candidates.
    """
    if len(candidates) <= 1:
        return list(candidates)
    return [p for p in candidates if not _is_dominated(p, candidates)]


def select_candidates(
    catalogue: list[dict],
    room: RoomSpec,
    standard: str | None = None,
) -> SelectionResult | list[SelectionResult]:
    """Select candidate patterns for a target room.

    Filters by footprint (<= room) then extracts the Pareto front.
    If standard is specified, returns a single SelectionResult.
    Otherwise returns a list of 3 SelectionResult (one per standard).

    Args:
        catalogue: JSON patterns from the catalogue.
        room: Target room.
        standard: Layout standard (None = all 3).

    Returns:
        SelectionResult or list of SelectionResult.
    """
    standards = [standard] if standard else list(ALL_CONFIGS.keys())
    results = []

    for std in standards:
        spacing = ALL_CONFIGS.get(std)
        fitting = []
        oversize_extra = []
        for p in catalogue:
            if p.get("standard") != std:
                continue
            # D-242: no hard filter — all patterns of the target standard
            # are proposed. Oversize classification uses real footprint.
            exact = _fits_in_room(p, room, spacing)
            candidate = PatternCandidate(
                pattern=p,
                name=p["name"],
                room_width_cm=p["room_width_cm"],
                room_depth_cm=p["room_depth_cm"],
                standard=std,
                n_desks=count_desks(p),
                oversize=not exact,
            )
            if exact:
                fitting.append(candidate)
            else:
                oversize_extra.append(candidate)

        front = pareto_front(fitting)
        # Sort by desk count descending
        front.sort(key=lambda c: c.n_desks, reverse=True)
        # Append oversize candidates after the Pareto front
        oversize_extra.sort(key=lambda c: c.n_desks, reverse=True)

        results.append(SelectionResult(
            standard=std,
            candidates=front + oversize_extra,
            all_fitting=fitting + oversize_extra,
        ))

        logger.debug(
            "Selection %s: %d fit, %d oversize, %d on Pareto front",
            std, len(fitting), len(oversize_extra), len(front),
        )

    if standard:
        return results[0]
    return results


# ---------------------------------------------------------------------------
# Step 2 — East-West mirror
# ---------------------------------------------------------------------------

def _block_eo_extent(block: dict) -> int:
    """EO width of a block at its current orientation.

    Args:
        block: JSON block with 'type' and 'orientation'.

    Returns:
        Width in cm along the EO axis.
    """
    btype = block.get("type", "")
    orient = block.get("orientation", 0)
    eo, ns, _ = _BLOCK_REGISTRY.get(btype, (0, 0, 0))
    if orient in (90, 270):
        return ns
    return eo


def _mirror_block(block: dict) -> dict:
    """East-West mirror of an individual block.

    - Ortho types: ORTHO_R <-> ORTHO_L, orientation = (360 - theta) % 360
    - Other blocks: orientation = (180 - theta) % 360
    - Sticks: E <-> O
    - offset_ns_cm unchanged

    Args:
        block: Original JSON block.

    Returns:
        New mirrored block dict.
    """
    b = copy.deepcopy(block)
    btype = b.get("type", "")
    orient = b.get("orientation", 0)

    # Swap type ortho
    if btype in _ORTHO_MIRROR:
        b["type"] = _ORTHO_MIRROR[btype]
        b["orientation"] = (360 - orient) % 360
    else:
        b["orientation"] = (180 - orient) % 360

    # Swap sticks E <-> W. Legacy "O" (west alias) is normalized to "W".
    if "sticks" in b:
        _STICK_MIRROR = {"E": "W", "W": "E", "O": "E", "N": "N", "S": "S"}
        b["sticks"] = [_STICK_MIRROR.get(s, s) for s in b["sticks"]]

    return b


def _mirror_row(row: dict, room_width_cm: int) -> dict:
    """East-West mirror of a block row.

    Reverses block order and recalculates gaps.

    Args:
        row: JSON row {"blocks": [...]}.
        room_width_cm: Room width.

    Returns:
        New mirrored row.
    """
    blocks = row.get("blocks", [])
    if not blocks:
        return copy.deepcopy(row)

    # Compute absolute position of each block
    positions = []  # (x_start, width)
    x = 0
    for block in blocks:
        gap = block.get("gap_cm", 0)
        w = _block_eo_extent(block)
        x += gap
        positions.append((x, w))
        x += w

    # Residual space on the right
    remaining_right = room_width_cm - x

    # Mirror: reversed order, reflected positions
    mirrored_blocks = []
    n = len(blocks)
    prev_right = 0

    for i in range(n - 1, -1, -1):
        orig_x, orig_w = positions[i]
        # Mirror position of the block
        mirror_x = room_width_cm - orig_x - orig_w
        gap = mirror_x - prev_right
        mirrored_block = _mirror_block(blocks[i])
        mirrored_block["gap_cm"] = gap
        mirrored_blocks.append(mirrored_block)
        prev_right = mirror_x + orig_w

    return {"blocks": mirrored_blocks}


def _mirror_windows(windows: list[dict], room_width_cm: int) -> list[dict]:
    """East-West mirror of windows."""
    result = []
    for w in windows:
        mw = copy.deepcopy(w)
        face = mw.get("face", "")
        if face in ("north", "south"):
            mw["offset_cm"] = room_width_cm - mw["offset_cm"] - mw["width_cm"]
        elif face == "east":
            mw["face"] = "west"
        elif face == "west":
            mw["face"] = "east"
        result.append(mw)
    return result


def _mirror_openings(openings: list[dict], room_width_cm: int) -> list[dict]:
    """East-West mirror of openings (doors)."""
    result = []
    for o in openings:
        mo = copy.deepcopy(o)
        face = mo.get("face", "")
        if face in ("north", "south"):
            mo["offset_cm"] = room_width_cm - mo["offset_cm"] - mo["width_cm"]
        elif face == "east":
            mo["face"] = "west"
        elif face == "west":
            mo["face"] = "east"
        # Swap hinge side
        hs = mo.get("hinge_side", "left")
        mo["hinge_side"] = "right" if hs == "left" else "left"
        result.append(mo)
    return result


def _mirror_exclusions(
    exclusions: list[dict], room_width_cm: int,
) -> list[dict]:
    """East-West mirror of exclusion zones."""
    result = []
    for z in exclusions:
        mz = copy.deepcopy(z)
        mz["x_cm"] = room_width_cm - z["x_cm"] - z["width_cm"]
        result.append(mz)
    return result


def mirror_pattern(pattern: dict) -> dict:
    """Generate the East-West mirror of a pattern.

    The mirror reflects the pattern around the vertical central axis:
    - Blocks: reversed order per row, gaps recalculated
    - Ortho types: R <-> L
    - Orientations adjusted
    - Sticks: E <-> O
    - Room geometry: mirrored offsets, hinge_side reversed

    Args:
        pattern: Original JSON pattern.

    Returns:
        New mirrored pattern dict, suffixed '_MIR'.
    """
    room_w = pattern.get("room_width_cm", 0)
    mirrored = copy.deepcopy(pattern)
    mirrored["name"] = pattern["name"] + "_MIR"

    # Mirror rows
    mirrored["rows"] = [
        _mirror_row(row, room_w) for row in pattern.get("rows", [])
    ]

    # Mirror room geometry
    if "room_windows" in pattern:
        mirrored["room_windows"] = _mirror_windows(
            pattern["room_windows"], room_w,
        )
    if "room_openings" in pattern:
        mirrored["room_openings"] = _mirror_openings(
            pattern["room_openings"], room_w,
        )
    if "room_exclusions" in pattern:
        mirrored["room_exclusions"] = _mirror_exclusions(
            pattern["room_exclusions"], room_w,
        )

    return mirrored


# ---------------------------------------------------------------------------
# Step 3 — Stick clamping + homothety
# ---------------------------------------------------------------------------

_STICK_O = frozenset({"O", "W"})


def _block_ns_extent(block: dict) -> int:
    """NS height of a block at its current orientation."""
    btype = block.get("type", "")
    orient = block.get("orientation", 0)
    eo, ns, _ = _BLOCK_REGISTRY.get(btype, (0, 0, 0))
    if orient in (90, 270):
        return eo
    return ns


def _ns_intervals_overlap(b1: dict, b2: dict) -> bool:
    """True if two blocks' NS intervals overlap (= cannot share an EO span)."""
    y1 = b1.get("offset_ns_cm", 0)
    y1e = y1 + _block_ns_extent(b1)
    y2 = b2.get("offset_ns_cm", 0)
    y2e = y2 + _block_ns_extent(b2)
    return y1 < y2e and y2 < y1e


def _adapt_row_eo(
    row: dict, orig_width: int, target_width: int,
) -> dict:
    """Adapt a row to a target room width.

    Algorithm:
    - Blocks with stick O: fixed position (distance to west wall preserved)
    - Blocks with stick E: shifted by dw (distance to east wall preserved)
    - Blocks without EO stick: linear interpolation between neighbouring anchors
    - No anchor: positions unchanged (extra space on the right)

    Args:
        row: Original JSON row.
        orig_width: Pattern room width.
        target_width: Target room width.

    Returns:
        New row with adapted gaps.
    """
    dw = target_width - orig_width
    blocks = row.get("blocks", [])
    if not blocks or dw == 0:
        return copy.deepcopy(row)

    # Original absolute positions
    positions = []  # (x_start, width)
    x = 0
    for b in blocks:
        x += b.get("gap_cm", 0)
        w = _block_eo_extent(b)
        positions.append((x, w))
        x += w

    # Anchors: (index, new_x)
    anchors = []
    for i, b in enumerate(blocks):
        sticks = set(b.get("sticks", []))
        if sticks & _STICK_O:
            anchors.append((i, positions[i][0]))
        elif "E" in sticks:
            anchors.append((i, positions[i][0] + dw))

    # New positions
    new_x = [positions[i][0] for i in range(len(blocks))]

    if not anchors:
        pass  # No anchor -> positions unchanged, extra space on the right
    elif len(anchors) == 1:
        idx, ax = anchors[0]
        shift = ax - positions[idx][0]
        for i in range(len(blocks)):
            new_x[i] = positions[i][0] + shift
    else:
        anchors.sort()
        for idx, ax in anchors:
            new_x[idx] = ax

        # Before first anchor: same shift
        first_idx, first_ax = anchors[0]
        shift_left = first_ax - positions[first_idx][0]
        for i in range(first_idx):
            new_x[i] = positions[i][0] + shift_left

        # After last anchor: same shift
        last_idx, last_ax = anchors[-1]
        shift_right = last_ax - positions[last_idx][0]
        for i in range(last_idx + 1, len(blocks)):
            new_x[i] = positions[i][0] + shift_right

        # Between consecutive anchors: linear interpolation
        for a in range(len(anchors) - 1):
            li, lx = anchors[a]
            ri, rx = anchors[a + 1]
            orig_span = positions[ri][0] - positions[li][0]
            new_span = rx - lx
            for i in range(li + 1, ri):
                if orig_span > 0:
                    frac = (positions[i][0] - positions[li][0]) / orig_span
                    new_x[i] = lx + frac * new_span
                else:
                    new_x[i] = lx

    # Recalculate gaps. D-224: allow a negative gap when block i shares its EO
    # span with a previous block but does NOT overlap NS (single-row compressed
    # pattern with offset_ns_cm). Without this, max(0, ...) corrupts the layout
    # — the block is pushed by prev_right instead of staying at its target x.
    new_blocks = []
    prev_right = 0
    for i in range(len(blocks)):
        bi_x = int(round(new_x[i]))
        bi_eo = positions[i][1]
        raw_gap = bi_x - prev_right
        if raw_gap < 0 and not any(
            _ns_intervals_overlap(blocks[i], blocks[j])
            and bi_x < int(round(new_x[j])) + positions[j][1]
            and int(round(new_x[j])) < bi_x + bi_eo
            for j in range(i)
        ):
            gap = raw_gap  # legitimate negative gap (no EO+NS collision)
        else:
            gap = max(0, raw_gap)
        nb = copy.deepcopy(blocks[i])
        nb["gap_cm"] = gap
        new_blocks.append(nb)
        prev_right = max(prev_right, bi_x + bi_eo)

    return {"blocks": new_blocks}


def _adapt_ns(
    pattern: dict, orig_depth: int, target_depth: int,
) -> dict:
    """Adapt the NS dimension of a pattern to the target room.

    Distribution of extra space dd:
    - Rows with at least one N-stick block: NS position preserved
    - Rows with at least one S-stick block: shifted by dd
    - Rows without NS stick: interpolation or proportional distribution
    - Single row: offset_ns_cm of N/S-stick blocks adjusted, otherwise
      extra space distributed across row_gaps_cm

    Args:
        pattern: Adapted JSON pattern (width already adjusted).
        orig_depth: Pattern room depth.
        target_depth: Target room depth.

    Returns:
        Pattern with adjusted row_gaps_cm and offset_ns_cm.
    """
    dd = target_depth - orig_depth
    p = copy.deepcopy(pattern)
    rows = p.get("rows", [])
    row_gaps = list(p.get("row_gaps_cm", []))

    if dd == 0 or not rows:
        return p

    if len(rows) == 1:
        # Single row: extra space goes above/below
        # Blocks with stick S have their offset_ns increased by dd
        for b in rows[0].get("blocks", []):
            sticks = set(b.get("sticks", []))
            if "S" in sticks:
                b["offset_ns_cm"] = b.get("offset_ns_cm", 0) + dd
        p["rows"] = rows
        return p

    # Multiple rows: distribute dd into row_gaps
    # Identify if first row has stick N or last row has stick S
    def _row_has_stick(row, stick_dir):
        for b in row.get("blocks", []):
            if stick_dir in set(b.get("sticks", [])):
                return True
        return False

    first_has_n = _row_has_stick(rows[0], "N")
    last_has_s = _row_has_stick(rows[-1], "S")

    if not row_gaps:
        # No gaps between rows -> dd goes below
        p["row_gaps_cm"] = row_gaps
        return p

    # Distribute dd proportionally into row_gaps
    total_gaps = sum(row_gaps)
    if total_gaps > 0:
        for i in range(len(row_gaps)):
            row_gaps[i] += int(round(dd * row_gaps[i] / total_gaps))
    else:
        # All gaps at 0: equal distribution
        per_gap = dd // len(row_gaps)
        for i in range(len(row_gaps)):
            row_gaps[i] += per_gap

    p["row_gaps_cm"] = row_gaps
    return p


def adapt_to_room(
    pattern: dict, target_room: RoomSpec,
) -> dict:
    """Adapt a catalogue pattern to a target room.

    Clamping: stick blocks stay anchored to their wall.
    Homothety: non-stick blocks are redistributed proportionally.

    Args:
        pattern: JSON pattern from the catalogue.
        target_room: Target room (dimensions >= pattern).

    Returns:
        New pattern with adjusted gaps and target dimensions.
    """
    orig_w = pattern.get("room_width_cm", 0)
    orig_d = pattern.get("room_depth_cm", 0)
    target_w = target_room.width_cm
    target_d = target_room.depth_cm

    # EO adaptation (per row)
    adapted = copy.deepcopy(pattern)
    adapted["rows"] = [
        _adapt_row_eo(row, orig_w, target_w)
        for row in pattern.get("rows", [])
    ]
    adapted["room_width_cm"] = target_w
    adapted["room_depth_cm"] = target_d

    # NS adaptation
    adapted = _adapt_ns(adapted, orig_d, target_d)

    # Room geometry: replace with target room geometry
    adapted["room_windows"] = [
        {"face": w.face.value, "offset_cm": w.offset_cm, "width_cm": w.width_cm}
        for w in target_room.windows
    ]
    adapted["room_openings"] = [
        {"face": o.face.value, "offset_cm": o.offset_cm, "width_cm": o.width_cm,
         "has_door": o.has_door, "opens_inward": o.opens_inward,
         "hinge_side": o.hinge_side.value}
        for o in target_room.openings
    ]
    adapted["room_exclusions"] = [
        {"x_cm": z.x_cm, "y_cm": z.y_cm,
         "width_cm": z.width_cm, "depth_cm": z.depth_cm}
        for z in target_room.exclusion_zones
    ]

    return adapted


def adapt_dimensions(
    pattern: dict, target_width: int, target_depth: int,
) -> dict:
    """Adapt a pattern to new room dimensions (width and depth).

    Reuses _adapt_row_eo and _adapt_ns to reposition blocks while
    preserving lock (stick) anchoring.

    Args:
        pattern: JSON pattern with room_width_cm/room_depth_cm.
        target_width: New room width in cm.
        target_depth: New room depth in cm.

    Returns:
        New pattern dict with adjusted gaps and updated dimensions.
    """
    orig_w = pattern.get("room_width_cm", 0)
    orig_d = pattern.get("room_depth_cm", 0)

    adapted = copy.deepcopy(pattern)
    adapted["rows"] = [
        _adapt_row_eo(row, orig_w, target_width)
        for row in pattern.get("rows", [])
    ]
    adapted["room_width_cm"] = target_width
    adapted["room_depth_cm"] = target_depth

    adapted = _adapt_ns(adapted, orig_d, target_depth)
    return adapted


# ---------------------------------------------------------------------------
# Step 4 — Individual desk removal in forbidden zones
# ---------------------------------------------------------------------------

@dataclass
class BlockPosition:
    """Absolute position of a block within the pattern.

    Attributes:
        row_idx: Row index.
        block_idx: Block index within the row.
        x_cm: NW corner of the block (EO axis).
        y_cm: NW corner of the block (NS axis).
        eo_cm: Block EO extent (after rotation).
        ns_cm: Block NS extent (after rotation).
        block_type: Block type name.
        orientation: Block orientation in degrees.
    """
    row_idx: int
    block_idx: int
    x_cm: int
    y_cm: int
    eo_cm: int
    ns_cm: int
    block_type: str
    orientation: int


@dataclass
class DeskPosition:
    """Absolute position of a desk within the pattern.

    Attributes:
        row_idx: Row index.
        block_idx: Block index within the row.
        desk_idx: Desk index within the block.
        x_cm: NW corner of the desk, east axis.
        y_cm: NW corner of the desk, south axis.
        width_cm: EO dimension of the desk.
        depth_cm: NS dimension of the desk.
        block_type: Parent block type.
        chair_side: Direction the chair faces ("N", "E", "S", "W").
    """
    row_idx: int
    block_idx: int
    desk_idx: int
    x_cm: int
    y_cm: int
    width_cm: int
    depth_cm: int
    block_type: str
    chair_side: str = ""


# Relative positions of desks within each block type at orientation 0°.
# Convention (D-223): (dx, dy, extent_eo, extent_ns) — position and extent of
# the desk within the block's EO/NS frame, NW origin. DESK_D_CM is the desk's
# narrow side (80, "depth"), DESK_W_CM the wide side (180, "width"). A standard
# front-facing desk in BLOCK_1 (eo_cm=80, ns_cm=180) therefore has extent
# (DESK_D_CM, DESK_W_CM) along (EO, NS). Frontend block_geometry.js uses the
# same convention.
_DESK_LAYOUTS: dict[str, list[tuple[int, int, int, int]]] = {
    "BLOCK_1": [
        (0, 0, DESK_D_CM, DESK_W_CM),
    ],
    "BLOCK_2_FACE": [
        (0, 0, DESK_D_CM, DESK_W_CM),
        (DESK_D_CM, 0, DESK_D_CM, DESK_W_CM),
    ],
    "BLOCK_2_SIDE": [
        (0, 0, DESK_D_CM, DESK_W_CM),
        (0, DESK_W_CM, DESK_D_CM, DESK_W_CM),
    ],
    "BLOCK_3_SIDE": [
        (0, 0, DESK_D_CM, DESK_W_CM),
        (0, DESK_W_CM, DESK_D_CM, DESK_W_CM),
        (0, 2 * DESK_W_CM, DESK_D_CM, DESK_W_CM),
    ],
    "BLOCK_4_FACE": [
        (0, 0, DESK_D_CM, DESK_W_CM),
        (DESK_D_CM, 0, DESK_D_CM, DESK_W_CM),
        (0, DESK_W_CM, DESK_D_CM, DESK_W_CM),
        (DESK_D_CM, DESK_W_CM, DESK_D_CM, DESK_W_CM),
    ],
    "BLOCK_6_FACE": [
        (0, 0, DESK_D_CM, DESK_W_CM),
        (DESK_D_CM, 0, DESK_D_CM, DESK_W_CM),
        (0, DESK_W_CM, DESK_D_CM, DESK_W_CM),
        (DESK_D_CM, DESK_W_CM, DESK_D_CM, DESK_W_CM),
        (0, 2 * DESK_W_CM, DESK_D_CM, DESK_W_CM),
        (DESK_D_CM, 2 * DESK_W_CM, DESK_D_CM, DESK_W_CM),
    ],
    "BLOCK_2_ORTHO_R": [
        # desk1 (facing S): horizontal bar at top, 180 EO × 80 NS
        (0, 0, DESK_W_CM, DESK_D_CM),
        # desk2 (facing W): vertical bar at bottom-left, 80 EO × 180 NS
        (0, DESK_D_CM, DESK_D_CM, DESK_W_CM),
    ],
    "BLOCK_2_ORTHO_L": [
        # desk1 (facing S): horizontal bar at top, 180 EO × 80 NS
        (0, 0, DESK_W_CM, DESK_D_CM),
        # desk2 (facing E): vertical bar at bottom-right, 80 EO × 180 NS
        (DESK_W_CM - DESK_D_CM, DESK_D_CM, DESK_D_CM, DESK_W_CM),
    ],
}

# Chair side per desk within each block type at orientation 0°.
# Convention: same ordering as _DESK_LAYOUTS.
# "W" = chair on west side, person's back faces west.
# Aligned with frontend block_geometry.js chairSide.
_DESK_CHAIR_SIDES: dict[str, list[str]] = {
    "BLOCK_1": ["W"],
    "BLOCK_2_FACE": ["W", "E"],
    "BLOCK_2_SIDE": ["W", "W"],
    "BLOCK_3_SIDE": ["W", "W", "W"],
    "BLOCK_4_FACE": ["W", "E", "W", "E"],
    "BLOCK_6_FACE": ["W", "E", "W", "E", "W", "E"],
    "BLOCK_2_ORTHO_R": ["N", "E"],
    "BLOCK_2_ORTHO_L": ["N", "W"],
}

_CHAIR_SIDE_ROTATE_CW = {"N": "E", "E": "S", "S": "W", "W": "N"}


def _rotate_chair_side(side: str, degrees: int) -> str:
    """Clockwise rotation of a chair side direction.

    Args:
        side: Chair side at orientation 0° ("N", "E", "S", "W").
        degrees: Rotation in degrees (0, 90, 180, 270).

    Returns:
        Rotated chair side.
    """
    steps = (degrees // 90) % 4
    for _ in range(steps):
        side = _CHAIR_SIDE_ROTATE_CW[side]
    return side


def _rotate_desk_layout(
    dx: int, dy: int, dw: int, dd: int,
    block_eo: int, block_ns: int, degrees: int,
) -> tuple[int, int, int, int]:
    """Clockwise rotation of a desk within a block.

    Args:
        dx, dy: Relative position within the block (orientation 0°).
        dw, dd: Desk dimensions.
        block_eo, block_ns: Block dimensions at orientation 0°.
        degrees: 90, 180, or 270.

    Returns:
        (new_dx, new_dy, new_dw, new_dd) within the rotated block.
    """
    for _ in range((degrees // 90) % 4):
        # 90° clockwise rotation: (x, y) -> (block_ns - y - dd, x)
        new_dx = block_ns - dy - dd
        new_dy = dx
        new_dw = dd
        new_dd = dw
        dx, dy, dw, dd = new_dx, new_dy, new_dw, new_dd
        block_eo, block_ns = block_ns, block_eo
    return dx, dy, dw, dd


def compute_block_positions(pattern: dict) -> list[BlockPosition]:
    """Compute absolute positions of all blocks in a pattern.

    Args:
        pattern: JSON pattern (catalogue format).

    Returns:
        List of BlockPosition with absolute coordinates.
    """
    positions: list[BlockPosition] = []
    row_y = 0
    rows = pattern.get("rows", [])
    row_gaps = pattern.get("row_gaps_cm", [])

    for ri, row in enumerate(rows):
        if ri > 0 and ri - 1 < len(row_gaps):
            row_y += row_gaps[ri - 1]

        block_x = 0
        for bi, block in enumerate(row.get("blocks", [])):
            block_x += block.get("gap_cm", 0)
            btype = block.get("type", "")
            orient = block.get("orientation", 0)
            offset_ns = block.get("offset_ns_cm", 0)

            eo, ns, _ = _BLOCK_REGISTRY.get(btype, (0, 0, 0))
            block_eo = ns if orient in (90, 270) else eo
            block_ns = eo if orient in (90, 270) else ns

            positions.append(BlockPosition(
                row_idx=ri,
                block_idx=bi,
                x_cm=block_x,
                y_cm=row_y + offset_ns,
                eo_cm=block_eo,
                ns_cm=block_ns,
                block_type=btype,
                orientation=orient,
            ))

            block_x += block_eo

        max_ns = 0
        for block in row.get("blocks", []):
            max_ns = max(max_ns, _block_ns_extent(block))
        row_y += max_ns

    return positions


def compute_desk_positions(pattern: dict) -> list[DeskPosition]:
    """Compute absolute positions of all desks in a pattern.

    Delegates block-level positioning to ``compute_block_positions``,
    then expands each block into its constituent desks.

    Args:
        pattern: JSON pattern (adapted or not).

    Returns:
        List of DeskPosition with absolute coordinates.
    """
    block_positions = compute_block_positions(pattern)
    desks: list[DeskPosition] = []

    for bp in block_positions:
        desk_layout = _DESK_LAYOUTS.get(bp.block_type, [])
        chair_sides = _DESK_CHAIR_SIDES.get(bp.block_type, [])
        eo_0, ns_0, _ = _BLOCK_REGISTRY.get(bp.block_type, (0, 0, 0))

        for di, (dx, dy, dw, dd) in enumerate(desk_layout):
            if bp.orientation != 0:
                dx, dy, dw, dd = _rotate_desk_layout(
                    dx, dy, dw, dd, eo_0, ns_0, bp.orientation,
                )
            cs = chair_sides[di] if di < len(chair_sides) else "W"
            if bp.orientation != 0:
                cs = _rotate_chair_side(cs, bp.orientation)
            desks.append(DeskPosition(
                row_idx=bp.row_idx,
                block_idx=bp.block_idx,
                desk_idx=di,
                x_cm=bp.x_cm + dx,
                y_cm=bp.y_cm + dy,
                width_cm=dw,
                depth_cm=dd,
                block_type=bp.block_type,
                chair_side=cs,
            ))

    return desks


def _rects_intersect(
    x1: int, y1: int, w1: int, d1: int,
    x2: int, y2: int, w2: int, d2: int,
) -> bool:
    """Check whether two rectangles overlap (non-empty intersection)."""
    return (x1 < x2 + w2 and x1 + w1 > x2
            and y1 < y2 + d2 and y1 + d1 > y2)


def remove_conflicting_desks(
    pattern: dict, room: RoomSpec,
) -> tuple[dict, list[DeskPosition]]:
    """Remove desks that intersect forbidden zones.

    Individual removal: the desk is removed, not the entire block.
    The returned pattern has modified blocks (removed desks marked).

    Args:
        pattern: JSON pattern (adapted to the target room).
        room: Target room with exclusion_zones.

    Returns:
        (modified_pattern, list_of_removed_desks)
    """
    desks = compute_desk_positions(pattern)
    removed = []

    for desk in desks:
        for excl in room.exclusion_zones:
            if _rects_intersect(
                desk.x_cm, desk.y_cm, desk.width_cm, desk.depth_cm,
                excl.x_cm, excl.y_cm, excl.width_cm, excl.depth_cm,
            ):
                removed.append(desk)
                break

    # Also remove desks that extend outside the room
    for desk in desks:
        if desk in removed:
            continue
        if (desk.x_cm < 0 or desk.y_cm < 0
                or desk.x_cm + desk.width_cm > room.width_cm
                or desk.y_cm + desk.depth_cm > room.depth_cm):
            removed.append(desk)

    # Build the set of desks to keep
    removed_set = {(d.row_idx, d.block_idx, d.desk_idx) for d in removed}
    remaining_desks = [d for d in desks if
                       (d.row_idx, d.block_idx, d.desk_idx) not in removed_set]

    # Update counter
    result = copy.deepcopy(pattern)
    n_remaining = len(remaining_desks)

    logger.debug(
        "Desk removal: %d removed, %d remaining",
        len(removed), n_remaining,
    )

    # Store removal info in the pattern
    result["_removed_desks"] = [
        {"row": d.row_idx, "block": d.block_idx, "desk": d.desk_idx,
         "x_cm": d.x_cm, "y_cm": d.y_cm}
        for d in removed
    ]
    result["_n_desks_after_removal"] = n_remaining

    return result, removed


_SYMMETRIC_180_TYPES: frozenset[str] = frozenset(
    b.name for b in (
        BLOCK_1, BLOCK_2_FACE, BLOCK_2_SIDE, BLOCK_3_SIDE,
        BLOCK_4_FACE, BLOCK_6_FACE, BLOCK_2_ORTHO_R, BLOCK_2_ORTHO_L,
    )
    if b.symmetric_180
)


def _normalize_orientation(block_type: str, orientation: int) -> int:
    """Normalize block orientation for fingerprint comparison.

    Symmetric-180 blocks are reduced modulo 180; others modulo 360.

    Args:
        block_type: Block type name.
        orientation: Raw orientation in degrees.

    Returns:
        Normalized orientation.
    """
    if block_type in _SYMMETRIC_180_TYPES:
        return orientation % 180
    return orientation % 360


def _pattern_fingerprint(pattern: dict) -> tuple:
    """Compute a structural fingerprint for a pattern.

    The fingerprint captures what the user will see on screen (block layout
    and room dimensions), independent of pattern name or WS labels.
    Openings, windows and exclusions are excluded because they are replaced
    by the target room's geometry during adaptation.

    Args:
        pattern: JSON pattern (catalogue format).

    Returns:
        Hashable tuple suitable for deduplication.
    """
    blocks = compute_block_positions(pattern)
    block_tuples = sorted(
        (
            bp.block_type,
            bp.x_cm,
            bp.y_cm,
            _normalize_orientation(bp.block_type, bp.orientation),
        )
        for bp in blocks
    )
    return (
        pattern.get("room_width_cm", 0),
        pattern.get("room_depth_cm", 0),
        tuple(block_tuples),
    )


def dedupe_by_fingerprint(
    candidates: list[PatternCandidate],
) -> list[PatternCandidate]:
    """Remove duplicate candidates that share the same structural fingerprint.

    Preserves the original order: first encountered candidate wins.

    Args:
        candidates: List of pattern candidates (may include mirrors).

    Returns:
        Deduplicated list.
    """
    seen: set[tuple] = set()
    result: list[PatternCandidate] = []
    for c in candidates:
        fp = _pattern_fingerprint(c.pattern)
        if fp not in seen:
            seen.add(fp)
            result.append(c)
    return result


def generate_mirrors(
    candidates: list[PatternCandidate],
) -> list[PatternCandidate]:
    """Generate East-West mirrors of all candidates.

    Returns the original list plus the mirrors.

    Args:
        candidates: Candidates from the selection step.

    Returns:
        Extended list (originals + mirrors).
    """
    result = list(candidates)
    for c in candidates:
        mirrored_pattern = mirror_pattern(c.pattern)
        result.append(PatternCandidate(
            pattern=mirrored_pattern,
            name=mirrored_pattern["name"],
            room_width_cm=c.room_width_cm,
            room_depth_cm=c.room_depth_cm,
            standard=c.standard,
            n_desks=c.n_desks,
        ))
    return result


# ---------------------------------------------------------------------------
# Step 5 — Scoring (circulation + comfort)
# ---------------------------------------------------------------------------

@dataclass
class MatchScore:
    """Scores of a candidate after adaptation to the target room.

    Attributes:
        pattern_name: Source pattern name.
        standard: Layout standard.
        n_desks: Number of desks after removal.
        m2_per_desk: Area per desk (m²).
        circulation_grade: Circulation grade (A-F) from Dijkstra analysis.
        connectivity_pct: Connectivity percentage.
        min_passage_cm: Minimum passage found (cm).
        worst_detour: Worst detour ratio.
        largest_free_rect_m2: Largest free rectangle (m²).
        adapted_pattern: Adapted JSON pattern.
        oversize: Whether pattern is oversize for the room.
        dim_circulation: D-238 dimension 1 — circulation [0,1].
        dim_light: D-238 dimension 2 — window proximity [0,1] or None.
        dim_back_door: D-238 dimension 3 — back-to-door [0,1] or None.
        dim_face_wall: D-238 dimension 4 — face-wall [0,1] or None.
        dim_distance: D-238 dimension 5 — inter-desk distance [0,1] or None.
            v1: always None (computed frontend-side, not replicated yet).
        composite_score: Weighted average of active dimensions.
        room_grade: Composite letter grade (A-F).
    """
    pattern_name: str
    standard: str
    n_desks: int
    m2_per_desk: float
    circulation_grade: str
    connectivity_pct: float
    min_passage_cm: float
    worst_detour: float
    largest_free_rect_m2: float
    adapted_pattern: dict
    oversize: bool = False
    dim_circulation: float | None = None
    dim_light: float | None = None
    dim_back_door: float | None = None
    dim_face_wall: float | None = None
    dim_distance: float | None = None
    composite_score: float = 0.0
    room_grade: str = "F"


# ---------------------------------------------------------------------------
# D-238 — Multi-dimensional grade
# ---------------------------------------------------------------------------

# Circulation grade → dimension [0, 1]
_GRADE_TO_DIM: dict[str, float] = {
    "A": 1.0, "B": 0.8, "C": 0.6, "D": 0.4, "E": 0.2, "F": 0.0,
}

# In canonical model, corridor is always south
_CANONICAL_CORRIDOR_FACE = "south"

_OPPOSITE_FACE = {
    "north": "south", "south": "north",
    "east": "west", "west": "east",
    "N": "S", "S": "N", "E": "W", "W": "E",
}

# D-238 composite thresholds
_GRADE_THRESHOLDS: list[tuple[str, float]] = [
    ("A", 0.90), ("B", 0.75), ("C", 0.60), ("D", 0.45), ("E", 0.30),
]

# D-238 dimension-specific thresholds (cm)
_LIGHT_PROXIMITY_CM = 200
_BACK_DOOR_DISTANCE_CM = 300


def _desk_center(desk: DeskPosition) -> tuple[float, float]:
    """Centre of a desk in cm."""
    return desk.x_cm + desk.width_cm / 2, desk.y_cm + desk.depth_cm / 2


def _opening_center(
    opening, room: RoomSpec,
) -> tuple[float, float]:
    """Centre of an opening on the room wall in cm."""
    face = opening.face.value if hasattr(opening.face, "value") else opening.face
    if face in ("north", "south"):
        cx = opening.offset_cm + opening.width_cm / 2
        cy = 0.0 if face == "north" else float(room.depth_cm)
    else:
        cx = 0.0 if face == "west" else float(room.width_cm)
        cy = opening.offset_cm + opening.width_cm / 2
    return cx, cy


def _window_center(
    window, room: RoomSpec,
) -> tuple[float, float]:
    """Centre of a window on the room wall in cm."""
    face = window.face.value if hasattr(window.face, "value") else window.face
    if face in ("north", "south"):
        cx = window.offset_cm + window.width_cm / 2
        cy = 0.0 if face == "north" else float(room.depth_cm)
    else:
        cx = 0.0 if face == "west" else float(room.width_cm)
        cy = window.offset_cm + window.width_cm / 2
    return cx, cy


def _compute_dim_light(
    active_desks: list[DeskPosition], room: RoomSpec,
) -> float | None:
    """Dimension 2 — window proximity.

    Ratio of desks whose centre is within _LIGHT_PROXIMITY_CM of
    the nearest window centre. Returns None if the room has no windows.
    """
    if not room.windows:
        return None
    if not active_desks:
        return None
    win_centers = [_window_center(w, room) for w in room.windows]
    count = 0
    for desk in active_desks:
        dx, dy = _desk_center(desk)
        min_dist = min(
            math.hypot(dx - wx, dy - wy) for wx, wy in win_centers
        )
        if min_dist <= _LIGHT_PROXIMITY_CM:
            count += 1
    return count / len(active_desks)


def _compute_dim_back_door(
    active_desks: list[DeskPosition], room: RoomSpec,
) -> float | None:
    """Dimension 3 — back to corridor door.

    Ratio of desks that do NOT have their back facing a corridor door
    within _BACK_DOOR_DISTANCE_CM. Returns None if no corridor door exists.

    In canonical model, corridor = south. A desk with chair_side == "S"
    has the person's back facing south (= towards corridor door).
    """
    corridor_doors = [
        o for o in room.openings
        if (o.face.value if hasattr(o.face, "value") else o.face)
        == _CANONICAL_CORRIDOR_FACE
    ]
    if not corridor_doors:
        return None
    if not active_desks:
        return None

    door_centers = [_opening_center(d, room) for d in corridor_doors]
    chair_to_face = {"N": "north", "S": "south", "E": "east", "W": "west"}

    bad_count = 0
    for desk in active_desks:
        cs_face = chair_to_face.get(desk.chair_side, "")
        if cs_face != _CANONICAL_CORRIDOR_FACE:
            continue
        dx, dy = _desk_center(desk)
        min_dist = min(
            math.hypot(dx - ox, dy - oy) for ox, oy in door_centers
        )
        if min_dist <= _BACK_DOOR_DISTANCE_CM:
            bad_count += 1

    return (len(active_desks) - bad_count) / len(active_desks)


def _compute_dim_face_wall(
    active_desks: list[DeskPosition],
    room: RoomSpec,
    walking_margin_cm: int,
) -> float | None:
    """Dimension 4 — face wall.

    Ratio of desks that do NOT have a wall in front of their screen
    within walking_margin_cm. Screen side = opposite of chair_side.
    """
    if not active_desks:
        return None

    bad_count = 0
    for desk in active_desks:
        screen_side = _OPPOSITE_FACE.get(desk.chair_side, "")
        if screen_side == "E":
            dist = room.width_cm - (desk.x_cm + desk.width_cm)
        elif screen_side == "W":
            dist = desk.x_cm
        elif screen_side == "N":
            dist = desk.y_cm
        elif screen_side == "S":
            dist = room.depth_cm - (desk.y_cm + desk.depth_cm)
        else:
            continue
        if dist <= walking_margin_cm:
            bad_count += 1

    return (len(active_desks) - bad_count) / len(active_desks)


def _compute_composite_and_grade(
    dims: dict[str, float | None],
    weights: dict[str, float],
) -> tuple[float, str]:
    """Compute composite score and letter grade.

    Args:
        dims: Dimension name → value (None = N/A, excluded).
        weights: Dimension name → weight.

    Returns:
        (composite_score, grade_letter).
    """
    num = 0.0
    den = 0.0
    for name, val in dims.items():
        if val is None:
            continue
        w = weights.get(name, 1.0)
        num += w * val
        den += w

    composite = round(num / den, 2) if den > 0 else 0.0

    for letter, threshold in _GRADE_THRESHOLDS:
        if composite >= threshold:
            return composite, letter
    return composite, "F"


def _pattern_to_circulation_format(
    pattern: dict, room: RoomSpec,
) -> tuple[dict, list[dict]]:
    """Convert a catalogue pattern + RoomSpec to the circulation analysis format.

    Args:
        pattern: Adapted JSON pattern (with optional _removed_desks).
        room: Target room.

    Returns:
        (room_dict, blocks_list) au format attendu par circulation_analysis.analyse().
    """
    # Room dict in legacy format
    doors = []
    for o in room.openings:
        doors.append({
            "wall": o.face.value,
            "position_cm": o.offset_cm,
            "width_cm": o.width_cm,
        })
    room_dict = {
        "eo_cm": room.width_cm,
        "ns_cm": room.depth_cm,
        "doors": doors,
    }

    # Positioned blocks in circulation format
    blocks_out = []
    row_y = 0
    rows = pattern.get("rows", [])
    row_gaps = pattern.get("row_gaps_cm", [])

    for ri, row in enumerate(rows):
        if ri > 0 and ri - 1 < len(row_gaps):
            row_y += row_gaps[ri - 1]

        block_x = 0
        for bi, block in enumerate(row.get("blocks", [])):
            block_x += block.get("gap_cm", 0)
            btype = block.get("type", "")
            orient = block.get("orientation", 0)
            offset_ns = block.get("offset_ns_cm", 0)

            eo, ns, _ = _BLOCK_REGISTRY.get(btype, (0, 0, 0))
            if orient in (90, 270):
                block_eo, block_ns = ns, eo
            else:
                block_eo, block_ns = eo, ns

            blocks_out.append({
                "type": btype,
                "orientation": orient,
                "x_cm": block_x,
                "y_cm": row_y + offset_ns,
                "eo_cm": block_eo,
                "ns_cm": block_ns,
            })

            block_x += block_eo

        max_ns = 0
        for block in row.get("blocks", []):
            max_ns = max(max_ns, _block_ns_extent(block))
        row_y += max_ns

    return room_dict, blocks_out


def score_candidate(
    pattern: dict, room: RoomSpec, standard: str,
    oversize: bool = False,
) -> MatchScore:
    """Compute the full score of an adapted candidate.

    Args:
        pattern: Adapted and cleaned JSON pattern (desks removed).
        room: Target room.
        standard: Layout standard.

    Returns:
        MatchScore with all indicators including D-238 multi-dim grade.
    """
    from olm.core.circulation_analysis import analyse as circ_analyse

    n_desks = pattern.get("_n_desks_after_removal", count_desks(pattern))
    area_m2 = room.width_cm * room.depth_cm / 10_000
    m2_per_desk = round(area_m2 / n_desks, 2) if n_desks > 0 else 0.0

    # Circulation analysis
    from olm.core.spacing_config import get_default
    default_cfg = get_default()
    cfg = ALL_CONFIGS.get(standard, default_cfg) if default_cfg else None
    room_dict, blocks_list = _pattern_to_circulation_format(pattern, room)
    circ = circ_analyse(room_dict, blocks_list, cfg.door_exclusion_depth_cm)

    # Minimum passage (via desk paths)
    min_passage = min(circ.path_widths) if circ.path_widths else 0.0

    # Residual free rectangle
    free_rect_m2 = largest_free_rectangle_m2(pattern, room)

    # D-238 — Multi-dimensional grade
    # Active desks (excluding removed)
    all_desks = compute_desk_positions(pattern)
    removed_set = {
        (rd["row"], rd["block"], rd["desk"])
        for rd in pattern.get("_removed_desks", [])
    }
    active_desks = [
        d for d in all_desks
        if (d.row_idx, d.block_idx, d.desk_idx) not in removed_set
    ]

    dim_circulation = _GRADE_TO_DIM.get(circ.grade, 0.0)
    dim_light = _compute_dim_light(active_desks, room)
    dim_back_door = _compute_dim_back_door(active_desks, room)

    walking_margin = cfg.walking_margin_cm if cfg else 90
    dim_face_wall = _compute_dim_face_wall(
        active_desks, room, walking_margin,
    )
    # v1: dim_distance not computed backend-side (D-238 limitation)
    dim_distance = None

    # Composite grade
    from olm.core.app_config import get_matching
    matching = get_matching()
    dim_weights = {
        "circulation": matching.get("w_comfort", 1.0),
        "light": matching.get("w_light", 1.0),
        "back_door": matching.get("w_back_door", 1.0),
        "face_wall": matching.get("w_face_wall", 1.0),
        "distance": matching.get("w_distance", 1.0),
    }
    dims = {
        "circulation": dim_circulation,
        "light": dim_light,
        "back_door": dim_back_door,
        "face_wall": dim_face_wall,
        "distance": dim_distance,
    }
    composite, room_grade = _compute_composite_and_grade(dims, dim_weights)

    return MatchScore(
        pattern_name=pattern.get("name", "?"),
        standard=standard,
        n_desks=n_desks,
        m2_per_desk=m2_per_desk,
        circulation_grade=circ.grade,
        connectivity_pct=circ.connectivity_pct,
        min_passage_cm=min_passage,
        worst_detour=circ.worst_detour_ratio,
        largest_free_rect_m2=free_rect_m2,
        adapted_pattern=pattern,
        oversize=oversize,
        dim_circulation=dim_circulation,
        dim_light=dim_light,
        dim_back_door=dim_back_door,
        dim_face_wall=dim_face_wall,
        dim_distance=dim_distance,
        composite_score=composite,
        room_grade=room_grade,
    )


# ---------------------------------------------------------------------------
# Step 6 — Best selection per standard
# ---------------------------------------------------------------------------

def _score_key(s: MatchScore) -> float:
    """Sort key for best candidate selection.

    D-238: density only (m²/desk descending = less dense = better).
    The multi-dimensional grade informs but does not drive sorting.
    Lower key = better candidate (used with min()).
    """
    return -s.m2_per_desk


def select_best(scores: list[MatchScore]) -> MatchScore | None:
    """Select the best candidate from a list of scores.

    Args:
        scores: List of MatchScore for a given standard.

    Returns:
        Best MatchScore, or None if list is empty.
    """
    if not scores:
        return None
    return min(scores, key=_score_key)


# ---------------------------------------------------------------------------
# Step 7 — Largest residual free rectangle
# ---------------------------------------------------------------------------

def largest_free_rectangle_m2(
    pattern: dict, room: RoomSpec,
) -> float:
    """Compute the area of the largest free rectangle after layout.

    Uses the maximal histogram algorithm (O(rows x cols)).

    Args:
        pattern: Adapted pattern with desk positions.
        room: Target room.

    Returns:
        Area in m² of the largest free rectangle.
    """
    import numpy as np

    from olm.core.matching_config import GRID_CELL_CM

    cols = room.width_cm // GRID_CELL_CM
    rows = room.depth_cm // GRID_CELL_CM
    if cols <= 0 or rows <= 0:
        return 0.0

    # Occupancy grid: True = occupied
    occupied = np.zeros((rows, cols), dtype=bool)

    # Peripheral walls
    occupied[0, :] = True
    occupied[-1, :] = True
    occupied[:, 0] = True
    occupied[:, -1] = True

    # Remaining desks (excluding removed)
    desks = compute_desk_positions(pattern)
    removed_set = set()
    for rd in pattern.get("_removed_desks", []):
        removed_set.add((rd["row"], rd["block"], rd["desk"]))

    for d in desks:
        if (d.row_idx, d.block_idx, d.desk_idx) in removed_set:
            continue
        r1 = d.y_cm // GRID_CELL_CM
        r2 = (d.y_cm + d.depth_cm) // GRID_CELL_CM
        c1 = d.x_cm // GRID_CELL_CM
        c2 = (d.x_cm + d.width_cm) // GRID_CELL_CM
        r1 = max(0, min(r1, rows))
        r2 = max(0, min(r2, rows))
        c1 = max(0, min(c1, cols))
        c2 = max(0, min(c2, cols))
        occupied[r1:r2, c1:c2] = True

    # Exclusion zones
    for excl in room.exclusion_zones:
        r1 = int(excl.y_cm // GRID_CELL_CM)
        r2 = int((excl.y_cm + excl.depth_cm) // GRID_CELL_CM)
        c1 = int(excl.x_cm // GRID_CELL_CM)
        c2 = int((excl.x_cm + excl.width_cm) // GRID_CELL_CM)
        r1 = max(0, min(r1, rows))
        r2 = max(0, min(r2, rows))
        c1 = max(0, min(c1, cols))
        c2 = max(0, min(c2, cols))
        occupied[r1:r2, c1:c2] = True

    # Largest rectangle in a histogram algorithm
    free = ~occupied
    heights = np.zeros(cols, dtype=int)
    max_area = 0

    for r in range(rows):
        for c in range(cols):
            heights[c] = heights[c] + 1 if free[r, c] else 0

        # Largest rectangle in histogram (stack-based)
        stack: list[int] = []
        for c in range(cols + 1):
            h = heights[c] if c < cols else 0
            while stack and heights[stack[-1]] > h:
                height = heights[stack.pop()]
                width = c if not stack else c - stack[-1] - 1
                max_area = max(max_area, height * width)
            stack.append(c)

    cell_area_m2 = (GRID_CELL_CM / 100) ** 2
    return round(max_area * cell_area_m2, 2)


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

@dataclass
class MatchingResult:
    """Complete matching result for a room.

    Attributes:
        room: Target room.
        by_standard: Best score per standard.
        all_scores: All computed scores.
    """
    room: RoomSpec
    by_standard: dict[str, MatchScore | None]
    all_scores: list[MatchScore]


def match_room(
    catalogue: list[dict], room: RoomSpec,
) -> MatchingResult:
    """Full matching pipeline for a target room.

    Runs all 7 pipeline steps for all 3 standards.

    Args:
        catalogue: JSON patterns from the catalogue.
        room: Target room.

    Returns:
        MatchingResult with the best per standard and all scores.
    """
    all_scores: list[MatchScore] = []
    by_standard: dict[str, MatchScore | None] = {}

    # Step 1: selection by standard
    selection_results = select_candidates(catalogue, room)

    for sel in selection_results:
        std = sel.standard
        if not sel.candidates:
            by_standard[std] = None
            continue

        # Step 2: mirrors + adapt + dedupe on adapted layout.
        # D-236: two catalogue patterns of different sizes can converge
        # to the SAME adapted layout in a given target room. The
        # fingerprint must therefore be computed on the adapted pattern,
        # not the original — otherwise visual duplicates slip through.
        with_mirrors = generate_mirrors(sel.candidates)
        seen_fps: set[tuple] = set()
        deduped_pairs: list[tuple[PatternCandidate, dict]] = []
        for candidate in with_mirrors:
            adapted = adapt_to_room(candidate.pattern, room)
            fp = _pattern_fingerprint(adapted)
            if fp in seen_fps:
                continue
            seen_fps.add(fp)
            deduped_pairs.append((candidate, adapted))

        std_scores: list[MatchScore] = []
        for candidate, adapted in deduped_pairs:
            # Step 4: remove desks in forbidden zones
            cleaned, removed = remove_conflicting_desks(adapted, room)

            # Step 5: scoring
            score = score_candidate(
                cleaned, room, std, oversize=candidate.oversize,
            )
            std_scores.append(score)
            all_scores.append(score)

        # Step 6: select the best
        by_standard[std] = select_best(std_scores)

    return MatchingResult(
        room=room,
        by_standard=by_standard,
        all_scores=all_scores,
    )


# ---------------------------------------------------------------------------
# Automatic pattern naming
# ---------------------------------------------------------------------------

def _count_openings(pattern: dict) -> int:
    """Count the number of openings (doors + bays) in a pattern."""
    return len(pattern.get("room_openings", []))


def _pattern_group_key(pattern: dict) -> tuple[int, int, str, int]:
    """Group key for naming: (width, depth, std_short, n_openings).

    Two patterns belong to the same group if they share the same key.
    The suffix _{k}O only appears when n_openings >= 2.
    """
    w = pattern.get("room_width_cm", 0)
    d = pattern.get("room_depth_cm", 0)
    std_key = pattern.get("standard", "")
    std = get_standard_label(std_key) if std_key else "UNKNOWN"
    n_open = _count_openings(pattern)
    return (w, d, std, n_open)


def generate_auto_name(
    pattern: dict, catalogue: list[dict],
) -> str:
    """Generate the automatic name for a pattern.

    Format: {W}x{D}_{STANDARD}[_{k}O]_{n}
    - {k}O present only if >= 2 openings
    - {n} = next available increment within the group

    Args:
        pattern: Pattern to name.
        catalogue: Current catalogue (used to compute the increment).

    Returns:
        Generated name.
    """
    key = _pattern_group_key(pattern)
    w, d, std_short, n_open = key

    # Count existing patterns in the same group
    existing_n = []
    for p in catalogue:
        if _pattern_group_key(p) == key:
            # Extract n from existing name
            n = _extract_increment(p.get("name", ""))
            if n is not None:
                existing_n.append(n)

    next_n = max(existing_n, default=0) + 1

    # Build the name
    base = f"{w}x{d}_{std_short}"
    if n_open >= 2:
        base += f"_{n_open}O"
    return f"{base}_{next_n}"


def _extract_increment(name: str) -> int | None:
    """Extract the trailing increment from a pattern name.

    Examples: '310x480_AFNOR_2O_3' -> 3, '310x480_SITE_1' -> 1,
              '310x480_SITE' -> None (legacy format without increment)
    """
    parts = name.rsplit("_", 1)
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None


def compact_catalogue_names(catalogue: list[dict]) -> list[dict]:
    """Compact increments of all patterns per group.

    For each group (same W x D + standard + opening count),
    renumber 1, 2, 3... with no gaps, sorted by original name.

    Args:
        catalogue: List of patterns.

    Returns:
        Catalogue with compacted names (modified in place AND returned).
    """
    from collections import defaultdict

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for p in catalogue:
        key = _pattern_group_key(p)
        groups[key].append(p)

    for key, patterns in groups.items():
        w, d, std_short, n_open = key

        # Sort by existing increment (or by name for stability)
        def sort_key(p):
            n = _extract_increment(p.get("name", ""))
            return n if n is not None else 0
        patterns.sort(key=sort_key)

        # Renumber
        base = f"{w}x{d}_{std_short}"
        if n_open >= 2:
            base += f"_{n_open}O"

        for i, p in enumerate(patterns, start=1):
            p["name"] = f"{base}_{i}"

    return catalogue


def migrate_catalogue_names(catalogue: list[dict]) -> list[dict]:
    """Migrate existing names to the current naming convention.

    Legacy names (e.g. '310x480_AFNOR') become '310x480_AFNOR_1'.
    Groups are compacted after migration.

    Args:
        catalogue: Catalogue with legacy names.

    Returns:
        Catalogue with migrated names.
    """
    # Ensure each pattern has a parseable name.
    # Legacy names like '310x480_AFNOR' have no increment;
    # compact_catalogue_names will renumber them.
    return compact_catalogue_names(catalogue)
