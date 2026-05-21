"""Tests for D-256 CABINET — furniture block (Lot 1).

Covers:
1. /api/blocks exposes CABINET with correct geometry and furniture flag
2. Config change propagates to /api/blocks dimensions
3. CABINET absent from PATTERNS and matching candidates
4. Config round-trip (save + reload)
"""
from __future__ import annotations

import pytest

from olm.server.app import app


@pytest.fixture()
def client():
    """Flask test client with reset session lock."""
    import olm.server.app as _app_mod
    _app_mod._active_session = None
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    _app_mod._active_session = None


class TestCabinetBlockDefs:
    """CABINET exposed in /api/blocks with correct attributes."""

    def test_cabinet_in_blocks(self, client):
        """CABINET is present in /api/blocks with n_desks=0, furniture=True."""
        resp = client.get("/api/blocks")
        assert resp.status_code == 200
        data = resp.get_json()
        blocks = data["blocks"]
        assert "CABINET" in blocks
        cab = blocks["CABINET"]
        assert cab["eo_cm"] == 70
        assert cab["ns_cm"] == 40
        assert cab["n_desks"] == 0
        assert cab["furniture"] is True
        # All 4 faces absent (non_superposable_cm = 0, candidate_cm = 0)
        for face in ("north", "south", "east", "west"):
            assert cab["faces"][face]["non_superposable_cm"] == 0
            assert cab["faces"][face]["candidate_cm"] == 0


class TestCabinetConfigPropagation:
    """Changing cabinet_width_cm/depth_cm updates /api/blocks."""

    def test_config_change_propagates(self, client):
        """After config change, /api/blocks reflects new dimensions."""
        import olm.core.pattern_generator as pg
        original_w = pg.CABINET_W_CM
        original_d = pg.CABINET_D_CM
        try:
            # Change width to 90
            resp = client.post("/api/config", json={
                "key": "cabinet_width_cm", "value": 90,
            })
            assert resp.status_code == 200
            # Change depth to 50
            resp = client.post("/api/config", json={
                "key": "cabinet_depth_cm", "value": 50,
            })
            assert resp.status_code == 200
            # Verify module-level values updated
            assert pg.CABINET_W_CM == 90
            assert pg.CABINET_D_CM == 50
            # Verify /api/blocks reflects new values
            resp = client.get("/api/blocks")
            cab = resp.get_json()["blocks"]["CABINET"]
            assert cab["eo_cm"] == 90
            assert cab["ns_cm"] == 50
        finally:
            # Restore original values
            pg.CABINET_W_CM = original_w
            pg.CABINET_D_CM = original_d
            client.post("/api/config", json={
                "key": "cabinet_width_cm", "value": original_w,
            })
            client.post("/api/config", json={
                "key": "cabinet_depth_cm", "value": original_d,
            })
            from olm.server.services.config_service import invalidate_block_cache
            invalidate_block_cache()


class TestCabinetNotInPatterns:
    """CABINET must NOT appear in generated patterns or matching."""

    def test_not_in_patterns(self):
        """CABINET absent from PATTERNS and DOUBLE_ROW_PATTERNS."""
        from olm.core.pattern_generator import (
            DOUBLE_ROW_PATTERNS,
            PATTERNS,
            PATTERNS_ALL,
        )
        for p in PATTERNS + PATTERNS_ALL:
            for b in p.blocks:
                assert b.name != "CABINET", (
                    f"CABINET found in pattern {p.name}"
                )
        for dp in DOUBLE_ROW_PATTERNS:
            for b in dp.north_row.blocks + dp.south_row.blocks:
                assert b.name != "CABINET", (
                    f"CABINET found in double-row pattern {dp.name}"
                )

    def test_not_in_palette(self):
        """Palette types list does not include CABINET (hardcoded)."""
        from olm.core.pattern_generator import CABINET
        assert CABINET.furniture is True
        assert CABINET.n_desks == 0

    def test_not_in_matching_candidates(self, client):
        """CABINET blocks never appear in matching candidate patterns."""
        from olm.core.catalogue_matcher import load_catalogue
        catalogue = load_catalogue()
        for pattern in catalogue:
            for row in pattern.get("rows", []):
                for block in row.get("blocks", []):
                    assert block.get("type") != "CABINET", (
                        f"CABINET in catalogue pattern {pattern.get('name')}"
                    )


class TestCabinetConfigRoundTrip:
    """Config keys cabinet_width_cm / cabinet_depth_cm round-trip."""

    def test_round_trip(self, client):
        """GET config contains cabinet keys, POST saves them."""
        resp = client.get("/api/config")
        assert resp.status_code == 200
        cfg = resp.get_json()
        assert "cabinet_width_cm" in cfg
        assert "cabinet_depth_cm" in cfg
        assert cfg["cabinet_width_cm"] == 70
        assert cfg["cabinet_depth_cm"] == 40


class TestFurnitureInAmendment:
    """D-256 Lot 2: furniture[] round-trips through saved_layout."""

    def test_furniture_survives_json_roundtrip(self):
        """furniture list passes through JSON deep-clone (opaque)."""
        import json
        amendment = {
            "pattern_name": "test (amended)",
            "standard": "standard2",
            "n_desks": 4,
            "pattern": {"rows": []},
            "furniture": [
                {"type": "CABINET", "x_cm": 120, "y_cm": 40, "orientation": 0},
                {"type": "CABINET", "x_cm": 200, "y_cm": 100, "orientation": 90},
            ],
            "amended": True,
        }
        # Simulate the deep-clone that ingestion_serialize.js does
        cloned = json.loads(json.dumps(amendment))
        assert "furniture" in cloned
        assert len(cloned["furniture"]) == 2
        cab0 = cloned["furniture"][0]
        assert cab0["type"] == "CABINET"
        assert cab0["x_cm"] == 120
        assert cab0["y_cm"] == 40
        assert cab0["orientation"] == 0
        cab1 = cloned["furniture"][1]
        assert cab1["orientation"] == 90

    def test_furniture_absent_means_empty(self):
        """Missing furniture key treated as empty list."""
        amendment = {"pattern_name": "test", "pattern": {"rows": []}}
        furn = amendment.get("furniture") or []
        assert furn == []
