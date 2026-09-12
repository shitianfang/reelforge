"""Central registry: provider endpoints, price estimates, generation limits.

Endpoint slugs and input params were verified against fal's public OpenAPI
(https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=...) on 2026-09-12.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    p = REPO_ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

FAL_MODELS = {
    "image_fast": "fal-ai/z-image/turbo",                              # $0.005/MP
    "image_high": "fal-ai/bytedance/seedream/v5/lite/text-to-image",   # $0.035/img
    "video_i2v": "minimax/h3-max-turbo/image-to-video",
    "video_t2v": "minimax/h3-max-turbo/text-to-video",
    "music": "minimax/music-3",                                        # $0.002/s
}

# USD estimates used by the budget ledger (not authoritative billing).
PRICES = {
    "image_fast_per_mp": 0.005,
    "image_high": 0.035,
    "music_per_s": 0.002,
    # H3 Max Turbo per output second, by resolution — 75% LAUNCH DISCOUNT,
    # ends 2026-09-14; after that: 480P 0.025 / 768P 0.04 / 1080P 0.08.
    "video_per_s": {"480P": 0.00625, "768P": 0.01, "1080P": 0.02},
}
DISCOUNT_DEADLINE = "2026-09-14"

# Seedream 5 Lite rejects small canvases: total pixels must be >= ~2560x1440.
IMAGE_HIGH_MIN_PIXELS = 2560 * 1440

# H3 accepts integer durations in this range only.
VIDEO_MIN_S = 4
VIDEO_MAX_S = 15
RESOLUTIONS = ("480P", "768P", "1080P")

ASPECTS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


def fal_key() -> str:
    key = os.environ.get("FAL_KEY", "")
    if not key:
        raise SystemExit("FAL_KEY is not set (env or .env at repo root). "
                         "Get one at https://fal.ai/dashboard/keys, or use --dry-run.")
    return key
