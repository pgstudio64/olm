"""Matching service — floor-plan match, coverage, mock candidates.

Handles all operations for group E endpoints.
"""
from __future__ import annotations

import logging
import time  # v0.5.33 instrumentation : timing matching (freeze Floor→Room)

from olm.core.catalogue_matcher import (
    compute_desk_positions,
    match_room,
)
from olm.core.coverage_analysis import (
    analyse_coverage,
    report_to_dict,
)
from olm.server.services.catalogue_service import load_catalogue
from olm.server.services.config_service import get_block_defs
from olm.server.services.serialization import room_from_json, room_to_json

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mock candidates
# ---------------------------------------------------------------------------

MOCK_ROOM = {
    "eo_cm": 300,
    "ns_cm": 480,
    "doors": [
        {"wall": "south", "position_cm": 0, "width_cm": 90, "swing": "right"},
    ],
    "windows": [{"wall": "north", "position_cm": 0, "width_cm": 300}],
    "obstacles": [],
}


def _pattern_emprise_eo(pattern: dict) -> float:
    """Compute the EO footprint (width) of the first row of a pattern."""
    block_defs = get_block_defs("standard3")
    rows = pattern.get("rows", [])
    if not rows:
        return 0.0
    total = 0.0
    for block in rows[0].get("blocks", []):
        total += block.get("gap_cm", 0)
        btype = block.get("type", "")
        orient = block.get("orientation", 0)
        bdef = block_defs.get(btype, {})
        eo = bdef.get("eo_cm", 0)
        ns = bdef.get("ns_cm", 0)
        if orient in (90, 270):
            total += ns
        else:
            total += eo
    return total


def _pattern_total_desks(pattern: dict) -> int:
    """Count the total number of desks in a pattern."""
    block_defs = get_block_defs("standard3")
    total = 0
    for row in pattern.get("rows", []):
        for block in row.get("blocks", []):
            bdef = block_defs.get(block.get("type", ""), {})
            total += bdef.get("n_desks", 0)
    return total


def get_mock_candidates() -> dict:
    """Generate mock candidate solutions for the reference room.

    Returns:
        Dict with ``room``, ``candidates``, ``pipelineStep``.
    """
    patterns = load_catalogue()
    candidates = []
    cid = 1
    room_eo = MOCK_ROOM["eo_cm"]

    for pattern in patterns:
        emprise = _pattern_emprise_eo(pattern)
        desks = _pattern_total_desks(pattern)
        rows_copy = pattern.get("rows", [])
        gaps_copy = pattern.get("row_gaps_cm", [])

        anchors = [
            {"anchor_x_cm": 0, "anchor_y_cm": 0},
            {"anchor_x_cm": max(0.0, (room_eo - emprise) / 2.0),
             "anchor_y_cm": 50},
            {"anchor_x_cm": max(0.0, room_eo - emprise),
             "anchor_y_cm": 0},
        ]
        for anchor in anchors:
            candidates.append({
                "id": cid,
                "label": "Sol. " + str(cid),
                "pattern_name": pattern["name"],
                "anchor_x_cm": round(anchor["anchor_x_cm"], 1),
                "anchor_y_cm": anchor["anchor_y_cm"],
                "rotation": 0,
                "desks": desks,
                "score": None,
                "sqm_per_desk": None,
                "circulation_grade": None,
                "rows": rows_copy,
                "row_gaps_cm": gaps_copy,
            })
            cid += 1

    return {
        "room": MOCK_ROOM,
        "candidates": candidates,
        "pipelineStep": 0,
    }


# ---------------------------------------------------------------------------
# Floor-plan match
# ---------------------------------------------------------------------------


def floor_plan_match(data: dict) -> dict:
    """Run catalogue matching on a set of rooms.

    Args:
        data: dict with ``rooms`` list (canonical coordinates).

    Returns:
        ``{"rooms": [...]}``.

    Raises:
        ValueError: if ``rooms`` is missing.
    """
    if not data or "rooms" not in data:
        raise ValueError("Required field: rooms")

    catalogue = load_catalogue()
    results = []

    # v0.5.33 instrumentation : timing par piece + total. Logue dans olm.log
    # ([MATCH-PERF]) ET renvoie dans la reponse (_perf) pour la modal Perf.
    _t_all = time.perf_counter()
    _perf_rooms = []
    logger.info("[MATCH-PERF] start : %d rooms, %d patterns",
                len(data["rooms"]), len(catalogue))

    for r in data["rooms"]:
        room = room_from_json(r)
        _t_room = time.perf_counter()
        match_result = match_room(catalogue, room)
        _dt_room = (time.perf_counter() - _t_room) * 1000
        logger.info("[MATCH-PERF] room %s : %.0f ms, %d scores",
                    r.get("name", "?"), _dt_room, len(match_result.all_scores))
        _perf_rooms.append({
            "name": r.get("name", "?"),
            "ms": round(_dt_room),
            "scores": len(match_result.all_scores),
        })

        room_result = room_to_json(room)
        room_result["by_standard"] = {}
        room_result["all_candidates"] = []

        for score in match_result.all_scores:
            desks = compute_desk_positions(score.adapted_pattern)
            removed_set = set()
            for rd in score.adapted_pattern.get("_removed_desks", []):
                removed_set.add((rd["row"], rd["block"], rd["desk"]))

            desk_list = [
                {
                    "x_cm": d.x_cm, "y_cm": d.y_cm,
                    "width_cm": d.width_cm, "depth_cm": d.depth_cm,
                    "chair_side": d.chair_side,
                    "removed": (d.row_idx, d.block_idx, d.desk_idx)
                               in removed_set,
                }
                for d in desks
            ]

            candidate = {
                "pattern_name": score.pattern_name,
                "standard": score.standard,
                "n_desks": score.n_desks,
                "m2_per_desk": score.m2_per_desk,
                "circulation_grade": score.circulation_grade,
                "connectivity_pct": score.connectivity_pct,
                "min_passage_cm": score.min_passage_cm,
                "worst_detour": score.worst_detour,
                "largest_free_rect_m2": score.largest_free_rect_m2,
                "oversize": score.oversize,
                "fit_class": score.fit_class,
                "overflow_cm": score.overflow_cm,
                "dim_reachability": score.dim_reachability,
                "dim_passage": score.dim_passage,
                "passage_grade": score.passage_grade,
                "dim_light": score.dim_light,
                "dim_back_door": score.dim_back_door,
                "dim_face_wall": score.dim_face_wall,
                "composite_score": score.composite_score,
                "room_grade": score.room_grade,
                "desks": desk_list,
                "pattern": score.adapted_pattern,
            }
            room_result["all_candidates"].append(candidate)

        for std, best in match_result.by_standard.items():
            room_result["by_standard"][std] = (
                best.pattern_name if best else None
            )

        results.append(room_result)

    _dt_all = (time.perf_counter() - _t_all) * 1000
    logger.info("[MATCH-PERF] total : %.0f ms for %d rooms",
                _dt_all, len(data["rooms"]))

    return {
        "rooms": results,
        "_perf": {"total_ms": round(_dt_all), "rooms": _perf_rooms},
    }


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def coverage_report(data: dict) -> dict:
    """Catalogue coverage analysis on a set of rooms.

    Args:
        data: dict with ``rooms`` list.

    Returns:
        Coverage report dict.

    Raises:
        ValueError: if ``rooms`` is missing.
    """
    if not data or "rooms" not in data:
        raise ValueError("Required field: rooms")

    rooms = [room_from_json(r) for r in data["rooms"]]
    catalogue = load_catalogue()
    report = analyse_coverage(rooms, catalogue)
    return report_to_dict(report)
