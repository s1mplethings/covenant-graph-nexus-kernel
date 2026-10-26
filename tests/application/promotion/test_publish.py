from __future__ import annotations

import dataclasses
import json
import pathlib

import pytest

from cgkn.application.promotion.contracts import ApprovalLevel, MediaAsset, PublicationStatus, TransportStatus, canonical_hash
from cgkn.application.promotion.publish import (
    BlueskyPublisherAdapter, EnvironmentCredentialResolver, FakePublisherAdapter, MastodonPublisherAdapter,
    PostizBridgeAdapter, PublicationEngine, PublicationScheduler, PublicationStore, YouTubePublisherAdapter,
)
from cgkn.application.promotion.publish import _transport_result


class StaticCredentials:
    def resolve(self, opaque_ref: str) -> str:
        assert opaque_ref == "credential:test"
        return "top-secret-token"


class RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses); self.calls = []

    def request(self, method, url, *, headers, json_body=None, body=None, timeout=30.0):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "json_body": json_body, "body_len": len(body or b""), "timeout": timeout})
        return self.responses.pop(0)


def prepared(public_pack, studio, *, platform="mastodon", asset=None, level=ApprovalLevel.APPROVED_TO_PUBLISH, scheduled_at=None, adapter_ref=None):
    _, brief, variants = studio.prepare_campaign(public_pack, platforms=(platform,))
    assets = (asset,) if asset else ()
    approval = studio.approve(brief, variants, assets, actor="operator", level=level)
    plan = studio.plan(brief, variants[0], assets, approval, adapter_ref=adapter_ref or f"promotion.publisher.{platform}@1", scheduled_at=scheduled_at)
    return brief, variants[0], assets, approval, plan


def test_publish_requires_explicit_exact_approval(public_pack, studio, tmp_path):
    _, variant, assets, approval, plan = prepared(public_pack, studio, level=ApprovalLevel.DRAFT_ONLY)
    engine = PublicationEngine(PublicationStore(tmp_path / "state.json"), {"promotion.publisher.mastodon@1": FakePublisherAdapter(platform="mastodon", adapter_ref="promotion.publisher.mastodon@1")})
    with pytest.raises(PermissionError, match="explicit publish approval"):
        engine.execute(plan, variant, assets, approval)


def test_fake_publish_is_idempotent_and_restart_safe(public_pack, studio, tmp_path):
    _, variant, assets, approval, plan = prepared(public_pack, studio)
    store_path = tmp_path / "state.json"
    adapter = FakePublisherAdapter(platform="mastodon", adapter_ref=plan.adapter_ref)
    first = PublicationEngine(PublicationStore(store_path), {plan.adapter_ref: adapter}).execute(plan, variant, assets, approval)
    second = PublicationEngine(PublicationStore(store_path), {plan.adapter_ref: adapter}).execute(plan, variant, assets, approval)
    assert first.result == PublicationStatus.PUBLISHED.value
    assert second.result == PublicationStatus.ALREADY_PUBLISHED.value
    assert first.platform_post_id == second.platform_post_id and first.receipt_hash != second.receipt_hash


def test_retry_is_bounded_and_classified(public_pack, studio, tmp_path):
    _, variant, assets, approval, plan = prepared(public_pack, studio)
    plan = dataclasses.replace(plan, max_retries=2)
    adapter = FakePublisherAdapter(platform="mastodon", adapter_ref=plan.adapter_ref, mode="timeout")
    receipt = PublicationEngine(PublicationStore(tmp_path / "state.json"), {plan.adapter_ref: adapter}).execute(plan, variant, assets, approval)
    assert receipt.result == PublicationStatus.FAILED_RETRYABLE.value and receipt.retry_count == 2


def test_scheduler_persists_queue_and_resumes(public_pack, studio, tmp_path):
    future = "2099-01-01T00:00:00Z"
    _, variant, assets, approval, plan = prepared(public_pack, studio, scheduled_at=future)
    path = tmp_path / "scheduler.json"; adapter = FakePublisherAdapter(platform="mastodon", adapter_ref=plan.adapter_ref)
    scheduler = PublicationScheduler(PublicationStore(path), PublicationEngine(PublicationStore(path), {plan.adapter_ref: adapter}))
    scheduler.enqueue(plan, variant, assets, approval)
    resumed_store = PublicationStore(path); resumed = PublicationScheduler(resumed_store, PublicationEngine(resumed_store, {plan.adapter_ref: adapter}))
    assert resumed.run_due(now="2026-10-25T00:00:00Z") == ()
    receipts = resumed.run_due(now="2100-01-01T00:00:00Z")
    assert len(receipts) == 1 and receipts[0].result == PublicationStatus.PUBLISHED.value


def test_schedule_only_approval_never_auto_publishes(public_pack, studio, tmp_path):
    _, variant, assets, approval, plan = prepared(public_pack, studio, level=ApprovalLevel.APPROVED_TO_SCHEDULE, scheduled_at="2026-10-25T00:00:00Z")
    path = tmp_path / "scheduler.json"; adapter = FakePublisherAdapter(platform="mastodon", adapter_ref=plan.adapter_ref)
    store = PublicationStore(path); scheduler = PublicationScheduler(store, PublicationEngine(store, {plan.adapter_ref: adapter}))
    scheduler.enqueue(plan, variant, assets, approval)
    assert scheduler.run_due(now="2026-10-26T00:00:00Z") == ()


