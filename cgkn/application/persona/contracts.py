from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str:
    if dataclasses.is_dataclass(value):
        value = dataclasses.asdict(value)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


def _confidence(value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError("confidence must be normalized")


class PersonaDataClass(str, Enum):
    GOVERNED_STABLE = "GOVERNED_STABLE"
    AUTHORITATIVE_PERSONA_STATE = "AUTHORITATIVE_PERSONA_STATE"
    DERIVED_PERSONA_STATE = "DERIVED_PERSONA_STATE"
    EPISODIC_REFERENCE = "EPISODIC_REFERENCE"
    EPHEMERAL_CONTEXT = "EPHEMERAL_CONTEXT"


class Familiarity(str, Enum):
    NEW = "NEW"
    KNOWN = "KNOWN"
    REPEATED = "REPEATED"
    COLLABORATIVE = "COLLABORATIVE"
    PROJECT_PARTICIPANT = "PROJECT_PARTICIPANT"


class CommitmentStatus(str, Enum):
    OPEN = "OPEN"
    DUE = "DUE"
    FULFILLED = "FULFILLED"
    BROKEN = "BROKEN"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class GoalKind(str, Enum):
    LONG_TERM = "LONG_TERM"
    PROJECT_PHASE = "PROJECT_PHASE"
    SOCIAL = "SOCIAL"
    RELATIONSHIP = "RELATIONSHIP"
    ACTIVE_TASK = "ACTIVE_TASK"


class SituationKind(str, Enum):
    OUR_REPOSITORY_SUPPORT = "OUR_REPOSITORY_SUPPORT"
    OUTSIDER_TECHNICAL_DISCUSSION = "OUTSIDER_TECHNICAL_DISCUSSION"
    DIRECT_MENTION = "DIRECT_MENTION"
    FOLLOW_UP_FROM_KNOWN_PERSON = "FOLLOW_UP_FROM_KNOWN_PERSON"
    MAINTAINER_ONLY_ROADMAP = "MAINTAINER_ONLY_ROADMAP"
    PROMOTION_SENSITIVE_COMMUNITY = "PROMOTION_SENSITIVE_COMMUNITY"
    DISPUTED_TECHNICAL_DISCUSSION = "DISPUTED_TECHNICAL_DISCUSSION"
    MODERATION_CONTEXT = "MODERATION_CONTEXT"
    CASUAL_SOCIAL_INTERACTION = "CASUAL_SOCIAL_INTERACTION"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class AttentionAction(str, Enum):
    ACT = "ACT"
    WAIT = "WAIT"
    IGNORE = "IGNORE"
    FOLLOW_UP = "FOLLOW_UP"
    FULFILL_COMMITMENT = "FULFILL_COMMITMENT"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class IdentityDriftStatus(str, Enum):
    CONSISTENT = "CONSISTENT"
    TENSION = "TENSION"
    VIOLATION = "VIOLATION"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


@dataclass(frozen=True)
class IdentityConstitution:
    persona_id: str
    public_identity: str
    mission: str
    values: tuple[str, ...]
    public_affiliation: str
    communication_principles: tuple[str, ...]
    social_boundaries: tuple[str, ...]
    promotion_boundaries: tuple[str, ...]
    epistemic_principles: tuple[str, ...]
    identity_change_policy: str
    schema_version: str = SCHEMA_VERSION
    data_class: PersonaDataClass = PersonaDataClass.GOVERNED_STABLE

    def __post_init__(self) -> None:
        for name in ("persona_id", "public_identity", "mission", "public_affiliation", "identity_change_policy"):
            _required(getattr(self, name), name)
        if not self.values or not self.epistemic_principles:
            raise ValueError("identity values and epistemic principles are required")

    @property
    def identity_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True)
class SelfModelItem:
    item_id: str
    category: str
    statement: str
    confidence: float
    evidence_refs: tuple[str, ...]
    status: str = "ACTIVE"
    supersedes: str | None = None
    last_updated: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _required(self.item_id, "item_id"); _required(self.statement, "statement"); _confidence(self.confidence)
        if not self.evidence_refs:
            raise ValueError("self-model item requires evidence")


