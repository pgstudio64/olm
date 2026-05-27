"""Tests for D-310 candidate filters (6bis / 6bis-grade / 6ter).

Covers:
- 6bis: removal of candidates with dim_reachability == 0
- 6bis: removal of candidates with min_passage below threshold
- 6bis: conservation of fits_well candidates
- 6bis-grade: room_grade forced to F when dim_reachability == 0
- 6ter: dominated too_tight removed
- 6ter: too_tight kept when n_desks > max_working
- 6ter: max_working == 0 -> nothing removed
- by_standard recalculated on survivors / None when empty
"""
from __future__ import annotations

from unittest.mock import patch

from olm.core.catalogue_matcher import (
    MatchScore,
    best_pattern_per_standard,
    candidate_category,
    filter_and_rank_candidates,
    score_candidate,
)
from olm.core.circulation_analysis import CirculationResult
from olm.core.room_model import Face, OpeningSpec, RoomSpec
from olm.core.spacing_config import SpacingConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_score(
    name: str = "test_pattern",
    standard: str = "standard3",
    n_desks: int = 3,
    fit_class: str = "fitting",
    passage_grade: str | None = "A",
    min_passage_cm: float = 100.0,
    dim_reachability: float = 1.0,
    all_desks_reachable: bool = True,
    room_grade: str = "B",
    composite_score: float = 0.7,
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
        all_desks_reachable=all_desks_reachable,
        dim_passage=0.8 if passage_grade else None,
        passage_grade=passage_grade,
        dim_light=1.0,
        dim_back_door=1.0,
        dim_face_wall=1.0,
        composite_score=composite_score,
        room_grade=room_grade,
    )


_STD3_CFG = SpacingConfig(
    name="standard3",
    chair_clearance_cm=40,
    walking_margin_cm=70,
    slip_in_margin_cm=30,
    main_corridor_cm=120,
    door_exclusion_depth_cm=90,
    max_island_size=6,
)

_STD1_CFG = SpacingConfig(
    name="standard1",
    chair_clearance_cm=50,
    walking_margin_cm=90,
    slip_in_margin_cm=40,
    main_corridor_cm=140,
    door_exclusion_depth_cm=110,
    max_island_size=4,
)

_TEST_CONFIGS = {"standard3": _STD3_CFG, "standard1": _STD1_CFG}


def _filter(
    scores: list[MatchScore],
    removal_pct: int = 20,
) -> list[MatchScore]:
    """Shorthand: call the real filter with deterministic configs."""
    return filter_and_rank_candidates(
        scores, removal_pct, configs=_TEST_CONFIGS,
    )


def _filter_with_by_std(
    scores: list[MatchScore],
    removal_pct: int = 20,
) -> tuple[list[MatchScore], dict[str, str | None]]:
    """Filter + compute by_standard from survivors."""
    final = _filter(scores, removal_pct)
    all_stds = list({s.standard for s in scores})
    by_std = best_pattern_per_standard(final, all_stds)
    return final, by_std


# ---------------------------------------------------------------------------
# 6bis — reachability 0 (impossible)
# ---------------------------------------------------------------------------

class Test6bisReachability:
    """Candidates with all_desks_reachable=False are removed (D-317)."""

    def test_unreachable_desk_removed(self):
        impossible = _make_score(
            name="impossible", dim_reachability=0,
            all_desks_reachable=False, room_grade="F",
        )
        good = _make_score(name="good", dim_reachability=1.0)
        final = _filter([impossible, good])
        names = [s.pattern_name for s in final]
        assert "impossible" not in names
        assert "good" in names

    def test_reachable_low_connectivity_kept(self):
        """D-317: dim_reachability=0 (grade F) but desk IS reachable."""
        score = _make_score(
            dim_reachability=0.0, all_desks_reachable=True,
            passage_grade="A", min_passage_cm=90.0,
        )
        final = _filter([score])
        assert len(final) == 1
        assert final[0].best_effort is False

    def test_reachability_nonzero_kept(self):
        score = _make_score(dim_reachability=0.4, passage_grade="D")
        final = _filter([score])
        assert len(final) == 1


# ---------------------------------------------------------------------------
# 6bis — passage too narrow
# ---------------------------------------------------------------------------

