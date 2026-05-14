"""Tests pour olm/ingestion/extract.py — fonctions cibles P0.2.

Couverture : extract_room_features, _face_is_exterior (D-177),
_filter_impossible_openings (D-180), extract_rooms_from_preprocessed (D-156/157).
Cas K-* production (2026-05-08).
Ref audit 6.2 item 1.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

# ── Constantes de test ────────────────────────────────────────────────────

SCALE_CM_PER_PX = 0.5  # 1 px = 0.5 cm
EXTERIOR_RGB = (135, 206, 235)
CORRIDOR_RGB = (193, 247, 179)
IMG_W, IMG_H = 200, 200
# bbox de la piece test : (20,20)→(180,180) = 160×160 px = 80×80 cm
ROOM_BBOX = (20, 20, 180, 180)
ROOM_SEED = (100, 100)  # centre du bbox


# ── Helpers de dessin ─────────────────────────────────────────────────────

def _draw_rect_walls(
    draw: ImageDraw.ImageDraw,
    bbox: tuple[int, int, int, int],
    thickness: int = 3,
    gaps: list[dict] | None = None,
) -> None:
    """Dessine 4 murs noirs autour d'un bbox, avec des gaps optionnels.

    Args:
        draw: PIL ImageDraw.
        bbox: (x0, y0, x1, y1).
        thickness: epaisseur du mur en px.
        gaps: liste de {"face": str, "start_px": int, "end_px": int}
            ou start/end sont relatifs au debut de la face.
    """
    x0, y0, x1, y1 = bbox
    gap_map: dict[str, list[tuple[int, int]]] = {}
    for g in (gaps or []):
        gap_map.setdefault(g["face"], []).append(
            (g["start_px"], g["end_px"]))

    def _is_in_gap(face: str, pos: int) -> bool:
        for gs, ge in gap_map.get(face, []):
            if gs <= pos < ge:
                return True
        return False

    # Mur nord (y = y0)
    for px in range(x0, x1):
        if not _is_in_gap("north", px - x0):
            draw.rectangle(
                [px, y0, px, y0 + thickness - 1], fill=0)
    # Mur sud (y = y1)
    for px in range(x0, x1):
        if not _is_in_gap("south", px - x0):
            draw.rectangle(
                [px, y1 - thickness, px, y1 - 1], fill=0)
    # Mur ouest (x = x0)
    for py in range(y0, y1):
        if not _is_in_gap("west", py - y0):
            draw.rectangle(
                [x0, py, x0 + thickness - 1, py], fill=0)
    # Mur est (x = x1)
    for py in range(y0, y1):
        if not _is_in_gap("east", py - y0):
            draw.rectangle(
                [x1 - thickness, py, x1 - 1, py], fill=0)


def _make_room_image(
    w: int = IMG_W,
    h: int = IMG_H,
    bbox: tuple[int, int, int, int] = ROOM_BBOX,
    gaps: list[dict] | None = None,
    pillar: dict | None = None,
) -> Image.Image:
    """Cree une image grayscale avec une piece rectangulaire muree.

    Args:
        w, h: dimensions image.
        bbox: bbox de la piece.
        gaps: ouvertures dans les murs.
        pillar: {"x": int, "y": int, "size": int} carre noir.
    """
    img = Image.new("L", (w, h), color=255)
    draw = ImageDraw.Draw(img)
    _draw_rect_walls(draw, bbox, thickness=3, gaps=gaps)
    if pillar:
        px, py, sz = pillar["x"], pillar["y"], pillar["size"]
        draw.rectangle([px, py, px + sz - 1, py + sz - 1], fill=0)
    return img


def _make_color_image(
    w: int = IMG_W,
    h: int = IMG_H,
    blue_zones: list[tuple[int, int, int, int]] | None = None,
    green_zones: list[tuple[int, int, int, int]] | None = None,
) -> Image.Image:
    """Cree une image RGB avec zones bleues (exterieur) et vertes (couloir)."""
    img = Image.new("RGB", (w, h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    for z in (blue_zones or []):
        draw.rectangle([z[0], z[1], z[2] - 1, z[3] - 1], fill=EXTERIOR_RGB)
    for z in (green_zones or []):
        draw.rectangle([z[0], z[1], z[2] - 1, z[3] - 1], fill=CORRIDOR_RGB)
    return img


def _make_binary(w: int, h: int, walls: list[tuple]) -> np.ndarray:
    """Image binaire (True = mur) avec rectangles de mur specifies."""
    binary = np.zeros((h, w), dtype=bool)
    for x0, y0, x1, y1 in walls:
        binary[y0:y1, x0:x1] = True
    return binary


# ── Fixture partagee : _apply_detection_config ────────────────────────────

@pytest.fixture(autouse=True)
def _setup_detection_config():
    """Applique detection_config au scale de test avant chaque test."""
    from olm.ingestion.comb_detection import _apply_detection_config
    _apply_detection_config(SCALE_CM_PER_PX)


# ====================================================================
# 1. extract_room_features — tests fonctionnels
# ====================================================================

class TestExtractRoomFeatures:
    """Tests pour extract_room_features (point d'entree principal)."""

    def test_happy_path(self):
        """Payload minimal retourne la structure attendue."""
        from olm.ingestion.extract import extract_room_features
        img = _make_room_image(
            gaps=[{"face": "south", "start_px": 60, "end_px": 100}],
        )
        result = extract_room_features(
            img, ROOM_SEED, ROOM_BBOX, SCALE_CM_PER_PX,
        )
        assert "bbox_px" in result
        assert "windows" in result
        assert "openings" in result
        assert "doors" in result
        assert "hits" in result
        assert isinstance(result["bbox_px"], list)
        assert len(result["bbox_px"]) == 4

    def test_bbox_returned_in_cm_range(self):
        """Le bbox retourne a des dimensions coherentes en cm."""
        from olm.ingestion.extract import extract_room_features
        img = _make_room_image()
        result = extract_room_features(
            img, ROOM_SEED, ROOM_BBOX, SCALE_CM_PER_PX,
        )
        bx0, by0, bx1, by1 = result["bbox_px"]
        w_cm = (bx1 - bx0) * SCALE_CM_PER_PX
        h_cm = (by1 - by0) * SCALE_CM_PER_PX
        # Piece de 80x80 cm — tolerance ±5 cm
        assert abs(w_cm - 80) <= 5, f"width_cm={w_cm}, expected ~80"
        assert abs(h_cm - 80) <= 5, f"depth_cm={h_cm}, expected ~80"

    def test_exterior_window_detected(self):
        """Face nord exterieure (bleu) produit au moins 1 fenetre nord."""
        from olm.ingestion.extract import extract_room_features
        img = _make_room_image()
        color = _make_color_image(
            blue_zones=[(0, 0, IMG_W, 20)],
        )
        result = extract_room_features(
            img, ROOM_SEED, ROOM_BBOX, SCALE_CM_PER_PX,
            color_image=color,
            exterior_rgb=EXTERIOR_RGB,
            window_mode="simple",
        )
        north_windows = [
            w for w in result["windows"] if w["face"] == "north"
        ]
        assert len(north_windows) >= 1, "fenetre nord attendue"

    def test_no_window_on_interior_face(self):
        """Face sans bleu (interieure) ne produit pas de fenetre en mode simple."""
        from olm.ingestion.extract import extract_room_features
        img = _make_room_image()
        color = _make_color_image(
            blue_zones=[(0, 0, IMG_W, 20)],
        )
        result = extract_room_features(
            img, ROOM_SEED, ROOM_BBOX, SCALE_CM_PER_PX,
            color_image=color,
            exterior_rgb=EXTERIOR_RGB,
            window_mode="simple",
        )
        south_windows = [
            w for w in result["windows"] if w["face"] == "south"
        ]
        assert len(south_windows) == 0, "pas de fenetre sud attendue"

    def test_corridor_face_triggers_impossible_filter(self):
        """corridor_face active _filter_impossible_openings (D-180)."""
        from olm.ingestion.extract import extract_room_features
        # Mur nord avec un gap tres large (>70% de la face) + mur derriere
        img = _make_room_image(
            gaps=[{"face": "north", "start_px": 10, "end_px": 150}],
        )
        # Ajouter un mur derriere le nord (en haut du bbox)
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 14, 180, 16], fill=0)

        result = extract_room_features(
            img, ROOM_SEED, ROOM_BBOX, SCALE_CM_PER_PX,
            corridor_face="south",
        )
        # Les openings nord devraient etre filtrees (mur derriere)
        north_openings = [
            o for o in result["openings"] if o["face"] == "north"
        ]
        assert len(north_openings) == 0, (
            "openings nord impossibles devraient etre filtrees"
        )


