"""Lightweight structural validation for profiles and switches."""

from __future__ import annotations

import math
import re
from typing import Any

VALID_REQUIREMENTS = {"allowed", "not_allowed", "undefined"}
VALID_RULE_TYPES = {"numeric_range", "qualitative_enum", "qualitative_bool"}
# numeric_range ops (classify_numeric contract)
NUMERIC_OPS = {">=", "<=", ">", "<", "between", "==", "!="}
# applies_when / composite condition leaf ops (evaluate._eval_leaf contract)
CONDITION_OPS = {">=", "<=", ">", "<", "in", "not_in", "==", "!=", "bool"}
VALID_MARGIN_MODES = {"absolute", "relative"}
VALID_DEFINITION_MODES = {"permissive", "restrictive", "default"}
VALID_UNDEFINED_AS = {"allowed", "not_allowed", "undefined"}
VALID_MISSING_POLICY_VALUES = {"allowed", "not_allowed", "undefined", "mode"}
VALID_WARNING_CODE_KEYS = {"outside", "boundary"}
WARNING_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _validate_composite(cond: Any, prefix: str, errors: list[str]) -> None:
    """Validate an applies_when tree; mirrors composite.parse_composite."""
    if not isinstance(cond, dict):
        errors.append(f"{prefix}: condition must be an object")
        return
    if "all_of" in cond:
        children = cond["all_of"]
        if not isinstance(children, list):
            errors.append(f"{prefix}.all_of: must be a list")
            return
        for i, c in enumerate(children):
            _validate_composite(c, f"{prefix}.all_of[{i}]", errors)
    elif "any_of" in cond:
        children = cond["any_of"]
        if not isinstance(children, list):
            errors.append(f"{prefix}.any_of: must be a list")
            return
        for i, c in enumerate(children):
            _validate_composite(c, f"{prefix}.any_of[{i}]", errors)
    elif "not" in cond:
        _validate_composite(cond["not"], f"{prefix}.not", errors)
    elif "key" in cond and "op" in cond:
        op = cond["op"]
        if op not in CONDITION_OPS:
            errors.append(f"{prefix}: invalid condition op {op!r}")
        if op in ("in", "not_in") and not isinstance(cond.get("value"), list):
            errors.append(f"{prefix}: op {op} requires value to be a list")
    else:
        errors.append(f"{prefix}: unrecognized composite structure: {sorted(cond.keys())}")


def _validate_enum(el: dict[str, Any], prefix: str, eid: Any, req: str, errors: list[str]) -> None:
    allowed_raw = el.get("allowed_values")
    boundary_raw = el.get("boundary_values")
    forbidden_raw = el.get("forbidden_values")

    if req == "allowed" and not allowed_raw:
        errors.append(f"{prefix} ({eid}): enum with requirement=allowed needs allowed_values")
    if req == "not_allowed":
        if allowed_raw:
            errors.append(
                f"{prefix} ({eid}): enum with requirement=not_allowed must not define "
                "allowed_values (use forbidden_values)"
            )
        if not forbidden_raw:
            errors.append(f"{prefix} ({eid}): enum with requirement=not_allowed needs forbidden_values")

    sets: dict[str, set[Any]] = {}
    for name, raw in (
        ("allowed_values", allowed_raw),
        ("boundary_values", boundary_raw),
        ("forbidden_values", forbidden_raw),
    ):
        if not raw:
            continue
        if not isinstance(raw, list):
            errors.append(f"{prefix} ({eid}): {name} must be a list")
            continue
        try:
            sets[name] = set(raw)
        except TypeError:
            errors.append(f"{prefix} ({eid}): {name} entries must be scalar values")
            return

    pairs = [
        ("allowed_values", "boundary_values"),
        ("allowed_values", "forbidden_values"),
        ("boundary_values", "forbidden_values"),
    ]
    for a, b in pairs:
        if a in sets and b in sets and (sets[a] & sets[b]):
            overlap = ", ".join(sorted(map(str, sets[a] & sets[b])))
            errors.append(f"{prefix} ({eid}): {a} and {b} overlap on: {overlap}")


