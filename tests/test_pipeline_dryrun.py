"""End-to-end dry runs: real beat detection, real ffmpeg cuts, fake generation.

Nothing here touches the network. The storyboard is the protocol under test:
the runner writes it, the gate reads it, and edits made through
storyboard.update_shot (or the `reelforge shot` CLI) steer the next run.
"""

import json
from pathlib import Path

import pytest

from reelforge import media, runner, storyboard
from reelforge.job import load_job

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

DIRECT_JOB = JOB.replace("name: e2e-test", "name: e2e-direct\nflow: direct")


@pytest.fixture
def job(tmp_path: Path) -> Path:
    p = tmp_path / "job.yaml"
    p.write_text(JOB)
    return p


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    return tmp_path / "runs"


def run(job: Path, runs: Path, *flags: str) -> int:
    return runner.main(["run", str(job), "--dry-run", "--workdir", str(runs), *flags])


def shot_cli(job: Path, runs: Path, index: int, *flags: str) -> int:
    return runner.main(["shot", str(job), str(index), "--workdir", str(runs), *flags])


def workdir_of(runs: Path, name: str = "e2e-test") -> Path:
    return runs / name


# --- the image-first gate ------------------------------------------------

def test_gate_stops_before_paying_for_video(job: Path, runs: Path):
    assert run(job, runs) == 3  # --dry-run does NOT imply --auto
    wd = workdir_of(runs)

    sb = storyboard.load(wd)
    assert not storyboard.all_approved(sb)
    for s in sb["shots"]:
        assert s["status"] == "images_ready"
        assert len(s["candidates"]) == 2 and all(Path(c).exists() for c in s["candidates"])
        assert s["chosen"] is None and s["video"] is None
        assert s["image_prompt"] and s["video_prompt"]
        assert s["est_images_usd"] > 0 and s["est_video_usd"] > 0

    state = json.loads((wd / "state.json").read_text())
    assert "keyframes" in state["done"]
    assert "videos" not in state["done"] and "assemble" not in state["done"]
    assert not (wd / "final.mp4").exists()
    assert not list((wd / "assets").glob("clip_*.mp4"))


def test_approving_every_shot_completes_the_job(job: Path, runs: Path):
    assert run(job, runs) == 3
    wd = workdir_of(runs)

    # shot 0 edited the way an agent or the dashboard does it: through the API.
    storyboard.update_shot(wd, 0, {"image_prompt": "a black cat with amber eyes, "
                                                   "single hard spotlight, no subtitles",
                                   "chosen": 1, "status": "approved", "notes": "keeper"})
    # shot 1 the way a CLI agent does it.
    assert shot_cli(job, runs, 1, "--chosen", "0", "--approve") == 0
    assert storyboard.all_approved(storyboard.load(wd))

    assert run(job, runs) == 0
    sb = storyboard.load(wd)
    assert [s["status"] for s in sb["shots"]] == ["done", "done"]
    for s in sb["shots"]:
        assert Path(s["video"]).exists()
    assert sb["shots"][0]["notes"] == "keeper"

    final = Path(json.loads((wd / "state.json").read_text())["done"]["assemble"])
    assert final.exists()
    planned = sum(s["end"] - s["start"] for s in sb["shots"])
    assert abs(media.probe_duration(final) - planned) < 0.25

    # Resume is a no-op: nothing regenerates, same final.
    mtime = final.stat().st_mtime
    assert run(job, runs) == 0
    assert final.stat().st_mtime == mtime


def test_redo_regenerates_only_that_shot(job: Path, runs: Path):
    assert run(job, runs) == 3
    wd = workdir_of(runs)
    before = storyboard.load(wd)
    kept = before["shots"][0]["candidates"]
    kept_mtimes = [Path(c).stat().st_mtime for c in kept]

    storyboard.update_shot(wd, 0, {"chosen": 0, "status": "approved"})
    # Editing a prompt after keyframes exist implies a redo of that shot only.
    storyboard.update_shot(wd, 1, {"image_prompt": "a black cat with amber eyes, "
                                                   "hard rim light, no subtitles"})
    assert storyboard.get_shot(storyboard.load(wd), 1)["status"] == "redo"

    assert run(job, runs) == 3  # shot 1 is pending again, so the gate holds
    after = storyboard.load(wd)
    assert after["shots"][0]["candidates"] == kept  # approved shot untouched
    assert [Path(c).stat().st_mtime for c in kept] == kept_mtimes
    assert after["shots"][0]["status"] == "approved"

    redone = after["shots"][1]
    assert redone["status"] == "images_ready" and redone["chosen"] is None
    # Fresh filenames, so nothing can serve the stale candidates.
    assert set(redone["candidates"]).isdisjoint(before["shots"][1]["candidates"])
    assert all(Path(c).exists() for c in redone["candidates"])

    assert shot_cli(job, runs, 1, "--chosen", "1", "--approve") == 0
    assert run(job, runs) == 0
    assert all(Path(s["video"]).exists() for s in storyboard.load(wd)["shots"])


