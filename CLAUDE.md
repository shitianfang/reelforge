Layout: src/reelforge/{runner,job,beats,promptcraft,storyboard,judge,generate,assemble,media,fal,config,dashboard}.py — pipeline steps in runner.py docstring; storyboard.py owns per-shot prompts/candidates/choices (single edit endpoint: update_shot); judge.py is only the prompt bank; generate.py is the only provider-aware file; endpoint ids/prices live in config.py only; dashboard.html is the whole UI.

Commands: `uv run pytest` (no keys); `uv run reelforge run <job.yaml> --dry-run`; `uv run reelforge dash` (port 7799); live runs need FAL_KEY in .env (gitignored — never commit it).

Creative work (planning jobs, writing shot lists, judging keyframes/clips): load the `director` skill first.

Rules:
- Endpoint params come from fal's public OpenAPI: `curl "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<slug>"` — check it before the first live call of a model (`VERIFY` marks the untested ones; music lyrics convention still unverified).
- Run pytest + a dry run before every push; after dashboard changes, also screenshot the page (playwright via `uv run --with playwright`).
- Storyboard gate (image-first): exit code 3 = shots still unapproved. Edit runs/<job>/storyboard.json, or `uv run reelforge shot <job.yaml> <i> [--image-prompt S] [--chosen N] --approve|--redo`, or pick on the dashboard, then re-run the same command. `--auto` is the only way past the gate unattended; `--dry-run` does not imply it.
- Money paths (playground submit, RunState.spend) must stay behind global_charge — the machine-wide cap in runs/limits.json is the last line against runaway batch spend.
