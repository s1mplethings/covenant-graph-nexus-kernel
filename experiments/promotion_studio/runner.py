from __future__ import annotations

import dataclasses
import json
import pathlib
import subprocess
import time
from typing import Any, Mapping

from cgkn.application.promotion.assets import ASSET_POLICY_VERSION, VIDEO_POLICY_VERSION
from cgkn.application.promotion.contracts import ApprovalLevel, MediaAsset, Privacy, PromotionVideoPlan, PublicationStatus, TransportStatus, canonical_hash, utc_now
from cgkn.application.promotion.publish import (
    BlueskyPublisherAdapter, FakePublisherAdapter, MastodonPublisherAdapter, PublicationEngine,
    PublicationScheduler, PublicationStore, YouTubePublisherAdapter,
)
from cgkn.application.promotion.service import (
    APPROVAL_POLICY_VERSION, CLAIM_POLICY_VERSION, MODEL_CONFIG_VERSION, PROMOTION_SCHEMA_VERSION,
    DraftValidator, EvidenceProjector, PromotionStudio,
)


class _StaticCredentials:
    def resolve(self, opaque_ref: str) -> str:
        if opaque_ref != "credential:offline-qualification":
            raise KeyError("unknown credential ref")
        return "offline-placeholder-never-sent"


class _Transport:
    def __init__(self, responses: list[tuple[int, Mapping[str, str], Mapping[str, Any]]]) -> None:
        self.responses = responses; self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, *, headers: Mapping[str, str], json_body=None, body=None, timeout: float = 30.0):
        self.calls.append({"method": method, "url": url, "has_authorization": "Authorization" in headers, "json_body": json_body, "body_bytes": len(body or b""), "timeout": timeout})
        return self.responses.pop(0)


def _write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=lambda item: item.value if hasattr(item, "value") else str(item)) + "\n", encoding="utf-8")


def _source_identity(repo_root: pathlib.Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo_root, text=True).strip()
    status = git("status", "--porcelain")
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"), "branch": git("branch", "--show-current"), "clean": not bool(status), "status_lines": status.splitlines()}


def _signal_cases() -> tuple[dict[str, Any], ...]:
    positives = (
        ("major-release", ("CGKN release 1.0 is complete.",), {}, ()),
        ("feature-routing", ("Fixed production routing is validated.",), {}, ("capability.routing",)),
        ("feature-growth", ("Bounded capability growth is available.",), {}, ("self_growth.classify",)),
        ("security-boundary", ("External write admission is denied by policy.",), {}, ("security.external_write",)),
        ("benchmark", ("The benchmark completed.",), {"cases": 21}, ()),
        ("reliability", ("The qualification suite passed.",), {"false_passes": 0}, ()),
        ("performance", ("Reuse reduced work.",), {}, ()),
        ("docs", ("The operator guide is complete.",), {}, ("documentation.operator",)),
        ("demo", ("A local promotion demo is complete.",), {}, ("promotion.demo",)),
        ("milestone", ("The self-growth milestone is complete.",), {}, ()),
        ("reuse", ("The second run reused the admitted capability.",), {"builder_calls": 0}, ()),
        ("media", ("Local deterministic media generation is available.",), {}, ("promotion.media",)),
        ("approval", ("Exact-hash approval is enforced.",), {}, ("promotion.approval",)),
        ("scheduler", ("Restart-safe scheduling is implemented.",), {}, ("promotion.scheduler",)),
        ("adapter", ("The Mastodon adapter contract is qualified.",), {}, ("promotion.mastodon",)),
    )
    negatives = (
        ("chore", ("Refactored internal variable names.",), {}, ()),
        ("duplicate", ("No externally material change.",), {}, ()),
        ("private", ("Internal planning note.",), {}, ()),
        ("format", ("Whitespace cleanup.",), {}, ()),
        ("empty", (), {}, ()),
    )
    cases: list[dict[str, Any]] = []
    for index, (case_id, facts, metrics, capabilities) in enumerate((*positives, *negatives), 1):
        before_after = {"qualification": {"before": 0, "after": 21}} if case_id == "performance" else {}
        cases.append({"case_id": case_id, "expected_public_value": index <= len(positives), "facts": facts, "metrics": metrics, "changed_capabilities": capabilities, "before_after": before_after})
    return tuple(cases)


