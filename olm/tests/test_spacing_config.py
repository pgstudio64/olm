"""Tests for spacing_config.py — generic (no business standard names)."""
from olm.core.spacing_config import SpacingConfig, ALL_CONFIGS, get_default, get_default_name


def test_all_configs_loaded():
    """At least one standard is loaded from project/config.json."""
    assert len(ALL_CONFIGS) >= 1


def test_get_default():
    """get_default returns a SpacingConfig."""
    cfg = get_default()
    assert cfg is not None
    assert isinstance(cfg, SpacingConfig)


def test_get_default_name():
    """get_default_name returns a non-empty string."""
    name = get_default_name()
    assert name is not None
    assert name in ALL_CONFIGS


def test_spacing_fields():
    """Every loaded config has all required fields."""
    for name, cfg in ALL_CONFIGS.items():
        assert cfg.name == name
        assert cfg.chair_clearance_cm > 0
        assert cfg.passage_cm > 0
        assert cfg.door_exclusion_depth_cm > 0
        assert cfg.main_corridor_cm > 0


def test_from_dict_roundtrip():
    """from_dict(to_dict()) is identity."""
    cfg = get_default()
    d = cfg.to_dict()
    restored = SpacingConfig.from_dict(d)
    assert restored == cfg


def test_from_dict_ignores_extra_keys():
    """from_dict ignores keys not in the dataclass."""
    d = get_default().to_dict()
    d["unknown_field"] = 999
    restored = SpacingConfig.from_dict(d)
    assert not hasattr(restored, "unknown_field")
