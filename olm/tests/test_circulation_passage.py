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

# D-312: couleur attendue cote chaise selon la largeur de couloir (cm).
# Passage => emprise chaise = chair_clearance (70), requis = 70 + walking 70 = 140.
# 90/130 -> RED (< 140 - tol), 160/200 -> GREEN (>= 140 + tol).
_COLOR_BY_WIDTH = {90: "RED", 130: "RED", 160: "GREEN", 200: "GREEN"}

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


def test_stacked_back_not_passage(results):
    """STACKED 2x BLOCK_1 : desk du FOND (back) = bout du couloir, non-passage."""
    e = results[("STACKED_BLOCK_1", 160, "west", "back")]
    assert e["prod"] is False
    assert e["color"] == "GREEN"
    # D-312: dead-end emprise = chair(70) + slip(20) = 90, marge = 160 - 90 = 70
    assert e["marge"] == 70


def test_stacked_front_is_passage(results):
    """STACKED 2x BLOCK_1 : desk PROCHE (front) = trafic vers le fond, passage."""
    e = results[("STACKED_BLOCK_1", 160, "west", "front")]
    assert e["prod"] is True
    # D-312: passage emprise = chair(70), requis = 70 + walking(70) = 140,
    # marge = 160 - 140 = 20 => GREEN
    assert e["color"] == "GREEN"
    assert e["marge"] == 20


def test_stacked3_front_is_passage(results):
    """STACKED3 3x BLOCK_1 : desk PROCHE (front) = passage (trafic vers mid+back)."""
    e = results[("STACKED3_BLOCK_1", 160, "west", "front")]
    assert e["prod"] is True
    # D-312: passage => requis 140, marge = 160 - 140 = 20 => GREEN
    assert e["color"] == "GREEN"
    assert e["marge"] == 20


def test_stacked3_mid_is_passage(results):
    """STACKED3 3x BLOCK_1 : desk MILIEU (mid) = passage (trafic vers back)."""
    e = results[("STACKED3_BLOCK_1", 160, "west", "mid")]
    assert e["prod"] is True
    # D-312: passage => requis 140, marge = 160 - 140 = 20 => GREEN
    assert e["color"] == "GREEN"
    assert e["marge"] == 20


def test_stacked3_back_not_passage(results):
    """STACKED3 3x BLOCK_1 : desk FOND (back) = bout du couloir, non-passage."""
    e = results[("STACKED3_BLOCK_1", 160, "west", "back")]
    assert e["prod"] is False
    assert e["color"] == "GREEN"
    # D-312: dead-end emprise = chair(70) + slip(20) = 90, marge = 160 - 90 = 70
    assert e["marge"] == 70


def test_two_columns_end_of_corridor(results):
    """Deux colonnes : colB_front (proche porte) = passage, colB_back (fond) = non."""
    front = results[("TWOCOL_BLOCK_1", 160, "west", "colB_front")]
    assert front["prod"] is True, "colB front devrait être passage (trafic vers back)"
    # D-312: passage => requis 140, marge = 160 - 140 = 20 => GREEN
    assert front["color"] == "GREEN"
    back = results[("TWOCOL_BLOCK_1", 160, "west", "colB_back")]
    assert back["prod"] is False, "colB back = bout du couloir, non-passage"
    assert back["color"] == "GREEN"
