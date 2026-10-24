from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA_VERSION = "1.0"
_PRIVATE_PATH = re.compile(r"(?i)(?:[a-z]:\\|/(?:users|home|private|tmp)/)")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str:
    if dataclasses.is_dataclass(value):
        value = dataclasses.asdict(value)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


class SignalKind(str, Enum):
    MAJOR_RELEASE = "MAJOR_RELEASE"
    FEATURE = "FEATURE"
    PERFORMANCE = "PERFORMANCE"
    RELIABILITY = "RELIABILITY"
    SECURITY = "SECURITY"
    BENCHMARK_RESULT = "BENCHMARK_RESULT"
    TECHNICAL_INSIGHT = "TECHNICAL_INSIGHT"
    DEMO = "DEMO"
    MILESTONE = "MILESTONE"
    DOCUMENTATION = "DOCUMENTATION"
    COMMUNITY = "COMMUNITY"
    NO_PUBLICATION_VALUE = "NO_PUBLICATION_VALUE"


class Privacy(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE_PREVIEW_ONLY = "PRIVATE_PREVIEW_ONLY"


class ApprovalLevel(str, Enum):
    DRAFT_ONLY = "DRAFT_ONLY"
    APPROVED_TO_SCHEDULE = "APPROVED_TO_SCHEDULE"
    APPROVED_TO_PUBLISH = "APPROVED_TO_PUBLISH"
    REJECTED = "REJECTED"


class PublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    CANCELLED = "CANCELLED"
    ALREADY_PUBLISHED = "ALREADY_PUBLISHED"


class TransportStatus(str, Enum):
    SUCCESS = "SUCCESS"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    AUTH_REVOKED = "AUTH_REVOKED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    SCOPE_MISSING = "SCOPE_MISSING"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PromotionClaim:
    claim_id: str
    text: str
    evidence_ids: tuple[str, ...]
    status: str = "APPROVED"
    public_safe: bool = True
    expires_at: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.claim_id, "claim_id"); _require_text(self.text, "text")
        if not self.evidence_ids:
            raise ValueError("claim requires evidence")
        if _PRIVATE_PATH.search(self.text):
            raise ValueError("claim contains private local path")


@dataclass(frozen=True)
class PromotionEvidencePack:
    project_id: str
    source_commit: str
    evidence_ids: tuple[str, ...]
    public_facts: tuple[str, ...]
    validated_metrics: Mapping[str, float | int | str]
    changed_capabilities: tuple[str, ...]
    before_after_metrics: Mapping[str, Mapping[str, float | int | str]]
    public_safe: bool
    candidate_assets: tuple[str, ...]
    allowed_claims: tuple[PromotionClaim, ...]
    forbidden_private_claims: tuple[str, ...]
    captured_at: str
    privacy: Privacy = Privacy.PRIVATE_PREVIEW_ONLY
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.project_id, "project_id"); _require_text(self.source_commit, "source_commit")
        if not self.evidence_ids or not self.captured_at:
            raise ValueError("evidence identity and captured_at are required")
        for value in self.public_facts:
            if _PRIVATE_PATH.search(value):
                raise ValueError("private local path is not public evidence")

    @property
    def evidence_hash(self) -> str:
        return canonical_hash(dataclasses.asdict(self))


@dataclass(frozen=True)
class PromotionSignal:
    signal_id: str
    project_id: str
    kind: SignalKind
    evidence_hash: str
    evidence_ids: tuple[str, ...]
    public_value: bool
    rationale: str
    detected_at: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.signal_id, "signal_id"); _require_text(self.evidence_hash, "evidence_hash")
        if self.public_value == (self.kind is SignalKind.NO_PUBLICATION_VALUE):
            raise ValueError("signal kind and public value disagree")


@dataclass(frozen=True)
class CampaignBrief:
    campaign_id: str
    signal_id: str
    objective: str
    audience: str
    core_message: str
    approved_claim_ids: tuple[str, ...]
    story_angle: str
    cta: str
    asset_plan: tuple[str, ...]
    platform_targets: tuple[str, ...]
    tone: str
    release_window: str
    risk_class: str
    privacy: Privacy
    created_at: str
    revision: int = 1
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("campaign_id", "signal_id", "objective", "audience", "core_message", "story_angle", "cta"):
            _require_text(getattr(self, name), name)
        if not self.approved_claim_ids or not self.platform_targets:
            raise ValueError("campaign requires approved claims and targets")


