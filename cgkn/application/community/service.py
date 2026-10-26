from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from cgkn.application.promotion.contracts import PromotionClaim
from cgkn.application.promotion.service import PromotionClaimLedger

from .contracts import (
    CommunityOpportunity, CommunityPersonaProfile, CommunityPolicy, CommunityPost, CommunityThread,
    DiscoveryTopicSet, EngagementAction, EngagementDecision, OpportunityDecision, ProjectMention,
    ReplyDraft, ReplyType, canonical_hash, utc_now,
)


COMMUNITY_SCHEMA_VERSION = "community-domain-v1.0"
DISCOVERY_POLICY_VERSION = "community-discovery-v1.0"
OPPORTUNITY_POLICY_VERSION = "community-opportunity-precision-v1.0"
ENGAGEMENT_POLICY_VERSION = "community-engagement-v1.0"
PROJECT_MENTION_POLICY_VERSION = "community-project-mention-v1.0"
APPROVAL_POLICY_VERSION = "community-reply-approval-v1.0"
PERSONA_VERSION = "community-persona-transparent-technical-v1.0"
MODEL_CONFIG_VERSION = "community-deterministic-cheap-ready-v1.0"

_PRIVATE = re.compile(r"(?i)(?:[a-z]:\\|/(?:users|home|private|tmp)/)")
_SECRET = re.compile(r"(?i)(?:authorization|api[_ -]?key|access[_ -]?token|client[_ -]?secret|password)\s*[:=]")
_LINK = re.compile(r"https?://\S+")
_PROMOTIONAL = re.compile(r"(?i)\b(star my repo|follow us|check out my product|best tool|revolutionary)\b")
_TOPICS: Mapping[str, tuple[str, ...]] = {
    "structured knowledge retrieval": ("rag", "retrieval augmented", "knowledge graph", "context window", "evidence fidelity"),
    "agent architecture": ("agent architecture", "execution dag", "capability routing", "tool routing", "multi-agent overhead"),
    "reliable generation and repair": ("llm repair", "code repair", "structured output", "interface regression", "deterministic validation"),
    "cost-aware execution": ("cheap model", "strong model", "model routing", "token cost", "local model"),
    "validated capability growth": ("self-growing", "self growth", "capability registry", "tool discovery", "capability reuse"),
}


DEFAULT_PERSONA = CommunityPersonaProfile(
    persona_id="cgnk-community-technical-v1",
    identity="CGNK project builder",
    voice="technical, specific, transparent, and curious",
    tone="helpful and non-salesy",
    technical_depth="explain mechanisms, trade-offs, and limitations",
    preferred_response_style="answer the question first; use compact concrete guidance",
    project_mention_behavior="mention CGNK only when the implementation or measured evidence directly helps",
    cta_behavior="no call to action by default",
    things_to_avoid=("unsupported claims", "hidden affiliation", "generic promotion", "argument escalation", "fabricated experience"),
    disclosure_text="I'm building and testing CGKN, so this is first-party project experience.",
)


class TopicDeriver:
    @staticmethod
    def derive(project_id: str, claims: Iterable[PromotionClaim]) -> DiscoveryTopicSet:
        claim_ids = tuple(sorted(claim.claim_id for claim in claims if claim.public_safe and claim.status == "APPROVED"))
        topics = tuple(_TOPICS)
        # Interleave topic families so a bounded five-query scan does not spend
        # its entire budget on near-synonyms from the first topic.
        families = tuple(_TOPICS.values())
        queries = tuple(dict.fromkeys(
            term for index in range(max(map(len, families))) for terms in families for term in terms[index:index + 1]
        ))
        return DiscoveryTopicSet(
            "topics-" + canonical_hash({"project": project_id, "claims": claim_ids, "queries": queries})[7:23],
            project_id, topics, queries, claim_ids, 5, 10,
        )


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9+_.-]{1,}", text.lower()))


