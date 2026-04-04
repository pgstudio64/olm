"""Tests pour spacing_config.py."""
from olm.core.spacing_config import SpacingConfig, AFNOR_ADVICE, GROUP, SITE, ALL_CONFIGS


def test_afnor_primitives():
    assert AFNOR_ADVICE.chair_clearance_cm == 70
    assert AFNOR_ADVICE.passage_cm == 90
    assert AFNOR_ADVICE.door_exclusion_depth_cm == 180
    assert AFNOR_ADVICE.main_corridor_cm == 140
    assert AFNOR_ADVICE.front_access_cm == 60
    assert AFNOR_ADVICE.desk_to_wall_cm == 20
    assert AFNOR_ADVICE.max_island_size == 4


def test_afnor_derived():
    assert AFNOR_ADVICE.passage_behind_one_row_cm == 160
    assert AFNOR_ADVICE.passage_between_back_to_back_cm == 230


def test_group_door_exclusion():
    assert GROUP.door_exclusion_depth_cm == 180


def test_site_door_exclusion():
    assert SITE.door_exclusion_depth_cm == 120


def test_all_configs_keys():
    assert set(ALL_CONFIGS.keys()) == {"AFNOR_ADVICE", "GROUP", "SITE"}


def test_frozen():
    try:
        AFNOR_ADVICE.passage_cm = 100
        assert False, "Should raise FrozenInstanceError"
    except AttributeError:
        pass