@dataclass(frozen=True)
class SelfModel:
    persona_id: str
    items: tuple[SelfModelItem, ...] = ()
    schema_version: str = SCHEMA_VERSION
    data_class: PersonaDataClass = PersonaDataClass.DERIVED_PERSONA_STATE

    def __post_init__(self) -> None:
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("duplicate self-model item")


@dataclass(frozen=True)
class Goal:
    goal_id: str
    kind: GoalKind
    statement: str
    source_ref: str
    priority: int
    status: str = "ACTIVE"
    change_requires_approval: bool = False

    def __post_init__(self) -> None:
        _required(self.goal_id, "goal_id"); _required(self.statement, "statement"); _required(self.source_ref, "source_ref")


@dataclass(frozen=True)
class GoalStack:
    goals: tuple[Goal, ...]
    schema_version: str = SCHEMA_VERSION
    data_class: PersonaDataClass = PersonaDataClass.AUTHORITATIVE_PERSONA_STATE

    def __post_init__(self) -> None:
        if len({goal.goal_id for goal in self.goals}) != len(self.goals):
            raise ValueError("duplicate goal")


@dataclass(frozen=True)
class EpisodeReference:
    episode_id: str
    happened_at: str
    context: str
    action: str
    result: str
    expectation: str
    surprise: str
    evidence_refs: tuple[str, ...]
    people_refs: tuple[str, ...] = ()
    community_refs: tuple[str, ...] = ()
    importance: float = 0.5
    schema_version: str = SCHEMA_VERSION
    data_class: PersonaDataClass = PersonaDataClass.EPISODIC_REFERENCE

    def __post_init__(self) -> None:
        _required(self.episode_id, "episode_id"); _required(self.context, "context")
        if not self.evidence_refs:
            raise ValueError("episode requires existing evidence refs")
        _confidence(self.importance)


@dataclass(frozen=True)
class ReflectionRecord:
    reflection_id: str
    trigger: str
    question: str
    lesson: str
    evidence_refs: tuple[str, ...]
    applicability: str
    confidence: float
    contradictions: tuple[str, ...] = ()
    proposed_self_updates: tuple[str, ...] = ()
    proposed_goal_updates: tuple[str, ...] = ()
    proposed_relationship_updates: tuple[str, ...] = ()
    identity_amendment_proposal: str | None = None
    supersedes: str | None = None
    schema_version: str = SCHEMA_VERSION
    data_class: PersonaDataClass = PersonaDataClass.DERIVED_PERSONA_STATE

    def __post_init__(self) -> None:
        if not self.evidence_refs:
            raise ValueError("reflection requires evidence")
        _confidence(self.confidence)


@dataclass(frozen=True)
class RelationshipState:
    subject_ref: str
    relationship_type: str
    first_interaction: str
    last_interaction: str
    interaction_count: int
    shared_topics: tuple[str, ...]
    explicit_interests: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    commitment_ids: tuple[str, ...]
    explicit_preferences: tuple[str, ...]
    familiarity: Familiarity
    trust_evidence: tuple[str, ...]
    boundaries: tuple[str, ...]
    recent_tone: str
    evidence_refs: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION
    data_class: PersonaDataClass = PersonaDataClass.AUTHORITATIVE_PERSONA_STATE

    def __post_init__(self) -> None:
        _required(self.subject_ref, "subject_ref")
        if self.interaction_count < 1 or not self.evidence_refs:
            raise ValueError("relationship requires observed interaction evidence")


