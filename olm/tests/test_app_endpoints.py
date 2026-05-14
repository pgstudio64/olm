"""Tests des 5 endpoints critiques de olm/server/app.py.

Couverture : reanalyze, floor-plan/match, plans/save, room-dsl/parse, config.
Ref audit 6.2 item 3.
"""
from __future__ import annotations

import io
import json
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers de validation structurelle
# ---------------------------------------------------------------------------

VALID_FACES = {"north", "south", "east", "west"}
VALID_GRADES = set("ABCDEF")


def _assert_window(w: dict[str, Any]) -> None:
    """Valide la structure d'une window."""
    assert "face" in w and isinstance(w["face"], str)
    assert w["face"] in VALID_FACES
    assert "offset_cm" in w and isinstance(w["offset_cm"], int)
    assert w["offset_cm"] >= 0
    assert "width_cm" in w and isinstance(w["width_cm"], int)
    assert w["width_cm"] > 0


def _assert_door(d: dict[str, Any]) -> None:
    """Valide la structure d'une door."""
    assert "face" in d and isinstance(d["face"], str)
    assert d["face"] in VALID_FACES
    assert "offset_cm" in d and isinstance(d["offset_cm"], int)
    assert d["offset_cm"] >= 0
    assert "width_cm" in d and isinstance(d["width_cm"], int)
    assert d["width_cm"] > 0
    assert "hinge_side" in d and d["hinge_side"] in {"left", "right"}
    assert "opens_inward" in d and isinstance(d["opens_inward"], bool)


def _assert_opening(o: dict[str, Any]) -> None:
    """Valide la structure d'une opening."""
    assert "face" in o and isinstance(o["face"], str)
    assert o["face"] in VALID_FACES
    assert "offset_cm" in o and isinstance(o["offset_cm"], int)
    assert o["offset_cm"] >= 0
    assert "width_cm" in o and isinstance(o["width_cm"], int)
    assert o["width_cm"] > 0


# ====================================================================
# 1. POST /api/room/reanalyze
# ====================================================================

