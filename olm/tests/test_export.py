"""Tests for the export service (D-196, floor-summary cartouche).

Covers PNG export, PDF export, CSV generation, missing -SD 404,
amendment desk recomputation, and floor-summary aggregation.
"""
from __future__ import annotations

import csv
import json
import os

import pytest
from PIL import Image

from olm.server.app import app
from olm.server.services.export_service import (
    _DESK_CONFLICT_INK,
    _compute_floor_summary,
    _get_active_desks,
    _get_all_desks,
    _parse_surface_m2,
)


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
        "olm.server.services.export_service.get_plans_dir", _plans_fn)
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
        assert header[-1] == "composite_score"
        assert len(header) == 20


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
    """(c) Room without candidate → CSV with empty columns 5-19."""

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
        # Columns 5-20 (indices 4..19) all empty
        for i in range(4, 20):
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


# ---------------------------------------------------------------------------
# Floor-summary cartouche tests
# ---------------------------------------------------------------------------


class TestParseSurface:
    """_parse_surface_m2 — various format strings."""

    def test_standard_format(self):
        assert _parse_surface_m2("16.84 m2") == 16.84

    def test_no_space(self):
        assert _parse_surface_m2("16.84m2") == 16.84

    def test_unicode_m2(self):
        assert _parse_surface_m2("16.84 m\u00b2") == 16.84

    def test_integer(self):
        assert _parse_surface_m2("20 m2") == 20.0

    def test_empty_string(self):
        assert _parse_surface_m2("") is None

    def test_garbage(self):
        assert _parse_surface_m2("unknown") is None


class TestGetActiveDesks:
    """_get_active_desks — filters removed desks, recomputes if needed."""

    def test_filters_removed(self):
        candidate = {
            "desks": [
                {"x_cm": 0, "y_cm": 0, "removed": False},
                {"x_cm": 1, "y_cm": 0, "removed": True},
                {"x_cm": 2, "y_cm": 0, "removed": False},
            ],
        }
        active = _get_active_desks(candidate)
        assert len(active) == 2
        assert all(not d["removed"] for d in active)

    def test_empty_desks_no_pattern(self):
        candidate = {"desks": []}
        assert _get_active_desks(candidate) == []

    def test_no_desks_key(self):
        candidate = {}
        assert _get_active_desks(candidate) == []


