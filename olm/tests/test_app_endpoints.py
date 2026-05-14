"""Tests des 5 endpoints critiques de olm/server/app.py.

Couverture : reanalyze, floor-plan/match, plans/save, room-dsl/parse, config.
Ref audit 6.2 item 3.
"""
from __future__ import annotations

import json
import os

import pytest


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
