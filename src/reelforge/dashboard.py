"""Local observation + playground console (serves on 127.0.0.1 only).

Read side: balance, ledger totals, spend caps, every run's state and assets.
Act side: playground generations (image/video/music, model of choice, free or
recipe-composed prompts), picking review candidates, continuing a gated job.
All playground spends go through the same machine-wide cap as batch runs.
"""

import json
import mimetypes
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import generate
from .config import DISCOUNT_DEADLINE, FAL_MODELS, PRICES, RESOLUTIONS, fal_key
from .fal import FalClient, get_balance
from .job import (BudgetExceeded, global_charge, ledger_total, load_limits,
                  save_limits)
from .promptcraft import STYLES, ShotBrief, image_prompt, lint, video_prompt

HTML = Path(__file__).parent / "dashboard.html"

MODEL_INFO = [
    {"id": "image_fast", "kind": "image", "endpoint": FAL_MODELS["image_fast"],
     "label": "Z-Image Turbo(图片·草稿档)", "price": "$0.005/百万像素,一张竖屏草稿约 ¥0.03",
     "pros": "便宜到可以随便试、约 3 秒出图、真实感不错",
     "cons": "细节和文字渲染不如高档模型,大图偶尔糊",
     "usage": "默认就用它:一个想法先生 3~5 张挑,不心疼钱"},
    {"id": "image_high", "kind": "image", "endpoint": FAL_MODELS["image_high"],
     "label": "Seedream 5 Lite(图片·质量档)", "price": "$0.035/张(约 ¥0.25)",
     "pros": "商业海报质感、画面里写字最准、最高 3072² 大图",
     "cons": "比草稿档贵 7 倍,速度稍慢",
     "usage": "草稿档挑中构图后,同一段提示词换它出正式版"},
    {"id": "video_t2v", "kind": "video", "endpoint": FAL_MODELS["video_t2v"],
     "label": "H3 视频·文字直接生成", "price": "480P $0.00625/秒 · 768P $0.01/秒 · 1080P $0.02/秒",
     "pros": "一句话直接出带声音的视频,最省事",
     "cons": "画面不可控,同一句话每次结果差很多",
     "usage": f"试想法用 480P + 4~5 秒(不到 ¥0.25);⚠ 折扣 {DISCOUNT_DEADLINE} 到期后涨 4 倍"},
    {"id": "video_i2v", "kind": "video", "endpoint": FAL_MODELS["video_i2v"],
     "label": "H3 视频·从图片生成", "price": "同左",
     "pros": "画面=你选中的那张图,构图颜色完全可控,系列内容主角不走样",
     "cons": "要先有一张满意的图,多一步",
     "usage": "正经做内容走这条:图便宜先挑好,再花视频的钱"},
    {"id": "music", "kind": "music", "endpoint": FAL_MODELS["music"],
     "label": "MiniMax Music 3(配乐)", "price": "$0.002/秒,30 秒约 ¥0.43",
     "pros": "便宜,描述曲风即可,可写歌词",
     "cons": "不能指定精确 BPM,节拍靠系统检测",
     "usage": "批量任务会自动先生成音乐再卡点;单独试听在试玩台选\"音乐\""},
]

STYLE_INFO = {
    "contrast-noir": "黑色电影风:顶光硬打、深黑背景、橙青撞色 — 高级感产品/人物",
    "rim-glow": "轮廓光风:背后打光勾出发光边缘 — 手表、数码、深色产品特写",
    "neon-street": "赛博霓虹街头:品红+青色霓虹、湿地反光 — 宠物/人物动作戏",
    "pov-pet": "宠物第一视角:胸背带运动相机、鱼眼、抖动 — 爆款宠物 POV",
    "pov-vlog": "角色自拍 vlog:自拍杆视角 — 雪人/怪物对镜头说话那类爆款",
}

_balance = {"t": 0.0, "v": None}


def balance_cached() -> float | None:
    if time.time() - _balance["t"] > 30:
        try:
            _balance["v"] = get_balance(fal_key())
        except SystemExit:
            _balance["v"] = None
        _balance["t"] = time.time()
    return _balance["v"]


