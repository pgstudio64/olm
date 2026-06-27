"""Non-régression du rendu d'arc de porte (renderShared.doorSvg) — D-322.

Le bug : la branche `face === 'west'` de doorSvg utilisait le même flag
`sweep` de base que la branche `east` au lieu de son miroir, donc l'arc des
portes sur mur ouest était dessiné « à l'envers » (centré sur le coin opposé
à la charnière). Ce test verrouille les 16 combinaisons
(face × hinge_side × opens_inward) : l'arc doit toujours être centré sur la
charnière.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_door_arc_centered_at_hinge() -> None:
    """Les 16 arcs de porte sont centrés sur la charnière (pas l'opposé)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node introuvable — test rendu arc skippé")

    runner = Path(__file__).parent / "js" / "door_arc_runner.js"
    result = subprocess.run(
        [node, str(runner)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, (
        f"JS runner échoue:\n{result.stdout}\n{result.stderr}"
    )

    cases = json.loads(result.stdout)
    assert len(cases) == 16, f"attendu 16 cas, reçu {len(cases)}"

    inverted = [
        f"{c['face']}/{c['swing']}/inward={c['inward']}"
        for c in cases if not c["center_at_hinge"]
    ]
    assert not inverted, "arcs inversés (centre ≠ charnière): " + ", ".join(inverted)
