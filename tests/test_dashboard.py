import json
from pathlib import Path

import pytest

from reelforge import dashboard, runner
from reelforge.job import BudgetExceeded, global_charge, ledger_total, save_limits

JOB = """
name: dash-test
style: neon-street
flow: direct
music: {prompt: "phonk", duration_s: 16}
shots:
  - {subject: "a black cat with amber eyes", action: "sprinting"}
"""


def test_playground_estimate_matches_price_table():
    assert dashboard.playground_estimate(
        {"kind": "image", "model": "image_fast", "width": 1000, "height": 1000}) == 0.005
    assert dashboard.playground_estimate(
        {"kind": "image", "model": "image_high"}) == 0.035
    assert dashboard.playground_estimate(
        {"kind": "video", "duration": 10, "resolution": "768P"}) == pytest.approx(0.10)
    assert dashboard.playground_estimate(
        {"kind": "music", "duration": 30}) == pytest.approx(0.06)


def test_global_charge_cap_and_ledger(tmp_path: Path):
    save_limits(tmp_path, {"global_cap_usd": 0.10})
    global_charge(tmp_path, "j1", 0.06, "a")
    with pytest.raises(BudgetExceeded):
        global_charge(tmp_path, "j2", 0.06, "b")
    assert ledger_total(tmp_path) == pytest.approx(0.06)  # rejected spend not logged


def test_scan_jobs_sees_dry_run(tmp_path: Path):
    job = tmp_path / "job.yaml"
    job.write_text(JOB)
    assert runner.main(["run", str(job), "--dry-run",
                        "--workdir", str(tmp_path / "runs")]) == 0
    jobs = dashboard.scan_jobs(tmp_path / "runs")
    assert len(jobs) == 1
    j = jobs[0]
    assert j["name"] == "dash-test"
    assert j["final"] and Path(j["final"]).exists()
    assert j["spec"]["flow"] == "direct"
    assert "keyframes" not in j["steps"]  # direct flow skips images entirely
    assert j["estimate_usd"] > 0
    detail = dashboard.job_detail(tmp_path / "runs", "dash-test")
    assert detail["state"]["done"]["plan"]
