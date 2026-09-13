import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from reelforge import dashboard, runner, storyboard
from reelforge.job import BudgetExceeded, global_charge, ledger_total, save_limits

JOB = """
name: dash-test
style: neon-street
flow: direct
music: {prompt: "phonk", duration_s: 16}
shots:
  - {subject: "a black cat with amber eyes", action: "sprinting"}
"""


def make_run(runs_root: Path, name: str = "sb-test") -> Path:
    """A run on disk shaped like the runner leaves it at the review gate."""
    workdir = runs_root / name
    (workdir / "assets").mkdir(parents=True)
    (workdir / "state.json").write_text(json.dumps({
        "spec": {"flow": "image-first", "style": "neon-street", "budget_usd": 3.0},
        "estimate_usd": 0.5, "cost_usd": 0.12,
        "done": {"music": str(workdir / "assets/music.wav"), "plan": [], "keyframes": 1},
    }))
    assets = workdir / "assets"
    storyboard.save(workdir, {
        "version": 1, "job": name, "flow": "image-first",
        "shots": [
            {"index": 0, "start": 0.0, "end": 5.0, "gen_seconds": 6, "on_drop": False,
             "video_prompt": "a black cat sprinting, neon street",
             "est_video_usd": 0.06, "video": None, "notes": "", "status": "images_ready",
             "image_prompt": "a black cat, neon street", "est_images_usd": 0.01,
             "candidates": [str(assets / "kf_0_a1_0.png"), str(assets / "kf_0_a1_1.png")],
             "chosen": None},
            {"index": 1, "start": 5.0, "end": 9.0, "gen_seconds": 5, "on_drop": True,
             "video_prompt": "the cat leaps on the drop",
             "est_video_usd": 0.05, "video": str(assets / "clip_1.mp4"),
             "notes": "", "status": "done",
             "image_prompt": "the cat mid-leap", "est_images_usd": 0.01,
             "candidates": [str(assets / "kf_1_a1_0.png")], "chosen": 0},
        ],
    })
    return workdir


@contextmanager
def serving(runs_root: Path):
    """The real handler on a real socket: routes and status codes included."""
    runs_root.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        dashboard.make_handler(runs_root, dashboard.Playground(runs_root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def call(base: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


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


def test_storyboard_get_maps_assets_to_servable_urls(tmp_path: Path):
    runs = tmp_path / "runs"
    make_run(runs)
    with serving(runs) as base:
        code, d = call(base, "/api/storyboard?job=sb-test")
        assert code == 200
        sb = d["storyboard"]
        assert d["job"] == "sb-test" and sb["flow"] == "image-first"
        s0, s1 = sb["shots"]
        # every asset path the runner recorded comes back as a /files/ URL the
        # page can actually load — no path surgery left to the browser
        assert s0["candidates"] == ["/files/sb-test/assets/kf_0_a1_0.png",
                                    "/files/sb-test/assets/kf_0_a1_1.png"]
        assert s1["video"] == "/files/sb-test/assets/clip_1.mp4"
        # the rest of the contract is passed through untouched
        assert (s0["status"], s0["chosen"], s0["on_drop"]) == ("images_ready", None, False)
        assert s0["est_video_usd"] == 0.06 and s0["image_prompt"]
        assert s1["status"] == "done" and s1["on_drop"] is True
        # a run that exists but has no storyboard yet is not an error
        (runs / "bare").mkdir()
        assert call(base, "/api/storyboard?job=bare") == (200, {"job": "bare",
                                                               "storyboard": None})
        code, d = call(base, "/api/storyboard?job=nope")
        assert code == 404 and "nope" in d["error"]


def test_summary_lists_runs_with_a_storyboard_digest(tmp_path: Path):
    runs = tmp_path / "runs"
    make_run(runs)
    job = dashboard.scan_jobs(runs)[0]
    assert job["storyboard"] == {"flow": "image-first", "shots": 2,
                                 "counts": {"images_ready": 1, "done": 1},
                                 "pending": 1, "ready": 2, "awaiting": True}
    assert job["updated"] > 0 and job["running"] is False


def test_post_shot_edits_through_the_storyboard_contract(tmp_path: Path):
    runs = tmp_path / "runs"
    workdir = make_run(runs)
    with serving(runs) as base:
        code, d = call(base, "/api/shot", {"job": "sb-test", "index": 0,
                                           "chosen": 1, "status": "approved"})
        assert code == 200 and d["ok"] is True
        shot = d["storyboard"]["shots"][0]
        assert (shot["status"], shot["chosen"]) == ("approved", 1)
        assert storyboard.load(workdir)["shots"][0]["status"] == "approved"
        # the answer carries the mapped URLs too, so the page repaints from it
        assert shot["candidates"][1] == "/files/sb-test/assets/kf_0_a1_1.png"
        # editing a prompt after keyframes exist is a redo, per the contract
        code, d = call(base, "/api/shot", {"job": "sb-test", "index": 0,
                                           "image_prompt": "a black cat, rim light"})
        assert code == 200 and d["storyboard"]["shots"][0]["status"] == "redo"


def test_post_shot_400s_with_the_contract_s_own_message(tmp_path: Path):
    """A rejected edit must name the real cause: the page shows this verbatim."""
    runs = tmp_path / "runs"
    make_run(runs)
    with serving(runs) as base:
        code, d = call(base, "/api/shot", {"job": "sb-test", "index": 0,
                                           "status": "nope"})
        assert code == 400
        assert d["error"] == ("unknown status 'nope'; allowed: planned, "
                              "images_ready, redo, approved, done")
        code, d = call(base, "/api/shot", {"job": "sb-test", "index": 0,
                                           "status": "approved"})
        assert code == 400
        assert d["error"] == "approving an image-first shot needs a chosen candidate"
        code, d = call(base, "/api/shot", {"job": "sb-test", "index": 0, "chosen": 9})
        assert code == 400 and d["error"] == "chosen must be an int in 0..1"
        code, d = call(base, "/api/shot", {"job": "sb-test", "index": 7,
                                           "status": "approved"})
        assert code == 400 and d["error"] == "no shot 7"
        code, d = call(base, "/api/shot", {"job": "sb-test", "index": 0,
                                           "gen_seconds": 12})
        assert code == 400 and "editable fields" in d["error"]
        code, d = call(base, "/api/shot", {"job": "ghost", "index": 0,
                                           "status": "approved"})
        assert code == 400 and d["error"] == "no storyboard yet — run the job first"
