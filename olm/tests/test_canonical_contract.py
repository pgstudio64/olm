"""Tests de contrat canonical -- filet de non-regression D-274 Lot 0.

Lacunes connues de canonical.py (prerequis du Lot 2 -- bascule Python
autoritaire) :
  (a) transparent_zones : non transformees par canonical.py alors que
      canonical_io.js les transforme (lignes 349-351).
  (b) Champ doors[] : inconnu de canonical.py ; canonical_io.js le
      transforme separement (lignes 322-324).
  (c) hinge_side B-F5 : inversion naive couplee au flip d'offset --
      faux quand exactement une des faces src/dst est "west". Couvert
      ici en xfail strict (test_canon_hinge_correct).
  (d) Exclusion zones east/west B-F6 : les formules de rotation pour
      corridor east et west sont permutees entre canonical.py et
      canonical_io.js (Python applique la rotation dans le sens
      oppose a sa propre face_map pour les exclusions east/west).
      Le round-trip est preserve des deux cotes mais le resultat
      canonique intermediaire differe. Le test de parite Py/JS
      exclut les exclusion_zones pour cette raison.

Fixtures : olm/tests/fixtures/canonical_cases.json (5 pieces, 20
ouvertures, 5 fenetres, 5 exclusions). Valeurs attendues golden
generees par canonical.py (non-hinge) + override hinge via formule
geometrique corrigee (cf. audit B-F5).
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from olm.core.canonical import canonicalize_room, decanonicalize_room

# -- Chargement des fixtures partagees Py / JS ---------------------------

_FIXTURES_PATH = Path(__file__).parent / "fixtures" / "canonical_cases.json"


def _load_cases() -> list[dict]:
    with open(_FIXTURES_PATH, encoding="utf-8") as f:
        return json.load(f)


CASES = _load_cases()
CASE_NAMES = [c["name"] for c in CASES]

# -- Champs compares ------------------------------------------------------

_ROUNDTRIP_FIELDS = (
    "width_cm", "depth_cm", "corridor_face",
    "openings", "windows", "exclusion_zones",
)

_OPENING_FIELDS_NO_HINGE = (
    "face", "offset_cm", "width_cm", "has_door", "opens_inward",
)

_OPENING_FIELDS_ALL = (
    "face", "offset_cm", "width_cm", "has_door", "hinge_side",
    "opens_inward",
)

_WINDOW_FIELDS = ("face", "offset_cm", "width_cm")
_EXCL_FIELDS = ("x_cm", "y_cm", "width_cm", "depth_cm")


# -- Helpers ---------------------------------------------------------------

def _pick(d: dict, keys: tuple[str, ...]) -> dict:
    """Extraire uniquement les cles specifiees d'un dict."""
    return {k: d[k] for k in keys if k in d}


def _strip_internal(room: dict) -> dict:
    """Retirer les champs internes (_original_corridor_face etc.)."""
    return {k: v for k, v in room.items() if not k.startswith("_")}


# -- test_roundtrip_identity -----------------------------------------------

@pytest.mark.parametrize("case_name", CASE_NAMES)
def test_roundtrip_identity(case_name: str) -> None:
    """decanon(canon(input), corridor_face) == input sur tous les champs."""
    case = next(c for c in CASES if c["name"] == case_name)
    room = case["input_room"]
    room_copy = copy.deepcopy(room)
    cf = room["corridor_face"]

    canon = canonicalize_room(room_copy)
    restored = _strip_internal(decanonicalize_room(canon, cf))

    for field in _ROUNDTRIP_FIELDS:
        assert restored.get(field) == room.get(field), (
            f"Round-trip {case_name} field={field}:\n"
            f"  original: {room.get(field)}\n"
            f"  restored: {restored.get(field)}"
        )


# -- test_canon_golden_non_hinge -------------------------------------------

@pytest.mark.parametrize("case_name", CASE_NAMES)
def test_canon_golden_non_hinge(case_name: str) -> None:
    """canon(input) == expected sur dims, faces, offsets, windows, exclusions.

    Hinge exclu -- teste separement dans test_canon_hinge_correct.
    """
    case = next(c for c in CASES if c["name"] == case_name)
    canon = canonicalize_room(copy.deepcopy(case["input_room"]))
    expected = case["expected_canon"]

    # Dimensions
    assert canon["width_cm"] == expected["width_cm"], (
        f"{case_name} width_cm"
    )
    assert canon["depth_cm"] == expected["depth_cm"], (
        f"{case_name} depth_cm"
    )
    cf = canon.get("corridor_face", "south")
    assert cf == "south", f"{case_name} corridor_face={cf}"

    # Openings (sans hinge)
    canon_ops = canon.get("openings", [])
    exp_ops = expected["openings"]
    assert len(canon_ops) == len(exp_ops), (
        f"{case_name}: opening count {len(canon_ops)} != {len(exp_ops)}"
    )
    for i, (co, eo) in enumerate(zip(canon_ops, exp_ops)):
        actual = _pick(co, _OPENING_FIELDS_NO_HINGE)
        expect = _pick(eo, _OPENING_FIELDS_NO_HINGE)
        assert actual == expect, (
            f"{case_name} opening[{i}]: {actual} != {expect}"
        )

    # Windows
    canon_wins = canon.get("windows", [])
    exp_wins = expected["windows"]
    assert len(canon_wins) == len(exp_wins), (
        f"{case_name} windows count"
    )
    for i, (cw, ew) in enumerate(zip(canon_wins, exp_wins)):
        assert _pick(cw, _WINDOW_FIELDS) == _pick(ew, _WINDOW_FIELDS), (
            f"{case_name} window[{i}]"
        )

    # Exclusion zones
    canon_excl = canon.get("exclusion_zones", [])
    exp_excl = expected["exclusion_zones"]
    assert len(canon_excl) == len(exp_excl), (
        f"{case_name} exclusion count"
    )
    for i, (ce, ee) in enumerate(zip(canon_excl, exp_excl)):
        assert _pick(ce, _EXCL_FIELDS) == _pick(ee, _EXCL_FIELDS), (
            f"{case_name} exclusion[{i}]"
        )


