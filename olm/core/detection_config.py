"""Configuration centralisée de la détection de pièces (ingestion raster).

Toutes les tolérances sont déclarées en **cm** (ou degrés, ou niveaux gris pour
le seuil de binarisation). La conversion en pixels se fait au runtime via la
méthode `to_px(scale_cm_per_px)`.

Les valeurs peuvent être surchargées par `project/config.json` sous la clé
`room_detection`. Seules les clés présentes dans le JSON écrasent les
défauts — les autres conservent leur valeur par défaut.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict
from typing import Any


@dataclass(frozen=True)
class DetectionConfigCm:
    """Paramètres de détection, en cm (ou unités naturelles).

    Tous les `*_cm` se convertissent en px au runtime. Les autres restent
    dans leur unité naturelle.
    """

    # --- Binarisation ---
    binarize_threshold: int = 110            # niveaux gris (0-255), < = mur
    ortho_angle_tolerance_deg: float = 5.0   # tolérance orthogonalité

    # --- Classification / sizing des segments de mur ---
    wall_depth_cm: float = 24.0              # profondeur de probe dans mur
    min_opening_width_cm: float = 24.0       # largeur min pour qu'un "trou"
                                             # soit une opening
    min_opening_depth_cm: float = 100.0       # profondeur min derrière le mur
                                             # (just enough to clear wall
                                             # thickness between two rooms)
    min_window_width_cm: float = 24.0
    min_obstacle_width_cm: float = 30.0
    max_absorb_cm: float = 30.0              # largeur max d'une "rupture"
                                             # parasite absorbée dans un mur

    # --- Snap / tolérance géométrique ---
    snap_search_cm: float = 18.0             # recherche ±N cm autour d'un bord
    mode_tolerance_cm: float = 15.0          # tolérance autour du mode de mur
    morph_dilate_cm: float = 3.0             # dilatation morphologique

    # --- Comb rays ---
    comb_step_cm: float = 15.0               # pas entre rays
    coarse_step_cm: float = 90.0             # pas phase 1 (grossière)
    ray_margin_cm: float = 30.0              # marge au-delà de phase 1
    max_ray_cm: float = 4500.0               # distance max d'un ray

    # --- Détection de portes ---
    door_probe_depth_cm: float = 12.0        # offset probe pour arc
    door_group_gap_cm: float = 75.0          # gap max entre pixels d'un arc
    door_wall_margin_cm: float = 9.0         # marge anti-mur perp
    default_door_width_cm: float = 90.0

    # --- Divers ---
    cartouche_margin_cm: float = 3.0

    def to_px(self, scale_cm_per_px: float) -> "DetectionConfigPx":
        """Convertit les valeurs cm en px au scale courant."""
        px_per_cm = 1.0 / scale_cm_per_px
        def _px(cm: float) -> int:
            return max(1, int(round(cm * px_per_cm)))
        return DetectionConfigPx(
            binarize_threshold=self.binarize_threshold,
            ortho_angle_tolerance_deg=self.ortho_angle_tolerance_deg,
            wall_depth_px=_px(self.wall_depth_cm),
            min_opening_width_px=_px(self.min_opening_width_cm),
            min_opening_depth_px=_px(self.min_opening_depth_cm),
            min_window_width_px=_px(self.min_window_width_cm),
            min_obstacle_width_px=_px(self.min_obstacle_width_cm),
            max_absorb_px=_px(self.max_absorb_cm),
            snap_search_px=_px(self.snap_search_cm),
            mode_tolerance_px=_px(self.mode_tolerance_cm),
            morph_dilate_px=_px(self.morph_dilate_cm),
            comb_step_px=_px(self.comb_step_cm),
            coarse_step_px=_px(self.coarse_step_cm),
            ray_margin_px=_px(self.ray_margin_cm),
            max_ray_px=_px(self.max_ray_cm),
            door_probe_depth_px=_px(self.door_probe_depth_cm),
            door_group_gap_px=_px(self.door_group_gap_cm),
            door_wall_margin_px=_px(self.door_wall_margin_cm),
            default_door_width_px=_px(self.default_door_width_cm),
            cartouche_margin_px=_px(self.cartouche_margin_cm),
        )

    @classmethod
    def from_dict(cls, data: dict | None) -> "DetectionConfigCm":
        """Crée une instance, en écrasant les défauts par les clés fournies."""
        if not data:
            return cls()
        known = {f.name for f in fields(cls)}
        kept = {k: v for k, v in data.items() if k in known}
        return cls(**{**asdict(cls()), **kept})


@dataclass(frozen=True)
class DetectionConfigPx:
    """Snapshot de DetectionConfigCm converti en pixels pour un scale donné.

    Ne jamais instancier directement — passer par `DetectionConfigCm.to_px`.
    """

    binarize_threshold: int
    ortho_angle_tolerance_deg: float

    wall_depth_px: int
    min_opening_width_px: int
    min_opening_depth_px: int
    min_window_width_px: int
    min_obstacle_width_px: int
    max_absorb_px: int

    snap_search_px: int
    mode_tolerance_px: int
    morph_dilate_px: int

    comb_step_px: int
    coarse_step_px: int
    ray_margin_px: int
    max_ray_px: int

    door_probe_depth_px: int
    door_group_gap_px: int
    door_wall_margin_px: int
    default_door_width_px: int

    cartouche_margin_px: int


DEFAULT_DETECTION_CONFIG_CM = DetectionConfigCm()
