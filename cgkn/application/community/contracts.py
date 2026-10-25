from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
_PRIVATE = re.compile(r"(?i)(?:[a-z]:\\|/(?:users|home|private|tmp)/)")
_SECRET = re.compile(r"(?i)(?:authorization|api[_ -]?key|access[_ -]?token|client[_ -]?secret|password)\s*[:=]")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str:
    if dataclasses.is_dataclass(value):
        value = dataclasses.asdict(value)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


class ConnectivityMode(str, Enum):
    READ_WRITE_SUPPORTED = "READ_WRITE_SUPPORTED"
    READ_ONLY_SUPPORTED = "READ_ONLY_SUPPORTED"
    DRAFT_ONLY = "DRAFT_ONLY"
    MANUAL_ONLY = "MANUAL_ONLY"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class OpportunityDecision(str, Enum):
    ENGAGE_HIGH = "ENGAGE_HIGH"
    ENGAGE_MEDIUM = "ENGAGE_MEDIUM"
    DRAFT_ONLY = "DRAFT_ONLY"
    IGNORE = "IGNORE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    BLOCKED_POLICY = "BLOCKED_POLICY"


class EngagementAction(str, Enum):
    ENGAGE_WITHOUT_MENTION = "ENGAGE_WITHOUT_MENTION"
    ENGAGE_WITH_PROJECT_MENTION = "ENGAGE_WITH_PROJECT_MENTION"
    DRAFT_ONLY = "DRAFT_ONLY"
    IGNORE = "IGNORE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    BLOCKED_POLICY = "BLOCKED_POLICY"


class ProjectMention(str, Enum):
    NONE = "NONE"
    MENTION_NO_LINK = "MENTION_NO_LINK"
    MENTION_WITH_LINK = "MENTION_WITH_LINK"


class ReplyType(str, Enum):
    DIRECT_TECHNICAL_HELP = "DIRECT_TECHNICAL_HELP"
    QUESTION_ANSWER = "QUESTION_ANSWER"
    CLARIFICATION = "CLARIFICATION"
    EXPERIENCE_SHARE = "EXPERIENCE_SHARE"
    PROJECT_REFERENCE = "PROJECT_REFERENCE"
    FOLLOW_UP = "FOLLOW_UP"
    CORRECTION = "CORRECTION"
    NO_REPLY = "NO_REPLY"


class ReplyApprovalLevel(str, Enum):
    DRAFT_ONLY = "DRAFT_ONLY"
    APPROVED_TO_REPLY = "APPROVED_TO_REPLY"
    REJECTED = "REJECTED"
    NEEDS_HUMAN_CONTEXT = "NEEDS_HUMAN_CONTEXT"
    BLOCKED_POLICY = "BLOCKED_POLICY"


class ReplyStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ALREADY_REPLIED = "ALREADY_REPLIED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    BLOCKED_APPROVAL = "BLOCKED_APPROVAL"
    BLOCKED_POLICY = "BLOCKED_POLICY"


class FollowUpStatus(str, Enum):
    NONE = "NONE"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    FOLLOW_UP_CANDIDATE = "FOLLOW_UP_CANDIDATE"
    FOLLOW_UP_DRAFTED = "FOLLOW_UP_DRAFTED"
    FOLLOW_UP_APPROVED = "FOLLOW_UP_APPROVED"
    FOLLOW_UP_SENT = "FOLLOW_UP_SENT"
    CLOSED = "CLOSED"
    MODERATION_EVENT = "MODERATION_EVENT"


@dataclass(frozen=True)
class CommunitySource:
    source_id: str
    platform: str
    community_name: str
    community_identity: str
    source_type: str
    read_capability: str
    reply_capability: str
    auth_requirements: tuple[str, ...]
    rules_url: str | None
    automation_policy: str
    rate_limit_metadata: Mapping[str, Any]
    last_scanned: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("source_id", "platform", "community_name", "community_identity", "source_type"):
            _text(getattr(self, name), name)


@dataclass(frozen=True)
class CommunityPolicy:
    source_id: str
    policy_version: str
    rules_known: bool
    self_promotion: str
    link_policy: str
    automation_policy: str
    ai_content_policy: str
    max_replies_per_day: int
    max_project_mentions_per_ten_replies: int
    requires_disclosure: bool = True
    prohibited_topics: tuple[str, ...] = ()
    source_urls: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _text(self.source_id, "source_id")
        if self.max_replies_per_day < 0 or not 0 <= self.max_project_mentions_per_ten_replies <= 10:
            raise ValueError("invalid community rate policy")


@dataclass(frozen=True)
class CommunityPost:
    post_id: str
    thread_id: str
    parent_post_id: str | None
    author_public_identity: str
    content: str
    created_at: str
    edited_at: str | None = None
    links: tuple[str, ...] = ()
    public_metadata: Mapping[str, Any] = field(default_factory=dict)
    our_reply_target: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("post_id", "thread_id", "author_public_identity", "content", "created_at"):
            _text(getattr(self, name), name)


@dataclass(frozen=True)
class CommunityThread:
    thread_id: str
    platform: str
    canonical_url: str
    title: str
    author_public_identity: str
    created_at: str
    last_activity_at: str
    community: str
    tags: tuple[str, ...]
    posts: tuple[CommunityPost, ...]
    thread_summary: str
    retrieved_post_ids: tuple[str, ...]
    cgnk_relevance: float
    current_engagement_state: str = "NEW"
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("thread_id", "platform", "canonical_url", "title", "community"):
            _text(getattr(self, name), name)
        if not self.posts or not 0 <= self.cgnk_relevance <= 1:
            raise ValueError("thread requires posts and normalized relevance")
        if set(self.retrieved_post_ids) != {post.post_id for post in self.posts}:
            raise ValueError("retrieved post identity mismatch")


