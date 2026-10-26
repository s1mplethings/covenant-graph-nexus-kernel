from __future__ import annotations

import dataclasses

import pytest

from cgkn.application.community.contracts import EngagementAction, ProjectMention, ReplyApprovalLevel, ReplyStatus
from cgkn.application.community.reply import CommunityReplyEngine, CommunityReplyStore, FakeCommunityReplyAdapter, FollowUpTracker
from cgkn.application.community.service import EngagementPolicy, OpportunityRanker, ReplyDrafter, ReplyValidator, TopicDeriver

from .conftest import make_thread


def make_draft(claim_ledger, community_policy, *, mention: bool = False, platform: str = "dry_run"):
    ranker = OpportunityRanker(TopicDeriver.derive("cgkn", claim_ledger.require_approved(("claim-1",))))
    metadata = {"relevance": .95, "ability_to_help": .95, "project_mention_fit": .95 if mention else .2, "explicit_tool_request": mention}
    thread = make_thread("reply", metadata, platform=platform)
    opportunity = ranker.rank(thread, community_policy)
    decision = EngagementPolicy.decide(opportunity, community_policy)
    return decision, ReplyDrafter.draft(thread, opportunity, decision, community_policy, claim_ledger)


def test_draft_has_standalone_value_without_project(claim_ledger, community_policy):
    decision, draft = make_draft(claim_ledger, community_policy)
    result = ReplyValidator.validate(draft, decision, community_policy, claim_ledger)
    assert result.status == "PASS"
    assert draft.project_mention is ProjectMention.NONE
    assert "CGKN" not in draft.text


def test_project_mention_is_disclosed_and_grounded(claim_ledger, community_policy):
    decision, draft = make_draft(claim_ledger, community_policy, mention=True)
    result = ReplyValidator.validate(draft, decision, community_policy, claim_ledger)
    assert result.status == "PASS"
    assert "I'm building" in draft.text
    assert draft.claim_ids == ("claim-1",)


def test_unknown_rules_prevent_validation(claim_ledger, community_policy):
    decision, draft = make_draft(claim_ledger, community_policy)
    policy = dataclasses.replace(community_policy, rules_known=False)
    result = ReplyValidator.validate(draft, decision, policy, claim_ledger)
    assert "RULES_UNKNOWN_HUMAN_REVIEW" in result.errors


def test_approval_binds_exact_revision(tmp_path, claim_ledger, community_policy):
    _, draft = make_draft(claim_ledger, community_policy)
    engine = CommunityReplyEngine(CommunityReplyStore(tmp_path / "state.json"), {})
    approval = engine.approve(draft, approved_by="human")
    changed = dataclasses.replace(draft, text=draft.text + " changed", revision=2)
    with pytest.raises(PermissionError, match="exact reply"):
        engine.validate_approval(changed, approval)


def test_draft_only_approval_cannot_publish(tmp_path, claim_ledger, community_policy):
    _, draft = make_draft(claim_ledger, community_policy)
    adapter = FakeCommunityReplyAdapter()
    engine = CommunityReplyEngine(CommunityReplyStore(tmp_path / "state.json"), {adapter.adapter_ref: adapter})
    approval = engine.approve(draft, approved_by="human", level=ReplyApprovalLevel.DRAFT_ONLY)
    with pytest.raises(PermissionError, match="APPROVED_TO_REPLY"):
        engine.execute(draft, approval, community_policy, community="test", adapter_ref=adapter.adapter_ref)


def test_publish_is_restart_safe_and_idempotent(tmp_path, claim_ledger, community_policy):
    _, draft = make_draft(claim_ledger, community_policy)
    adapter = FakeCommunityReplyAdapter()
    path = tmp_path / "state.json"
    engine = CommunityReplyEngine(CommunityReplyStore(path), {adapter.adapter_ref: adapter})
    approval = engine.approve(draft, approved_by="human")
    first = engine.execute(draft, approval, community_policy, community="test", adapter_ref=adapter.adapter_ref)
    second = CommunityReplyEngine(CommunityReplyStore(path), {adapter.adapter_ref: adapter}).execute(draft, approval, community_policy, community="test", adapter_ref=adapter.adapter_ref)
    assert first.status is ReplyStatus.PUBLISHED
    assert second.status is ReplyStatus.ALREADY_REPLIED
    assert adapter.calls == 1


def test_high_spam_risk_cannot_publish(tmp_path, claim_ledger, community_policy):
    _, draft = make_draft(claim_ledger, community_policy)
    draft = dataclasses.replace(draft, spam_risk_score=.9)
    adapter = FakeCommunityReplyAdapter(); engine = CommunityReplyEngine(CommunityReplyStore(tmp_path / "state.json"), {adapter.adapter_ref: adapter})
    with pytest.raises(PermissionError, match="spam"):
        engine.execute(draft, engine.approve(draft, approved_by="human"), community_policy, community="test", adapter_ref=adapter.adapter_ref)


def test_moderator_warning_suppresses_community(tmp_path, claim_ledger, community_policy):
    _, draft = make_draft(claim_ledger, community_policy)
    adapter = FakeCommunityReplyAdapter(mode="moderator_warning"); store = CommunityReplyStore(tmp_path / "state.json")
    engine = CommunityReplyEngine(store, {adapter.adapter_ref: adapter}); approval = engine.approve(draft, approved_by="human")
    receipt = engine.execute(draft, approval, community_policy, community="test", adapter_ref=adapter.adapter_ref)
    state = FollowUpTracker.observe(receipt, adapter, store)
    assert state.suppression_active and store.is_suppressed("test")
    with pytest.raises(PermissionError, match="suppressed"):
        engine.execute(dataclasses.replace(draft, revision=2, draft_id="d2"), engine.approve(dataclasses.replace(draft, revision=2, draft_id="d2"), approved_by="human"), community_policy, community="test", adapter_ref=adapter.adapter_ref)


@pytest.mark.parametrize("mode,expected", [("timeout", ReplyStatus.FAILED_RETRYABLE), ("rate_limit", ReplyStatus.FAILED_RETRYABLE), ("malformed", ReplyStatus.FAILED_FINAL)])
def test_transport_failures_are_classified(tmp_path, claim_ledger, community_policy, mode, expected):
    _, draft = make_draft(claim_ledger, community_policy)
    adapter = FakeCommunityReplyAdapter(mode=mode); engine = CommunityReplyEngine(CommunityReplyStore(tmp_path / f"{mode}.json"), {adapter.adapter_ref: adapter})
    receipt = engine.execute(draft, engine.approve(draft, approved_by="human"), community_policy, community="test", adapter_ref=adapter.adapter_ref)
    assert receipt.status is expected

