"""Rule evaluation: quantitative (numeric) and qualitative (enum/bool) rules."""

from __future__ import annotations

import math
from typing import Any

from .margin import classify_numeric
from .types import (
    VALUE_MISSING,
    BoundaryMargin,
    CompositeCondition,
    Condition,
    DefinitionMode,
    EvalContext,
    Observation,
    Requirement,
    Rule,
    RuleResult,
    ScenarioState,
    ThresholdSpec,
    ValueMissing,
)


def resolve_condition(cond: CompositeCondition, obs: Observation) -> bool:
    """Evaluate a composite condition tree against an observation."""
    if cond.kind == "leaf":
        if cond.leaf is None:
            return True
        return _eval_leaf(cond.leaf, obs)
    if cond.kind == "all_of":
        return all(resolve_condition(c, obs) for c in cond.children)
    if cond.kind == "any_of":
        return any(resolve_condition(c, obs) for c in cond.children)
    if cond.kind == "not":
        if not cond.children:
            return True
        return not resolve_condition(cond.children[0], obs)
    raise ValueError(f"Unknown composite kind: {cond.kind}")


def _eval_leaf(leaf: Condition, obs: Observation) -> bool:
    val = obs.get(leaf.key)
    if isinstance(val, ValueMissing):
        return False
    op = leaf.op
    expected = leaf.value
    if op == "==":
        return val == expected
    if op == "!=":
        return val != expected
    if op == "in":
        return val in expected
    if op == "not_in":
        return val not in expected
    if op in (">=", "<=", ">", "<"):
        try:
            fval = float(val)
            fexp = float(expected)
        except (TypeError, ValueError):
            return False
        if op == ">=":
            return fval >= fexp
        if op == "<=":
            return fval <= fexp
        if op == ">":
            return fval > fexp
        return fval < fexp
    if op == "bool":
        return bool(val) == bool(expected)
    raise ValueError(f"Unknown condition op: {op}")