# ====================================================================
# 2. _face_is_exterior (D-177)
# ====================================================================

class TestFaceIsExterior:
    """Tests pour _face_is_exterior — scan directionnel avec seeds."""

    def test_blue_north_is_exterior(self):
        """Face nord avec >30% bleu au-dessus retourne True."""
        from olm.ingestion.extract import _face_is_exterior
        color = _make_color_image(blue_zones=[(0, 0, IMG_W, 20)])
        arr = np.array(color)
        assert _face_is_exterior(
            arr, ROOM_BBOX, "north", EXTERIOR_RGB,
        ) is True

    def test_no_blue_not_exterior(self):
        """Face sans bleu retourne False."""
        from olm.ingestion.extract import _face_is_exterior
        color = _make_color_image()  # tout blanc
        arr = np.array(color)
        for face in ("north", "south", "east", "west"):
            assert _face_is_exterior(
                arr, ROOM_BBOX, face, EXTERIOR_RGB,
            ) is False, f"{face} should not be exterior"

    def test_seed_blocks_exterior(self):
        """Seed d'une autre piece entre bbox et bleu bloque la detection."""
        from olm.ingestion.extract import _face_is_exterior
        # Bleu au-dessus de y=5, seed a y=15 (entre bbox y0=20 et bleu)
        color = _make_color_image(blue_zones=[(0, 0, IMG_W, 5)])
        arr = np.array(color)
        other_seeds = [(100, 15)]
        assert _face_is_exterior(
            arr, ROOM_BBOX, "north", EXTERIOR_RGB,
            other_seeds=other_seeds,
        ) is False

    def test_blue_south_is_exterior(self):
        """Face sud avec bleu en-dessous retourne True."""
        from olm.ingestion.extract import _face_is_exterior
        color = _make_color_image(
            blue_zones=[(0, 185, IMG_W, IMG_H)],
        )
        arr = np.array(color)
        assert _face_is_exterior(
            arr, ROOM_BBOX, "south", EXTERIOR_RGB,
        ) is True

    def test_blue_east_is_exterior(self):
        """Face est avec bleu a droite retourne True."""
        from olm.ingestion.extract import _face_is_exterior
        color = _make_color_image(
            blue_zones=[(185, 0, IMG_W, IMG_H)],
        )
        arr = np.array(color)
        assert _face_is_exterior(
            arr, ROOM_BBOX, "east", EXTERIOR_RGB,
        ) is True

    def test_zero_size_bbox_returns_false(self):
        """Bbox de taille nulle retourne False."""
        from olm.ingestion.extract import _face_is_exterior
        color = _make_color_image(blue_zones=[(0, 0, IMG_W, 20)])
        arr = np.array(color)
        assert _face_is_exterior(
            arr, (50, 50, 50, 50), "north", EXTERIOR_RGB,
        ) is False