@dataclass(frozen=True)
class ContentVariant:
    variant_id: str
    campaign_id: str
    platform: str
    text: str
    title: str = ""
    description: str = ""
    hashtags: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    media_refs: tuple[str, ...] = ()
    thumbnail_refs: tuple[str, ...] = ()
    visibility: str = "public"
    scheduled_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    claim_ids: tuple[str, ...] = ()
    revision: int = 1
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("variant_id", "campaign_id", "platform"):
            _require_text(getattr(self, name), name)
        if not self.text and not self.title:
            raise ValueError("variant requires text or title")
        if not self.claim_ids:
            raise ValueError("variant requires grounded claim IDs")

    @property
    def content_hash(self) -> str:
        return canonical_hash(dataclasses.asdict(self))


@dataclass(frozen=True)
class MediaAsset:
    asset_id: str
    campaign_id: str
    kind: str
    path: str
    media_type: str
    content_hash: str
    source_evidence_ids: tuple[str, ...]
    generator: str
    config_hash: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_evidence_ids or not self.content_hash.startswith("sha256:"):
            raise ValueError("asset requires provenance and hash")


@dataclass(frozen=True)
class Approval:
    approval_id: str
    campaign_id: str
    level: ApprovalLevel
    content_hashes: tuple[str, ...]
    media_hashes: tuple[str, ...]
    platform_targets: tuple[str, ...]
    approved_by: str
    approved_at: str
    schema_version: str = SCHEMA_VERSION

    @property
    def binding_hash(self) -> str:
        return canonical_hash(dataclasses.asdict(self))


@dataclass(frozen=True)
class PublicationPlan:
    plan_id: str
    campaign_id: str
    variant_id: str
    platform: str
    content_hash: str
    media_hashes: tuple[str, ...]
    claim_ids: tuple[str, ...]
    approval_id: str
    approval_binding_hash: str
    adapter_ref: str
    idempotency_key: str
    scheduled_at: str | None
    timezone: str
    privacy: Privacy
    status: PublicationStatus = PublicationStatus.DRAFT
    max_retries: int = 2
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.max_retries < 0 or self.max_retries > 3:
            raise ValueError("bounded retries must be between zero and three")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        if self.scheduled_at:
            try:
                parsed = dt.datetime.fromisoformat(self.scheduled_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("scheduled time must be ISO-8601") from exc
            if parsed.tzinfo is None:
                raise ValueError("scheduled time must be timezone aware")


@dataclass(frozen=True)
class AdapterResult:
    platform: str
    status: TransportStatus
    platform_post_id: str | None
    canonical_url: str | None
    created_at: str
    scheduled_at: str | None = None
    published_at: str | None = None
    media_ids: tuple[str, ...] = ()
    provider_request_ids: tuple[str, ...] = ()
    retryable: bool = False
    error_classification: str | None = None
    redacted_error: str | None = None
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class PublicationReceipt:
    receipt_id: str
    campaign_id: str
    variant_id: str
    platform: str
    content_hash: str
    media_hashes: tuple[str, ...]
    claim_ids: tuple[str, ...]
    approval_id: str
    approval_binding_hash: str
    adapter_ref: str
    provider_request_ids: tuple[str, ...]
    result: str
    platform_post_id: str | None
    canonical_url: str | None
    timestamp: str
    retry_count: int
    idempotency_key: str
    schema_version: str = SCHEMA_VERSION

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(dataclasses.asdict(self))


@dataclass(frozen=True)
class PlatformAnalyticsSnapshot:
    platform: str
    platform_post_id: str
    captured_at: str
    metrics: Mapping[str, int | float]
    status: str
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class PromotionExperienceRecord:
    campaign_id: str
    platform: str
    content_type: str
    hook: str
    claim_ids: tuple[str, ...]
    asset_types: tuple[str, ...]
    published_at: str | None
    aggregate_metrics: Mapping[str, int | float]
    errors: tuple[str, ...]
    known_cost: float | None
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class PromotionVideoPlan:
    campaign_id: str
    aspect_ratio: str
    width: int
    height: int
    duration_seconds: int
    title: str
    captions: tuple[str, ...]
    cta: str
    source_asset_refs: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION

