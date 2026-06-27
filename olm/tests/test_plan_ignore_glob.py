"""Filtre glob des plans (ignored_plan_glob) — masque les *-debug.png.

Le module de préparation de données amont émet des images ``*-debug.png``
(vérification détection pièces / seeds) sans JSON associé ; elles
apparaissaient comme des plans OCR fantômes. ``ingestion.ignored_plan_glob``
(défaut ``*-debug.png``) les masque de la liste des plans.
"""

from __future__ import annotations

import pytest

from olm.server.services import ingestion_service as ing


@pytest.fixture()
def plans_with_debug(tmp_path, monkeypatch):
    """Temp plans dir: a real plan (png+json) + two *-debug.png without json."""
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "office.png").write_bytes(b"x")
    (plans / "office.json").write_text("{}")
    (plans / "office-debug.png").write_bytes(b"x")
    (plans / "rooms-debug.png").write_bytes(b"x")
    _dir = str(plans)
    monkeypatch.setattr(ing, "get_plans_dir", lambda: _dir)
    return plans


def _set_glob(monkeypatch, pattern):
    monkeypatch.setattr(ing, "get_ignored_plan_glob", lambda: pattern)


def test_list_plans_default_glob_hides_debug(plans_with_debug, monkeypatch):
    """Default glob *-debug.png → debug images absent, real plan kept."""
    _set_glob(monkeypatch, "*-debug.png")
    ids = {p["id"] for p in ing.list_plans()["plans"]}
    assert ids == {"office"}


def test_list_plans_empty_glob_shows_all(plans_with_debug, monkeypatch):
    """Empty glob → no filtering, debug images appear as (OCR) plans."""
    _set_glob(monkeypatch, "")
    ids = {p["id"] for p in ing.list_plans()["plans"]}
    assert ids == {"office", "office-debug", "rooms-debug"}


def test_list_plans_glob_case_insensitive(plans_with_debug, monkeypatch):
    """Matching is case-insensitive (*-DEBUG.PNG also hides -debug.png)."""
    _set_glob(monkeypatch, "*-DEBUG.PNG")
    ids = {p["id"] for p in ing.list_plans()["plans"]}
    assert ids == {"office"}


def test_list_ingestion_plans_filters_debug(plans_with_debug, monkeypatch):
    """list_ingestion_plans (raw filenames) applies the same glob."""
    _set_glob(monkeypatch, "*-debug.png")
    names = set(ing.list_ingestion_plans()["plans"])
    assert names == {"office.png"}
