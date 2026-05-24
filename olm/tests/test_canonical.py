"""Tests round-trip canonicalize ↔ decanonicalize (D-83 solidification)."""

import pytest

from olm.core.canonical import canonicalize_room, decanonicalize_room
from olm.server.services.ingestion_service import (
    _canonicalize_features_for_client,
    _canonicalize_rooms_for_client,
)

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
        """Porte south abs → west canon. Offset préservé, hinge flippé (B-F5)."""
        c = self._canon()
        door = [o for o in c["openings"] if o.get("has_door")][0]
        # south abs, offset=100, width=90 → west canon.
        # south is horizontal, CW: no offset flip.
        assert door["face"] == "west"
        assert door["offset_cm"] == 100
        # B-F5 : south→west, polarity_diff=true, off_flip=false → flip hinge
        assert door["hinge_side"] == "right"


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


# ── D-274 Passe 1.1 : _canonicalize_rooms_for_client ────────────────────


def _make_import_room(corridor_face: str) -> dict:
    """Pièce simulant un résultat d'import (post-D-204)."""
    return {
        "name": "R1",
        "width_cm": 600,
        "depth_cm": 400,
        "corridor_face": corridor_face,
        "windows": [
            {"face": "north", "offset_cm": 50, "width_cm": 200},
        ],
        "openings": [
            {"face": "south", "offset_cm": 100, "width_cm": 90},
        ],
        "doors": [
            {
                "face": "south", "offset_cm": 80, "width_cm": 80,
                "hinge_side": "left",
            },
        ],
        "door_seeds": [{"seed_x": 100, "seed_y": 200}],
        "exclusion_zones": [
            {"x_cm": 10, "y_cm": 20, "width_cm": 80, "depth_cm": 60},
        ],
        "bbox_px": [50, 60, 170, 140],
        "seed_px": [110, 100],
    }


@pytest.mark.parametrize("corridor_face", ["south", "north", "east", "west", ""])
def test_canonicalize_rooms_corridor_face_south(corridor_face: str) -> None:
    """Le helper pose corridor_face='south' pour tous les cas."""
    rooms = [_make_import_room(corridor_face)]
    result = _canonicalize_rooms_for_client(rooms)
    assert len(result) == 1
    assert result[0]["corridor_face"] == "south"


@pytest.mark.parametrize("corridor_face", ["south", "north", "east", "west", ""])
def test_canonicalize_rooms_corridor_face_abs(corridor_face: str) -> None:
    """corridor_face_abs préserve la valeur d'origine."""
    rooms = [_make_import_room(corridor_face)]
    result = _canonicalize_rooms_for_client(rooms)
    assert result[0]["corridor_face_abs"] == corridor_face


@pytest.mark.parametrize("corridor_face", ["north", "east", "west"])
def test_canonicalize_rooms_no_original_cf(corridor_face: str) -> None:
    """_original_corridor_face supprimé (remplacé par corridor_face_abs)."""
    rooms = [_make_import_room(corridor_face)]
    result = _canonicalize_rooms_for_client(rooms)
    assert "_original_corridor_face" not in result[0]


@pytest.mark.parametrize("corridor_face", ["north", "east", "west"])
def test_canonicalize_rooms_matches_canonicalize_room(
    corridor_face: str,
) -> None:
    """Le helper produit les mêmes features cm que canonicalize_room."""
    room = _make_import_room(corridor_face)
    direct = canonicalize_room(room)
    via_helper = _canonicalize_rooms_for_client([dict(room)])[0]
    # Comparer les champs géométriques
    assert via_helper["width_cm"] == direct["width_cm"]
    assert via_helper["depth_cm"] == direct["depth_cm"]
    assert via_helper["windows"] == direct["windows"]
    assert via_helper["openings"] == direct["openings"]
    assert via_helper["doors"] == direct["doors"]
    if "exclusion_zones" in direct:
        assert via_helper["exclusion_zones"] == direct["exclusion_zones"]


