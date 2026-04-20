"""Auto-test d'orientation canonique (R-13 / D-119).

Vérifie à partir des couleurs sémantiques du PNG -SD que l'invariant
« posture humaine » du refactor R-12 est respecté : corridor toujours au
sud canon, extérieur (si façade) au nord canon.

Méthode : échantillonne les pixels dans une bande située juste au-delà de
chaque face du bbox absolu de la pièce, calcule le ratio de pixels verts
(`corridor_rgb`) et bleus (`exterior_rgb`). La face canon est mappée à la
face absolue via la matrice de rotation induite par `original_corridor_face`.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


# Matrice « face canon → face absolue » indexée par original_corridor_face.
# Cas corridor_face="south" (ou vide) : identité.
# Les valeurs sont les inverses de FACE_MAPS côté frontend (canonical_io.js).
_CANON_TO_ABS = {
    "": {"north": "north", "south": "south", "east": "east", "west": "west"},
    "south": {"north": "north", "south": "south", "east": "east", "west": "west"},
    "north": {"north": "south", "south": "north", "east": "west", "west": "east"},
    "east":  {"north": "west",  "south": "east",  "east": "north", "west": "south"},
    "west":  {"north": "east",  "south": "west",  "east": "south", "west": "north"},
}


def _sample_band(
    img: np.ndarray,
    bbox_px: tuple[int, int, int, int],
    face_abs: str,
    band_px: int,
) -> np.ndarray:
    """Échantillonne la bande de `band_px` pixels juste au-delà d'une face.

    Returns un array (H, W, 3) uint8, éventuellement vide si la bande sort
    du raster.
    """
    x0, y0, x1, y1 = bbox_px
    h, w = img.shape[:2]
    if face_abs == "north":
        y_lo = max(0, y0 - band_px)
        return img[y_lo:y0, x0:x1]
    if face_abs == "south":
        y_hi = min(h, y1 + band_px)
        return img[y1:y_hi, x0:x1]
    if face_abs == "west":
        x_lo = max(0, x0 - band_px)
        return img[y0:y1, x_lo:x0]
    if face_abs == "east":
        x_hi = min(w, x1 + band_px)
        return img[y0:y1, x1:x_hi]
    return np.zeros((0, 0, 3), dtype=np.uint8)


def _color_ratio(
    band: np.ndarray,
    rgb: tuple[int, int, int],
    tolerance: int = 25,
) -> float:
    """Ratio de pixels proches de `rgb` (distance L∞ ≤ tolerance) sur la bande."""
    if band.size == 0:
        return 0.0
    target = np.array(rgb, dtype=np.int16)
    diff = np.abs(band.astype(np.int16) - target).max(axis=2)
    match = diff <= tolerance
    return float(match.sum()) / float(match.size)


def check_corridor_south(
    enhanced_png_path: str | Path,
    bbox_px: tuple[int, int, int, int],
    original_corridor_face: str,
    corridor_rgb: tuple[int, int, int] = (193, 247, 179),
    band_px: int = 20,
    min_ratio: float = 0.20,
) -> dict:
    """Vérifie que la face canon "south" borde bien du vert (corridor).

    Args:
        enhanced_png_path: chemin du PNG -SD (couleurs sémantiques).
        bbox_px: bbox absolu de la pièce (x0, y0, x1, y1).
        original_corridor_face: face absolue stockée comme corridor
            (déduit via fromStorage). Peut valoir "", "south", "north",
            "east", "west".
        corridor_rgb: couleur vert corridor.
        band_px: épaisseur de la bande d'échantillonnage.
        min_ratio: seuil minimum de vert pour considérer le test validé.

    Returns:
        {
          "ok": bool,
          "ratio_green": float,
          "face_abs_checked": str,
          "band_shape": [h, w],
          "applicable": bool,   # False si la pièce n'a pas de repère canon défini
        }
    """
    ocf = original_corridor_face or ""
    face_map = _CANON_TO_ABS.get(ocf, _CANON_TO_ABS[""])
    face_abs = face_map["south"]

    img = np.array(Image.open(enhanced_png_path).convert("RGB"))
    band = _sample_band(img, tuple(int(v) for v in bbox_px), face_abs, band_px)
    ratio = _color_ratio(band, corridor_rgb)

    applicable = ocf in _CANON_TO_ABS and band.size > 0
    return {
        "ok": applicable and ratio >= min_ratio,
        "ratio_green": ratio,
        "face_abs_checked": face_abs,
        "band_shape": list(band.shape[:2]),
        "applicable": applicable,
        "min_ratio": min_ratio,
    }


def check_exterior_north(
    enhanced_png_path: str | Path,
    bbox_px: tuple[int, int, int, int],
    original_corridor_face: str,
    exterior_rgb: tuple[int, int, int] = (135, 206, 235),
    band_px: int = 20,
    min_ratio: float = 0.20,
) -> dict:
    """Vérifie que la face canon "north" borde du bleu (extérieur).

    Retour analogue à `check_corridor_south`. Utile seulement pour les
    pièces dont une façade est attendue au nord canon.
    """
    ocf = original_corridor_face or ""
    face_map = _CANON_TO_ABS.get(ocf, _CANON_TO_ABS[""])
    face_abs = face_map["north"]

    img = np.array(Image.open(enhanced_png_path).convert("RGB"))
    band = _sample_band(img, tuple(int(v) for v in bbox_px), face_abs, band_px)
    ratio = _color_ratio(band, exterior_rgb)

    applicable = ocf in _CANON_TO_ABS and band.size > 0
    return {
        "ok": applicable and ratio >= min_ratio,
        "ratio_blue": ratio,
        "face_abs_checked": face_abs,
        "band_shape": list(band.shape[:2]),
        "applicable": applicable,
        "min_ratio": min_ratio,
    }


def check_all_faces(
    enhanced_png_path: str | Path,
    bbox_px: tuple[int, int, int, int],
    original_corridor_face: str,
    corridor_rgb: tuple[int, int, int] = (193, 247, 179),
    exterior_rgb: tuple[int, int, int] = (135, 206, 235),
    band_px: int = 20,
) -> dict:
    """Retourne les ratios vert/bleu pour les 4 faces canon.

    Utile en diagnostic : permet de voir d'un coup d'œil où sont corridor
    et extérieur par rapport au repère canon détecté.
    """
    ocf = original_corridor_face or ""
    face_map = _CANON_TO_ABS.get(ocf, _CANON_TO_ABS[""])
    img = np.array(Image.open(enhanced_png_path).convert("RGB"))
    bb = tuple(int(v) for v in bbox_px)

    out = {
        "original_corridor_face": ocf,
        "faces": {},
    }
    for canon_face in ("north", "south", "east", "west"):
        face_abs = face_map.get(canon_face, canon_face)
        band = _sample_band(img, bb, face_abs, band_px)
        out["faces"][canon_face] = {
            "face_abs": face_abs,
            "ratio_green": _color_ratio(band, corridor_rgb),
            "ratio_blue": _color_ratio(band, exterior_rgb),
            "band_shape": list(band.shape[:2]),
        }
    return out