def _validate_confidence(el: dict[str, Any], prefix: str, eid: Any, rt: str | None, errors: list[str]) -> None:
    threshold = el.get("confidence_threshold")
    band = el.get("confidence_band")
    key = el.get("confidence_observation_key")
    if threshold is None and band is None and key is None:
        return

    if rt != "qualitative_bool":
        errors.append(f"{prefix} ({eid}): confidence_* fields are only valid on qualitative_bool rules")
        return
    if threshold is None:
        errors.append(f"{prefix} ({eid}): confidence_band/confidence_observation_key requires confidence_threshold")
        return
    if not _is_number(threshold) or not (0.0 <= float(threshold) <= 1.0):
        errors.append(f"{prefix} ({eid}): confidence_threshold must be a number in [0, 1]")
    if not key:
        errors.append(f"{prefix} ({eid}): confidence_threshold requires confidence_observation_key")
    if band is not None and (not _is_number(band) or float(band) < 0.0):
        errors.append(f"{prefix} ({eid}): confidence_band must be a finite number >= 0")


def _validate_numeric(el: dict[str, Any], prefix: str, eid: Any, errors: list[str]) -> None:
    op = el.get("op")
    if op not in NUMERIC_OPS:
        errors.append(f"{prefix} ({eid}): invalid numeric op {op!r} (allowed: {sorted(NUMERIC_OPS)})")
        return
    if op in (">=", "<=", ">", "<", "==", "!="):
        if el.get("threshold") is None:
            errors.append(f"{prefix} ({eid}): op {op} requires threshold")
        elif not _is_number(el.get("threshold")):
            errors.append(f"{prefix} ({eid}): threshold must be a finite number")
    if op == "between":
        rng = el.get("range")
        if rng is None:
            errors.append(f"{prefix} ({eid}): op between requires range")
        elif not isinstance(rng, (list, tuple)) or len(rng) != 2:
            errors.append(f"{prefix} ({eid}): range must be [lo, hi]")
        elif not all(_is_number(x) for x in rng):
            errors.append(f"{prefix} ({eid}): range bounds must be finite numbers")
        elif float(rng[0]) >= float(rng[1]):
            errors.append(f"{prefix} ({eid}): range requires lo < hi")