def test_canonicalize_rooms_no_mutation() -> None:
    """Le helper ne mute pas les rooms d'entrée."""
    room = _make_import_room("east")
    original_cf = room["corridor_face"]
    original_w = room["width_cm"]
    _canonicalize_rooms_for_client([room])
    assert room["corridor_face"] == original_cf
    assert room["width_cm"] == original_w


def test_canonicalize_rooms_door_seeds_passthrough() -> None:
    """door_seeds (image-absolute) sont préservés sans rotation."""
    room = _make_import_room("east")
    result = _canonicalize_rooms_for_client([room])[0]
    assert result["door_seeds"] == [{"seed_x": 100, "seed_y": 200}]


def test_canonicalize_rooms_bbox_px_passthrough() -> None:
    """bbox_px (image-absolute) est préservé sans rotation."""
    room = _make_import_room("west")
    result = _canonicalize_rooms_for_client([room])[0]
    assert result["bbox_px"] == [50, 60, 170, 140]


# ── D-274 Passe 1.2 : _canonicalize_features_for_client ─────────────────


def _make_features(corridor_face: str) -> dict:
    """Simule le retour de extract_room_features pour une piece donnee.

    Piece 600×400 cm (bbox 100×200 → 700×600 px, scale=3.0 cm/px).
    scale=3.0 → absW = px_to_cm(600, 3.0) = 1800, absD = px_to_cm(400, 3.0) = 1200.
    """
    return {
        "bbox_px": [100, 200, 700, 600],
        "seed_px": [400, 400],
        "windows": [
            {"face": "north", "offset_cm": 50, "width_cm": 200},
        ],
        "openings": [
            {"face": "south", "offset_cm": 100, "width_cm": 90},
        ],
        "doors": [
            {
                "face": "south", "offset_cm": 80, "width_cm": 80,
                "hinge_side": "left", "opens_inward": True,
            },
        ],
        "auto_exclusion_zones": [
            {"x_cm": 10, "y_cm": 20, "width_cm": 80, "depth_cm": 60,
             "origin": "auto"},
        ],
        "hits": [[150, 250, "n"], [200, 300, "s"]],
        "pillar_hits": [[160, 260]],
        "coarse_hits": [[170, 270, "e"]],
        "auto_door_masks_px": [],
    }


_FEAT_SCALE = 3.0


@pytest.mark.parametrize("corridor_face", ["south", "north", "east", "west"])
def test_features_matches_canonicalize_room(corridor_face: str) -> None:
    """Le helper produit les memes features que canonicalize_room."""
    feat = _make_features(corridor_face)
    _canonicalize_features_for_client(feat, corridor_face, _FEAT_SCALE)

    # Verifier via canonicalize_room directe
    from olm.core.units import px_to_cm
    bbox = [100, 200, 700, 600]
    abs_w = px_to_cm(bbox[2] - bbox[0], _FEAT_SCALE)
    abs_d = px_to_cm(bbox[3] - bbox[1], _FEAT_SCALE)
    room = {
        "width_cm": abs_w,
        "depth_cm": abs_d,
        "corridor_face": corridor_face,
        "windows": [{"face": "north", "offset_cm": 50, "width_cm": 200}],
        "openings": [{"face": "south", "offset_cm": 100, "width_cm": 90}],
        "doors": [
            {"face": "south", "offset_cm": 80, "width_cm": 80,
             "hinge_side": "left", "opens_inward": True},
        ],
        "exclusion_zones": [
            {"x_cm": 10, "y_cm": 20, "width_cm": 80, "depth_cm": 60,
             "origin": "auto"},
        ],
    }
    canon = canonicalize_room(room)

    assert feat["width_cm"] == canon["width_cm"]
    assert feat["depth_cm"] == canon["depth_cm"]
    assert feat["windows"] == canon.get("windows", [])
    assert feat["openings"] == canon.get("openings", [])
    assert feat["doors"] == canon.get("doors", [])


