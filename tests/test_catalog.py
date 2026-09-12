import pytest

from reelforge.models_catalog import CATALOG, est_for, get_model


def test_catalog_invariants():
    ids = [m["id"] for m in CATALOG]
    assert len(ids) == len(set(ids))
    for m in CATALOG:
        assert m["kind"] in ("image", "video", "music", "audio")
        for field in ("label", "endpoint", "price", "pros", "cons", "usage", "tier"):
            assert m.get(field), f"{m['id']} missing {field}"
        if m["selectable"]:
            assert m["family"], f"{m['id']} selectable but has no adapter family"


def test_selectable_models_all_have_estimates():
    for m in CATALOG:
        if not m["selectable"]:
            continue
        est = est_for(m["id"], width=1080, height=1920, duration=6, resolution="768P")
        assert 0 < est < 2, f"{m['id']} estimate {est} out of sane range"


def test_estimates_match_known_prices():
    assert est_for("image_fast", width=1000, height=1000) == pytest.approx(0.005)
    assert est_for("image_flux2", width=1000, height=1000) == pytest.approx(0.012)
    assert est_for("video_h3_turbo", duration=10, resolution="768P") == pytest.approx(0.10)
    assert est_for("video_h3_max", duration=10, resolution="768P") == pytest.approx(0.20)
    # fal's own example: Seedance 720p 5s with audio ≈ $0.26
    assert est_for("video_seedance", duration=5, resolution="768P") == pytest.approx(0.26, abs=0.02)
    assert est_for("music_el", duration=60) == pytest.approx(0.60)


def test_non_selectable_has_no_estimator():
    with pytest.raises(KeyError):
        est_for("video_sora2", duration=5)
    with pytest.raises(KeyError):
        get_model("nope")
