"""Office pattern-placement invariants, demonstrated on the "test 1" plan.

Audit harness (D-270 / D-271). For every catalogue pattern that *fits* in each
room derived from the ``test_office_1`` floor plan, the adapted layout
(``adapt_to_room``) is checked against three placement properties:

1. **Footprint fits** — the emprise of every block (body + face zones + door
   swing) stays inside ``[0, W] x [0, D]``.
2. **Locks preserved** — a block carrying a wall lock (stick) keeps its
   distance to that wall after adaptation.
3. **Blocks against walls** — on a lock-free axis the emprise hugs at least
   one wall (D-271: no centring; first block west, last block east, surplus
   distributed into the inter-block gaps).

Rooms: ``fixtures/test1_rooms.json`` (dimensions only, derived from the plan).
Patterns: the bundled default catalogue (``olm/data/default_catalogue.json``),
committed and stable — NOT the mutable ``project/`` catalogue, so the harness
stays deterministic regardless of live catalogue edits.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from olm.core.catalogue_matcher import (
    ALL_CONFIGS,
    PatternAdaptOverlap,
    _classify_fit,
    adapt_to_room,
    compute_block_positions,
    load_catalogue,
)
from olm.core.pattern_fit import compute_pattern_footprint
from olm.core.room_model import RoomSpec

# --- Tolerances (cm) -------------------------------------------------------
FOOTPRINT_TOL_CM = 1   # integer rounding in adaptation
LOCK_TOL_CM = 1        # integer rounding in adaptation
BALANCE_TOL_CM = 10    # one grid step

# Minimum number of (room, pattern) fitting pairs the harness must exercise,
# so a silent regression (empty catalogue / broken classifier) fails loudly.
MIN_PAIRS = 50

_FIXTURE = Path(__file__).parent / "fixtures" / "test1_rooms.json"
# Bundled, committed catalogue — stable and independent of project/ edits.
_DEFAULT_CATALOGUE = (
    Path(__file__).parent.parent / "data" / "default_catalogue.json"
)

# Stick aliases: legacy "O" means West.
_WEST = {"W", "O"}
_EAST = {"E"}
_NORTH = {"N"}
_SOUTH = {"S"}


def _load_rooms() -> list[dict]:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return data["rooms"]


def _flat_blocks(pattern: dict) -> list[dict]:
    """Blocks in the same order as ``compute_block_positions``."""
    return [b for row in pattern.get("rows", []) for b in row.get("blocks", [])]


def _sticks(block: dict) -> set[str]:
    return set(block.get("sticks") or [])


def _fitting_pairs() -> list[dict]:
    """All (room, pattern) pairs where the pattern fits and adapts cleanly.

    Each entry holds everything the property checks need: the room dims, the
    original/adapted patterns, their block positions and the spacing config.
    """
    catalogue = load_catalogue(str(_DEFAULT_CATALOGUE))
    pairs: list[dict] = []
    for rm in _load_rooms():
        w, d = rm["width_cm"], rm["depth_cm"]
        room = RoomSpec(width_cm=w, depth_cm=d)
        for pattern in catalogue:
            spacing = ALL_CONFIGS.get(pattern.get("standard", ""))
            if spacing is None:
                continue
            try:
                if _classify_fit(pattern, room, spacing) != "fitting":
                    continue
            except Exception:
                continue
            try:
                adapted = adapt_to_room(pattern, room)
            except PatternAdaptOverlap:
                # The matcher skips these too (match_room), so we do as well.
                continue
            pairs.append({
                "room": rm["name"],
                "w": w,
                "d": d,
                "pattern": pattern["name"],
                "spacing": spacing,
                "orig": pattern,
                "adapted": adapted,
            })
    return pairs


# Computed once at import: the matched set is deterministic.
_PAIRS = _fitting_pairs()


def _fmt(rows: list[str], limit: int = 12) -> str:
    head = rows[:limit]
    extra = len(rows) - len(head)
    suffix = f"\n  ... (+{extra} more)" if extra > 0 else ""
    return "\n  " + "\n  ".join(head) + suffix


def test_harness_exercises_enough_pairs():
    """Guard: the audit must actually run on a meaningful set of pairs."""
    assert len(_PAIRS) >= MIN_PAIRS, (
        f"Only {len(_PAIRS)} fitting pairs — catalogue or classifier broken?"
    )


def test_locks_preserved():
    """Property 2 — a locked block keeps its distance to its anchor wall."""
    violations: list[str] = []
    for p in _PAIRS:
        w, d = p["w"], p["d"]
        orig, adapted = p["orig"], p["adapted"]
        ow, od = orig["room_width_cm"], orig["room_depth_cm"]
        before = compute_block_positions(orig)
        after = compute_block_positions(adapted)
        for blk, pb, pa in zip(_flat_blocks(orig), before, after):
            st = _sticks(blk)
            label = f"{p['room']}/{p['pattern']} {blk.get('type')}"
            if st & _WEST and abs(pb.x_cm - pa.x_cm) > LOCK_TOL_CM:
                violations.append(f"{label} W: {pb.x_cm}->{pa.x_cm}")
            if st & _EAST:
                db = ow - (pb.x_cm + pb.eo_cm)
                da = w - (pa.x_cm + pa.eo_cm)
                if abs(db - da) > LOCK_TOL_CM:
                    violations.append(f"{label} E: {db}->{da}")
            if st & _NORTH and abs(pb.y_cm - pa.y_cm) > LOCK_TOL_CM:
                violations.append(f"{label} N: {pb.y_cm}->{pa.y_cm}")
            if st & _SOUTH:
                db = od - (pb.y_cm + pb.ns_cm)
                da = d - (pa.y_cm + pa.ns_cm)
                if abs(db - da) > LOCK_TOL_CM:
                    violations.append(f"{label} S: {db}->{da}")
    assert not violations, (
        f"{len(violations)} lock(s) not preserved after adaptation:"
        + _fmt(violations)
    )


def test_footprint_fits_inside_room():
    """Property 1 — every adapted block emprise stays inside the room."""
    violations: list[str] = []
    for p in _PAIRS:
        w, d = p["w"], p["d"]
        x0, x1, y0, y1 = compute_pattern_footprint(p["adapted"], p["spacing"])
        if (x0 < -FOOTPRINT_TOL_CM or y0 < -FOOTPRINT_TOL_CM
                or x1 > w + FOOTPRINT_TOL_CM or y1 > d + FOOTPRINT_TOL_CM):
            violations.append(
                f"{p['room']}/{p['pattern']}: footprint "
                f"[{x0},{x1}]x[{y0},{y1}] in {w}x{d}"
            )
    assert not violations, (
        f"{len(violations)} pattern(s) overflow the room:" + _fmt(violations)
    )


def test_blocks_against_walls_on_unlocked_axes():
    """Property 3 — on a lock-free axis, blocks hug at least one wall."""
    violations: list[str] = []
    for p in _PAIRS:
        w, d = p["w"], p["d"]
        all_sticks: set[str] = set()
        for blk in _flat_blocks(p["orig"]):
            all_sticks |= _sticks(blk)
        x0, x1, y0, y1 = compute_pattern_footprint(
            p["adapted"], p["spacing"],
        )
        if not (all_sticks & (_WEST | _EAST)):
            left, right = x0, w - x1
            if min(left, right) > BALANCE_TOL_CM:
                violations.append(
                    f"{p['room']}/{p['pattern']} EO: "
                    f"left={left} right={right}"
                )
        if not (all_sticks & (_NORTH | _SOUTH)):
            top, bottom = y0, d - y1
            if min(top, bottom) > BALANCE_TOL_CM:
                violations.append(
                    f"{p['room']}/{p['pattern']} NS: "
                    f"top={top} bottom={bottom}"
                )
    assert not violations, (
        f"{len(violations)} layout(s) not against a wall:"
        + _fmt(violations)
    )