# ====================================================================
# 3. _filter_impossible_openings (D-180) — complement
# ====================================================================

class TestFilterImpossibleOpeningsExtract:
    """Tests complementaires via extract_room_features (end-to-end)."""

    def test_small_opening_survives(self):
        """Ouverture <70% de la face n'est pas filtree."""
        from olm.ingestion.extract import _filter_impossible_openings
        binary = _make_binary(200, 200, [(20, 14, 180, 16)])
        openings = [{"face": "north", "offset_cm": 0, "width_cm": 20}]
        # 20 / (160*0.5=80) = 25% < 70%
        result = _filter_impossible_openings(
            openings, ROOM_BBOX, "south", binary, SCALE_CM_PER_PX,
        )
        assert len(result) == 1

    def test_no_corridor_face_passthrough(self):
        """Sans corridor_face, le filtre retourne tout inchange."""
        from olm.ingestion.extract import _filter_impossible_openings
        binary = _make_binary(200, 200, [(20, 14, 180, 16)])
        openings = [{"face": "north", "offset_cm": 0, "width_cm": 75}]
        result = _filter_impossible_openings(
            openings, ROOM_BBOX, "", binary, SCALE_CM_PER_PX,
        )
        assert len(result) == 1


# ====================================================================
# 4. extract_rooms_from_preprocessed (D-156, D-157)
# ====================================================================

