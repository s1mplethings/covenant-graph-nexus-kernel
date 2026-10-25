from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re
import tempfile
from typing import Any, Iterable, Mapping

from .contracts import (
    AttentionAction, AttentionDecision, Commitment, CommitmentLedger, CommitmentStatus,
    EpisodeReference, Familiarity, Goal, GoalKind, GoalStack, IdentityConstitution,
    IdentityDriftStatus, PersonaActionContext, PersonaExperienceRecord, PersonaState,
    PersonaStateReceipt, ReflectionRecord, RelationshipState, SituationKind, SocialSituation,
    SelfModel, SelfModelItem, canonical_hash, utc_now,
)


IDENTITY_POLICY_VERSION = "persona-identity-v1.0"
RELATIONSHIP_POLICY_VERSION = "persona-relationship-evidence-v1.0"
COMMITMENT_POLICY_VERSION = "persona-commitment-explicit-v1.0"
REFLECTION_POLICY_VERSION = "persona-reflection-sparse-evidence-v1.0"
ATTENTION_POLICY_VERSION = "persona-attention-precision-v1.0"
CONTEXT_POLICY_VERSION = "persona-context-localized-v1.0"
SOCIAL_SANDBOX_POLICY_VERSION = "persona-social-sandbox-advisory-v1.0"

_SECRET = re.compile(r"(?i)(authorization|api[_ -]?key|access[_ -]?token|password)\s*[:=]")
_PRIVATE = re.compile(r"(?i)(?:[a-z]:\\|/(?:users|home|private|tmp)/)")
_IDENTITY_INJECTION = re.compile(r"(?i)(from now on|ignore .*instruction|your identity is|pretend (?:you are|to be))")
_SENSITIVE = re.compile(r"(?i)\b(politic\w*|religio\w*|health\w*|diagnos\w*|sexual\w*|ethnic\w*|private identity)\b")


def default_identity() -> IdentityConstitution:
    return IdentityConstitution(
        persona_id="cgnk-project-digital-self-v1",
        public_identity="CGKN project digital persona and AI-assisted project operator",
        mission="Improve evidence-grounded project reasoning and bounded capability execution while preserving human authority.",
        values=("evidence before claims", "admit failures and uncertainty", "prefer measured simplicity", "respect community authority"),
        public_affiliation="First-party CGKN project identity; AI-assisted and never an independent user.",
        communication_principles=("answer concretely", "cite real project evidence", "adapt length without changing values", "avoid generic promotion"),
        social_boundaries=("no human impersonation", "no fabricated experience or emotion", "no sensitive personal inference", "silence is valid"),
        promotion_boundaries=("no hidden affiliation", "no unsupported benchmarks", "no fake testimonials", "no unsolicited calls to action"),
        epistemic_principles=("raw evidence outranks reflection", "absence of evidence is uncertainty", "model output is not evidence"),
        identity_change_policy="Proposal only; a governed human approval and separate receipt are required.",
    )


def initial_state() -> PersonaState:
    identity = default_identity()
    goals = GoalStack((
        Goal("goal-mission", GoalKind.LONG_TERM, identity.mission, "PRODUCT_GOAL.md", 100, change_requires_approval=True),
        Goal("goal-trust", GoalKind.SOCIAL, "Protect long-term community trust over short-term exposure.", "governance/community_status.json", 90),
    ))
    return PersonaState(identity, SelfModel(identity.persona_id), goals)


class PersonaStore:
    """Small versioned state file; Project Knowledge and evidence remain external authorities."""

    def __init__(self, path: pathlib.Path | str) -> None:
        self.path = pathlib.Path(path)

    def save(self, state: PersonaState) -> None:
        value = dataclasses.asdict(state)
        value["state_hash"] = state.state_hash
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, default=lambda item: item.value)
                handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            pathlib.Path(temp_name).unlink(missing_ok=True)

    def load(self) -> PersonaState:
        value = json.loads(self.path.read_text(encoding="utf-8"))
        expected = value.pop("state_hash", None)
        if value.get("schema_version") != "1.0":
            raise ValueError("unsupported persona schema")
        state = _state_from_dict(value)
        if expected != state.state_hash:
            raise ValueError("persona state hash mismatch")
        return state


