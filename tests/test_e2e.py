"""Tests for perception adapters and CLI end-to-end."""

import json
import subprocess
import sys
from pathlib import Path

from odd_judge.api import OddJudge
from odd_judge.perception.json_stream import load_observation_file, load_observation_stream
from odd_judge.perception.mock import MockAdapter, SCENARIOS

ROOT = Path(__file__).resolve().parent.parent


def test_mock_adapter_scenarios():
    assert set(MockAdapter.list_scenarios()) == set(SCENARIOS)
    for name in SCENARIOS:
        obs = MockAdapter(name).get_observation()
        assert obs.fields


def test_json_file_adapter():
    obs = load_observation_file(ROOT / "observations" / "sample_highway_inside.json")
    assert obs.get("scenery.road_type") == "expressway_main"


def test_judge_inside():
    judge = OddJudge.from_files(
        ROOT / "profiles" / "byd_tjp.json",
        switches_path=ROOT / "switches" / "default_switches.json",
    )
    report = judge.evaluate_path(ROOT / "observations" / "sample_highway_inside.json")
    assert report.state.value == "INSIDE"
    assert report.recommendation == "continue"


def test_judge_boundary():
    judge = OddJudge.from_files(
        ROOT / "profiles" / "byd_tjp.json",
        switches_path=ROOT / "switches" / "default_switches.json",
    )
    report = judge.evaluate_path(ROOT / "observations" / "sample_curve_boundary.json")
    assert report.state.value == "BOUNDARY"
    assert report.recommendation == "warn_driver"
    assert len(report.boundary_reasons) > 0


def test_judge_outside():
    judge = OddJudge.from_files(
        ROOT / "profiles" / "byd_tjp.json",
        switches_path=ROOT / "switches" / "default_switches.json",
    )
    report = judge.evaluate_path(ROOT / "observations" / "sample_rain_outside.json")
    assert report.state.value == "OUTSIDE"
    assert report.recommendation == "mrm_or_refuse"
    assert len(report.outside_reasons) > 0


def test_switch_skips_rule():
    switches = {
        "global_enabled": True,
        "by_element": {"ODC.3.1.2.rain_intensity": False},
        "by_rule_type": {},
        "by_tag": {},
        "boundary_warnings_enabled": True,
    }
    judge = OddJudge.from_files(
        ROOT / "profiles" / "byd_tjp.json",
        switches_path=None,
    )
    judge.switch_policy.by_element["ODC.3.1.2.rain_intensity"] = False
    report = judge.evaluate_path(ROOT / "observations" / "sample_rain_outside.json")
    skipped_ids = {s["element_id"] for s in report.skipped}
    assert "ODC.3.1.2.rain_intensity" in skipped_ids


def test_cli_evaluate():
    result = subprocess.run(
        [
            sys.executable, "-m", "odd_judge", "evaluate",
            "--project-root", str(ROOT),
            "--profile", "byd_tjp",
            "--obs", str(ROOT / "observations" / "sample_curve_boundary.json"),
            "--switches", str(ROOT / "switches" / "default_switches.json"),
            "--format", "text",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 1, result.stderr  # BOUNDARY → warn exit code
    assert "BOUNDARY" in result.stdout


def test_cli_validate():
    result = subprocess.run(
        [sys.executable, "-m", "odd_judge", "validate", "--profile", str(ROOT / "profiles" / "byd_tjp.json")],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "VALID" in result.stdout


def _run_cli(*argv: str):
    return subprocess.run(
        [sys.executable, "-m", "odd_judge", *argv],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )


def test_cli_exit_codes_reflect_worst_state():
    """0 = INSIDE, 1 = BOUNDARY, 3 = OUTSIDE."""
    common = ["evaluate", "--project-root", str(ROOT), "--profile", "byd_tjp", "--format", "text"]

    inside = _run_cli(*common, "--obs", str(ROOT / "observations" / "sample_highway_inside.json"))
    assert inside.returncode == 0, inside.stderr + inside.stdout

    boundary = _run_cli(*common, "--obs", str(ROOT / "observations" / "sample_curve_boundary.json"))
    assert boundary.returncode == 1, boundary.stderr + boundary.stdout

    outside = _run_cli(*common, "--obs", str(ROOT / "observations" / "sample_rain_outside.json"))
    assert outside.returncode == 3, outside.stderr + outside.stdout


def test_cli_missing_input_is_clean_error():
    result = _run_cli("evaluate", "--project-root", str(ROOT), "--profile", "byd_tjp")
    assert result.returncode == 4
    assert "ERROR:" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_unknown_obs_file_is_clean_error():
    result = _run_cli(
        "evaluate",
        "--project-root",
        str(ROOT),
        "--profile",
        "byd_tjp",
        "--obs",
        str(ROOT / "observations" / "does_not_exist.json"),
    )
    assert result.returncode == 4
    assert "ERROR:" in result.stderr
    assert "Traceback" not in result.stderr


def test_mock_scenarios_match_json_verdicts():
    """Mock fixtures must carry the same keys as the JSON samples → same verdict."""
    judge = OddJudge.from_files(
        ROOT / "profiles" / "byd_tjp.json",
        switches_path=ROOT / "switches" / "default_switches.json",
    )
    pairs = [
        ("highway_inside", "sample_highway_inside.json", "INSIDE"),
        ("curve_boundary", "sample_curve_boundary.json", "BOUNDARY"),
        ("rain_outside", "sample_rain_outside.json", "OUTSIDE"),
    ]
    for scenario, sample, expected in pairs:
        mock_state = judge.evaluate(MockAdapter(scenario).get_observation()).state.value
        json_state = judge.evaluate_path(ROOT / "observations" / sample).state.value
        assert mock_state == expected, f"mock {scenario}: {mock_state}"
        assert json_state == expected, f"json {sample}: {json_state}"


def test_effective_switches_in_report():
    """active_switches lists only switches that actually alter the judgment."""
    judge = OddJudge.from_files(
        ROOT / "profiles" / "byd_tjp.json",
        switches_path=ROOT / "switches" / "default_switches.json",
    )
    report = judge.evaluate_path(ROOT / "observations" / "sample_highway_inside.json")
    assert report.active_switches == []

    judge.switch_policy.by_element["ODC.3.1.2.rain_intensity"] = False
    judge.switch_policy.boundary_warnings_enabled = False
    report = judge.evaluate_path(ROOT / "observations" / "sample_rain_outside.json")
    assert "by_element[ODC.3.1.2.rain_intensity]=false" in report.active_switches
    assert "boundary_warnings_enabled=false" in report.active_switches
