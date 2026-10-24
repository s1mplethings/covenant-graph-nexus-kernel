from __future__ import annotations

import pathlib
import shutil

import pytest
from PIL import Image

from cgkn.application.promotion.contracts import PromotionVideoPlan


def test_deterministic_cards_cover_landscape_and_square(public_pack, studio):
    _, brief, _ = studio.prepare_campaign(public_pack, platforms=("mastodon",))
    claims = tuple(item.text for item in public_pack.allowed_claims)
    landscape = studio.assets.render_card(brief, claims, public_pack.evidence_ids)
    square = studio.assets.render_card(brief, claims, public_pack.evidence_ids, width=1080, height=1080)
    assert landscape.media_type == square.media_type == "image/png"
    assert Image.open(landscape.path).size == (1200, 675)
    assert Image.open(square.path).size == (1080, 1080)
    assert landscape.content_hash != square.content_hash


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg unavailable")
def test_ffmpeg_video_has_audio_video_and_provenance(public_pack, studio):
    _, brief, _ = studio.prepare_campaign(public_pack, platforms=("youtube",))
    plan = PromotionVideoPlan(brief.campaign_id, "9:16", 360, 640, 2, "CGKN verified update", ("Bounded qualification",), "Inspect the evidence", ())
    asset = studio.assets.render_video(plan, public_pack.evidence_ids)
    assert pathlib.Path(asset.path).is_file() and pathlib.Path(asset.path).stat().st_size > 1000
    assert asset.media_type == "video/mp4" and asset.duration_seconds and asset.duration_seconds >= 1.9
    assert asset.source_evidence_ids == public_pack.evidence_ids
