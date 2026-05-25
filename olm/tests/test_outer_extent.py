"""D-316: golden tests for outer_extent_cm (internal overhang).

Verifies:
- All non-ORTHO blocks have outer_extent_cm == total_cm (invariance).
- ORTHO_R/L have the correct overhang on their internal face.
- Rotation propagates outer_extent_cm correctly.
- Parité with FaceZone.outer_cm property.
"""
import pytest

from olm.core.pattern_fit import get_face_zones
from olm.core.pattern_generator import (
    DESK_D_CM,
    DESK_W_CM,
    FaceZone,
)
from olm.core.spacing_config import ALL_CONFIGS, build_block_defs

# ── Helpers ───────────────────────────────────────────────────────────

_BLOCK_TYPES = [
    "BLOCK_1", "BLOCK_2_FACE", "BLOCK_2_SIDE", "BLOCK_3_SIDE",
    "BLOCK_4_FACE", "BLOCK_6_FACE",
    "BLOCK_2_ORTHO_R", "BLOCK_2_ORTHO_L",
    "CABINET",
]
_ORIENTATIONS = [0, 90, 180, 270]
_DIRS = ["north", "south", "east", "west"]


def _void_depth() -> int:
    """Void depth for ORTHO blocks (eo_cm - DESK_D_CM at orient 0)."""
    return DESK_W_CM - DESK_D_CM


# ── Tests ─────────────────────────────────────────────────────────────


class TestOuterExtentPresent:
    """outer_extent_cm is set on every face by build_block_defs."""

    @pytest.mark.parametrize("std", list(ALL_CONFIGS.keys()))
    def test_all_faces_have_outer_extent(self, std):
        defs = build_block_defs(ALL_CONFIGS[std])
        for btype in _BLOCK_TYPES:
            for d in _DIRS:
                fd = defs[btype]["faces"][d]
                assert "outer_extent_cm" in fd, (
                    f"{btype}.{d} missing outer_extent_cm ({std})"
                )


class TestNonOrthoInvariance:
    """Non-ORTHO blocks: outer_extent_cm == total_cm (no change)."""

    _NON_ORTHO = [
        "BLOCK_1", "BLOCK_2_FACE", "BLOCK_2_SIDE", "BLOCK_3_SIDE",
        "BLOCK_4_FACE", "BLOCK_6_FACE", "CABINET",
    ]

    @pytest.mark.parametrize("std", list(ALL_CONFIGS.keys()))
    @pytest.mark.parametrize("btype", _NON_ORTHO)
    def test_invariance(self, std, btype):
        defs = build_block_defs(ALL_CONFIGS[std])
        for d in _DIRS:
            fd = defs[btype]["faces"][d]
            total = fd["non_superposable_cm"] + fd["candidate_cm"]
            assert fd["outer_extent_cm"] == total, (
                f"{btype}.{d}: outer_extent_cm={fd['outer_extent_cm']}"
                f" != total={total} ({std})"
            )


class TestOrthoOverhang:
    """ORTHO blocks: internal face has overhang = max(0, total - void)."""

    @pytest.mark.parametrize("std", list(ALL_CONFIGS.keys()))
    def test_ortho_r_east(self, std):
        defs = build_block_defs(ALL_CONFIGS[std])
        fd = defs["BLOCK_2_ORTHO_R"]["faces"]["east"]
        total = fd["non_superposable_cm"] + fd["candidate_cm"]
        expected = max(0, total - _void_depth())
        assert fd["outer_extent_cm"] == expected

    @pytest.mark.parametrize("std", list(ALL_CONFIGS.keys()))
    def test_ortho_l_west(self, std):
        defs = build_block_defs(ALL_CONFIGS[std])
        fd = defs["BLOCK_2_ORTHO_L"]["faces"]["west"]
        total = fd["non_superposable_cm"] + fd["candidate_cm"]
        expected = max(0, total - _void_depth())
        assert fd["outer_extent_cm"] == expected

    @pytest.mark.parametrize("std", list(ALL_CONFIGS.keys()))
    def test_ortho_r_non_internal_unchanged(self, std):
        """North face of ORTHO_R is normal — outer_extent = total."""
        defs = build_block_defs(ALL_CONFIGS[std])
        fd = defs["BLOCK_2_ORTHO_R"]["faces"]["north"]
        total = fd["non_superposable_cm"] + fd["candidate_cm"]
        assert fd["outer_extent_cm"] == total


class TestOuterCmProperty:
    """FaceZone.outer_cm delegates to outer_extent_cm when set."""

    def test_outer_cm_uses_outer_extent(self):
        fz = FaceZone(70, 20, internal=True, outer_extent_cm=10)
        assert fz.outer_cm == 10

    def test_outer_cm_legacy_internal(self):
        """Without outer_extent_cm, internal falls back to 0."""
        fz = FaceZone(70, 20, internal=True)
        assert fz.outer_cm == 0

    def test_outer_cm_legacy_normal(self):
        """Without outer_extent_cm, normal falls back to total_cm."""
        fz = FaceZone(70, 20, internal=False)
        assert fz.outer_cm == 90

    def test_outer_cm_with_extent_normal(self):
        """outer_extent_cm set on a normal face."""
        fz = FaceZone(70, 20, internal=False, outer_extent_cm=90)
        assert fz.outer_cm == 90


