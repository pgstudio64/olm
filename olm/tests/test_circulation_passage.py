"""Filet de non-régression — détection de passage walking margin (D-297).

Pilote le harnais Node `olm/tests/js/circulation/circulation_runner.js --json`
qui charge le VRAI code de prod (`editor.js` : `_isPassageAlong` +
`_gapResidualCells` mode "walkable", `shared.js`, `block_geometry.js`,
`distance_rules.js`) et vérifie que la walking margin est appliquée là où
Dijkstra fait passer une personne derrière un poste occupé.

Skip si node absent.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_RUNNER = Path(__file__).parent / "js" / "circulation" / "circulation_runner.js"

# Couleur attendue côté chaise selon la largeur de couloir (cm) :
# 90/130 -> RED (couloir < emprise chaise 90 + walking 70 = 160),
# 160 -> AMBER (= 160), 200 -> GREEN (> 160).
_COLOR_BY_WIDTH = {90: "RED", 130: "RED", 160: "AMBER", 200: "GREEN"}

_SIDE_BLOCKS = ("BLOCK_2_SIDE", "BLOCK_3_SIDE")
_FACE_BLOCKS = ("BLOCK_4_FACE", "BLOCK_6_FACE")


@pytest.fixture(scope="module")
def results() -> dict:
    """Run the harness once, index entries by (scenario, width, face)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node introuvable -- test passage circulation skippé")
    proc = subprocess.run(
        [node, str(_RUNNER), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, (
        f"harnais Node échoue:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    data = json.loads(proc.stdout)
    def _key(e: dict) -> tuple:
        k = (e["scenario"], e["width"], e["face"])
        if "position" in e:
            k = k + (e["position"],)
        return k
    return {_key(e): e for e in data}


@pytest.mark.parametrize("block", _SIDE_BLOCKS)
@pytest.mark.parametrize("width", [90, 130, 160, 200])
def test_side_chair_corridor_is_passage(results, block, width):
    """Couloir côté chaise (west) d'un bloc SIDE = passage, couleur par largeur."""
    e = results[(block, width, "west")]
    assert e["prod"] is True, f"{block} {width} west devrait être passage"
    assert e["color"] == _COLOR_BY_WIDTH[width]


@pytest.mark.parametrize("block", _SIDE_BLOCKS)
@pytest.mark.parametrize("width", [90, 130, 160, 200])
def test_side_screen_side_not_passage(results, block, width):
    """Côté écran (east) d'un bloc SIDE = jamais passage (personne n'y marche)."""
    e = results[(block, width, "east")]
    assert e["prod"] is False
    assert e["color"] == "GREEN"


@pytest.mark.parametrize("block", _FACE_BLOCKS)
@pytest.mark.parametrize("width", [90, 130, 160, 200])
@pytest.mark.parametrize("face", ["west", "east"])
def test_face_both_sides_are_passage(results, block, width, face):
    """Bloc FACE : chaises des deux côtés → les deux couloirs sont des passages."""
    e = results[(block, width, face)]
    assert e["prod"] is True
    assert e["color"] == _COLOR_BY_WIDTH[width]


def test_depth1_blocks_not_passage(results):
    """Profondeur 1 (BLOCK_1, BLOCK_2_FACE) : on ne passe derrière personne."""
    assert results[("BLOCK_1", 90, "west")]["prod"] is False
    assert results[("BLOCK_2_FACE", 90, "west")]["prod"] is False
    assert results[("BLOCK_2_FACE", 90, "east")]["prod"] is False


@pytest.mark.parametrize("gap", [90, 160])
def test_between_blocks_corridor_is_passage(results, gap):
    """Couloir d'accès chaise entre deux blocs = passage (régression couverte)."""
    e = results[("TWO_BLOCK_2_SIDE", gap, "right")]
    assert e["prod"] is True
    assert e["legacy"] is False  # le bug : non détecté avant le fix


def test_stacked_back_is_passage(results):
    """STACKED 2x BLOCK_1 : le desk du FOND (back) a un couloir profond = passage."""
    e = results[("STACKED_BLOCK_1", 160, "west", "back")]
    assert e["prod"] is True
    assert e["color"] == "AMBER"
    assert e["marge"] == 0


def test_stacked_front_is_not_passage(results):
    """STACKED 2x BLOCK_1 : le desk de DEVANT (front) a un couloir peu profond."""
    e = results[("STACKED_BLOCK_1", 160, "west", "front")]
    assert e["prod"] is False
    assert e["color"] == "GREEN"
    assert e["marge"] == 70


def test_two_columns_union_isolation(results):
    """Deux colonnes empilées : l'union d'un couloir n'englobe pas l'autre."""
    back = results[("TWOCOL_BLOCK_1", 160, "west", "colB_back")]
    assert back["prod"] is True, "colB back devrait être passage (profond)"
    assert back["color"] == "AMBER"
    front = results[("TWOCOL_BLOCK_1", 160, "west", "colB_front")]
    assert front["prod"] is False, "colB front ne devrait PAS être passage"
    assert front["color"] == "GREEN"