class TestReanalyze:
    """Tests pour POST /api/room/reanalyze."""

    def test_happy_path(self, client, tiny_plan_png):
        """Payload valide retourne 200 avec windows et openings."""
        resp = client.post("/api/room/reanalyze", json={
            "plan_path": tiny_plan_png,
            "seed_px": [5, 5],
            "bbox_px": [0, 0, 10, 10],
            "scale_cm_per_px": 1.0,
            "mode": "preprocessed",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "windows" in data
        assert "openings" in data
        assert isinstance(data["windows"], list)
        assert isinstance(data["openings"], list)
        for w in data["windows"]:
            _assert_window(w)
        for o in data["openings"]:
            _assert_opening(o)
        if "doors" in data:
            assert isinstance(data["doors"], list)
            for d in data["doors"]:
                _assert_door(d)

    def test_other_seeds_d159(self, client, tiny_plan_png):
        """other_seeds_px (D-159, fix K2/K5/K12/K25) est transmis sans crash."""
        resp = client.post("/api/room/reanalyze", json={
            "plan_path": tiny_plan_png,
            "seed_px": [5, 5],
            "bbox_px": [0, 0, 10, 10],
            "scale_cm_per_px": 1.0,
            "other_seeds_px": [[8, 8], [2, 2]],
            "mode": "preprocessed",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "windows" in data
        assert "openings" in data
        for w in data["windows"]:
            _assert_window(w)
        for o in data["openings"]:
            _assert_opening(o)
        if "doors" in data:
            assert isinstance(data["doors"], list)
            for d in data["doors"]:
                _assert_door(d)

    def test_missing_plan_path(self, client):
        """plan_path absent retourne 400."""
        resp = client.post("/api/room/reanalyze", json={
            "seed_px": [5, 5],
            "bbox_px": [0, 0, 10, 10],
            "scale_cm_per_px": 1.0,
        })
        assert resp.status_code == 400
        assert "plan_path" in resp.get_json()["error"]

    def test_invalid_plan_path(self, client):
        """plan_path inexistant retourne 400."""
        resp = client.post("/api/room/reanalyze", json={
            "plan_path": "/nonexistent/plan.png",
            "seed_px": [5, 5],
            "scale_cm_per_px": 1.0,
        })
        assert resp.status_code == 400
        assert "plan_path" in resp.get_json()["error"]

    def test_missing_seed_px(self, client, tiny_plan_png):
        """seed_px absent retourne 400."""
        resp = client.post("/api/room/reanalyze", json={
            "plan_path": tiny_plan_png,
            "bbox_px": [0, 0, 10, 10],
            "scale_cm_per_px": 1.0,
        })
        assert resp.status_code == 400
        assert "seed_px" in resp.get_json()["error"]

    def test_corridor_face_param(self, client, tiny_plan_png):
        """corridor_face (D-180) est accepte sans erreur."""
        resp = client.post("/api/room/reanalyze", json={
            "plan_path": tiny_plan_png,
            "seed_px": [5, 5],
            "bbox_px": [0, 0, 10, 10],
            "scale_cm_per_px": 1.0,
            "corridor_face": "south",
            "mode": "preprocessed",
        })
        assert resp.status_code == 200

    def test_bbox_not_integers(self, client, tiny_plan_png):
        """bbox_px avec des valeurs non entieres retourne 400."""
        resp = client.post("/api/room/reanalyze", json={
            "plan_path": tiny_plan_png,
            "seed_px": [5, 5],
            "bbox_px": ["a", "b", "c", "d"],
            "scale_cm_per_px": 1.0,
        })
        assert resp.status_code == 400
        assert "bbox_px" in resp.get_json()["error"]

    def test_inverted_bbox_treated_as_none(self, client, tiny_plan_png):
        """bbox_px inverse (x1<=x0) est ignore, pas d'erreur."""
        resp = client.post("/api/room/reanalyze", json={
            "plan_path": tiny_plan_png,
            "seed_px": [5, 5],
            "bbox_px": [10, 10, 0, 0],
            "scale_cm_per_px": 1.0,
            "mode": "preprocessed",
        })
        assert resp.status_code == 200

    def test_without_bbox(self, client, tiny_plan_png):
        """Appel sans bbox_px (seed-only) retourne 200."""
        resp = client.post("/api/room/reanalyze", json={
            "plan_path": tiny_plan_png,
            "seed_px": [5, 5],
            "scale_cm_per_px": 1.0,
            "mode": "preprocessed",
        })
        assert resp.status_code == 200

    def test_transparent_zones_and_doors(self, client, tiny_plan_png):
        """transparent_zones et doors sont transmis sans crash."""
        resp = client.post("/api/room/reanalyze", json={
            "plan_path": tiny_plan_png,
            "seed_px": [5, 5],
            "bbox_px": [0, 0, 10, 10],
            "scale_cm_per_px": 1.0,
            "transparent_zones": [
                {"x_cm": 0, "y_cm": 0, "width_cm": 2, "depth_cm": 2},
            ],
            "doors": [
                {"x": 3, "y": 9, "width": 2},
            ],
            "mode": "preprocessed",
        })
        assert resp.status_code == 200


# ====================================================================
# 2. POST /api/floor-plan/match
# ====================================================================

class TestFloorPlanMatch:
    """Tests pour POST /api/floor-plan/match."""

    def test_happy_path(
        self, client, sample_room_canonical, monkeypatch_catalogue,
    ):
        """Payload valide retourne 200 avec structure rooms complete."""
        resp = client.post("/api/floor-plan/match", json={
            "rooms": [sample_room_canonical],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "rooms" in data
        assert len(data["rooms"]) == 1
        room = data["rooms"][0]
        assert "by_standard" in room
        assert "all_candidates" in room
        assert "windows" in room
        assert "openings" in room
        assert "exclusion_zones" in room

        # all_candidates non vide sur le happy path
        candidates = room["all_candidates"]
        assert isinstance(candidates, list)
        assert len(candidates) > 0

        # Structure de chaque candidat
        for c in candidates:
            assert isinstance(c["pattern_name"], str)
            assert isinstance(c["standard"], str)
            assert isinstance(c["n_desks"], int)
            assert isinstance(c["m2_per_desk"], (int, float))
            assert isinstance(c["circulation_grade"], str)
            assert c["circulation_grade"] in VALID_GRADES
            assert isinstance(c["desks"], list)

        # Au moins un candidat a des desks non vides
        assert any(len(c["desks"]) > 0 for c in candidates)

        # Structure de chaque desk
        for c in candidates:
            for d in c["desks"]:
                assert isinstance(d["x_cm"], int)
                assert isinstance(d["y_cm"], int)
                assert isinstance(d["width_cm"], int)
                assert isinstance(d["depth_cm"], int)

        # by_standard[AFNOR_ADVICE] pointe vers un candidat existant
        by_std = room["by_standard"]
        assert "AFNOR_ADVICE" in by_std
        best_name = by_std["AFNOR_ADVICE"]
        assert best_name is not None
        candidate_names = {c["pattern_name"] for c in candidates}
        assert best_name in candidate_names

    def test_room_without_features(self, client, monkeypatch_catalogue):
        """Room sans windows ni openings retourne 200."""
        resp = client.post("/api/floor-plan/match", json={
            "rooms": [{
                "name": "empty",
                "width_cm": 400,
                "depth_cm": 500,
            }],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["rooms"]) == 1

    def test_missing_rooms_field(self, client):
        """Payload sans champ rooms retourne 400."""
        resp = client.post("/api/floor-plan/match", json={"other": 1})
        assert resp.status_code == 400
        assert "rooms" in resp.get_json()["error"]

    def test_empty_payload(self, client):
        """Payload JSON vide (sans rooms) retourne 400."""
        resp = client.post("/api/floor-plan/match", json={})
        assert resp.status_code == 400

    def test_multiple_rooms(self, client, sample_room_canonical, monkeypatch_catalogue):
        """Matching sur plusieurs rooms retourne un resultat par room."""
        room2 = dict(sample_room_canonical, name="102")
        resp = client.post("/api/floor-plan/match", json={
            "rooms": [sample_room_canonical, room2],
        })
        assert resp.status_code == 200
        assert len(resp.get_json()["rooms"]) == 2

    def test_room_with_origin_fields(self, client, monkeypatch_catalogue):
        """Windows/openings avec origin (D-131) sont preserves dans la reponse."""
        resp = client.post("/api/floor-plan/match", json={
            "rooms": [{
                "name": "orig",
                "width_cm": 300,
                "depth_cm": 480,
                "windows": [
                    {"face": "north", "offset_cm": 0, "width_cm": 300,
                     "origin": "manual"},
                ],
                "openings": [
                    {"face": "south", "offset_cm": 100, "width_cm": 90,
                     "has_door": True, "opens_inward": True,
                     "hinge_side": "left", "origin": "auto"},
                ],
            }],
        })
        assert resp.status_code == 200
        room = resp.get_json()["rooms"][0]
        assert room["windows"][0]["origin"] == "manual"
        assert room["openings"][0]["origin"] == "auto"


# ====================================================================
# 3. POST /api/plans/<plan_id>/save
# ====================================================================

class TestPlanSave:
    """Tests pour POST /api/plans/<plan_id>/save."""

    def test_happy_path(self, client, tmp_plans_dir, sample_plan_json):
        """Save ecrit le JSON sur disque et retourne ok."""
        resp = client.post(
            "/api/plans/test_plan/save",
            json=sample_plan_json,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

        json_path = tmp_plans_dir / "test_plan.json"
        assert json_path.exists()

    def test_roundtrip_preserves_fields(
        self, client, tmp_plans_dir, sample_plan_json,
    ):
        """Save puis load preserve exclusion_zones, walls_user_edited, doors."""
        client.post("/api/plans/rt_plan/save", json=sample_plan_json)

        json_path = tmp_plans_dir / "rt_plan.json"
        with open(json_path, encoding="utf-8") as f:
            loaded = json.load(f)

        room = loaded["rooms"]["101"]
        # D-122 P4 : doors separes des openings
        assert "doors" in room
        assert "openings" in room
        assert len(room["doors"]) == 1
        assert len(room["openings"]) == 1
        # walls_user_edited preserve
        assert room["walls_user_edited"] is True
        # exclusion_zones preservees
        assert len(room["exclusion_zones"]) == 1
        zone = room["exclusion_zones"][0]
        assert zone["width_cm"] == 50
        assert zone["depth_cm"] == 50

    def test_empty_payload(self, client, tmp_plans_dir):
        """Payload JSON vide retourne 400."""
        resp = client.post("/api/plans/bad/save", json={})
        assert resp.status_code == 400

    def test_save_creates_file(self, client, tmp_plans_dir):
        """Save cree le fichier meme si le plan n'existait pas."""
        resp = client.post("/api/plans/new_plan/save", json={"rooms": {}})
        assert resp.status_code == 200
        assert (tmp_plans_dir / "new_plan.json").exists()


# ====================================================================
# 3b. GET /api/plans/<plan_id>/metadata
# ====================================================================

class TestPlanMetadata:
    """Tests pour GET /api/plans/<plan_id>/metadata."""

    def test_v3_dict_rooms(self, client, tmp_plans_dir):
        """Metadata supporte JSON v3 (rooms = dict indexe par room_id)."""
        plan_json = {
            "building_id": "B1",
            "floor_id": "R+1",
            "drawing_scale_text": "1:100",
            "page_width_px": 2000,
            "page_height_px": 1500,
            "rooms": {
                "101": {
                    "seed_x": 500, "seed_y": 400,
                    "bbox_px": [400, 300, 700, 600],
                },
                "102": {
                    "seed_x": 900, "seed_y": 400,
                    "bbox_px": [800, 300, 1100, 600],
                },
            },
        }
        (tmp_plans_dir / "plan_v3.json").write_text(
            __import__("json").dumps(plan_json), encoding="utf-8")
        resp = client.get("/api/plans/plan_v3/metadata")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["building_id"] == "B1"
        assert data["floor_id"] == "R+1"
        assert data["image_size"] == [2000, 1500]
        assert len(data["rooms_summary"]) == 2
        names = {r["name"] for r in data["rooms_summary"]}
        assert names == {"101", "102"}
        for r in data["rooms_summary"]:
            assert len(r["bbox_px"]) == 4

    def test_missing_json(self, client, tmp_plans_dir):
        """Metadata retourne 404 si le JSON du plan est absent."""
        resp = client.get("/api/plans/inexistant/metadata")
        assert resp.status_code == 404

    def test_rooms_without_bbox(self, client, tmp_plans_dir):
        """Rooms sans bbox_px sont ignores dans rooms_summary."""
        plan_json = {
            "page_width_px": 1000, "page_height_px": 800,
            "rooms": {"201": {"seed_x": 100, "seed_y": 100}},
        }
        (tmp_plans_dir / "no_bbox.json").write_text(
            __import__("json").dumps(plan_json), encoding="utf-8")
        resp = client.get("/api/plans/no_bbox/metadata")
        assert resp.status_code == 200
        assert resp.get_json()["rooms_summary"] == []


# ====================================================================
# 4. POST /api/room-dsl/parse
# ====================================================================

class TestRoomDslParse:
    """Tests pour POST /api/room-dsl/parse."""

    def test_happy_path(self, client):
        """DSL valide avec fenetre et porte retourne la structure parsee."""
        dsl = "ROOM 300x480\nWINDOW N 0 300\nDOOR S 0 90 INT L"
        resp = client.post("/api/room-dsl/parse", json={"dsl": dsl})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["width_cm"] == 300
        assert data["depth_cm"] == 480
        assert len(data["windows"]) == 1
        assert data["windows"][0]["face"] == "north"
        assert len(data["openings"]) == 1
        assert data["openings"][0]["face"] == "south"
        assert data["openings"][0]["has_door"] is True

    def test_exclusion_zone(self, client):
        """DSL avec zone d'exclusion retourne exclusion_zones non vide."""
        dsl = "ROOM 300x480\nEXCLUSION 0 0 50 50"
        resp = client.post("/api/room-dsl/parse", json={"dsl": dsl})
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["exclusion_zones"]) == 1
        assert data["exclusion_zones"][0]["width_cm"] == 50

    def test_invalid_dsl(self, client):
        """DSL invalide retourne 400 avec message d'erreur."""
        resp = client.post("/api/room-dsl/parse", json={
            "dsl": "INVALID GARBAGE",
        })
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_missing_dsl_field(self, client):
        """Payload sans champ dsl retourne 400."""
        resp = client.post("/api/room-dsl/parse", json={"other": "x"})
        assert resp.status_code == 400
        assert "dsl" in resp.get_json()["error"]


# ====================================================================
# 5. GET /api/config
# ====================================================================

class TestConfig:
    """Tests pour GET /api/config."""

    def test_happy_path(self, client):
        """Config retourne 200 avec les cles attendues."""
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "olm_version" in data
        assert "dev_mode" in data
        assert "room_code" in data

    def test_dev_mode_default(self, client):
        """dev_mode est False par defaut (D-179)."""
        resp = client.get("/api/config")
        data = resp.get_json()
        assert data["dev_mode"] is False

    def test_structure(self, client):
        """Config contient les parametres metier de base."""
        resp = client.get("/api/config")
        data = resp.get_json()
        assert "desk_width_cm" in data
        assert "desk_depth_cm" in data
        assert "grid_cell_cm" in data
        assert isinstance(data["desk_width_cm"], (int, float))


# ====================================================================
# 6. Upload validation (P2.1)
# ====================================================================

# ====================================================================
# 7. GET /health (P2.2)
# ====================================================================

class TestHealth:
    """Tests pour GET /health."""

    def test_happy_path(self, client):
        """GET /health retourne 200 avec la structure attendue."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "version" in data
        assert isinstance(data["checks"], dict)
        for key in ("config_readable", "catalogue_loadable",
                     "plans_dir_exists", "plans_dir_writable"):
            assert key in data["checks"]
            assert isinstance(data["checks"][key], bool)
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))
        assert data["uptime_seconds"] >= 0

    def test_config_missing_returns_503(self, client, monkeypatch):
        """config.json absent provoque status=degraded et 503."""
        monkeypatch.setattr(
            "olm.server.services.config_service._CONFIG_PATH",
            "/nonexistent/config.json",
        )
        monkeypatch.setattr(
            "olm.server.services.config_service.load_project_config",
            lambda: (_ for _ in ()).throw(
                FileNotFoundError("/nonexistent/config.json")),
        )
        resp = client.get("/health")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "degraded"
        assert data["checks"]["config_readable"] is False
        assert "errors" in data
        assert any("config" in e for e in data["errors"])


class TestUploadValidation:
    """Tests pour la validation des uploads (P2.1)."""

    def test_txt_file_rejected(self, client):
        """Upload d'un .txt retourne 415 Unsupported Media Type."""
        data = io.BytesIO(b"hello world")
        resp = client.post("/api/import/ocr", data={
            "floorplan_image": (data, "test.txt", "text/plain"),
        }, content_type="multipart/form-data")
        assert resp.status_code == 415
        assert "error" in resp.get_json()

    def test_valid_png_accepted(self, client):
        """Upload d'un PNG valide passe la validation MIME (pas de 415)."""
        from PIL import Image
        buf = io.BytesIO()
        Image.new("L", (10, 10), color=128).save(buf, format="PNG")
        buf.seek(0)
        resp = client.post("/api/import/ocr", data={
            "floorplan_image": (buf, "plan.png", "image/png"),
        }, content_type="multipart/form-data")
        assert resp.status_code != 415

    def test_upload_too_large(self, client):
        """Upload depassant MAX_CONTENT_LENGTH retourne 413."""
        from olm.server.app import app
        original = app.config.get('MAX_CONTENT_LENGTH')
        app.config['MAX_CONTENT_LENGTH'] = 100
        try:
            data = io.BytesIO(b'x' * 200)
            resp = client.post("/api/import/ocr", data={
                "floorplan_image": (data, "big.png", "image/png"),
            }, content_type="multipart/form-data")
            assert resp.status_code == 413
        finally:
            app.config['MAX_CONTENT_LENGTH'] = original


# ====================================================================
# 10. Logging (P2.4)
# ====================================================================


class TestLogging:
    """Tests pour le logging structuré (P2.4)."""

    def test_health_writes_to_log_file(self, client, tmp_path):
        """GET /health ecrit une ligne dans le fichier de log."""
        import logging
        import logging.handlers

        from olm.server.app import LOG_FORMAT, _RequestIdFilter

        log_file = tmp_path / "olm_test.log"
        olm_logger = logging.getLogger("olm")
        handler = logging.FileHandler(str(log_file))
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler.addFilter(_RequestIdFilter())
        olm_logger.addHandler(handler)
        try:
            client.get("/health")
            handler.flush()
            content = log_file.read_text()
            assert "GET /health" in content
            assert "[INFO]" in content
            assert "req-" in content
        finally:
            olm_logger.removeHandler(handler)

    @pytest.mark.slow
    def test_log_rotation(self, tmp_path):
        """Ecrire > 5 MB de logs declenche la rotation."""
        import logging
        import logging.handlers

        from olm.server.app import LOG_BACKUP_COUNT, LOG_MAX_BYTES

        log_file = tmp_path / "rotation_test.log"
        handler = logging.handlers.RotatingFileHandler(
            str(log_file),
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
        )
        test_logger = logging.getLogger("olm.test.rotation")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)
        try:
            # Ecrire ~6 MB de logs (> 5 MB maxBytes)
            line = "X" * 1000
            for _ in range(6200):
                test_logger.info(line)
            handler.flush()
            rotated = tmp_path / "rotation_test.log.1"
            assert rotated.exists(), "rotation_test.log.1 should exist"
        finally:
            test_logger.removeHandler(handler)
            handler.close()
