"""Tests for _filter_impossible_openings (extract.py)."""
from __future__ import annotations

import numpy as np
import pytest

from olm.ingestion.extract import _filter_impossible_openings


def _make_binary(w: int, h: int, walls: list[tuple]) -> np.ndarray:
    """Create a binary image (True = wall) with specified wall rectangles."""
    binary = np.zeros((h, w), dtype=bool)
    for x0, y0, x1, y1 in walls:
        binary[y0:y1, x0:x1] = True
    return binary


class TestFilterImpossibleOpenings:
    """Synthetic tests for the impossible-opening filter."""

    def test_no_openings_passthrough(self):
        """No openings → returns empty list."""
        binary = _make_binary(200, 200, [])
        result = _filter_impossible_openings(
            [], (10, 10, 190, 190), "south", binary, 1.0)
        assert result == []

    def test_small_opening_kept(self):
        """Opening covering <70% of face → kept."""
        binary = _make_binary(200, 200, [])
        openings = [{"face": "north", "offset_cm": 0, "width_cm": 50}]
        # Face length = 180 cm (190-10), 50/180 = 28% < 70%
        result = _filter_impossible_openings(
            openings, (10, 10, 190, 190), "south", binary, 1.0)
        assert len(result) == 1

    def test_corridor_face_excluded(self):
        """Opening on corridor face → never filtered, even if >70%."""
        # Wall behind to make sure the filter WOULD trigger on non-corridor
        binary = _make_binary(200, 200, [(0, 190, 200, 200)])
        openings = [{"face": "south", "offset_cm": 0, "width_cm": 170}]
        # 170/180 = 94% but it's the corridor face
        result = _filter_impossible_openings(
            openings, (10, 10, 190, 190), "south", binary, 1.0)
        assert len(result) == 1

    def test_large_opening_wall_behind_dropped(self):
        """Opening >70% with wall behind → artefact → dropped."""
        # Room bbox: (10, 10, 190, 190). North face at y=10.
        # Wall at y=5 (behind the north face).
        binary = _make_binary(200, 200, [(10, 4, 190, 6)])
        openings = [{"face": "north", "offset_cm": 0, "width_cm": 170}]
        # 170/180 = 94%, and there's a wall 5px behind → drop
        result = _filter_impossible_openings(
            openings, (10, 10, 190, 190), "south", binary, 1.0,
            probe_depth_cm=20.0)
        assert len(result) == 0

    def test_large_opening_no_wall_behind_kept(self):
        """Opening >70% but no wall behind → real passage → kept."""
        # No wall pixels at all behind the north face.
        binary = _make_binary(200, 200, [])
        openings = [{"face": "north", "offset_cm": 0, "width_cm": 170}]
        result = _filter_impossible_openings(
            openings, (10, 10, 190, 190), "south", binary, 1.0,
            probe_depth_cm=20.0)
        assert len(result) == 1

    def test_east_face_wall_behind(self):
        """East face: opening >70% with wall behind → dropped."""
        # East face at x=190. Wall at x=195.
        binary = _make_binary(200, 200, [(194, 10, 196, 190)])
        openings = [{"face": "east", "offset_cm": 0, "width_cm": 170}]
        result = _filter_impossible_openings(
            openings, (10, 10, 190, 190), "south", binary, 1.0,
            probe_depth_cm=20.0)
        assert len(result) == 0

    def test_west_face_wall_behind(self):
        """West face: opening >70% with wall behind → dropped."""
        # West face at x=10. Wall at x=5.
        binary = _make_binary(200, 200, [(4, 10, 6, 190)])
        openings = [{"face": "west", "offset_cm": 0, "width_cm": 170}]
        result = _filter_impossible_openings(
            openings, (10, 10, 190, 190), "south", binary, 1.0,
            probe_depth_cm=20.0)
        assert len(result) == 0

    def test_mixed_faces_only_guilty_dropped(self):
        """Only the face with >70% + wall behind is filtered."""
        # Wall behind north only.
        binary = _make_binary(200, 200, [(10, 4, 190, 6)])
        openings = [
            {"face": "north", "offset_cm": 0, "width_cm": 170},  # guilty
            {"face": "east", "offset_cm": 0, "width_cm": 30},    # innocent
        ]
        result = _filter_impossible_openings(
            openings, (10, 10, 190, 190), "south", binary, 1.0,
            probe_depth_cm=20.0)
        assert len(result) == 1
        assert result[0]["face"] == "east"

    def test_custom_ratio(self):
        """Custom max_ratio=0.5 triggers on smaller coverage."""
        binary = _make_binary(200, 200, [(10, 4, 190, 6)])
        openings = [{"face": "north", "offset_cm": 0, "width_cm": 100}]
        # 100/180 = 55%, default 0.7 would keep, but 0.5 triggers
        result = _filter_impossible_openings(
            openings, (10, 10, 190, 190), "south", binary, 1.0,
            max_ratio=0.5, probe_depth_cm=20.0)
        assert len(result) == 0

    def test_scale_independent(self):
        """Filter works at different scales (0.5 cm/px)."""
        # At 0.5 cm/px, 1px = 0.5cm. Room 100x100 cm = 200x200 px.
        # North face at y=0. Wall 3px behind (y=-3 → clamp to y=0 area).
        # Use bbox (0, 0, 200, 200), wall at y outside...
        # Simpler: bbox (20, 20, 220, 220), wall at y=15.
        binary = _make_binary(250, 250, [(20, 14, 220, 16)])
        openings = [{"face": "north", "offset_cm": 0, "width_cm": 90}]
        # Face len = (220-20)*0.5 = 100 cm. 90/100 = 90% → triggers.
        result = _filter_impossible_openings(
            openings, (20, 20, 220, 220), "south", binary, 0.5,
            probe_depth_cm=20.0)
        assert len(result) == 0
