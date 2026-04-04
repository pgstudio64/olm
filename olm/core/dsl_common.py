"""Shared helpers for DSL parsers (pattern_dsl, room_dsl).

Provides:
- DSLError: base error class for all DSLs
- strip_comment: strip ``--`` comments
- parse_int: token -> int conversion with clear error messages
"""
from __future__ import annotations


class DSLError(ValueError):
    """Syntax or semantic error in a DSL."""


def strip_comment(line: str) -> str:
    """Strip ``--`` comment and leading/trailing whitespace.

    Args:
        line: Raw line possibly containing a comment.

    Returns:
        Cleaned line, possibly empty.
    """
    idx = line.find("--")
    if idx != -1:
        line = line[:idx]
    return line.strip()


def parse_int(token: str, name: str, context: str = "") -> int:
    """Convert a token to int with a clear error message.

    Args:
        token: String to convert.
        name: Field name (for error message).
        context: Additional context for error message
                 (e.g. "Line 3").

    Returns:
        Integer value.

    Raises:
        DSLError: If the token is not a valid integer.
    """
    try:
        return int(token)
    except ValueError:
        prefix = f"{context}: " if context else ""
        raise DSLError(
            f"{prefix}invalid {name} '{token}' (integer expected)"
        ) from None