@dataclass(frozen=True)
class Commitment:
    commitment_id: str
    subject_ref: str
    statement: str
    created_at: str
    due_at: str | None
    evidence_ref: str
    source_kind: str
    status: CommitmentStatus
    fulfillment_evidence: tuple[str, ...]
    priority: int
    scope: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.source_kind not in {"ACTUAL_EMITTED_PUBLIC_ACTION", "EXPLICIT_USER_GOVERNANCE"}:
            raise ValueError("commitment source is not authoritative")
        _required(self.evidence_ref, "evidence_ref")
        if self.status is CommitmentStatus.FULFILLED and not self.fulfillment_evidence:
            raise ValueError("fulfilled commitment requires evidence")


@dataclass(frozen=True)
class CommitmentLedger:
    commitments: tuple[Commitment, ...] = ()
    schema_version: str = SCHEMA_VERSION
    data_class: PersonaDataClass = PersonaDataClass.AUTHORITATIVE_PERSONA_STATE

    def __post_init__(self) -> None:
        if len({item.commitment_id for item in self.commitments}) != len(self.commitments):
            raise ValueError("duplicate commitment")


@dataclass(frozen=True)
class SocialSituation:
    situation_id: str
    kind: SituationKind
    platform: str
    community_ref: str
    subject_ref: str | None
    role: str
    authority_holder: str
    user_intent: str
    relevant_history_refs: tuple[str, ...]
    stakes: tuple[str, ...]
    community_rules_known: bool
    direct_mention: bool
    invited: bool
    promotion_sensitive: bool
    social_risk: float
    schema_version: str = SCHEMA_VERSION
    data_class: PersonaDataClass = PersonaDataClass.EPHEMERAL_CONTEXT

    def __post_init__(self) -> None:
        _confidence(self.social_risk)


@dataclass(frozen=True)
class AttentionDecision:
    action: AttentionAction
    reason_codes: tuple[str, ...]
    commitment_id: str | None
    unique_contribution: bool
    approval_required: bool
    policy_version: str
    decided_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class PersonaActionContext:
    identity: Mapping[str, Any]
    self_model: tuple[Mapping[str, Any], ...]
    goals: tuple[Mapping[str, Any], ...]
    situation: Mapping[str, Any]
    episodes: tuple[Mapping[str, Any], ...]
    relationship: Mapping[str, Any] | None
    commitments: tuple[Mapping[str, Any], ...]
    knowledge_refs: tuple[str, ...]
    claim_ids: tuple[str, ...]
    capability_refs: tuple[str, ...]
    budgets: Mapping[str, int]
    context_hash: str
    schema_version: str = SCHEMA_VERSION
    data_class: PersonaDataClass = PersonaDataClass.EPHEMERAL_CONTEXT


@dataclass(frozen=True)
class PersonaActionDecision:
    action: AttentionAction
    draft: str | None
    identity_status: IdentityDriftStatus
    disclosure_required: bool
    approval_required: bool
    evidence_refs: tuple[str, ...]
    capability_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PersonaExperienceRecord:
    experience_id: str
    action_ref: str
    receipt_ref: str | None
    response_ref: str | None
    outcome: str
    relationship_ref: str | None
    commitment_ids: tuple[str, ...]
    reflection_trigger: str | None
    evidence_refs: tuple[str, ...]
    recorded_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.evidence_refs:
            raise ValueError("experience requires evidence")


@dataclass(frozen=True)
class PersonaStateReceipt:
    receipt_id: str
    change_kind: str
    before_hash: str
    after_hash: str
    evidence_refs: tuple[str, ...]
    policy_version: str
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class PersonaState:
    identity: IdentityConstitution
    self_model: SelfModel
    goals: GoalStack
    episodes: tuple[EpisodeReference, ...] = ()
    reflections: tuple[ReflectionRecord, ...] = ()
    relationships: tuple[RelationshipState, ...] = ()
    commitments: CommitmentLedger = field(default_factory=CommitmentLedger)
    experiences: tuple[PersonaExperienceRecord, ...] = ()
    receipts: tuple[PersonaStateReceipt, ...] = ()
    revision: int = 1
    schema_version: str = SCHEMA_VERSION

    @property
    def state_hash(self) -> str:
        return canonical_hash(self)