@pytest.mark.parametrize("corridor_face", ["east", "west"])
def test_features_dims_swapped(corridor_face: str) -> None:
    """Pour east/west, width et depth sont echanges."""
    from olm.core.units import px_to_cm
    feat = _make_features(corridor_face)
    _canonicalize_features_for_client(feat, corridor_face, _FEAT_SCALE)
    bbox = [100, 200, 700, 600]
    abs_w = px_to_cm(bbox[2] - bbox[0], _FEAT_SCALE)
    abs_d = px_to_cm(bbox[3] - bbox[1], _FEAT_SCALE)
    assert feat["width_cm"] == abs_d
    assert feat["depth_cm"] == abs_w


def test_features_dims_not_swapped_north() -> None:
    """Pour north, width et depth restent identiques."""
    from olm.core.units import px_to_cm
    feat = _make_features("north")
    _canonicalize_features_for_client(feat, "north", _FEAT_SCALE)
    bbox = [100, 200, 700, 600]
    assert feat["width_cm"] == px_to_cm(bbox[2] - bbox[0], _FEAT_SCALE)
    assert feat["depth_cm"] == px_to_cm(bbox[3] - bbox[1], _FEAT_SCALE)


@pytest.mark.parametrize("corridor_face", ["south", "north", "east", "west"])
def test_features_hits_untouched(corridor_face: str) -> None:
    """Les hits/pillar_hits/coarse_hits/seed_px restent en px image."""
    feat = _make_features(corridor_face)
    orig_hits = list(feat["hits"])
    orig_pillar = list(feat["pillar_hits"])
    orig_coarse = list(feat["coarse_hits"])
    orig_seed = list(feat["seed_px"])
    _canonicalize_features_for_client(feat, corridor_face, _FEAT_SCALE)
    assert feat["hits"] == orig_hits
    assert feat["pillar_hits"] == orig_pillar
    assert feat["coarse_hits"] == orig_coarse
    assert feat["seed_px"] == orig_seed


@pytest.mark.parametrize("corridor_face", ["north", "east", "west"])
def test_features_corridor_face_abs(corridor_face: str) -> None:
    """corridor_face_abs est pose, _original_corridor_face supprime."""
    feat = _make_features(corridor_face)
    _canonicalize_features_for_client(feat, corridor_face, _FEAT_SCALE)
    assert feat["corridor_face_abs"] == corridor_face
    assert "_original_corridor_face" not in feat


@pytest.mark.parametrize("corridor_face", ["north", "east", "west"])
def test_features_exclusion_zones_canonicalized(corridor_face: str) -> None:
    """auto_exclusion_zones sont canonicalisees (meme formule que zones)."""
    feat = _make_features(corridor_face)
    _canonicalize_features_for_client(feat, corridor_face, _FEAT_SCALE)
    zones = feat["auto_exclusion_zones"]
    assert len(zones) == 1
    z = zones[0]
    # Verifier que les valeurs sont entieres (arrondi half-up)
    assert z["x_cm"] == int(z["x_cm"])
    assert z["y_cm"] == int(z["y_cm"])
    assert z["width_cm"] == int(z["width_cm"])
    assert z["depth_cm"] == int(z["depth_cm"])
    assert z["origin"] == "auto"


def test_features_no_bbox() -> None:
    """Sans bbox_px, le helper ajoute corridor_face_abs sans crash."""
    feat = {"windows": [], "openings": [], "doors": []}
    _canonicalize_features_for_client(feat, "east", _FEAT_SCALE)
    assert feat["corridor_face_abs"] == "east"
    assert "width_cm" not in feat


def test_features_half_up_rounding() -> None:
    """Arrondi half-up (pas banker's rounding) sur les zones."""
    feat = {
        "bbox_px": [0, 0, 200, 100],
        "seed_px": [100, 50],
        "windows": [],
        "openings": [],
        "doors": [],
        "auto_exclusion_zones": [
            {"x_cm": 10.5, "y_cm": 20.5, "width_cm": 30.5, "depth_cm": 40.5,
             "origin": "auto"},
        ],
        "hits": [],
    }
    _canonicalize_features_for_client(feat, "south", 1.0)
    z = feat["auto_exclusion_zones"][0]
    # half-up: 0.5 arrondit vers le haut (11, 21, 31, 41)
    assert z["x_cm"] == 11
    assert z["y_cm"] == 21
    assert z["width_cm"] == 31
    assert z["depth_cm"] == 41
