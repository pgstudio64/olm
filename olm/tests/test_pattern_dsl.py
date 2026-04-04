"""Tests pour pattern_dsl.py."""
import pytest
from olm.core.pattern_dsl import parse_dsl, to_dsl, parse_catalogue_dsl, DSLError


class TestParseDSL:

    def test_single_block(self):
        result = parse_dsl("P_B4: BLOC_4_FACE")
        assert result["name"] == "P_B4"
        assert len(result["rows"]) == 1
        assert len(result["rows"][0]["blocks"]) == 1
        assert result["rows"][0]["blocks"][0]["type"] == "BLOC_4_FACE"
        assert result["rows"][0]["blocks"][0]["orientation"] == 0
        assert result["row_gaps_cm"] == []

    def test_single_row_with_gap(self):
        result = parse_dsl("P_B4_B2F: BLOC_4_FACE, 180, BLOC_2_FACE")
        assert result["name"] == "P_B4_B2F"
        row = result["rows"][0]
        assert len(row["blocks"]) == 2
        assert row["blocks"][0]["type"] == "BLOC_4_FACE"
        assert "gap_cm" not in row["blocks"][0]
        assert row["blocks"][1]["type"] == "BLOC_2_FACE"
        assert row["blocks"][1]["gap_cm"] == 180

    def test_double_row(self):
        result = parse_dsl("P_B4_B4: BLOC_4_FACE; 180; BLOC_4_FACE")
        assert len(result["rows"]) == 2
        assert result["row_gaps_cm"] == [180]

    def test_double_row_mixed(self):
        result = parse_dsl(
            "P_B4B2F_B4: BLOC_4_FACE, 180, BLOC_2_FACE; 180; BLOC_4_FACE"
        )
        assert len(result["rows"]) == 2
        assert len(result["rows"][0]["blocks"]) == 2
        assert len(result["rows"][1]["blocks"]) == 1
        assert result["row_gaps_cm"] == [180]

    def test_orientation(self):
        result = parse_dsl("P_R90: BLOC_4_FACE@90")
        assert result["rows"][0]["blocks"][0]["orientation"] == 90

    def test_complex(self):
        result = parse_dsl(
            "P_COMPLEX: BLOC_4_FACE@90, 200, BLOC_2_FACE@90; 180; BLOC_4_FACE@90, 200, BLOC_1@270"
        )
        assert len(result["rows"]) == 2
        assert result["rows"][0]["blocks"][1]["gap_cm"] == 200
        assert result["rows"][1]["blocks"][1]["orientation"] == 270

    def test_all_block_types(self):
        for bt in ["BLOC_1", "BLOC_2_FACE", "BLOC_2_COTE", "BLOC_3_COTE",
                    "BLOC_4_FACE", "BLOC_6_FACE"]:
            result = parse_dsl(f"TEST: {bt}")
            assert result["rows"][0]["blocks"][0]["type"] == bt

    def test_spaces_ignored(self):
        result = parse_dsl("  P_X :  BLOC_4_FACE ,  180 ,  BLOC_2_FACE  ")
        assert result["name"] == "P_X"
        assert len(result["rows"][0]["blocks"]) == 2

    def test_error_empty(self):
        with pytest.raises(DSLError):
            parse_dsl("")

    def test_error_no_colon(self):
        with pytest.raises(DSLError):
            parse_dsl("P_B4 BLOC_4_FACE")

    def test_error_unknown_block(self):
        with pytest.raises(DSLError, match="inconnu"):
            parse_dsl("P_X: BLOC_99")

    def test_error_bad_orientation(self):
        with pytest.raises(DSLError, match="Orientation"):
            parse_dsl("P_X: BLOC_4_FACE@45")

    def test_error_comment(self):
        with pytest.raises(DSLError):
            parse_dsl("-- commentaire")

    def test_offset_sud(self):
        result = parse_dsl("P_OFF: BLOC_4_FACE, 180, BLOC_2_FACE SUD20")
        b1 = result["rows"][0]["blocks"][1]
        assert b1["offset_ns_cm"] == 20

    def test_offset_nord(self):
        result = parse_dsl("P_OFF: BLOC_4_FACE NORD30")
        b0 = result["rows"][0]["blocks"][0]
        assert b0["offset_ns_cm"] == -30

    def test_offset_with_orientation(self):
        result = parse_dsl("P_OFF: BLOC_4_FACE@90 SUD10")
        b0 = result["rows"][0]["blocks"][0]
        assert b0["orientation"] == 90
        assert b0["offset_ns_cm"] == 10

    def test_no_offset_means_absent(self):
        result = parse_dsl("P_X: BLOC_4_FACE")
        b0 = result["rows"][0]["blocks"][0]
        assert "offset_ns_cm" not in b0

    def test_error_bad_offset(self):
        with pytest.raises(DSLError, match="invalide"):
            parse_dsl("P_X: BLOC_4_FACE EST20")