class Test6bisPassage:
    """Candidates below the passage removal threshold are removed."""

    def test_passage_below_threshold_fallback(self):
        """D-317: sole narrow candidate recovered as best_effort."""
        # std3: walking_margin=70, 20% -> threshold=56.
        narrow = _make_score(
            name="narrow", min_passage_cm=50.0,
            passage_grade="F", dim_reachability=0.4,
        )
        final = _filter([narrow])
        assert len(final) == 1
        assert final[0].best_effort is True

    def test_passage_at_threshold_kept(self):
        # Exactly at threshold (56.0) -> kept (strict <).
        at_limit = _make_score(
            name="at_limit", min_passage_cm=56.0,
            passage_grade="D", dim_reachability=0.4,
        )
        final = _filter([at_limit])
        assert len(final) == 1

    def test_passage_above_threshold_kept(self):
        above = _make_score(
            name="above", min_passage_cm=60.0,
            passage_grade="D", dim_reachability=0.4,
        )
        final = _filter([above])
        assert len(final) == 1

    def test_custom_removal_pct_fallback(self):
        """D-317: sole narrow candidate at custom threshold → best_effort."""
        # 50% of 70 = 35. 30 < 35 -> removed, then fallback.
        narrow = _make_score(
            name="narrow", min_passage_cm=30.0,
            passage_grade="F", dim_reachability=0.4,
        )
        final = _filter([narrow], removal_pct=50)
        assert len(final) == 1
        assert final[0].best_effort is True


# ---------------------------------------------------------------------------
# 6bis — fits_well never removed
# ---------------------------------------------------------------------------

class Test6bisFitsWellSafe:
    """A fits_well candidate is never removed by 6bis.

    By construction: fits_well requires circulates_well (passage_grade
    in {A,B,C}) which means min_passage >= walking_margin, always above
    the removal threshold. And dim_reachability > 0 (circ grade != F).
    """

    def test_fits_well_not_removed(self):
        fw = _make_score(
            name="fw", n_desks=3, fit_class="fitting",
            passage_grade="A", min_passage_cm=100.0,
            dim_reachability=1.0,
        )
        final = _filter([fw])
        assert len(final) == 1
        assert final[0].pattern_name == "fw"


# ---------------------------------------------------------------------------
# 6bis-grade — room_grade forced to F via score_candidate
# ---------------------------------------------------------------------------

class Test6bisGrade:
    """score_candidate forces room_grade='F' when dim_reachability==0.

    Integration test: mock circ_analyse to return grade F (unreachable
    desk), then verify that score_candidate propagates room_grade = F.
    """

    def test_grade_f_when_unreachable(self):
        room = RoomSpec(
            width_cm=300, depth_cm=400,
            openings=[
                OpeningSpec(face=Face.SOUTH, offset_cm=0, width_cm=90),
            ],
        )
        pattern = {
            "name": "test_unreachable",
            "room_width_cm": 300,
            "room_depth_cm": 400,
            "rows": [{
                "blocks": [{
                    "type": "BLOCK_1_FACE",
                    "orientation": 0,
                    "gap_cm": 0,
                }],
            }],
            "row_gaps_cm": [0],
            "room_openings": [{
                "face": "south", "offset_cm": 0, "width_cm": 90,
                "has_door": True,
            }],
        }
        # Mock circulation to return grade F with one unreachable desk.
        # paths=[[]] means 1 targeted desk with no BFS path found.
        fake_circ = CirculationResult(
            grade="F",
            connectivity_pct=50.0,
            isolated_area_pct=30.0,
            avg_detour_ratio=1.0,
            worst_detour_ratio=1.0,
            path_widths=[80.0],
            paths=[[]],
        )
        with patch(
            "olm.core.circulation_analysis.analyse",
            return_value=fake_circ,
        ):
            score = score_candidate(pattern, room, "standard3")

        assert score.dim_reachability == 0.0
        assert score.room_grade == "F"

    def test_grade_preserved_when_reachable(self):
        room = RoomSpec(
            width_cm=300, depth_cm=400,
            openings=[
                OpeningSpec(face=Face.SOUTH, offset_cm=0, width_cm=90),
            ],
        )
        pattern = {
            "name": "test_reachable",
            "room_width_cm": 300,
            "room_depth_cm": 400,
            "rows": [{
                "blocks": [{
                    "type": "BLOCK_1_FACE",
                    "orientation": 0,
                    "gap_cm": 0,
                }],
            }],
            "row_gaps_cm": [0],
            "room_openings": [{
                "face": "south", "offset_cm": 0, "width_cm": 90,
                "has_door": True,
            }],
        }
        fake_circ = CirculationResult(
            grade="A",
            connectivity_pct=100.0,
            isolated_area_pct=0.0,
            avg_detour_ratio=1.0,
            worst_detour_ratio=1.0,
            path_widths=[120.0],
        )
        with patch(
            "olm.core.circulation_analysis.analyse",
            return_value=fake_circ,
        ):
            score = score_candidate(pattern, room, "standard3")

        assert score.dim_reachability == 1.0
        assert score.room_grade != "F"