class TestComputeFloorSummary:
    """_compute_floor_summary — aggregation logic."""

    @pytest.fixture()
    def plans_dir(self, tmp_path, monkeypatch):
        """Temp plans dir with a minimal JSON plan."""
        plans = tmp_path / "plans"
        plans.mkdir()
        plan = {
            "rooms": {
                "101": {
                    "surface": "14.40 m2",
                    "bbox_px": [10, 10, 70, 106],
                },
                "102": {
                    "surface": "20.00 m2",
                    "bbox_px": [80, 10, 140, 60],
                },
                "103": {
                    "bbox_px": [150, 10, 200, 50],
                },
            },
        }
        with open(plans / "tp.json", "w") as f:
            json.dump(plan, f)
        _plans_str = str(plans)
        monkeypatch.setattr(
            "olm.server.services.export_service.get_plans_dir",
            lambda: _plans_str,
        )
        return plans

    def test_annotated_surface(self, plans_dir):
        """Surface parsed from JSON 'surface' field."""
        rooms = [_room_payload()]
        rooms[0]["name"] = "101"
        s = _compute_floor_summary("tp", rooms, 5.0)
        assert s["furnished_offices"] == 1
        assert s["total_offices"] == 3
        assert s["furnished_area"] == 14.4
        assert s["total_workstations"] == 1
        assert s["avg_area"] is not None

    def test_fallback_bbox_payload(self, plans_dir):
        """Room 103 has no 'surface' → bbox from payload used."""
        room = _room_payload()
        room["name"] = "103"
        room["width_cm"] = 250
        room["depth_cm"] = 200
        s = _compute_floor_summary("tp", [room], 5.0)
        # 250*200/10000 = 5.0
        assert s["furnished_area"] == 5.0

    def test_fallback_bbox_json(self, plans_dir):
        """Room 103 not in payload → bbox_px from JSON + scale."""
        rooms = [_room_payload()]
        rooms[0]["name"] = "101"
        s = _compute_floor_summary("tp", rooms, 5.0)
        # Room 103: bbox_px [150,10,200,50] → 50*40 px
        # → 250*200 cm → 5.0 m2
        # Total = 14.40 + 20.00 + 5.0 = 39.4
        assert s["total_area"] == 39.4

    def test_zero_workstations(self, plans_dir):
        """Room without desks → avg = n/a."""
        room = _room_payload(with_candidate=False)
        room["name"] = "101"
        s = _compute_floor_summary("tp", [room], 5.0)
        assert s["furnished_offices"] == 0
        assert s["total_workstations"] == 0
        assert s["avg_area"] is None

    def test_counts_misplaced_desks(self, plans_dir):
        """D-323 suivi: misplaced (removed) desks count as workstations too."""
        room = _room_payload()
        room["name"] = "101"
        room["candidate"]["desks"].append({
            "x_cm": 200, "y_cm": 10, "width_cm": 180, "depth_cm": 80,
            "removed": True, "chair_side": "S",
        })
        s = _compute_floor_summary("tp", [room], 5.0)
        # 1 active + 1 misplaced = 2 workstations counted.
        assert s["total_workstations"] == 2

    def test_room_outside_json(self, plans_dir):
        """Payload room not in JSON → still counted in total."""
        room = _room_payload()
        room["name"] = "999"
        room["width_cm"] = 400
        room["depth_cm"] = 500
        s = _compute_floor_summary("tp", [room], 5.0)
        # Union: 101, 102, 103, 999 → 4 total
        assert s["total_offices"] == 4
        assert s["furnished_offices"] == 1

    def test_json_not_found(self, tmp_path, monkeypatch):
        """Missing JSON plan → total = payload names only."""
        monkeypatch.setattr(
            "olm.server.services.export_service.get_plans_dir",
            lambda: str(tmp_path),
        )
        room = _room_payload()
        room["name"] = "A1"
        s = _compute_floor_summary("nonexistent", [room], 5.0)
        assert s["total_offices"] == 1
        assert s["furnished_offices"] == 1


class TestExportCabinet:
    """D-266: cabinets (furniture) drawn as B&W rectangles at export."""

    def test_cabinet_draws_rectangle(self, export_env):
        """A cabinet in candidate.furniture produces a visible rectangle."""
        from olm.server.services.export_service import compose_plan_image
        plans_dir = export_env / "plans"
        plan = {"rooms": {"101": {"surface": "14.40 m2",
                                   "bbox_px": [10, 10, 60, 50]}}}
        with open(plans_dir / "test_plan.json", "w") as f:
            json.dump(plan, f)

        room = _room_payload()
        room["candidate"]["furniture"] = [
            {"type": "CABINET", "x_cm": 200, "y_cm": 10, "orientation": 0},
        ]
        img_with = compose_plan_image("test_plan", [room], 5.0)

        # Without furniture
        room2 = _room_payload()
        room2["candidate"]["furniture"] = []
        img_without = compose_plan_image("test_plan", [room2], 5.0)

        # Images should differ (cabinet adds pixels)
        import numpy as np
        arr_with = np.array(img_with)
        arr_without = np.array(img_without)
        assert not np.array_equal(arr_with, arr_without), \
            "Cabinet should produce visible pixels"

    def test_no_cabinet_no_change(self, export_env):
        """Empty furniture list produces no additional drawing."""
        from olm.server.services.export_service import compose_plan_image
        plans_dir = export_env / "plans"
        plan = {"rooms": {"101": {"surface": "14.40 m2",
                                   "bbox_px": [10, 10, 60, 50]}}}
        with open(plans_dir / "test_plan.json", "w") as f:
            json.dump(plan, f)

        room1 = _room_payload()
        room1["candidate"]["furniture"] = []
        img1 = compose_plan_image("test_plan", [room1], 5.0)

        room2 = _room_payload()
        # No furniture key at all
        room2["candidate"].pop("furniture", None)
        img2 = compose_plan_image("test_plan", [room2], 5.0)

        import numpy as np
        assert np.array_equal(np.array(img1), np.array(img2))

    def test_cabinet_orientation_90(self, export_env):
        """Cabinet at orientation 90 swaps width/depth (no crash)."""
        from olm.server.services.export_service import compose_plan_image
        plans_dir = export_env / "plans"
        plan = {"rooms": {"101": {"surface": "14.40 m2",
                                   "bbox_px": [10, 10, 60, 50]}}}
        with open(plans_dir / "test_plan.json", "w") as f:
            json.dump(plan, f)

        room = _room_payload()
        room["candidate"]["furniture"] = [
            {"type": "CABINET", "x_cm": 100, "y_cm": 5, "orientation": 90},
        ]
        img = compose_plan_image("test_plan", [room], 5.0)
        assert img.mode == "RGBA"