class TestToDSL:

    def test_single_block(self):
        pattern = {
            "name": "P_B4",
            "rows": [{"blocks": [{"type": "BLOC_4_FACE", "orientation": 0}]}],
            "row_gaps_cm": [],
        }
        assert to_dsl(pattern) == "P_B4: BLOC_4_FACE"

    def test_single_row_with_gap(self):
        pattern = {
            "name": "P_B4_B2F",
            "rows": [{"blocks": [
                {"type": "BLOC_4_FACE", "orientation": 0},
                {"type": "BLOC_2_FACE", "orientation": 0, "gap_cm": 180},
            ]}],
            "row_gaps_cm": [],
        }
        assert to_dsl(pattern) == "P_B4_B2F: BLOC_4_FACE, 180, BLOC_2_FACE"

    def test_double_row(self):
        pattern = {
            "name": "P_B4_B4",
            "rows": [
                {"blocks": [{"type": "BLOC_4_FACE", "orientation": 0}]},
                {"blocks": [{"type": "BLOC_4_FACE", "orientation": 0}]},
            ],
            "row_gaps_cm": [180],
        }
        assert to_dsl(pattern) == "P_B4_B4: BLOC_4_FACE; 180; BLOC_4_FACE"

    def test_orientation_included(self):
        pattern = {
            "name": "P_R90",
            "rows": [{"blocks": [{"type": "BLOC_4_FACE", "orientation": 90}]}],
            "row_gaps_cm": [],
        }
        assert to_dsl(pattern) == "P_R90: BLOC_4_FACE@90"

    def test_orientation_0_omitted(self):
        pattern = {
            "name": "P_X",
            "rows": [{"blocks": [{"type": "BLOC_1", "orientation": 0}]}],
            "row_gaps_cm": [],
        }
        assert "P_X: BLOC_1" == to_dsl(pattern)
        assert "@" not in to_dsl(pattern)

    def test_offset_sud(self):
        pattern = {
            "name": "P_OFF",
            "rows": [{"blocks": [
                {"type": "BLOC_4_FACE", "orientation": 0},
                {"type": "BLOC_2_FACE", "orientation": 0, "gap_cm": 180, "offset_ns_cm": 20},
            ]}],
            "row_gaps_cm": [],
        }
        assert to_dsl(pattern) == "P_OFF: BLOC_4_FACE, 180, BLOC_2_FACE SUD20"

    def test_offset_nord(self):
        pattern = {
            "name": "P_OFF",
            "rows": [{"blocks": [
                {"type": "BLOC_4_FACE", "orientation": 90, "offset_ns_cm": -30},
            ]}],
            "row_gaps_cm": [],
        }
        assert to_dsl(pattern) == "P_OFF: BLOC_4_FACE@90 NORD30"

    def test_offset_zero_omitted(self):
        pattern = {
            "name": "P_X",
            "rows": [{"blocks": [
                {"type": "BLOC_4_FACE", "orientation": 0, "offset_ns_cm": 0},
            ]}],
            "row_gaps_cm": [],
        }
        dsl = to_dsl(pattern)
        assert "SUD" not in dsl
        assert "NORD" not in dsl


class TestRoundTrip:

    def test_single_block(self):
        dsl = "P_B4: BLOC_4_FACE"
        assert to_dsl(parse_dsl(dsl)) == dsl

    def test_single_row_gap(self):
        dsl = "P_B4_B2F: BLOC_4_FACE, 180, BLOC_2_FACE"
        assert to_dsl(parse_dsl(dsl)) == dsl

    def test_double_row(self):
        dsl = "P_B4_B4: BLOC_4_FACE; 180; BLOC_4_FACE"
        assert to_dsl(parse_dsl(dsl)) == dsl

    def test_complex(self):
        dsl = "P_MIX: BLOC_4_FACE, 180, BLOC_2_FACE; 180; BLOC_4_FACE"
        assert to_dsl(parse_dsl(dsl)) == dsl

    def test_with_orientation(self):
        dsl = "P_R: BLOC_4_FACE@90, 200, BLOC_1@270"
        assert to_dsl(parse_dsl(dsl)) == dsl

    def test_with_offset_sud(self):
        dsl = "P_OFF: BLOC_4_FACE, 180, BLOC_2_FACE SUD20"
        assert to_dsl(parse_dsl(dsl)) == dsl

    def test_with_offset_nord(self):
        dsl = "P_OFF: BLOC_4_FACE@90 NORD30"
        assert to_dsl(parse_dsl(dsl)) == dsl

    def test_full_features(self):
        """Round-trip avec toutes les caracteristiques : gaps, orientations, offsets, multi-rangees."""
        dsl = "P_FULL: BLOC_4_FACE@90 NORD10, 200, BLOC_2_FACE SUD20; 180; BLOC_6_FACE, 150, BLOC_1@270"
        assert to_dsl(parse_dsl(dsl)) == dsl


class TestCatalogueParse:

    def test_multi_line(self):
        text = """
-- Patterns simples
P_B4: BLOC_4_FACE
P_B4_B2F: BLOC_4_FACE, 180, BLOC_2_FACE

-- Pattern double
P_B4_B4: BLOC_4_FACE; 180; BLOC_4_FACE
"""
        result = parse_catalogue_dsl(text)
        assert len(result) == 3
        assert result[0]["name"] == "P_B4"
        assert result[2]["name"] == "P_B4_B4"
