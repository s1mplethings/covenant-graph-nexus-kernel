from __future__ import annotations

import dataclasses
import json
import pathlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .assets import DeterministicAssetRenderer
from .contracts import (
    Approval, ApprovalLevel, CampaignBrief, ContentVariant, MediaAsset, Privacy, PromotionClaim,
    PlatformAnalyticsSnapshot, PromotionEvidencePack, PromotionExperienceRecord, PromotionSignal, PromotionVideoPlan, PublicationPlan, PublicationStatus,
    SignalKind, canonical_hash, utc_now,
)


PROMOTION_SCHEMA_VERSION = "promotion-domain-v1.0"
CLAIM_POLICY_VERSION = "promotion-claim-policy-v1.0"
APPROVAL_POLICY_VERSION = "promotion-approval-policy-v1.0"
MODEL_CONFIG_VERSION = "promotion-deterministic-template-v1.0"
_PATH = re.compile(r"(?i)(?:[a-z]:\\|/(?:users|home|private|tmp)/)")
_SECRET = re.compile(r"(?i)(?:authorization|api[_ -]?key|access[_ -]?token|client[_ -]?secret|password)\s*[:=]")
_NUMBER = re.compile(r"(?<![a-zA-Z])\d+(?:\.\d+)?%?")
_UNSUPPORTED_SUPERLATIVE = re.compile(r"(?i)\b(revolutionary|world.?fastest|best in the world|production.?grade|彻底解决|革命性|全球最快|生产级)\b")


PLATFORM_RULES: dict[str, dict[str, Any]] = {
    "bluesky": {"text_max": 300, "media_max": 4, "requires_title": False, "video": False},
    "mastodon": {"text_max": 500, "media_max": 4, "requires_title": False, "video": True},
    "x": {"text_max": 280, "media_max": 4, "requires_title": False, "video": True},
    "youtube": {"text_max": 5000, "title_max": 100, "media_max": 1, "requires_title": True, "video": True},
    "github": {"text_max": 125000, "title_max": 125, "media_max": 10, "requires_title": True, "video": False},
    "dry_run": {"text_max": 10000, "media_max": 10, "requires_title": False, "video": True},
}


class PromotionClaimLedger:
    def __init__(self, claims: Iterable[PromotionClaim] = ()) -> None:
        self._claims: dict[str, PromotionClaim] = {}
        for claim in claims:
            self.add(claim)

    def add(self, claim: PromotionClaim) -> None:
        if claim.claim_id in self._claims and self._claims[claim.claim_id] != claim:
            raise ValueError("claim identity collision")
        self._claims[claim.claim_id] = claim

    def require_approved(self, claim_ids: Iterable[str]) -> tuple[PromotionClaim, ...]:
        result: list[PromotionClaim] = []
        for claim_id in claim_ids:
            claim = self._claims.get(claim_id)
            if not claim or claim.status != "APPROVED" or not claim.public_safe:
                raise ValueError(f"unapproved claim: {claim_id}")
            result.append(claim)
        if not result:
            raise ValueError("at least one approved claim required")
        return tuple(result)

    def as_dict(self) -> dict[str, Any]:
        return {key: dataclasses.asdict(value) for key, value in sorted(self._claims.items())}


class EvidenceProjector:
    """Project explicit, already-public-safe facts; never infer claims from arbitrary text."""

    @staticmethod
    def project(
        *, project_id: str, source_commit: str, evidence_ids: Iterable[str], facts: Iterable[str],
        metrics: Mapping[str, float | int | str], changed_capabilities: Iterable[str] = (),
        before_after: Mapping[str, Mapping[str, float | int | str]] | None = None,
        candidate_assets: Iterable[str] = (), privacy: Privacy = Privacy.PRIVATE_PREVIEW_ONLY,
    ) -> PromotionEvidencePack:
        clean_facts: list[str] = []
        claims: list[PromotionClaim] = []
        ids = tuple(sorted(set(str(item) for item in evidence_ids if str(item))))
        if not ids:
            raise ValueError("evidence projection requires source IDs")
        for index, fact in enumerate(facts, 1):
            text = str(fact).strip()
            if not text:
                continue
            if _PATH.search(text) or _SECRET.search(text):
                raise ValueError("private or secret-like fact cannot be projected")
            clean_facts.append(text)
            claims.append(PromotionClaim(f"claim-{index:03d}", text, ids))
        for key, value in sorted(metrics.items()):
            text = f"{key.replace('_', ' ')}: {value}"
            if _PATH.search(text) or _SECRET.search(text):
                raise ValueError("unsafe metric")
            claims.append(PromotionClaim(f"metric-{key}", text, ids))
        return PromotionEvidencePack(
            project_id, source_commit, ids, tuple(clean_facts), dict(metrics), tuple(changed_capabilities),
            dict(before_after or {}), True, tuple(candidate_assets), tuple(claims), (), utc_now(), privacy,
        )


