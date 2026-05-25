"""Tests for the office.candidates diagnostic endpoint and pipeline.

Covers:
- POST /api/office/diagnose returns 200 with room_context, step_counts, patterns.
- Missing room field returns 400.
- classify_candidate_status pure helper (6bis + 6ter decisions).
- filter_and_rank_candidates still works identically after refactor.
"""
from __future__ import annotations

from olm.core.catalogue_matcher import (
    MatchScore,
    candidate_category,
    classify_candidate_status,
    filter_and_rank_candidates,
)
from olm.core.spacing_config import SpacingConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STD3_CFG = SpacingConfig(
    name="standard3",
    chair_clearance_cm=40,
    walking_margin_cm=70,
    slip_in_margin_cm=30,
    main_corridor_cm=120,
    door_exclusion_depth_cm=90,
    max_island_size=6,
)

_TEST_CONFIGS = {"standard3": _STD3_CFG}


def _make_score(
    name: str = "test_pattern",
    standard: str = "standard3",
    n_desks: int = 3,
    fit_class: str = "fitting",
    passage_grade: str | None = "A",
    min_passage_cm: float = 100.0,
    dim_reachability: float = 1.0,
    room_grade: str = "B",
    overflow_cm: float = 0.0,
    oversize: bool = False,
) -> MatchScore:
    """Build a minimal MatchScore for filter testing."""
    return MatchScore(
        pattern_name=name,
        standard=standard,
        n_desks=n_desks,
        m2_per_desk=5.0,
        circulation_grade="A" if dim_reachability > 0 else "F",
        connectivity_pct=100.0,
        min_passage_cm=min_passage_cm,
        worst_detour=1.0,
        largest_free_rect_m2=2.0,
        adapted_pattern={"name": name, "rows": [], "row_gaps_cm": []},
        oversize=oversize,
        fit_class=fit_class,
        overflow_cm=overflow_cm,
        dim_reachability=dim_reachability,
        dim_passage=0.8 if passage_grade else None,
        passage_grade=passage_grade,
        dim_light=1.0,
        dim_back_door=1.0,
        dim_face_wall=1.0,
        composite_score=0.7,
        room_grade=room_grade,
    )


# ---------------------------------------------------------------------------
# classify_candidate_status
# ---------------------------------------------------------------------------

class TestClassifyCandidateStatus:
    """Pure decision helper shared by prod and diag."""

    def test_kept(self):
        s = _make_score(dim_reachability=1.0, min_passage_cm=100.0)
        assert classify_candidate_status(s, 56.0, 0) == "kept"

    def test_removed_6bis_reach(self):
        s = _make_score(dim_reachability=0)
        assert classify_candidate_status(s, 56.0, 0) == "removed_6bis_reach"

    def test_removed_6bis_passage(self):
        # threshold = 56.0, min_passage = 50.0 < 56.0
        s = _make_score(
            dim_reachability=0.4, min_passage_cm=50.0, passage_grade="F",
        )
        assert classify_candidate_status(s, 56.0, 0) == "removed_6bis_passage"

    def test_passage_at_threshold_kept(self):
        s = _make_score(
            dim_reachability=0.4, min_passage_cm=56.0, passage_grade="D",
        )
        assert classify_candidate_status(s, 56.0, 0) == "kept"

    def test_removed_6ter(self):
        # too_tight candidate with n_desks=2, max_working=3.
        s = _make_score(
            n_desks=2, passage_grade="D",
            dim_reachability=0.4, min_passage_cm=60.0,
        )
        # Verify it's classified as too_tight.
        assert candidate_category(s, 3) == "too_tight"
        assert classify_candidate_status(s, 56.0, 3) == "removed_6ter"

    def test_6ter_disabled_when_max_working_zero(self):
        s = _make_score(
            n_desks=2, passage_grade="D",
            dim_reachability=0.4, min_passage_cm=60.0,
        )
        # max_working=0 disables 6ter guard.
        assert classify_candidate_status(s, 56.0, 0) == "kept"

    def test_threshold_none_skips_passage_check(self):
        s = _make_score(
            dim_reachability=0.4, min_passage_cm=10.0, passage_grade="F",
        )
        # No threshold (no config) → passage check skipped.
        assert classify_candidate_status(s, None, 0) == "kept"