def _handle_missing(rule: Rule, ctx: EvalContext) -> RuleResult:
    """Handle missing observation or undefined requirement based on definition mode."""
    if rule.requirement == Requirement.UNDEFINED:
        return RuleResult(
            element_id=rule.element_id,
            state=ScenarioState.UNDEFINED,
            observed=None,
            message_zh=f"{rule.label_zh or rule.element_id}: 元素要求为不定义",
            label_zh=rule.label_zh,
            requirement=rule.requirement.value,
            rule_type=rule.rule_type,
            tags=rule.tags,
            reason_code="UNDEFINED-REQ",
        )

    mode = ctx.definition_mode
    if rule.undefined_as is not None:
        # Element-level override for missing observation
        if rule.undefined_as == Requirement.UNDEFINED:
            return RuleResult(
                element_id=rule.element_id,
                state=ScenarioState.UNDEFINED,
                observed=None,
                message_zh=f"{rule.label_zh or rule.element_id}: 观测缺失按不定义处理",
                label_zh=rule.label_zh,
                requirement=rule.requirement.value,
                rule_type=rule.rule_type,
                tags=rule.tags,
                reason_code="UNDEFINED-AS-UNDEFINED",
            )
        if rule.undefined_as == Requirement.ALLOWED:
            return RuleResult(
                element_id=rule.element_id,
                state=ScenarioState.INSIDE,
                observed=None,
                message_zh=f"{rule.label_zh or rule.element_id}: 观测缺失按允许处理",
                label_zh=rule.label_zh,
                requirement=rule.requirement.value,
                rule_type=rule.rule_type,
                tags=rule.tags,
            )
        if rule.undefined_as == Requirement.NOT_ALLOWED:
            return RuleResult(
                element_id=rule.element_id,
                state=ScenarioState.OUTSIDE,
                observed=None,
                message_zh=f"{rule.label_zh or rule.element_id}: 观测缺失按不允许处理",
                label_zh=rule.label_zh,
                requirement=rule.requirement.value,
                rule_type=rule.rule_type,
                tags=rule.tags,
                reason_code="UNDEFINED-AS-NOT-ALLOWED",
            )

    if ctx.missing_policy is not None:
        value, source = ctx.missing_policy.resolve(rule)
        if value == "allowed":
            return RuleResult(
                element_id=rule.element_id,
                state=ScenarioState.INSIDE,
                observed=None,
                message_zh=f"{rule.label_zh or rule.element_id}: 观测缺失(missing_policy {source}→域内)",
                label_zh=rule.label_zh,
                requirement=rule.requirement.value,
                rule_type=rule.rule_type,
                tags=rule.tags,
                reason_code="MISSING-POLICY-ALLOWED",
                policy_source=source,
            )
        if value == "not_allowed":
            return RuleResult(
                element_id=rule.element_id,
                state=ScenarioState.OUTSIDE,
                observed=None,
                message_zh=f"{rule.label_zh or rule.element_id}: 观测缺失(missing_policy {source}→域外)",
                label_zh=rule.label_zh,
                requirement=rule.requirement.value,
                rule_type=rule.rule_type,
                tags=rule.tags,
                reason_code="MISSING-POLICY-NOT-ALLOWED",
                policy_source=source,
            )
        if value == "undefined":
            return RuleResult(
                element_id=rule.element_id,
                state=ScenarioState.UNDEFINED,
                observed=None,
                message_zh=f"{rule.label_zh or rule.element_id}: 观测缺失(missing_policy {source}→不定义)",
                label_zh=rule.label_zh,
                requirement=rule.requirement.value,
                rule_type=rule.rule_type,
                tags=rule.tags,
                reason_code="MISSING-POLICY-UNDEFINED",
                policy_source=source,
            )

    if mode == DefinitionMode.PERMISSIVE:
        return RuleResult(
            element_id=rule.element_id,
            state=ScenarioState.INSIDE,
            observed=None,
            message_zh=f"{rule.label_zh or rule.element_id}: 观测缺失(permissive→域内)",
            label_zh=rule.label_zh,
            requirement=rule.requirement.value,
            rule_type=rule.rule_type,
            tags=rule.tags,
            reason_code="UNDEFINED-PERMISSIVE",
        )
    if mode == DefinitionMode.RESTRICTIVE:
        return RuleResult(
            element_id=rule.element_id,
            state=ScenarioState.OUTSIDE,
            observed=None,
            message_zh=f"{rule.label_zh or rule.element_id}: 观测缺失(restrictive→域外)",
            label_zh=rule.label_zh,
            requirement=rule.requirement.value,
            rule_type=rule.rule_type,
            tags=rule.tags,
            reason_code="UNDEFINED-STRICT",
        )
    # DEFAULT
    return RuleResult(
        element_id=rule.element_id,
        state=ScenarioState.UNDEFINED,
        observed=None,
        message_zh=f"{rule.label_zh or rule.element_id}: 观测缺失(default→不定义)",
        label_zh=rule.label_zh,
        requirement=rule.requirement.value,
        rule_type=rule.rule_type,
        tags=rule.tags,
        reason_code="UNDEFINED-DEFAULT",
    )


def _apply_requirement(raw_state: ScenarioState, requirement: Requirement) -> ScenarioState:
    """Map raw observation state through element requirement semantics.

    allowed:     INSIDE→INSIDE, BOUNDARY→BOUNDARY, OUTSIDE→OUTSIDE
    not_allowed: forbidden condition PRESENT means:
                 raw OUTSIDE (condition absent) → INSIDE
                 raw BOUNDARY (near forbidden) → BOUNDARY
                 raw INSIDE  (condition present) → OUTSIDE
    """
    if requirement == Requirement.ALLOWED:
        return raw_state
    if requirement == Requirement.NOT_ALLOWED:
        if raw_state == ScenarioState.INSIDE:
            return ScenarioState.OUTSIDE
        if raw_state == ScenarioState.OUTSIDE:
            return ScenarioState.INSIDE
        return ScenarioState.BOUNDARY
    return ScenarioState.UNDEFINED


