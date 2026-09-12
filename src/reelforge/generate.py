"""Generation services: one function per medium, provider-agnostic surface.

Each takes the transport client; the DryRunClient branch synthesizes local
placeholders so the whole pipeline is runnable and testable without keys.
A future ComfyUI/self-hosted backend implements the same three functions.
"""

from pathlib import Path

from . import media
from .config import FAL_MODELS, PRICES


def _first_url(payload: dict, *keys: str) -> str:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, dict) and "url" in v:
            return v["url"]
        if isinstance(v, list) and v and "url" in v[0]:
            return v[0]["url"]
    raise KeyError(f"no media url in response keys {list(payload)}")


def gen_image(client, prompt: str, size: tuple[int, int], dest: Path, variant: int = 0) -> Path:
    if client.dry:
        return media.synth_image(dest, size, variant)
    w, h = size
    out = client.run(FAL_MODELS["image"], {
        "prompt": prompt,
        "image_size": {"width": w, "height": h},  # VERIFY param name on first live run
        "num_images": 1,
    })
    client.download(_first_url(out, "images", "image"), dest)
    return dest


def gen_video(client, prompt: str, image_path: Path, seconds: int,
              size: tuple[int, int], dest: Path, variant: int = 0) -> Path:
    if client.dry:
        return media.synth_clip(dest, size, seconds, variant)
    import base64
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    out = client.run(FAL_MODELS["video_i2v"], {
        "prompt": prompt,
        "image_url": f"data:image/png;base64,{b64}",
        "duration": seconds,  # VERIFY: H3 takes integer seconds 4-15
    })
    client.download(_first_url(out, "video"), dest)
    return dest


def gen_music(client, prompt: str, seconds: int, dest: Path) -> Path:
    if client.dry:
        return media.synth_music(dest, seconds)
    out = client.run(FAL_MODELS["music"], {
        "prompt": prompt,
        "duration": seconds,  # VERIFY: param support varies across music endpoints
    })
    client.download(_first_url(out, "audio"), dest)
    return dest


def estimate(kind: str, seconds: int = 0, count: int = 1) -> float:
    if kind == "image":
        return PRICES["image"] * count
    if kind == "video":
        return PRICES["video_per_s"] * seconds * count
    if kind == "music":
        return PRICES["music_per_s"] * seconds * count
    raise KeyError(kind)
