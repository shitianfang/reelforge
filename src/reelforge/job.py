"""Job specs (yaml in, validated dataclass out) and resumable run state."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import ASPECTS
from .promptcraft import STYLES, ShotBrief


@dataclass
class MusicSpec:
    prompt: str
    duration_s: int = 30


@dataclass
class JobSpec:
    name: str
    style: str
    shots: list[ShotBrief]
    music: MusicSpec
    aspect: str = "9:16"
    n_variants: int = 3
    budget_usd: float = 3.0

    @property
    def size(self) -> tuple[int, int]:
        return ASPECTS[self.aspect]


def load_job(path) -> JobSpec:
    raw = yaml.safe_load(Path(path).read_text())
    problems = []
    for key in ("name", "style", "shots", "music"):
        if key not in raw:
            problems.append(f"missing required key: {key}")
    if raw.get("style") and raw["style"] not in STYLES:
        problems.append(f"unknown style '{raw['style']}'; available: {', '.join(STYLES)}")
    if raw.get("aspect", "9:16") not in ASPECTS:
        problems.append(f"unknown aspect '{raw['aspect']}'; available: {', '.join(ASPECTS)}")
    if problems:
        raise SystemExit(f"invalid job {path}:\n  - " + "\n  - ".join(problems))
    shots = [ShotBrief(**s) for s in raw["shots"]]
    music = MusicSpec(**raw["music"])
    return JobSpec(
        name=raw["name"], style=raw["style"], shots=shots, music=music,
        aspect=raw.get("aspect", "9:16"),
        n_variants=int(raw.get("n_variants", 3)),
        budget_usd=float(raw.get("budget_usd", 3.0)),
    )


class BudgetExceeded(SystemExit):
    pass


@dataclass
class RunState:
    """Step results + cost ledger, persisted after every step for resume."""

    path: Path
    data: dict = field(default_factory=lambda: {"done": {}, "cost_usd": 0.0})

    @classmethod
    def load(cls, workdir: Path) -> "RunState":
        path = workdir / "state.json"
        if path.exists():
            return cls(path=path, data=json.loads(path.read_text()))
        return cls(path=path)

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2))

    def done(self, step: str):
        return self.data["done"].get(step)

    def mark(self, step: str, payload) -> None:
        self.data["done"][step] = payload
        self.save()

    def clear(self, step: str) -> None:
        self.data["done"].pop(step, None)
        self.save()

    def spend(self, usd: float, budget: float, what: str) -> None:
        new_total = self.data["cost_usd"] + usd
        if new_total > budget:
            self.save()
            raise BudgetExceeded(
                f"budget cap ${budget:.2f} would be exceeded by {what} "
                f"(spent ${self.data['cost_usd']:.2f}, next +${usd:.2f}). "
                f"Raise budget_usd in the job file to continue.")
        self.data["cost_usd"] = new_total
        self.save()
