from pathlib import Path

import pytest

from reelforge import beats, media


@pytest.fixture(scope="module")
def click_track(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("audio") / "click.wav"
    media.synth_music(p, seconds=24, bpm=120)
    return p


def test_grid_matches_click_track(click_track):
    grid = beats.analyze(click_track)
    # Accept the metrical family (60/120/240) — librosa may halve or double.
    assert any(abs(grid.bpm - t) < 8 for t in (60, 120, 240)), grid.bpm
    spacing = [b - a for a, b in zip(grid.beat_times, grid.beat_times[1:])]
    median = sorted(spacing)[len(spacing) // 2]
    assert any(abs(median - s) < 0.06 for s in (0.25, 0.5, 1.0)), median


def test_drop_detected_near_midpoint(click_track):
    grid = beats.analyze(click_track)
    assert grid.drop_time is not None
    assert abs(grid.drop_time - 12.0) < 2.5


def test_shot_boundaries_land_on_beats(click_track):
    grid = beats.analyze(click_track)
    shots = beats.plan_shots(grid, n_shots=5)
    assert len(shots) >= 2
    for s in shots:
        assert s.end - s.start >= 1.0
        assert beats.VIDEO_MIN_S <= s.gen_seconds <= beats.VIDEO_MAX_S
        assert s.gen_seconds >= s.length  # trim never exceeds generated material
    for s in shots[:-1]:
        nearest = min(abs(s.end - b) for b in grid.beat_times)
        assert nearest < 0.03, f"cut at {s.end} is off-beat by {nearest}"
    # Timeline is contiguous from 0 to the last beat.
    assert shots[0].start == 0.0
    for a, b in zip(shots, shots[1:]):
        assert a.end == b.start


def test_long_slots_are_split(click_track):
    grid = beats.analyze(click_track)
    shots = beats.plan_shots(grid, n_shots=1, max_shot=8.0)
    assert all(s.length <= 8.0 + 0.6 for s in shots)
    assert len(shots) >= 3  # 24s timeline can't be one 8s-max slot
