from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import tempfile
import urllib.parse
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from cgkn.application.promotion.publish import CredentialResolver, HTTPTransport

from .contracts import (
    CommunityPolicy, CommunityReplyReceipt, FollowUpState, FollowUpStatus, ProjectMention,
    ReplyApproval, ReplyApprovalLevel, ReplyDraft, ReplyStatus, canonical_hash, utc_now,
)


REPLY_ADAPTER_INTERFACE_VERSION = "community-reply-adapter-v1.0"


@dataclass(frozen=True)
class ReplyAdapterResult:
    status: ReplyStatus
    reply_id: str | None
    canonical_url: str | None
    request_ids: tuple[str, ...] = ()
    retryable: bool = False
    error_classification: str | None = None
    redacted_error: str | None = None


class CommunityReplyAdapter(Protocol):
    adapter_ref: str
    platform: str
    features: frozenset[str]

    def validate_credentials(self) -> str: ...
    def validate_target(self, thread_id: str, target_post_id: str) -> str: ...
    def validate_policy(self, policy: CommunityPolicy) -> str: ...
    def create_reply(self, draft: ReplyDraft, idempotency_key: str) -> ReplyAdapterResult: ...
    def fetch_reply(self, reply_id: str) -> ReplyAdapterResult: ...
    def fetch_replies_to_reply(self, reply_id: str) -> tuple[Mapping[str, Any], ...]: ...
    def edit(self, reply_id: str, text: str) -> ReplyAdapterResult: ...
    def delete(self, reply_id: str) -> ReplyAdapterResult: ...
    def fetch_thread_status(self, thread_id: str) -> str: ...


@dataclass
class FakeCommunityReplyAdapter:
    platform: str = "dry_run"
    mode: str = "success"
    adapter_ref: str = "community.reply.fake@1"
    features: frozenset[str] = frozenset({"reply", "fetch", "followup", "edit", "delete"})
    calls: int = 0
    replies: dict[str, str] = dataclasses.field(default_factory=dict)

    def validate_credentials(self) -> str:
        return "AUTH_EXPIRED" if self.mode == "auth_expired" else "VALID"

    def validate_target(self, thread_id: str, target_post_id: str) -> str:
        if self.mode == "thread_deleted": return "THREAD_DELETED"
        if self.mode == "target_edited": return "TARGET_EDITED"
        return "VALID"

    def validate_policy(self, policy: CommunityPolicy) -> str:
        return "VALID" if policy.rules_known and policy.automation_policy != "BLOCKED" else "BLOCKED_POLICY"

    def create_reply(self, draft: ReplyDraft, idempotency_key: str) -> ReplyAdapterResult:
        self.calls += 1
        if self.mode in {"timeout", "timeout_before_response"}:
            return ReplyAdapterResult(ReplyStatus.FAILED_RETRYABLE, None, None, retryable=True, error_classification="TIMEOUT", redacted_error="reply timeout")
        if self.mode == "rate_limit":
            return ReplyAdapterResult(ReplyStatus.FAILED_RETRYABLE, None, None, retryable=True, error_classification="RATE_LIMITED", redacted_error="rate limited")
        if self.mode == "malformed":
            return ReplyAdapterResult(ReplyStatus.FAILED_FINAL, None, None, error_classification="MALFORMED_RESPONSE", redacted_error="missing reply identity")
        reply_id = "reply-" + canonical_hash(idempotency_key)[7:19]
        self.replies[reply_id] = draft.text
        return ReplyAdapterResult(ReplyStatus.PUBLISHED, reply_id, f"dry-run://{reply_id}", ("fake-request-" + str(self.calls),))

    def fetch_reply(self, reply_id: str) -> ReplyAdapterResult:
        if self.mode == "reply_removed" or reply_id not in self.replies:
            return ReplyAdapterResult(ReplyStatus.FAILED_FINAL, reply_id, None, error_classification="REPLY_REMOVED")
        return ReplyAdapterResult(ReplyStatus.PUBLISHED, reply_id, f"dry-run://{reply_id}")

    def fetch_replies_to_reply(self, reply_id: str) -> tuple[Mapping[str, Any], ...]:
        if self.mode == "moderator_warning":
            return ({"post_id": "moderator-1", "kind": "MODERATOR_WARNING", "content": "Please stop promotion."},)
        if self.mode == "followup":
            return ({"post_id": "followup-1", "kind": "DIRECT_QUESTION", "content": "Can you clarify the interface boundary?"},)
        return ()

    def edit(self, reply_id: str, text: str) -> ReplyAdapterResult:
        if reply_id not in self.replies: return ReplyAdapterResult(ReplyStatus.FAILED_FINAL, reply_id, None)
        self.replies[reply_id] = text
        return ReplyAdapterResult(ReplyStatus.PUBLISHED, reply_id, f"dry-run://{reply_id}")

    def delete(self, reply_id: str) -> ReplyAdapterResult:
        self.replies.pop(reply_id, None)
        return ReplyAdapterResult(ReplyStatus.PUBLISHED, reply_id, None)

    def fetch_thread_status(self, thread_id: str) -> str:
        if self.mode == "thread_deleted": return "DELETED"
        if self.mode == "moderator_warning": return "MODERATION_EVENT"
        return "OPEN"


