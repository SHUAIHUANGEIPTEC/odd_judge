"""Boundary margin helpers and numeric state classification."""

from __future__ import annotations

import math
from typing import Optional

from .types import BoundaryMargin, ScenarioState, ThresholdSpec

# Relative tolerance applied when a safety margin lands exactly on the band
# width, so a decimal value that is "one band away" classifies the same way
# regardless of binary rounding (e.g. 2.5+0.2 vs the literal 2.7).
EDGE_REL_TOL = 1e-12


def _reaches_band(margin_value: float, band: float) -> bool:
    """True when the safety margin is at least one full band (INSIDE edge)."""
    if margin_value >= band:
        return True
    return band > 0.0 and math.isclose(margin_value, band, rel_tol=EDGE_REL_TOL)


def classify_numeric(
    value: float,
    spec: ThresholdSpec,
) -> tuple[ScenarioState, Optional[float], Optional[float]]:
    """Classify a numeric observation against a threshold spec.

    Unified margin principle for relational/range ops (>=, >, <=, <, between):

        OUTSIDE   the violating set is hit (margin < 0, or == 0 for strict ops)
        BOUNDARY  0 <= margin < band        (margin == 0 stays BOUNDARY)
        INSIDE    margin >= band            (band edge belongs to INSIDE)

    For equality ops the band is an inclusive tolerance zone around the
    satisfying point (`==`) / forbidden point (`!=`): the outer band edge is
    BOUNDARY, beyond it flips (== → OUTSIDE, != → INSIDE).

    Returns (state, remaining_margin, margin_band); remaining_margin is the
    signed safety margin (positive = inside, negative = outside).
    """
    if not math.isfinite(value):
        raise ValueError(f"classify_numeric requires a finite value, got {value!r}")

    op = spec.op
    margin_cfg = spec.margin or BoundaryMargin(mode="absolute", value=0.0)

    if op in (">=", ">") and spec.threshold is not None:
        thr = float(spec.threshold)
        band = margin_cfg.band_for_threshold(thr)
        m = value - thr  # exact sign: subtraction of two doubles never lies
        violated = m < 0 if op == ">=" else m <= 0
        remaining = m

    elif op in ("<=", "<") and spec.threshold is not None:
        thr = float(spec.threshold)
        band = margin_cfg.band_for_threshold(thr)
        m = thr - value
        violated = m < 0 if op == "<=" else m <= 0
        remaining = m

    elif op == "between" and spec.range is not None:
        lo, hi = float(spec.range[0]), float(spec.range[1])
        band = margin_cfg.band_for_range(lo, hi)
        remaining = min(value - lo, hi - value)
        violated = remaining < 0

    elif op == "==" and spec.threshold is not None:
        thr = float(spec.threshold)
        band = margin_cfg.band_for_threshold(thr)
        d = abs(value - thr)
        if d == 0.0:
            return ScenarioState.INSIDE, 0.0, band
        # tolerance zone closed at the band edge (fp-edge absorbed)
        if band > 0.0 and (d < band or math.isclose(d, band, rel_tol=EDGE_REL_TOL)):
            return ScenarioState.BOUNDARY, thr - value, band
        return ScenarioState.OUTSIDE, thr - value, band

    elif op == "!=" and spec.threshold is not None:
        thr = float(spec.threshold)
        band = margin_cfg.band_for_threshold(thr)
        d = abs(value - thr)
        if d == 0.0:
            return ScenarioState.OUTSIDE, 0.0, band
        # forbidden point hit only when exactly equal; near-miss is BOUNDARY
        # while the band lasts, INSIDE (with fp tolerance) at the band edge.
        if band > 0.0 and (d < band or math.isclose(d, band, rel_tol=EDGE_REL_TOL)):
            return ScenarioState.BOUNDARY, d, band
        return ScenarioState.INSIDE, d, band

    else:
        raise ValueError(f"Unsupported numeric op for classify_numeric: {op!r}")

    # Relational / between: unified three-way split on the safety margin.
    if violated:
        return ScenarioState.OUTSIDE, remaining, band
    if _reaches_band(remaining, band):
        return ScenarioState.INSIDE, remaining, band
    return ScenarioState.BOUNDARY, remaining, band


def relative_band(threshold: float, fraction: float) -> float:
    return abs(threshold) * fraction
