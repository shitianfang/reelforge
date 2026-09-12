"""Generation services: one function per medium, provider-agnostic surface.

Each takes the transport client; the DryRunClient branch synthesizes local
placeholders so the whole pipeline is runnable and testable without keys.
A future ComfyUI/self-hosted backend implements the same functions.
"""

import base64
import math
from pathlib import Path

from . import media
from .config import FAL_MODELS, IMAGE_HIGH_MIN_PIXELS, PRICES


def _first_url(payload: dict, *keys: str) -> str:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, dict) and "url" in v:
            return v["url"]
        if isinstance(v, list) and v and "url" in v[0]:
            return v[0]["url"]
    raise KeyError(f"no media url in response keys {list(payload)}")


def _high_tier_size(size: tuple[int, int]) -> tuple[int, int]:
    """Seedream 5 Lite enforces a minimum canvas; scale up preserving aspect."""
    w, h = size
    if w * h >= IMAGE_HIGH_MIN_PIXELS:
        return size
    f = math.sqrt(IMAGE_HIGH_MIN_PIXELS / (w * h))
    return int(w * f) + 1, int(h * f) + 1


def gen_image(client, prompt: str, size: tuple[int, int], dest: Path,
              variant: int = 0, quality: str = "fast") -> Path:
    if client.dry:
        return media.synth_image(dest, size, variant)
    if quality == "high":
        w, h = _high_tier_size(size)
        out = client.run(FAL_MODELS["image_high"], {
            "prompt": prompt,
            "image_size": {"width": w, "height": h},
        })
    else:
        w, h = size
        out = client.run(FAL_MODELS["image_fast"], {
            "prompt": prompt,
            "image_size": {"width": w, "height": h},
            "num_images": 1,
        })
    client.download(_first_url(out, "images", "image"), dest)
    return dest


def gen_video(client, prompt: str, seconds: int, size: tuple[int, int],
              dest: Path, image_path: Path | None = None,
              resolution: str = "768P", variant: int = 0) -> Path:
    if client.dry:
        return media.synth_clip(dest, size, seconds, variant)
    payload = {
        "prompt": prompt,
        "duration": seconds,
        "resolution": resolution,
        "prompt_expansion_mode": "balanced",
    }
    if image_path is not None:
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        payload["image_url"] = f"data:image/png;base64,{b64}"
        model = FAL_MODELS["video_i2v"]
    else:
        model = FAL_MODELS["video_t2v"]
    out = client.run(model, payload)
    client.download(_first_url(out, "video"), dest)
    return dest


def gen_music(client, prompt: str, seconds: int, dest: Path, lyrics: str = "") -> Path:
    if client.dry:
        return media.synth_music(dest, seconds)
    out = client.run(FAL_MODELS["music"], {
        "prompt": prompt,
        "lyrics": lyrics,  # VERIFY on first live music run: instrumental convention
        "duration": seconds,
    })
    client.download(_first_url(out, "audio", "audios"), dest)
    return dest


# --- cost estimates (feed the ledger and the dashboard) -------------------

def est_image(size: tuple[int, int], quality: str = "fast", count: int = 1) -> float:
    if quality == "high":
        return PRICES["image_high"] * count
    w, h = size
    return PRICES["image_fast_per_mp"] * (w * h / 1_000_000) * count


def est_video(seconds: int, resolution: str = "768P", count: int = 1) -> float:
    return PRICES["video_per_s"][resolution] * seconds * count


def est_music(seconds: int) -> float:
    return PRICES["music_per_s"] * seconds
