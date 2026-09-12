"""Attended review gate: candidates are scored by a vision-capable reviewer
(normally the Claude Code session driving the run), never by the generator
itself — different judge and generator avoids preference leakage.
"""

import json
from pathlib import Path

RUBRIC = {
    "subject_separation": "Is the subject cleanly separated from the background (no melting)?",
    "perceived_contrast": "Does the frame read as high-contrast and visually striking?",
    "composition": "Is the composition intentional (subject placement, leading lines)?",
    "intent_match": "Does it match the shot brief?",
}

INSTRUCTIONS = (
    "Score each candidate 1-5 per rubric key, pick `chosen` (candidate index) per shot, "
    "and optionally set `revise_prompt` to a full replacement prompt to regenerate that "
    "shot's keyframes. Write the result to review.json next to this file."
)


def write_request(workdir: Path, shots: list[dict]) -> Path:
    req = {"rubric": RUBRIC, "instructions": INSTRUCTIONS, "shots": shots}
    path = workdir / "review_request.json"
    path.write_text(json.dumps(req, indent=2))
    return path


def load_review(workdir: Path) -> dict | None:
    path = workdir / "review.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def auto_review(shots: list[dict]) -> dict:
    """Fallback for --auto / dry runs: first candidate wins."""
    return {str(s["index"]): {"chosen": 0} for s in shots}


def record_winner(library: Path, entry: dict) -> None:
    """Append a winning prompt to the shared prompt bank (jsonl)."""
    library.parent.mkdir(parents=True, exist_ok=True)
    with open(library, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
