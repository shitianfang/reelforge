"""Prompt bank: the prompts that actually won a review, kept for reuse.

Choosing happens in the storyboard (storyboard.py) — a human or the driving
agent picks the winning candidate per shot. When a run then proceeds past the
approval gate, the winning image prompt is appended here, so later jobs can
start from prompts that were judged good rather than from scratch.
"""

import json
from pathlib import Path


def record_winner(library: Path, entry: dict) -> None:
    """Append a winning prompt to the shared prompt bank (jsonl)."""
    library.parent.mkdir(parents=True, exist_ok=True)
    with open(library, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
