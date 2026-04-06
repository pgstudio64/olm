from dataclasses import dataclass
import json

from olm.core.app_config import get as _cfg_get

# AFNOR NF X35-102
# Desk dimensions — human perspective:
#   width  = large side (left-right when seated) = 180 cm
#   depth  = front-to-back (towards screen)      = 80 cm
DESK_W_CM: int = _cfg_get("desk_width_cm", 180)   # desk width
DESK_D_CM: int = _cfg_get("desk_depth_cm", 80)    # desk depth
CHAIR_CLEARANCE_CM = 70   # ES-01 chair clearance — fixed non-overlappable zone
PASSAGE_CM = 90           # ES-06 minimum circulation zone — mandatory, extensible
PASSAGE_SINGLE_CM = 30    # ES-03 minimum circulation zone for single desk access

# Note: the `candidate_cm` field is kept for compatibility but designates a
# minimum circulation zone (mandatory, extensible but not reducible). The old
# term "suppressible candidate zone" was dropped along with the debt/slack approach.


@dataclass
class FaceZone:
    """Clearance zone on one face of a block.

    Two components:
    - non_superposable_cm: fixed zone (chair clearance), incompressible.
    - candidate_cm: minimum circulation zone, mandatory and extensible
      but not reducible. Scoring/rebalancing may increase it.

    Attributes:
        non_superposable_cm: Thickness of the fixed zone (chair clearance).
        candidate_cm: Thickness of the minimum circulation zone.
    """

    non_superposable_cm: int = 0
    candidate_cm: int = 0

    @property
    def total_cm(self) -> int:
        """Total thickness (fixed zone + minimum circulation zone)."""
        return self.non_superposable_cm + self.candidate_cm

    @classmethod
    def absent(cls) -> "FaceZone":
        """No zone on this face (screen side or wall)."""
        return cls(0, 0)

    @classmethod
    def circulation_only(cls) -> "FaceZone":
        """Minimum circulation zone only — 90 cm (ES-06)."""
        return cls(0, PASSAGE_CM)

    @classmethod
    def chair_and_circulation(cls) -> "FaceZone":
        """Fixed zone (70 cm) + minimum circulation zone (90 cm)."""
        return cls(CHAIR_CLEARANCE_CM, PASSAGE_CM)


@dataclass
class FaceCandidates:
    """Clearance zones on the four faces of a block."""

    north: FaceZone
    south: FaceZone
    east: FaceZone
    west: FaceZone


@dataclass
class Block:
    name: str
    eo_cm: int          # EO dimension (width)
    ns_cm: int          # NS dimension (depth) = DESK_D_CM always
    n_desks: int
    faces: FaceCandidates
    symmetric_180: bool = False  # True if block is identical after 180° rotation
    derogatory: bool = False


@dataclass
class Pattern:
    name: str
    blocks: list[Block]
    n_desks: int
    physical_eo_cm: int   # desks only
    physical_ns_cm: int
    total_eo_cm: int      # including all candidate zones
    total_ns_cm: int
    orientation: int = 0  # 0, 90, 180 ou 270


# Block faces — fixed zone (chair clearance) + minimum circulation zone:
# - N/S (front/back of desks): no chair -> absent
# - E/W face-to-face blocks: ES-04 = 70 + 90 = 160 cm (passage behind occupied desk)
# - E/W single/side-by-side blocks: ES-03 = 70 + 30 = 100 cm (single desk access)
_FACE_CHAIR_PASSAGE = FaceZone(CHAIR_CLEARANCE_CM, PASSAGE_CM)         # 70 + 90 = 160 cm
_FACE_CHAIR_ACCESS = FaceZone(CHAIR_CLEARANCE_CM, PASSAGE_SINGLE_CM)   # 70 + 30 = 100 cm

BLOCK_2_FACE = Block(
    name="BLOCK_2_FACE",
    eo_cm=DESK_D_CM * 2,     # 160 cm (2 × depth)
    ns_cm=DESK_W_CM,          # 180 cm (1 × width)
    n_desks=2,
    faces=FaceCandidates(
        north=FaceZone.absent(),
        south=FaceZone.absent(),
        east=_FACE_CHAIR_PASSAGE,    # ES-04 : 70 + 90 = 160 cm
        west=_FACE_CHAIR_PASSAGE,
    ),
    symmetric_180=True,
)

BLOCK_1 = Block(
    name="BLOCK_1",
    eo_cm=DESK_D_CM,          # 80 cm (depth)
    ns_cm=DESK_W_CM,          # 180 cm (width)
    n_desks=1,
    faces=FaceCandidates(
        north=FaceZone.absent(),
        south=FaceZone.absent(),
        east=FaceZone.absent(),
        west=_FACE_CHAIR_ACCESS,     # ES-03 : 70 + 30 = 100 cm
    ),
)

BLOCK_2_SIDE = Block(
    name="BLOCK_2_SIDE",
    eo_cm=DESK_D_CM,          # 80 cm (depth)
    ns_cm=DESK_W_CM * 2,      # 360 cm (2 × width)
    n_desks=2,
    faces=FaceCandidates(
        north=FaceZone.absent(),
        south=FaceZone.absent(),
        east=FaceZone.absent(),
        west=_FACE_CHAIR_ACCESS,     # ES-03 : 70 + 30 = 100 cm
    ),
)

BLOCK_3_SIDE = Block(
    name="BLOCK_3_SIDE",
    eo_cm=DESK_D_CM,          # 80 cm (depth)
    ns_cm=DESK_W_CM * 3,      # 540 cm (3 × width)
    n_desks=3,
    faces=FaceCandidates(
        north=FaceZone.absent(),
        south=FaceZone.absent(),
        east=FaceZone.absent(),
        west=_FACE_CHAIR_ACCESS,     # ES-03 : 70 + 30 = 100 cm
    ),
)

BLOCK_4_FACE = Block(
    name="BLOCK_4_FACE",
    eo_cm=DESK_D_CM * 2,     # 160 cm (2 × depth)
    ns_cm=DESK_W_CM * 2,     # 360 cm (2 × width)
    n_desks=4,
    faces=FaceCandidates(
        north=FaceZone.absent(),
        south=FaceZone.absent(),
        east=_FACE_CHAIR_PASSAGE,    # ES-04 : 70 + 90 = 160 cm
        west=_FACE_CHAIR_PASSAGE,
    ),
    symmetric_180=True,
)

BLOCK_6_FACE = Block(
    name="BLOCK_6_FACE",
    eo_cm=DESK_D_CM * 2,     # 160 cm (2 × depth)
    ns_cm=DESK_W_CM * 3,     # 540 cm (3 × width)
    n_desks=6,
    faces=FaceCandidates(
        north=FaceZone.absent(),
        south=FaceZone.absent(),
        east=_FACE_CHAIR_PASSAGE,    # ES-04 : 70 + 90 = 160 cm
        west=_FACE_CHAIR_PASSAGE,
    ),
    symmetric_180=True,
    derogatory=True,
)

