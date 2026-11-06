"""Tests for BoundaryMargin and classify_numeric."""

from odd_judge.core.margin import classify_numeric
from odd_judge.core.types import BoundaryMargin, ScenarioState, ThresholdSpec


def test_absolute_band():
    m = BoundaryMargin(mode="absolute", value=20.0)
    assert m.band_for_threshold(200.0) == 20.0
    assert m.band_for_range(100.0, 200.0) == 20.0


def test_relative_band():
    m = BoundaryMargin(mode="relative", value=0.1)
    assert m.band_for_threshold(200.0) == 20.0
    assert m.band_for_range(0.0, 100.0) == 10.0


def test_ge_inside():
    spec = ThresholdSpec(op=">=", threshold=200.0, margin=BoundaryMargin("absolute", 20.0))
    state, rem, band = classify_numeric(250.0, spec)
    assert state == ScenarioState.INSIDE
    assert rem == 50.0
    assert band == 20.0


def test_ge_boundary():
    spec = ThresholdSpec(op=">=", threshold=200.0, margin=BoundaryMargin("absolute", 20.0))
    state, rem, band = classify_numeric(212.0, spec)
    assert state == ScenarioState.BOUNDARY
    assert rem == 12.0


def test_ge_outside():
    spec = ThresholdSpec(op=">=", threshold=200.0, margin=BoundaryMargin("absolute", 20.0))
    state, rem, _ = classify_numeric(180.0, spec)
    assert state == ScenarioState.OUTSIDE
    assert rem == -20.0


def test_le_inside_boundary_outside():
    spec = ThresholdSpec(op="<=", threshold=9.0, margin=BoundaryMargin("absolute", 1.0))
    assert classify_numeric(5.0, spec)[0] == ScenarioState.INSIDE
    assert classify_numeric(8.5, spec)[0] == ScenarioState.BOUNDARY
    assert classify_numeric(10.0, spec)[0] == ScenarioState.OUTSIDE


def test_between_inside():
    spec = ThresholdSpec(op="between", range=(2.5, 5.5), margin=BoundaryMargin("absolute", 0.2))
    state, rem, _ = classify_numeric(3.5, spec)
    assert state == ScenarioState.INSIDE
    assert rem == 1.0  # min(3.5-2.5, 5.5-3.5) = 1.0


def test_between_boundary():
    spec = ThresholdSpec(op="between", range=(2.5, 5.5), margin=BoundaryMargin("absolute", 0.2))
    state, rem, _ = classify_numeric(2.65, spec)
    assert state == ScenarioState.BOUNDARY
    assert abs(rem - 0.15) < 1e-9


def test_between_outside():
    spec = ThresholdSpec(op="between", range=(2.5, 5.5), margin=BoundaryMargin("absolute", 0.2))
    state, rem, _ = classify_numeric(2.0, spec)
    assert state == ScenarioState.OUTSIDE
    assert rem == -0.5


# ---------------------------------------------------------------------------
# Band-edge unification: a value exactly one band away belongs to INSIDE
# for relational/range ops (>= > <= < between), stable under fp rounding.
# ---------------------------------------------------------------------------


def test_ge_band_edge_is_inside():
    spec = ThresholdSpec(op=">=", threshold=0.6, margin=BoundaryMargin("absolute", 0.05))
    assert classify_numeric(0.65, spec)[0] == ScenarioState.INSIDE  # JSON literal
    assert classify_numeric(0.6 + 0.05, spec)[0] == ScenarioState.INSIDE  # expression
    assert classify_numeric(0.64999999, spec)[0] == ScenarioState.BOUNDARY
    assert classify_numeric(0.6, spec)[0] == ScenarioState.BOUNDARY  # threshold itself


def test_le_band_edge_is_inside():
    spec = ThresholdSpec(op="<=", threshold=14.9, margin=BoundaryMargin("absolute", 1.5))
    assert classify_numeric(13.4, spec)[0] == ScenarioState.INSIDE  # thr - band
    assert classify_numeric(13.400001, spec)[0] == ScenarioState.BOUNDARY
    assert classify_numeric(14.9, spec)[0] == ScenarioState.BOUNDARY


def test_strict_gt_edge_semantics():
    spec = ThresholdSpec(op=">", threshold=200.0, margin=BoundaryMargin("absolute", 20.0))
    assert classify_numeric(200.0, spec)[0] == ScenarioState.OUTSIDE  # strict: threshold violates
    assert classify_numeric(220.0, spec)[0] == ScenarioState.INSIDE  # band edge → INSIDE
    assert classify_numeric(210.0, spec)[0] == ScenarioState.BOUNDARY


