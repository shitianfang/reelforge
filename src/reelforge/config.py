"""Central registry: provider endpoints, price estimates, generation limits."""

import os

# fal.ai endpoint ids. VERIFY against https://fal.ai/explore on first live run:
# H3 and Music endpoint ids were confirmed to exist as of 2026-09 but exact
# slugs may differ; update here only — nothing else references them.
FAL_MODELS = {
    "image": "fal-ai/bytedance/seedream/v4.5/text-to-image",
    "video_i2v": "fal-ai/minimax/h3-max/image-to-video",
    "music": "fal-ai/minimax-music/v1.5",
}

# USD estimates used by the budget ledger (not authoritative billing).
PRICES = {
    "image": 0.04,          # per image
    "video_per_s": 0.0125,  # per output second
    "music_per_s": 0.002,   # per output second
}

# H3 accepts integer durations in this range only.
VIDEO_MIN_S = 4
VIDEO_MAX_S = 15

ASPECTS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


def fal_key() -> str:
    key = os.environ.get("FAL_KEY", "")
    if not key:
        raise SystemExit("FAL_KEY is not set. Get one at https://fal.ai/dashboard/keys, "
                         "then: export FAL_KEY=...  (or use --dry-run)")
    return key