class OpportunityRanker:
    """Precision-first deterministic ranker. Untrusted post text is data only."""

    def __init__(self, topics: DiscoveryTopicSet) -> None:
        self.topics = topics

    def rank(self, thread: CommunityThread, policy: CommunityPolicy) -> CommunityOpportunity:
        target = thread.posts[-1]
        metadata = dict(target.public_metadata)
        text = f"{thread.title}\n{target.content}".lower()
        direct = bool(metadata.get("direct_mention")) or "cgnk" in text or "cgkn" in text
        explicit_tool = bool(metadata.get("explicit_tool_request")) or any(term in text for term in ("recommend a tool", "which tool", "implementation reference", "how do you build"))
        matches = sum(1 for query in self.topics.queries if query in text)
        relevance = float(metadata.get("relevance", min(1.0, matches / 2 + (0.35 if direct else 0))))
        knowledge_gap = bool(metadata.get("knowledge_gap"))
        ability = float(metadata.get("ability_to_help", 0.0 if knowledge_gap else min(1.0, relevance + (0.2 if "?" in text else 0))))
        quality = float(metadata.get("discussion_quality", 0.8 if len(target.content) >= 80 else 0.55))
        freshness = float(metadata.get("freshness", 0.8))
        fit = float(metadata.get("community_fit", 0.8 if thread.platform in {"github", "discourse", "hackernews", "mastodon", "bluesky"} else 0.55))
        duplicate = float(metadata.get("existing_engagement", 1.0 if metadata.get("already_replied") else 0.0))
        promo_risk = float(metadata.get("promotion_risk", 0.9 if metadata.get("promotion_bait") else 0.15))
        rule_risk = float(metadata.get("rule_risk", 0.0 if policy.rules_known else 0.7))
        if policy.self_promotion == "PROHIBITED":
            rule_risk = max(rule_risk, 0.9)
        mention_fit = float(metadata.get("project_mention_fit", 0.95 if direct or explicit_tool else (0.7 if metadata.get("implementation_reference_needed") else 0.2)))
        spam = min(1.0, 0.45 * promo_risk + 0.35 * rule_risk + (0.2 if metadata.get("high_link_density") else 0.0))
        reasons: list[str] = []
        if direct: reasons.append("DIRECT_MENTION")
        if explicit_tool: reasons.append("EXPLICIT_TOOL_REQUEST")
        if relevance >= 0.7: reasons.append("RELEVANT_TECHNICAL_PROBLEM")
        if ability >= 0.7: reasons.append("SUPPORTED_ABILITY_TO_HELP")
        if knowledge_gap: reasons.append("KNOWLEDGE_GAP")
        if duplicate: reasons.append("ALREADY_ENGAGED")
        if not policy.rules_known: reasons.append("RULES_UNKNOWN")
        if policy.self_promotion == "PROHIBITED": reasons.append("SELF_PROMOTION_PROHIBITED")
        if metadata.get("hostile_bait"): reasons.append("HOSTILE_BAIT")
        if metadata.get("security_sensitive"): reasons.append("SECURITY_SENSITIVE")
        if metadata.get("stale") or freshness < 0.25: reasons.append("STALE")

        if metadata.get("blocked_policy"):
            priority = OpportunityDecision.BLOCKED_POLICY
        elif metadata.get("security_sensitive"):
            priority = OpportunityDecision.HUMAN_REVIEW
        elif duplicate or metadata.get("resolved") or metadata.get("hostile_bait") or relevance < 0.55 or ability < 0.55 or freshness < 0.25:
            priority = OpportunityDecision.IGNORE
        elif not policy.rules_known:
            priority = OpportunityDecision.HUMAN_REVIEW
        elif promo_risk >= 0.75 or rule_risk >= 0.75:
            priority = OpportunityDecision.DRAFT_ONLY
        elif direct or (relevance >= 0.85 and ability >= 0.8):
            priority = OpportunityDecision.ENGAGE_HIGH
        else:
            priority = OpportunityDecision.ENGAGE_MEDIUM
        return CommunityOpportunity(
            "opportunity-" + canonical_hash({"thread": thread.thread_id, "target": target.post_id})[7:23],
            thread.thread_id, target.post_id, relevance, ability, quality, freshness, fit, promo_risk,
            rule_risk, duplicate, mention_fit, spam, priority, tuple(reasons),
        )