@dataclass
class OfficialHTTPReplyAdapter:
    """Injected official-API transport for GitHub, Mastodon, Bluesky, or Discourse replies."""

    platform: str
    base_url: str
    credential_ref: str
    credentials: CredentialResolver
    transport: HTTPTransport
    account_identity: str = ""
    adapter_ref: str = "community.reply.official-http@1"
    features: frozenset[str] = frozenset({"reply", "fetch"})

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        token = self.credentials.resolve(self.credential_ref)
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": "CGKN-Community-Operator/1.0"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def validate_credentials(self) -> str:
        path = {
            "github": "/user", "mastodon": "/api/v1/accounts/verify_credentials",
            "bluesky": "/xrpc/com.atproto.server.getSession", "discourse": "/session/current.json",
        }.get(self.platform)
        if not path: return "UNSUPPORTED"
        status, _, _ = self.transport.request("GET", self.base_url.rstrip("/") + path, headers=self._headers())
        return "VALID" if status == 200 else "INVALID"

    def validate_target(self, thread_id: str, target_post_id: str) -> str:
        return "VALID" if thread_id and target_post_id else "INVALID_TARGET"

    def validate_policy(self, policy: CommunityPolicy) -> str:
        return "VALID" if policy.rules_known and policy.automation_policy == "OFFICIAL_API_WITH_APPROVAL" else "BLOCKED_POLICY"

    def create_reply(self, draft: ReplyDraft, idempotency_key: str) -> ReplyAdapterResult:
        endpoint, body, id_key, url_key = self._request(draft)
        status, headers, payload = self.transport.request("POST", self.base_url.rstrip("/") + endpoint, headers=self._headers(idempotency_key), json_body=body)
        request_id = headers.get("x-request-id") or headers.get("X-GitHub-Request-Id")
        request_ids = (str(request_id),) if request_id else ()
        if status in {200, 201, 202} and payload.get(id_key):
            reply_id = str(payload[id_key])
            return ReplyAdapterResult(ReplyStatus.PUBLISHED, reply_id, str(payload.get(url_key) or reply_id), request_ids)
        retryable = status == 429 or status >= 500
        return ReplyAdapterResult(ReplyStatus.FAILED_RETRYABLE if retryable else ReplyStatus.FAILED_FINAL, None, None, request_ids, retryable, f"HTTP_{status}", f"provider HTTP {status}")

    def _request(self, draft: ReplyDraft) -> tuple[str, dict[str, Any], str, str]:
        if self.platform == "github":
            parsed = urllib.parse.urlparse(draft.thread_id)
            parts = parsed.path.strip("/").split("/")
            if len(parts) < 4 or parts[2] not in {"issues", "pull"}:
                raise ValueError("GitHub thread identity must be a canonical issue URL")
            return f"/repos/{parts[0]}/{parts[1]}/issues/{parts[3]}/comments", {"body": draft.text}, "id", "html_url"
        if self.platform == "mastodon":
            return "/api/v1/statuses", {"status": draft.text, "in_reply_to_id": draft.target_post_id, "visibility": "public"}, "id", "url"
        if self.platform == "bluesky":
            record = {"$type": "app.bsky.feed.post", "text": draft.text, "createdAt": utc_now(), "reply": {"root": {"uri": draft.thread_id, "cid": draft.target_post_id}, "parent": {"uri": draft.thread_id, "cid": draft.target_post_id}}}
            return "/xrpc/com.atproto.repo.createRecord", {"repo": self.account_identity, "collection": "app.bsky.feed.post", "record": record}, "uri", "uri"
        if self.platform == "discourse":
            return "/posts.json", {"raw": draft.text, "topic_id": draft.thread_id, "reply_to_post_number": draft.target_post_id}, "id", "url"
        raise ValueError("unsupported official reply platform")

    def fetch_reply(self, reply_id: str) -> ReplyAdapterResult:
        return ReplyAdapterResult(ReplyStatus.FAILED_FINAL, reply_id, None, error_classification="FETCH_PLATFORM_SPECIFIC")

    def fetch_replies_to_reply(self, reply_id: str) -> tuple[Mapping[str, Any], ...]:
        return ()

    def edit(self, reply_id: str, text: str) -> ReplyAdapterResult:
        return ReplyAdapterResult(ReplyStatus.FAILED_FINAL, reply_id, None, error_classification="EXPLICIT_EDIT_NOT_CONFIGURED")

    def delete(self, reply_id: str) -> ReplyAdapterResult:
        return ReplyAdapterResult(ReplyStatus.FAILED_FINAL, reply_id, None, error_classification="EXPLICIT_DELETE_NOT_CONFIGURED")

    def fetch_thread_status(self, thread_id: str) -> str:
        return "NOT_EVALUATED"