def _state_from_dict(value: Mapping[str, Any]) -> PersonaState:
    identity = IdentityConstitution(**value["identity"])
    self_model = SelfModel(value["self_model"]["persona_id"], tuple(SelfModelItem(**item) for item in value["self_model"].get("items", ())))
    goals = GoalStack(tuple(Goal(**{**item, "kind": GoalKind(item["kind"])}) for item in value["goals"]["goals"]))
    episodes = tuple(EpisodeReference(**item) for item in value.get("episodes", ()))
    reflections = tuple(ReflectionRecord(**item) for item in value.get("reflections", ()))
    relationships = tuple(RelationshipState(**{**item, "familiarity": Familiarity(item["familiarity"])}) for item in value.get("relationships", ()))
    commitments = CommitmentLedger(tuple(Commitment(**{**item, "status": CommitmentStatus(item["status"])}) for item in value.get("commitments", {}).get("commitments", ())))
    experiences = tuple(PersonaExperienceRecord(**item) for item in value.get("experiences", ()))
    receipts = tuple(PersonaStateReceipt(**item) for item in value.get("receipts", ()))
    return PersonaState(identity, self_model, goals, episodes, reflections, relationships, commitments, experiences, receipts, int(value.get("revision", 1)))


class PersonaEngine:
    def __init__(self, state: PersonaState | None = None) -> None:
        self.state = state or initial_state()

    @staticmethod
    def _safe_text(*values: str) -> None:
        text = "\n".join(values)
        if _SECRET.search(text) or _PRIVATE.search(text):
            raise ValueError("private or secret material cannot enter persona state")

    def _commit(self, state: PersonaState, change_kind: str, evidence_refs: Iterable[str], policy: str) -> PersonaStateReceipt:
        receipt = PersonaStateReceipt(
            "persona-receipt-" + canonical_hash({"before": self.state.state_hash, "after": state.state_hash, "kind": change_kind})[7:23],
            change_kind, self.state.state_hash, state.state_hash, tuple(evidence_refs), policy,
        )
        self.state = dataclasses.replace(state, receipts=state.receipts + (receipt,))
        return receipt

    def record_episode(self, episode: EpisodeReference) -> PersonaStateReceipt:
        if any(item.episode_id == episode.episode_id for item in self.state.episodes):
            raise ValueError("duplicate episode")
        self._safe_text(episode.context, episode.action, episode.result, episode.expectation, episode.surprise)
        state = dataclasses.replace(self.state, episodes=self.state.episodes + (episode,), revision=self.state.revision + 1)
        return self._commit(state, "EPISODE_RECORDED", episode.evidence_refs, "persona-episode-reference-v1.0")

    def update_relationship(self, subject_ref: str, episode_id: str, *, topics: Iterable[str] = (),
                            explicit_preferences: Iterable[str] = (), recent_tone: str = "neutral",
                            relationship_type: str = "public technical contact") -> PersonaStateReceipt:
        episode = next((item for item in self.state.episodes if item.episode_id == episode_id and subject_ref in item.people_refs), None)
        if episode is None:
            raise ValueError("relationship update requires a matching observed episode")
        preferences = tuple(dict.fromkeys(explicit_preferences))
        if any(_SENSITIVE.search(item) for item in preferences):
            raise ValueError("sensitive relationship inference rejected")
        current = next((item for item in self.state.relationships if item.subject_ref == subject_ref), None)
        count = (current.interaction_count if current else 0) + 1
        familiarity = Familiarity.NEW if count == 1 else Familiarity.KNOWN if count < 3 else Familiarity.REPEATED
        relationship = RelationshipState(
            subject_ref, relationship_type, current.first_interaction if current else episode.happened_at,
            episode.happened_at, count, tuple(dict.fromkeys((current.shared_topics if current else ()) + tuple(topics))),
            current.explicit_interests if current else (), current.unresolved_questions if current else (),
            current.commitment_ids if current else (), tuple(dict.fromkeys((current.explicit_preferences if current else ()) + preferences)),
            current.familiarity if current and current.familiarity in {Familiarity.COLLABORATIVE, Familiarity.PROJECT_PARTICIPANT} else familiarity,
            tuple(dict.fromkeys((current.trust_evidence if current else ()) + episode.evidence_refs)),
            current.boundaries if current else ("use only thread-relevant public history",), recent_tone,
            tuple(dict.fromkeys((current.evidence_refs if current else ()) + episode.evidence_refs)),
        )
        relationships = tuple(item for item in self.state.relationships if item.subject_ref != subject_ref) + (relationship,)
        state = dataclasses.replace(self.state, relationships=relationships, revision=self.state.revision + 1)
        return self._commit(state, "RELATIONSHIP_UPDATED", episode.evidence_refs, RELATIONSHIP_POLICY_VERSION)

    def create_commitment(self, commitment: Commitment) -> PersonaStateReceipt:
        if any(item.commitment_id == commitment.commitment_id for item in self.state.commitments.commitments):
            raise ValueError("duplicate commitment")
        state = dataclasses.replace(self.state, commitments=CommitmentLedger(self.state.commitments.commitments + (commitment,)), revision=self.state.revision + 1)
        return self._commit(state, "COMMITMENT_CREATED", (commitment.evidence_ref,), COMMITMENT_POLICY_VERSION)

    def transition_commitment(self, commitment_id: str, status: CommitmentStatus, evidence_refs: Iterable[str]) -> PersonaStateReceipt:
        refs = tuple(evidence_refs)
        if status is CommitmentStatus.FULFILLED and not refs:
            raise ValueError("fulfillment requires evidence")
        found = False; updated = []
        for item in self.state.commitments.commitments:
            if item.commitment_id == commitment_id:
                found = True; updated.append(dataclasses.replace(item, status=status, fulfillment_evidence=refs or item.fulfillment_evidence))
            else: updated.append(item)
        if not found: raise KeyError(commitment_id)
        state = dataclasses.replace(self.state, commitments=CommitmentLedger(tuple(updated)), revision=self.state.revision + 1)
        return self._commit(state, "COMMITMENT_" + status.value, refs, COMMITMENT_POLICY_VERSION)

    def reflect(self, record: ReflectionRecord) -> PersonaStateReceipt:
        known = {ref for episode in self.state.episodes for ref in episode.evidence_refs}
        if set(record.evidence_refs) - known:
            raise ValueError("reflection cites unknown evidence")
        if _IDENTITY_INJECTION.search(record.lesson):
            raise ValueError("reflection injection rejected")
        self._safe_text(record.lesson, record.applicability)
        state = dataclasses.replace(self.state, reflections=self.state.reflections + (record,), revision=self.state.revision + 1)
        return self._commit(state, "REFLECTION_RECORDED", record.evidence_refs, REFLECTION_POLICY_VERSION)

    def apply_self_update(self, item: SelfModelItem, reflection_id: str) -> PersonaStateReceipt:
        reflection = next((row for row in self.state.reflections if row.reflection_id == reflection_id), None)
        if reflection is None or set(item.evidence_refs) - set(reflection.evidence_refs):
            raise ValueError("self update is not supported by qualified reflection")
        items = tuple(row for row in self.state.self_model.items if row.item_id != item.item_id) + (item,)
        state = dataclasses.replace(self.state, self_model=SelfModel(self.state.identity.persona_id, items), revision=self.state.revision + 1)
        return self._commit(state, "SELF_MODEL_UPDATED", item.evidence_refs, REFLECTION_POLICY_VERSION)

    def build_situation(self, *, situation_id: str, platform: str, community_ref: str, subject_ref: str | None,
                        public_text: str, metadata: Mapping[str, Any]) -> SocialSituation:
        relationship = next((item for item in self.state.relationships if item.subject_ref == subject_ref), None)
        direct = bool(metadata.get("direct_mention")); invited = bool(metadata.get("invited"))
        if metadata.get("moderation_event"): kind = SituationKind.MODERATION_CONTEXT
        elif metadata.get("maintainer_only"): kind = SituationKind.MAINTAINER_ONLY_ROADMAP
        elif metadata.get("our_repository"): kind = SituationKind.OUR_REPOSITORY_SUPPORT
        elif relationship: kind = SituationKind.FOLLOW_UP_FROM_KNOWN_PERSON
        elif direct: kind = SituationKind.DIRECT_MENTION
        elif metadata.get("promotion_sensitive"): kind = SituationKind.PROMOTION_SENSITIVE_COMMUNITY
        elif metadata.get("technical_dispute"): kind = SituationKind.DISPUTED_TECHNICAL_DISCUSSION
        elif metadata.get("technical"): kind = SituationKind.OUTSIDER_TECHNICAL_DISCUSSION
        elif not public_text.strip(): kind = SituationKind.INSUFFICIENT_CONTEXT
        else: kind = SituationKind.CASUAL_SOCIAL_INTERACTION
        role = "project_operator" if metadata.get("our_repository") else "invited_project_representative" if invited else "outsider"
        history = relationship.evidence_refs[-3:] if relationship else ()
        risk = .9 if kind in {SituationKind.MODERATION_CONTEXT, SituationKind.MAINTAINER_ONLY_ROADMAP} else .7 if metadata.get("promotion_sensitive") else .25
        return SocialSituation(situation_id, kind, platform, community_ref, subject_ref, role,
                               str(metadata.get("authority_holder", "community maintainers")), str(metadata.get("intent", "unknown")),
                               history, tuple(metadata.get("stakes", ("community trust",))), bool(metadata.get("rules_known")),
                               direct, invited, bool(metadata.get("promotion_sensitive")), risk)

    def decide_attention(self, situation: SocialSituation, *, ability_to_help: float, unique_contribution: bool,
                         freshness: float = 1.0) -> AttentionDecision:
        due = next((item for item in self.state.commitments.commitments if item.subject_ref == situation.subject_ref and item.status is CommitmentStatus.DUE), None)
        reasons = []
        if due:
            action = AttentionAction.FULFILL_COMMITMENT; reasons.append("DUE_COMMITMENT")
        elif situation.kind in {SituationKind.MODERATION_CONTEXT, SituationKind.MAINTAINER_ONLY_ROADMAP}:
            action = AttentionAction.HUMAN_REVIEW; reasons.append("AUTHORITY_OR_MODERATION_RISK")
        elif not situation.community_rules_known:
            action = AttentionAction.HUMAN_REVIEW; reasons.append("COMMUNITY_RULES_UNKNOWN")
        elif situation.kind is SituationKind.FOLLOW_UP_FROM_KNOWN_PERSON and unique_contribution:
            action = AttentionAction.FOLLOW_UP; reasons.append("RELEVANT_RELATIONSHIP_HISTORY")
        elif situation.direct_mention and ability_to_help >= .6 and unique_contribution:
            action = AttentionAction.ACT; reasons.extend(("DIRECT_MENTION", "UNIQUE_CONTRIBUTION"))
        elif freshness < .25 or ability_to_help < .55 or not unique_contribution:
            action = AttentionAction.IGNORE; reasons.append("NO_CURRENT_UNIQUE_CONTRIBUTION")
        else:
            action = AttentionAction.WAIT; reasons.append("PRECISION_FIRST")
        return AttentionDecision(action, tuple(reasons), due.commitment_id if due else None, unique_contribution, action not in {AttentionAction.IGNORE, AttentionAction.WAIT}, ATTENTION_POLICY_VERSION)

    def build_action_context(self, situation: SocialSituation, *, knowledge_refs: Iterable[str] = (), claim_ids: Iterable[str] = (),
                             capability_refs: Iterable[str] = (), max_episodes: int = 3, max_self_items: int = 4,
                             max_goals: int = 4, max_chars: int = 12000) -> PersonaActionContext:
        relationship = next((item for item in self.state.relationships if item.subject_ref == situation.subject_ref), None)
        candidate_episodes = [item for item in self.state.episodes if situation.subject_ref in item.people_refs or situation.community_ref in item.community_refs]
        candidate_episodes.sort(key=lambda item: (-item.importance, item.happened_at, item.episode_id))
        episodes = tuple(dataclasses.asdict(item) for item in candidate_episodes[:max_episodes])
        self_items = tuple(dataclasses.asdict(item) for item in self.state.self_model.items if item.status == "ACTIVE")[:max_self_items]
        goals = tuple(dataclasses.asdict(item) for item in sorted(self.state.goals.goals, key=lambda item: -item.priority) if item.status == "ACTIVE")[:max_goals]
        commitments = tuple(dataclasses.asdict(item) for item in self.state.commitments.commitments if item.status in {CommitmentStatus.OPEN, CommitmentStatus.DUE} and (item.subject_ref == situation.subject_ref or item.scope == "project"))
        identity = dataclasses.asdict(self.state.identity); relation = dataclasses.asdict(relationship) if relationship else None
        parts = {"identity_chars": len(json.dumps(identity, default=str)), "self_model_chars": len(json.dumps(self_items, default=str)),
                 "episode_chars": len(json.dumps(episodes, default=str)), "relationship_chars": len(json.dumps(relation, default=str)),
                 "goal_chars": len(json.dumps(goals, default=str)), "commitment_chars": len(json.dumps(commitments, default=str)),
                 "knowledge_chars": len(json.dumps(tuple(knowledge_refs))), "thread_chars": len(json.dumps(dataclasses.asdict(situation), default=str))}
        parts["total_chars"] = sum(parts.values()); parts["estimated_tokens"] = (parts["total_chars"] + 3) // 4
        if parts["total_chars"] > max_chars: raise ValueError("PERSONA_CONTEXT_BUDGET_EXCEEDED")
        payload = {"identity": identity, "self_model": self_items, "goals": goals, "situation": dataclasses.asdict(situation),
                   "episodes": episodes, "relationship": relation, "commitments": commitments,
                   "knowledge_refs": tuple(knowledge_refs), "claim_ids": tuple(claim_ids), "capability_refs": tuple(capability_refs), "budgets": parts}
        return PersonaActionContext(**payload, context_hash=canonical_hash(payload))

    def identity_guard(self, text: str, *, project_mentioned: bool, disclosure_present: bool,
                       evidence_refs: Iterable[str] = ()) -> IdentityDriftStatus:
        if _IDENTITY_INJECTION.search(text): return IdentityDriftStatus.VIOLATION
        if project_mentioned and not disclosure_present: return IdentityDriftStatus.VIOLATION
        if re.search(r"(?i)\b(i am human|independent user|personally felt|my private life)\b", text): return IdentityDriftStatus.VIOLATION
        if re.search(r"(?i)\b(we tested|we found|we measured|we initially expected)\b", text) and not tuple(evidence_refs):
            return IdentityDriftStatus.NEEDS_HUMAN_REVIEW
        if re.search(r"(?i)\b(best|revolutionary|guaranteed)\b", text): return IdentityDriftStatus.TENSION
        return IdentityDriftStatus.CONSISTENT

    def record_experience(self, record: PersonaExperienceRecord) -> PersonaStateReceipt:
        state = dataclasses.replace(self.state, experiences=self.state.experiences + (record,), revision=self.state.revision + 1)
        return self._commit(state, "EXPERIENCE_RECORDED", record.evidence_refs, "persona-experience-v1.0")


