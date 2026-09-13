# reelforge

An AI video tool built to be driven by a coding agent.

You describe a reel in a small YAML file; reelforge generates the music, reads
its beat grid, plans one shot per beat-aligned slot, drafts a keyframe for each
shot, and — once the shots are approved — renders the video and cuts it to the
beat with ffmpeg. Generation runs on [fal.ai](https://fal.ai).

Everything it does is a CLI command over plain files: no API to integrate, no
UI to click through. Claude Code, Codex or any CLI agent can run a job, read
the storyboard it produced, rewrite a prompt it doesn't like, regenerate one
shot, approve the rest and finish the reel — while a human watches the whole
thing happen in the dashboard and steers when they want to.

## Quickstart

```bash
uv sync
uv run reelforge run jobs/examples/direct.yaml --dry-run --auto   # placeholder media, no keys
uv run reelforge dash                                             # http://127.0.0.1:7799
```

Real runs need a fal key in `.env` at the repo root (`FAL_KEY=...`), or
exported. `--dry-run` synthesizes local placeholder media instead of calling
anything, and is how the tests and every smoke run work.

## Two ways to run a job

**Storyboard-first** (`flow: image-first`, the default) — spend on pictures
before spending on video:

```bash
uv run reelforge run jobs/examples/pet-pov.yaml
# music → beats → shot plan → storyboard.json → keyframe candidates per shot
# exit code 3: shots are waiting for approval
```

Review each shot, edit what's wrong, regenerate what you don't like, approve
what you do — then re-run the same command and the approved shots become video:

```bash
uv run reelforge shot jobs/examples/pet-pov.yaml 0 --chosen 2 --approve
uv run reelforge shot jobs/examples/pet-pov.yaml 1 \
    --image-prompt "a golden retriever with a red collar, hard rim light, ..." --redo
uv run reelforge run jobs/examples/pet-pov.yaml        # redoes shot 1, gates again
```

Keyframes are cheap (fractions of a cent each) and video is not, so the loop
can run as long as it takes. `--auto` skips the gate entirely: first candidate
per shot, straight through to the final cut.

**Direct** (`flow: direct`) — one command from manifest to finished reel,
text-to-video with no keyframe stage and no gate:

```bash
uv run reelforge run jobs/examples/direct.yaml
```

## The storyboard contract

After planning, `runs/<job>/storyboard.json` is the single source of truth for
every prompt the job will use. The runner writes it once and never overwrites
it, so edits survive between runs; it reads prompts back from it when
rendering, and records candidates, choices and finished clips into it as work
completes. Each shot looks like:

```json
{
  "index": 0, "start": 0.0, "end": 11.77, "gen_seconds": 13, "on_drop": false,
  "image_prompt": "...", "video_prompt": "...",
  "est_images_usd": 0.031, "est_video_usd": 0.13,
  "candidates": ["runs/pet-pov-demo/assets/kf_0_a1_0.png", "..."],
  "chosen": null, "video": null, "notes": "", "status": "images_ready"
}
```

Status lifecycle: `planned → images_ready → approved → done`, with
`images_ready → redo` when a prompt is edited — a redo regenerates that shot's
keyframes only (to fresh filenames, so nothing serves a stale image) and leaves
approved shots alone. Direct-flow shots skip the image stage entirely.

An agent can edit the file directly, or go through the validating endpoint,
which is the same one the dashboard uses:

```bash
uv run reelforge shot <job.yaml> <index> \
    [--image-prompt S] [--video-prompt S] [--chosen N] [--approve | --redo] [--notes S]
```

It prints the updated shot as JSON. Bad edits are rejected at write time rather
than at spend time — unknown fields, empty or lint-failing prompts, a `chosen`
index that doesn't exist, approving a shot with nothing chosen — with the
reason on stderr and exit code 2.

Run exit codes: `0` done, `2` invalid edit, `3` shots awaiting approval, `4`
budget exceeded. Every step is resumable: re-running the same command picks up
where it stopped, per shot.

`uv run reelforge status <job.yaml>` prints the run state plus a one-line
summary per shot (status, chosen candidate, whether the clip exists).

## Dashboard: the observability window

`uv run reelforge dash` serves a local console on 127.0.0.1. It is where a
human watches what the agent is doing — the plan it made and everything being
generated, live, without clicking anything — and steps in to pick keyframes,
adjust spend limits or try a model in the playground when they want to. The
CLI never needs it; the two are views on the same files.

## Cost controls

Money is gated at three levels, checked before every paid call:

- `budget_usd` per job in the manifest — the run stops with exit code 4 rather
  than exceed it;
- a machine-wide cap in `runs/limits.json` covering every job and every
  playground call, editable from the dashboard;
- `runs/ledger.jsonl`, an append-only record of every charge, plus per-run
  spend in `state.json`.

Estimates are computed before the spend, not after: the storyboard carries
per-shot `est_images_usd` / `est_video_usd`, and the dashboard shows a cost
estimate before any generation starts.

## Job spec

```yaml
name: neon-cat-demo        # run directory name (runs/<name>/)
style: neon-street         # prompt recipe: contrast-noir | rim-glow | neon-street | pov-pet | pov-vlog
flow: image-first          # image-first (storyboard gate) | direct (text-to-video)
image_quality: fast        # fast (Z-Image Turbo) | high (Seedream 5 Lite)
resolution: 768P           # video tier: 480P | 768P | 1080P
aspect: "9:16"             # 9:16 | 16:9 | 1:1
budget_usd: 3.0            # per-job cap
n_variants: 3              # keyframe candidates per shot
music:
  prompt: "dark aggressive phonk, 130 bpm, hard-hitting drop"
  duration_s: 30
shots:                     # one entry per shot; subject is the anchor —
  - subject: "a black cat with amber eyes"   # keep it verbatim across shots
    action: "sprinting toward the camera"
    scene: "narrow alley walls streaked with magenta neon"
```

Two rules the pipeline enforces regardless of flow. **Music first:** the beat
grid is the only timing authority, shot lengths are beat-aligned slots decided
before any video exists, and each clip is generated slightly longer than its
slot so the trim lands exactly on a beat. **Judge ≠ generator:** candidates are
picked by a reviewer — the agent driving the run, or the human watching it —
never by the model that made them; winning prompts accumulate in
`library/prompts.jsonl` as a reusable prompt bank.

## Models

The catalog is `src/reelforge/models_catalog.py` — every endpoint id, price and
cost estimator in one file, with the pipeline's defaults in `config.py`.
Runnable today: Z-Image Turbo, FLUX 2, Nano Banana and Seedream 5 Lite for
images; H3 Max Turbo, H3 Max and Seedance 1.5 Pro for video; MiniMax Music 3
and ElevenLabs Music for audio. The rest of the catalog is display-only until
its adapter lands. Endpoint slugs and schemas are verified against fal's public
OpenAPI (`https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<slug>`).

H3-family prices carry a 75% launch discount ending 2026-09-14.

## Prompt recipes

`src/reelforge/promptcraft.py` builds prompts from published guidance rather
than vibes: subject-first ordering with one hard light source and plain-word
chromatic contrast ([Hailuo visual-contrast guide](https://hailuoai.video/pages/knowledge/visual-contrast-ai-video-subjects-guide)),
lens terms to mask generation noise, an identical 5–7 word subject anchor
across a sequence, and — for POV formats — stating where the camera is
physically mounted instead of saying "POV"
([viral AI vlog teardown](https://trending.knowyourmeme.com/editorials/guides/what-are-the-ai-bigfoot-and-yeti-vlogs-and-how-are-people-making-them-the-viral-ai-video-trend-on-tiktok-explained)).
A lint step rejects the vague words that measurably hurt output, in generated
and hand-edited prompts alike.

## Provider pluggability

`src/reelforge/generate.py` is the only file that knows how media gets made;
`fal.py` is pure transport. A self-hosted backend (MiniMax H3 open weights on a
rented GPU via ComfyUI) can implement the same three functions when the
economics favor it.

## Roadmap

- Dance/motion-transfer job kind (Wan Animate / Wan-Dancer)
- Unattended vision scoring, so an agent can approve keyframes on a rubric
- Video-stage review: sample frames from draft clips, re-render the winner
- ComfyUI backend for self-hosted H3

## License

MIT