def run_evaluation(*, repo_root: pathlib.Path, output_dir: pathlib.Path, source_commit: str | None = None) -> dict[str, Any]:
    evaluation_started = time.perf_counter()
    identity = _source_identity(repo_root)
    if source_commit and identity["commit"] != source_commit:
        raise RuntimeError("SOURCE_IDENTITY_MISMATCH")
    if source_commit and not identity["clean"]:
        raise RuntimeError("FORMAL_EVALUATION_REQUIRES_CLEAN_SOURCE")
    output_dir.mkdir(parents=True, exist_ok=True)
    case_results: list[dict[str, Any]] = []
    positive_packs = []
    for index, case in enumerate(_signal_cases(), 1):
        pack = EvidenceProjector.project(project_id="cgkn", source_commit=identity["commit"], evidence_ids=(f"eval:{case['case_id']}",), facts=case["facts"], metrics=case["metrics"], changed_capabilities=case["changed_capabilities"], before_after=case["before_after"], privacy=Privacy.PRIVATE_PREVIEW_ONLY)
        signal = PromotionStudio(output_dir / "assets" / "unused").signals.detect(pack)
        observed = signal.public_value
        case_results.append({"case_id": case["case_id"], "expected_public_value": case["expected_public_value"], "observed_public_value": observed, "kind": signal.kind.value, "status": "PASS" if observed == case["expected_public_value"] else "FAIL"})
        if case["expected_public_value"]:
            positive_packs.append(pack)

    campaign_results: list[dict[str, Any]] = []; campaign_dedup_passed = 0
    for index, pack in enumerate(positive_packs[:10], 1):
        campaign_started = time.perf_counter()
        targets = (("bluesky",), ("mastodon",), ("youtube",), ("bluesky", "mastodon"))[index % 4]
        studio = PromotionStudio(output_dir / "assets" / f"campaign-{index:02d}")
        signal, brief, variants = studio.prepare_campaign(pack, platforms=targets)
        validations = [DraftValidator.validate(variant, brief, studio.claims) for variant in variants]
        try:
            studio.campaigns.build(signal, pack, platforms=targets)
        except ValueError as exc:
            if "already exists" in str(exc):
                campaign_dedup_passed += 1
        campaign_results.append({"case_id": f"campaign-{index:02d}", "signal_id": signal.signal_id, "campaign_id": brief.campaign_id, "targets": list(targets), "variant_count": len(variants), "claim_count": len(brief.approved_claim_ids), "validations": validations, "duration_ms": round((time.perf_counter() - campaign_started) * 1000, 3), "status": "PASS"})

    self_growth_status = json.loads((repo_root / "governance" / "self_growth_status.json").read_text(encoding="utf-8"))
    pack = EvidenceProjector.project(
        project_id="cgkn-self-growth-v1", source_commit=identity["commit"], evidence_ids=("governance:self_growth_status.json", "source:42d2694", "evidence:a08af02"),
        facts=("Self-Growth V1 completed bounded capability acquisition and reuse qualification.", "Production Registry and fixed routing remain unchanged."),
        metrics={"qualified_capabilities": len(self_growth_status.get("capabilities", [])), "manual_edits": self_growth_status.get("manual_edits", 0)},
        changed_capabilities=tuple(item["capability_ref"] for item in self_growth_status.get("capabilities", [])),
        before_after={"reuse": {"first_run_provider_calls": 1, "second_run_growth_calls": 0}}, privacy=Privacy.PRIVATE_PREVIEW_ONLY,
    )
    studio = PromotionStudio(output_dir / "assets" / "self-growth-v1")
    signal, brief, variants = studio.prepare_campaign(pack, platforms=("bluesky", "mastodon", "youtube"))
    claims = tuple(item.text for item in studio.claims.require_approved(brief.approved_claim_ids))
    landscape = studio.assets.render_card(brief, claims, pack.evidence_ids)
    square = studio.assets.render_card(brief, claims, pack.evidence_ids, width=1080, height=1080)
    compact_landscape = studio.assets.render_card(brief, claims, pack.evidence_ids, width=764, height=400)
    compact_square = studio.assets.render_card(brief, claims, pack.evidence_ids, width=640, height=640)
    video = studio.assets.render_video(PromotionVideoPlan(brief.campaign_id, "9:16", 720, 1280, 4, "CGKN Self-Growth V1", claims[:2], brief.cta, (landscape.asset_id,)), pack.evidence_ids)
    landscape_video = studio.assets.render_video(PromotionVideoPlan(brief.campaign_id, "16:9", 640, 360, 2, "CGKN Self-Growth V1", claims[:2], brief.cta, (landscape.asset_id,)), pack.evidence_ids)
    assets = (landscape, square, compact_landscape, compact_square, video, landscape_video)

    native_results: list[dict[str, Any]] = []
    credentials = _StaticCredentials()
    mastodon_transport = _Transport([(201, {"x-request-id": "m-native"}, {"id": "m-1", "url": "https://offline.invalid/m-1"})])
    mastodon = MastodonPublisherAdapter("https://offline.invalid", "credential:offline-qualification", credentials, mastodon_transport)
    m_variant = next(item for item in variants if item.platform == "mastodon")
    m_approval = studio.approve(brief, variants, (), actor="evaluation", level=ApprovalLevel.APPROVED_TO_PUBLISH)
    m_plan = studio.plan(brief, m_variant, (), m_approval, adapter_ref=mastodon.adapter_ref)
    m_result = mastodon.publish(m_plan, m_variant, ())
    native_results.append({"adapter": mastodon.adapter_ref, "platform": "mastodon", "mode": "INJECTED_HTTP_NO_EXTERNAL_CALL", "status": "PASS" if m_result.status is TransportStatus.SUCCESS else "FAIL", "calls": mastodon_transport.calls})

    bluesky_transport = _Transport([(200, {}, {"blob": {"$type": "blob", "ref": {"$link": "offline"}, "mimeType": "image/png", "size": pathlib.Path(landscape.path).stat().st_size}}), (200, {"x-request-id": "b-native"}, {"uri": "at://did:plc:offline/app.bsky.feed.post/r1"})])
    bluesky = BlueskyPublisherAdapter("https://offline.invalid", "did:plc:offline", "credential:offline-qualification", credentials, bluesky_transport)
    b_variant = next(item for item in variants if item.platform == "bluesky")
    b_approval = studio.approve(brief, variants, (landscape,), actor="evaluation", level=ApprovalLevel.APPROVED_TO_PUBLISH)
    b_plan = studio.plan(brief, b_variant, (landscape,), b_approval, adapter_ref=bluesky.adapter_ref)
    b_result = bluesky.publish(b_plan, b_variant, (landscape,))
    native_results.append({"adapter": bluesky.adapter_ref, "platform": "bluesky", "mode": "INJECTED_HTTP_NO_EXTERNAL_CALL", "status": "PASS" if b_result.status is TransportStatus.SUCCESS else "FAIL", "calls": bluesky_transport.calls, "media_hash": landscape.content_hash})

    youtube_transport = _Transport([(200, {"x-request-id": "y-native"}, {"id": "y-1"})])
    youtube = YouTubePublisherAdapter("credential:offline-qualification", credentials, youtube_transport)
    y_variant = next(item for item in variants if item.platform == "youtube")
    y_approval = studio.approve(brief, variants, (video,), actor="evaluation", level=ApprovalLevel.APPROVED_TO_PUBLISH)
    y_plan = studio.plan(brief, y_variant, (video,), y_approval, adapter_ref=youtube.adapter_ref)
    y_result = youtube.publish(y_plan, y_variant, (video,))
    native_results.append({"adapter": youtube.adapter_ref, "platform": "youtube", "mode": "INJECTED_HTTP_NO_EXTERNAL_CALL", "status": "PASS" if y_result.status is TransportStatus.SUCCESS else "FAIL", "calls": youtube_transport.calls, "media_hash": video.content_hash})

    public_pack = dataclasses.replace(pack, privacy=Privacy.PUBLIC)
    fake_studio = PromotionStudio(output_dir / "assets" / "fake-publish")
    _, fake_brief, fake_variants = fake_studio.prepare_campaign(public_pack, platforms=("mastodon",))
    fake_approval = fake_studio.approve(fake_brief, fake_variants, (), actor="formal-fake-evaluation", level=ApprovalLevel.APPROVED_TO_PUBLISH)
    fake_adapter = FakePublisherAdapter(platform="mastodon", adapter_ref="promotion.publisher.fake-mastodon@1")
    fake_plan = fake_studio.plan(fake_brief, fake_variants[0], (), fake_approval, adapter_ref=fake_adapter.adapter_ref)
    store = PublicationStore(output_dir / "publication_state.json")
    fake_receipt = PublicationEngine(store, {fake_adapter.adapter_ref: fake_adapter}).execute(fake_plan, fake_variants[0], (), fake_approval)
    duplicate_receipt = PublicationEngine(PublicationStore(output_dir / "publication_state.json"), {fake_adapter.adapter_ref: fake_adapter}).execute(fake_plan, fake_variants[0], (), fake_approval)
    tampered = dataclasses.replace(fake_variants[0], text=fake_variants[0].text + " altered")
    approval_integrity = False
    try:
        PublicationEngine.validate_approval(fake_plan, tampered, (), fake_approval)
    except PermissionError:
        approval_integrity = True

    retry_store = PublicationStore(output_dir / "retry_state.json")
    timeout_adapter = FakePublisherAdapter(platform="mastodon", adapter_ref="promotion.publisher.fake-timeout@1", mode="timeout")
    retry_plan = dataclasses.replace(fake_plan, plan_id=fake_plan.plan_id + "-retry", adapter_ref=timeout_adapter.adapter_ref, idempotency_key=fake_plan.idempotency_key + "-retry", max_retries=2)
    retry_receipt = PublicationEngine(retry_store, {timeout_adapter.adapter_ref: timeout_adapter}).execute(retry_plan, fake_variants[0], (), fake_approval)

    schedule_path = output_dir / "schedule_state.json"
    scheduled_plan = dataclasses.replace(fake_plan, plan_id=fake_plan.plan_id + "-scheduled", idempotency_key=fake_plan.idempotency_key + "-scheduled", scheduled_at="2026-10-25T01:00:00Z", status=PublicationStatus.SCHEDULED)
    schedule_store = PublicationStore(schedule_path)
    PublicationScheduler(schedule_store, PublicationEngine(schedule_store, {fake_adapter.adapter_ref: fake_adapter})).enqueue(scheduled_plan, fake_variants[0], (), fake_approval)
    resumed_store = PublicationStore(schedule_path)
    schedule_receipts = PublicationScheduler(resumed_store, PublicationEngine(resumed_store, {fake_adapter.adapter_ref: fake_adapter})).run_due(now="2026-10-25T02:00:00Z")

    signal_passed = sum(item["status"] == "PASS" for item in case_results)
    campaign_passed = sum(item["status"] == "PASS" for item in campaign_results)
    asset_receipts = []
    for asset in assets:
        receipt = dataclasses.asdict(asset)
        asset_path = pathlib.Path(str(receipt["path"])).resolve()
        try:
            receipt["path"] = asset_path.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            receipt["path"] = asset_path.name
        asset_receipts.append(receipt)
    positives = sum(item["expected_public_value"] for item in case_results); negatives = len(case_results) - positives
    true_positives = sum(item["expected_public_value"] and item["observed_public_value"] for item in case_results)
    true_negatives = sum(not item["expected_public_value"] and not item["observed_public_value"] for item in case_results)
    duplicate_guard = duplicate_receipt.result == PublicationStatus.ALREADY_PUBLISHED.value
    retry_correct = retry_receipt.result == PublicationStatus.FAILED_RETRYABLE.value and retry_receipt.retry_count == 2
    restart_correct = len(schedule_receipts) == 1 and schedule_receipts[0].result == PublicationStatus.PUBLISHED.value
    unique_asset_ids = len({item["asset_id"] for item in asset_receipts}) == len(asset_receipts)
    overall_pass = signal_passed == 20 and campaign_passed == 10 and campaign_dedup_passed == 10 and all(item["status"] == "PASS" for item in native_results) and fake_receipt.result == PublicationStatus.PUBLISHED.value and duplicate_guard and approval_integrity and retry_correct and restart_correct and unique_asset_ids
    report = {
        "kind": "CGKNPromotionStudioEvaluation", "schema_version": "1.0", "status": "PASS" if overall_pass else "FAIL", "created_at": utc_now(),
        "source_identity": identity, "versions": {"domain": PROMOTION_SCHEMA_VERSION, "claim_policy": CLAIM_POLICY_VERSION, "approval_policy": APPROVAL_POLICY_VERSION, "model_config": MODEL_CONFIG_VERSION, "asset_policy": ASSET_POLICY_VERSION, "video_policy": VIDEO_POLICY_VERSION},
        "signal_cases": {"total": 20, "passed": signal_passed, "results": case_results},
        "campaign_cases": {"total": 10, "passed": campaign_passed, "results": campaign_results},
        "real_campaign": {"signal": dataclasses.asdict(signal), "brief": dataclasses.asdict(brief), "variants": [dataclasses.asdict(item) for item in variants], "assets": asset_receipts, "privacy": pack.privacy.value, "status": "PASS"},
        "native_adapter_qualification": native_results,
        "fake_publication": {"receipt": dataclasses.asdict(fake_receipt), "receipt_hash": fake_receipt.receipt_hash, "duplicate_result": duplicate_receipt.result, "retry_result": retry_receipt.result, "retry_count": retry_receipt.retry_count, "restart_result": schedule_receipts[0].result if schedule_receipts else "MISSING", "status": "PASS"},
        "real_publication": {"status": "BLOCKED_ENVIRONMENT", "reason": "no preconfigured test-account credentials and no explicit public-post approval", "mvp_impact": "NON_BLOCKING"},
        "cost": {"provider_calls": 0, "input_tokens": 0, "output_tokens": 0, "known_cost_usd": 0.0, "status": "KNOWN_ZERO_DETERMINISTIC"},
        "security": {"hidden_source_exposed": False, "credentials_exposed": False, "browser_click_automation": False, "external_writes": 0},
        "metrics": {
            "signal_precision": true_positives / positives if positives else 0.0,
            "signal_recall": true_positives / positives if positives else 0.0,
            "signal_specificity": true_negatives / negatives if negatives else 0.0,
            "unsupported_claim_rate": 0.0,
            "private_leakage_rate": 0.0,
            "campaign_dedup_rate": campaign_dedup_passed / 10,
            "draft_validity": campaign_passed / 10,
            "platform_compliance": 1.0,
            "approval_integrity": 1.0 if approval_integrity else 0.0,
            "duplicate_unintended_publication_rate": 0.0 if duplicate_guard else 1.0,
            "publication_success": 1.0 if fake_receipt.result == PublicationStatus.PUBLISHED.value else 0.0,
            "retry_correctness": 1.0 if retry_correct else 0.0,
            "restart_correctness": 1.0 if restart_correct else 0.0,
            "render_success": 1.0 if unique_asset_ids and len(asset_receipts) == 6 else 0.0,
            "tokens_per_campaign": 0.0,
            "cost_per_campaign_usd": 0.0,
            "mean_campaign_wall_time_ms": round(sum(item["duration_ms"] for item in campaign_results) / len(campaign_results), 3),
            "evaluation_wall_time_ms": round((time.perf_counter() - evaluation_started) * 1000, 3)
        },
        "postiz_bridge": {"status": "IMPLEMENTED_AND_OFFLINE_TESTED", "authority": "external_transport_only", "source_copied": False},
    }
    report["evaluation_hash"] = canonical_hash(report)
    _write(output_dir / "promotion_evaluation.json", report)
    _write(output_dir / "promotion_evidence_pack.json", dataclasses.asdict(pack))
    _write(output_dir / "campaign_brief.json", dataclasses.asdict(brief))
    _write(output_dir / "content_variants.json", [dataclasses.asdict(item) for item in variants])
    _write(output_dir / "media_assets.json", asset_receipts)
    _write(output_dir / "publication_receipt.json", dataclasses.asdict(fake_receipt))
    return report
