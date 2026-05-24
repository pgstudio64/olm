"""Parameters for static matching and the grid.

Groups the algorithmic parameters of the static pipeline (grid,
filtering thresholds). Normative parameters (spacings, exclusion zones)
remain in spacing_config.py.
"""

from olm.core.app_config import get as _cfg_get

# Cell size in cm. Used for matching sweeps, circulation grid construction,
# and all geometric discretisations.
GRID_CELL_CM: int = _cfg_get("grid_cell_cm", 10)

# Filtering threshold by desk count.
# Candidates with fewer than (1 - ratio) × max_desks_found are discarded.
# Example: ratio=0.30 → keep candidates with >= 70% of the best count.
_matching = _cfg_get("matching", {})
MIN_DESKS_DROP_RATIO: float = (
    _matching.get("min_desks_drop_ratio", 0.30) if isinstance(_matching, dict) else 0.30
)

# D-244: tolerance for oversize classification.
# A pattern whose footprint exceeds the room by <= FIT_TOLERANCE (per axis)
# is listed as "tolere" (grey). Beyond that it is hidden entirely.
FIT_TOLERANCE: float = 0.10

# D-271: footprint guard tolerance after adapt_to_room.
# Blocks must fit inside the room within this rounding margin (cm).
FOOTPRINT_GUARD_TOL_CM: int = 1

# D-242: OVERSIZE_MARGIN removed — no hard filter, all patterns proposed.