class SocialSandbox:
    ROLES = ("MAINTAINER", "CURIOUS_DEVELOPER", "SKEPTICAL_EXPERT", "SPAM_SENSITIVE_MODERATOR", "NEWCOMER", "POTENTIAL_CONTRIBUTOR", "PROJECT_USER")

    @classmethod
    def rehearse(cls, *, public_thread: str, draft: str, community_policy: Mapping[str, Any],
                 disclosure: str, approved_claims: Iterable[str], roles: Iterable[str] | None = None) -> dict[str, Any]:
        selected = tuple(roles or cls.ROLES[:5])
        if not 3 <= len(selected) <= 6 or set(selected) - set(cls.ROLES): raise ValueError("sandbox requires 3-6 known synthetic roles")
        text = draft.casefold(); promotion = bool(re.search(r"\b(check out|star|follow us|best tool|revolutionary)\b", text))
        outsider = bool(community_policy.get("maintainer_only"))
        disclosure_missing = ("cgnk" in text or "cgkn" in text) and not disclosure.strip()
        unsupported = any(phrase in text for phrase in ("100%", "guaranteed", "everyone loves")) or ("we tested" in text and not tuple(approved_claims))
        generic = not any(token in text for token in set(re.findall(r"[a-z0-9_]{5,}", public_thread.casefold())))
        results = []
        for role in selected:
            risk = sum((promotion, outsider, disclosure_missing, unsupported, generic and role in {"MAINTAINER", "SKEPTICAL_EXPERT"}))
            results.append({"role": role, "perceived_usefulness": "LOW" if generic else "MEDIUM", "promotion_concern": promotion,
                            "credibility_concern": unsupported or disclosure_missing, "outsider_concern": outsider,
                            "likely_follow_up": "What evidence supports this?" if unsupported else None,
                            "misunderstanding_risk": "HIGH" if disclosure_missing else "LOW", "social_risk": min(1.0, risk / 3)})
        max_risk = max(item["social_risk"] for item in results)
        aggregate = "SOCIAL_REHEARSAL_HIGH_RISK" if max_risk >= .67 else "SOCIAL_REHEARSAL_WARNING" if max_risk >= .34 else "SOCIAL_REHEARSAL_PASS"
        return {"policy_version": SOCIAL_SANDBOX_POLICY_VERSION, "synthetic_only": True, "authority": "ADVISORY_ONLY",
                "writes_relationship_state": False, "writes_project_knowledge": False, "approval_bypass": False,
                "roles": results, "aggregate": aggregate, "sandbox_hash": canonical_hash(results)}