class SignalDetector:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def detect(self, pack: PromotionEvidencePack) -> PromotionSignal:
        identity = canonical_hash({"project": pack.project_id, "source": pack.source_commit, "evidence": pack.evidence_hash})
        if identity in self._seen:
            kind, public, reason = SignalKind.NO_PUBLICATION_VALUE, False, "duplicate evidence signal"
        elif any("security" in item.lower() for item in pack.changed_capabilities):
            kind, public, reason = SignalKind.SECURITY, True, "validated security capability change"
        elif pack.before_after_metrics:
            kind, public, reason = SignalKind.PERFORMANCE, True, "validated before/after evidence"
        elif pack.changed_capabilities:
            kind, public, reason = SignalKind.FEATURE, True, "validated capability change"
        elif pack.validated_metrics:
            kind, public, reason = SignalKind.BENCHMARK_RESULT, True, "validated metrics available"
        elif any(term in fact.lower() for fact in pack.public_facts for term in ("release", "milestone", "complete", "pass")):
            kind, public, reason = SignalKind.MILESTONE, True, "validated milestone evidence"
        else:
            kind, public, reason = SignalKind.NO_PUBLICATION_VALUE, False, "no material public change"
        if public:
            self._seen.add(identity)
        return PromotionSignal("signal-" + identity[7:23], pack.project_id, kind, pack.evidence_hash, pack.evidence_ids, public, reason, utc_now())


class CampaignBuilder:
    def __init__(self) -> None:
        self._signals: dict[str, str] = {}

    def build(self, signal: PromotionSignal, pack: PromotionEvidencePack, *, platforms: tuple[str, ...] = ("bluesky", "mastodon", "youtube")) -> CampaignBrief:
        if not signal.public_value:
            raise ValueError("signal has no publication value")
        if signal.signal_id in self._signals:
            raise ValueError("campaign already exists for signal")
        unknown = set(platforms) - set(PLATFORM_RULES)
        if unknown:
            raise ValueError(f"unsupported platform targets: {sorted(unknown)}")
        claim_ids = tuple(claim.claim_id for claim in pack.allowed_claims if claim.public_safe and claim.status == "APPROVED")
        if not claim_ids:
            raise ValueError("campaign needs approved claims")
        campaign_id = "campaign-" + canonical_hash({"signal": signal.signal_id, "claims": claim_ids})[7:23]
        core = pack.public_facts[0] if pack.public_facts else pack.allowed_claims[0].text
        brief = CampaignBrief(
            campaign_id, signal.signal_id, "Explain a verified CGKN project milestone", "developers and local-first automation builders",
            core, claim_ids, "show the measured change and the authority boundary", "Review the evidence and follow the project",
            ("project_card", "short_video"), platforms, "technical, precise, non-promotional", "manual approval window", "MEDIUM",
            pack.privacy, utc_now(),
        )
        self._signals[signal.signal_id] = campaign_id
        return brief


class ContentGenerator:
    """Deterministic baseline route; Provider-backed drafting can replace this bounded executor."""

    @staticmethod
    def generate(brief: CampaignBrief, ledger: PromotionClaimLedger) -> tuple[ContentVariant, ...]:
        claims = ledger.require_approved(brief.approved_claim_ids)
        primary = claims[0].text.rstrip(".")
        secondary = claims[1].text.rstrip(".") if len(claims) > 1 else "Evidence is linked to the exact source revision"
        variants: list[ContentVariant] = []
        for platform in brief.platform_targets:
            if platform == "youtube":
                title = ("CGKN: " + brief.core_message)[:100]
                text = f"{primary}. {secondary}. {brief.cta}."
                variants.append(ContentVariant(f"{brief.campaign_id}-youtube-r1", brief.campaign_id, platform, text, title, text, ("CGKN", "LocalFirst"), (), (), (), "private", None, {"format": "16:9", "route": "deterministic"}, tuple(c.claim_id for c in claims), 1))
            else:
                text = f"{primary}. {secondary}. {brief.cta}."
                limit = int(PLATFORM_RULES[platform]["text_max"])
                if len(text) > limit:
                    text = (primary + ". " + brief.cta + ".")[:limit]
                variants.append(ContentVariant(f"{brief.campaign_id}-{platform}-r1", brief.campaign_id, platform, text, hashtags=("CGKN", "LocalFirst"), visibility="public", metadata={"route": "deterministic"}, claim_ids=tuple(c.claim_id for c in claims), revision=1))
        return tuple(variants)


