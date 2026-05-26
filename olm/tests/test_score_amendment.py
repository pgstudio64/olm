"""Tests for the score-amendment endpoint and service function.

Covers:
- POST /api/floor-plan/score-amendment returns 200 with all 24 fields.
- Missing required fields return 400.
- Unknown standard returns 400.
- Zero-desk amendment does not crash.
- All 24 response fields are present (snapshot invariant).
"""
from __future__ import annotations

# Canonical 24 fields expected in the response (P4).
_EXPECTED_FIELDS = frozenset({
    "pattern_name", "standard", "n_desks", "m2_per_desk",
    "circulation_grade", "connectivity_pct", "min_passage_cm",
    "worst_detour", "largest_free_rect_m2", "oversize", "fit_class",
    "overflow_cm", "dim_reachability", "all_desks_reachable",
    "dim_passage", "passage_grade", "dim_light", "dim_back_door",
    "dim_face_wall", "composite_score", "room_grade", "category",
    "desks", "pattern",
})

# Minimal room matching conftest.sample_room_canonical dims.
_ROOM = {
    "name": "amend_test",
    "width_cm": 500,
    "depth_cm": 480,
    "windows": [
        {"face": "north", "offset_cm": 0, "width_cm": 500},
    ],
    "openings": [
        {"face": "south", "offset_cm": 200, "width_cm": 90,
         "has_door": True, "opens_inward": True, "hinge_side": "left"},
    ],
    "exclusion_zones": [],
}

# Minimal pattern (single BLOCK_1, row 0 empty, row 1 with block).
_PATTERN = {
    "name": "amend_test_pat",
    "rows": [
        {"blocks": []},
        {"blocks": [
            {"type": "BLOCK_1", "orientation": 0,
             "offset_ns_cm": -180, "gap_cm": 100},
        ]},
    ],
    "row_gaps_cm": [180],
    "room_width_cm": 500,
    "room_depth_cm": 480,
    "standard": "standard1",
    "room_windows": [
        {"face": "north", "offset_cm": 0, "width_cm": 500},
    ],
    "room_openings": [
        {"face": "south", "has_door": True, "hinge_side": "left",
         "offset_cm": 200, "opens_inward": True, "width_cm": 90},
    ],
    "room_exclusions": [],
}


class TestScoreAmendmentEndpoint:
    """Integration tests for POST /api/floor-plan/score-amendment."""

    def test_missing_room_returns_400(self, client):
        resp = client.post(
            "/api/floor-plan/score-amendment",
            json={"pattern": _PATTERN},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_missing_pattern_returns_400(self, client):
        resp = client.post(
            "/api/floor-plan/score-amendment",
            json={"room": _ROOM},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_unknown_standard_returns_400(self, client):
        resp = client.post(
            "/api/floor-plan/score-amendment",
            json={
                "room": _ROOM,
                "pattern": _PATTERN,
                "standard": "nonexistent_standard",
            },
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_valid_amendment_returns_200(self, client):
        resp = client.post(
            "/api/floor-plan/score-amendment",
            json={
                "room": _ROOM,
                "pattern": _PATTERN,
                "standard": "standard1",
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "error" not in data
        assert data["standard"] == "standard1"
        assert isinstance(data["n_desks"], int)
        assert isinstance(data["room_grade"], str)
        assert isinstance(data["desks"], list)
        assert isinstance(data["category"], str)

    def test_all_24_fields_present(self, client):
        """Snapshot invariant: response contains exactly the 24 fields."""
        resp = client.post(
            "/api/floor-plan/score-amendment",
            json={
                "room": _ROOM,
                "pattern": _PATTERN,
                "standard": "standard1",
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        missing = _EXPECTED_FIELDS - set(data.keys())
        assert not missing, f"Missing fields: {missing}"

    def test_zero_desk_amendment(self, client):
        """Amendment with no blocks does not crash."""
        empty_pattern = {
            "name": "empty_amend",
            "rows": [],
            "row_gaps_cm": [],
            "room_width_cm": 500,
            "room_depth_cm": 480,
            "standard": "standard1",
        }
        resp = client.post(
            "/api/floor-plan/score-amendment",
            json={
                "room": _ROOM,
                "pattern": empty_pattern,
                "standard": "standard1",
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["n_desks"] == 0
        assert data["m2_per_desk"] == 0.0
        assert data["desks"] == []