def _warning_code(rule: Rule, state: ScenarioState) -> str | None:
    if state == ScenarioState.OUTSIDE:
        return rule.warning_codes.get("outside")
    if state == ScenarioState.BOUNDARY:
        return rule.warning_codes.get("boundary") or rule.warning_codes.get("outside")
    return None


def evaluate_numeric(rule: Rule, obs: Observation, ctx: EvalContext) -> RuleResult:
    val = obs.get(rule.observation_key)
    if isinstance(val, ValueMissing) or val is VALUE_MISSING:
        return _handle_missing(rule, ctx)

    if rule.spec is None:
        raise ValueError(f"Rule {rule.element_id} has rule_type numeric_range but no spec")

    try:
        fval = float(val)
    except (TypeError, ValueError):
        return _handle_missing(rule, ctx)
    if not math.isfinite(fval):
        # NaN / ±inf are invalid sensor data, same fallback as a missing value
        return _handle_missing(rule, ctx)

    raw_state, remaining, band = classify_numeric(fval, rule.spec)
    state = _apply_requirement(raw_state, rule.requirement)

    msg = f"{rule.label_zh or rule.element_id}: 观测={fval}"
    if state == ScenarioState.BOUNDARY:
        msg += f"，临近边界(剩余裕度={remaining:.3f})"
    elif state == ScenarioState.OUTSIDE:
        msg += "，已越界"

    return RuleResult(
        element_id=rule.element_id,
        state=state,
        observed=fval,
        remaining_margin=remaining,
        margin_band=band,
        reason_code=_warning_code(rule, state),
        message_zh=msg,
        label_zh=rule.label_zh,
        requirement=rule.requirement.value,
        rule_type=rule.rule_type,
        tags=rule.tags,
    )


def evaluate_enum(rule: Rule, obs: Observation, ctx: EvalContext) -> RuleResult:
    val = obs.get(rule.observation_key)
    if isinstance(val, ValueMissing) or val is VALUE_MISSING:
        return _handle_missing(rule, ctx)

    allowed = set(rule.allowed_values or ())
    forbidden = set(rule.forbidden_values or ())
    boundary = set(rule.boundary_values or ())

    # Determine raw state relative to "allowed" semantics first
    if allowed:
        if val in allowed:
            raw = ScenarioState.INSIDE
        elif val in boundary:
            raw = ScenarioState.BOUNDARY
        elif val in forbidden:
            raw = ScenarioState.OUTSIDE
        else:
            # unknown enum value: treat as missing observation so the outcome
            # follows definition_mode uniformly for every requirement
            return _handle_missing(rule, ctx)
    elif forbidden:
        # Reached only when allowed_values is empty; schema restricts such
        # rules to requirement=not_allowed, so raw here lives in the
        # "forbidden present" frame and _apply_requirement flips it.
        if val in forbidden:
            raw = ScenarioState.INSIDE  # forbidden present → flips to OUTSIDE
        elif val in boundary:
            raw = ScenarioState.BOUNDARY
        else:
            raw = ScenarioState.OUTSIDE  # forbidden absent → flips to INSIDE
    else:
        raw = ScenarioState.INSIDE

    state = _apply_requirement(raw, rule.requirement)

    msg = f"{rule.label_zh or rule.element_id}: 观测={val!r}"
    if state == ScenarioState.BOUNDARY:
        msg += "，临近边界"
    elif state == ScenarioState.OUTSIDE:
        msg += "，越界"

    return RuleResult(
        element_id=rule.element_id,
        state=state,
        observed=val,
        remaining_margin=None,
        margin_band=None,
        reason_code=_warning_code(rule, state),
        message_zh=msg,
        label_zh=rule.label_zh,
        requirement=rule.requirement.value,
        rule_type=rule.rule_type,
        tags=rule.tags,
    )