class DraftValidator:
    @staticmethod
    def validate(variant: ContentVariant, brief: CampaignBrief, ledger: PromotionClaimLedger) -> dict[str, Any]:
        claims = ledger.require_approved(variant.claim_ids)
        if set(variant.claim_ids) - set(brief.approved_claim_ids):
            raise ValueError("variant uses claim outside campaign")
        public_text = " ".join((variant.title, variant.text, variant.description, *variant.links))
        if _PATH.search(public_text):
            raise ValueError("private local path leakage")
        if _SECRET.search(public_text):
            raise ValueError("secret-like content leakage")
        if _UNSUPPORTED_SUPERLATIVE.search(public_text):
            raise ValueError("unsupported superlative")
        allowed_numbers = set(_NUMBER.findall(" ".join(claim.text for claim in claims)))
        observed_numbers = set(_NUMBER.findall(public_text))
        if observed_numbers - allowed_numbers:
            raise ValueError("unsupported numerical claim")
        rules = PLATFORM_RULES[variant.platform]
        if len(variant.text) > int(rules["text_max"]):
            raise ValueError("platform text length exceeded")
        if rules.get("requires_title") and not variant.title:
            raise ValueError("platform title required")
        if variant.title and len(variant.title) > int(rules.get("title_max", 10_000)):
            raise ValueError("platform title length exceeded")
        if any(not link.startswith("https://") for link in variant.links):
            raise ValueError("only HTTPS public links allowed")
        return {"status": "PASS", "claim_ids": list(variant.claim_ids), "content_hash": variant.content_hash, "policy": CLAIM_POLICY_VERSION}


class AnalyticsFeedback:
    """Convert aggregate metrics into rebuildable local experience; never infer project facts."""

    @staticmethod
    def record(brief: CampaignBrief, variant: ContentVariant, snapshot: PlatformAnalyticsSnapshot, *, asset_types: tuple[str, ...] = (), known_cost: float | None = None, errors: tuple[str, ...] = ()) -> PromotionExperienceRecord:
        if snapshot.platform != variant.platform:
            raise ValueError("analytics platform mismatch")
        aggregate = {str(key): float(value) for key, value in snapshot.metrics.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
        return PromotionExperienceRecord(brief.campaign_id, variant.platform, str(variant.metadata.get("format", "text")), brief.story_angle, variant.claim_ids, asset_types, None, aggregate, errors, known_cost)


@dataclass
class PromotionStudio:
    asset_root: pathlib.Path

    def __post_init__(self) -> None:
        self.claims = PromotionClaimLedger()
        self.signals = SignalDetector()
        self.campaigns = CampaignBuilder()
        self.assets = DeterministicAssetRenderer(self.asset_root)

    def prepare_campaign(self, pack: PromotionEvidencePack, *, platforms: tuple[str, ...] = ("bluesky", "mastodon", "youtube")) -> tuple[PromotionSignal, CampaignBrief, tuple[ContentVariant, ...]]:
        for claim in pack.allowed_claims:
            self.claims.add(claim)
        signal = self.signals.detect(pack)
        brief = self.campaigns.build(signal, pack, platforms=platforms)
        variants = ContentGenerator.generate(brief, self.claims)
        for variant in variants:
            DraftValidator.validate(variant, brief, self.claims)
        return signal, brief, variants

    def render_assets(self, brief: CampaignBrief, pack: PromotionEvidencePack) -> tuple[MediaAsset, MediaAsset]:
        claims = self.claims.require_approved(brief.approved_claim_ids)
        card = self.assets.render_card(brief, tuple(item.text for item in claims), pack.evidence_ids)
        video_plan = PromotionVideoPlan(brief.campaign_id, "9:16", 720, 1280, 4, brief.core_message[:60], tuple(item.text for item in claims[:2]), brief.cta, (card.asset_id,))
        video = self.assets.render_video(video_plan, pack.evidence_ids)
        return card, video

    @staticmethod
    def approve(brief: CampaignBrief, variants: tuple[ContentVariant, ...], assets: tuple[MediaAsset, ...], *, actor: str, level: ApprovalLevel = ApprovalLevel.DRAFT_ONLY) -> Approval:
        return Approval("approval-" + canonical_hash({"campaign": brief.campaign_id, "revision": brief.revision, "actor": actor})[7:23], brief.campaign_id, level, tuple(v.content_hash for v in variants), tuple(a.content_hash for a in assets), tuple(v.platform for v in variants), actor, utc_now())

    @staticmethod
    def plan(brief: CampaignBrief, variant: ContentVariant, assets: tuple[MediaAsset, ...], approval: Approval, *, adapter_ref: str, scheduled_at: str | None = None, timezone: str = "UTC") -> PublicationPlan:
        key = canonical_hash({"campaign": brief.campaign_id, "variant": variant.variant_id, "platform": variant.platform, "revision": variant.revision})
        status = PublicationStatus.SCHEDULED if scheduled_at else PublicationStatus.APPROVED
        return PublicationPlan("plan-" + key[7:23], brief.campaign_id, variant.variant_id, variant.platform, variant.content_hash, tuple(a.content_hash for a in assets), variant.claim_ids, approval.approval_id, approval.binding_hash, adapter_ref, key, scheduled_at, timezone, brief.privacy, status)

