"""Tests for JSON v3 plan validation (P2.7, D-188)."""
import copy

import pytest

from olm.core.json_v3_validator import load_schema, validate_plan

# -- Fixtures ---------------------------------------------------------------

_MINIMAL_ROOM = {
    "surface": "14.28 m2",
    "seed_x": 100,
    "seed_y": 200,
}

_FULL_ROOM = {
    "surface": "14.28 m2",
    "seed_x": 100,
    "seed_y": 200,
    "bbox_px": [80, 150, 200, 300],
    "canonical_top_face": "north",
    "corridor_face_abs": "south",
    "doors": [
        {
            "face": "south",
            "offset_px": 15,
            "width_px": 93,
            "hinge_side": "left",
            "opens_inward": True,
            "seed_x": 120,
            "seed_y": 290,
        },
    ],
    "openings": [
        {
            "face": "west",
            "offset_px": 57,
            "width_px": 114,
            "origin": "auto",
        },
    ],
    "windows": [
        {
            "face": "north",
            "offset_px": 0,
            "width_px": 76,
            "origin": "auto",
        },
    ],
    "exclusion_zones": [
        {"x_cm": 0, "y_cm": 0, "width_cm": 50, "depth_cm": 50},
    ],
    "walls_user_edited": False,
}

_MINIMAL_PLAN = {
    "file": "test.png",
    "page_width_px": 1920,
    "page_height_px": 1080,
    "rooms": {"101": copy.deepcopy(_MINIMAL_ROOM)},
}

_FULL_PLAN = {
    "file": "test.png",
    "page_width_px": 1920,
    "page_height_px": 1080,
    "source_mode": "preprocessed",
    "building_id": "B01",
    "floor_id": "R+1",
    "north_angle_deg": 0,
    "first_scan_done": True,
    "drawing_scale_text": "1 : 350",
    "drawing_scale_measured": 2.96,
    "render_dpi": 300,
    "olm_state": {"version": 1},
    "rooms": {
        "237": copy.deepcopy(_FULL_ROOM),
        "918": copy.deepcopy(_MINIMAL_ROOM),
    },
}


# -- Tests -------------------------------------------------------------------


class TestSchemaLoad:
    """Verify the schema can be loaded and cached."""

    def test_load_schema_returns_dict(self):
        schema = load_schema()
        assert isinstance(schema, dict)
        assert schema.get("$schema") == "http://json-schema.org/draft-07/schema#"

    def test_load_schema_is_cached(self):
        s1 = load_schema()
        s2 = load_schema()
        assert s1 is s2


class TestValidPlan:
    """Plans that must pass validation."""

    def test_full_plan(self):
        validate_plan(copy.deepcopy(_FULL_PLAN))

    def test_minimal_plan(self):
        validate_plan(copy.deepcopy(_MINIMAL_PLAN))

    def test_olm_state_free_form_in_room(self):
        """rooms.X.olm_state = { libre: 'anything' } must pass."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["olm_state"] = {"libre": "anything"}
        validate_plan(plan)

    def test_door_input_seed_only(self):
        """A door with only seed_x/seed_y (input format) must pass."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["doors"] = [
            {"seed_x": 100, "seed_y": 200},
        ]
        validate_plan(plan)

    def test_drawing_scale_measured_as_string(self):
        """drawing_scale_measured can be a string like '2.96 cm/px'."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["drawing_scale_measured"] = "2.9633 cm/px"
        validate_plan(plan)

    def test_exclusion_zone_with_origin(self):
        """exclusion_zone with origin='manual' must pass (D-192)."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["exclusion_zones"] = [
            {"x_cm": 0, "y_cm": 0, "width_cm": 50, "depth_cm": 50, "origin": "manual"},
        ]
        validate_plan(plan)

    def test_transparent_zone_with_origin(self):
        """transparent_zone with origin='auto' must pass — reuses exclusion_zone schema (D-192)."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["transparent_zones"] = [
            {"x_cm": 10, "y_cm": 10, "width_cm": 30, "depth_cm": 20, "origin": "auto"},
        ]
        validate_plan(plan)

    def test_exclusion_zone_negative_xy(self):
        """exclusion_zone with negative x_cm/y_cm must pass (D-205)."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["exclusion_zones"] = [
            {"x_cm": -10, "y_cm": -5, "width_cm": 50, "depth_cm": 30},
        ]
        validate_plan(plan)

    def test_transparent_zone_negative_xy(self):
        """transparent_zone with negative x_cm/y_cm must pass (D-205)."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["transparent_zones"] = [
            {"x_cm": -20, "y_cm": -10, "width_cm": 40, "depth_cm": 20},
        ]
        validate_plan(plan)


class TestInvalidPlan:
    """Plans that must fail validation with a clear message."""

    def test_missing_rooms(self):
        plan = {"file": "test.png", "page_width_px": 1920, "page_height_px": 1080}
        with pytest.raises(ValueError, match="rooms"):
            validate_plan(plan)

    def test_empty_rooms(self):
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"] = {}
        with pytest.raises(ValueError):
            validate_plan(plan)

    def test_bbox_px_wrong_length(self):
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["bbox_px"] = [80, 150, 200]
        with pytest.raises(ValueError, match="bbox_px"):
            validate_plan(plan)

    def test_window_invalid_face(self):
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["windows"] = [
            {"face": "haut", "offset_px": 0, "width_px": 50},
        ]
        with pytest.raises(ValueError, match="face"):
            validate_plan(plan)

    def test_missing_file(self):
        plan = copy.deepcopy(_MINIMAL_PLAN)
        del plan["file"]
        with pytest.raises(ValueError, match="file"):
            validate_plan(plan)

    def test_missing_seed_x(self):
        plan = copy.deepcopy(_MINIMAL_PLAN)
        del plan["rooms"]["101"]["seed_x"]
        with pytest.raises(ValueError, match="seed_x"):
            validate_plan(plan)

    def test_door_without_seed_or_face(self):
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["doors"] = [
            {"offset_px": 10, "width_px": 50},
        ]
        with pytest.raises(ValueError):
            validate_plan(plan)


# -- D-204 door_seeds tests -------------------------------------------------


class TestDoorSeedsSchema:
    """D-204: door_seeds[] as separate immutable input."""

    def test_door_seeds_valid(self):
        """door_seeds with seed_x/seed_y passes validation."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["door_seeds"] = [
            {"seed_x": 100, "seed_y": 200},
            {"seed_x": 300, "seed_y": 400},
        ]
        validate_plan(plan)

    def test_door_seeds_with_typed_doors(self):
        """door_seeds + typed doors coexist."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["door_seeds"] = [
            {"seed_x": 100, "seed_y": 200},
        ]
        plan["rooms"]["101"]["doors"] = [
            {"face": "south", "offset_px": 10, "width_px": 27},
        ]
        validate_plan(plan)

    def test_door_seeds_missing_seed_y(self):
        """door_seed without seed_y fails."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["door_seeds"] = [
            {"seed_x": 100},
        ]
        with pytest.raises(ValueError, match="seed_y"):
            validate_plan(plan)

    def test_door_seeds_extra_field(self):
        """door_seed with extra field fails (additionalProperties=false)."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["door_seeds"] = [
            {"seed_x": 100, "seed_y": 200, "face": "south"},
        ]
        with pytest.raises(ValueError):
            validate_plan(plan)

    def test_typed_door_no_face_fails(self):
        """D-204: a door without face is invalid in new schema."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["doors"] = [
            {"offset_px": 10, "width_px": 50},
        ]
        with pytest.raises(ValueError):
            validate_plan(plan)

    def test_legacy_mixed_doors_still_valid(self):
        """Legacy mixed doors (seed-only + typed) still pass schema."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["doors"] = [
            {"seed_x": 100, "seed_y": 200},
            {"face": "south", "offset_px": 10, "width_px": 27},
        ]
        validate_plan(plan)


# -- D-245 saved_layout tests -----------------------------------------------


class TestSavedLayout:
    """D-245: saved_layout optional field in room."""

    def test_saved_layout_valid(self):
        """Room with saved_layout object passes validation."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["saved_layout"] = {
            "pattern_name": "WS02_NS",
            "standard": "comfortable",
            "n_desks": 4,
            "saved": True,
        }
        validate_plan(plan)

    def test_saved_layout_absent_ok(self):
        """Room without saved_layout passes (retrocompat)."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        assert "saved_layout" not in plan["rooms"]["101"]
        validate_plan(plan)

    def test_saved_layout_non_object_fails(self):
        """saved_layout must be an object, not a string."""
        plan = copy.deepcopy(_MINIMAL_PLAN)
        plan["rooms"]["101"]["saved_layout"] = "invalid"
        with pytest.raises(ValueError, match="saved_layout"):
            validate_plan(plan)
