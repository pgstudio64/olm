"""Tests pour olm.core.units — D-274 Lot 1."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from olm.core.units import (
    INCH_TO_CM,
    cm_to_px,
    parse_drawing_scale,
    px_to_cm,
    scale_from_dpi_ratio,
)

# -- INCH_TO_CM ------------------------------------------------------------


def test_inch_to_cm_value() -> None:
    assert INCH_TO_CM == 2.54


# -- px_to_cm --------------------------------------------------------------


class TestPxToCm:

    def test_basic(self) -> None:
        assert px_to_cm(100, 2.96) == 296

    def test_half_up_rounds_up(self) -> None:
        """0.5 arrondi vers le haut (half-up, pas banker's)."""
        assert px_to_cm(1, 0.5) == 1  # 0.5 -> 1 (pas 0)
        assert px_to_cm(5, 0.5) == 3  # 2.5 -> 3 (pas 2)
        assert px_to_cm(3, 0.5) == 2  # 1.5 -> 2

    def test_zero_scale(self) -> None:
        assert px_to_cm(100, 0.0) == 0

    def test_fractional_result(self) -> None:
        assert px_to_cm(157, 2.96) == 465  # 464.72 -> 465


# -- cm_to_px --------------------------------------------------------------


class TestCmToPx:

    def test_basic(self) -> None:
        assert cm_to_px(296, 2.96) == 100

    def test_half_up_rounds_up(self) -> None:
        assert cm_to_px(1, 2.0) == 1  # 0.5 -> 1 (pas 0)
        assert cm_to_px(5, 2.0) == 3  # 2.5 -> 3 (pas 2)

    def test_zero_scale(self) -> None:
        assert cm_to_px(100, 0.0) == 0

    def test_fractional_result(self) -> None:
        assert cm_to_px(465, 2.96) == 157  # 157.094 -> 157


# -- Round-trip px <-> cm --------------------------------------------------


@pytest.mark.parametrize("cm_per_px", [0.5, 1.0, 2.96, 3.654])
@pytest.mark.parametrize("cm_val", [100, 250, 467, 601])
def test_px_cm_round_trip(cm_val: int, cm_per_px: float) -> None:
    """px_to_cm(cm_to_px(v, s), s) est a +-ceil(cm_per_px) de v."""
    px = cm_to_px(cm_val, cm_per_px)
    restored = px_to_cm(px, cm_per_px)
    tol = max(1, math.ceil(cm_per_px))
    assert abs(restored - cm_val) <= tol, (
        f"Round-trip cm={cm_val} scale={cm_per_px}: "
        f"px={px} -> restored={restored} (tol={tol})"
    )


# -- Coherence surface ----------------------------------------------------


def test_scale_surface_consistency() -> None:
    """bbox_px -> dims_cm -> surface_m2 coherent avec calcul direct."""
    cm_per_px = 2.96
    w_px, h_px = 158, 203
    w_cm = px_to_cm(w_px, cm_per_px)
    d_cm = px_to_cm(h_px, cm_per_px)
    surface = round(w_cm * d_cm / 10000, 2)
    surface_raw = round(w_px * h_px * cm_per_px ** 2 / 10000, 2)
    assert abs(surface - surface_raw) < 0.5


# -- scale_from_dpi_ratio -------------------------------------------------


def test_scale_from_dpi_ratio_basic() -> None:
    result = scale_from_dpi_ratio(72, 100)
    assert abs(result - 2.54 * 100 / 72) < 1e-10


def test_scale_from_dpi_ratio_invalid() -> None:
    assert scale_from_dpi_ratio(0, 100) == 0.0
    assert scale_from_dpi_ratio(72, 0) == 0.0


# -- parse_drawing_scale ---------------------------------------------------


def test_parse_drawing_scale_basic() -> None:
    result = parse_drawing_scale("1:100", 72)
    assert result is not None
    assert abs(result - 2.54 * 100 / 72) < 1e-10


def test_parse_drawing_scale_spaces() -> None:
    result = parse_drawing_scale("1 : 350", 150)
    assert result is not None
    expected = 2.54 * 350 / 150
    assert abs(result - expected) < 1e-10


def test_parse_drawing_scale_invalid() -> None:
    assert parse_drawing_scale("", 72) is None
    assert parse_drawing_scale("foo", 72) is None
    assert parse_drawing_scale("1:100", 0) is None


# -- Parite JS -------------------------------------------------------------


def test_units_js_parity() -> None:
    """Python et JS donnent les memes resultats pour px_to_cm/cm_to_px."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node introuvable — test parite JS skippe")

    runner = Path(__file__).parent / "js" / "units_runner.js"
    result = subprocess.run(
        [node, str(runner)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, (
        f"JS runner echoue:\n{result.stdout}\n{result.stderr}"
    )

    js_results = json.loads(result.stdout)

    # Cases identiques a celles testees ci-dessus en Python
    py_cases = [
        {"fn": "pxToCm", "args": [100, 2.96], "expected": px_to_cm(100, 2.96)},
        {"fn": "pxToCm", "args": [1, 0.5], "expected": px_to_cm(1, 0.5)},
        {"fn": "pxToCm", "args": [5, 0.5], "expected": px_to_cm(5, 0.5)},
        {"fn": "pxToCm", "args": [3, 0.5], "expected": px_to_cm(3, 0.5)},
        {"fn": "cmToPx", "args": [296, 2.96], "expected": cm_to_px(296, 2.96)},
        {"fn": "cmToPx", "args": [1, 2.0], "expected": cm_to_px(1, 2.0)},
        {"fn": "cmToPx", "args": [5, 2.0], "expected": cm_to_px(5, 2.0)},
        {"fn": "drawingScaleToCmPerPx", "args": [100, 72],
         "expected": scale_from_dpi_ratio(72, 100)},
    ]

    mismatches: list[str] = []
    for i, (py, js) in enumerate(zip(py_cases, js_results)):
        if isinstance(py["expected"], float):
            if abs(js["result"] - py["expected"]) > 1e-10:
                mismatches.append(
                    f"case[{i}] {py['fn']}{py['args']}: "
                    f"py={py['expected']} js={js['result']}"
                )
        else:
            if js["result"] != py["expected"]:
                mismatches.append(
                    f"case[{i}] {py['fn']}{py['args']}: "
                    f"py={py['expected']} js={js['result']}"
                )

    assert not mismatches, "\n".join(mismatches)