def test_mastodon_native_contract_and_media_upload(public_pack, studio, tmp_path):
    image = tmp_path / "card.png"; image.write_bytes(b"PNG")
    asset = MediaAsset("a", "c", "PROJECT_CARD", str(image), "image/png", canonical_hash(b"PNG"), public_pack.evidence_ids, "test", canonical_hash("cfg"), 10, 10)
    _, variant, assets, approval, plan = prepared(public_pack, studio, asset=asset)
    transport = RecordingTransport([(200, {"x-request-id": "media-r"}, {"id": "media-1"}), (200, {"x-request-id": "post-r"}, {"id": "post-1", "url": "https://social/p/1"})])
    adapter = MastodonPublisherAdapter("https://social.example", "credential:test", StaticCredentials(), transport)
    result = adapter.publish(plan, variant, assets)
    assert result.status is TransportStatus.SUCCESS and result.media_ids == ("media-1",)
    assert transport.calls[0]["url"].endswith("/api/v2/media") and transport.calls[1]["json_body"]["media_ids"] == ["media-1"]
    assert transport.calls[1]["headers"]["Idempotency-Key"] == plan.idempotency_key


def test_bluesky_native_contract_uploads_blob(public_pack, studio, tmp_path):
    image = tmp_path / "card.png"; image.write_bytes(b"PNG")
    asset = MediaAsset("a", "c", "PROJECT_CARD", str(image), "image/png", canonical_hash(b"PNG"), public_pack.evidence_ids, "test", canonical_hash("cfg"), 10, 10)
    _, variant, assets, approval, plan = prepared(public_pack, studio, platform="bluesky", asset=asset)
    transport = RecordingTransport([(200, {}, {"blob": {"$type": "blob", "ref": {"$link": "abc"}, "mimeType": "image/png", "size": 3}}), (200, {"x-request-id": "b-r"}, {"uri": "at://did:plc:test/app.bsky.feed.post/r"})])
    adapter = BlueskyPublisherAdapter("https://bsky.social", "did:plc:test", "credential:test", StaticCredentials(), transport)
    result = adapter.publish(plan, variant, assets)
    assert result.status is TransportStatus.SUCCESS
    assert transport.calls[0]["url"].endswith("uploadBlob")
    assert transport.calls[1]["json_body"]["record"]["embed"]["images"][0]["image"]["mimeType"] == "image/png"


def test_youtube_native_contract_uses_video_upload(public_pack, studio, tmp_path):
    video = tmp_path / "video.mp4"; video.write_bytes(b"video-bytes")
    asset = MediaAsset("v", "c", "PROMOTION_VIDEO", str(video), "video/mp4", canonical_hash(b"video"), public_pack.evidence_ids, "test", canonical_hash("cfg"), 720, 1280, 3.0)
    _, variant, assets, approval, plan = prepared(public_pack, studio, platform="youtube", asset=asset)
    transport = RecordingTransport([(200, {"x-request-id": "yt-r"}, {"id": "yt-video"})])
    adapter = YouTubePublisherAdapter("credential:test", StaticCredentials(), transport)
    result = adapter.publish(plan, variant, assets)
    assert result.status is TransportStatus.SUCCESS and result.canonical_url == "https://youtu.be/yt-video"
    assert transport.calls[0]["body_len"] == len(b"video-bytes") and "top-secret-token" not in json.dumps(dataclasses.asdict(result))


def test_environment_credentials_are_opaque_and_not_serialized(monkeypatch):
    monkeypatch.setenv("PROMOTION_TEST_TOKEN", "very-secret")
    resolver = EnvironmentCredentialResolver({"credential:test": "PROMOTION_TEST_TOKEN"})
    assert resolver.resolve("credential:test") == "very-secret"
    assert "very-secret" not in repr(resolver.__dict__)


def test_platform_response_url_is_treated_as_untrusted():
    result = _transport_result("mastodon", 200, {}, {"id": "p", "url": "javascript:alert(1)"}, id_key="id")
    assert result.status is TransportStatus.SUCCESS and result.canonical_url is None


def test_native_metrics_available_or_explicitly_unsupported():
    transport = RecordingTransport([(200, {}, {"id": "p", "replies_count": 2, "reblogs_count": 3, "favourites_count": 5})])
    adapter = MastodonPublisherAdapter("https://social.example", "credential:test", StaticCredentials(), transport)
    metrics = adapter.fetch_metrics("p")
    assert metrics.status == "AVAILABLE" and metrics.metrics["favourites_count"] == 5
    assert FakePublisherAdapter().fetch_metrics("p").status == "NOT_AVAILABLE"


@pytest.mark.parametrize(("status", "expected", "retryable"), [(401, TransportStatus.AUTH_EXPIRED, False), (403, TransportStatus.SCOPE_MISSING, False), (429, TransportStatus.RATE_LIMITED, True), (503, TransportStatus.FAILED, True)])
def test_transport_failures_are_stably_classified(status, expected, retryable):
    result = _transport_result("mastodon", status, {"x-request-id": "r"}, {"error": "untrusted body"}, id_key="id")
    assert result.status is expected and result.retryable is retryable
    assert "untrusted body" not in (result.redacted_error or "")


def test_postiz_bridge_is_only_transport_and_requires_grounded_content(public_pack, studio):
    _, variant, assets, approval, plan = prepared(public_pack, studio)
    transport = RecordingTransport([(201, {"x-request-id": "pz-r"}, {"id": "pz-1", "url": "https://postiz.invalid/pz-1"})])
    adapter = PostizBridgeAdapter("https://postiz.invalid", "credential:test", StaticCredentials(), transport)
    plan = dataclasses.replace(plan, platform="postiz_bridge", adapter_ref=adapter.adapter_ref)
    result = adapter.publish(plan, variant, assets)
    assert result.status is TransportStatus.SUCCESS
    assert transport.calls[0]["json_body"]["content"] == variant.text
    with pytest.raises(ValueError, match="grounded claim"):
        dataclasses.replace(variant, claim_ids=())
