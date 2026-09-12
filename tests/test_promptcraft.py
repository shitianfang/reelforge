import pytest

from reelforge.promptcraft import ShotBrief, image_prompt, lint, video_prompt


def test_anchor_survives_verbatim_across_shots():
    anchor = "a black cat with amber eyes"
    briefs = [ShotBrief(subject=anchor, action=a)
              for a in ("sprinting toward camera", "leaping over a puddle")]
    prompts = [video_prompt(b, "neon-street") for b in briefs]
    assert all(p.startswith(anchor) for p in prompts)


def test_pov_recipe_states_camera_mount_not_pov():
    p = image_prompt(ShotBrief(subject="a golden retriever", action=""), "pov-pet")
    assert "that is where the camera is" in p
    assert "fisheye" in p
    assert "no subtitles" in p


def test_drop_shot_gets_action_peak():
    b = ShotBrief(subject="a dancer in silver", action="spinning")
    assert "final beat" in video_prompt(b, "contrast-noir", on_drop=True)
    assert "final beat" not in video_prompt(b, "contrast-noir", on_drop=False)


def test_lint_flags_vague_words():
    assert lint("a portrait, soft lighting, moody") == ["soft lighting", "moody"]
    assert lint(image_prompt(ShotBrief(subject="a watch", action=""), "rim-glow")) == []


def test_unknown_style_is_a_clear_error():
    with pytest.raises(KeyError, match="unknown style"):
        image_prompt(ShotBrief(subject="x", action=""), "nope")