def playground_estimate(req: dict) -> float:
    kind = req["kind"]
    if kind == "image":
        return generate.est_image((int(req.get("width", 720)), int(req.get("height", 1280))),
                                  "high" if req.get("model") == "image_high" else "fast")
    if kind == "video":
        return generate.est_video(int(req.get("duration", 5)),
                                  req.get("resolution", "768P"))
    if kind == "music":
        return generate.est_music(int(req.get("duration", 30)))
    raise ValueError(f"unknown kind {kind}")


class Playground:
    def __init__(self, runs_root: Path):
        self.dir = runs_root / "playground"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.runs_root = runs_root
        self.log = self.dir / "log.jsonl"
        self.lock = threading.Lock()
        self.tasks: dict[str, dict] = {}
        if self.log.exists():
            for line in self.log.read_text().splitlines():
                if line:
                    rec = json.loads(line)
                    self.tasks[rec["id"]] = rec  # last line per id wins
        for rec in self.tasks.values():
            if rec["status"] == "running":  # server restarted mid-task
                rec["status"] = "failed"
                rec["error"] = "server restarted"

    def _persist(self, rec: dict) -> None:
        with self.lock:
            self.tasks[rec["id"]] = rec
            with open(self.log, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def submit(self, req: dict) -> dict:
        kind = req["kind"]
        prompt = (req.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt is empty")
        est = playground_estimate(req)
        global_charge(self.runs_root, "playground", est, f"playground {kind}")
        ext = {"image": "png", "video": "mp4", "music": "wav"}[kind]
        rec = {
            "id": uuid.uuid4().hex[:10], "ts": round(time.time(), 1),
            "kind": kind, "prompt": prompt, "est_usd": round(est, 4),
            "status": "running", "file": None,
            "params": {k: req[k] for k in
                       ("model", "width", "height", "duration", "resolution",
                        "source_image", "lyrics") if k in req},
        }
        rec["file"] = f"playground/{rec['id']}.{ext}"
        self._persist(rec)
        threading.Thread(target=self._work, args=(rec,), daemon=True).start()
        return rec

    def _work(self, rec: dict) -> None:
        rec = dict(rec)
        try:
            client = FalClient(fal_key())
            dest = self.runs_root / rec["file"]
            p, kind = rec["params"], rec["kind"]
            if kind == "image":
                generate.gen_image(client, rec["prompt"],
                                   (int(p.get("width", 720)), int(p.get("height", 1280))),
                                   dest,
                                   quality="high" if p.get("model") == "image_high" else "fast")
            elif kind == "video":
                src = p.get("source_image")
                image = self.runs_root / src if src else None
                if image is not None and not image.exists():
                    raise FileNotFoundError(f"source image {src} not found")
                generate.gen_video(client, rec["prompt"], int(p.get("duration", 5)),
                                   (0, 0), dest, image_path=image,
                                   resolution=p.get("resolution", "768P"))
            else:
                generate.gen_music(client, rec["prompt"], int(p.get("duration", 30)),
                                   dest, lyrics=p.get("lyrics", ""))
            rec["status"] = "done"
        except Exception as e:  # surfaced on the card, not lost in a thread
            rec["status"] = "failed"
            rec["error"] = f"{type(e).__name__}: {e}"[:500]
        self._persist(rec)

    def list(self) -> list[dict]:
        return sorted(self.tasks.values(), key=lambda r: -r["ts"])


def scan_jobs(runs_root: Path) -> list[dict]:
    jobs = []
    for state_path in sorted(runs_root.glob("*/state.json")):
        workdir = state_path.parent
        if workdir.name == "playground":
            continue
        state = json.loads(state_path.read_text())
        done = state.get("done", {})
        jobs.append({
            "name": workdir.name,
            "spec": state.get("spec"),
            "estimate_usd": state.get("estimate_usd"),
            "cost_usd": state.get("cost_usd", 0.0),
            "steps": list(done.keys()),
            "plan": done.get("plan"),
            "beats": {k: v for k, v in (done.get("beats") or {}).items()
                      if k != "beat_times"},
            "final": done.get("assemble"),
            "awaiting_review": (workdir / "review_request.json").exists()
                               and not (workdir / "review.json").exists(),
            "job_file": state.get("job_file"),
        })
    return jobs


def job_detail(runs_root: Path, name: str) -> dict:
    workdir = runs_root / name
    out = {"name": name}
    sp = workdir / "state.json"
    if sp.exists():
        out["state"] = json.loads(sp.read_text())
    for f, key in (("review_request.json", "review_request"), ("review.json", "review")):
        p = workdir / f
        if p.exists():
            out[key] = json.loads(p.read_text())
    log = workdir / "run.log"
    if log.exists():
        out["run_log_tail"] = log.read_text()[-3000:]
    return out


RUNNING: dict[str, subprocess.Popen] = {}


def continue_job(runs_root: Path, name: str) -> str:
    proc = RUNNING.get(name)
    if proc and proc.poll() is None:
        return "already running"
    job_file = json.loads((runs_root / name / "state.json").read_text()).get("job_file")
    if not job_file or not Path(job_file).exists():
        return "job_file unknown; run it from the CLI once"
    log = open(runs_root / name / "run.log", "a")
    RUNNING[name] = subprocess.Popen(
        [sys.executable, "-m", "reelforge", "run", job_file, "--workdir", str(runs_root)],
        stdout=log, stderr=subprocess.STDOUT)
    return "started"


def make_handler(runs_root: Path, playground: Playground):
    root = runs_root.resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the terminal quiet
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            try:
                if self.path in ("/", "/index.html"):
                    body = HTML.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/api/summary":
                    self._json({
                        "balance": balance_cached(),
                        "spent": round(ledger_total(root), 4),
                        "limits": load_limits(root),
                        "prices": PRICES,
                        "discount_deadline": DISCOUNT_DEADLINE,
                        "resolutions": list(RESOLUTIONS),
                        "models": MODEL_INFO,
                        "styles": {k: v for k, v in STYLES.items()},
                        "style_info": STYLE_INFO,
                        "jobs": scan_jobs(root),
                        "playground": playground.list()[:60],
                    })
                elif self.path.startswith("/api/job/"):
                    self._json(job_detail(root, unquote(self.path[9:])))
                elif self.path.startswith("/files/"):
                    self._serve_file(unquote(self.path[7:]))
                else:
                    self._json({"error": "not found"}, 404)
            except BrokenPipeError:
                pass
            except Exception as e:
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def do_POST(self):
            try:
                req = self._read_body()
                if self.path == "/api/generate":
                    self._json(playground.submit(req))
                elif self.path == "/api/compose":
                    brief = ShotBrief(subject=req.get("subject", ""),
                                      action=req.get("action", ""),
                                      scene=req.get("scene", ""))
                    fn = image_prompt if req.get("kind") == "image" else video_prompt
                    kwargs = {} if req.get("kind") == "image" else \
                        {"on_drop": bool(req.get("on_drop"))}
                    prompt = fn(brief, req.get("style", "contrast-noir"), **kwargs)
                    self._json({"prompt": prompt, "warnings": lint(prompt)})
                elif self.path == "/api/limits":
                    cap = float(req["global_cap_usd"])
                    save_limits(root, {"global_cap_usd": cap})
                    self._json({"ok": True, "global_cap_usd": cap})
                elif self.path == "/api/review":
                    name = re.sub(r"[^\w.-]", "", req["job"])
                    chosen = {str(k): {"chosen": int(v)}
                              for k, v in req["chosen"].items()}
                    (root / name / "review.json").write_text(json.dumps(chosen, indent=2))
                    self._json({"ok": True})
                elif self.path == "/api/continue":
                    name = re.sub(r"[^\w.-]", "", req["job"])
                    self._json({"result": continue_job(root, name)})
                else:
                    self._json({"error": "not found"}, 404)
            except BudgetExceeded as e:
                self._json({"error": str(e)}, 402)
            except Exception as e:
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def _serve_file(self, rel: str):
            target = (root / rel).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                self._json({"error": "not found"}, 404)
                return
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            data = target.read_bytes()
            rng = self.headers.get("Range")
            if rng:  # minimal single-range support so <video> can seek
                m = re.match(r"bytes=(\d*)-(\d*)", rng)
                start = int(m.group(1) or 0)
                end = int(m.group(2) or len(data) - 1)
                end = min(end, len(data) - 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                chunk = data[start:end + 1]
            else:
                self.send_response(200)
                chunk = data
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)

    return Handler


def serve(runs_root: Path, port: int) -> int:
    runs_root.mkdir(parents=True, exist_ok=True)
    playground = Playground(runs_root)
    httpd = ThreadingHTTPServer(("127.0.0.1", port),
                                make_handler(runs_root, playground))
    print(f"reelforge dashboard: http://127.0.0.1:{port}  (runs root: {runs_root})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
