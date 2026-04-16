"""Tests round-trip canonicalize ↔ decanonicalize (D-83 solidification)."""

import pytest

from olm.core.canonical import canonicalize_room, decanonicalize_room


# ── Fixture : pièce de référence avec tous les éléments ──────────────────

def _make_room(corridor_face: str) -> dict:
    """Pièce 600×400 avec fenêtre, porte, ouverture et exclusion."""
    return {
        "name": "test_room",
        "width_cm": 600,
        "depth_cm": 400,
        "corridor_face": corridor_face,
        "windows": [
            {"face": "north", "offset_cm": 50, "width_cm": 200},
        ],
        "openings": [
            {
                "face": "south", "offset_cm": 100, "width_cm": 90,
                "has_door": True, "hinge_side": "left", "opens_inward": True,
            },
            {"face": "east", "offset_cm": 30, "width_cm": 120, "has_door": False},
        ],
        "exclusion_zones": [
            {"x_cm": 10, "y_cm": 20, "width_cm": 80, "depth_cm": 60},
        ],
    }


# ── Round-trip : decanonicalise(canonicalise(room)) == room ──────────────

_FIELDS_TO_COMPARE = ["width_cm", "depth_cm", "windows", "openings", "exclusion_zones"]


def _strip_internal(room: dict) -> dict:
    """Supprime les champs internes (_original_corridor_face) pour comparaison."""
    out = {k: v for k, v in room.items() if not k.startswith("_")}
    return out


@pytest.mark.parametrize("corridor_face", ["south", "north", "east", "west"])
def test_round_trip(corridor_face: str) -> None:
    """canonicalize puis decanonicalize redonne la pièce d'origine."""
    original = _make_room(corridor_face)
    canonical = canonicalize_room(original)
    restored = decanonicalize_room(canonical, corridor_face)
    restored = _strip_internal(restored)

    for field in _FIELDS_TO_COMPARE:
        assert restored[field] == original[field], (
            f"Round-trip failed for corridor_face={corridor_face}, field={field}:\n"
            f"  original: {original[field]}\n"
            f"  restored: {restored[field]}"
        )
    assert restored["corridor_face"] == corridor_face


# ── Canonicalisation produit corridor_face="south" ───────────────────────

@pytest.mark.parametrize("corridor_face", ["north", "east", "west"])
def test_canonicalize_sets_south(corridor_face: str) -> None:
    """Après canonicalize, corridor_face est toujours 'south'."""
    room = _make_room(corridor_face)
    canonical = canonicalize_room(room)
    assert canonical["corridor_face"] == "south"
    assert canonical["_original_corridor_face"] == corridor_face


def test_canonicalize_south_is_identity() -> None:
    """corridor_face='south' retourne la même room (pas de copie)."""
    room = _make_room("south")
    result = canonicalize_room(room)
    assert result is room


# ── Dimensions swappées pour east/west ───────────────────────────────────

@pytest.mark.parametrize("corridor_face", ["east", "west"])
def test_dimensions_swapped(corridor_face: str) -> None:
    """Pour corridor east/west, width et depth sont échangés."""
    room = _make_room(corridor_face)
    canonical = canonicalize_room(room)
    assert canonical["width_cm"] == room["depth_cm"]
    assert canonical["depth_cm"] == room["width_cm"]


def test_dimensions_not_swapped_north() -> None:
    """Pour corridor north, width et depth restent identiques."""
    room = _make_room("north")
    canonical = canonicalize_room(room)
    assert canonical["width_cm"] == room["width_cm"]
    assert canonical["depth_cm"] == room["depth_cm"]


# ── Face mapping vérifié ─────────────────────────────────────────────────

def test_north_window_maps_to_south() -> None:
    """Corridor north : fenêtre face north → face south (en face)."""
    room = _make_room("north")
    canonical = canonicalize_room(room)
    assert canonical["windows"][0]["face"] == "south"


def test_east_door_south_maps_to_west() -> None:
    """Corridor east : porte face south → face west."""
    room = _make_room("east")
    canonical = canonicalize_room(room)
    door = [o for o in canonical["openings"] if o.get("has_door")][0]
    assert door["face"] == "west"


# ── Exclusion zones round-trip détaillé ──────────────────────────────────

@pytest.mark.parametrize("corridor_face", ["north", "east", "west"])
def test_exclusion_round_trip(corridor_face: str) -> None:
    """Exclusion zones survivent au round-trip sans perte de précision."""
    room = _make_room(corridor_face)
    canonical = canonicalize_room(room)
    restored = decanonicalize_room(canonical, corridor_face)
    assert restored["exclusion_zones"] == room["exclusion_zones"]


# ── Room sans éléments optionnels ────────────────────────────────────────

@pytest.mark.parametrize("corridor_face", ["north", "east", "west"])
def test_minimal_room_round_trip(corridor_face: str) -> None:
    """Round-trip fonctionne même sans windows/openings/exclusions."""
    room = {
        "name": "bare",
        "width_cm": 500,
        "depth_cm": 300,
        "corridor_face": corridor_face,
    }
    canonical = canonicalize_room(room)
    restored = decanonicalize_room(canonical, corridor_face)
    assert restored["width_cm"] == room["width_cm"]
    assert restored["depth_cm"] == room["depth_cm"]
