from __future__ import annotations

import dataclasses
import pathlib

import pytest

from cgkn.application.promotion.contracts import ApprovalLevel, PlatformAnalyticsSnapshot, Privacy, SignalKind, utc_now
from cgkn.application.promotion.service import AnalyticsFeedback, CampaignBuilder, DraftValidator, EvidenceProjector, PromotionStudio, SignalDetector


def test_evidence_projection_is_source_bound_and_rejects_private_paths(public_pack):
    assert public_pack.public_safe
    assert public_pack.evidence_hash.startswith("sha256:")
    assert all(claim.evidence_ids for claim in public_pack.allowed_claims)
    with pytest.raises(ValueError, match="private or secret-like"):
        EvidenceProjector.project(project_id="x", source_commit="abc1234", evidence_ids=("e",), facts=("C:\\Users\\me\\secret.txt",), metrics={}, changed_capabilities=(), before_after={}, candidate_assets=())


def test_signal_detector_deduplicates_and_suppresses_no_value(public_pack):
    detector = SignalDetector()
    signal = detector.detect(public_pack)
    assert signal and signal.public_value and signal.kind is SignalKind.PERFORMANCE
    assert detector.detect(public_pack).kind is SignalKind.NO_PUBLICATION_VALUE
    quiet = dataclasses.replace(public_pack, public_facts=(), validated_metrics={}, changed_capabilities=(), before_after_metrics={}, allowed_claims=())
    detector2 = SignalDetector(); no_value = detector2.detect(quiet)
    assert no_value and not no_value.public_value and no_value.kind is SignalKind.NO_PUBLICATION_VALUE


def test_campaign_and_content_are_claim_grounded(public_pack, studio: PromotionStudio):
    signal, brief, variants = studio.prepare_campaign(public_pack, platforms=("mastodon", "youtube"))
    assert signal.public_value and len(variants) == 2
    assert set(brief.approved_claim_ids) == {claim.claim_id for claim in public_pack.allowed_claims}
    assert all(set(item.claim_ids) <= set(brief.approved_claim_ids) for item in variants)


def test_invalid_claim_and_unknown_number_fail_closed(public_pack, studio: PromotionStudio):
    _, brief, variants = studio.prepare_campaign(public_pack, platforms=("mastodon",))
    bad_claim = dataclasses.replace(variants[0], claim_ids=("claim-does-not-exist",))
    with pytest.raises(ValueError, match="unapproved claim"):
        DraftValidator.validate(bad_claim, brief, studio.claims)
    bad_number = dataclasses.replace(variants[0], text=variants[0].text + " Improved by 999 percent.")
    with pytest.raises(ValueError, match="unsupported numerical claim"):
        DraftValidator.validate(bad_number, brief, studio.claims)


def test_private_campaign_cannot_build_public_plan(public_pack, studio: PromotionStudio):
    private = dataclasses.replace(public_pack, privacy=Privacy.PRIVATE_PREVIEW_ONLY)
    _, brief, variants = studio.prepare_campaign(private, platforms=("mastodon",))
    approval = studio.approve(brief, variants, (), level=ApprovalLevel.APPROVED_TO_PUBLISH, actor="human")
    plan = studio.plan(brief, variants[0], (), approval, adapter_ref="promotion.publisher.mastodon@1")
    from cgkn.application.promotion.publish import PublicationEngine
    with pytest.raises(PermissionError, match="private preview"):
        PublicationEngine.validate_approval(plan, variants[0], (), approval)


def test_campaign_rejects_no_publication_value(public_pack):
    signal = SignalDetector().detect(dataclasses.replace(public_pack, public_facts=(), validated_metrics={}, changed_capabilities=(), before_after_metrics={}, allowed_claims=()))
    assert signal is not None
    with pytest.raises(ValueError, match="no publication value"):
        CampaignBuilder().build(signal, public_pack, platforms=("mastodon",))


def test_campaign_deduplicates_same_signal(public_pack):
    detector = SignalDetector(); builder = CampaignBuilder(); signal = detector.detect(public_pack)
    builder.build(signal, public_pack, platforms=("mastodon",))
    with pytest.raises(ValueError, match="already exists"):
        builder.build(signal, public_pack, platforms=("mastodon",))


def test_approval_default_is_draft_only(public_pack, studio: PromotionStudio):
    _, brief, variants = studio.prepare_campaign(public_pack, platforms=("mastodon",))
    assert studio.approve(brief, variants, (), actor="operator").level is ApprovalLevel.DRAFT_ONLY


def test_variant_edit_invalidates_exact_hash_approval(public_pack, studio: PromotionStudio):
    _, brief, variants = studio.prepare_campaign(public_pack, platforms=("mastodon",))
    approval = studio.approve(brief, variants, (), level=ApprovalLevel.APPROVED_TO_PUBLISH, actor="operator")
    plan = studio.plan(brief, variants[0], (), approval, adapter_ref="promotion.publisher.mastodon@1")
    edited = dataclasses.replace(variants[0], text=variants[0].text + " edited")
    from cgkn.application.promotion.publish import PublicationEngine
    with pytest.raises(PermissionError, match="exact content"):
        PublicationEngine.validate_approval(plan, edited, (), approval)


def test_analytics_feedback_keeps_only_aggregate_numeric_metrics(public_pack, studio: PromotionStudio):
    _, brief, variants = studio.prepare_campaign(public_pack, platforms=("mastodon",))
    snapshot = PlatformAnalyticsSnapshot("mastodon", "p", utc_now(), {"views": 12, "rate": 0.5}, "AVAILABLE")
    record = AnalyticsFeedback.record(brief, variants[0], snapshot, asset_types=("PROJECT_CARD",), known_cost=0.0)
    assert record.aggregate_metrics == {"views": 12.0, "rate": 0.5}
    assert record.claim_ids == variants[0].claim_ids