def evaluate_bool(rule: Rule, obs: Observation, ctx: EvalContext) -> RuleResult:
    val = obs.get(rule.observation_key)
    if isinstance(val, ValueMissing) or val is VALUE_MISSING:
        return _handle_missing(rule, ctx)

    # Only real booleans (and exact 0/1) are valid for a bool rule; strings
    # like "false" must not be truth-evaluated into a wrong verdict.
    if isinstance(val, bool):
        actual = val
    elif isinstance(val, (int, float)) and val in (0, 1):
        actual = bool(val)
    else:
        return _handle_missing(rule, ctx)

    expect = rule.expect if rule.expect is not None else True
    confidence = 1.0
    raw: ScenarioState

    if actual == expect:
        raw = ScenarioState.INSIDE
    elif rule.confidence_threshold is None:
        raw = ScenarioState.OUTSIDE
    else:
        # Confidence is consulted only on a mismatch; schema guarantees the
        # key when a threshold is configured.
        ckey = rule.confidence_observation_key
        cval = obs.get(ckey) if ckey else VALUE_MISSING
        if isinstance(cval, ValueMissing) or cval is VALUE_MISSING:
            return _handle_missing(rule, ctx)
        try:
            confidence = float(cval)
        except (TypeError, ValueError):
            return _handle_missing(rule, ctx)
        if not math.isfinite(confidence):
            return _handle_missing(rule, ctx)

        thr = float(rule.confidence_threshold)
        band = float(rule.confidence_band or 0.0)
        if confidence >= thr:
            raw = ScenarioState.OUTSIDE  # reliable mismatch
        elif confidence >= thr - band:
            raw = ScenarioState.BOUNDARY  # inside the critical band
        else:
            # Too unreliable to assert anything → same fallback as missing
            return _handle_missing(rule, ctx)

    state = _apply_requirement(raw, rule.requirement)

    msg = f"{rule.label_zh or rule.element_id}: 观测={val!r}, 期望={expect}"
    if state == ScenarioState.OUTSIDE:
        msg += "，越界"
    elif state == ScenarioState.BOUNDARY:
        msg += "，临近边界"

    return RuleResult(
        element_id=rule.element_id,
        state=state,
        observed=val,
        remaining_margin=None,
        margin_band=None,
        reason_code=_warning_code(rule, state),
        confidence=confidence,
        message_zh=msg,
        label_zh=rule.label_zh,
        requirement=rule.requirement.value,
        rule_type=rule.rule_type,
        tags=rule.tags,
    )


def evaluate_rule(rule: Rule, obs: Observation, ctx: EvalContext) -> RuleResult:
    """Main entry: evaluate one rule against an observation."""
    # Conditional applicability
    if rule.applies_when is not None:
        if not resolve_condition(rule.applies_when, obs):
            return RuleResult(
                element_id=rule.element_id,
                state=ScenarioState.SKIPPED,
                observed=None,
                message_zh=f"{rule.label_zh or rule.element_id}: 条件不适用，跳过",
                label_zh=rule.label_zh,
                requirement=rule.requirement.value,
                rule_type=rule.rule_type,
                tags=rule.tags,
                reason_code="CONDITIONAL-SKIP",
            )

    if rule.requirement == Requirement.UNDEFINED:
        return RuleResult(
            element_id=rule.element_id,
            state=ScenarioState.UNDEFINED,
            observed=None,
            message_zh=f"{rule.label_zh or rule.element_id}: 元素要求为不定义",
            label_zh=rule.label_zh,
            requirement=rule.requirement.value,
            rule_type=rule.rule_type,
            tags=rule.tags,
            reason_code="UNDEFINED-REQ",
        )

    rt = rule.rule_type
    if rt == "numeric_range":
        return evaluate_numeric(rule, obs, ctx)
    if rt == "qualitative_enum":
        return evaluate_enum(rule, obs, ctx)
    if rt == "qualitative_bool":
        return evaluate_bool(rule, obs, ctx)
    raise ValueError(f"Unknown rule_type: {rt}")
