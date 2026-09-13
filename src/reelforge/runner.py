"""Manifest-driven pipeline runner: resumable, budget-capped, storyboard-gated.

Flows:
- image-first: music → beats → plan → storyboard → keyframes → approval gate →
  videos → assemble. The gate is where "approve the pictures before paying for
  video" happens (exit code 3 = shots still waiting to be approved).
- direct: music → beats → plan → storyboard → videos (text-to-video) → assemble;
  its shots are approved at build time, so there is no gate.

Two files carry the run. state.json tracks step completion and spend;
storyboard.json owns every per-shot prompt, candidate, choice and clip from the
plan step onwards — the runner reads prompts from it and never re-derives them.
Both are written after each unit of work, so an interrupt resumes per shot.

Exit codes: 0 done, 3 awaiting review, 4 budget exceeded.
"""

import argparse
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

from . import assemble as asm
from . import beats, generate, judge, storyboard
from .config import fal_key
from .fal import DryRunClient, FalClient, get_balance
from .job import BudgetExceeded, JobSpec, RunState, load_job
from .promptcraft import lint

LIBRARY = Path(__file__).resolve().parents[2] / "library" / "prompts.jsonl"


def estimate_total(spec: JobSpec) -> float:
    """Rough full-job estimate for the dashboard, before a plan exists.

    Timeline ≈ music duration; each shot is generated ~1s longer than its slot.
    """
    n = len(spec.shots)
    video_s = spec.music.duration_s + n
    total = generate.est_music(spec.music.duration_s)
    total += generate.est_video(video_s, spec.resolution)
    if spec.flow == "image-first":
        total += generate.est_image(spec.size, spec.image_quality, n * spec.n_variants)
    return round(total, 3)


def _next_attempt(assets: Path, index: int) -> int:
    """Every keyframe regeneration writes to fresh filenames (kf_<shot>_a<n>_<v>),
    so nothing viewing this run — dashboard, browser cache — can show a stale
    candidate after a redo."""
    seen = [int(m.group(1)) for p in assets.glob(f"kf_{index}_a*_*.png")
            if (m := re.fullmatch(rf"kf_{index}_a(\d+)_\d+\.png", p.name))]
    return max(seen, default=0) + 1


def _record_winners(state: RunState, spec: JobSpec, sb: dict) -> None:
    """Approved image-first picks feed the shared prompt bank, once per pick."""
    logged = state.data.setdefault("prompt_bank", {})
    for s in sb["shots"]:
        if s.get("chosen") is None:
            continue
        chosen = s["candidates"][s["chosen"]]
        if logged.get(str(s["index"])) == chosen:
            continue
        judge.record_winner(LIBRARY, {"job": spec.name, "style": spec.style,
                                      "prompt": s["image_prompt"], "chosen": chosen})
        logged[str(s["index"])] = chosen
    state.save()