class CommunityReplyStore:
    def __init__(self, path: pathlib.Path | str) -> None:
        self.path = pathlib.Path(path)
        self._data: dict[str, Any] = {"receipts": {}, "approvals": {}, "suppressions": {}, "experience": []}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            for key, default in (("receipts", {}), ("approvals", {}), ("suppressions", {}), ("experience", [])):
                self._data.setdefault(key, default)

    def save_approval(self, approval: ReplyApproval) -> None:
        self._data["approvals"][approval.approval_id] = dataclasses.asdict(approval); self._flush()

    def receipt_for_key(self, key: str) -> CommunityReplyReceipt | None:
        raw = self._data["receipts"].get(key)
        if not raw: return None
        value = dict(raw); value["status"] = ReplyStatus(value["status"])
        return CommunityReplyReceipt(**value)

    def save_receipt(self, receipt: CommunityReplyReceipt) -> None:
        self._data["receipts"][receipt.idempotency_key] = dataclasses.asdict(receipt); self._flush()

    def suppress(self, community: str, reason: str) -> None:
        self._data["suppressions"][community] = {"reason": reason, "created_at": utc_now()}; self._flush()

    def is_suppressed(self, community: str) -> bool:
        return community in self._data["suppressions"]

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".community-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, sort_keys=True, indent=2, default=lambda item: item.value if hasattr(item, "value") else str(item))
                handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            pathlib.Path(temporary).unlink(missing_ok=True)


