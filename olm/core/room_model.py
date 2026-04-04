"""Modèle canonique de pièce — solver_lab.

Source de vérité pour la description des pièces dans le pipeline statique.
Aligné sur le glossaire (specs/GLOSSARY.md) et le repère D-26 (NW origin, x EST, y SUD).
Toutes les dimensions en centimètres.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Face(str, Enum):
    """Face d'une pièce (mur porteur de fenêtre, porte ou ouverture)."""
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"


class HingeSide(str, Enum):
    """Côté du gond vu depuis l'intérieur de la pièce."""
    LEFT = "left"
    RIGHT = "right"


@dataclass
class WindowSpec:
    """Fenêtre sur une face de la pièce.

    Attributes:
        face: Mur portant la fenêtre.
        offset_cm: Distance depuis l'extrémité ouest (faces N/S) ou nord (faces E/W).
        width_cm: Largeur de la fenêtre.
    """
    face: Face
    offset_cm: int
    width_cm: int


@dataclass
class OpeningSpec:
    """Ouverture dans un mur (porte battante ou baie libre).

    Attributes:
        face: Mur portant l'ouverture.
        offset_cm: Distance depuis l'extrémité ouest (faces N/S) ou nord (faces E/W).
        width_cm: Largeur de l'ouverture (défaut 90 cm).
        has_door: True si porte battante, False si baie libre.
        opens_inward: Sens d'ouverture (True = intérieur). Ignoré si has_door=False.
        hinge_side: Côté du gond vu de l'intérieur. Ignoré si has_door=False.
    """
    face: Face
    offset_cm: int
    width_cm: int = 90
    has_door: bool = True
    opens_inward: bool = True
    hinge_side: HingeSide = HingeSide.LEFT


@dataclass
class ExclusionZone:
    """Zone interdite au placement et à la circulation.

    Trois origines possibles (cf. glossaire) :
    - Obstacle physique (poteau, gaine technique)
    - Zone fictive géométrique (pièce en L/T/U inscrite dans son rectangle englobant)
    - Zone de débattement de porte (générée automatiquement par le pipeline)

    Attributes:
        x_cm: Coin nord-ouest, axe est.
        y_cm: Coin nord-ouest, axe sud.
        width_cm: Dimension ouest vers est.
        depth_cm: Dimension nord vers sud.
        physical: True = obstacle physique ; False = zone fictive géométrique.
    """
    x_cm: int
    y_cm: int
    width_cm: int
    depth_cm: int
    physical: bool = True


@dataclass
class RoomSpec:
    """Spécification complète d'une pièce en centimètres.

    Repère local D-26 : origine = coin nord-ouest, x vers est, y vers sud.
    Convention : fenêtres principales au nord, couloir/porte au sud.

    Attributes:
        width_cm: Dimension ouest vers est.
        depth_cm: Dimension nord vers sud.
        windows: Fenêtres de la pièce.
        openings: Ouvertures (portes battantes ou baies libres).
        exclusion_zones: Zones exclues du placement.
        name: Nom libre (ex. "B.4.12").
        code: Code réglementaire ("14" = open space candidat).
        direction: Orientation des fenêtres principales dans le plan bâtiment.
        raster_nw_x_px: Coin nord-ouest dans le repère raster global, axe est (pixels).
        raster_nw_y_px: Coin nord-ouest dans le repère raster global, axe sud (pixels).
    """
    width_cm: int
    depth_cm: int
    windows: list[WindowSpec] = field(default_factory=list)
    openings: list[OpeningSpec] = field(default_factory=list)
    exclusion_zones: list[ExclusionZone] = field(default_factory=list)
    name: str = ""
    code: str = "14"
    direction: Face | None = None
    raster_nw_x_px: int = 0
    raster_nw_y_px: int = 0

    @property
    def area_m2(self) -> float:
        """Surface brute en m²."""
        return (self.width_cm * self.depth_cm) / 10_000

    @property
    def net_area_m2(self) -> float:
        """Surface nette (brute moins zones interdites) en m²."""
        excluded = sum(z.width_cm * z.depth_cm for z in self.exclusion_zones)
        return (self.width_cm * self.depth_cm - excluded) / 10_000


@dataclass
class FloorPlan:
    """Ensemble des pièces d'un étage.

    Attributes:
        rooms: Pièces de l'étage.
        building_angle_deg: Angle bâtiment vers nord polaire (degrés).
        scale_cm_per_px: Échelle du plan raster.
    """
    rooms: list[RoomSpec] = field(default_factory=list)
    building_angle_deg: float = 0.0
    scale_cm_per_px: float = 0.0