class TestExtractRoomsFromPreprocessed:
    """Tests pour extract_rooms_from_preprocessed."""

    def _make_plan_files(
        self, tmp_path, rooms_dict: dict, extra_json: dict | None = None,
    ) -> tuple[dict, str, str]:
        """Cree JSON v3 + PNG overlay + PNG -SD dans tmp_path."""
        json_data = {
            "file": "test.png",
            "page_width_px": IMG_W,
            "page_height_px": IMG_H,
            "drawing_scale_text": "1:50",
            "render_dpi": 127,
            "rooms": rooms_dict,
        }
        if extra_json:
            json_data.update(extra_json)

        overlay = tmp_path / "test.png"
        sd = tmp_path / "test-SD.png"

        # Overlay = plan officiel (blanc)
        Image.new("RGB", (IMG_W, IMG_H), (255, 255, 255)).save(str(overlay))
        # -SD = plan algorithmique avec murs
        sd_img = _make_room_image()
        sd_img.convert("RGB").save(str(sd))

        return json_data, str(sd), str(overlay)

    def test_happy_path(self, tmp_path):
        """JSON v3 minimal avec 1 room retourne 1 room parsee."""
        from olm.ingestion.extract import extract_rooms_from_preprocessed
        rooms = {
            "101": {
                "surface": "6.4 m2",
                "seed_x": 100,
                "seed_y": 100,
                "bbox_px": [20, 20, 180, 180],
            },
        }
        json_data, sd, overlay = self._make_plan_files(tmp_path, rooms)
        result = extract_rooms_from_preprocessed(json_data, sd, overlay)
        assert len(result) == 1
        r = result[0]
        assert r["name"] == "101"
        assert "width_cm" in r
        assert "depth_cm" in r
        assert "bbox_px" in r
        assert "windows" in r
        assert "openings" in r

    def test_missing_rooms_raises(self, tmp_path):
        """JSON sans cle 'rooms' leve ValueError."""
        from olm.ingestion.extract import extract_rooms_from_preprocessed
        overlay = tmp_path / "test.png"
        Image.new("RGB", (IMG_W, IMG_H), (255, 255, 255)).save(str(overlay))
        with pytest.raises(ValueError, match="rooms"):
            extract_rooms_from_preprocessed(
                {"file": "x"}, "", str(overlay),
            )

    def test_v2_legacy_raises(self, tmp_path):
        """JSON v2 (rooms = list) leve ValueError."""
        from olm.ingestion.extract import extract_rooms_from_preprocessed
        overlay = tmp_path / "test.png"
        Image.new("RGB", (IMG_W, IMG_H), (255, 255, 255)).save(str(overlay))
        with pytest.raises(ValueError, match="v2"):
            extract_rooms_from_preprocessed(
                {"file": "x", "rooms": [{"code_line1": {}}]},
                "", str(overlay),
            )

    def test_rooms_without_seed_raises(self, tmp_path):
        """Room sans seed_x/seed_y leve ValueError."""
        from olm.ingestion.extract import extract_rooms_from_preprocessed
        overlay = tmp_path / "test.png"
        Image.new("RGB", (IMG_W, IMG_H), (255, 255, 255)).save(str(overlay))
        with pytest.raises(ValueError, match="seed"):
            extract_rooms_from_preprocessed(
                {"file": "x", "rooms": {"A": {"surface": "10 m2"}}},
                "", str(overlay),
            )

    def test_doors_preserved(self, tmp_path):
        """Doors du JSON sont preservees dans le resultat."""
        from olm.ingestion.extract import extract_rooms_from_preprocessed
        rooms = {
            "101": {
                "surface": "6.4 m2",
                "seed_x": 100,
                "seed_y": 100,
                "bbox_px": [20, 20, 180, 180],
                "doors": [
                    {"face": "south", "offset_px": 40, "width_px": 90,
                     "seed_x": 100, "seed_y": 177},
                ],
            },
        }
        json_data, sd, overlay = self._make_plan_files(tmp_path, rooms)
        result = extract_rooms_from_preprocessed(json_data, sd, overlay)
        assert len(result[0]["doors"]) >= 1
        door = result[0]["doors"][0]
        assert door.get("seed_x") == 100


