"""Analyse de couverture du catalogue — solver_lab.

Lance le matching sur un jeu de pièces cibles et produit un rapport
de couverture qualifié (D-42, D-51).

Entrée : liste de RoomSpec (ou fichier JSON rooms_*.json)
Sortie : CoverageReport avec qualification par pièce et backlog
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum

from olm.core.catalogue_matcher import (
    MatchScore, MatchingResult, load_catalogue, match_room,
)
from olm.core.room_model import (
    ExclusionZone, Face, HingeSide, OpeningSpec, RoomSpec, WindowSpec,
)

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Qualification
# ---------------------------------------------------------------------------

class CoverageStatus(str, Enum):
    """Statut de couverture d'une pièce pour un standard."""
    COVERED = "COVERED"                 # Pattern trouvé, scores acceptables
    PARTIAL = "PARTIAL"                 # Pattern trouvé mais scores faibles
    NO_FIT = "NO_FIT"                   # Aucun pattern ne rentre
    LOW_DENSITY = "LOW_DENSITY"         # m²/poste trop élevé (sous-exploité)
    LOW_SCORE = "LOW_SCORE"             # Circulation dégradée

# Seuils de qualification
M2_PER_DESK_MAX = 15.0      # Au-delà → LOW_DENSITY (pièce sous-exploitée)
CIRCULATION_MIN_GRADE = "C"  # En-dessous → LOW_SCORE

_GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}


@dataclass
class RoomCoverage:
    """Couverture d'une pièce pour un standard.

    Attributes:
        room: Pièce cible.
        standard: Standard d'aménagement.
        status: Statut de couverture.
        best_score: Meilleur score trouvé (None si NO_FIT).
        reason: Explication du statut.
    """
    room: RoomSpec
    standard: str
    status: CoverageStatus
    best_score: MatchScore | None
    reason: str


@dataclass
class BacklogItem:
    """Suggestion de pattern à créer.

    Attributes:
        width_cm: Largeur cible.
        depth_cm: Profondeur cible.
        standard: Standard d'aménagement.
        reason: Pourquoi ce pattern est nécessaire.
        n_openings: Nombre d'ouvertures de la pièce.
        room_name: Nom de la pièce source.
    """
    width_cm: int
    depth_cm: int
    standard: str
    reason: str
    n_openings: int
    room_name: str


@dataclass
class CoverageReport:
    """Rapport de couverture complet.

    Attributes:
        rooms: Liste des pièces analysées.
        coverages: Couverture par pièce × standard.
        backlog: Patterns suggérés à créer.
        summary: Résumé statistique.
    """
    rooms: list[RoomSpec]
    coverages: list[RoomCoverage]
    backlog: list[BacklogItem]
    summary: dict


# ---------------------------------------------------------------------------
# Chargement de pièces depuis JSON
# ---------------------------------------------------------------------------

def load_rooms_json(path: str) -> list[RoomSpec]:
    """Charge un jeu de pièces depuis un fichier JSON.

    Format attendu :
    {
      "rooms": [
        {
          "name": "B.4.12",
          "width_cm": 310,
          "depth_cm": 480,
          "windows": [{"face": "north", "offset_cm": 0, "width_cm": 310}],
          "openings": [{"face": "south", "offset_cm": 0, "width_cm": 90,
                        "has_door": true, "opens_inward": true,
                        "hinge_side": "left"}],
          "exclusion_zones": []
        }
      ]
    }

    Args:
        path: Chemin vers le fichier JSON.

    Returns:
        Liste de RoomSpec.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    rooms = []
    for r in data.get("rooms", []):
        windows = [
            WindowSpec(
                face=Face(w["face"]),
                offset_cm=w["offset_cm"],
                width_cm=w["width_cm"],
            )
            for w in r.get("windows", [])
        ]
        openings = [
            OpeningSpec(
                face=Face(o["face"]),
                offset_cm=o["offset_cm"],
                width_cm=o.get("width_cm", 90),
                has_door=o.get("has_door", True),
                opens_inward=o.get("opens_inward", True),
                hinge_side=HingeSide(o.get("hinge_side", "left")),
            )
            for o in r.get("openings", [])
        ]
        exclusions = [
            ExclusionZone(
                x_cm=z["x_cm"], y_cm=z["y_cm"],
                width_cm=z["width_cm"], depth_cm=z["depth_cm"],
            )
            for z in r.get("exclusion_zones", [])
        ]
        rooms.append(RoomSpec(
            width_cm=r["width_cm"],
            depth_cm=r["depth_cm"],
            windows=windows,
            openings=openings,
            exclusion_zones=exclusions,
            name=r.get("name", ""),
        ))

    return rooms


# ---------------------------------------------------------------------------
# Qualification d'une pièce
# ---------------------------------------------------------------------------

def _qualify(
    best: MatchScore | None, room: RoomSpec, standard: str,
) -> RoomCoverage:
    """Qualifie la couverture d'une pièce pour un standard."""
    if best is None:
        return RoomCoverage(
            room=room, standard=standard,
            status=CoverageStatus.NO_FIT, best_score=None,
            reason="Aucun pattern du catalogue ne rentre dans cette pièce",
        )

    # LOW_DENSITY : m²/poste trop élevé
    if best.m2_per_desk > M2_PER_DESK_MAX:
        return RoomCoverage(
            room=room, standard=standard,
            status=CoverageStatus.LOW_DENSITY, best_score=best,
            reason=(f"m²/poste={best.m2_per_desk:.1f} > seuil {M2_PER_DESK_MAX} "
                    f"— pièce sous-exploitée ({best.n_desks} postes)"),
        )

    # LOW_SCORE : circulation dégradée
    grade_ok = _GRADE_ORDER.get(best.circulation_grade, 5) <= _GRADE_ORDER[CIRCULATION_MIN_GRADE]
    if not grade_ok:
        return RoomCoverage(
            room=room, standard=standard,
            status=CoverageStatus.LOW_SCORE, best_score=best,
            reason=(f"Grade circulation={best.circulation_grade} "
                    f"(minimum attendu={CIRCULATION_MIN_GRADE})"),
        )

    return RoomCoverage(
        room=room, standard=standard,
        status=CoverageStatus.COVERED, best_score=best,
        reason=f"{best.n_desks} postes, {best.m2_per_desk:.1f} m²/p, "
               f"circ={best.circulation_grade}",
    )


