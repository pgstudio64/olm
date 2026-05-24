"""Fixtures partagees pour les tests OLM."""
from __future__ import annotations

from typing import Any

import pytest

import olm.core.pattern_generator as _pg
from olm.core.catalogue_matcher import rebuild_block_registry
from olm.server.app import app

# ---------------------------------------------------------------------------
# Pin desk dimensions to 160x80 for deterministic tests (D-270)
# ---------------------------------------------------------------------------

_PIN_W, _PIN_D = 160, 80


@pytest.fixture(scope="session", autouse=True)
def _preserve_config_json():
    """Snapshot project/config.json before the suite and restore it after.

    Some endpoint tests POST config mutations that persist to the real
    config.json (e.g. /api/current-standard writes current_standard).
    Without this, running the suite leaves the user's config.json mutated
    on disk (the « current_standard reverts to standard2 » bug).
    """
    from olm.core import app_config
    path = app_config._CONFIG_PATH
    backup = path.read_text(encoding="utf-8") if path.exists() else None
    yield
    if backup is not None:
        path.write_text(backup, encoding="utf-8")


@pytest.fixture(autouse=True)
def _pin_desk_dims():
    """Pin desk dimensions to 160x80 before each test, restore after."""
    orig_w, orig_d = _pg.DESK_W_CM, _pg.DESK_D_CM
    _pg.refresh_desk_dims(_PIN_W, _PIN_D)
    rebuild_block_registry()
    yield
    _pg.refresh_desk_dims(orig_w, orig_d)
    rebuild_block_registry()


@pytest.fixture()
def client():
    """Client Flask pour tester les endpoints API."""
    import olm.server.app as _app_mod
    _app_mod._active_session = None  # Reset session lock (P2.5)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    _app_mod._active_session = None


@pytest.fixture()
def tmp_plans_dir(tmp_path, monkeypatch):
    """Redirige le repertoire plans vers un dossier temporaire."""
    plans = tmp_path / "plans"
    plans.mkdir()
    _plans_str = str(plans)
    _plans_fn = lambda: _plans_str
    monkeypatch.setattr("olm.server.app.PLANS_DIR", _plans_str)
    # Patch source + all imported references
    monkeypatch.setattr(
        "olm.server.services.config_service.get_plans_dir", _plans_fn)
    monkeypatch.setattr(
        "olm.server.app.get_plans_dir", _plans_fn)
    monkeypatch.setattr(
        "olm.server.services.ingestion_service.get_plans_dir", _plans_fn)
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
                "surface": "14.40 m2",
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
    # Block positioned so its full west face zone (chair clearance +
    # slip-in = 100 cm for standard1) stays inside the room
    # (gap_cm=100 → block at x=100, west zone ends at x=0).
    # Door at x=[100,190] sits between the block east edge and the
    # east wall, so no pushback on south wall.
    fake_catalogue = [
        {
            "name": "300x480_TEST_1",
            "rows": [
                {"blocks": []},
                {"blocks": [
                    {"type": "BLOCK_1", "orientation": 0,
                     "offset_ns_cm": -180, "gap_cm": 100},
                ]},
            ],
            "row_gaps_cm": [180],
            "room_width_cm": 300,
            "room_depth_cm": 480,
            "standard": "standard1",
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
    # Prevent writes to the real catalogue file on disk
    monkeypatch.setattr(
        "olm.server.services.catalogue_service.save_catalogue",
        lambda pats: None,
    )
    return fake_catalogue
