"""Shared core types for OLM."""
from enum import Enum


class CellType(int, Enum):
    FREE      = 0   # Walkable cell — pedestrian passage allowed
    WALL      = 1   # Wall or fixed obstacle — never walkable
    FOOTPRINT = 2   # Footprint of a placed block — not walkable (except chair area)
    DOOR      = 3   # Door — walkable, source for connectivity
    CORRIDOR  = 4   # Footprint of an active corridor — walkable


class IngestionMode(str, Enum):
    """Mode d'ingestion du plan de sol."""
    OCR = "ocr"               # Analyse raster + OCR (pipeline existant)
    PREPROCESSED = "preprocessed"  # Données structurées JSON + PNG enhanced/overlay
