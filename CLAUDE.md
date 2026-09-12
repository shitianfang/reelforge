Layout: src/reelforge/{runner,job,beats,promptcraft,judge,generate,assemble,media,fal,config}.py — pipeline steps in runner.py docstring; generate.py is the only provider-aware file; endpoint ids/prices live in config.py only.

Commands: `uv run pytest` (no keys); `uv run reelforge run <job.yaml> --dry-run`; live runs need FAL_KEY.

Rules:
- Verify `VERIFY`-marked endpoint params in config.py/generate.py against fal.ai docs before the first live call of each model.
- Run pytest + a dry run before every push.
- Attended review gate: on exit code 3, read runs/<name>/review_request.json, look at the candidate images, write review.json (rubric scores, chosen index, optional revise_prompt), re-run.