class EngagementPolicy:
    @staticmethod
    def decide(opportunity: CommunityOpportunity, policy: CommunityPolicy, *, recent_project_mentions: int = 0) -> EngagementDecision:
        reasons = list(opportunity.reason_codes)
        review = False
        if opportunity.priority is OpportunityDecision.BLOCKED_POLICY:
            action, mention, review = EngagementAction.BLOCKED_POLICY, ProjectMention.NONE, True
        elif opportunity.priority is OpportunityDecision.HUMAN_REVIEW:
            action, mention, review = EngagementAction.HUMAN_REVIEW, ProjectMention.NONE, True
        elif opportunity.priority is OpportunityDecision.IGNORE:
            action, mention = EngagementAction.IGNORE, ProjectMention.NONE
        elif opportunity.priority is OpportunityDecision.DRAFT_ONLY:
            action, mention = EngagementAction.DRAFT_ONLY, ProjectMention.NONE
        else:
            mention_allowed = (
                opportunity.project_mention_fit >= 0.75
                and policy.self_promotion != "PROHIBITED"
                and recent_project_mentions < policy.max_project_mentions_per_ten_replies
            )
            if mention_allowed:
                link_allowed = policy.link_policy == "ALLOWED" and (
                    "DIRECT_MENTION" in reasons or "EXPLICIT_TOOL_REQUEST" in reasons
                )
                mention = ProjectMention.MENTION_WITH_LINK if link_allowed else ProjectMention.MENTION_NO_LINK
                action = EngagementAction.ENGAGE_WITH_PROJECT_MENTION
            else:
                mention = ProjectMention.NONE
                action = EngagementAction.ENGAGE_WITHOUT_MENTION
                if opportunity.project_mention_fit >= 0.75:
                    reasons.append("MENTION_FATIGUE_OR_POLICY")
        return EngagementDecision(
            opportunity.opportunity_id, action, mention, tuple(reasons), ENGAGEMENT_POLICY_VERSION,
            review, utc_now(),
        )


@dataclass(frozen=True)
class ReplyValidation:
    status: str
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    validation_hash: str


class ReplyDrafter:
    """Deterministic safe baseline; a cheap bounded executor may replace only draft composition."""

    @staticmethod
    def draft(
        thread: CommunityThread,
        opportunity: CommunityOpportunity,
        decision: EngagementDecision,
        policy: CommunityPolicy,
        claims: PromotionClaimLedger,
        *, persona: CommunityPersonaProfile = DEFAULT_PERSONA,
        project_url: str = "https://github.com/s1mplethings/covenant-graph-nexus-kernel",
    ) -> ReplyDraft:
        if decision.action in {EngagementAction.IGNORE, EngagementAction.BLOCKED_POLICY}:
            raise ValueError("decision does not permit drafting")
        target = next(post for post in thread.posts if post.post_id == opportunity.target_post_id)
        technical = ReplyDrafter._technical_answer(target.content)
        mention = decision.project_mention
        claim_ids: tuple[str, ...] = ()
        links: tuple[str, ...] = ()
        text = technical
        reply_type = ReplyType.DIRECT_TECHNICAL_HELP if "?" in target.content else ReplyType.CLARIFICATION
        if mention is not ProjectMention.NONE:
            available = tuple(claims.as_dict())
            if not available:
                raise ValueError("project mention requires approved project claims")
            approved = claims.require_approved((available[0],))
            claim_ids = (approved[0].claim_id,)
            text += f"\n\n{persona.disclosure_text} One relevant project fact is: {approved[0].text}"
            reply_type = ReplyType.PROJECT_REFERENCE
            if mention is ProjectMention.MENTION_WITH_LINK:
                links = (project_url,)
                text += f" Reference: {project_url}"
        return ReplyDraft(
            "draft-" + canonical_hash({"opportunity": opportunity.opportunity_id, "text": text, "revision": 1})[7:23],
            opportunity.opportunity_id, thread.thread_id, target.post_id, thread.platform, reply_type,
            text, mention, links, claim_ids, ("GENERAL_TECHNICAL_REASONING",), persona.persona_id,
            standalone_value=bool(technical.strip()), spam_risk_score=opportunity.spam_risk_score,
            policy_version=policy.policy_version,
        )

    @staticmethod
    def _technical_answer(content: str) -> str:
        lower = content.lower()
        if any(term in lower for term in ("rag", "retrieval", "context window", "knowledge")):
            return ("A practical way to make retrieval reliable is to keep source observations separate from derived summaries, "
                    "store explicit dependency links, and invalidate only summaries affected by changed evidence. Evaluate retrieval "
                    "with frozen questions and inspect both missed evidence and unsupported answer claims.")
        if any(term in lower for term in ("repair", "regression", "structured output")):
            return ("Treat repair as a bounded state transition: preserve the accepted interface, identify the smallest owning unit, "
                    "apply a typed patch, and rerun that unit plus its dependents. A schema-valid response is not enough; verify the "
                    "result against an external test or observable runtime behavior.")
        if any(term in lower for term in ("cheap model", "strong model", "routing", "cost")):
            return ("Separate decisions from execution before comparing models. Keep project-level choices with the stronger controller, "
                    "give the cheaper executor a bounded contract and direct dependencies, then compare cost per accepted result rather "
                    "than cost per call. Record retries and failed-call usage as part of the total.")
        if any(term in lower for term in ("agent", "dag", "capability", "tool")):
            return ("It helps to separate semantic composition from executable dependencies: keep stable capability identities in a tree, "
                    "compile only runnable dependencies into one DAG, and make each executor accept a narrow typed input. That keeps a tool "
                    "failure from forcing a whole-project replan.")
        return ("The safest next step is to turn the question into a falsifiable contract: state the expected observable result, keep the "
                "input scope small, run one deterministic check, and record the failing boundary before adding more automation.")