def test_between_band_edges_are_inside_stable():
    """Both ends: exact band distance → INSIDE regardless of fp direction."""
    lane = ThresholdSpec(op="between", range=(2.5, 5.5), margin=BoundaryMargin("absolute", 0.2))
    assert classify_numeric(2.7, lane)[0] == ScenarioState.INSIDE
    assert classify_numeric(5.3, lane)[0] == ScenarioState.INSIDE
    cross = ThresholdSpec(op="between", range=(-2.0, 2.0), margin=BoundaryMargin("absolute", 0.2))
    assert classify_numeric(1.8, cross)[0] == ScenarioState.INSIDE
    assert classify_numeric(-1.8, cross)[0] == ScenarioState.INSIDE
    grade = ThresholdSpec(op="between", range=(-9.0, 9.0), margin=BoundaryMargin("absolute", 0.9))
    assert classify_numeric(8.1, grade)[0] == ScenarioState.INSIDE
    assert classify_numeric(-8.1, grade)[0] == ScenarioState.INSIDE


def test_between_range_endpoints_are_boundary():
    speed = ThresholdSpec(op="between", range=(0.0, 80.0), margin=BoundaryMargin("absolute", 3.0))
    assert classify_numeric(0.0, speed)[0] == ScenarioState.BOUNDARY
    assert classify_numeric(80.0, speed)[0] == ScenarioState.BOUNDARY
    assert classify_numeric(3.0, speed)[0] == ScenarioState.INSIDE  # band edge
    assert classify_numeric(77.0, speed)[0] == ScenarioState.INSIDE  # band edge
    assert classify_numeric(2.9, speed)[0] == ScenarioState.BOUNDARY
    assert classify_numeric(80.1, speed)[0] == ScenarioState.OUTSIDE


def test_zero_band_has_no_boundary_zone():
    spec = ThresholdSpec(op="<=", threshold=0.0, margin=BoundaryMargin("absolute", 0.0))
    assert classify_numeric(0.0, spec)[0] == ScenarioState.INSIDE
    assert classify_numeric(1.0, spec)[0] == ScenarioState.OUTSIDE
    ge = ThresholdSpec(op=">=", threshold=100.0, margin=BoundaryMargin("absolute", 0.0))
    assert classify_numeric(100.0, ge)[0] == ScenarioState.INSIDE
    assert classify_numeric(99.9, ge)[0] == ScenarioState.OUTSIDE


# ---------------------------------------------------------------------------
# == / != : the band is an inclusive tolerance zone
# ---------------------------------------------------------------------------


def test_neq_produces_boundary_near_forbidden_value():
    spec = ThresholdSpec(op="!=", threshold=10.0, margin=BoundaryMargin("absolute", 1.0))
    assert classify_numeric(10.0, spec)[0] == ScenarioState.OUTSIDE
    assert classify_numeric(10.5, spec)[0] == ScenarioState.BOUNDARY
    assert classify_numeric(9.5, spec)[0] == ScenarioState.BOUNDARY
    assert classify_numeric(11.0, spec)[0] == ScenarioState.BOUNDARY  # band edge, closed
    assert classify_numeric(11.000001, spec)[0] == ScenarioState.INSIDE
    assert classify_numeric(12.0, spec)[0] == ScenarioState.INSIDE


def test_neq_zero_band_is_binary():
    spec = ThresholdSpec(op="!=", threshold=10.0, margin=BoundaryMargin("absolute", 0.0))
    assert classify_numeric(10.0, spec)[0] == ScenarioState.OUTSIDE
    assert classify_numeric(10.5, spec)[0] == ScenarioState.INSIDE


def test_eq_tolerance_zone_closed_at_edge():
    spec = ThresholdSpec(op="==", threshold=10.0, margin=BoundaryMargin("absolute", 1.0))
    assert classify_numeric(10.0, spec)[0] == ScenarioState.INSIDE
    assert classify_numeric(10.5, spec)[0] == ScenarioState.BOUNDARY
    assert classify_numeric(11.0, spec)[0] == ScenarioState.BOUNDARY  # edge closed
    assert classify_numeric(11.000001, spec)[0] == ScenarioState.OUTSIDE


def test_non_finite_value_raises():
    spec = ThresholdSpec(op="between", range=(0.0, 80.0), margin=BoundaryMargin("absolute", 3.0))
    for bad in (float("nan"), float("inf"), float("-inf")):
        try:
            classify_numeric(bad, spec)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad!r}")