# ====================================================================
# 5. Cas K-* production (2026-05-08)
# ====================================================================

class TestProductionCasesK:
    """Tests de non-regression pour les cas K-* signales en production."""

    def test_K2_pillar_seen_as_opening(self):
        """Regression K2 (2026-05-08, fix D-159) : poteau 20 cm vu comme ouvertures.

        Un poteau carre de 20 cm (40 px a scale 0.5) sur la face nord
        cote fenetre ne doit PAS produire 2 ouvertures encadrant le poteau.
        Avec bleu au nord, la face produit 1 fenetre (pas des ouvertures).
        """
        from olm.ingestion.extract import extract_room_features
        # Poteau au milieu de la face nord : (90, 20, 130, 60)
        img = _make_room_image(
            pillar={"x": 90, "y": 20, "size": 40},
        )
        color = _make_color_image(blue_zones=[(0, 0, IMG_W, 18)])
        result = extract_room_features(
            img, ROOM_SEED, ROOM_BBOX, SCALE_CM_PER_PX,
            color_image=color,
            exterior_rgb=EXTERIOR_RGB,
            window_mode="simple",
        )
        # Face nord exterieure → au moins 1 fenetre
        north_windows = [
            w for w in result["windows"] if w["face"] == "north"
        ]
        assert len(north_windows) >= 1, (
            "K2: au moins 1 fenetre nord malgre le poteau"
        )
        # PAS 2 ouvertures nord (symptome K2)
        north_openings = [
            o for o in result["openings"] if o["face"] == "north"
        ]
        assert len(north_openings) == 0, (
            "K2: pas d'ouvertures nord (le poteau n'est pas un passage)"
        )

    def test_K4_arc_window_not_door(self):
        """Regression K4 (2026-05-08) : fenetre avec zone bleue, pas de porte.

        Une face nord exterieure (bleu) avec un gap dans le mur (fenetre)
        ne doit pas produire de porte sur cette face.
        """
        from olm.ingestion.extract import extract_room_features
        img = _make_room_image(
            gaps=[{"face": "north", "start_px": 40, "end_px": 120}],
        )
        color = _make_color_image(blue_zones=[(0, 0, IMG_W, 18)])
        result = extract_room_features(
            img, ROOM_SEED, ROOM_BBOX, SCALE_CM_PER_PX,
            color_image=color,
            exterior_rgb=EXTERIOR_RGB,
            window_mode="simple",
        )
        north_doors = [
            d for d in result["doors"] if d.get("face") == "north"
        ]
        assert len(north_doors) == 0, (
            "K4: pas de porte nord sur une fenetre exterieure"
        )

    def test_K5_K12_K25_other_seeds_no_contamination(self):
        """Regression K5/K12/K25 (2026-05-08, fix D-159 other_seeds).

        2 pieces adjacentes : le rescan de la piece 1 avec other_seeds
        de la piece 2 ne doit pas contaminer le bbox vers la piece 2.
        """
        from olm.ingestion.extract import extract_room_features
        # 2 pieces cote a cote : R1 (20..180) et R2 (220..380)
        img = Image.new("L", (400, 200), color=255)
        draw = ImageDraw.Draw(img)
        # Murs de R1
        _draw_rect_walls(draw, (20, 20, 180, 180), thickness=3)
        # Murs de R2
        _draw_rect_walls(draw, (220, 20, 380, 180), thickness=3)

        r1_seed = (100, 100)
        r2_seed = (300, 100)
        r1_bbox = (20, 20, 180, 180)

        result = extract_room_features(
            img, r1_seed, r1_bbox, SCALE_CM_PER_PX,
            other_seeds=[r2_seed],
        )
        bx0, _, bx1, _ = result["bbox_px"]
        # Le bbox retourne ne doit pas depasser dans la zone R2
        r1_right_cm = bx1 * SCALE_CM_PER_PX
        r2_left_cm = 220 * SCALE_CM_PER_PX  # 110 cm
        assert r1_right_cm <= r2_left_cm + 5, (
            f"K5/K12/K25: bbox R1 ({r1_right_cm} cm) depasse dans R2 "
            f"({r2_left_cm} cm)"
        )

    def test_K8_K14_K16_thin_door_arc_no_crash(self):
        """Regression K8/K14/K16 (2026-05-08) : arc de porte fin.

        Un arc de porte tres fin (1 px) ne doit pas faire crasher
        la detection. Le test verifie la stabilite, pas la detection
        positive (un arc de 1 px est en-dessous du seuil detectable
        sur une image synthetique de cette taille).
        """
        from olm.ingestion.extract import extract_room_features
        # Gap dans le mur sud (porte) + arc tres fin (1px de noir)
        img = _make_room_image(
            gaps=[{"face": "south", "start_px": 60, "end_px": 100}],
        )
        draw = ImageDraw.Draw(img)
        # Arc fin : quart de cercle 1 px depuis le bord gauche du gap
        cx, cy = 20 + 60, 177  # coin gauche du gap, interieur
        for angle in range(0, 91, 5):
            import math
            rad = math.radians(angle)
            ax = int(cx + 20 * math.cos(rad))
            ay = int(cy - 20 * math.sin(rad))
            if 0 <= ax < IMG_W and 0 <= ay < IMG_H:
                draw.point((ax, ay), fill=0)

        result = extract_room_features(
            img, ROOM_SEED, ROOM_BBOX, SCALE_CM_PER_PX,
        )
        assert "doors" in result
        assert isinstance(result["doors"], list)

    def test_K77_bbox_coordinates_consistent(self):
        """Regression K77 (2026-05-08) : coordonnees preservees au cm pres.

        Quand on passe un bbox explicite, les coordonnees cm du resultat
        doivent etre coherentes (±5 cm) avec la piece d'entree.
        """
        from olm.ingestion.extract import extract_room_features
        img = _make_room_image()
        result = extract_room_features(
            img, ROOM_SEED, ROOM_BBOX, SCALE_CM_PER_PX,
        )
        bx0, by0, bx1, by1 = result["bbox_px"]
        w_cm = (bx1 - bx0) * SCALE_CM_PER_PX
        h_cm = (by1 - by0) * SCALE_CM_PER_PX
        # Piece d'entree = 160×160 px = 80×80 cm
        expected_w_cm = (ROOM_BBOX[2] - ROOM_BBOX[0]) * SCALE_CM_PER_PX
        expected_h_cm = (ROOM_BBOX[3] - ROOM_BBOX[1]) * SCALE_CM_PER_PX
        assert abs(w_cm - expected_w_cm) <= 5, (
            f"K77: width {w_cm} cm vs expected {expected_w_cm} cm"
        )
        assert abs(h_cm - expected_h_cm) <= 5, (
            f"K77: depth {h_cm} cm vs expected {expected_h_cm} cm"
        )