class PersonaCommunityBridge:
    """Adds bounded continuity before Community drafting; Community remains the policy/write authority."""

    @staticmethod
    def prepare(engine: PersonaEngine, thread: Any, policy: Any, *, ability_to_help: float,
                unique_contribution: bool, knowledge_refs: Iterable[str] = (), claim_ids: Iterable[str] = ()) -> dict[str, Any]:
        target = thread.posts[-1]
        metadata = dict(target.public_metadata)
        metadata.update({"rules_known": bool(policy.rules_known), "promotion_sensitive": policy.self_promotion != "ALLOWED",
                         "technical": True, "authority_holder": "community maintainers", "intent": "public technical discussion"})
        situation = engine.build_situation(situation_id="situation-" + canonical_hash({"thread": thread.thread_id, "post": target.post_id})[7:23],
                                           platform=thread.platform, community_ref=thread.community,
                                           subject_ref=target.author_public_identity, public_text=target.content, metadata=metadata)
        attention = engine.decide_attention(situation, ability_to_help=ability_to_help, unique_contribution=unique_contribution,
                                            freshness=float(metadata.get("freshness", 1.0)))
        context = engine.build_action_context(situation, knowledge_refs=knowledge_refs, claim_ids=claim_ids,
                                              capability_refs=("community.prepare_context@1", "community.draft_reply@1"))
        return {"situation": dataclasses.asdict(situation), "attention": dataclasses.asdict(attention),
                "context": dataclasses.asdict(context), "advisory_only": True, "community_gate_required": True,
                "public_write_approval_required": True, "external_write_executed": False}
