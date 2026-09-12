"""Frame-accurate beat-synced assembly with ffmpeg.

Every cut lands on a beat: each clip is trimmed to its planned slot length
(re-encoded at a fixed fps/size so the concat is frame-accurate), then the
music is muxed over the joined timeline.
"""

from pathlib import Path

from . import media


def assemble(clips: list[tuple[Path, float]], music: Path, dest: Path,
             size: tuple[int, int], fps: int = 30) -> Path:
    w, h = size
    workdir = dest.parent / "parts"
    workdir.mkdir(exist_ok=True)
    parts = []
    for i, (clip, length) in enumerate(clips):
        part = workdir / f"part_{i:03d}.mp4"
        media.ff("-i", str(clip), "-t", f"{length:.3f}",
                 "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                        f"crop={w}:{h},fps={fps}",
                 "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 str(part))
        parts.append(part)
    lst = workdir / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    silent = workdir / "silent.mp4"
    media.ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent))
    total = sum(length for _, length in clips)
    media.ff("-i", str(silent), "-i", str(music),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
             "-t", f"{total:.3f}", str(dest))
    return dest
