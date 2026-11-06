"""Tests for qualitative and quantitative rule evaluation."""

from odd_judge.core.evaluate import evaluate_rule
from odd_judge.core.types import (
    BoundaryMargin,
    DefinitionMode,
    EvalContext,
    Observation,
    Requirement,
    Rule,
    ScenarioState,
    ThresholdSpec,
)


def make_obs(**fields):
    return Observation(fields=fields)


def test_numeric_allowed_inside():
    rule = Rule(
        element_id="t.speed",
        path=("speed",),
        requirement=Requirement.ALLOWED,
        rule_type="numeric_range",
        observation_key="v.speed",
        spec=ThresholdSpec(op="between", range=(0, 80), margin=BoundaryMargin("absolute", 3)),
        warning_codes={"boundary": "B", "outside": "O"},
    )
    obs = make_obs(v={"speed": 50.0})
    r = evaluate_rule(rule, obs, EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.INSIDE


def test_numeric_allowed_boundary():
    rule = Rule(
        element_id="t.speed",
        path=("speed",),
        requirement=Requirement.ALLOWED,
        rule_type="numeric_range",
        observation_key="v.speed",
        spec=ThresholdSpec(op="between", range=(0, 80), margin=BoundaryMargin("absolute", 3)),
        warning_codes={"boundary": "B", "outside": "O"},
    )
    obs = make_obs(v={"speed": 78.5})
    r = evaluate_rule(rule, obs, EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.BOUNDARY
    assert r.reason_code == "B"


def test_numeric_allowed_outside():
    rule = Rule(
        element_id="t.speed",
        path=("speed",),
        requirement=Requirement.ALLOWED,
        rule_type="numeric_range",
        observation_key="v.speed",
        spec=ThresholdSpec(op="between", range=(0, 80), margin=BoundaryMargin("absolute", 3)),
        warning_codes={"boundary": "B", "outside": "O"},
    )
    obs = make_obs(v={"speed": 95.0})
    r = evaluate_rule(rule, obs, EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE
    assert r.reason_code == "O"


def test_not_allowed_presence_is_outside():
    """requirement=not_allowed: forbidden condition PRESENT → OUTSIDE."""
    rule = Rule(
        element_id="t.intersection",
        path=("junction",),
        requirement=Requirement.NOT_ALLOWED,
        rule_type="qualitative_bool",
        observation_key="s.has_intersection",
        expect=True,
        warning_codes={"outside": "X"},
    )
    # forbidden condition present
    obs = make_obs(s={"has_intersection": True})
    r = evaluate_rule(rule, obs, EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE


def test_not_allowed_absent_is_inside():
    rule = Rule(
        element_id="t.intersection",
        path=("junction",),
        requirement=Requirement.NOT_ALLOWED,
        rule_type="qualitative_bool",
        observation_key="s.has_intersection",
        expect=True,
        warning_codes={"outside": "X"},
    )
    obs = make_obs(s={"has_intersection": False})
    r = evaluate_rule(rule, obs, EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.INSIDE


def test_enum_allowed():
    rule = Rule(
        element_id="t.road",
        path=("road",),
        requirement=Requirement.ALLOWED,
        rule_type="qualitative_enum",
        observation_key="s.type",
        allowed_values=("expressway_main", "highway_main"),
        forbidden_values=("rural_road",),
        warning_codes={"outside": "R"},
    )
    ctx = EvalContext(DefinitionMode.RESTRICTIVE)
    assert evaluate_rule(rule, make_obs(s={"type": "expressway_main"}), ctx).state == ScenarioState.INSIDE
    assert evaluate_rule(rule, make_obs(s={"type": "rural_road"}), ctx).state == ScenarioState.OUTSIDE


def test_enum_boundary_values():
    rule = Rule(
        element_id="t.snow",
        path=("snow",),
        requirement=Requirement.ALLOWED,
        rule_type="qualitative_enum",
        observation_key="e.snow",
        allowed_values=("none", "light"),
        boundary_values=("moderate",),
        forbidden_values=("heavy",),
        warning_codes={"boundary": "SB", "outside": "SO"},
    )
    ctx = EvalContext(DefinitionMode.RESTRICTIVE)
    r = evaluate_rule(rule, make_obs(e={"snow": "moderate"}), ctx)
    assert r.state == ScenarioState.BOUNDARY
    assert r.reason_code == "SB"


def test_bool_allowed():
    rule = Rule(
        element_id="t.belt",
        path=("belt",),
        requirement=Requirement.ALLOWED,
        rule_type="qualitative_bool",
        observation_key="v.seatbelt",
        expect=True,
        warning_codes={"outside": "BE"},
    )
    ctx = EvalContext(DefinitionMode.RESTRICTIVE)
    assert evaluate_rule(rule, make_obs(v={"seatbelt": True}), ctx).state == ScenarioState.INSIDE
    assert evaluate_rule(rule, make_obs(v={"seatbelt": False}), ctx).state == ScenarioState.OUTSIDE


def test_undefined_requirement_skips():
    rule = Rule(
        element_id="t.foo",
        path=("foo",),
        requirement=Requirement.UNDEFINED,
        rule_type="qualitative_bool",
        observation_key="x.y",
        expect=True,
    )
    r = evaluate_rule(rule, make_obs(x={"y": True}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.UNDEFINED


def test_missing_obs_restrictive():
    rule = Rule(
        element_id="t.missing",
        path=("m",),
        requirement=Requirement.ALLOWED,
        rule_type="qualitative_bool",
        observation_key="x.nope",
        expect=True,
    )
    r = evaluate_rule(rule, make_obs(x={}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE
    assert r.reason_code == "UNDEFINED-STRICT"


def test_missing_obs_permissive():
    rule = Rule(
        element_id="t.missing",
        path=("m",),
        requirement=Requirement.ALLOWED,
        rule_type="qualitative_bool",
        observation_key="x.nope",
        expect=True,
    )
    r = evaluate_rule(rule, make_obs(x={}), EvalContext(DefinitionMode.PERMISSIVE))
    assert r.state == ScenarioState.INSIDE


def test_missing_obs_default():
    rule = Rule(
        element_id="t.missing",
        path=("m",),
        requirement=Requirement.ALLOWED,
        rule_type="qualitative_bool",
        observation_key="x.nope",
        expect=True,
    )
    r = evaluate_rule(rule, make_obs(x={}), EvalContext(DefinitionMode.DEFAULT))
    assert r.state == ScenarioState.UNDEFINED


# ---------------------------------------------------------------------------
# Invalid observation data → same fallback as a missing value
# ---------------------------------------------------------------------------


def _numeric_rule(observation_key="v.x"):
    return Rule(
        element_id="t.num",
        path=("num",),
        requirement=Requirement.ALLOWED,
        rule_type="numeric_range",
        observation_key=observation_key,
        spec=ThresholdSpec(op="between", range=(0.0, 80.0), margin=BoundaryMargin("absolute", 3.0)),
        warning_codes={"outside": "N"},
    )


def test_numeric_nan_falls_back_by_definition_mode():
    rule = _numeric_rule()
    strict = evaluate_rule(rule, make_obs(v={"x": float("nan")}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert strict.state == ScenarioState.OUTSIDE
    assert strict.reason_code == "UNDEFINED-STRICT"
    loose = evaluate_rule(rule, make_obs(v={"x": float("nan")}), EvalContext(DefinitionMode.PERMISSIVE))
    assert loose.state == ScenarioState.INSIDE


def test_numeric_infinity_is_invalid_not_inside():
    rule = _numeric_rule()
    r = evaluate_rule(rule, make_obs(v={"x": float("inf")}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE
    assert r.reason_code == "UNDEFINED-STRICT"


def test_numeric_non_numeric_string_is_missing():
    rule = _numeric_rule()
    r = evaluate_rule(rule, make_obs(v={"x": "N/A"}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE
    assert r.reason_code == "UNDEFINED-STRICT"


# ---------------------------------------------------------------------------
# Unknown enum value → treated as missing, consistently for both config shapes
# ---------------------------------------------------------------------------


def _enum_rule(requirement, allowed=None, forbidden=None):
    return Rule(
        element_id="t.enum",
        path=("enum",),
        requirement=requirement,
        rule_type="qualitative_enum",
        observation_key="s.type",
        allowed_values=allowed,
        forbidden_values=forbidden,
        warning_codes={"outside": "E"},
    )


def test_unknown_enum_is_missing_for_allowed_config():
    rule = _enum_rule(Requirement.ALLOWED, allowed=("a",), forbidden=("b",))
    r = evaluate_rule(rule, make_obs(s={"type": "zzz"}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE
    assert r.reason_code == "UNDEFINED-STRICT"
    r2 = evaluate_rule(rule, make_obs(s={"type": "zzz"}), EvalContext(DefinitionMode.PERMISSIVE))
    assert r2.state == ScenarioState.INSIDE


def test_forbidden_only_config_anything_not_forbidden_is_compliant():
    """Forbidden-list semantics: a value outside the list is compliant, not
    unknown — the two ambiguous config shapes are rejected by schema instead."""
    rule = _enum_rule(Requirement.NOT_ALLOWED, forbidden=("b",))
    r = evaluate_rule(rule, make_obs(s={"type": "zzz"}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.INSIDE
    # ...while the allowed-list shape treats unlisted values as missing
    rule2 = _enum_rule(Requirement.ALLOWED, allowed=("a",), forbidden=("b",))
    r2 = evaluate_rule(rule2, make_obs(s={"type": "zzz"}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r2.state == ScenarioState.OUTSIDE
    assert r2.reason_code == "UNDEFINED-STRICT"


def test_known_forbidden_value_still_flips_for_not_allowed():
    rule = _enum_rule(Requirement.NOT_ALLOWED, forbidden=("b",))
    r = evaluate_rule(rule, make_obs(s={"type": "b"}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE
    assert r.reason_code == "E"  # configured warning code, not the missing fallback
    r2 = evaluate_rule(rule, make_obs(s={"type": "ok"}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r2.state == ScenarioState.INSIDE


# ---------------------------------------------------------------------------
# Bool rules: strict type check + live confidence handling
# ---------------------------------------------------------------------------


def test_bool_string_value_is_missing_not_truthy():
    rule = Rule(
        element_id="t.flag",
        path=("flag",),
        requirement=Requirement.ALLOWED,
        rule_type="qualitative_bool",
        observation_key="a.flag",
        expect=False,
    )
    # "false" must not be truth-evaluated as True → falls back as missing
    r = evaluate_rule(rule, make_obs(a={"flag": "false"}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE
    assert r.reason_code == "UNDEFINED-STRICT"
    # numeric 0/1 are accepted as booleans
    assert evaluate_rule(rule, make_obs(a={"flag": 0}), EvalContext(DefinitionMode.RESTRICTIVE)).state == ScenarioState.INSIDE
    assert evaluate_rule(rule, make_obs(a={"flag": 1}), EvalContext(DefinitionMode.RESTRICTIVE)).state == ScenarioState.OUTSIDE


def _confidence_rule():
    return Rule(
        element_id="t.conf",
        path=("conf",),
        requirement=Requirement.ALLOWED,
        rule_type="qualitative_bool",
        observation_key="a.flag",
        expect=True,
        confidence_threshold=0.7,
        confidence_band=0.1,
        confidence_observation_key="a.score",
        warning_codes={"boundary": "CB", "outside": "CO"},
    )


def test_bool_confidence_match_is_inside_without_consulting_confidence():
    r = evaluate_rule(_confidence_rule(), make_obs(a={"flag": True, "score": 0.2}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.INSIDE


def test_bool_confidence_reliable_mismatch_is_outside():
    r = evaluate_rule(_confidence_rule(), make_obs(a={"flag": False, "score": 0.9}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE
    assert r.confidence == 0.9
    assert r.reason_code == "CO"


def test_bool_confidence_critical_band_is_boundary():
    r = evaluate_rule(_confidence_rule(), make_obs(a={"flag": False, "score": 0.65}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.BOUNDARY
    assert r.reason_code == "CB"
    assert r.confidence == 0.65


def test_bool_confidence_below_band_falls_back_as_missing():
    r = evaluate_rule(_confidence_rule(), make_obs(a={"flag": False, "score": 0.5}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE
    assert r.reason_code == "UNDEFINED-STRICT"


def test_bool_confidence_missing_key_falls_back_as_missing():
    r = evaluate_rule(_confidence_rule(), make_obs(a={"flag": False}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE
    assert r.reason_code == "UNDEFINED-STRICT"


def test_bool_without_confidence_config_is_binary():
    rule = Rule(
        element_id="t.plain",
        path=("p",),
        requirement=Requirement.ALLOWED,
        rule_type="qualitative_bool",
        observation_key="a.flag",
        expect=True,
    )
    r = evaluate_rule(rule, make_obs(a={"flag": False}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.OUTSIDE
    assert r.reason_code is None


# ---------------------------------------------------------------------------
# undefined_as element-level override
# ---------------------------------------------------------------------------


def test_undefined_as_undefined_returns_undefined():
    rule = Rule(
        element_id="t.u",
        path=("u",),
        requirement=Requirement.ALLOWED,
        rule_type="qualitative_bool",
        observation_key="a.gone",
        expect=True,
        undefined_as=Requirement.UNDEFINED,
    )
    r = evaluate_rule(rule, make_obs(a={}), EvalContext(DefinitionMode.PERMISSIVE))
    assert r.state == ScenarioState.UNDEFINED
    assert r.reason_code == "UNDEFINED-AS-UNDEFINED"


def test_undefined_as_allowed_overrides_restrictive():
    rule = Rule(
        element_id="t.u2",
        path=("u",),
        requirement=Requirement.ALLOWED,
        rule_type="qualitative_bool",
        observation_key="a.gone",
        expect=True,
        undefined_as=Requirement.ALLOWED,
    )
    r = evaluate_rule(rule, make_obs(a={}), EvalContext(DefinitionMode.RESTRICTIVE))
    assert r.state == ScenarioState.INSIDE
