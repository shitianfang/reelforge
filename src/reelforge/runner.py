"""Manifest-driven pipeline runner: resumable, budget-capped, review-gated.

Flows:
- image-first: music → beats → plan → keyframes → review → videos → assemble.
  The review gate is where "approve the pictures before paying for video"
  happens (exit code 3 = awaiting review.json).
- direct: music → beats → plan → videos (text-to-video) → assemble.
State survives interruption; re-running continues where it left off.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import assemble as asm
from . import beats, generate, judge
from .config import DISCOUNT_DEADLINE, PRICES, fal_key
from .fal import DryRunClient, FalClient, get_balance
from .job import BudgetExceeded, JobSpec, RunState, load_job
from .promptcraft import image_prompt, lint, video_prompt

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

    if spec.flow == "image-first":
        # 4. keyframe candidates per shot
        if not state.done("keyframes"):
            keyframes = []
            for s, brief in zip(plan, briefs):
                prompt = image_prompt(brief, spec.style)
                if bad := lint(prompt):
                    raise SystemExit(f"prompt lint failed for shot {s['index']}: banned words {bad}")
                candidates = []
                for v in range(spec.n_variants):
                    state.spend(generate.est_image(spec.size, spec.image_quality),
                                spec.budget_usd, f"keyframe {s['index']}v{v}")
                    p = generate.gen_image(client, prompt, spec.size,
                                           assets / f"kf_{s['index']}_{v}.png",
                                           variant=v, quality=spec.image_quality)
                    candidates.append(str(p))
                keyframes.append({"index": s["index"], "prompt": prompt,
                                  "candidates": candidates})
            state.mark("keyframes", keyframes)
            log(f"keyframes: {sum(len(k['candidates']) for k in keyframes)} candidates")

        # 5. review gate (attended by default; --auto or dry-run picks first)
        if not state.done("review"):
            keyframes = state.done("keyframes")
            review = judge.load_review(workdir)
            if review is None:
                if auto:
                    review = judge.auto_review(keyframes)
                else:
                    req = judge.write_request(workdir, keyframes)
                    log(f"awaiting review: score candidates per {req}, write review.json, re-run")
                    return 3
            revised = [k for k in keyframes
                       if review.get(str(k["index"]), {}).get("revise_prompt")]
            if revised:
                # Regenerate revised shots' keyframes, then review again.
                for k in revised:
                    k["prompt"] = review[str(k["index"])]["revise_prompt"]
                state.mark("keyframes", keyframes)  # keep revised prompts
                state.clear("review")
                (workdir / "review.json").unlink()
                for k in revised:
                    for v in range(spec.n_variants):
                        state.spend(generate.est_image(spec.size, spec.image_quality),
                                    spec.budget_usd, f"revised keyframe {k['index']}v{v}")
                        generate.gen_image(client, k["prompt"], spec.size,
                                           assets / f"kf_{k['index']}_{v}.png",
                                           variant=v, quality=spec.image_quality)
                log(f"regenerated {len(revised)} revised shots; review again")
                return 3
            chosen = {k["index"]: k["candidates"][review[str(k["index"])]["chosen"]]
                      for k in keyframes}
            state.mark("review", {str(i): c for i, c in chosen.items()})
            if not client.dry:  # placeholder prompts must not pollute the prompt bank
                for k in keyframes:
                    judge.record_winner(LIBRARY, {"job": spec.name, "style": spec.style,
                                                  "prompt": k["prompt"],
                                                  "chosen": chosen[k["index"]]})

    # 6. videos: durations from the beat plan; i2v from chosen keyframes,
    #    or t2v straight from prompts in the direct flow
    if not state.done("videos"):
        chosen = state.done("review") if spec.flow == "image-first" else {}
        clips = []
        for s, brief in zip(plan, briefs):
            prompt = video_prompt(brief, spec.style, on_drop=s["on_drop"])
            state.spend(generate.est_video(s["gen_seconds"], spec.resolution),
                        spec.budget_usd, f"video {s['index']}")
            image = Path(chosen[str(s["index"])]) if chosen else None
            p = generate.gen_video(client, prompt, s["gen_seconds"], spec.size,
                                   assets / f"clip_{s['index']}.mp4",
                                   image_path=image, resolution=spec.resolution,
                                   variant=s["index"])
            clips.append(str(p))
        state.mark("videos", clips)
        log(f"videos: {len(clips)} clips")

    # 7. beat-synced assembly
    if not state.done("assemble"):
        clips = [(Path(c), s["end"] - s["start"])
                 for c, s in zip(state.done("videos"), plan)]
        final = asm.assemble(clips, Path(state.done("music")),
                             workdir / "final.mp4", spec.size)
        state.mark("assemble", str(final))

    log(f"DONE  final={state.done('assemble')}  est. cost=${state.data['cost_usd']:.2f}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reelforge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="run a job manifest")
    p_run.add_argument("job", help="path to job yaml")
    p_run.add_argument("--dry-run", action="store_true",
                       help="no API calls: synthesize placeholder media")
    p_run.add_argument("--auto", action="store_true",
                       help="skip the attended review gate (first candidate wins)")
    p_run.add_argument("--workdir", default="runs", help="output root (default: runs/)")
    p_status = sub.add_parser("status", help="show a job's run state")
    p_status.add_argument("job", help="path to job yaml")
    p_status.add_argument("--workdir", default="runs")
    sub.add_parser("balance", help="print fal.ai account balance")
    p_dash = sub.add_parser("dash", help="serve the observation dashboard")
    p_dash.add_argument("--port", type=int, default=7799)
    p_dash.add_argument("--workdir", default="runs")
    args = ap.parse_args(argv)

    if args.cmd == "balance":
        b = get_balance(fal_key())
        print(f"${b:.2f}" if b is not None else "balance unavailable")
        return 0
    if args.cmd == "dash":
        from .dashboard import serve
        return serve(Path(args.workdir), args.port)

    spec = load_job(args.job)
    workdir = Path(args.workdir) / spec.name
    if args.cmd == "status":
        state = RunState.load(workdir)
        print(json.dumps(state.data, indent=2))
        return 0
    client = DryRunClient() if args.dry_run else FalClient(fal_key())
    try:
        return run_job(spec, workdir, client, auto=args.auto or args.dry_run,
                       job_file=str(Path(args.job).resolve()))
    except BudgetExceeded as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