# ---------------------------------------------------------------------------
# D-319 — dim_reachability aligned on all_desks_reachable
# ---------------------------------------------------------------------------

class TestDimReachabilityFromDesks:
    """D-319: dim_reachability is 1.0/0.0 based on all_desks_reachable."""

    def test_all_desks_reachable_gives_one(self):
        """One desk with a valid BFS path → dim_reachability=1.0."""
        room = RoomSpec(
            width_cm=300, depth_cm=400,
            openings=[
                OpeningSpec(
                    face=Face.SOUTH, offset_cm=0, width_cm=90,
                ),
            ],
        )
        pattern = {
            "name": "test_reach_ok",
            "room_width_cm": 300,
            "room_depth_cm": 400,
            "rows": [{"blocks": [{
                "type": "BLOCK_1_FACE",
                "orientation": 0,
                "gap_cm": 0,
            }]}],
            "row_gaps_cm": [0],
            "room_openings": [{
                "face": "south", "offset_cm": 0, "width_cm": 90,
                "has_door": True,
            }],
        }
        fake_circ = CirculationResult(
            grade="C",
            connectivity_pct=55.0,
            isolated_area_pct=10.0,
            avg_detour_ratio=1.2,
            worst_detour_ratio=1.5,
            path_widths=[90.0],
            paths=[[(1, 1), (1, 2)]],
        )
        with patch(
            "olm.core.circulation_analysis.analyse",
            return_value=fake_circ,
        ):
            score = score_candidate(pattern, room, "standard3")

        assert score.all_desks_reachable is True
        assert score.dim_reachability == 1.0

    def test_one_desk_unreachable_gives_zero(self):
        """Two desks, second has no BFS path → dim_reachability=0.0."""
        room = RoomSpec(
            width_cm=400, depth_cm=400,
            openings=[
                OpeningSpec(
                    face=Face.SOUTH, offset_cm=0, width_cm=90,
                ),
            ],
        )
        pattern = {
            "name": "test_reach_ko",
            "room_width_cm": 400,
            "room_depth_cm": 400,
            "rows": [{"blocks": [{
                "type": "BLOCK_2",
                "orientation": 0,
                "gap_cm": 0,
            }]}],
            "row_gaps_cm": [0],
            "room_openings": [{
                "face": "south", "offset_cm": 0, "width_cm": 90,
                "has_door": True,
            }],
        }
        # paths: desk 0 reachable, desk 1 unreachable (empty path)
        fake_circ = CirculationResult(
            grade="F",
            connectivity_pct=40.0,
            isolated_area_pct=20.0,
            avg_detour_ratio=2.0,
            worst_detour_ratio=3.0,
            path_widths=[60.0],
            paths=[[(1, 1)], []],
        )
        with patch(
            "olm.core.circulation_analysis.analyse",
            return_value=fake_circ,
        ):
            score = score_candidate(pattern, room, "standard3")

        assert score.all_desks_reachable is False
        assert score.dim_reachability == 0.0
        assert score.room_grade == "F"


# ---------------------------------------------------------------------------
# 6ter — dominated too_tight removed
# ---------------------------------------------------------------------------