def run_job(spec: JobSpec, workdir: Path, client, auto: bool,
            job_file: str | None = None) -> int:
    workdir.mkdir(parents=True, exist_ok=True)
    assets = workdir / "assets"
    assets.mkdir(exist_ok=True)
    state = RunState.load(workdir)
    if "spec" not in state.data:
        state.data["spec"] = asdict(spec)
        state.data["estimate_usd"] = estimate_total(spec)
        if job_file:  # lets the dashboard's "continue" button re-invoke this job
            state.data["job_file"] = job_file
        state.save()
    log = lambda msg: print(f"[{spec.name}] {msg}")

    # 1. music first: the beat grid is the timing authority for everything else
    if not state.done("music"):
        state.spend(generate.est_music(spec.music.duration_s), spec.budget_usd, "music")
        path = generate.gen_music(client, spec.music.prompt, spec.music.duration_s,
                                  assets / "music.wav", lyrics=spec.music.lyrics)
        state.mark("music", str(path))
        log(f"music -> {path}")

    # 2. beat analysis
    if not state.done("beats"):
        grid = beats.analyze(state.done("music"))
        state.mark("beats", {"bpm": grid.bpm, "beat_times": grid.beat_times,
                             "duration": grid.duration, "drop_time": grid.drop_time})
        log(f"beats: {grid.bpm:.0f} bpm, {len(grid.beat_times)} beats, drop={grid.drop_time}")

    # 3. shot plan on the grid
    if not state.done("plan"):
        g = state.done("beats")
        grid = beats.BeatGrid(bpm=g["bpm"], beat_times=g["beat_times"],
                              duration=g["duration"], drop_time=g["drop_time"])
        plan = beats.plan_shots(grid, n_shots=len(spec.shots))
        state.mark("plan", [{"index": s.index, "start": s.start, "end": s.end,
                             "gen_seconds": s.gen_seconds, "on_drop": s.on_drop}
                            for s in plan])
        log(f"plan: {len(plan)} shots, cuts on beats at "
            + ", ".join(f"{s.end:.2f}s" for s in plan))

    plan = state.done("plan")
    briefs = [spec.shots[s["index"] % len(spec.shots)] for s in plan]

    # 4. storyboard: prompts + per-shot estimates, visible before anything renders.
    #    Written once; from here on it is the source of truth and an existing one
    #    is never overwritten — it holds the edits made between runs.
    sb = storyboard.load(workdir)
    if sb is None:
        sb = storyboard.build(spec, plan, briefs)
        # A run that already rendered clips (one started before this file
        # existed) adopts them, so nothing paid for is generated twice.
        for shot, clip in zip(sb["shots"], state.done("videos") or []):
            if clip and Path(clip).exists():
                shot["video"], shot["status"] = clip, "done"
        storyboard.save(workdir, sb)
        log(f"storyboard -> {storyboard.path(workdir)} ({len(sb['shots'])} shots)")

    if spec.flow == "image-first":
        # 5. keyframe candidates, per shot ("planned" = new, "redo" = prompt edited)
        for shot in [s for s in sb["shots"] if s["status"] in ("planned", "redo")]:
            i = shot["index"]
            if bad := lint(shot["image_prompt"]):
                raise SystemExit(f"prompt lint failed for shot {i}: banned words {bad}")
            attempt = _next_attempt(assets, i)
            candidates = []
            for v in range(spec.n_variants):
                state.spend(generate.est_image(spec.size, spec.image_quality),
                            spec.budget_usd, f"keyframe {i}v{v}")
                candidates.append(str(generate.gen_image(
                    client, shot["image_prompt"], spec.size,
                    assets / f"kf_{i}_a{attempt}_{v}.png",
                    variant=(attempt - 1) * spec.n_variants + v,
                    quality=spec.image_quality)))
            shot["candidates"] = candidates
            shot["chosen"] = None          # a redo's old pick no longer exists
            shot["status"] = "images_ready"
            if shot["video"]:              # redo after rendering: that clip is void
                shot["video"] = None
                state.clear("videos")
                state.clear("assemble")
            storyboard.save(workdir, sb)   # per shot, so an interrupt resumes here
            log(f"keyframes shot {i}: {len(candidates)} candidates (attempt {attempt})")
        if all(s["candidates"] for s in sb["shots"]):
            state.mark("keyframes", {"shots": len(sb["shots"]),
                                     "candidates": sum(len(s["candidates"])
                                                       for s in sb["shots"])})

        # 6. approval gate: no video is paid for until every shot is approved
        if auto:
            storyboard.auto_approve(sb)
            storyboard.save(workdir, sb)
        elif not storyboard.all_approved(sb):
            pending = [s for s in sb["shots"] if s["status"] not in ("approved", "done")]
            log(f"awaiting review: {len(pending)}/{len(sb['shots'])} shots not approved ("
                + ", ".join(f"#{s['index']} {s['status']}" for s in pending) + ")")
            log(f"  edit {storyboard.path(workdir)} (image_prompt / chosen / status), or")
            log(f"  uv run reelforge shot {job_file or '<job.yaml>'} "
                "<index> --chosen <n> --approve   (--redo regenerates that shot), or")
            log("  pick candidates on the dashboard: uv run reelforge dash")
            log("then re-run the same command to continue.")
            return 3
        if not client.dry:  # placeholder prompts must not pollute the prompt bank
            _record_winners(state, spec, sb)

    # 7. videos: durations from the beat plan, prompts from the storyboard;
    #    i2v from the chosen keyframe, or t2v in the direct flow
    for shot in sb["shots"]:
        i = shot["index"]
        if shot["video"] and Path(shot["video"]).exists():
            continue
        image = None
        if spec.flow == "image-first":
            if shot["chosen"] is None:
                raise SystemExit(f"shot {i} is approved without a chosen keyframe")
            image = Path(shot["candidates"][shot["chosen"]])
        state.spend(generate.est_video(shot["gen_seconds"], spec.resolution),
                    spec.budget_usd, f"video {i}")
        p = generate.gen_video(client, shot["video_prompt"], shot["gen_seconds"],
                               spec.size, assets / f"clip_{i}.mp4",
                               image_path=image, resolution=spec.resolution,
                               variant=i)
        shot["video"] = str(p)
        shot["status"] = "done"
        storyboard.save(workdir, sb)
        log(f"video shot {i} -> {p}")
    clips = [s["video"] for s in sb["shots"]]
    if state.done("videos") != clips:
        state.mark("videos", clips)

    # 8. beat-synced assembly
    if not state.done("assemble"):
        cuts = [(Path(s["video"]), s["end"] - s["start"]) for s in sb["shots"]]
        final = asm.assemble(cuts, Path(state.done("music")),
                             workdir / "final.mp4", spec.size)
        state.mark("assemble", str(final))

    log(f"DONE  final={state.done('assemble')}  est. cost=${state.data['cost_usd']:.2f}")
    return 0


