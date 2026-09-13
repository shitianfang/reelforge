"""Storyboard: the per-shot creative plan sitting between planning and paid
rendering — the file a human or agent edits shot by shot until satisfied.

Once the beat plan exists it is the single source of truth for prompts: the
runner writes it right after planning (so the dashboard can show what WILL be
generated before anything renders), attaches keyframe candidates as they
finish, and reads prompts/choices back from it when rendering video. The
dashboard and any driving agent (Claude Code, Codex, ...) edit it only through
update_shot, which validates fields so a bad edit fails at write time, not at
spend time.

Shot status lifecycle (image-first flow):

    planned -> images_ready -> approved -> done
                  ^   |
                  |   v
                  redo   (prompt edited; that shot's keyframes regenerate)

Direct-flow shots skip images: planned -> approved -> done, auto-approved at
build time since there is nothing to review before the video exists.
"""

import json
from pathlib import Path

from . import generate
from .promptcraft import image_prompt, lint, video_prompt

FILENAME = "storyboard.json"
EDITABLE = {"image_prompt", "video_prompt", "chosen", "status", "notes"}
STATUSES = ("planned", "images_ready", "redo", "approved", "done")


def path(workdir: Path) -> Path:
    return Path(workdir) / FILENAME


def load(workdir: Path) -> dict | None:
    p = path(workdir)
    return json.loads(p.read_text()) if p.exists() else None


def save(workdir: Path, sb: dict) -> None:
    path(workdir).write_text(json.dumps(sb, indent=2, ensure_ascii=False))


def build(spec, plan, briefs) -> dict:
    """Prompts + per-shot cost estimates, ready to show before anything renders."""
    shots = []
    for s, brief in zip(plan, briefs):
        shot = {
            "index": s["index"], "start": s["start"], "end": s["end"],
            "gen_seconds": s["gen_seconds"], "on_drop": s["on_drop"],
            "video_prompt": video_prompt(brief, spec.style, on_drop=s["on_drop"]),
            "est_video_usd": generate.est_video(s["gen_seconds"], spec.resolution),
            "video": None, "notes": "",
            "status": "planned" if spec.flow == "image-first" else "approved",
        }
        if spec.flow == "image-first":
            shot["image_prompt"] = image_prompt(brief, spec.style)
            shot["est_images_usd"] = generate.est_image(
                spec.size, spec.image_quality, spec.n_variants)
            shot["candidates"] = []
            shot["chosen"] = None
        shots.append(shot)
    return {"version": 1, "job": spec.name, "flow": spec.flow, "shots": shots}


def get_shot(sb: dict, index: int) -> dict:
    shot = next((s for s in sb["shots"] if s["index"] == index), None)
    if shot is None:
        raise ValueError(f"no shot {index}")
    return shot


def update_shot(workdir: Path, index: int, fields: dict) -> dict:
    """Validated edit endpoint shared by the dashboard, CLI and driving agents."""
    sb = load(workdir)
    if sb is None:
        raise ValueError("no storyboard yet — run the job first")
    shot = get_shot(sb, index)
    if unknown := set(fields) - EDITABLE:
        raise ValueError(f"not editable: {', '.join(sorted(unknown))}")
    for key in ("image_prompt", "video_prompt"):
        if key in fields:
            text = str(fields[key]).strip()
            if not text:
                raise ValueError(f"{key} must not be empty")
            if bad := lint(text):
                raise ValueError(f"{key} contains banned words: {', '.join(bad)}")
            fields[key] = text
    if fields.get("status") is not None and fields["status"] not in STATUSES:
        raise ValueError(
            f"unknown status '{fields['status']}'; allowed: {', '.join(STATUSES)}")
    if fields.get("chosen") is not None:
        n = len(shot.get("candidates") or [])
        if not (isinstance(fields["chosen"], int) and 0 <= fields["chosen"] < n):
            raise ValueError(f"chosen must be an int in 0..{n - 1}")
    chosen_after = fields.get("chosen", shot.get("chosen"))
    if fields.get("status") == "approved" and "candidates" in shot \
            and chosen_after is None:
        raise ValueError("approving an image-first shot needs a chosen candidate")
    shot.update(fields)
    # Editing a prompt after keyframes exist implies a redo unless stated.
    if "image_prompt" in fields and "status" not in fields and shot.get("candidates"):
        shot["status"] = "redo"
    save(workdir, sb)
    return sb


def all_approved(sb: dict) -> bool:
    return all(s["status"] in ("approved", "done") for s in sb["shots"])


def auto_approve(sb: dict) -> None:
    """--auto runs: first candidate wins, every shot approved."""
    for s in sb["shots"]:
        if "candidates" in s and s.get("chosen") is None and s["candidates"]:
            s["chosen"] = 0
        if s["status"] != "done":
            s["status"] = "approved"
