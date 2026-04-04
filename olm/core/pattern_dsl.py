"""Pattern DSL parser and serializer.

Bijection DSL text <-> JSON per specs/PATTERN_DSL_SPEC.md.

DSL text:
    P_B4_B2F: BLOCK_4_FACE, 180, BLOCK_2_FACE
    P_B4_B4: BLOCK_4_FACE; 180; BLOCK_4_FACE

JSON:
    {"name": "P_B4_B2F", "rows": [{"blocks": [...]}], "row_gaps_cm": []}
"""
from __future__ import annotations

import re

from olm.core.dsl_common import DSLError, strip_comment

VALID_BLOCK_TYPES = frozenset({
    "BLOCK_1", "BLOCK_2_FACE", "BLOCK_2_SIDE",
    "BLOCK_3_SIDE", "BLOCK_4_FACE", "BLOCK_6_FACE",
    "BLOCK_2_ORTHO_L", "BLOCK_2_ORTHO_R",
})

VALID_ORIENTATIONS = frozenset({0, 90, 180, 270})


def parse_dsl(text: str) -> dict:
    """Parse une ligne DSL en dict JSON (format PATTERN_DSL_SPEC.md).

    Args:
        text: Ligne DSL, ex. "P_B4_B2F: BLOCK_4_FACE, 180, BLOCK_2_FACE"

    Returns:
        Dict avec clés name, rows, row_gaps_cm.

    Raises:
        DSLError: Syntaxe invalide ou type de bloc inconnu.
    """
    text = strip_comment(text)
    if not text:
        raise DSLError("Empty DSL")

    # Séparer nom : contenu
    if ":" not in text:
        raise DSLError(f"Missing ':' separator in: {text}")

    name_part, body = text.split(":", 1)
    name = name_part.strip()
    if not name:
        raise DSLError("Empty pattern name")
    if not re.match(r"^[A-Za-z0-9_ ]+$", name):
        raise DSLError(f"Invalid pattern name: {name}")

    body = body.strip()
    if not body:
        raise DSLError(f"Empty pattern body for: {name}")

    # Séparer les rangées par ";"
    raw_parts = [p.strip() for p in body.split(";")]

    rows = []
    row_gaps_cm = []

    i = 0
    while i < len(raw_parts):
        # Chaque rangée est une séquence d'éléments séparés par ","
        row_text = raw_parts[i]
        row = _parse_row(row_text)
        rows.append(row)
        i += 1

        # Après une rangée, un gap inter-rangée optionnel puis la rangée suivante
        if i < len(raw_parts):
            # Vérifier si c'est un gap (nombre pur) ou une rangée
            next_part = raw_parts[i]
            if re.match(r"^\d+$", next_part):
                row_gaps_cm.append(int(next_part))
                i += 1
            else:
                # Pas de gap explicite — erreur : un gap est requis entre rangées
                raise DSLError(
                    f"Missing inter-row gap between rows in: {name}"
                )

    return {"name": name, "rows": rows, "row_gaps_cm": row_gaps_cm}


def _parse_row(text: str) -> dict:
    """Parse une rangée (éléments séparés par virgule).

    Un gap avant le premier bloc est autorisé — il représente la distance
    entre le mur ouest et le premier bloc (gap_cm sur le premier bloc).
    """
    elements = [e.strip() for e in text.split(",")]
    blocks = []
    pending_gap: int | None = None

    for elem in elements:
        if not elem:
            continue
        if re.match(r"^\d+$", elem):
            # C'est un gap — le stocker pour le prochain bloc
            pending_gap = int(elem)
        else:
            # C'est un bloc
            block = _parse_block(elem)
            if pending_gap is not None:
                block["gap_cm"] = pending_gap
                pending_gap = None
            blocks.append(block)

    if not blocks:
        raise DSLError(f"Row without block: {text}")

    return {"blocks": blocks}


_OFFSET_RE = re.compile(r"^(S|N)(\d+)$")
_STICK_RE = re.compile(r"^@S([NSEW])$")
_VALID_STICK_DIRS = frozenset({"N", "S", "E", "W"})


def _parse_block(text: str) -> dict:
    """Parse a block element: BLOCK_TYPE[@ORIENT] [S<N>|N<N>] [@SN|@SS|@SE|@SW]*."""
    parts_ws = text.strip().split()
    main_part = parts_ws[0]
    offset_ns_cm = 0
    sticks: list[str] = []

    for token in parts_ws[1:]:
        offset_match = _OFFSET_RE.match(token)
        stick_match = _STICK_RE.match(token)
        if offset_match:
            direction = offset_match.group(1)
            value = int(offset_match.group(2))
            offset_ns_cm = value if direction == "S" else -value
        elif stick_match:
            d = stick_match.group(1)
            if d not in _VALID_STICK_DIRS:
                raise DSLError(f"Invalid stick direction: {token}")
            if d not in sticks:
                sticks.append(d)
        else:
            raise DSLError(f"Invalid token after block: {token}")

    if "@" in main_part:
        at_parts = main_part.split("@", 1)
        block_type = at_parts[0].strip()
        try:
            orientation = int(at_parts[1].strip())
        except ValueError:
            raise DSLError(f"Invalid orientation: {at_parts[1]}")
    else:
        block_type = main_part.strip()
        orientation = 0

    if block_type not in VALID_BLOCK_TYPES:
        raise DSLError(f"Unknown block type: {block_type}")
    if orientation not in VALID_ORIENTATIONS:
        raise DSLError(f"Invalid orientation ({orientation}), expected 0/90/180/270")

    result: dict = {"type": block_type, "orientation": orientation}
    if offset_ns_cm != 0:
        result["offset_ns_cm"] = offset_ns_cm
    if sticks:
        result["sticks"] = sticks
    return result


def to_dsl(pattern: dict) -> str:
    """Convertit un dict JSON (format PATTERN_DSL_SPEC.md) en ligne DSL.

    Args:
        pattern: Dict avec clés name, rows, row_gaps_cm.

    Returns:
        Ligne DSL, ex. "P_B4_B2F: BLOCK_4_FACE, 180, BLOCK_2_FACE"
    """
    name = pattern["name"]
    rows = pattern["rows"]
    row_gaps = pattern.get("row_gaps_cm", [])

    row_strs = []
    for row in rows:
        parts = []
        for block in row["blocks"]:
            block_str = block["type"]
            orient = block.get("orientation", 0)
            if orient != 0:
                block_str += f"@{orient}"
            offset = block.get("offset_ns_cm", 0)
            if offset > 0:
                block_str += f" S{offset}"
            elif offset < 0:
                block_str += f" N{-offset}"
            for s in block.get("sticks", []):
                block_str += f" @S{s}"
            gap = block.get("gap_cm")
            if gap is not None:
                parts.append(str(gap))
            parts.append(block_str)
        row_strs.append(", ".join(parts))

    # Intercaler les gaps inter-rangées
    result_parts = []
    for i, row_str in enumerate(row_strs):
        result_parts.append(row_str)
        if i < len(row_gaps):
            result_parts.append(str(row_gaps[i]))

    return f"{name}: {'; '.join(result_parts)}"


def parse_catalogue_dsl(text: str) -> list[dict]:
    """Parse un texte multi-lignes contenant plusieurs patterns DSL.

    Les lignes vides et les commentaires (--) sont ignorés.

    Args:
        text: Texte multi-lignes.

    Returns:
        Liste de dicts JSON.
    """
    patterns = []
    for raw_line in text.strip().splitlines():
        line = strip_comment(raw_line)
        if not line:
            continue
        patterns.append(parse_dsl(line))
    return patterns