class CommunityReplyEngine:
    def __init__(self, store: CommunityReplyStore, adapters: Mapping[str, CommunityReplyAdapter]) -> None:
        self.store = store
        self.adapters = dict(adapters)

    @staticmethod
    def approve(draft: ReplyDraft, *, approved_by: str, level: ReplyApprovalLevel = ReplyApprovalLevel.APPROVED_TO_REPLY) -> ReplyApproval:
        return ReplyApproval(
            "reply-approval-" + canonical_hash({"reply": draft.reply_hash, "actor": approved_by})[7:23], level,
            draft.thread_id, draft.target_post_id, draft.reply_hash, draft.project_mention, draft.links,
            draft.platform, draft.persona_id, draft.revision, approved_by, utc_now(),
        )

    @staticmethod
    def validate_approval(draft: ReplyDraft, approval: ReplyApproval) -> None:
        if approval.level is not ReplyApprovalLevel.APPROVED_TO_REPLY:
            raise PermissionError("APPROVED_TO_REPLY required")
        expected = (
            draft.thread_id, draft.target_post_id, draft.reply_hash, draft.project_mention,
            draft.links, draft.platform, draft.persona_id, draft.revision,
        )
        observed = (
            approval.thread_id, approval.target_post_id, approval.reply_hash, approval.project_mention,
            approval.links, approval.platform, approval.persona_id, approval.revision,
        )
        if expected != observed:
            raise PermissionError("approval does not bind exact reply revision and target")

    def execute(self, draft: ReplyDraft, approval: ReplyApproval, policy: CommunityPolicy, *, community: str, adapter_ref: str, max_retries: int = 1) -> CommunityReplyReceipt:
        self.validate_approval(draft, approval)
        if self.store.is_suppressed(community):
            raise PermissionError("community is suppressed after moderation event")
        if draft.spam_risk_score >= 0.7:
            raise PermissionError("high-spam-risk reply cannot publish")
        key = canonical_hash({"thread": draft.thread_id, "target": draft.target_post_id, "revision": draft.revision, "reply": draft.reply_hash})
        prior = self.store.receipt_for_key(key)
        if prior and prior.status in {ReplyStatus.PUBLISHED, ReplyStatus.ALREADY_REPLIED}:
            return dataclasses.replace(prior, status=ReplyStatus.ALREADY_REPLIED)
        adapter = self.adapters.get(adapter_ref)
        if adapter is None or adapter.platform not in {draft.platform, "dry_run"}:
            raise ValueError("community reply adapter unavailable or platform mismatch")
        if adapter.validate_credentials() != "VALID" or adapter.validate_target(draft.thread_id, draft.target_post_id) != "VALID":
            raise PermissionError("credential or target validation failed")
        if adapter.validate_policy(policy) != "VALID":
            raise PermissionError("community policy forbids automated reply transport")
        attempts = 0
        while True:
            result = adapter.create_reply(draft, key); attempts += 1
            if result.status is ReplyStatus.PUBLISHED or not result.retryable or attempts > max_retries:
                break
        receipt = CommunityReplyReceipt(
            "community-receipt-" + key[7:23], draft.platform, community, draft.thread_id,
            draft.target_post_id, result.reply_id, draft.reply_hash, draft.claim_ids,
            draft.project_mention is not ProjectMention.NONE, draft.links, approval.approval_id,
            approval.binding_hash, adapter_ref, result.request_ids, utc_now(),
            utc_now() if result.status is ReplyStatus.PUBLISHED else None, draft.revision,
            result.status, key, attempts - 1,
        )
        self.store.save_approval(approval); self.store.save_receipt(receipt)
        return receipt


class FollowUpTracker:
    @staticmethod
    def observe(receipt: CommunityReplyReceipt, adapter: CommunityReplyAdapter, store: CommunityReplyStore) -> FollowUpState:
        if not receipt.reply_id:
            return FollowUpState(receipt.thread_id, receipt.reply_receipt_id, FollowUpStatus.NONE, None, False, False, None, False, utc_now())
        thread_status = adapter.fetch_thread_status(receipt.thread_id)
        replies = adapter.fetch_replies_to_reply(receipt.reply_id)
        moderation = next((str(item.get("kind")) for item in replies if str(item.get("kind", "")).startswith("MODERATOR")), None)
        if thread_status == "MODERATION_EVENT" or moderation:
            store.suppress(receipt.community, moderation or "MODERATION_EVENT")
            return FollowUpState(receipt.thread_id, receipt.reply_receipt_id, FollowUpStatus.MODERATION_EVENT, None, False, False, moderation or thread_status, True, utc_now())
        if not replies:
            return FollowUpState(receipt.thread_id, receipt.reply_receipt_id, FollowUpStatus.AWAITING_RESPONSE, None, False, False, None, False, utc_now())
        latest = replies[-1]
        direct = latest.get("kind") == "DIRECT_QUESTION"
        disagreement = latest.get("kind") == "TECHNICAL_DISAGREEMENT"
        status = FollowUpStatus.FOLLOW_UP_CANDIDATE if direct or disagreement else FollowUpStatus.RESPONSE_RECEIVED
        return FollowUpState(receipt.thread_id, receipt.reply_receipt_id, status, str(latest.get("post_id") or ""), direct, disagreement, None, False, utc_now())

