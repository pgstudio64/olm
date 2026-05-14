"""Fixtures partagees pour les tests OLM."""
from __future__ import annotations

import json
import os
from typing import Any

import pytest

from olm.server.app import app


@pytest.fixture()
def client():
    """Client Flask pour tester les endpoints API."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def tmp_plans_dir(tmp_path, monkeypatch):
    """Redirige le repertoire plans vers un dossier temporaire."""
    plans = tmp_path / "plans"
    plans.mkdir()
    _plans_str = str(plans)
    monkeypatch.setattr("olm.server.app.PLANS_DIR", _plans_str)
    # Patch both the source function and the imported reference in app
    monkeypatch.setattr(
        "olm.server.services.config_service.get_plans_dir",
        lambda: _plans_str,
    )
    monkeypatch.setattr(
        "olm.server.app.get_plans_dir", lambda: _plans_str,
    )
    return plans


@pytest.fixture()
def sample_plan_json() -> dict[str, Any]:
    """JSON v3 minimal avec rooms, doors separes des openings, exclusion_zones."""
    return {
        "file": "test_plan.png",
        "page_width_px": 1000,
        "page_height_px": 800,
        "drawing_scale_text": "1:100",
        "rooms": {
            "101": {
                "surface": 14.4,
                "seed_x": 500,
                "seed_y": 400,
                "bbox_px": [400, 300, 700, 600],
                "walls_user_edited": True,
                "windows": [
                    {"face": "north", "offset_cm": 0, "width_cm": 300,
                     "offset_px": 0, "width_px": 600, "origin": "auto"},
                ],
                "openings": [
                    {"face": "south", "offset_cm": 50, "width_cm": 90,
                     "offset_px": 100, "width_px": 180, "origin": "auto"},
                ],
                "doors": [
                    {"face": "south", "offset_cm": 50, "width_cm": 90,
                     "has_door": True, "opens_inward": True,
                     "hinge_side": "left", "seed_x": 510, "seed_y": 590},
                ],
                "exclusion_zones": [
                    {"x_cm": 0, "y_cm": 0, "width_cm": 50, "depth_cm": 50},
                ],
            },
        },
    }


@pytest.fixture()
def sample_room_canonical() -> dict[str, Any]:
    """Room canonique minimale pour /api/floor-plan/match."""
    return {
        "name": "101",
        "width_cm": 300,
        "depth_cm": 480,
        "windows": [
            {"face": "north", "offset_cm": 0, "width_cm": 300},
        ],
        "openings": [
            {"face": "south", "offset_cm": 100, "width_cm": 90,
             "has_door": True, "opens_inward": True, "hinge_side": "left"},
        ],
        "exclusion_zones": [
            {"x_cm": 0, "y_cm": 0, "width_cm": 50, "depth_cm": 50},
        ],
    }


@pytest.fixture()
def tiny_plan_png(tmp_path) -> str:
    """Image 10x10 pixels gris 128, ecrite dans tmp_path."""
    from PIL import Image
    img = Image.new("L", (10, 10), color=128)
    path = tmp_path / "tiny_plan.png"
    img.save(str(path))
    return str(path)


@pytest.fixture()
def monkeypatch_catalogue(monkeypatch):
    """Remplace le catalogue par un pattern minimal."""
    fake_catalogue = [
        {
            "name": "300x480_TEST_1",
            "rows": [
                {"blocks": []},
                {"blocks": [
                    {"type": "BLOCK_1", "orientation": 0,
                     "offset_ns_cm": -180, "gap_cm": 20},
                ]},
            ],
            "row_gaps_cm": [180],
            "room_width_cm": 300,
            "room_depth_cm": 480,
            "standard": "AFNOR_ADVICE",
            "room_windows": [
                {"face": "north", "offset_cm": 0, "width_cm": 300},
            ],
            "room_openings": [
                {"face": "south", "has_door": True, "hinge_side": "left",
                 "offset_cm": 100, "opens_inward": True, "width_cm": 90},
            ],
            "room_exclusions": [],
        },
    ]
    monkeypatch.setattr(
        "olm.server.services.catalogue_service.load_catalogue",
        lambda: fake_catalogue,
    )
    # matching_service imports load_catalogue — patch its local ref too
    monkeypatch.setattr(
        "olm.server.services.matching_service.load_catalogue",
        lambda: fake_catalogue,
    )
    return fake_catalogue