class ReplyValidator:
    @staticmethod
    def validate(
        draft: ReplyDraft,
        decision: EngagementDecision,
        policy: CommunityPolicy,
        claims: PromotionClaimLedger,
        *, recent_reply_texts: Iterable[str] = (),
    ) -> ReplyValidation:
        errors: list[str] = []
        warnings: list[str] = []
        if decision.action in {EngagementAction.IGNORE, EngagementAction.BLOCKED_POLICY}:
            errors.append("DECISION_FORBIDS_REPLY")
        if not policy.rules_known:
            errors.append("RULES_UNKNOWN_HUMAN_REVIEW")
        if not draft.standalone_value:
            errors.append("LOW_VALUE_PROMOTIONAL_REPLY")
        if _PRIVATE.search(draft.text) or _SECRET.search(draft.text):
            errors.append("PRIVATE_OR_SECRET_LEAKAGE")
        if _PROMOTIONAL.search(draft.text):
            errors.append("PROMOTIONAL_CTA_FORBIDDEN")
        if draft.project_mention is not ProjectMention.NONE:
            try:
                claims.require_approved(draft.claim_ids)
            except ValueError:
                errors.append("UNSUPPORTED_PROJECT_CLAIM")
            if policy.requires_disclosure and "building" not in draft.text.lower():
                errors.append("HIDDEN_AFFILIATION")
            if policy.self_promotion == "PROHIBITED":
                errors.append("PROJECT_MENTION_BLOCKED_POLICY")
        elif draft.claim_ids:
            errors.append("PROJECT_CLAIM_WITHOUT_DISCLOSED_MENTION")
        if draft.links and policy.link_policy != "ALLOWED":
            errors.append("LINK_BLOCKED_POLICY")
        if tuple(_LINK.findall(draft.text)) != draft.links:
            errors.append("LINK_IDENTITY_MISMATCH")
        if draft.spam_risk_score >= 0.7:
            errors.append("HIGH_SPAM_RISK")
        draft_tokens = _tokens(draft.text)
        for prior in recent_reply_texts:
            prior_tokens = _tokens(prior)
            union = draft_tokens | prior_tokens
            similarity = len(draft_tokens & prior_tokens) / len(union) if union else 0.0
            if similarity >= 0.8:
                errors.append("REPLY_TOO_SIMILAR")
                break
        if decision.human_review_required:
            warnings.append("HUMAN_REVIEW_REQUIRED")
        status = "PASS" if not errors else "FAIL"
        return ReplyValidation(status, tuple(sorted(set(errors))), tuple(sorted(set(warnings))), canonical_hash({"draft": draft.reply_hash, "errors": errors, "warnings": warnings}))