# Orthogonal blocks: 2 desks at 90° to each other, adjacent
# BLOCK_2_ORTHO_R: L at bottom-left (desk1 faces south, desk2 faces west)
#   +--------180cm---------+
#   |   Desk1 (facing S)    | 80cm
#   +------+----------------+
#   |Desk2 |
#   |(fac.W| 180cm
#   |      |
#   +------+
#    80cm
# Chairs: desk1=north, desk2=east
BLOCK_2_ORTHO_R = Block(
    name="BLOCK_2_ORTHO_R",
    eo_cm=DESK_W_CM,          # 180 cm (width of desk1)
    ns_cm=DESK_D_CM + DESK_W_CM,  # 260 cm (80+180)
    n_desks=2,
    faces=FaceCandidates(
        north=_FACE_CHAIR_ACCESS,    # ES-03 : chaise desk1
        south=FaceZone.absent(),
        east=_FACE_CHAIR_ACCESS,     # ES-03 : chaise desk2
        west=FaceZone.absent(),
    ),
)

# BLOCK_2_ORTHO_L: mirror — L at bottom-right (desk1 faces south, desk2 faces east)
#   +--------180cm---------+
#   |   Desk1 (facing S)    | 80cm
#   +----------------+------+
#                    |Desk2 |
#                    |(fac.E| 180cm
#                    |      |
#                    +------+
#                     80cm
# Chairs: desk1=north, desk2=west
BLOCK_2_ORTHO_L = Block(
    name="BLOCK_2_ORTHO_L",
    eo_cm=DESK_W_CM,          # 180 cm (width)
    ns_cm=DESK_D_CM + DESK_W_CM,  # 260 cm (80+180)
    n_desks=2,
    faces=FaceCandidates(
        north=_FACE_CHAIR_ACCESS,    # ES-03 : chaise desk1
        south=FaceZone.absent(),
        east=FaceZone.absent(),
        west=_FACE_CHAIR_ACCESS,     # ES-03 : chaise desk2
    ),
)


@dataclass
class DoubleRowPattern:
    name: str
    north_row: Pattern
    south_row: Pattern
    n_desks: int
    physical_eo_cm: int    # max(north_row.physical_eo_cm, south_row.physical_eo_cm)
    physical_ns_cm: int    # 2 x DESK_D_CM
    total_eo_cm: int
    total_ns_cm: int       # see decomposition below
    central_corridor_cm: int  # always CHAIR_CLEARANCE_CM x 2 + PASSAGE_CM
    orientation: int = 0  # 0, 90, 180 ou 270


def compose_row(blocks: list[Block], name: str) -> Pattern:
    """Compose a row of EO-aligned blocks.

    Candidate zones between adjacent blocks are merged: only one 90 cm
    passage is counted, not two. The west and east ends of the row inherit
    the faces of the first and last block.

    Args:
        blocks: Ordered list of blocks from west to east.
        name: Pattern identifier.

    Returns:
        Composed pattern with computed footprints.
    """
    assert blocks, "Block list cannot be empty"

    physical_eo = sum(b.eo_cm for b in blocks)
    ns = max(b.ns_cm for b in blocks)
    n_desks = sum(b.n_desks for b in blocks)

    west_zone  = blocks[0].faces.west
    east_zone  = blocks[-1].faces.east
    north_zone = blocks[0].faces.north
    south_zone = blocks[0].faces.south

    total_eo = west_zone.total_cm + physical_eo + east_zone.total_cm
    total_ns = north_zone.candidate_cm + ns + south_zone.candidate_cm

    return Pattern(
        name=name,
        blocks=blocks,
        n_desks=n_desks,
        physical_eo_cm=physical_eo,
        physical_ns_cm=ns,
        total_eo_cm=total_eo,
        total_ns_cm=total_ns,
    )


def compose_double_row(
    north_blocks: list[Block],
    south_blocks: list[Block],
    name: str,
) -> DoubleRowPattern:
    """Compose a double-row pattern (north + south) — orientation Option B.

    Desks are oriented NS (180 cm), users face E/W.
    Chair clearances (70 cm) are along the EO axis — internal to blocks.

    NS decomposition (Option B):
        90 cm  — north candidate passage (removable if row is against north wall)
       180 cm  — north row desks
        90 cm  — inter-row passage ES-06 (passage between two distinct blocks)
       180 cm  — south row desks
        90 cm  — south candidate passage
       ------
       630 cm  total NS with all candidate zones

    Args:
        north_blocks: North row blocks.
        south_blocks: South row blocks.
        name: Double-row pattern identifier.

    Returns:
        DoubleRowPattern with computed footprints.
    """
    north = compose_row(north_blocks, name + "_N")
    south = compose_row(south_blocks, name + "_S")

    inter_row_passage = PASSAGE_CM  # ES-06 = 90 cm

    total_ns = (
        PASSAGE_CM          # north candidate zone
        + DESK_D_CM         # north row desks
        + inter_row_passage # inter-row passage
        + DESK_D_CM         # south row desks
        + PASSAGE_CM        # south candidate zone
    )

    return DoubleRowPattern(
        name=name,
        north_row=north,
        south_row=south,
        n_desks=north.n_desks + south.n_desks,
        physical_eo_cm=max(north.physical_eo_cm, south.physical_eo_cm),
        physical_ns_cm=DESK_D_CM * 2,
        total_eo_cm=max(north.total_eo_cm, south.total_eo_cm),
        total_ns_cm=total_ns,
        central_corridor_cm=inter_row_passage,
    )