# ====================================================================
# 4. _dedup_corner_doors — corner dedup unit tests
# ====================================================================

class TestDedupCornerDoors:
    """Tests pour _dedup_corner_doors (post-filtrage coins)."""

    def _make_door(self, face, jh, jf, wfr=0.1):
        return {
            "face": face,
            "offset_px": min(jh, jf),
            "width_px": abs(jf - jh),
            "hinge_side": "left",
            "opens_inward": True,
            "seed_confirmed": False,
            "jamb_hinge_px": jh,
            "jamb_free_px": jf,
            "wall_px": 0,
            "wall_fill_ratio": wfr,
        }

    def test_no_doors(self):
        from olm.ingestion.comb_detection import _dedup_corner_doors
        assert _dedup_corner_doors([], (0, 0, 200, 200), 20) == []

    def test_single_door_kept(self):
        from olm.ingestion.comb_detection import _dedup_corner_doors
        d = self._make_door("north", 10, 40, 0.2)
        result = _dedup_corner_doors([d], (0, 0, 200, 200), 20)
        assert len(result) == 1

    def test_non_adjacent_doors_kept(self):
        """Portes sur faces opposees (north+south) ne sont pas dedup."""
        from olm.ingestion.comb_detection import _dedup_corner_doors
        d1 = self._make_door("north", 10, 40, 0.2)
        d2 = self._make_door("south", 10, 40, 0.3)
        result = _dedup_corner_doors([d1, d2], (0, 0, 200, 200), 20)
        assert len(result) == 2

    def test_corner_dedup_keeps_lower_fill(self):
        """Deux portes au coin NW : garde celle avec le vrai trou."""
        from olm.ingestion.comb_detection import _dedup_corner_doors
        # Porte north pres de x0=0 (coin NW), mur plein
        d_north = self._make_door("north", 2, 30, wfr=0.45)
        # Porte west pres de y0=0 (coin NW), vrai trou
        d_west = self._make_door("west", 2, 30, wfr=0.10)
        rect = (0, 0, 200, 200)
        result = _dedup_corner_doors([d_north, d_west], rect, 20)
        assert len(result) == 1
        assert result[0]["face"] == "west"

    def test_corner_dedup_SE(self):
        """Deux portes au coin SE : garde celle avec le vrai trou."""
        from olm.ingestion.comb_detection import _dedup_corner_doors
        # Porte south pres de x1=200
        d_south = self._make_door("south", 185, 200, wfr=0.40)
        # Porte east pres de y1=200
        d_east = self._make_door("east", 185, 200, wfr=0.05)
        rect = (0, 0, 200, 200)
        result = _dedup_corner_doors([d_south, d_east], rect, 20)
        assert len(result) == 1
        assert result[0]["face"] == "east"

    def test_far_doors_not_deduped(self):
        """Portes adjacentes mais pas au meme coin : pas de dedup."""
        from olm.ingestion.comb_detection import _dedup_corner_doors
        # Porte north pres de x0=0 (coin NW)
        d_north = self._make_door("north", 2, 30, wfr=0.3)
        # Porte west pres de y1=200 (coin SW, pas NW)
        d_west = self._make_door("west", 180, 200, wfr=0.1)
        rect = (0, 0, 200, 200)
        result = _dedup_corner_doors([d_north, d_west], rect, 20)
        assert len(result) == 2