# ---------------------------------------------------------------------------
# filter_and_rank_candidates (regression after refactor)
# ---------------------------------------------------------------------------

class TestFilterRefactorRegression:
    """Ensure the refactored filter_and_rank_candidates is identical."""

    def test_6bis_reach_removed(self):
        impossible = _make_score(name="imp", dim_reachability=0)
        good = _make_score(name="good")
        final = filter_and_rank_candidates(
            [impossible, good], configs=_TEST_CONFIGS,
        )
        names = [s.pattern_name for s in final]
        assert "imp" not in names
        assert "good" in names

    def test_6bis_passage_removed(self):
        narrow = _make_score(
            name="narrow", min_passage_cm=50.0,
            passage_grade="F", dim_reachability=0.4,
        )
        final = filter_and_rank_candidates(
            [narrow], configs=_TEST_CONFIGS,
        )
        assert len(final) == 0

    def test_6ter_dominated_removed(self):
        fw = _make_score(
            name="fw_3", n_desks=3, passage_grade="A",
            dim_reachability=1.0,
        )
        tight = _make_score(
            name="tight_2", n_desks=2, passage_grade="D",
            dim_reachability=0.4, min_passage_cm=60.0,
        )
        final = filter_and_rank_candidates(
            [fw, tight], configs=_TEST_CONFIGS,
        )
        names = [s.pattern_name for s in final]
        assert "fw_3" in names
        assert "tight_2" not in names

    def test_all_kept_when_no_fits_well(self):
        tight_a = _make_score(
            name="ta", n_desks=3, passage_grade="D",
            dim_reachability=0.4, min_passage_cm=60.0,
        )
        tight_b = _make_score(
            name="tb", n_desks=2, passage_grade="D",
            dim_reachability=0.4, min_passage_cm=60.0,
        )
        final = filter_and_rank_candidates(
            [tight_a, tight_b], configs=_TEST_CONFIGS,
        )
        assert len(final) == 2


# ---------------------------------------------------------------------------
# Endpoint /api/office/diagnose
# ---------------------------------------------------------------------------

class TestDiagnoseEndpoint:
    """Integration tests for the diagnose API endpoint."""

    def test_missing_room_returns_400(self, client):
        resp = client.post(
            "/api/office/diagnose",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_valid_room_returns_200(self, client):
        room = {
            "name": "test_diag",
            "width_cm": 400,
            "depth_cm": 500,
            "openings": [{
                "face": "south", "offset_cm": 0, "width_cm": 90,
                "has_door": True, "opens_inward": True,
                "hinge_side": "left",
            }],
            "windows": [{"face": "north", "offset_cm": 0, "width_cm": 300}],
            "exclusion_zones": [],
        }
        resp = client.post(
            "/api/office/diagnose",
            json={"room": room},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "room_context" in data
        assert "step_counts" in data
        assert "patterns" in data

        ctx = data["room_context"]
        assert ctx["name"] == "test_diag"
        assert ctx["width_cm"] == 400
        assert ctx["depth_cm"] == 500
        assert ctx["n_doors"] == 1
        assert ctx["n_windows"] == 1

        counts = data["step_counts"]
        assert "total_catalogue" in counts
        assert "kept" in counts
        assert counts["total_catalogue"] >= 0

        # Patterns list: each entry has required fields.
        for p in data["patterns"]:
            assert "pattern_name" in p
            assert "standard" in p
            assert "status" in p
            assert p["status"] in {
                "kept", "wrong_standard", "no_fit",
                "removed_6bis_reach", "removed_6bis_passage",
                "removed_6ter", "hidden",
            }
