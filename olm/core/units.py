"""D-274 Lot 1 : source unique pour les conversions px <-> cm.

Constantes et helpers de conversion d'echelle. Toutes les conversions
px <-> cm du projet doivent passer par ce module (Python) ou par
units.js (JavaScript, meme logique).

Convention d'unite : cm_per_px (cm par pixel) est l'echelle maitre,
coherente avec ingState.scale cote JS et scale_cm_per_px cote Python.

Regle d'arrondi : half-up partout (floor(x + 0.5)), alignee avec
Math.round en JS. Pas de banker's rounding Python.
"""

from __future__ import annotations

import math
import re

# -- Constante de conversion pouce -> cm (source unique) ------------------

INCH_TO_CM: float = 2.54

# -- Conversions px <-> cm ------------------------------------------------


def px_to_cm(px_val: float, cm_per_px: float) -> int:
    """Convertit une valeur en pixels vers des centimetres (arrondi entier).

    Args:
        px_val: Valeur en pixels.
        cm_per_px: Echelle (centimetres par pixel).

    Returns:
        Valeur en cm, arrondie half-up.
    """
    return int(math.floor(px_val * cm_per_px + 0.5))


def cm_to_px(cm_val: float, cm_per_px: float) -> int:
    """Convertit une valeur en centimetres vers des pixels (arrondi entier).

    Args:
        cm_val: Valeur en centimetres.
        cm_per_px: Echelle (centimetres par pixel).

    Returns:
        Valeur en px, arrondie half-up.
    """
    if cm_per_px <= 0:
        return 0
    return int(math.floor(cm_val / cm_per_px + 0.5))


# -- Formules d'echelle « 1:N » ------------------------------------------


def scale_from_dpi_ratio(dpi: int, ratio: float) -> float:
    """Calcule cm_per_px depuis un DPI et un ratio d'echelle (ex. 100 pour 1:100).

    Args:
        dpi: Resolution de rendu en points par pouce.
        ratio: Facteur d'echelle du plan (ex. 100 pour « 1:100 »).

    Returns:
        cm_per_px (0.0 si dpi ou ratio invalides).
    """
    if dpi <= 0 or ratio <= 0:
        return 0.0
    return (INCH_TO_CM / float(dpi)) * ratio


def parse_drawing_scale(text: str, dpi: int) -> float | None:
    """Parse une notation « 1:N » et retourne cm_per_px via le DPI.

    Args:
        text: Chaine a parser (ex. "1:100", "1 : 350").
        dpi: Resolution de rendu en points par pouce.

    Returns:
        cm_per_px, ou None si le texte n'est pas reconnu ou dpi <= 0.
    """
    if not text or dpi <= 0:
        return None
    m = re.match(r"1\s*:\s*(\d+(?:\.\d+)?)", text.strip())
    if not m:
        return None
    return scale_from_dpi_ratio(dpi, float(m.group(1)))
