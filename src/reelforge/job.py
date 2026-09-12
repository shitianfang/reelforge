"""Job specs (yaml in, validated dataclass out) and resumable run state.

Spend control has two layers, both enforced before each paid call:
- per-job `budget_usd` from the job file;
- a machine-wide cap in <runs>/limits.json, editable from the dashboard.
Every spend is appended to <runs>/ledger.jsonl for the dashboard's totals.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import ASPECTS, RESOLUTIONS
from .promptcraft import STYLES, ShotBrief

DEFAULT_GLOBAL_CAP = 5.0


@dataclass
class MusicSpec:
    prompt: str
    duration_s: int = 30
    lyrics: str = ""


@dataclass
class JobSpec:
    name: str
    style: str
    shots: list[ShotBrief]
    music: MusicSpec
    aspect: str = "9:16"
    flow: str = "image-first"      # image-first | direct (text-to-video, no review)
    image_quality: str = "fast"    # fast (Z-Image Turbo) | high (Seedream 5 Lite)
    resolution: str = "768P"       # 480P | 768P | 1080P
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
    checks = [
        ("style", raw.get("style"), STYLES),
        ("aspect", raw.get("aspect", "9:16"), ASPECTS),
        ("flow", raw.get("flow", "image-first"), ("image-first", "direct")),
        ("image_quality", raw.get("image_quality", "fast"), ("fast", "high")),
        ("resolution", raw.get("resolution", "768P"), RESOLUTIONS),
    ]
    for name, value, allowed in checks:
        if value is not None and value not in allowed:
            problems.append(f"unknown {name} '{value}'; allowed: {', '.join(allowed)}")
    if problems:
        raise SystemExit(f"invalid job {path}:\n  - " + "\n  - ".join(problems))
    return JobSpec(
        name=raw["name"], style=raw["style"],
        shots=[ShotBrief(**s) for s in raw["shots"]],
        music=MusicSpec(**raw["music"]),
        aspect=raw.get("aspect", "9:16"),
        flow=raw.get("flow", "image-first"),
        image_quality=raw.get("image_quality", "fast"),
        resolution=raw.get("resolution", "768P"),
        n_variants=int(raw.get("n_variants", 3)),
        budget_usd=float(raw.get("budget_usd", 3.0)),
    )


class BudgetExceeded(SystemExit):
    pass


def load_limits(runs_root: Path) -> dict:
    p = runs_root / "limits.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"global_cap_usd": DEFAULT_GLOBAL_CAP}


def save_limits(runs_root: Path, limits: dict) -> None:
    runs_root.mkdir(parents=True, exist_ok=True)
    (runs_root / "limits.json").write_text(json.dumps(limits, indent=2))


def ledger_total(runs_root: Path) -> float:
    p = runs_root / "ledger.jsonl"
    if not p.exists():
        return 0.0
    return sum(json.loads(line)["usd"] for line in p.read_text().splitlines() if line)


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

    @property
    def runs_root(self) -> Path:
        return self.path.parent.parent

    @property
    def job_name(self) -> str:
        return self.path.parent.name

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
        if self.data["cost_usd"] + usd > budget:
            self.save()
            raise BudgetExceeded(
                f"job budget ${budget:.2f} would be exceeded by {what} "
                f"(spent ${self.data['cost_usd']:.2f}, next +${usd:.2f}). "
                f"Raise budget_usd in the job file to continue.")
        global_charge(self.runs_root, self.job_name, usd, what)
        self.data["cost_usd"] += usd
        self.save()


def global_charge(runs_root: Path, job: str, usd: float, what: str) -> None:
    """Machine-wide cap check + ledger append; shared by runs and the dashboard."""
    cap = load_limits(runs_root).get("global_cap_usd", DEFAULT_GLOBAL_CAP)
    machine_total = ledger_total(runs_root)
    if machine_total + usd > cap:
        raise BudgetExceeded(
            f"machine-wide cap ${cap:.2f} would be exceeded by {what} "
            f"(all-jobs total ${machine_total:.2f}, next +${usd:.2f}). "
            f"Raise it on the dashboard or in {runs_root / 'limits.json'}.")
    runs_root.mkdir(parents=True, exist_ok=True)
    with open(runs_root / "ledger.jsonl", "a") as f:
        f.write(json.dumps({"ts": round(time.time(), 1), "job": job,
                            "what": what, "usd": round(usd, 5)}) + "\n")
