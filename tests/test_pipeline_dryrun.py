"""End-to-end dry run: real beat detection, real ffmpeg cuts, fake generation."""

import json
from pathlib import Path

from reelforge import media, runner

JOB = """
name: e2e-test
style: contrast-noir
aspect: "9:16"
budget_usd: 5.0
n_variants: 2
music:
  prompt: "high-energy phonk, hard drops"
  duration_s: 16
shots:
  - subject: "a black cat with amber eyes"
    action: "sprinting toward camera"
  - subject: "a black cat with amber eyes"
    action: "leaping across neon rooftops"
"""


def test_dry_run_produces_beat_synced_final(tmp_path: Path):
    job = tmp_path / "job.yaml"
    job.write_text(JOB)
    rc = runner.main(["run", str(job), "--dry-run", "--workdir", str(tmp_path / "runs")])
    assert rc == 0

    workdir = tmp_path / "runs" / "e2e-test"
    state = json.loads((workdir / "state.json").read_text())
    final = Path(state["done"]["assemble"])
    assert final.exists()

    plan = state["done"]["plan"]
    planned = sum(s["end"] - s["start"] for s in plan)
    assert abs(media.probe_duration(final) - planned) < 0.25
    assert state["cost_usd"] > 0

    # Resume is a no-op: nothing regenerates, same final.
    mtime = final.stat().st_mtime
    assert runner.main(["run", str(job), "--dry-run",
                        "--workdir", str(tmp_path / "runs")]) == 0
    assert final.stat().st_mtime == mtime


def test_budget_cap_stops_the_run(tmp_path: Path):
    job = tmp_path / "job.yaml"
    job.write_text(JOB.replace("budget_usd: 5.0", "budget_usd: 0.01"))
    rc = runner.main(["run", str(job), "--dry-run", "--workdir", str(tmp_path / "runs")])
    assert rc == 4
