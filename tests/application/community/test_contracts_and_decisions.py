from __future__ import annotations

import dataclasses

import pytest

from cgkn.application.community.contracts import (
    CommunityPost, EngagementAction, OpportunityDecision, ProjectMention, ReplyDraft, ReplyType,
)
from cgkn.application.community.service import EngagementPolicy, OpportunityRanker, TopicDeriver

from .conftest import make_thread


def ranker(claim_ledger):
    return OpportunityRanker(TopicDeriver.derive("cgkn", claim_ledger.require_approved(("claim-1",))))


def test_contracts_are_frozen_and_hash_stable():
    post = CommunityPost("p", "t", None, "u", "content", "2026-10-25T00:00:00Z")
    with pytest.raises(dataclasses.FrozenInstanceError):
        post.content = "changed"


def test_thread_rejects_retrieved_identity_mismatch():
    with pytest.raises(ValueError, match="identity mismatch"):
        make_thread("bad", {"relevance": .9}).__class__("t", "github", "https://example.invalid", "title", "u", "now", "now", "c", (), (CommunityPost("p", "t", None, "u", "x", "now"),), "x", ("wrong",), .9)


@pytest.mark.parametrize(
    "metadata,expected_priority,expected_action,expected_mention",
    [
        ({"direct_mention": True, "relevance": .95, "ability_to_help": .95, "project_mention_fit": .95}, OpportunityDecision.ENGAGE_HIGH, EngagementAction.ENGAGE_WITH_PROJECT_MENTION, ProjectMention.MENTION_WITH_LINK),
        ({"relevance": .9, "ability_to_help": .9, "project_mention_fit": .2}, OpportunityDecision.ENGAGE_HIGH, EngagementAction.ENGAGE_WITHOUT_MENTION, ProjectMention.NONE),
        ({"relevance": .2, "ability_to_help": .2}, OpportunityDecision.IGNORE, EngagementAction.IGNORE, ProjectMention.NONE),
        ({"relevance": .9, "ability_to_help": .9, "promotion_bait": True}, OpportunityDecision.DRAFT_ONLY, EngagementAction.DRAFT_ONLY, ProjectMention.NONE),
        ({"relevance": .9, "ability_to_help": .9, "security_sensitive": True}, OpportunityDecision.HUMAN_REVIEW, EngagementAction.HUMAN_REVIEW, ProjectMention.NONE),
    ],
)
def test_precision_first_decisions(claim_ledger, community_policy, metadata, expected_priority, expected_action, expected_mention):
    opportunity = ranker(claim_ledger).rank(make_thread("case", metadata), community_policy)
    decision = EngagementPolicy.decide(opportunity, community_policy)
    assert opportunity.priority is expected_priority
    assert decision.action is expected_action
    assert decision.project_mention is expected_mention


def test_unknown_rules_force_human_review(claim_ledger, community_policy):
    policy = dataclasses.replace(community_policy, rules_known=False)
    opportunity = ranker(claim_ledger).rank(make_thread("unknown", {"relevance": .95, "ability_to_help": .95}), policy)
    assert opportunity.priority is OpportunityDecision.HUMAN_REVIEW


def test_mention_fatigue_suppresses_project_reference(claim_ledger, community_policy):
    opportunity = ranker(claim_ledger).rank(make_thread("mention", {"direct_mention": True, "relevance": .95, "ability_to_help": .95, "project_mention_fit": .95}), community_policy)
    decision = EngagementPolicy.decide(opportunity, community_policy, recent_project_mentions=2)
    assert decision.action is EngagementAction.ENGAGE_WITHOUT_MENTION
    assert "MENTION_FATIGUE_OR_POLICY" in decision.reason_codes


def test_reply_contract_rejects_link_without_mention():
    with pytest.raises(ValueError, match="cannot include links"):
        ReplyDraft("d", "o", "t", "p", "github", ReplyType.QUESTION_ANSWER, "useful", ProjectMention.NONE, ("https://example.invalid",), (), ("GENERAL_TECHNICAL_REASONING",), "persona", True, .1, "policy")