# ---------------------------------------------------------------------------
# Analyse de couverture
# ---------------------------------------------------------------------------

def analyse_coverage(
    rooms: list[RoomSpec],
    catalogue: list[dict] | None = None,
) -> CoverageReport:
    """Analyse la couverture du catalogue sur un jeu de pièces.

    Args:
        rooms: Pièces cibles.
        catalogue: Catalogue de patterns (défaut : chargé depuis le fichier).

    Returns:
        CoverageReport avec qualification et backlog.
    """
    if catalogue is None:
        catalogue = load_catalogue()

    coverages: list[RoomCoverage] = []
    backlog: list[BacklogItem] = []

    for room in rooms:
        result = match_room(catalogue, room)

        for std, best in result.by_standard.items():
            cov = _qualify(best, room, std)
            coverages.append(cov)

            # Générer un backlog item si mal couvert
            if cov.status != CoverageStatus.COVERED:
                backlog.append(BacklogItem(
                    width_cm=room.width_cm,
                    depth_cm=room.depth_cm,
                    standard=std,
                    reason=cov.reason,
                    n_openings=len(room.openings),
                    room_name=room.name,
                ))

    # Résumé
    total = len(coverages)
    by_status = {}
    for s in CoverageStatus:
        count = sum(1 for c in coverages if c.status == s)
        by_status[s.value] = count

    summary = {
        "total_rooms": len(rooms),
        "total_evaluations": total,
        "by_status": by_status,
        "coverage_pct": round(
            by_status.get("COVERED", 0) / total * 100, 1,
        ) if total > 0 else 0.0,
    }

    logger.info(
        "Couverture : %d pièces, %d évaluations, %.1f%% couvertes",
        len(rooms), total, summary["coverage_pct"],
    )

    return CoverageReport(
        rooms=rooms,
        coverages=coverages,
        backlog=backlog,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Export rapport
# ---------------------------------------------------------------------------

def report_to_dict(report: CoverageReport) -> dict:
    """Convertit le rapport en dict sérialisable JSON."""
    return {
        "summary": report.summary,
        "coverages": [
            {
                "room_name": c.room.name,
                "room_size": f"{c.room.width_cm}x{c.room.depth_cm}",
                "standard": c.standard,
                "status": c.status.value,
                "reason": c.reason,
                "n_desks": c.best_score.n_desks if c.best_score else 0,
                "m2_per_desk": c.best_score.m2_per_desk if c.best_score else 0,
                "circ_grade": c.best_score.circulation_grade if c.best_score else "-",
                "pattern": c.best_score.pattern_name if c.best_score else "-",
            }
            for c in report.coverages
        ],
        "backlog": [
            {
                "width_cm": b.width_cm,
                "depth_cm": b.depth_cm,
                "standard": b.standard,
                "reason": b.reason,
                "n_openings": b.n_openings,
                "room_name": b.room_name,
            }
            for b in report.backlog
        ],
    }


def print_report(report: CoverageReport) -> None:
    """Affiche le rapport de couverture sur stdout."""
    print(f"\n{'='*70}")
    print(f"RAPPORT DE COUVERTURE — {report.summary['total_rooms']} pièces")
    print(f"{'='*70}")
    print(f"Couverture globale : {report.summary['coverage_pct']}%")
    for status, count in report.summary["by_status"].items():
        print(f"  {status:15s} : {count}")

    print(f"\n{'─'*70}")
    print(f"{'Pièce':12s} {'Taille':10s} {'Standard':15s} {'Statut':12s} "
          f"{'Postes':>6s} {'m²/p':>5s} {'Circ':>4s} {'Pattern'}")
    print(f"{'─'*70}")

    for c in report.coverages:
        n = c.best_score.n_desks if c.best_score else 0
        m2 = f"{c.best_score.m2_per_desk:.1f}" if c.best_score else "-"
        gr = c.best_score.circulation_grade if c.best_score else "-"
        pn = c.best_score.pattern_name if c.best_score else "-"
        size = f"{c.room.width_cm}x{c.room.depth_cm}"
        print(f"{c.room.name:12s} {size:10s} {c.standard:15s} {c.status.value:12s} "
              f"{n:>6d} {m2:>5s} {gr:>4s} {pn}")

    if report.backlog:
        print(f"\n{'─'*70}")
        print("BACKLOG — Patterns à créer :")
        print(f"{'─'*70}")
        for b in report.backlog:
            o_str = f" ({b.n_openings}O)" if b.n_openings >= 2 else ""
            print(f"  {b.width_cm}x{b.depth_cm} {b.standard}{o_str} "
                  f"[{b.room_name}] — {b.reason}")
