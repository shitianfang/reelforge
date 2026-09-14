"""finish path: local grade + fal (Topaz) payload/charge, no network."""

from pathlib import Path

import pytest

from reelforge import media
from reelforge.generate import finish_video
from reelforge.models_catalog import est_for
from reelforge.runner import main


class FakeClient:
    dry = False

    def __init__(self):
        self.calls = []

    def upload(self, path, content_type):
        assert Path(path).exists()
        return "https://v3.fal.media/fake/in.mp4"

    def run(self, endpoint, payload, timeout_s=0):
        self.calls.append((endpoint, payload))
        return {"video": {"url": "https://v3.fal.media/fake/out.mp4"}}

    def download(self, url, dest):
        Path(dest).write_bytes(b"finished")


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    d = tmp_path_factory.mktemp("finish")
    return media.synth_clip(d / "in.mp4", (192, 144), 1, 0)


def test_grade_runs_locally(clip, tmp_path):
    out = media.grade(clip, tmp_path / "graded.mp4")
    assert out.exists() and out.stat().st_size > 0
    assert abs(media.probe_duration(out) - media.probe_duration(clip)) < 0.2
    assert media.probe_size(out) == media.probe_size(clip)


def test_finish_payload_and_charge(clip, tmp_path):
    client = FakeClient()
    charges = []
    dest = tmp_path / "out.mp4"
    finish_video(client, clip, dest, target_fps=60, upscale=1.0,
                 charge=lambda usd, what: charges.append((usd, what)))
    (endpoint, payload), = client.calls
    assert endpoint == "fal-ai/topaz/upscale/video"
    assert payload["video_url"].startswith("https://")
    assert payload["target_fps"] == 60 and payload["upscale_factor"] == 1.0
    assert payload["H264_output"] is True
    # 144p output ≤720p → $0.01/s, doubled for 60fps, 1s clip
    (usd, what), = charges
    assert usd == pytest.approx(est_for("video_finish", height=144, duration=1, fps=60))
    assert usd == pytest.approx(0.02)
    assert dest.read_bytes() == b"finished"


def test_finish_no_fps_keeps_payload_lean(clip, tmp_path):
    client = FakeClient()
    finish_video(client, clip, tmp_path / "out.mp4", target_fps=None, upscale=2.0)
    (_, payload), = client.calls
    assert "target_fps" not in payload and payload["upscale_factor"] == 2.0


def test_cli_finish_dry_run(clip, tmp_path):
    dest = tmp_path / "cli_out.mp4"
    rc = main(["finish", str(clip), str(dest), "--dry-run",
               "--workdir", str(tmp_path / "runs")])
    assert rc == 0
    assert dest.exists() and dest.stat().st_size > 0
    assert not dest.with_suffix(".graded.mp4").exists()  # intermediate cleaned up