# -- test_canon_hinge_correct ---------------------------------------------

@pytest.mark.xfail(
    strict=True,
    reason="B-F5: hinge inversion naive couplee au flip d'offset -- "
           "corrige en D-274 Lot 3",
)
def test_canon_hinge_correct() -> None:
    """Tous les hinge canoniques correspondent a l'attendu geometrique.

    Echoue aujourd'hui car canonical.py inverse hinge quand l'offset
    est flippe, sans tenir compte de l'inversion de polarite de la
    face west (left = high y, alors que north/south/east = low x ou
    low y). 8 ouvertures sur 4 pieces non-south sont affectees.
    """
    mismatches: list[str] = []
    for case in CASES:
        canon = canonicalize_room(copy.deepcopy(case["input_room"]))
        expected = case["expected_canon"]
        for i, (co, eo) in enumerate(
            zip(canon.get("openings", []), expected["openings"])
        ):
            actual_h = co.get("hinge_side")
            expect_h = eo.get("hinge_side")
            if actual_h != expect_h:
                mismatches.append(
                    f"{case['name']} opening[{i}] "
                    f"{eo['face']}: got={actual_h}, want={expect_h}"
                )
    assert not mismatches, (
        f"{len(mismatches)} hinge mismatch(es):\n"
        + "\n".join(f"  {m}" for m in mismatches)
    )


# -- test_python_js_parity ------------------------------------------------

def test_python_js_parity() -> None:
    """canonical.py et canonical_io.js produisent des resultats identiques.

    Compare dims, openings (face, offset, width, hinge, has_door,
    opens_inward) et windows. Exclusion zones exclues a cause de
    B-F6 (formules east/west permutees entre Py et JS).
    Skip si node absent.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node introuvable -- test parite JS skippe")

    runner = Path(__file__).parent / "js" / "canonical_runner.js"
    result = subprocess.run(
        [node, str(runner)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"JS runner echoue:\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    js_results = json.loads(result.stdout)
    assert len(js_results) == len(CASES), (
        f"JS a retourne {len(js_results)} cas, attendu {len(CASES)}"
    )

    mismatches: list[str] = []
    for case, js_canon in zip(CASES, js_results):
        py_canon = canonicalize_room(copy.deepcopy(case["input_room"]))
        name = case["name"]

        # Dimensions
        for dim in ("width_cm", "depth_cm"):
            if py_canon[dim] != js_canon[dim]:
                mismatches.append(
                    f"{name} {dim}: py={py_canon[dim]} "
                    f"js={js_canon[dim]}"
                )

        # Openings
        py_ops = py_canon.get("openings", [])
        js_ops = js_canon.get("openings", [])
        if len(py_ops) != len(js_ops):
            mismatches.append(
                f"{name} openings count: "
                f"py={len(py_ops)} js={len(js_ops)}"
            )
            continue
        for i, (po, jo) in enumerate(zip(py_ops, js_ops)):
            pp = _pick(po, _OPENING_FIELDS_ALL)
            jp = _pick(jo, _OPENING_FIELDS_ALL)
            if pp != jp:
                mismatches.append(
                    f"{name} opening[{i}]: py={pp} js={jp}"
                )

        # Windows
        py_wins = py_canon.get("windows", [])
        js_wins = js_canon.get("windows", [])
        if len(py_wins) != len(js_wins):
            mismatches.append(
                f"{name} windows count: "
                f"py={len(py_wins)} js={len(js_wins)}"
            )
            continue
        for i, (pw, jw) in enumerate(zip(py_wins, js_wins)):
            pp = _pick(pw, _WINDOW_FIELDS)
            jp = _pick(jw, _WINDOW_FIELDS)
            if pp != jp:
                mismatches.append(
                    f"{name} window[{i}]: py={pp} js={jp}"
                )

    assert not mismatches, (
        f"{len(mismatches)} parite mismatch(es):\n"
        + "\n".join(f"  {m}" for m in mismatches)
    )
