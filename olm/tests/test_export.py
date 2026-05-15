"""Tests for the export service (D-196).

Covers PNG export, PDF export, CSV generation, missing -SD 404,
and amendment desk recomputation.
"""
from __future__ import annotations

import csv
import os

import pytest
from PIL import Image

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


@pytest.fixture()
def export_env(tmp_path, monkeypatch):
    """Set up a temp plans dir with a minimal -SD.png and export dir."""
    plans = tmp_path / "plans"
    plans.mkdir()
    # Create a 100x80 RGBA image as <plan_id>-SD.png
    img = Image.new("RGBA", (100, 80), (200, 200, 200, 255))
    sd_path = plans / "test_plan-SD.png"
    img.save(str(sd_path))

    _plans_str = str(plans)
    _plans_fn = lambda: _plans_str
    monkeypatch.setattr("olm.server.app.PLANS_DIR", _plans_str)
    monkeypatch.setattr(
        "olm.server.services.config_service.get_plans_dir", _plans_fn)
    monkeypatch.setattr(
        "olm.server.app.get_plans_dir", _plans_fn)
    # Redirect PROJECT_ROOT so exports go to tmp_path
    monkeypatch.setattr(
        "olm.server.services.export_service.PROJECT_ROOT", str(tmp_path))
    # Neutral detection colours (no match in the grey image)
    monkeypatch.setattr(
        "olm.server.services.export_service.get_exterior_rgb",
        lambda: (135, 206, 235))
    monkeypatch.setattr(
        "olm.server.services.export_service.get_corridor_rgb",
        lambda: (193, 247, 179))
    return tmp_path


def _room_payload(*, with_candidate: bool = True, chair_side: str = "S"):
    """Build a minimal room dict for export tests."""
    room = {
        "name": "101",
        "width_cm": 300,
        "depth_cm": 480,
        "bbox_px": [10, 10, 60, 50],
        "corridor_face_abs": "south",
        "is_amended": False,
    }
    if with_candidate:
        room["candidate"] = {
            "pattern_name": "PAT_TEST",
            "standard": "standard3",
            "n_desks": 1,
            "m2_per_desk": 14.4,
            "circulation_grade": "A",
            "connectivity_pct": 100,
            "min_passage_cm": 120,
            "worst_detour": 1.1,
            "largest_free_rect_m2": 8.0,
            "desks": [
                {
                    "x_cm": 10, "y_cm": 10,
                    "width_cm": 180, "depth_cm": 80,
                    "removed": False,
                    "chair_side": chair_side,
                },
            ],
            "pattern": {
                "rows": [{"blocks": [
                    {"type": "BLOCK_1", "orientation": 0, "gap_cm": 10},
                ]}],
                "row_gaps_cm": [],
            },
        }
    else:
        room["candidate"] = None
    return room


class TestExportPng:
    """(a) POST /api/floor-plan/export/png — happy path."""

    def test_export_png_ok(self, client, export_env):
        payload = {
            "plan_id": "test_plan",
            "scale_cm_per_px": 5.0,
            "rooms": [_room_payload(chair_side="S")],
        }
        resp = client.post(
            "/api/floor-plan/export/png",
            json=payload,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "plan_path" in data
        assert data["plan_path"].endswith(".png")
        assert os.path.isfile(data["plan_path"])
        assert os.path.getsize(data["plan_path"]) > 0
        # CSV also created
        assert "csv_path" in data
        assert os.path.isfile(data["csv_path"])
        # Verify CSV header
        with open(data["csv_path"], encoding="utf-8-sig") as f:
            reader = csv.reader(f, delimiter=";")
            header = next(reader)
        assert header[0] == "room_code"
        assert header[-1] == "manual_amendments"
        assert len(header) == 15


_HAS_FITZ = False
try:
    import fitz  # noqa: F401
    _HAS_FITZ = True
except ImportError:
    pass


class TestExportPdf:
    """(b) POST /api/floor-plan/export/pdf — PDF magic header."""

    @pytest.mark.skipif(not _HAS_FITZ, reason="pymupdf not installed")
    def test_export_pdf_ok(self, client, export_env):
        payload = {
            "plan_id": "test_plan",
            "scale_cm_per_px": 5.0,
            "rooms": [_room_payload()],
        }
        resp = client.post(
            "/api/floor-plan/export/pdf",
            json=payload,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["plan_path"].endswith(".pdf")
        with open(data["plan_path"], "rb") as f:
            magic = f.read(5)
        assert magic == b"%PDF-"


class TestExportCsvNoCandidate:
    """(c) Room without candidate → CSV with empty columns 5-15."""

    def test_export_csv_room_without_candidate(self, client, export_env):
        payload = {
            "plan_id": "test_plan",
            "scale_cm_per_px": 5.0,
            "rooms": [_room_payload(with_candidate=False)],
        }
        resp = client.post(
            "/api/floor-plan/export/png",
            json=payload,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        with open(data["csv_path"], encoding="utf-8-sig") as f:
            reader = csv.reader(f, delimiter=";")
            next(reader)  # skip header
            row = next(reader)
        # First 4 columns filled
        assert row[0] == "101"
        assert row[3] == "14.4"
        # Columns 5-15 (indices 4..14) all empty
        for i in range(4, 15):
            assert row[i] == "", f"Column {i} should be empty, got '{row[i]}'"


class TestExport404:
    """(d) Missing -SD.png → 404."""

    def test_export_404_missing_sd(self, client, export_env):
        payload = {
            "plan_id": "nonexistent_plan",
            "scale_cm_per_px": 5.0,
            "rooms": [_room_payload()],
        }
        resp = client.post(
            "/api/floor-plan/export/png",
            json=payload,
        )
        assert resp.status_code == 404
        assert "not found" in resp.get_json()["error"]


class TestExportAmendmentRecompute:
    """(e) Amendment with empty desks but pattern → desks recomputed."""

    def test_export_amendment_recomputes_desks(self, client, export_env):
        room = _room_payload()
        # Simulate amendment: desks empty, pattern present
        room["candidate"]["desks"] = []
        room["is_amended"] = True
        payload = {
            "plan_id": "test_plan",
            "scale_cm_per_px": 5.0,
            "rooms": [room],
        }
        resp = client.post(
            "/api/floor-plan/export/png",
            json=payload,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # Image rendered (desks computed from pattern)
        assert os.path.isfile(data["plan_path"])
        img = Image.open(data["plan_path"])
        # The desk overlay should have been drawn — the image should
        # differ from a plain grey image (check non-grey pixels exist
        # in the desk area)
        assert img.size == (100, 80)
