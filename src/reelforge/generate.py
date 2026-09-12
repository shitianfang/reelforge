"""Generation services: one function per medium, provider-agnostic surface.

Model choice is a catalog id (models_catalog.py); each family has a small
payload adapter here. The DryRunClient branch synthesizes local placeholders
so the whole pipeline is runnable and testable without keys.
"""

import base64
import math
from pathlib import Path

from . import media
from .config import IMAGE_HIGH_MIN_PIXELS, PRICES
from .models_catalog import SEEDANCE_DIMS, est_for, get_model


def _first_url(payload: dict, *keys: str) -> str:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, dict) and "url" in v:
            return v["url"]
        if isinstance(v, list) and v and "url" in v[0]:
            return v[0]["url"]
    raise KeyError(f"no media url in response keys {list(payload)}: {str(payload)[:300]}")


def _nearest_aspect(size: tuple[int, int]) -> str:
    """nano-banana takes an aspect enum, not pixels."""
    choices = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3,
               "3:4": 3 / 4, "21:9": 21 / 9, "3:2": 3 / 2, "2:3": 2 / 3}
    r = size[0] / size[1]
    return min(choices, key=lambda k: abs(choices[k] - r))


def _high_tier_size(size: tuple[int, int]) -> tuple[int, int]:
    """Seedream 5 Lite enforces a minimum canvas; scale up preserving aspect."""
    w, h = size
    if w * h >= IMAGE_HIGH_MIN_PIXELS:
        return size
    f = math.sqrt(IMAGE_HIGH_MIN_PIXELS / (w * h))
    return int(w * f) + 1, int(h * f) + 1


def gen_image(client, prompt: str, size: tuple[int, int], dest: Path,
              variant: int = 0, quality: str = "fast",
              model_id: str | None = None) -> Path:
    if client.dry:
        return media.synth_image(dest, size, variant)
    model_id = model_id or ("image_high" if quality == "high" else "image_fast")
    m = get_model(model_id)
    w, h = size
    if m["family"] == "seedream":
        w, h = _high_tier_size(size)
        payload = {"prompt": prompt, "image_size": {"width": w, "height": h}}
    elif m["family"] == "aspect":
        payload = {"prompt": prompt, "aspect_ratio": _nearest_aspect(size),
                   "num_images": 1}
    else:  # "wh": z-image, flux-2
        payload = {"prompt": prompt, "image_size": {"width": w, "height": h},
                   "num_images": 1}
    out = client.run(m["endpoint"], payload)
    client.download(_first_url(out, "images", "image"), dest)
    return dest


def gen_video(client, prompt: str, seconds: int, size: tuple[int, int],
              dest: Path, image_path: Path | None = None,
              resolution: str = "768P", variant: int = 0,
              model_id: str | None = None) -> Path:
    if client.dry:
        return media.synth_clip(dest, size, seconds, variant)
    m = get_model(model_id or "video_h3_turbo")
    if m["family"] in ("seedance", "seedance25"):
        max_s = 12 if m["family"] == "seedance" else 30
        payload = {
            "prompt": prompt,
            "duration": str(max(4, min(max_s, seconds))),
            "resolution": {"480P": "480p", "768P": "720p", "1080P": "1080p"}[resolution],
            "aspect_ratio": _nearest_aspect(size) if size != (0, 0) else "9:16",
            "generate_audio": True,
        }
    else:  # h3 family (turbo and max share the schema)
        payload = {
            "prompt": prompt,
            "duration": seconds,
            "resolution": resolution,
            "prompt_expansion_mode": "balanced",
        }
    if image_path is not None:
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        payload["image_url"] = f"data:image/png;base64,{b64}"
        endpoint = m["endpoint"]
    else:
        endpoint = m.get("endpoint_t2v", m["endpoint"])
    out = client.run(endpoint, payload)
    client.download(_first_url(out, "video"), dest)
    return dest


def gen_music(client, prompt: str, seconds: int, dest: Path, lyrics: str = "",
              model_id: str | None = None) -> Path:
    if client.dry:
        return media.synth_music(dest, seconds)
    m = get_model(model_id or "music")
    if m["family"] == "el_music":
        payload = {"prompt": prompt, "music_length_ms": seconds * 1000,
                   "force_instrumental": not lyrics}
    else:  # minimax music-3
        payload = {"prompt": prompt, "lyrics": lyrics, "duration": seconds}
    out = client.run(m["endpoint"], payload)
    client.download(_first_url(out, "audio", "audios"), dest)
    return dest


# --- cost estimates (pipeline defaults; the playground uses est_for) -------

def est_image(size: tuple[int, int], quality: str = "fast", count: int = 1) -> float:
    model_id = "image_high" if quality == "high" else "image_fast"
    return est_for(model_id, width=size[0], height=size[1]) * count


def est_video(seconds: int, resolution: str = "768P", count: int = 1) -> float:
    return est_for("video_h3_turbo", duration=seconds, resolution=resolution) * count


def est_music(seconds: int) -> float:
    return est_for("music", duration=seconds)
