"""Shared exceptions for olm.core modules.

Defined in a standalone module to avoid circular imports between
``pattern_fit``, ``catalogue_matcher`` and ``pattern_normalize``.
"""


class PatternStructurallyInvalid(Exception):
    """Pattern cannot be processed due to structural issues.

    Raised when blocks physically overlap, when the pattern definition
    is inconsistent, or when adaptation to a target room produces a
    collision. Subclassed by ``PatternAdaptOverlap`` for the adaptation
    case.
    """