@dataclass(frozen=True)
class DiscoveryTopicSet:
    topic_set_id: str
    project_id: str
    topics: tuple[str, ...]
    queries: tuple[str, ...]
    source_claim_ids: tuple[str, ...]
    max_queries_per_platform: int
    max_results_per_query: int
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.topics or not self.queries or self.max_queries_per_platform <= 0 or self.max_results_per_query <= 0:
            raise ValueError("bounded topic set required")


@dataclass(frozen=True)
class CommunityScanPlan:
    plan_id: str
    source_ids: tuple[str, ...]
    topic_set_id: str
    cadence: str
    max_results: int
    time_window_hours: int
    community_filters: tuple[str, ...]
    last_cursor: str | None = None
    status: str = "READY"
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_ids or self.max_results <= 0 or self.time_window_hours <= 0:
            raise ValueError("bounded scan plan required")


@dataclass(frozen=True)
class CommunityOpportunity:
    opportunity_id: str
    thread_id: str
    target_post_id: str
    relevance: float
    ability_to_help: float
    discussion_quality: float
    freshness: float
    community_fit: float
    promotion_risk: float
    rule_risk: float
    existing_engagement: float
    project_mention_fit: float
    spam_risk_score: float
    priority: OpportunityDecision
    reason_codes: tuple[str, ...]
    expires_at: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        scores = (
            self.relevance, self.ability_to_help, self.discussion_quality, self.freshness,
            self.community_fit, self.promotion_risk, self.rule_risk, self.existing_engagement,
            self.project_mention_fit, self.spam_risk_score,
        )
        if any(not 0 <= score <= 1 for score in scores):
            raise ValueError("opportunity scores must be normalized")


@dataclass(frozen=True)
class EngagementDecision:
    opportunity_id: str
    action: EngagementAction
    project_mention: ProjectMention
    reason_codes: tuple[str, ...]
    policy_version: str
    human_review_required: bool
    decided_at: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.action is EngagementAction.ENGAGE_WITHOUT_MENTION and self.project_mention is not ProjectMention.NONE:
            raise ValueError("mention conflicts with engagement action")
        if self.action is EngagementAction.ENGAGE_WITH_PROJECT_MENTION and self.project_mention is ProjectMention.NONE:
            raise ValueError("project mention action requires mention")


@dataclass(frozen=True)
class CommunityPersonaProfile:
    persona_id: str
    identity: str
    voice: str
    tone: str
    technical_depth: str
    preferred_response_style: str
    project_mention_behavior: str
    cta_behavior: str
    things_to_avoid: tuple[str, ...]
    disclosure_text: str
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class ReplyDraft:
    draft_id: str
    opportunity_id: str
    thread_id: str
    target_post_id: str
    platform: str
    reply_type: ReplyType
    text: str
    project_mention: ProjectMention
    links: tuple[str, ...]
    claim_ids: tuple[str, ...]
    general_reasoning_labels: tuple[str, ...]
    persona_id: str
    standalone_value: bool
    spam_risk_score: float
    policy_version: str
    revision: int = 1
    created_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _text(self.text, "reply text")
        if self.revision <= 0 or not 0 <= self.spam_risk_score <= 1:
            raise ValueError("invalid reply revision or spam score")
        if self.project_mention is ProjectMention.NONE and self.links:
            raise ValueError("project-free reply cannot include links")
        if self.project_mention is ProjectMention.MENTION_WITH_LINK and not self.links:
            raise ValueError("linked mention requires link")

    @property
    def reply_hash(self) -> str:
        return canonical_hash(dataclasses.asdict(self))


@dataclass(frozen=True)
class ReplyApproval:
    approval_id: str
    level: ReplyApprovalLevel
    thread_id: str
    target_post_id: str
    reply_hash: str
    project_mention: ProjectMention
    links: tuple[str, ...]
    platform: str
    persona_id: str
    revision: int
    approved_by: str
    approved_at: str
    schema_version: str = SCHEMA_VERSION

    @property
    def binding_hash(self) -> str:
        return canonical_hash(dataclasses.asdict(self))


@dataclass(frozen=True)
class CommunityReplyReceipt:
    reply_receipt_id: str
    platform: str
    community: str
    thread_id: str
    target_post_id: str
    reply_id: str | None
    reply_hash: str
    claim_ids: tuple[str, ...]
    mention_flag: bool
    links: tuple[str, ...]
    approval_identity: str
    approval_binding_hash: str
    adapter_ref: str
    request_ids: tuple[str, ...]
    created_at: str
    published_at: str | None
    revision: int
    status: ReplyStatus
    idempotency_key: str
    retry_count: int = 0
    schema_version: str = SCHEMA_VERSION

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(dataclasses.asdict(self))


@dataclass(frozen=True)
class FollowUpState:
    thread_id: str
    reply_receipt_id: str
    status: FollowUpStatus
    last_observed_post_id: str | None
    direct_question: bool
    technical_disagreement: bool
    moderator_event: str | None
    suppression_active: bool
    updated_at: str
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class CommunityExperienceRecord:
    opportunity_id: str
    decision: str
    reply_type: str | None
    mentioned_project: bool
    linked_project: bool
    approval: str
    publication: str
    reply_received: bool
    follow_up: str
    moderation: str | None
    aggregate_metrics: Mapping[str, int | float]
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    known_cost_usd: float | None
    recorded_at: str
    schema_version: str = SCHEMA_VERSION

