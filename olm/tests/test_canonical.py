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


# ── Valeurs canoniques intermédiaires (pas que round-trip) ──────────────
# Vérifie que l'offset dans le repère canonique correspond à la
# position physique attendue après rotation.
# Pièce 600 (W) × 400 (D) ; ouvertures : see _make_room.

class TestCanonicalOffsetEast:
    """corridor_face = east (90° CW)."""

    def _canon(self):
        return canonicalize_room(_make_room("east"))

    def test_window_north_offset_preserved(self) -> None:
        """Fenêtre north abs → east canon. Offset préservé (h→v, CW)."""
        # north abs, offset=50, width=200.
        # 90° CW : début north (NW) → début east (NE). Pas de flip.
        c = self._canon()
        win = c["windows"][0]
        assert win["face"] == "east"
        assert win["offset_cm"] == 50

    def test_opening_south_offset_preserved(self) -> None:
        """Ouverture south abs → west canon. Offset préservé (h→v, CW)."""
        c = self._canon()
        op = [o for o in c["openings"] if not o.get("has_door")][0]
        # south abs face="east", offset=30 → canon face="west"
        # Hmm, east abs offset=30 → south canon.
        # Let me re-check _make_room openings.
        # opening[1] = face="east", offset=30, width=120
        assert op["face"] == "south"
        # east abs (vertical) → south canon. CW flip vertical: YES.
        # _absLen("east", 600, 400) = 400. offset = 400 - 30 - 120 = 250.
        assert op["offset_cm"] == 250

    def test_door_south_offset_preserved(self) -> None:
        """Porte south abs → west canon. Offset préservé."""
        c = self._canon()
        door = [o for o in c["openings"] if o.get("has_door")][0]
        # south abs, offset=100, width=90 → west canon.
        # south is horizontal, CW: no flip.
        assert door["face"] == "west"
        assert door["offset_cm"] == 100
        assert door["hinge_side"] == "left"  # pas de flip


class TestCanonicalOffsetWest:
    """corridor_face = west (90° CCW)."""

    def _canon(self):
        return canonicalize_room(_make_room("west"))

    def test_window_north_offset_flipped(self) -> None:
        """Fenêtre north abs → west canon. Offset flippé (h→v, CCW)."""
        c = self._canon()
        win = c["windows"][0]
        assert win["face"] == "west"
        # north abs (horizontal), CCW flip: YES.
        # _face_len("north") = W = 600. offset = 600 - 50 - 200 = 350.
        assert win["offset_cm"] == 350

    def test_opening_east_offset_preserved(self) -> None:
        """Ouverture east abs → north canon. Offset préservé (v→h, CCW)."""
        c = self._canon()
        op = [o for o in c["openings"] if not o.get("has_door")][0]
        assert op["face"] == "north"
        # east abs (vertical), CCW: no flip.
        assert op["offset_cm"] == 30


class TestCanonicalOffsetNorth:
    """corridor_face = north (180°)."""

    def _canon(self):
        return canonicalize_room(_make_room("north"))

    def test_window_north_offset_flipped(self) -> None:
        """Fenêtre north abs → south canon. Offset flippé (180°)."""
        c = self._canon()
        win = c["windows"][0]
        assert win["face"] == "south"
        # 180° : toujours flip. _face_len("north") = 600.
        # offset = 600 - 50 - 200 = 350.
        assert win["offset_cm"] == 350


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
