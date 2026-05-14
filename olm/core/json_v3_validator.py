"""JSON v3 plan validator — validates plan data against the v3 JSON Schema.

Uses ``jsonschema`` (draft-07) to catch malformed plans at import, save,
and load time.  See ``olm/core/schemas/plan_v3.json`` for the schema.

D-188 / P2.7.
"""
from __future__ import annotations

import json
import logging
import os

try:
    import jsonschema
except ImportError:
    jsonschema = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "schemas", "plan_v3.json",
)
_schema_cache: dict | None = None


def load_schema() -> dict:
    """Load and cache the plan v3 JSON Schema from disk.

    Returns:
        The parsed JSON Schema dict.
    """
    global _schema_cache  # noqa: PLW0603
    if _schema_cache is not None:
        return _schema_cache
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        _schema_cache = json.load(f)
    return _schema_cache


def validate_plan(data: dict) -> None:
    """Validate a plan dict against the v3 JSON Schema.

    Args:
        data: the plan dict to validate.

    Raises:
        ValueError: with a human-readable message indicating the
            JSON path and the validation error.
    """
    if jsonschema is None:
        logger.warning("jsonschema not installed — validation skipped")
        return
    schema = load_schema()
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if not errors:
        return
    first = errors[0]
    path = ".".join(str(p) for p in first.absolute_path) or "(root)"
    raise ValueError(f"JSON v3 invalide a '{path}': {first.message}")
