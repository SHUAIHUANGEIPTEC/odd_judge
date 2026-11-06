"""Tests for config loading and switches."""

import json
from pathlib import Path

import pytest

from odd_judge.config.loader import load_profile, load_profile_with_extends, load_switches, parse_profile
from odd_judge.config.schema import validate_profile_dict
from odd_judge.core.errors import ConfigError

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"


def test_load_byd_profile():
    pid, mode, rules = load_profile(PROFILES / "byd_tjp.json")
    assert pid == "byd_tjp"
    assert mode.value == "restrictive"
    assert len(rules) > 30


def test_load_skeleton():
    pid, mode, rules = load_profile(PROFILES / "odc_skeleton.json")
    assert pid == "odc_skeleton"
    assert mode.value == "default"


def test_profile_validation_errors():
    bad = {"profile_id": "x", "elements": [{"element_id": "a", "requirement": "bad_req"}]}
    errors = validate_profile_dict(bad)
    assert any("invalid requirement" in e for e in errors)


def test_profile_validation_ok():
    with open(PROFILES / "byd_tjp.json", encoding="utf-8") as f:
        data = json.load(f)
    assert validate_profile_dict(data) == []


def test_override_merge():
    pid, mode, rules = load_profile_with_extends(
        PROFILES / "byd_tjp.json",
        override_paths=[PROFILES / "overrides" / "example_enterprise.json"],
    )
    ids = {r.element_id for r in rules}
    assert "ODC.ENT.1.road_temperature" in ids
    assert "ODC.1.2.1.curve_radius" in ids


def test_load_switches():
    sw = load_switches(ROOT / "switches" / "default_switches.json")
    assert sw["global_enabled"] is True
    assert sw["boundary_warnings_enabled"] is True


def test_parse_profile_from_dict():
    data = {
        "profile_id": "mini",
        "definition_mode": "permissive",
        "elements": [
            {
                "element_id": "x1",
                "requirement": "allowed",
                "rule_type": "numeric_range",
                "observation_key": "a.b",
                "op": ">=",
                "threshold": 1.0,
            }
        ],
    }
    pid, mode, rules = parse_profile(data)
    assert pid == "mini"
    assert len(rules) == 1


# ---------------------------------------------------------------------------
# Schema: configuration errors must be caught at validate time
# ---------------------------------------------------------------------------


def _profile(elements):
    return {"profile_id": "probe", "elements": elements}


def _num(**overrides):
    el = {
        "element_id": "n1",
        "requirement": "allowed",
        "rule_type": "numeric_range",
        "observation_key": "a.b",
        "op": ">=",
        "threshold": 1.0,
    }
    el.update(overrides)
    return el


def test_schema_rejects_condition_ops_on_numeric_range():
    el = _num(op="in")
    errors = validate_profile_dict(_profile([el]))
    assert any("invalid numeric op" in e for e in errors)


def test_schema_requires_threshold_for_equality_ops():
    el = _num(op="==")
    del el["threshold"]
    errors = validate_profile_dict(_profile([el]))
    assert any("requires threshold" in e for e in errors)


def test_schema_requires_valid_range_for_between():
    errors = validate_profile_dict(_profile([_num(op="between", range=[9.0, -9.0])]))
    assert any("lo < hi" in e for e in errors)
    errors = validate_profile_dict(_profile([_num(op="between", range=None)]))
    assert any("requires range" in e for e in errors)


def test_schema_rejects_negative_boundary_margin():
    errors = validate_profile_dict(
        _profile([_num(boundary_margin={"mode": "absolute", "value": -1.0})])
    )
    assert any("boundary_margin.value" in e for e in errors)


def test_schema_rejects_bad_undefined_as():
    errors = validate_profile_dict(_profile([_num(undefined_as="maybe")]))
    assert any("invalid undefined_as" in e for e in errors)


def test_schema_rejects_non_bool_expect():
    el = {
        "element_id": "b1",
        "requirement": "allowed",
        "rule_type": "qualitative_bool",
        "observation_key": "a.b",
        "expect": "yes",
    }
    errors = validate_profile_dict(_profile([el]))
    assert any("expect must be a boolean" in e for e in errors)


def test_schema_enum_allowed_requires_allowed_values():
    el = {
        "element_id": "e1",
        "requirement": "allowed",
        "rule_type": "qualitative_enum",
        "observation_key": "a.b",
        "forbidden_values": ["x"],
    }
    errors = validate_profile_dict(_profile([el]))
    assert any("needs allowed_values" in e for e in errors)


def test_schema_enum_not_allowed_must_not_use_allowed_values():
    el = {
        "element_id": "e2",
        "requirement": "not_allowed",
        "rule_type": "qualitative_enum",
        "observation_key": "a.b",
        "allowed_values": ["x"],
        "forbidden_values": ["y"],
    }
    errors = validate_profile_dict(_profile([el]))
    assert any("must not define" in e for e in errors)


def test_schema_rejects_overlapping_enum_sets():
    el = {
        "element_id": "e3",
        "requirement": "allowed",
        "rule_type": "qualitative_enum",
        "observation_key": "a.b",
        "allowed_values": ["x", "y"],
        "boundary_values": ["y"],
    }
    errors = validate_profile_dict(_profile([el]))
    assert any("overlap" in e for e in errors)