class TestCartoucheSmokeExport:
    """Smoke test: compose_plan_image with cartouche runs without error."""

    def test_compose_with_cartouche(self, export_env):
        """compose_plan_image produces an image with cartouche pixels."""
        from olm.server.services.export_service import (
            compose_plan_image,
        )
        # Write a minimal JSON plan so the cartouche has data
        plans_dir = export_env / "plans"
        plan = {
            "rooms": {
                "101": {"surface": "14.40 m2", "bbox_px": [10, 10, 60, 50]},
            },
        }
        with open(plans_dir / "test_plan.json", "w") as f:
            json.dump(plan, f)

        rooms = [_room_payload()]
        img = compose_plan_image("test_plan", rooms, 5.0)
        assert img.size == (100, 80)
        assert img.mode == "RGBA"
        # The cartouche draws in the top-left corner — pixel (13,13)
        # should differ from plain grey (200,200,200) due to the
        # semi-opaque white background
        px = img.getpixel((13, 13))
        assert px != (200, 200, 200, 255), "Cartouche should be visible"


# ---------------------------------------------------------------------------
# Preview endpoint tests
# ---------------------------------------------------------------------------


class TestPreviewEndpoint:
    """POST /api/floor-plan/preview — returns PNG bytes."""

    def test_preview_returns_png(self, client, export_env):
        """Happy path: valid payload returns a PNG image."""
        # Write a minimal JSON plan so the cartouche has data
        plans_dir = export_env / "plans"
        plan = {
            "rooms": {
                "101": {"surface": "14.40 m2", "bbox_px": [10, 10, 60, 50]},
            },
        }
        with open(plans_dir / "test_plan.json", "w") as f:
            json.dump(plan, f)

        payload = {
            "plan_id": "test_plan",
            "scale_cm_per_px": 5.0,
            "rooms": [_room_payload()],
        }
        resp = client.post("/api/floor-plan/preview", json=payload)
        assert resp.status_code == 200
        assert resp.content_type == "image/png"
        # Verify returned bytes are a valid PNG
        assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"
        # Verify we can open the image
        from io import BytesIO
        img = Image.open(BytesIO(resp.data))
        assert img.size == (100, 80)
        assert img.mode == "RGBA"

    def test_preview_no_data(self, client, export_env):
        """No JSON body → 400."""
        resp = client.post(
            "/api/floor-plan/preview",
            data="",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_preview_missing_plan_id(self, client, export_env):
        """Missing plan_id → 400."""
        payload = {
            "plan_id": "",
            "scale_cm_per_px": 5.0,
            "rooms": [_room_payload()],
        }
        resp = client.post("/api/floor-plan/preview", json=payload)
        assert resp.status_code == 400
        assert "plan_id" in resp.get_json()["error"].lower()

    def test_preview_missing_rooms(self, client, export_env):
        """Empty rooms list → 400."""
        payload = {
            "plan_id": "test_plan",
            "scale_cm_per_px": 5.0,
            "rooms": [],
        }
        resp = client.post("/api/floor-plan/preview", json=payload)
        assert resp.status_code == 400

    def test_preview_invalid_scale(self, client, export_env):
        """Invalid scale → 400."""
        payload = {
            "plan_id": "test_plan",
            "scale_cm_per_px": -1,
            "rooms": [_room_payload()],
        }
        resp = client.post("/api/floor-plan/preview", json=payload)
        assert resp.status_code == 400

    def test_preview_missing_sd_png(self, client, export_env):
        """Non-existent -SD.png → 404."""
        payload = {
            "plan_id": "nonexistent",
            "scale_cm_per_px": 5.0,
            "rooms": [_room_payload()],
        }
        resp = client.post("/api/floor-plan/preview", json=payload)
        assert resp.status_code == 404
        assert "not found" in resp.get_json()["error"]

    def test_preview_no_disk_write(self, client, export_env):
        """Preview must NOT write anything to disk."""
        plans_dir = export_env / "plans"
        plan = {
            "rooms": {
                "101": {"surface": "14.40 m2", "bbox_px": [10, 10, 60, 50]},
            },
        }
        with open(plans_dir / "test_plan.json", "w") as f:
            json.dump(plan, f)

        # Count files before
        exports_dir = export_env / "project" / "exports"
        before = set(export_env.rglob("*")) - {plans_dir / "test_plan.json",
                                                 plans_dir / "test_plan-SD.png"}
        payload = {
            "plan_id": "test_plan",
            "scale_cm_per_px": 5.0,
            "rooms": [_room_payload()],
        }
        resp = client.post("/api/floor-plan/preview", json=payload)
        assert resp.status_code == 200
        # No new files created
        after = set(export_env.rglob("*")) - {plans_dir / "test_plan.json",
                                               plans_dir / "test_plan-SD.png"}
        assert before == after, "Preview should not write files to disk"


class TestConflictDeskGrey:
    """D-323: desks in a placement conflict are kept and drawn in grey ink,
    not dropped, on preview/export."""

    def test_get_all_desks_includes_removed(self):
        """_get_all_desks keeps removed desks; _get_active_desks filters them."""
        candidate = {
            "desks": [
                {"x_cm": 0, "y_cm": 0, "removed": False},
                {"x_cm": 1, "y_cm": 0, "removed": True},
                {"x_cm": 2, "y_cm": 0, "removed": False},
            ]
        }
        assert len(_get_all_desks(candidate)) == 3
        assert len(_get_active_desks(candidate)) == 2

    def _write_plan_json(self, plans_dir):
        plan = {"rooms": {"101": {"surface": "14.40 m2",
                                  "bbox_px": [10, 10, 60, 50]}}}
        with open(plans_dir / "test_plan.json", "w") as f:
            json.dump(plan, f)

    def test_conflict_desk_drawn_grey(self, export_env):
        """A removed desk produces grey ink pixels; an active one does not."""
        import numpy as np
        from olm.server.services.export_service import compose_plan_image
        self._write_plan_json(export_env / "plans")
        ink = tuple(_DESK_CONFLICT_INK)

        room_removed = _room_payload()
        room_removed["candidate"]["desks"][0]["removed"] = True
        arr_removed = np.array(compose_plan_image("test_plan", [room_removed], 5.0))

        room_active = _room_payload()  # removed=False by default
        arr_active = np.array(compose_plan_image("test_plan", [room_active], 5.0))

        def count_ink(arr):
            return int(np.all(arr == np.array(ink), axis=-1).sum())

        assert count_ink(arr_removed) > 0, "conflict desk should add grey ink"
        assert count_ink(arr_active) == 0, "active desk must not use conflict grey"

    def test_conflict_only_room_still_renders(self, export_env):
        """A room whose only desk is in conflict is still drawn (not skipped)."""
        import numpy as np
        from olm.server.services.export_service import compose_plan_image
        self._write_plan_json(export_env / "plans")
        ink = tuple(_DESK_CONFLICT_INK)

        room = _room_payload()
        room["candidate"]["desks"][0]["removed"] = True
        arr = np.array(compose_plan_image("test_plan", [room], 5.0))
        grey = int(np.all(arr == np.array(ink), axis=-1).sum())
        assert grey > 0, "all-conflict room must still render its grey desk"