def validate_profile_dict(data: dict[str, Any]) -> list[str]:
    """Return a list of error strings (empty = valid)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["profile must be a JSON object"]

    if "profile_id" not in data:
        errors.append("missing profile_id")
    if "elements" not in data:
        errors.append("missing elements")
        return errors

    mode = data.get("definition_mode", "default")
    if mode not in VALID_DEFINITION_MODES:
        errors.append(f"invalid definition_mode: {mode!r}")

    errors.extend(_check_missing_policy(data.get("missing_policy")))

    elements = data["elements"]
    if not isinstance(elements, list):
        errors.append("elements must be a list")
        return errors

    seen_ids: set[str] = set()
    for i, el in enumerate(elements):
        prefix = f"elements[{i}]"
        if not isinstance(el, dict):
            errors.append(f"{prefix}: must be object")
            continue
        eid = el.get("element_id")
        if not eid:
            errors.append(f"{prefix}: missing element_id")
        elif eid in seen_ids:
            errors.append(f"{prefix}: duplicate element_id {eid}")
        else:
            seen_ids.add(eid)

        req = el.get("requirement", "allowed")
        if req not in VALID_REQUIREMENTS:
            errors.append(f"{prefix} ({eid}): invalid requirement {req!r}")

        ua = el.get("undefined_as")
        if ua is not None and ua not in VALID_UNDEFINED_AS:
            errors.append(f"{prefix} ({eid}): invalid undefined_as {ua!r}")

        if "expect" in el and el.get("expect") is not None and not isinstance(el.get("expect"), bool):
            errors.append(f"{prefix} ({eid}): expect must be a boolean")

        rt = el.get("rule_type")
        if rt is not None and rt not in VALID_RULE_TYPES:
            # registered custom types pass through; strict checks below only
            # apply to the built-ins
            pass

        if not el.get("observation_key") and req != "undefined":
            errors.append(f"{prefix} ({eid}): missing observation_key")

        if rt == "numeric_range":
            _validate_numeric(el, prefix, eid, errors)

        if rt == "qualitative_enum" and req != "undefined":
            _validate_enum(el, prefix, eid, req, errors)

        _validate_confidence(el, prefix, eid, rt, errors)

        bm = el.get("boundary_margin")
        if bm is not None:
            if not isinstance(bm, dict):
                errors.append(f"{prefix} ({eid}): boundary_margin must be object")
            else:
                if bm.get("mode") not in VALID_MARGIN_MODES:
                    errors.append(f"{prefix} ({eid}): invalid boundary_margin.mode")
                bmv = bm.get("value", 0.0)
                if not _is_number(bmv) or float(bmv) < 0.0:
                    errors.append(f"{prefix} ({eid}): boundary_margin.value must be a finite number >= 0")

        if el.get("applies_when") is not None:
            _validate_composite(el["applies_when"], f"{prefix} ({eid}).applies_when", errors)

        wc = el.get("warning_codes")
        if wc is not None:
            if not isinstance(wc, dict):
                errors.append(f"{prefix} ({eid}): warning_codes must be object")
            else:
                for key, val in wc.items():
                    if key not in VALID_WARNING_CODE_KEYS:
                        errors.append(
                            f"{prefix} ({eid}): invalid warning_codes key {key!r} "
                            "(allowed: outside, boundary)"
                        )
                    if not isinstance(val, str) or not WARNING_CODE_RE.match(val):
                        errors.append(f"{prefix} ({eid}): invalid warning code format: {val!r}")

    errors.extend(check_warning_code_duplicates(elements))
    return errors


def _check_missing_policy(mp: object) -> list[str]:
    """Validate the optional top-level ``missing_policy`` block."""
    if mp is None:
        return []
    if not isinstance(mp, dict):
        return ["missing_policy must be an object"]
    errors: list[str] = []
    for key in mp:
        if key not in ("by_element", "by_tag", "default"):
            errors.append(f"missing_policy: unknown key {key!r}")
    for group in ("by_element", "by_tag"):
        sub = mp.get(group)
        if sub is None:
            continue
        if not isinstance(sub, dict):
            errors.append(f"missing_policy.{group} must be an object")
            continue
        for name, value in sub.items():
            if value not in VALID_MISSING_POLICY_VALUES:
                errors.append(
                    f"missing_policy.{group}[{name}]: invalid value {value!r} "
                    f"(allowed: {sorted(VALID_MISSING_POLICY_VALUES)})"
                )
    default = mp.get("default")
    if default is not None and default not in VALID_MISSING_POLICY_VALUES:
        errors.append(
            f"missing_policy.default: invalid value {default!r} "
            f"(allowed: {sorted(VALID_MISSING_POLICY_VALUES)})"
        )
    return errors


def check_warning_code_duplicates(elements: list[Any]) -> list[str]:
    """Return errors when the same warning code is used by more than one element.

    `boundary` and `outside` codes are counted uniformly; a code may appear
    at most once across the whole profile (duplicate codes make report
    consumers unable to attribute a warning to its source element).
    """
    errors: list[str] = []
    code_owners: dict[str, str] = {}
    for i, el in enumerate(elements):
        if not isinstance(el, dict):
            continue
        eid = el.get("element_id") or f"elements[{i}]"
        wc = el.get("warning_codes")
        if not isinstance(wc, dict):
            continue
        for val in wc.values():
            if not isinstance(val, str):
                continue
            owner = code_owners.get(val)
            if owner is None:
                code_owners[val] = eid
            elif owner != eid:
                errors.append(f"duplicate warning code {val!r}: used by {owner} and {eid}")
    return errors


def validate_switches_dict(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["switches must be a JSON object"]
    for key in ("by_element", "by_rule_type", "by_tag"):
        if key in data and not isinstance(data[key], dict):
            errors.append(f"{key} must be an object")
    return errors