def test_schema_confidence_requires_key_and_bool_rule():
    # threshold without key
    errors = validate_profile_dict(
        _profile([
            {
                "element_id": "c1",
                "requirement": "allowed",
                "rule_type": "qualitative_bool",
                "observation_key": "a.b",
                "confidence_threshold": 0.7,
            }
        ])
    )
    assert any("requires confidence_observation_key" in e for e in errors)

    # confidence fields on a numeric rule → dead config, rejected
    errors = validate_profile_dict(
        _profile([
            _num(confidence_threshold=0.7, confidence_observation_key="a.c")
        ])
    )
    assert any("only valid on qualitative_bool" in e for e in errors)

    # threshold out of range
    errors = validate_profile_dict(
        _profile([
            {
                "element_id": "c2",
                "requirement": "allowed",
                "rule_type": "qualitative_bool",
                "observation_key": "a.b",
                "confidence_threshold": 1.5,
                "confidence_observation_key": "a.c",
            }
        ])
    )
    assert any("confidence_threshold" in e and "[0, 1]" in e for e in errors)


def test_schema_rejects_bad_applies_when_op():
    el = _num(applies_when={"key": "s.type", "op": "like", "value": "x"})
    errors = validate_profile_dict(_profile([el]))
    assert any("invalid condition op" in e for e in errors)


def test_schema_rejects_in_without_list_value():
    el = _num(applies_when={"key": "s.type", "op": "in", "value": "expressway"})
    errors = validate_profile_dict(_profile([el]))
    assert any("requires value to be a list" in e for e in errors)


def test_schema_accepts_valid_confidence_rule():
    el = {
        "element_id": "c3",
        "requirement": "allowed",
        "rule_type": "qualitative_bool",
        "observation_key": "a.b",
        "expect": True,
        "confidence_threshold": 0.7,
        "confidence_band": 0.1,
        "confidence_observation_key": "a.c",
    }
    assert validate_profile_dict(_profile([el])) == []


# ---------------------------------------------------------------------------
# merge_profiles priority
# ---------------------------------------------------------------------------


def test_merge_profiles_base_priority_true_keeps_base():
    from odd_judge.config.loader import merge_profiles

    base = {"profile_id": "b", "elements": [{"element_id": "E", "v": 1}]}
    other = {"profile_id": "o", "elements": [{"element_id": "E", "v": 2}]}
    merged = merge_profiles(base, other, base_priority=True)
    assert merged["elements"][0]["v"] == 1


def test_merge_profiles_base_priority_false_keeps_other():
    from odd_judge.config.loader import merge_profiles

    base = {"profile_id": "b", "elements": [{"element_id": "E", "v": 1}]}
    other = {"profile_id": "o", "elements": [{"element_id": "E", "v": 2}]}
    merged = merge_profiles(base, other, base_priority=False)
    assert merged["elements"][0]["v"] == 2


def test_loader_parses_confidence_observation_key():
    data = {
        "profile_id": "mini",
        "elements": [
            {
                "element_id": "x1",
                "requirement": "allowed",
                "rule_type": "qualitative_bool",
                "observation_key": "a.b",
                "expect": True,
                "confidence_threshold": 0.7,
                "confidence_band": 0.1,
                "confidence_observation_key": "a.conf",
            }
        ],
    }
    _, _, rules = parse_profile(data)
    assert rules[0].confidence_observation_key == "a.conf"
    assert rules[0].confidence_threshold == 0.7
    assert rules[0].confidence_band == 0.1


def _mini_profile(warning_codes_by_id: dict) -> dict:
    """Build a minimal valid profile with one element per given warning_codes."""
    return {
        "profile_id": "mini",
        "elements": [
            {
                "element_id": eid,
                "requirement": "allowed",
                "rule_type": "qualitative_bool",
                "observation_key": "a.b",
                "expect": True,
                "warning_codes": wc,
            }
            for eid, wc in warning_codes_by_id.items()
        ],
    }


def test_warning_codes_invalid_key():
    data = _mini_profile({"x1": {"warn": "X-001"}})
    errors = validate_profile_dict(data)
    assert any("invalid warning_codes key" in e for e in errors)


def test_warning_codes_invalid_format():
    data = _mini_profile({"x1": {"outside": "lower case code"}})
    errors = validate_profile_dict(data)
    assert any("invalid warning code format" in e for e in errors)


def test_warning_codes_duplicate_across_elements():
    data = _mini_profile(
        {
            "x1": {"outside": "X-001", "boundary": "X-NEAR"},
            "x2": {"boundary": "X-NEAR"},
        }
    )
    errors = validate_profile_dict(data)
    assert any("duplicate warning code" in e and "X-NEAR" in e for e in errors)


def test_warning_codes_valid():
    data = _mini_profile(
        {
            "x1": {"outside": "X-001", "boundary": "X-NEAR"},
            "x2": {"outside": "X-002"},
        }
    )
    assert validate_profile_dict(data) == []


def test_warning_codes_duplicate_via_registry_element():
    """Plugin-registered elements must not collide with profile codes."""
    from odd_judge.config import registry

    data = _mini_profile({"x1": {"outside": "X-001"}})
    registry.register_element(
        {
            "element_id": "plug.1",
            "requirement": "allowed",
            "rule_type": "qualitative_bool",
            "observation_key": "a.b",
            "expect": True,
            "warning_codes": {"boundary": "X-001"},
        }
    )
    try:
        with pytest.raises(ConfigError, match="duplicate warning code"):
            parse_profile(data)
    finally:
        registry.clear()