def print_storyboard(sb: dict) -> None:
    """Compact per-shot view: what each shot is waiting on, at a glance."""
    print(f"\nstoryboard ({sb['flow']}, {len(sb['shots'])} shots):")
    for s in sb["shots"]:
        chosen = s.get("chosen")
        print(f"  #{s['index']}  {s['status']:<12}"
              f"  chosen={'-' if chosen is None else chosen}"
              f"  video={'yes' if s.get('video') else 'no'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reelforge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="run a job manifest")
    p_run.add_argument("job", help="path to job yaml")
    p_run.add_argument("--dry-run", action="store_true",
                       help="no API calls: synthesize placeholder media")
    p_run.add_argument("--auto", action="store_true",
                       help="skip the approval gate (first candidate wins)")
    p_run.add_argument("--workdir", default="runs", help="output root (default: runs/)")
    p_shot = sub.add_parser("shot", help="edit one storyboard shot")
    p_shot.add_argument("job", help="path to job yaml")
    p_shot.add_argument("index", type=int, help="shot index (0-based)")
    p_shot.add_argument("--image-prompt", help="replace the keyframe prompt")
    p_shot.add_argument("--video-prompt", help="replace the video prompt")
    p_shot.add_argument("--chosen", type=int, help="winning candidate index")
    p_shot.add_argument("--notes", help="free-text note kept with the shot")
    g = p_shot.add_mutually_exclusive_group()
    g.add_argument("--approve", action="store_true", help="mark the shot approved")
    g.add_argument("--redo", action="store_true",
                   help="regenerate this shot's keyframes on the next run")
    p_shot.add_argument("--workdir", default="runs")
    p_status = sub.add_parser("status", help="show a job's run state")
    p_status.add_argument("job", help="path to job yaml")
    p_status.add_argument("--workdir", default="runs")
    sub.add_parser("balance", help="print fal.ai account balance")
    p_dash = sub.add_parser("dash", help="serve the observation dashboard")
    p_dash.add_argument("--port", type=int, default=7799)
    p_dash.add_argument("--host", default="127.0.0.1",
                        help="bind address; 0.0.0.0 exposes the dashboard "
                             "(including paid generation) to the whole network")
    p_dash.add_argument("--workdir", default="runs")
    args = ap.parse_args(argv)

    if args.cmd == "balance":
        b = get_balance(fal_key())
        print(f"${b:.2f}" if b is not None else "balance unavailable")
        return 0
    if args.cmd == "dash":
        from .dashboard import serve
        return serve(Path(args.workdir), args.port, host=args.host)

    spec = load_job(args.job)
    workdir = Path(args.workdir) / spec.name
    if args.cmd == "status":
        state = RunState.load(workdir)
        print(json.dumps(state.data, indent=2))
        if (sb := storyboard.load(workdir)) is not None:
            print_storyboard(sb)
        return 0
    if args.cmd == "shot":
        fields = {k: v for k, v in (("image_prompt", args.image_prompt),
                                    ("video_prompt", args.video_prompt),
                                    ("chosen", args.chosen),
                                    ("notes", args.notes)) if v is not None}
        if args.approve:
            fields["status"] = "approved"
        if args.redo:
            fields["status"] = "redo"
        try:
            sb = storyboard.update_shot(workdir, args.index, fields)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(json.dumps(storyboard.get_shot(sb, args.index), indent=2,
                         ensure_ascii=False))
        return 0
    client = DryRunClient() if args.dry_run else FalClient(fal_key())
    try:
        return run_job(spec, workdir, client, auto=args.auto,
                       job_file=str(Path(args.job).resolve()))
    except BudgetExceeded as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