def rotate_face_candidates(faces: FaceCandidates, degrees: int) -> FaceCandidates:
    """Clockwise rotation of block faces.

    90° clockwise: N->E, E->S, S->W, W->N
    (what was north becomes east, etc.)

    Args:
        faces: Original FaceCandidates.
        degrees: 90, 180 or 270.

    Returns:
        New rotated FaceCandidates.
    """
    steps = (degrees // 90) % 4
    n, e, s, w = faces.north, faces.east, faces.south, faces.west
    for _ in range(steps):
        n, e, s, w = w, n, e, s
    return FaceCandidates(north=n, south=s, east=e, west=w)


def rotate_pattern_90(pattern: Pattern) -> Pattern:
    """Clockwise 90° rotation of a single-row pattern.

    Swaps EO <-> NS. Rotates the faces of each block.
    Suffix __R90 appended to the name.

    Args:
        pattern: Pattern at orientation 0°.

    Returns:
        New Pattern at 90°.
    """
    rotated_blocks = [
        Block(
            name=b.name,
            eo_cm=b.ns_cm,
            ns_cm=b.eo_cm,
            n_desks=b.n_desks,
            faces=rotate_face_candidates(b.faces, 90),
            derogatory=b.derogatory,
        )
        for b in pattern.blocks
    ]
    new_phys_eo = pattern.physical_ns_cm
    new_phys_ns = pattern.physical_eo_cm

    west_zone  = rotated_blocks[0].faces.west
    east_zone  = rotated_blocks[-1].faces.east
    north_zone = rotated_blocks[0].faces.north
    south_zone = rotated_blocks[0].faces.south

    new_total_eo = west_zone.total_cm + new_phys_eo + east_zone.total_cm
    new_total_ns = north_zone.candidate_cm + new_phys_ns + south_zone.candidate_cm

    return Pattern(
        name=pattern.name + "__R90",
        blocks=rotated_blocks,
        n_desks=pattern.n_desks,
        physical_eo_cm=new_phys_eo,
        physical_ns_cm=new_phys_ns,
        total_eo_cm=new_total_eo,
        total_ns_cm=new_total_ns,
        orientation=90,
    )


def rotate_double_row_90(pattern: DoubleRowPattern) -> DoubleRowPattern:
    """Clockwise 90° rotation of a double-row pattern.

    Rotates both rows via rotate_pattern_90.
    Suffix __R90 appended to the name.

    Args:
        pattern: DoubleRowPattern at orientation 0°.

    Returns:
        New DoubleRowPattern at 90°.
    """
    north_r = rotate_pattern_90(pattern.north_row)
    south_r = rotate_pattern_90(pattern.south_row)
    return DoubleRowPattern(
        name=pattern.name + "__R90",
        north_row=north_r,
        south_row=south_r,
        n_desks=pattern.n_desks,
        physical_eo_cm=pattern.physical_ns_cm,
        physical_ns_cm=pattern.physical_eo_cm,
        total_eo_cm=max(north_r.total_eo_cm, south_r.total_eo_cm),
        total_ns_cm=max(north_r.total_ns_cm, south_r.total_ns_cm),
        central_corridor_cm=pattern.central_corridor_cm,
        orientation=90,
    )


def mirror_double_row(pattern: DoubleRowPattern) -> "DoubleRowPattern | None":
    """EO mirror of an asymmetric double-row pattern.

    Returns None if north_row == south_row (redundant mirror).
    Suffix __MIRROR appended to the name.

    Args:
        pattern: DoubleRowPattern at orientation 0°.

    Returns:
        Mirrored DoubleRowPattern or None.
    """
    north_names = [b.name for b in pattern.north_row.blocks]
    south_names = [b.name for b in pattern.south_row.blocks]
    if north_names == south_names:
        return None
    return DoubleRowPattern(
        name=pattern.name + "__MIRROR",
        north_row=pattern.south_row,
        south_row=pattern.north_row,
        n_desks=pattern.n_desks,
        physical_eo_cm=pattern.physical_eo_cm,
        physical_ns_cm=pattern.physical_ns_cm,
        total_eo_cm=pattern.total_eo_cm,
        total_ns_cm=pattern.total_ns_cm,
        central_corridor_cm=pattern.central_corridor_cm,
        orientation=pattern.orientation,
    )


PATTERNS = [
    compose_row([BLOCK_4_FACE], "P_B4"),
    compose_row([BLOCK_4_FACE, BLOCK_2_FACE], "P_B4_B2F"),
    compose_row([BLOCK_6_FACE], "P_B6"),
    compose_row([BLOCK_6_FACE, BLOCK_2_FACE], "P_B6_B2F"),
]
PATTERNS_ALL = PATTERNS + [rotate_pattern_90(p) for p in PATTERNS]

DOUBLE_ROW_PATTERNS = [
    compose_double_row([BLOCK_4_FACE],              [BLOCK_4_FACE],              "P_B4_B4"),
    compose_double_row([BLOCK_4_FACE],              [BLOCK_4_FACE, BLOCK_2_FACE], "P_B4_B4B2F"),
    compose_double_row([BLOCK_4_FACE, BLOCK_2_FACE], [BLOCK_4_FACE, BLOCK_2_FACE], "P_B4B2F_B4B2F"),
    compose_double_row([BLOCK_2_FACE],              [BLOCK_2_FACE],              "P_B2F_B2F"),
    compose_double_row([BLOCK_2_FACE],              [BLOCK_4_FACE],              "P_B2F_B4"),
    compose_double_row([BLOCK_4_FACE, BLOCK_2_FACE], [BLOCK_4_FACE],              "P_B4B2F_B4"),
]
_mirrors = [mirror_double_row(p) for p in DOUBLE_ROW_PATTERNS]
DOUBLE_ROW_PATTERNS_ALL = (
    DOUBLE_ROW_PATTERNS
    + [rotate_double_row_90(p) for p in DOUBLE_ROW_PATTERNS]
    + [m for m in _mirrors if m is not None]
)


def compute_sqm_per_desk(pattern: "Pattern | DoubleRowPattern") -> float:
    """Effective area per desk (m²), including non-overlappable clearances.

    Formula:
        effective_eo = west.non_superposable_cm + physical_eo + east.non_superposable_cm
        area_cm2     = effective_eo x physical_ns_cm
        sqm          = area_cm2 / (10 000 x n_desks)

    Args:
        pattern: Single-row or double-row pattern.

    Returns:
        Area rounded to 2 decimal places, in m²/desk.
    """
    if hasattr(pattern, "north_row"):           # DoubleRowPattern
        west_ns = pattern.north_row.blocks[0].faces.west.non_superposable_cm
        east_ns = pattern.north_row.blocks[-1].faces.east.non_superposable_cm
    else:                                       # Pattern
        west_ns = pattern.blocks[0].faces.west.non_superposable_cm
        east_ns = pattern.blocks[-1].faces.east.non_superposable_cm
    effective_eo = west_ns + pattern.physical_eo_cm + east_ns
    area_cm2 = effective_eo * pattern.physical_ns_cm
    return round(area_cm2 / (10_000 * pattern.n_desks), 2)


def compute_circulation_grade_cm(pattern: "Pattern | DoubleRowPattern") -> int:
    """Intrinsic circulation grade of the pattern, in cm.

    For a DoubleRowPattern: width of the inter-row corridor (central_corridor_cm).
    For a single-row Pattern: north candidate zone (ES-06 passage).

    Args:
        pattern: Single-row or double-row pattern.

    Returns:
        Passage width in cm.
    """
    if hasattr(pattern, "central_corridor_cm"):
        return pattern.central_corridor_cm
    return pattern.blocks[0].faces.north.candidate_cm


def export_catalogue(
    patterns: list[Pattern],
    double_patterns: list[DoubleRowPattern],
    path: str,
) -> None:
    """Export the complete catalogue to JSON (single + double row).

    Args:
        patterns: Single-row patterns.
        double_patterns: Double-row patterns.
        path: Output JSON file path.
    """
    data = {
        "single_row": [
            {
                "name": p.name,
                "orientation": p.orientation,
                "n_desks": p.n_desks,
                "physical_eo_cm": p.physical_eo_cm,
                "physical_ns_cm": p.physical_ns_cm,
                "total_eo_cm": p.total_eo_cm,
                "total_ns_cm": p.total_ns_cm,
                "west_zone_cm":  p.blocks[0].faces.west.total_cm,
                "east_zone_cm":  p.blocks[-1].faces.east.total_cm,
                "north_zone_cm": p.blocks[0].faces.north.total_cm,
                "south_zone_cm": p.blocks[0].faces.south.total_cm,
                "blocks": [b.name for b in p.blocks],
                "sqm_per_desk": compute_sqm_per_desk(p),
                "circulation_grade_cm": compute_circulation_grade_cm(p),
            }
            for p in patterns
        ],
        "double_row": [
            {
                "name": p.name,
                "orientation": p.orientation,
                "n_desks": p.n_desks,
                "physical_eo_cm": p.physical_eo_cm,
                "physical_ns_cm": p.physical_ns_cm,
                "total_eo_cm": p.total_eo_cm,
                "total_ns_cm": p.total_ns_cm,
                "central_corridor_cm": p.central_corridor_cm,
                "west_zone_cm":  p.north_row.blocks[0].faces.west.total_cm,
                "east_zone_cm":  p.north_row.blocks[-1].faces.east.total_cm,
                "north_zone_cm": p.north_row.blocks[0].faces.north.total_cm,
                "south_zone_cm": p.north_row.blocks[0].faces.south.total_cm,
                "north_blocks": [b.name for b in p.north_row.blocks],
                "south_blocks": [b.name for b in p.south_row.blocks],
                "sqm_per_desk": compute_sqm_per_desk(p),
                "circulation_grade_cm": compute_circulation_grade_cm(p),
            }
            for p in double_patterns
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def pareto_front(patterns: list) -> list:
    """Return Pareto-optimal patterns.

    Criteria:
      - sqm_per_desk  -> minimise
      - circulation_grade_cm -> maximise

    Pattern A dominates B if:
      A.sqm_per_desk  <= B.sqm_per_desk
      A.circulation_grade_cm >= B.circulation_grade_cm
      and at least one inequality is strict.

    Comparison is only performed between patterns with
    the same n_desks.

    Args:
        patterns: Mixed list of Pattern and DoubleRowPattern.

    Returns:
        Sublist of non-dominated patterns.
    """
    non_dominated = []
    for candidate in patterns:
        sqm_c = compute_sqm_per_desk(candidate)
        circ_c = compute_circulation_grade_cm(candidate)
        dominated = False
        for other in patterns:
            if other is candidate:
                continue
            if other.n_desks != candidate.n_desks:
                continue
            sqm_o = compute_sqm_per_desk(other)
            circ_o = compute_circulation_grade_cm(other)
            if (sqm_o <= sqm_c
                    and circ_o >= circ_c
                    and (sqm_o < sqm_c or circ_o > circ_c)):
                dominated = True
                break
        if not dominated:
            non_dominated.append(candidate)
    return non_dominated


def export_pareto_catalogue() -> list[dict]:
    """Return only the Pareto-optimal catalogue entries.

    Returns:
        List of dicts (catalogue JSON format) of non-dominated patterns.
    """
    all_patterns = PATTERNS_ALL + DOUBLE_ROW_PATTERNS_ALL
    front = pareto_front(all_patterns)
    single = [p for p in front if not hasattr(p, "central_corridor_cm")]
    double = [p for p in front if hasattr(p, "central_corridor_cm")]
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    export_catalogue(single, double, tmp_path)
    with open(tmp_path, encoding="utf-8") as f:
        data = json.load(f)
    os.unlink(tmp_path)
    return data["single_row"] + data["double_row"]


def render_pattern_svg(pattern: DoubleRowPattern, path: str) -> None:
    """Generate a top-view SVG of a double-row pattern.

    Scale: 1 px = 2 cm (scale = 0.5). Dark background #1e1e1e.
    Candidate zones (90 cm): blue #4a90c4 fill-opacity 0.35, dasharray "5 3".
    Chair clearances (70 cm): orange #c8922a fill-opacity 0.55.
    Desks: grey #d0d0d0 fill, #888888 stroke.
    Screens: rect #1a1a1a rx=1.
    Chairs: rect #8B6914 rx=5, back #6a4e0e rx=3, armrests #7a5c10 rx=2.
            60% hidden under the desk (z-order).

    Rendering by block type:
      BLOCK_4 / BLOCK_6: NS chairs (facing N or S), horizontal orange at
                         outer row edges, horizontal screen at inner edge.
      BLOCK_2_FACE:      EW chairs (facing E or W), vertical orange on EW
                         faces of the block, vertical screen at inner edge.

    NS geometry (top to bottom):
      [blue N 90] [desks N 180] [corr 90] [desks S 180] [blue S 90]

    Args:
        pattern: Double-row pattern to draw.
        path: Output SVG file path.
    """
    BG          = "#1e1e1e"
    BLUE_FILL   = "#4a90c4"
    BLUE_OP     = "0.35"
    ORANGE_FILL = "#c8922a"
    ORANGE_OP   = "0.55"
    DESK_FILL   = "#d0d0d0"
    DESK_STR    = "#888888"
    SCREEN_COL  = "#1a1a1a"
    CHAIR_COL   = "#8B6914"
    CHAIR_BACK  = "#6a4e0e"
    CHAIR_ARM   = "#7a5c10"
    TEXT_BLUE   = "#a0c4e8"
    TEXT_OR     = "#d4a847"
    TEXT_W      = "#ffffff"
    TEXT_DIM    = "#cccccc"

    scale     = 0.5
    margin_t  = 70
    annot_r   = 130
    annot_top = 16

    def cm(v: int | float) -> float:
        """Convert centimetres to SVG pixels."""
        return v * scale

    dw      = cm(DESK_W_CM)             # 40 px  (80 cm)
    dh      = cm(DESK_D_CM)             # 90 px  (180 cm)
    deb_px  = cm(CHAIR_CLEARANCE_CM)    # 35 px  (70 cm)
    cand_px = cm(PASSAGE_CM)            # 45 px  (90 cm)

    # EO footprint of desks (widest row)
    eo_n = cm(sum(b.eo_cm for b in pattern.north_row.blocks))
    eo_s = cm(sum(b.eo_cm for b in pattern.south_row.blocks))
    eo_w = max(eo_n, eo_s)

    # EO coordinates
    x_bl_w = 20.0
    x_or_w = x_bl_w + cand_px
    x_dsk  = x_or_w + deb_px
    x_or_e = x_dsk  + eo_w
    x_bl_e = x_or_e + deb_px
    x_end  = x_bl_e + cand_px
    full_w = x_end - x_bl_w

    # NS coordinates
    y0       = margin_t + annot_top
    y_blue_n = y0
    y_desk_n = y_blue_n + cand_px
    y_corr   = y_desk_n + dh
    y_desk_s = y_corr   + cand_px
    y_blue_s = y_desk_s + dh
    y_bottom = y_blue_s + cand_px

    svg_w = int(x_end + annot_r)
    svg_h = int(y_bottom + 130)      # space for vertical legend (3 x 17 px + margins)

    L: list[str] = []

    def out(s: str) -> None:
        L.append(s)

    def _is_facing_ns(block: Block) -> bool:
        """True for BLOCK_4_FACE and BLOCK_6_FACE (facing N/S); False for BLOCK_2_FACE (facing E/W)."""
        return block.name in ("BLOCK_4_FACE", "BLOCK_6_FACE")

    # --- primitives ---

    def draw_zone_candidate(x: float, y: float, w: float, h: float,
                            label: str) -> None:
        """Semi-transparent blue hatched rectangle + optional centred label."""
        out(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{BLUE_FILL}" fill-opacity="{BLUE_OP}" '
            f'stroke="{BLUE_FILL}" stroke-width="0.8" stroke-dasharray="5 3"/>')
        if label:
            out(f'<text x="{x + w/2:.1f}" y="{y + h/2 + 4:.1f}" '
                f'text-anchor="middle" font-family="sans-serif" '
                f'font-size="9" fill="{TEXT_BLUE}">{label}</text>')

    def draw_zone_orange(x: float, y: float, w: float, h: float,
                         label: str = "") -> None:
        """Semi-transparent orange rectangle + optional centred label."""
        out(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{ORANGE_FILL}" fill-opacity="{ORANGE_OP}" '
            f'stroke="{ORANGE_FILL}" stroke-width="0.5"/>')
        if label:
            out(f'<text x="{x + w/2:.1f}" y="{y + h/2 + 4:.1f}" '
                f'text-anchor="middle" font-family="sans-serif" '
                f'font-size="8" fill="{TEXT_OR}">{label}</text>')

    def draw_desk(x: float, y: float, w: float, h: float,
                  screen_side: str) -> None:
        """Grey desk surface + screen on the specified edge.

        screen_side W/E: vertical screen 5 px x 55% h, centred NS.
        screen_side N/S: horizontal screen 55% w x 5 px, centred EO.
        """
        out(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{DESK_FILL}" stroke="{DESK_STR}" stroke-width="1"/>')
        if screen_side in ('W', 'E'):
            scr_h = h * 0.55
            scr_y = y + (h - scr_h) / 2
            scr_x = x if screen_side == 'W' else x + w - 5.0
            out(f'<rect x="{scr_x:.1f}" y="{scr_y:.1f}" '
                f'width="5" height="{scr_h:.1f}" fill="{SCREEN_COL}" rx="1"/>')
        else:  # N ou S
            scr_w = w * 0.55
            scr_x = x + (w - scr_w) / 2
            scr_y = y if screen_side == 'N' else y + h - 5.0
            out(f'<rect x="{scr_x:.1f}" y="{scr_y:.1f}" '
                f'width="{scr_w:.1f}" height="5" fill="{SCREEN_COL}" rx="1"/>')

    def draw_chair_ew(bx: float, y_desk: float, screen_side: str) -> None:
        """EW chair (BLOCK_2_FACE, facing E or W) — 60% under the desk.

        Body 40x22 px, back 7x16 px on outer side, armrests 22x5 px N and S.
        """
        ch_w, ch_h = 40.0, 22.0
        overlap = ch_w * 0.6        # 24 px sous le bureau
        ch_y = y_desk + (dh - ch_h) / 2
        if screen_side == 'W':
            ch_x   = bx - (ch_w - overlap)
            dos_x  = ch_x - 2
            acc_x  = ch_x + 3
        else:
            ch_x   = bx + dw - overlap
            dos_x  = ch_x + ch_w - 5
            acc_x  = ch_x + 15
        out(f'<rect x="{ch_x:.1f}" y="{ch_y:.1f}" '
            f'width="{ch_w:.1f}" height="{ch_h:.1f}" fill="{CHAIR_COL}" rx="5"/>')
        out(f'<rect x="{dos_x:.1f}" y="{ch_y + 3:.1f}" '
            f'width="7" height="16" fill="{CHAIR_BACK}" rx="3"/>')
        out(f'<rect x="{acc_x:.1f}" y="{ch_y - 3:.1f}" '
            f'width="22" height="5" fill="{CHAIR_ARM}" rx="2"/>')
        out(f'<rect x="{acc_x:.1f}" y="{ch_y + ch_h:.1f}" '
            f'width="22" height="5" fill="{CHAIR_ARM}" rx="2"/>')

    def draw_chair_ns(bx: float, y_desk: float, side: str) -> None:
        """NS chair (BLOCK_4/6, facing N or S) — 60% under the desk.

        Body (dw x 0.8) x 22 px, back on outer side (N for north row, S for south).
        Vertical armrests left and right.
        side='N': back north, user faces south; 60% overlap above the desk.
        side='S': back south, user faces north; 60% overlap below the desk.
        """
        ch_w = dw * 0.8
        ch_h = 22.0
        overlap = ch_h * 0.6
        ch_x = bx + (dw - ch_w) / 2
        if side == 'N':
            ch_y  = y_desk - (ch_h - overlap)  # 40% visible above the desk
            dos_y = ch_y - 2
        else:
            ch_y  = y_desk + dh - overlap       # 60% under the desk, 40% visible below
            dos_y = ch_y + ch_h - 4
        arm_h = ch_h * 0.5
        out(f'<rect x="{ch_x:.1f}" y="{ch_y:.1f}" '
            f'width="{ch_w:.1f}" height="{ch_h:.1f}" fill="{CHAIR_COL}" rx="5"/>')
        out(f'<rect x="{ch_x + 3:.1f}" y="{dos_y:.1f}" '
            f'width="{ch_w - 6:.1f}" height="6" fill="{CHAIR_BACK}" rx="3"/>')
        out(f'<rect x="{ch_x - 3:.1f}" y="{ch_y + 3:.1f}" '
            f'width="5" height="{arm_h:.1f}" fill="{CHAIR_ARM}" rx="2"/>')
        out(f'<rect x="{ch_x + ch_w - 2:.1f}" y="{ch_y + 3:.1f}" '
            f'width="5" height="{arm_h:.1f}" fill="{CHAIR_ARM}" rx="2"/>')

    def dim_arrow(x1: float, y1: float, x2: float, y2: float,
                  label: str, horiz: bool = False) -> None:
        """Double white arrow with dimension value."""
        out(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{TEXT_W}" stroke-width="0.8" '
            f'marker-start="url(#aw)" marker-end="url(#aw)"/>')
        if horiz:
            mx = (x1 + x2) / 2
            out(f'<text x="{mx:.1f}" y="{y1 - 4:.1f}" '
                f'text-anchor="middle" font-family="sans-serif" '
                f'font-size="8" fill="{TEXT_DIM}">{label}</text>')
        else:
            my = (y1 + y2) / 2
            out(f'<text x="{x1 + 6:.1f}" y="{my + 4:.1f}" '
                f'font-family="sans-serif" font-size="8" fill="{TEXT_DIM}">'
                f'{label}</text>')

    # === SVG header ===
    out(f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}">')
    out('<defs>'
        '<marker id="aw" viewBox="0 0 10 10" refX="5" refY="5" '
        'markerWidth="4" markerHeight="4" orient="auto-start-reverse">'
        '<path d="M2 1L8 5L2 9" fill="none" stroke="#fff" stroke-width="1.5"/>'
        '</marker>'
        '</defs>')
    out(f'<rect width="{svg_w}" height="{svg_h}" fill="{BG}"/>')

    # compass rose
    out(f'<text x="12" y="24" font-family="sans-serif" font-size="11" '
        f'font-weight="bold" fill="{TEXT_W}">N</text>')
    out(f'<line x1="16" y1="26" x2="16" y2="44" '
        f'stroke="{TEXT_W}" stroke-width="1.5"/>')

    # title + subtitle
    cx_title = x_bl_w + full_w / 2
    out(f'<text x="{cx_title:.0f}" y="22" text-anchor="middle" '
        f'font-family="sans-serif" font-size="12" font-weight="bold" '
        f'fill="{TEXT_W}">{pattern.name} — {pattern.n_desks} desks</text>')
    out(f'<text x="{cx_title:.0f}" y="37" text-anchor="middle" '
        f'font-family="sans-serif" font-size="9" fill="{TEXT_DIM}">'
        f'EO {pattern.total_eo_cm} cm × NS {pattern.total_ns_cm} cm'
        f' · couloir {pattern.central_corridor_cm} cm (ES-06)</text>')

    # === background zones ===

    # Blue N (north candidate), blue inter-row corridor, blue S (south candidate)
    for yy, lbl in [
        (y_blue_n, f"north circ. candidate — {PASSAGE_CM} cm"),
        (y_corr,   f"inter-row corridor ES-06 — {PASSAGE_CM} cm"),
        (y_blue_s, f"south circ. candidate — {PASSAGE_CM} cm"),
    ]:
        draw_zone_candidate(x_bl_w, yy, full_w, cand_px, "")
        out(f'<text x="{x_dsk + eo_w/2:.1f}" y="{yy + cand_px/2 + 4:.1f}" '
            f'text-anchor="middle" font-family="sans-serif" '
            f'font-size="9" fill="{TEXT_BLUE}">{lbl}</text>')

    # Blue W and E lateral zones — full NS height
    h_lateral = y_bottom - y_blue_n
    draw_zone_candidate(x_bl_w, y_blue_n, cand_px, h_lateral, "")
    draw_zone_candidate(x_bl_e, y_blue_n, cand_px, h_lateral, "")

    # === orange zones per block type ===

    def draw_row_oranges(blocks: list[Block], y_desk: float, row_side: str) -> None:
        """Orange zones of a row by block type.

        BLOCK_4/6: horizontal orange band at the outer edge of the row
                   (within the blue candidate zone), spanning the full block width.
        BLOCK_2_FACE: vertical orange bands on EW faces of the block,
                      height = desk height.

        Args:
            blocks: Row blocks (west -> east).
            y_desk: Y of the north edge of the desk zone.
            row_side: 'N' (north row, outer edge = north)
                      or 'S' (south row, outer edge = south).
        """
        x_cur = x_dsk
        for block in blocks:
            bw_px = cm(block.eo_cm)
            if _is_facing_ns(block):
                if row_side == 'N':
                    draw_zone_orange(x_cur, y_desk - deb_px, bw_px, deb_px,
                                     f"{CHAIR_CLEARANCE_CM} cm")
                else:
                    draw_zone_orange(x_cur, y_desk + dh, bw_px, deb_px,
                                     f"{CHAIR_CLEARANCE_CM} cm")
            else:  # BLOCK_2_FACE → orange vertical EW
                draw_zone_orange(x_cur - deb_px, y_desk, deb_px, dh, "")
                draw_zone_orange(x_cur + bw_px,  y_desk, deb_px, dh, "")
            x_cur += bw_px

    draw_row_oranges(pattern.north_row.blocks, y_desk_n, 'N')
    draw_row_oranges(pattern.south_row.blocks, y_desk_s, 'S')

    # === chairs then desks (z-order: chair first, desk on top) ===

    def draw_row_desks(blocks: list[Block], y_desk: float,
                       ws_offset: int, row_side: str) -> None:
        """Draw chairs THEN desks for a row (correct z-order).

        Rendering by block type:
          BLOCK_4/6    -> NS chair (draw_chair_ns), horizontal screen at inner edge.
          BLOCK_2_FACE -> EW chair (draw_chair_ew), vertical screen at user side.

        Args:
            blocks: Row blocks (west -> east).
            y_desk: Y of the north edge of the desk zone.
            ws_offset: Starting index for WS labels.
            row_side: 'N' (north row) or 'S' (south row).
        """
        # (bx, y, chair_type, side_or_orient, ws_idx)
        desks_info: list[tuple[float, float, str, str, int]] = []
        x_cur = x_dsk
        ws_idx = ws_offset

        for block in blocks:
            bw_px = cm(block.eo_cm)
            if _is_facing_ns(block):
                chair_side = row_side  # 'N'→dossier nord ; 'S'→dossier sud
                for i in range(block.n_desks):
                    desks_info.append((x_cur + i * dw, y_desk, 'NS', chair_side, ws_idx))
                    ws_idx += 1
            else:  # BLOCK_2_FACE
                n_pairs = block.n_desks // 2
                for j in range(n_pairs):
                    desks_info.append((x_cur + j * dw * 2,       y_desk, 'EW', 'W', ws_idx))
                    ws_idx += 1
                    desks_info.append((x_cur + j * dw * 2 + dw,  y_desk, 'EW', 'E', ws_idx))
                    ws_idx += 1
            x_cur += bw_px

        # Chairs first (60% under the upcoming desk)
        for bx, by, ch_type, side, _ in desks_info:
            if ch_type == 'NS':
                draw_chair_ns(bx, by, side)
            else:
                draw_chair_ew(bx, by, side)

        # Desks on top (masking the 60%)
        for bx, by, ch_type, side, idx in desks_info:
            if ch_type == 'NS':
                screen_side = 'S' if row_side == 'N' else 'N'
            else:
                screen_side = side
            draw_desk(bx, by, dw, dh, screen_side)
            out(f'<text x="{bx + dw/2:.1f}" y="{by + dh/2 + 4:.1f}" '
                f'text-anchor="middle" font-family="sans-serif" '
                f'font-size="8" fill="#555555">WS{idx:02d}</text>')

    draw_row_desks(pattern.north_row.blocks, y_desk_n, 0, 'N')
    draw_row_desks(pattern.south_row.blocks, y_desk_s,
                   pattern.north_row.n_desks, 'S')

    # === EO dimensions at top ===
    ay = y0 - 4

    dim_arrow(x_bl_w, ay, x_or_w, ay, f"{PASSAGE_CM}", horiz=True)
    dim_arrow(x_or_w, ay, x_dsk,  ay, f"{CHAIR_CLEARANCE_CM}", horiz=True)
    x_cur = x_dsk
    for block in pattern.north_row.blocks:
        bw_px = cm(block.eo_cm)
        dim_arrow(x_cur, ay, x_cur + bw_px, ay, f"{block.eo_cm} cm", horiz=True)
        out(f'<text x="{x_cur + bw_px/2:.1f}" y="{ay + 12:.1f}" '
            f'text-anchor="middle" font-family="sans-serif" '
            f'font-size="8" fill="{TEXT_DIM}">{block.name}</text>')
        x_cur += bw_px
    dim_arrow(x_or_e, ay, x_bl_e, ay, f"{CHAIR_CLEARANCE_CM}", horiz=True)
    dim_arrow(x_bl_e, ay, x_end,  ay, f"{PASSAGE_CM}", horiz=True)

    # === NS dimensions on the right ===
    ax = x_end + 14
    dim_arrow(ax, y_blue_n, ax, y_desk_n, f"{PASSAGE_CM} cm")
    dim_arrow(ax, y_desk_n, ax, y_corr,   f"{DESK_D_CM} cm")
    dim_arrow(ax, y_corr,   ax, y_desk_s, f"{PASSAGE_CM} cm")
    dim_arrow(ax, y_desk_s, ax, y_blue_s, f"{DESK_D_CM} cm")
    dim_arrow(ax, y_blue_s, ax, y_bottom, f"{PASSAGE_CM} cm")

    # === door label + derogatory note ===
    cx_content = x_dsk + eo_w / 2
    out(f'<text x="{cx_content:.1f}" y="{y_bottom + 14:.1f}" '
        f'text-anchor="middle" font-family="sans-serif" '
        f'font-size="9" fill="{TEXT_DIM}">(door -> south)</text>')
    all_blocks = pattern.north_row.blocks + pattern.south_row.blocks
    if any(b.derogatory for b in all_blocks):
        out(f'<text x="{cx_content:.1f}" y="{y_bottom + 28:.1f}" '
            f'text-anchor="middle" font-family="sans-serif" font-size="9" '
            f'fill="#e8a020">⚠ AFNOR ES-10: derogatory use</text>')

    # === vertical legend ===
    ly = y_bottom + 46
    legend_items = [
        (DESK_FILL,   DESK_STR,    "1",      "Desk (80 x 180 cm)"),
        (ORANGE_FILL, ORANGE_FILL, ORANGE_OP, "Non-overlappable — chair clearance 70 cm"),
        (BLUE_FILL,   BLUE_FILL,   BLUE_OP,  "Candidate circulation zone — removable (90 cm)"),
    ]
    for fill, stroke, op, label_text in legend_items:
        out(f'<rect x="30" y="{ly:.0f}" width="12" height="10" '
            f'fill="{fill}" fill-opacity="{op}" '
            f'stroke="{stroke}" stroke-width="0.5"/>')
        out(f'<text x="46" y="{ly + 9:.0f}" '
            f'font-family="sans-serif" font-size="9" fill="{TEXT_DIM}">'
            f'{label_text}</text>')
        ly += 17

    out('</svg>')

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def render_block_svg(block: Block, path: str) -> None:
    """Generate a top-view SVG for an individual canonical block.

    Same visual style as render_pattern_svg (dark background, orange, blue).
    EO geometry: [orange 70] [desks eo_w] [orange 70]
    NS geometry: [blue 90] [desks 180] [blue 90]
    E/W faces being ABSENT for all canonical blocks, no lateral blue zones.

    Args:
        block: Canonical block to draw.
        path: Output SVG file path.
    """
    BG          = "#1e1e1e"
    BLUE_FILL   = "#4a90c4"
    BLUE_OP     = "0.35"
    ORANGE_FILL = "#c8922a"
    ORANGE_OP   = "0.5"
    DESK_FILL   = "#d0d0d0"
    DESK_STR    = "#888888"
    SCREEN_COL  = "#222222"
    CHAIR_COL   = "#8B6914"
    TEXT_BLUE   = "#a0c4e8"
    TEXT_OR     = "#d4a847"
    TEXT_W      = "#ffffff"
    TEXT_DIM    = "#cccccc"

    scale    = 0.5
    margin_t = 60
    annot_r  = 110
    annot_top = 14

    def cm(v: int | float) -> float:
        return v * scale

    deb_px  = cm(CHAIR_CLEARANCE_CM)   # 35 px
    cand_px = cm(PASSAGE_CM)            # 45 px
    dw      = cm(DESK_W_CM)             # 40 px
    dh      = cm(DESK_D_CM)             # 90 px
    eo_w    = cm(block.eo_cm)

    # EO coordinates: orange W | desks | orange E  (no lateral blue = ABSENT)
    x_or_w = 20.0
    x_dsk  = x_or_w + deb_px
    x_or_e = x_dsk  + eo_w
    x_end  = x_or_e + deb_px
    full_w = x_end - x_or_w

    # NS coordinates
    y0       = margin_t + annot_top
    y_pass_n = y0
    y_desk   = y_pass_n + cand_px
    y_pass_s = y_desk   + dh
    y_bottom = y_pass_s + cand_px

    svg_w = int(x_end + annot_r)
    svg_h = int(y_bottom + 90)

    L: list[str] = []

    def out(s: str) -> None:
        L.append(s)

    def draw_zone_candidate(x: float, y: float, w: float, h: float,
                            label: str) -> None:
        out(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{BLUE_FILL}" fill-opacity="{BLUE_OP}" '
            f'stroke="{BLUE_FILL}" stroke-width="0.5" stroke-dasharray="4 2"/>')
        if label:
            out(f'<text x="{x + w/2:.1f}" y="{y + h/2 + 4:.1f}" '
                f'text-anchor="middle" font-family="sans-serif" '
                f'font-size="9" fill="{TEXT_BLUE}">{label}</text>')

    def draw_zone_orange(x: float, y: float, w: float, h: float,
                         label: str = "") -> None:
        out(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{ORANGE_FILL}" fill-opacity="{ORANGE_OP}" '
            f'stroke="{ORANGE_FILL}" stroke-width="0.5"/>')
        if label:
            out(f'<text x="{x + w/2:.1f}" y="{y + h/2 + 4:.1f}" '
                f'text-anchor="middle" font-family="sans-serif" '
                f'font-size="8" fill="{TEXT_OR}">{label}</text>')

    def draw_desk(x: float, y: float, w: float, h: float, screen_side: str) -> None:
        out(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{DESK_FILL}" stroke="{DESK_STR}" stroke-width="1"/>')
        scr_thick = 5.0
        scr_h     = h * 0.55
        scr_y     = y + (h - scr_h) / 2
        scr_x     = x if screen_side == 'W' else x + w - scr_thick
        out(f'<rect x="{scr_x:.1f}" y="{scr_y:.1f}" '
            f'width="{scr_thick:.1f}" height="{scr_h:.1f}" '
            f'fill="{SCREEN_COL}" rx="1"/>')

    def draw_chair(cx: float, cy: float, rx: float, ry: float) -> None:
        out(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" '
            f'rx="{rx:.1f}" ry="{ry:.1f}" fill="{CHAIR_COL}"/>')

    def dim_arrow(x1: float, y1: float, x2: float, y2: float,
                  label: str, horiz: bool = False) -> None:
        out(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{TEXT_W}" stroke-width="0.8" '
            f'marker-start="url(#aw)" marker-end="url(#aw)"/>')
        if horiz:
            mx = (x1 + x2) / 2
            out(f'<text x="{mx:.1f}" y="{y1 - 4:.1f}" '
                f'text-anchor="middle" font-family="sans-serif" '
                f'font-size="9" fill="{TEXT_DIM}">{label}</text>')
        else:
            my = (y1 + y2) / 2
            out(f'<text x="{x1 + 6:.1f}" y="{my + 4:.1f}" '
                f'font-family="sans-serif" font-size="9" fill="{TEXT_DIM}">'
                f'{label}</text>')

    # === SVG header ===
    out(f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}">')
    out('<defs>'
        '<marker id="aw" viewBox="0 0 10 10" refX="5" refY="5" '
        'markerWidth="4" markerHeight="4" orient="auto-start-reverse">'
        '<path d="M2 1L8 5L2 9" fill="none" stroke="#fff" stroke-width="1.5"/>'
        '</marker>'
        '</defs>')
    out(f'<rect width="{svg_w}" height="{svg_h}" fill="{BG}"/>')

    # compass rose
    out(f'<text x="10" y="24" font-family="sans-serif" font-size="11" '
        f'font-weight="bold" fill="{TEXT_W}">N</text>')
    out(f'<line x1="14" y1="26" x2="14" y2="44" '
        f'stroke="{TEXT_W}" stroke-width="1.5"/>')

    # title
    cx_title = x_or_w + full_w / 2
    derog_note = " ⚠ derogatory" if block.derogatory else ""
    out(f'<text x="{cx_title:.0f}" y="22" text-anchor="middle" '
        f'font-family="sans-serif" font-size="13" font-weight="bold" '
        f'fill="{TEXT_W}">{block.name} — {block.n_desks} desks{derog_note}</text>')
    out(f'<text x="{cx_title:.0f}" y="38" text-anchor="middle" '
        f'font-family="sans-serif" font-size="10" fill="{TEXT_DIM}">'
        f'EO {block.eo_cm} cm x NS {block.ns_cm} cm'
        f' · clearance {CHAIR_CLEARANCE_CM} cm · passage {PASSAGE_CM} cm</text>')

    # === background zones ===
    # Blue NS north and south — full width (including orange)
    draw_zone_candidate(x_or_w, y_pass_n, full_w, cand_px,
                        f"north circ. candidate — {PASSAGE_CM} cm")
    draw_zone_candidate(x_or_w, y_pass_s, full_w, cand_px,
                        f"south circ. candidate — {PASSAGE_CM} cm")

    # Orange EO — physical NS height only (y_desk -> y_pass_s)
    draw_zone_orange(x_or_w, y_desk, deb_px, dh,
                     f"clear.\n{CHAIR_CLEARANCE_CM} cm")
    draw_zone_orange(x_or_e, y_desk, deb_px, dh,
                     f"clear.\n{CHAIR_CLEARANCE_CM} cm")

    # === chairs then desks (z-order) ===
    ch_rx = deb_px * 0.5
    ch_ry = dh * 0.20

    # Collect desk positions
    n_pairs = block.n_desks // 2
    desks_info: list[tuple[float, str, int]] = []
    x_cur = x_dsk
    ws_idx = 0
    for _ in range(n_pairs):
        desks_info.append((x_cur,      'W', ws_idx)); ws_idx += 1
        desks_info.append((x_cur + dw, 'E', ws_idx)); ws_idx += 1
        x_cur += dw * 2

    # Chairs
    cy_desk = y_desk + dh / 2
    for bx, side, idx in desks_info:
        if side == 'W':
            if bx == x_dsk:
                draw_chair(x_or_w + ch_rx * 0.6, cy_desk, ch_rx, ch_ry)
            else:
                draw_chair(bx - ch_rx * 0.6, cy_desk, ch_rx * 0.7, ch_ry)
        else:
            if bx + dw >= x_dsk + eo_w:
                draw_chair(x_or_e + ch_rx * 0.4, cy_desk, ch_rx, ch_ry)
            else:
                draw_chair(bx + dw + ch_rx * 0.6, cy_desk, ch_rx * 0.7, ch_ry)

    # Desks
    for bx, side, idx in desks_info:
        draw_desk(bx, y_desk, dw, dh, side)
        lbl = f"{block.name[0]}{idx:02d}"
        out(f'<text x="{bx + dw/2:.1f}" y="{y_desk + dh/2 + 4:.1f}" '
            f'text-anchor="middle" font-family="sans-serif" '
            f'font-size="8" fill="#555">{lbl}</text>')

    # === EO dimensions ===
    ay = y0 - 4
    dim_arrow(x_or_w, ay, x_dsk,  ay, f"{CHAIR_CLEARANCE_CM}", horiz=True)
    dim_arrow(x_dsk,  ay, x_or_e, ay, f"{block.eo_cm} cm", horiz=True)
    out(f'<text x="{x_dsk + eo_w/2:.1f}" y="{ay + 14:.1f}" '
        f'text-anchor="middle" font-family="sans-serif" '
        f'font-size="8" fill="{TEXT_DIM}">{block.name}</text>')
    dim_arrow(x_or_e, ay, x_end,  ay, f"{CHAIR_CLEARANCE_CM}", horiz=True)

    # === NS dimensions on the right ===
    ax = x_end + 14
    dim_arrow(ax, y_pass_n, ax, y_desk,   f"{PASSAGE_CM} cm")
    dim_arrow(ax, y_desk,   ax, y_pass_s, f"{block.ns_cm} cm")
    dim_arrow(ax, y_pass_s, ax, y_bottom, f"{PASSAGE_CM} cm")

    # door label
    out(f'<text x="{cx_title:.1f}" y="{y_bottom + 14:.1f}" '
        f'text-anchor="middle" font-family="sans-serif" '
        f'font-size="9" fill="{TEXT_DIM}">(door -> south)</text>')

    if block.derogatory:
        out(f'<text x="{cx_title:.1f}" y="{y_bottom + 28:.1f}" '
            f'text-anchor="middle" font-family="sans-serif" font-size="9" '
            f'fill="#e8a020">⚠ AFNOR ES-10: derogatory use</text>')

    # === legend ===
    ly = svg_h - 36
    legend_items = [
        (DESK_FILL,   DESK_STR,    "1",       "Desk (80 x 180 cm)"),
        (ORANGE_FILL, ORANGE_FILL, ORANGE_OP, "Non-overlappable — 70 cm"),
        (BLUE_FILL,   BLUE_FILL,   BLUE_OP,   "Candidate zone — removable (90 cm)"),
    ]
    item_w = max(150, (svg_w - 20) // len(legend_items))
    lx = 10.0
    for fill, stroke, op, label_text in legend_items:
        out(f'<rect x="{lx:.0f}" y="{ly:.0f}" width="12" height="10" '
            f'fill="{fill}" fill-opacity="{op}" '
            f'stroke="{stroke}" stroke-width="0.5"/>')
        out(f'<text x="{lx + 16:.0f}" y="{ly + 9:.0f}" '
            f'font-family="sans-serif" font-size="9" fill="{TEXT_DIM}">'
            f'{label_text}</text>')
        lx += item_w

    out('</svg>')

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    import os
    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)

    export_catalogue(
        PATTERNS_ALL,
        DOUBLE_ROW_PATTERNS_ALL,
        os.path.join(out_dir, "catalogue.json"),
    )

    for p in DOUBLE_ROW_PATTERNS_ALL:
        svg_path = os.path.join(out_dir, f"{p.name}.svg")
        render_pattern_svg(p, svg_path)
        print(f"✓ {svg_path}")

    for block in [BLOCK_1, BLOCK_2_SIDE, BLOCK_2_FACE, BLOCK_3_SIDE, BLOCK_4_FACE, BLOCK_6_FACE]:
        svg_path = os.path.join(out_dir, f"{block.name}.svg")
        render_block_svg(block, svg_path)
        print(f"✓ {svg_path}")

    print("Export complete.")

    # ── Pareto verification n=4 ──────────────────────────────────────────────
    all_patterns = PATTERNS_ALL + DOUBLE_ROW_PATTERNS_ALL
    pareto = set(id(p) for p in pareto_front(all_patterns))
    n4 = [p for p in all_patterns if p.n_desks == 4]
    header = f"{'name':<28} {'n':>4} {'sqm':>6} {'circ':>6} {'pareto':>8}"
    print("\n" + header)
    print("-" * len(header))
    for p in n4:
        sqm = compute_sqm_per_desk(p)
        circ = compute_circulation_grade_cm(p)
        in_front = "oui" if id(p) in pareto else "non"
        print(f"{p.name:<28} {p.n_desks:>4} {sqm:>6.2f} {circ:>6} {in_front:>8}")
