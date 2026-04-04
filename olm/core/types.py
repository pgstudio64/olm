"""Types partagés du core OLM."""
from enum import Enum


class CellType(int, Enum):
    FREE      = 0   # Cellule praticable — passage piéton possible
    WALL      = 1   # Mur ou obstacle fixe — jamais praticable
    FOOTPRINT = 2   # Emprise d'un bloc placé — non praticable (hors chaise)
    DOOR      = 3   # Porte — praticable, source pour connectivité
    CORRIDOR  = 4   # Emprise d'un corridor actif — praticable