class TestRotation:
    """outer_extent_cm survives face rotation via get_face_zones."""

    @pytest.mark.parametrize("std", list(ALL_CONFIGS.keys()))
    @pytest.mark.parametrize("orient", _ORIENTATIONS)
    def test_ortho_r_rotation(self, std, orient):
        """ORTHO_R: the internal overhang rotates with the face."""
        defs = build_block_defs(ALL_CONFIGS[std])
        fc = get_face_zones("BLOCK_2_ORTHO_R", orient, defs)
        # Collect all outer_cm values — their sum must be constant
        # across orientations (one overhang + one chair face).
        extents = {
            "north": fc.north.outer_cm,
            "south": fc.south.outer_cm,
            "east": fc.east.outer_cm,
            "west": fc.west.outer_cm,
        }
        chair_total = (
            defs["BLOCK_2_ORTHO_R"]["faces"]["north"]["non_superposable_cm"]
            + defs["BLOCK_2_ORTHO_R"]["faces"]["north"]["candidate_cm"]
        )
        overhang = defs["BLOCK_2_ORTHO_R"]["faces"]["east"][
            "outer_extent_cm"
        ]
        # Exactly two non-zero extents: chair and overhang
        non_zero = {d: v for d, v in extents.items() if v > 0}
        assert len(non_zero) == 2, (
            f"orient={orient}: expected 2 non-zero, got {non_zero}"
        )
        assert sorted(non_zero.values()) == sorted([chair_total, overhang])

    @pytest.mark.parametrize("std", list(ALL_CONFIGS.keys()))
    @pytest.mark.parametrize("orient", _ORIENTATIONS)
    def test_ortho_l_rotation(self, std, orient):
        """ORTHO_L: mirror of ORTHO_R."""
        defs = build_block_defs(ALL_CONFIGS[std])
        fc = get_face_zones("BLOCK_2_ORTHO_L", orient, defs)
        extents = {
            "north": fc.north.outer_cm,
            "south": fc.south.outer_cm,
            "east": fc.east.outer_cm,
            "west": fc.west.outer_cm,
        }
        chair_total = (
            defs["BLOCK_2_ORTHO_L"]["faces"]["north"]["non_superposable_cm"]
            + defs["BLOCK_2_ORTHO_L"]["faces"]["north"]["candidate_cm"]
        )
        overhang = defs["BLOCK_2_ORTHO_L"]["faces"]["west"][
            "outer_extent_cm"
        ]
        non_zero = {d: v for d, v in extents.items() if v > 0}
        assert len(non_zero) == 2, (
            f"orient={orient}: expected 2 non-zero, got {non_zero}"
        )
        assert sorted(non_zero.values()) == sorted([chair_total, overhang])


class TestGoldenValues:
    """Spot-check specific numeric values with current desk dims."""

    def test_desk_dims_precondition(self):
        """Ensure tests run with expected desk dimensions."""
        assert DESK_W_CM == 160, f"Expected DESK_W=160, got {DESK_W_CM}"
        assert DESK_D_CM == 80, f"Expected DESK_D=80, got {DESK_D_CM}"

    @pytest.mark.parametrize(
        "std_key,slip,expected_overhang",
        [
            ("standard1", 30, 20),   # 70+30-80=20
            ("standard2", 20, 10),   # 70+20-80=10
            ("standard3", 20, 10),   # 70+20-80=10
        ],
    )
    def test_ortho_r_east_golden(self, std_key, slip, expected_overhang):
        if std_key not in ALL_CONFIGS:
            pytest.skip(f"{std_key} not configured")
        defs = build_block_defs(ALL_CONFIGS[std_key])
        fd = defs["BLOCK_2_ORTHO_R"]["faces"]["east"]
        assert fd["outer_extent_cm"] == expected_overhang
        # Confirm slip matches expectation
        assert fd["candidate_cm"] == slip

    @pytest.mark.parametrize(
        "std_key,slip,expected_overhang",
        [
            ("standard1", 30, 20),
            ("standard2", 20, 10),
            ("standard3", 20, 10),
        ],
    )
    def test_ortho_l_west_golden(self, std_key, slip, expected_overhang):
        if std_key not in ALL_CONFIGS:
            pytest.skip(f"{std_key} not configured")
        defs = build_block_defs(ALL_CONFIGS[std_key])
        fd = defs["BLOCK_2_ORTHO_L"]["faces"]["west"]
        assert fd["outer_extent_cm"] == expected_overhang
        assert fd["candidate_cm"] == slip