class Test6terDominated:
    """Too_tight with n_desks <= max_working are removed."""

    def test_dominated_too_tight_removed(self):
        fw = _make_score(
            name="fw_3", n_desks=3, passage_grade="A",
            dim_reachability=1.0, fit_class="fitting",
        )
        tight = _make_score(
            name="tight_2", n_desks=2, passage_grade="D",
            dim_reachability=0.4, fit_class="fitting",
            min_passage_cm=60.0,
        )
        final = _filter([fw, tight])
        names = [s.pattern_name for s in final]
        assert "fw_3" in names
        assert "tight_2" not in names

    def test_too_tight_kept_if_more_desks(self):
        fw = _make_score(
            name="fw_2", n_desks=2, passage_grade="A",
            dim_reachability=1.0, fit_class="fitting",
        )
        tight = _make_score(
            name="tight_4", n_desks=4, passage_grade="D",
            dim_reachability=0.4, fit_class="fitting",
            min_passage_cm=60.0,
        )
        final = _filter([fw, tight])
        names = [s.pattern_name for s in final]
        assert "fw_2" in names
        assert "tight_4" in names

    def test_oversize_dominated_removed(self):
        fw = _make_score(
            name="fw_3", n_desks=3, passage_grade="A",
            dim_reachability=1.0, fit_class="fitting",
        )
        oversize = _make_score(
            name="oversize_2", n_desks=2,
            fit_class="oversize_1axis", oversize=True,
            overflow_cm=10.0, passage_grade="A",
            dim_reachability=1.0, min_passage_cm=100.0,
        )
        final = _filter([fw, oversize])
        names = [s.pattern_name for s in final]
        assert "oversize_2" not in names

    def test_oversize_kept_if_more_desks(self):
        fw = _make_score(
            name="fw_2", n_desks=2, passage_grade="A",
            dim_reachability=1.0, fit_class="fitting",
        )
        oversize = _make_score(
            name="oversize_4", n_desks=4,
            fit_class="oversize_1axis", oversize=True,
            overflow_cm=10.0, passage_grade="A",
            dim_reachability=1.0, min_passage_cm=100.0,
        )
        final = _filter([fw, oversize])
        names = [s.pattern_name for s in final]
        assert "oversize_4" in names


# ---------------------------------------------------------------------------
# 6ter — max_working == 0 -> nothing removed
# ---------------------------------------------------------------------------

class Test6terMaxWorkingZero:
    """When no fits_well exists, all too_tight are kept."""

    def test_all_too_tight_kept_when_no_fits_well(self):
        tight_a = _make_score(
            name="tight_a", n_desks=3, passage_grade="D",
            dim_reachability=0.4, fit_class="fitting",
            min_passage_cm=60.0,
        )
        tight_b = _make_score(
            name="tight_b", n_desks=2, passage_grade="D",
            dim_reachability=0.4, fit_class="fitting",
            min_passage_cm=60.0,
        )
        final = _filter([tight_a, tight_b])
        assert len(final) == 2


# ---------------------------------------------------------------------------
# by_standard recalculated
# ---------------------------------------------------------------------------

class TestByStandard:
    """by_standard reflects survivors, not the original match_result."""

    def test_by_standard_from_survivors(self):
        impossible = _make_score(
            name="best_orig", dim_reachability=0,
            all_desks_reachable=False, room_grade="F", n_desks=4,
        )
        good = _make_score(
            name="fallback", dim_reachability=1.0, n_desks=2,
            passage_grade="A",
        )
        _, by_std = _filter_with_by_std([impossible, good])
        assert by_std["standard3"] == "fallback"

    def test_by_standard_best_effort_when_all_removed(self):
        """D-317: sole impossible → best_effort fallback, not None."""
        impossible = _make_score(
            name="only", dim_reachability=0,
            all_desks_reachable=False, room_grade="F",
        )
        final, by_std = _filter_with_by_std([impossible])
        assert len(final) == 1
        assert final[0].best_effort is True
        assert by_std["standard3"] == "only"

    def test_by_standard_multiple_standards(self):
        """D-317: fallback is global (not per-standard). When at least
        one standard survives, the other may still have None."""
        s3 = _make_score(
            name="s3_good", standard="standard3",
            dim_reachability=1.0, passage_grade="A",
        )
        s1_bad = _make_score(
            name="s1_bad", standard="standard1",
            dim_reachability=0, all_desks_reachable=False,
            room_grade="F",
        )
        final, by_std = _filter_with_by_std([s3, s1_bad])
        assert by_std["standard3"] == "s3_good"
        # s1_bad removed; global list not empty → no fallback for std1.
        assert by_std["standard1"] is None


# ---------------------------------------------------------------------------
# fewer_desks always kept
# ---------------------------------------------------------------------------

class TestFewerDesksKept:
    """fewer_desks candidates are never removed by 6ter."""

    def test_fewer_desks_kept(self):
        fw = _make_score(
            name="fw_3", n_desks=3, passage_grade="A",
            dim_reachability=1.0, fit_class="fitting",
        )
        fewer = _make_score(
            name="fewer_2", n_desks=2, passage_grade="A",
            dim_reachability=1.0, fit_class="fitting",
        )
        final = _filter([fw, fewer])
        names = [s.pattern_name for s in final]
        assert "fewer_2" in names
        cat = candidate_category(fewer, 3)
        assert cat == "fewer_desks"
