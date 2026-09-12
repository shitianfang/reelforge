"""Music-first timing: the beat grid is the edit's single timing authority.

Order of operations matters: music is generated first, beats are detected,
then shot lengths are planned as beat-aligned slots, and only then are video
clips generated (slightly longer than their slot) and trimmed onto the grid.
"""

import math
from dataclasses import dataclass, field

import librosa
import numpy as np

from .config import VIDEO_MAX_S, VIDEO_MIN_S


@dataclass
class BeatGrid:
    bpm: float
    beat_times: list[float]
    duration: float
    drop_time: float | None  # start of the biggest sustained energy jump


@dataclass
class Shot:
    index: int
    start: float
    end: float
    on_drop: bool = False
    gen_seconds: int = field(init=False)

    def __post_init__(self):
        # Ask the video model for headroom above the slot length so the trim
        # always has material; H3 only accepts integers in [4, 15].
        self.gen_seconds = min(VIDEO_MAX_S, max(VIDEO_MIN_S, math.ceil(self.length) + 1))

    @property
    def length(self) -> float:
        return self.end - self.start


def analyze(audio_path) -> BeatGrid:
    y, sr = librosa.load(str(audio_path), mono=True)
    tempo, beat_times = librosa.beat.beat_track(y=y, sr=sr, units="time")
    bpm = float(np.atleast_1d(tempo)[0])
    beat_times = [float(t) for t in beat_times]
    duration = len(y) / sr

    drop_time = None
    if len(beat_times) >= 8:
        rms = librosa.feature.rms(y=y)[0]
        rms_t = librosa.times_like(rms, sr=sr)
        # Mean energy of the 4 beats after vs before each candidate beat;
        # the largest sustained jump is the drop.
        def window(a, b):
            m = (rms_t >= a) & (rms_t < b)
            return float(rms[m].mean()) if m.any() else 0.0
        best, best_jump = None, 0.0
        for k in range(4, len(beat_times) - 4):
            before = window(beat_times[k - 4], beat_times[k])
            after = window(beat_times[k], beat_times[k + 4])
            jump = after - before
            if jump > best_jump:
                best, best_jump = beat_times[k], jump
        if best is not None and best_jump > 0.02:
            drop_time = best
    return BeatGrid(bpm=bpm, beat_times=beat_times, duration=duration, drop_time=drop_time)


def plan_shots(grid: BeatGrid, n_shots: int, min_shot: float = 2.0,
               max_shot: float = float(VIDEO_MAX_S - 1)) -> list[Shot]:
    """Partition [0, last_beat] into n beat-aligned slots; one boundary lands
    on the drop when there is one."""
    if n_shots < 1:
        raise ValueError("n_shots must be >= 1")
    beats = np.array(grid.beat_times)
    if len(beats) < n_shots + 1:
        raise ValueError(f"only {len(beats)} beats detected, need at least {n_shots + 1}")
    total = float(beats[-1])

    def snap(t: float) -> float:
        return float(beats[np.abs(beats - t).argmin()])

    bounds = [0.0] + [snap(t) for t in np.linspace(0, total, n_shots + 1)[1:-1]] + [total]
    drop = grid.drop_time
    if drop is not None and n_shots > 1:
        inner = np.array(bounds[1:-1])
        bounds[1 + int(np.abs(inner - drop).argmin())] = snap(drop)

    # Enforce strictly increasing bounds with a minimum slot length.
    clean = [0.0]
    for b in bounds[1:-1]:
        if b - clean[-1] >= min_shot and total - b >= min_shot:
            clean.append(b)
    clean.append(total)

    # Split any slot that exceeds what one generated clip can cover.
    final = [clean[0]]
    for b in clean[1:]:
        while b - final[-1] > max_shot:
            mid = snap(final[-1] + max_shot)
            if mid <= final[-1] or b - mid < min_shot:
                break
            final.append(mid)
        final.append(b)

    shots = []
    for i in range(len(final) - 1):
        on_drop = drop is not None and abs(final[i] - snap(drop)) < 1e-6 and i > 0
        shots.append(Shot(index=i, start=final[i], end=final[i + 1], on_drop=on_drop))
    return shots