class TestReassignCornerDoorFromOpening:
    """Tests pour _reassign_corner_door_from_opening (D-198)."""

    def test_reassign_east_to_south(self):
        """Porte east au coin SE + opening south au coin SE → reassign."""
        from olm.ingestion.extract import _reassign_corner_door_from_opening
        door = {"face": "east", "offset_cm": 160, "width_cm": 40}
        opening = {"face": "south", "offset_cm": 260, "width_cm": 40}
        doors, ops = _reassign_corner_door_from_opening(
            [door], [opening], width_cm=300, depth_cm=200)
        assert doors[0]["face"] == "south"
        assert doors[0]["offset_cm"] == 260
        assert len(ops) == 0  # opening consumed

    def test_no_reassign_door_not_at_corner(self):
        """Porte east au milieu → pas de reassign."""
        from olm.ingestion.extract import _reassign_corner_door_from_opening
        door = {"face": "east", "offset_cm": 80, "width_cm": 40}
        opening = {"face": "south", "offset_cm": 260, "width_cm": 40}
        doors, ops = _reassign_corner_door_from_opening(
            [door], [opening], width_cm=300, depth_cm=200)
        assert doors[0]["face"] == "east"
        assert len(ops) == 1

    def test_no_reassign_opening_wrong_corner(self):
        """Porte east coin SE + opening south coin SW → pas de match."""
        from olm.ingestion.extract import _reassign_corner_door_from_opening
        door = {"face": "east", "offset_cm": 160, "width_cm": 40}
        opening = {"face": "south", "offset_cm": 0, "width_cm": 40}
        doors, ops = _reassign_corner_door_from_opening(
            [door], [opening], width_cm=300, depth_cm=200)
        assert doors[0]["face"] == "east"
        assert len(ops) == 1

    def test_reassign_north_to_west_NW(self):
        """Porte north coin NW + opening west coin NW → reassign."""
        from olm.ingestion.extract import _reassign_corner_door_from_opening
        door = {"face": "north", "offset_cm": 0, "width_cm": 40}
        opening = {"face": "west", "offset_cm": 0, "width_cm": 40}
        doors, ops = _reassign_corner_door_from_opening(
            [door], [opening], width_cm=300, depth_cm=200)
        assert doors[0]["face"] == "west"
        assert len(ops) == 0
