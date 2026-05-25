"""Tests for D-257 signed-margin model (distance_rules.js logic).

Since the JS functions cannot be called directly from Python, these
tests replicate the analyzeGap algorithm in pure Python to validate
the margin model against the specification (CONSTRAINTS.md §2.6/2.7).
"""


# ── Python replica of analyzeGap (mirrors distance_rules.js exactly) ──

def _classify_gap_side(face):
    """Classify one side: 'chair', 'wall', or 'other'."""
    if face is None:
        return "wall"
    if face.get("internal"):
        return "other"
    if (face.get("non_superposable_cm") or 0) > 0:
        return "chair"
    return "other"


def _gap_side_emprise(side_type, spacing):
    """Reserved cm for one side."""
    if side_type == "chair":
        return spacing["chair_clearance_cm"] + spacing["slip_in_margin_cm"]
    return 0


def analyze_gap(raw_dist_cm, face_a, face_b, spacing, opts=None):
    """Python replica of analyzeGap from distance_rules.js."""
    if not spacing:
        return {"color": "#c8a050", "marge": raw_dist_cm}
    side_a = _classify_gap_side(face_a)
    side_b = _classify_gap_side(face_b)
    emprise_a = _gap_side_emprise(side_a, spacing)
    emprise_b = _gap_side_emprise(side_b, spacing)
    passage = opts.get("passage", False) if opts else False
    walking = spacing["walking_margin_cm"] if passage else 0
    requis = emprise_a + emprise_b + walking
    marge = raw_dist_cm - requis
    tol = spacing.get("distance_tolerance_cm", 5)
    if marge > tol:
        color = "#58c080"     # green
    elif marge >= -tol:
        color = "#c8a050"     # amber
    else:
        color = "#d88080"     # red
    return {"color": color, "marge": marge}


# ── Test data ──

SPACING_STD1 = {
    "chair_clearance_cm": 70,
    "walking_margin_cm": 90,
    "slip_in_margin_cm": 30,
    "distance_tolerance_cm": 5,
}

CHAIR_FACE = {"non_superposable_cm": 70}
BACK_FACE = {"non_superposable_cm": 0}
WALL = None


# ── Tests ──

class TestAnalyzeGapPassageTrue:
    """Gaps with passage=True (walking margin added)."""

    def test_two_chairs_face_to_face_green(self):
        """290 cm between two chair faces, passage: plenty of room."""
        # requis = 100 + 100 + 90 = 290, marge = 0 => amber (±tol)
        # Try 300 => marge = +10 > tol=5 => green
        gap = analyze_gap(300, CHAIR_FACE, CHAIR_FACE, SPACING_STD1,
                          {"passage": True})
        assert gap["color"] == "#58c080"
        assert gap["marge"] == 10

    def test_two_chairs_face_to_face_amber(self):
        """290 cm exactly => marge=0 => amber."""
        gap = analyze_gap(290, CHAIR_FACE, CHAIR_FACE, SPACING_STD1,
                          {"passage": True})
        assert gap["color"] == "#c8a050"
        assert gap["marge"] == 0

    def test_two_chairs_face_to_face_red(self):
        """270 cm => marge = -20 < -5 => red."""
        gap = analyze_gap(270, CHAIR_FACE, CHAIR_FACE, SPACING_STD1,
                          {"passage": True})
        assert gap["color"] == "#d88080"
        assert gap["marge"] == -20

    def test_chair_vs_wall_passage(self):
        """Chair facing wall with passage: requis = 100 + 0 + 90 = 190."""
        gap = analyze_gap(200, CHAIR_FACE, WALL, SPACING_STD1,
                          {"passage": True})
        assert gap["marge"] == 10
        assert gap["color"] == "#58c080"


class TestAnalyzeGapPassageFalse:
    """Gaps without passage (walking NOT added)."""

    def test_chair_vs_wall_no_passage(self):
        """Chair facing wall, no passage: requis = 100 + 0 = 100.
        Option B (AFNOR fig 7)."""
        gap = analyze_gap(130, CHAIR_FACE, WALL, SPACING_STD1,
                          {"passage": False})
        assert gap["marge"] == 30
        assert gap["color"] == "#58c080"  # green (+30 > +5)

    def test_chair_vs_wall_tight_no_passage(self):
        """Chair facing wall at exactly emprise: marge=0 => amber."""
        gap = analyze_gap(100, CHAIR_FACE, WALL, SPACING_STD1,
                          {"passage": False})
        assert gap["marge"] == 0
        assert gap["color"] == "#c8a050"

    def test_back_vs_wall_no_passage(self):
        """Back face vs wall: emprise = 0, no walking. Full dist = margin."""
        gap = analyze_gap(40, BACK_FACE, WALL, SPACING_STD1,
                          {"passage": False})
        assert gap["marge"] == 40
        assert gap["color"] == "#58c080"

    def test_two_backs_no_passage(self):
        """Two back faces, no passage: emprise = 0, marge = rawDist."""
        gap = analyze_gap(5, BACK_FACE, BACK_FACE, SPACING_STD1,
                          {"passage": False})
        assert gap["marge"] == 5
        assert gap["color"] == "#c8a050"  # amber (marge=5 = tol)


class TestAnalyzeGapEdgeCases:
    """Edge cases: negative margin, no spacing, tolerance boundary."""

    def test_very_negative_margin(self):
        """Emprises overlap massively => very negative, red."""
        gap = analyze_gap(50, CHAIR_FACE, CHAIR_FACE, SPACING_STD1,
                          {"passage": True})
        # requis = 100 + 100 + 90 = 290, marge = 50 - 290 = -240
        assert gap["marge"] == -240
        assert gap["color"] == "#d88080"

    def test_no_spacing_fallback(self):
        """No spacing object => amber, marge = rawDist."""
        gap = analyze_gap(120, CHAIR_FACE, WALL, None)
        assert gap["marge"] == 120
        assert gap["color"] == "#c8a050"

    def test_tolerance_boundary_positive(self):
        """marge exactly +tol (5) => amber (not > tol)."""
        # Chair vs wall no passage: requis = 100, raw = 105 => marge = 5
        gap = analyze_gap(105, CHAIR_FACE, WALL, SPACING_STD1,
                          {"passage": False})
        assert gap["marge"] == 5
        assert gap["color"] == "#c8a050"

    def test_tolerance_boundary_negative(self):
        """marge exactly -tol (-5) => amber (>= -tol)."""
        gap = analyze_gap(95, CHAIR_FACE, WALL, SPACING_STD1,
                          {"passage": False})
        assert gap["marge"] == -5
        assert gap["color"] == "#c8a050"

    def test_internal_face_zero_emprise(self):
        """Internal face (D-241) treated as emprise=0."""
        internal = {"non_superposable_cm": 70, "internal": True}
        gap = analyze_gap(100, internal, WALL, SPACING_STD1,
                          {"passage": False})
        assert gap["marge"] == 100  # emprise = 0 (internal)

    def test_custom_tolerance(self):
        """Custom distance_tolerance_cm respected."""
        sp = {**SPACING_STD1, "distance_tolerance_cm": 10}
        gap = analyze_gap(108, CHAIR_FACE, WALL, sp, {"passage": False})
        # marge = 108 - 100 = 8, tol = 10 => 8 < 10 => amber
        assert gap["marge"] == 8
        assert gap["color"] == "#c8a050"
