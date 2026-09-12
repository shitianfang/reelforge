# reelforge

Fully automated, batch AI short-video pipeline, built to be driven by an AI
agent (Claude Code) end to end: music-first beat grids, researched prompt
recipes for high-contrast visuals, a scored review loop, fal.ai generation,
and frame-accurate beat-synced assembly with ffmpeg.

一条全自动批量 AI 短视频流水线:音乐先行拿到节拍网格 → 按拍规划镜头 →
高对比度提示词配方生成关键帧 → 评分闭环选优 → 图生视频 → 卡点剪辑成片。

## How it works

```
job.yaml ─► music (MiniMax Music) ─► beat grid + drop detection (librosa)
        ─► shot plan: every cut is a beat, drop gets the action peak
        ─► keyframes (Seedream 4.5) × N variants per shot
        ─► review gate: vision judge scores candidates, can revise prompts
        ─► video (MiniMax H3 image-to-video), durations from the beat plan
        ─► ffmpeg trim-to-beat + concat + music mux ─► final.mp4
```

Two design rules the pipeline enforces:

1. **Music first.** The beat grid is the single timing authority. Shot lengths
   are planned as beat-aligned slots *before* any video is generated, and each
   clip is generated slightly longer than its slot so the trim always lands
   exactly on a beat. Syncing after the fact is a losing game.
2. **Judge ≠ generator.** Keyframe candidates are scored by a vision-capable
   reviewer (the Claude Code session driving the run) against a fixed rubric,
   never by the generating model — avoiding preference leakage. Winning
   prompts accumulate in `library/prompts.jsonl` as a reusable prompt bank.

## Quickstart

```bash
uv sync
uv run pytest                      # no keys needed
uv run reelforge run jobs/examples/beatcut.yaml --dry-run   # full pipeline, placeholder media
```

Live runs need one key ([fal.ai](https://fal.ai/dashboard/keys)):

```bash
export FAL_KEY=...
uv run reelforge run jobs/examples/pet-pov.yaml
# exit code 3 = awaiting review: score runs/<name>/review_request.json
# candidates, write review.json, re-run to continue. Or pass --auto.
uv run reelforge status jobs/examples/pet-pov.yaml
```

Before the first live run, confirm the endpoint slugs in
`src/reelforge/config.py` against https://fal.ai/explore (marked `VERIFY`).

## Job spec

```yaml
name: neon-cat-demo        # run directory name
style: neon-street         # prompt recipe: contrast-noir | rim-glow | neon-street | pov-pet | pov-vlog
aspect: "9:16"             # 9:16 | 16:9 | 1:1
budget_usd: 3.0            # hard cap; the run stops before exceeding it
n_variants: 3              # keyframe candidates per shot
music:
  prompt: "dark aggressive phonk, 130 bpm, hard-hitting drop"
  duration_s: 30
shots:                     # one entry per shot; subject is the anchor —
  - subject: "a black cat with amber eyes"   # keep it verbatim across shots
    action: "sprinting toward the camera"
    scene: "narrow alley walls streaked with magenta neon"
```

## Prompt recipes

The recipes in `src/reelforge/promptcraft.py` encode published guidance rather
than vibes: subject-first ordering with one hard light source and plain-word
chromatic contrast ([Hailuo visual-contrast guide](https://hailuoai.video/pages/knowledge/visual-contrast-ai-video-subjects-guide)),
lens terms to mask generation noise, an identical 5–7 word subject anchor
across a sequence, and — for POV formats — stating where the camera is
physically mounted instead of saying "POV"
([viral AI vlog teardown](https://trending.knowyourmeme.com/editorials/guides/what-are-the-ai-bigfoot-and-yeti-vlogs-and-how-are-people-making-them-the-viral-ai-video-trend-on-tiktok-explained)).
A lint step rejects the vague words that measurably hurt output.

## Cost model

Estimates per finished 30s 9:16 reel at current fal.ai prices (launch-discount
era, verify): music ≈ $0.06, keyframes 4×3 ≈ $0.48, video ≈ $0.5–1.5 depending
on tier. The ledger in each run's `state.json` tracks estimated spend and the
run refuses to exceed `budget_usd`.

## Provider pluggability

`src/reelforge/generate.py` is the only file that knows how media gets made;
`fal.py` is pure transport. A self-hosted backend (MiniMax H3 open weights on
a rented GPU via ComfyUI) can implement the same three functions when the
economics favor it — see the roadmap.

## Roadmap

- Dance/motion-transfer job kind (Wan Animate / Wan-Dancer) for
  photo + source-dance viral formats
- Unattended judge mode (Anthropic API vision scoring) for cron batches
- Video-stage scoring: sample frames from draft clips, score, re-render winner
- ComfyUI backend for self-hosted H3 (AutoDL-class GPU rental)
- 2K hero-shot pass through the official MiniMax API

## License

MIT
