"""Tests de contrat canonical -- filet de non-regression D-274 Lot 0 + Lot 2a/2b.

Lacunes resolues en Lot 2a :
  (a) transparent_zones : transformees par canonical.py (parite JS).
  (b) Champ doors[] : transforme par canonical.py (parite JS).
  (d) Exclusion zones east/west B-F6 : formules alignees sur canonical_io.js.

Lacune resolue en Lot 2b (Passe 1.5b-1) :
  (c) hinge_side B-F5 : corrige via _flip_hinge_on_rotation / flipHingeOnRotation.

Fixtures : olm/tests/fixtures/canonical_cases.json (5 pieces, 20
ouvertures, 5 fenetres, 5 doors, 5 exclusions, 5 transparent_zones).
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
    "openings", "windows", "doors",
    "exclusion_zones", "transparent_zones",
)

_OPENING_FIELDS_NO_HINGE = (
    "face", "offset_cm", "width_cm", "has_door", "opens_inward",
)

_OPENING_FIELDS_ALL = (
    "face", "offset_cm", "width_cm", "has_door", "hinge_side",
    "opens_inward",
)

_WINDOW_FIELDS = ("face", "offset_cm", "width_cm")
_ZONE_FIELDS = ("x_cm", "y_cm", "width_cm", "depth_cm")


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
    """canon(input) == expected sur dims, faces, offsets, windows, zones.

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
    exp_excl = expected.get("exclusion_zones", [])
    assert len(canon_excl) == len(exp_excl), (
        f"{case_name} exclusion count"
    )
    for i, (ce, ee) in enumerate(zip(canon_excl, exp_excl)):
        assert _pick(ce, _ZONE_FIELDS) == _pick(ee, _ZONE_FIELDS), (
            f"{case_name} exclusion[{i}]"
        )

    # Transparent zones
    canon_tz = canon.get("transparent_zones", [])
    exp_tz = expected.get("transparent_zones", [])
    assert len(canon_tz) == len(exp_tz), (
        f"{case_name} transparent count"
    )
    for i, (ct, et) in enumerate(zip(canon_tz, exp_tz)):
        assert _pick(ct, _ZONE_FIELDS) == _pick(et, _ZONE_FIELDS), (
            f"{case_name} transparent[{i}]"
        )


# -- test_canon_hinge_correct ---------------------------------------------

def test_canon_hinge_correct() -> None:
    """Tous les hinge canoniques correspondent a l'attendu geometrique.

    B-F5 resolu (D-274 Passe 1.5b-1) : _flip_hinge_on_rotation tient
    compte de l'inversion de polarite de la face west.
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
    opens_inward), windows, doors, exclusion_zones et transparent_zones.
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
        else:
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
        else:
            for i, (pw, jw) in enumerate(zip(py_wins, js_wins)):
                pp = _pick(pw, _WINDOW_FIELDS)
                jp = _pick(jw, _WINDOW_FIELDS)
                if pp != jp:
                    mismatches.append(
                        f"{name} window[{i}]: py={pp} js={jp}"
                    )

        # Doors
        py_doors = py_canon.get("doors", [])
        js_doors = js_canon.get("doors", [])
        if len(py_doors) != len(js_doors):
            mismatches.append(
                f"{name} doors count: "
                f"py={len(py_doors)} js={len(js_doors)}"
            )
        else:
            for i, (pd, jd) in enumerate(zip(py_doors, js_doors)):
                pp = _pick(pd, _OPENING_FIELDS_ALL)
                jp = _pick(jd, _OPENING_FIELDS_ALL)
                if pp != jp:
                    mismatches.append(
                        f"{name} door[{i}]: py={pp} js={jp}"
                    )

        # Exclusion zones
        py_excl = py_canon.get("exclusion_zones", [])
        js_excl = js_canon.get("exclusion_zones", [])
        if len(py_excl) != len(js_excl):
            mismatches.append(
                f"{name} exclusion count: "
                f"py={len(py_excl)} js={len(js_excl)}"
            )
        else:
            for i, (pe, je) in enumerate(zip(py_excl, js_excl)):
                pp = _pick(pe, _ZONE_FIELDS)
                jp = _pick(je, _ZONE_FIELDS)
                if pp != jp:
                    mismatches.append(
                        f"{name} exclusion[{i}]: py={pp} js={jp}"
                    )

        # Transparent zones
        py_tz = py_canon.get("transparent_zones", [])
        js_tz = js_canon.get("transparent_zones", [])
        if len(py_tz) != len(js_tz):
            mismatches.append(
                f"{name} transparent count: "
                f"py={len(py_tz)} js={len(js_tz)}"
            )
        else:
            for i, (pt_, jt) in enumerate(zip(py_tz, js_tz)):
                pp = _pick(pt_, _ZONE_FIELDS)
                jp = _pick(jt, _ZONE_FIELDS)
                if pp != jp:
                    mismatches.append(
                        f"{name} transparent[{i}]: py={pp} js={jp}"
                    )

    assert not mismatches, (
        f"{len(mismatches)} parite mismatch(es):\n"
        + "\n".join(f"  {m}" for m in mismatches)
    )