def test_auto_skips_the_gate_and_picks_the_first_candidate(job: Path, runs: Path):
    assert run(job, runs, "--auto") == 0
    wd = workdir_of(runs)
    sb = storyboard.load(wd)
    assert [s["chosen"] for s in sb["shots"]] == [0, 0]
    assert [s["status"] for s in sb["shots"]] == ["done", "done"]

    # A finished run whose storyboard is missing (it predates the file, or was
    # deleted) adopts its clips instead of paying to render them again.
    clips = [Path(s["video"]) for s in sb["shots"]]
    mtimes = [c.stat().st_mtime for c in clips]
    storyboard.path(wd).unlink()
    assert run(job, runs) == 0
    assert [c.stat().st_mtime for c in clips] == mtimes
    assert [s["status"] for s in storyboard.load(wd)["shots"]] == ["done", "done"]


# --- the direct flow -----------------------------------------------------

def test_direct_flow_runs_end_to_end_without_a_gate(tmp_path: Path, runs: Path):
    job = tmp_path / "direct.yaml"
    job.write_text(DIRECT_JOB)
    assert run(job, runs) == 0  # no --auto needed: nothing to review

    wd = workdir_of(runs, "e2e-direct")
    sb = storyboard.load(wd)
    assert sb["flow"] == "direct"
    for s in sb["shots"]:
        assert "candidates" not in s  # direct shots never have keyframes
        assert s["status"] == "done" and Path(s["video"]).exists()
    state = json.loads((wd / "state.json").read_text())
    assert "keyframes" not in state["done"]
    assert Path(state["done"]["assemble"]).exists()


def test_budget_cap_stops_the_run(tmp_path: Path, runs: Path):
    job = tmp_path / "job.yaml"
    job.write_text(JOB.replace("budget_usd: 5.0", "budget_usd: 0.01"))
    assert run(job, runs) == 4


# --- update_shot validation (the single edit endpoint) -------------------

@pytest.fixture
def storyboarded(job: Path, runs: Path) -> Path:
    """A storyboard without the cost of a pipeline run."""
    spec = load_job(job)
    plan = [{"index": i, "start": 2.0 * i, "end": 2.0 * (i + 1),
             "gen_seconds": 3, "on_drop": False} for i in range(len(spec.shots))]
    wd = workdir_of(runs)
    wd.mkdir(parents=True)
    storyboard.save(wd, storyboard.build(spec, plan, spec.shots))
    return wd


@pytest.mark.parametrize("fields, message", [
    ({"est_video_usd": 9.9}, "not editable"),
    ({"index": 3}, "not editable"),
    ({"status": "shipped"}, "unknown status"),
    ({"image_prompt": "  "}, "must not be empty"),
    ({"image_prompt": "a moody cat, nice"}, "banned words"),
    ({"video_prompt": "beautiful cat"}, "banned words"),
    ({"chosen": 0}, "chosen must be an int"),          # no candidates yet
    ({"status": "approved"}, "needs a chosen candidate"),
])
def test_update_shot_rejects_bad_edits(storyboarded: Path, fields, message):
    with pytest.raises(ValueError, match=message):
        storyboard.update_shot(storyboarded, 0, fields)
    # A rejected edit changes nothing on disk.
    assert storyboard.get_shot(storyboard.load(storyboarded), 0)["status"] == "planned"


def test_update_shot_rejects_unknown_index(storyboarded: Path):
    with pytest.raises(ValueError, match="no shot 7"):
        storyboard.update_shot(storyboarded, 7, {"notes": "x"})


def test_update_shot_without_a_storyboard(runs: Path):
    (runs / "e2e-test").mkdir(parents=True)
    with pytest.raises(ValueError, match="no storyboard yet"):
        storyboard.update_shot(workdir_of(runs), 0, {"notes": "x"})


def test_shot_cli_reports_errors_on_stderr(job: Path, runs: Path,
                                           storyboarded: Path, capsys):
    assert shot_cli(job, runs, 0, "--chosen", "4") == 2
    assert "chosen must be an int" in capsys.readouterr().err
    assert shot_cli(job, runs, 0, "--redo", "--notes", "try again") == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "redo" and printed["notes"] == "try again"
