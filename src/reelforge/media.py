"""ffmpeg helpers and dry-run placeholder synthesis."""

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def ff(*args: str) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{p.stderr[-800:]}")


def probe_duration(path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(p.stdout.strip())


# --- dry-run synthesizers ------------------------------------------------

def synth_image(dest: Path, size: tuple[int, int], variant: int) -> Path:
    w, h = size
    ff("-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=1",
       "-vf", f"hue=h={variant * 90}", "-frames:v", "1", str(dest))
    return dest


def synth_clip(dest: Path, size: tuple[int, int], seconds: int, variant: int) -> Path:
    w, h = size
    ff("-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30:duration={seconds}",
       "-vf", f"hue=h={variant * 47}", "-pix_fmt", "yuv420p", str(dest))
    return dest


def synth_music(dest: Path, seconds: float, bpm: float = 120.0, sr: int = 22050) -> Path:
    """Kick pulses on the beat, louder back half so a drop is detectable."""
    n = int(seconds * sr)
    y = np.zeros(n, dtype=np.float32)
    beat = 60.0 / bpm
    t_kick = np.arange(int(0.12 * sr)) / sr
    kick = (np.sin(2 * np.pi * 55 * t_kick) * np.exp(-t_kick * 40)).astype(np.float32)
    rng = np.random.default_rng(0)
    hat = (rng.standard_normal(int(0.03 * sr)) * np.exp(-np.arange(int(0.03 * sr)) / (0.005 * sr))).astype(np.float32) * 0.15
    t = 0.0
    while t < seconds:
        i = int(t * sr)
        gain = 1.8 if t >= seconds / 2 else 1.0
        y[i:i + len(kick)] += kick[: max(0, min(len(kick), n - i))] * gain
        j = int((t + beat / 2) * sr)
        if j < n:
            y[j:j + len(hat)] += hat[: max(0, min(len(hat), n - j))] * gain
        t += beat
    y = np.clip(y, -1, 1)
    sf.write(str(dest), y, sr)
    return dest
