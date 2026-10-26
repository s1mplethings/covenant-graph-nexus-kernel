from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import tempfile
import urllib.parse
import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .contracts import (
    AdapterResult, Approval, ApprovalLevel, ContentVariant, MediaAsset, PlatformAnalyticsSnapshot,
    Privacy, PublicationPlan, PublicationReceipt, PublicationStatus, TransportStatus, canonical_hash, utc_now,
)


PUBLISHER_INTERFACE_VERSION = "promotion-publisher-v1.0"
SCHEDULER_POLICY_VERSION = "promotion-local-scheduler-v1.0"


class CredentialResolver(Protocol):
    def resolve(self, opaque_ref: str) -> str: ...


class EnvironmentCredentialResolver:
    """Resolve opaque references without ever returning them in evidence."""

    def __init__(self, mapping: Mapping[str, str]) -> None:
        self._mapping = dict(mapping)

    def resolve(self, opaque_ref: str) -> str:
        name = self._mapping.get(opaque_ref)
        if not name:
            raise KeyError("unknown credential reference")
        value = os.environ.get(name)
        if not value:
            raise RuntimeError("credential unavailable")
        return value


class HTTPTransport(Protocol):
    def request(
        self, method: str, url: str, *, headers: Mapping[str, str], json_body: Mapping[str, Any] | None = None,
        body: bytes | None = None, timeout: float = 30.0,
    ) -> tuple[int, Mapping[str, str], Mapping[str, Any]]: ...


class PublisherAdapter(Protocol):
    adapter_ref: str
    platform: str
    features: frozenset[str]

    def validate_credentials(self) -> str: ...
    def validate_content(self, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> None: ...
    def publish(self, plan: PublicationPlan, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> AdapterResult: ...
    def fetch_status(self, platform_post_id: str) -> AdapterResult: ...
    def fetch_metrics(self, platform_post_id: str) -> PlatformAnalyticsSnapshot: ...
    def delete(self, platform_post_id: str) -> AdapterResult: ...
    def cancel(self, platform_post_id: str) -> AdapterResult: ...


@dataclass
class FakePublisherAdapter:
    platform: str = "dry_run"
    mode: str = "success"
    adapter_ref: str = "promotion.publisher.dry-run@1"
    features: frozenset[str] = frozenset({"text", "image", "video", "schedule", "analytics", "cancel"})

    def validate_credentials(self) -> str:
        return "NOT_REQUIRED"

    def validate_content(self, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> None:
        if variant.platform not in {self.platform, "dry_run"}:
            raise ValueError("variant platform does not match adapter")
        if any(not pathlib.Path(asset.path).is_file() for asset in assets):
            raise ValueError("media asset missing")

    def publish(self, plan: PublicationPlan, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> AdapterResult:
        self.validate_content(variant, assets)
        if self.mode == "timeout":
            return AdapterResult(self.platform, TransportStatus.TIMEOUT, None, None, utc_now(), retryable=True, error_classification="TIMEOUT", redacted_error="publisher timeout")
        if self.mode == "rate_limit":
            return AdapterResult(self.platform, TransportStatus.RATE_LIMITED, None, None, utc_now(), retryable=True, error_classification="RATE_LIMITED", redacted_error="rate limited")
        if self.mode == "malformed":
            return AdapterResult(self.platform, TransportStatus.MALFORMED_RESPONSE, None, None, utc_now(), retryable=False, error_classification="MALFORMED_RESPONSE", redacted_error="missing provider identity")
        post_id = "dry-" + canonical_hash({"key": plan.idempotency_key})[7:19]
        return AdapterResult(self.platform, TransportStatus.SUCCESS, post_id, f"dry-run://{post_id}", utc_now(), published_at=utc_now(), media_ids=tuple(a.asset_id for a in assets), provider_request_ids=("dry-request-" + post_id,), retryable=False)

    def fetch_status(self, platform_post_id: str) -> AdapterResult:
        return AdapterResult(self.platform, TransportStatus.SUCCESS, platform_post_id, f"dry-run://{platform_post_id}", utc_now(), published_at=utc_now())

    def fetch_metrics(self, platform_post_id: str) -> PlatformAnalyticsSnapshot:
        return PlatformAnalyticsSnapshot(self.platform, platform_post_id, utc_now(), {}, "NOT_AVAILABLE")

    def delete(self, platform_post_id: str) -> AdapterResult:
        return AdapterResult(self.platform, TransportStatus.SUCCESS, platform_post_id, None, utc_now())

    def cancel(self, platform_post_id: str) -> AdapterResult:
        return self.delete(platform_post_id)


def _transport_result(platform: str, status: int, headers: Mapping[str, str], body: Mapping[str, Any], *, id_key: str, url_key: str = "url") -> AdapterResult:
    request_id = headers.get("x-request-id") or headers.get("X-Request-Id")
    request_ids = (str(request_id),) if request_id else ()
    if status in {200, 201, 202} and body.get(id_key):
        raw_url = str(body.get(url_key) or "")
        parsed = urllib.parse.urlparse(raw_url)
        safe_url = raw_url if parsed.scheme in {"https", "http", "at", "dry-run"} else None
        return AdapterResult(platform, TransportStatus.SUCCESS, str(body[id_key])[:512], safe_url, utc_now(), published_at=utc_now(), provider_request_ids=request_ids)
    classification = {401: TransportStatus.AUTH_EXPIRED, 403: TransportStatus.SCOPE_MISSING, 429: TransportStatus.RATE_LIMITED}.get(status, TransportStatus.FAILED)
    retryable = status == 429 or status >= 500
    return AdapterResult(platform, classification, None, None, utc_now(), provider_request_ids=request_ids, retryable=retryable, error_classification=classification.value, redacted_error=f"provider HTTP {status}")


@dataclass
class MastodonPublisherAdapter:
    base_url: str
    credential_ref: str
    credentials: CredentialResolver
    transport: HTTPTransport
    platform: str = "mastodon"
    adapter_ref: str = "promotion.publisher.mastodon@1"
    features: frozenset[str] = frozenset({"text", "image", "video", "schedule", "analytics", "delete"})

    def _headers(self, plan: PublicationPlan | None = None) -> dict[str, str]:
        value = {"Authorization": "Bearer " + self.credentials.resolve(self.credential_ref)}
        if plan:
            value["Idempotency-Key"] = plan.idempotency_key
        return value

    def validate_credentials(self) -> str:
        status, _, _ = self.transport.request("GET", self.base_url.rstrip("/") + "/api/v1/accounts/verify_credentials", headers=self._headers())
        return "VALID" if status == 200 else "INVALID"

    def validate_content(self, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> None:
        if variant.platform != self.platform or len(variant.text) > 500:
            raise ValueError("mastodon content constraint violation")
        if len(assets) > 4:
            raise ValueError("mastodon media limit exceeded")

    def publish(self, plan: PublicationPlan, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> AdapterResult:
        self.validate_content(variant, assets)
        body: dict[str, Any] = {"status": variant.text, "visibility": variant.visibility}
        media_ids: list[str] = []
        for asset in assets:
            boundary = "cgkn-" + asset.content_hash[7:23]
            name = pathlib.Path(asset.path).name
            payload = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                f"Content-Type: {asset.media_type}\r\n\r\n"
            ).encode("utf-8") + pathlib.Path(asset.path).read_bytes() + f"\r\n--{boundary}--\r\n".encode("ascii")
            headers = self._headers(plan); headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            upload_status, _, upload = self.transport.request("POST", self.base_url.rstrip("/") + "/api/v2/media", headers=headers, body=payload)
            if upload_status not in {200, 201, 202} or not upload.get("id"):
                return AdapterResult(self.platform, TransportStatus.FAILED, None, None, utc_now(), retryable=upload_status >= 500, error_classification="MEDIA_UPLOAD_FAILED", redacted_error=f"provider HTTP {upload_status}")
            media_ids.append(str(upload["id"]))
        if media_ids:
            body["media_ids"] = media_ids
        if plan.scheduled_at:
            body["scheduled_at"] = plan.scheduled_at
        status, headers, payload = self.transport.request("POST", self.base_url.rstrip("/") + "/api/v1/statuses", headers=self._headers(plan), json_body=body)
        return dataclasses.replace(_transport_result(self.platform, status, headers, payload, id_key="id"), media_ids=tuple(media_ids))

    def fetch_status(self, platform_post_id: str) -> AdapterResult:
        status, headers, payload = self.transport.request("GET", self.base_url.rstrip("/") + "/api/v1/statuses/" + platform_post_id, headers=self._headers())
        return _transport_result(self.platform, status, headers, payload, id_key="id")

    def fetch_metrics(self, platform_post_id: str) -> PlatformAnalyticsSnapshot:
        status, _, payload = self.transport.request("GET", self.base_url.rstrip("/") + "/api/v1/statuses/" + platform_post_id, headers=self._headers())
        if status != 200:
            return PlatformAnalyticsSnapshot(self.platform, platform_post_id, utc_now(), {}, "NOT_AVAILABLE")
        metrics = {key: int(payload.get(key, 0)) for key in ("replies_count", "reblogs_count", "favourites_count")}
        return PlatformAnalyticsSnapshot(self.platform, platform_post_id, utc_now(), metrics, "AVAILABLE")

    def delete(self, platform_post_id: str) -> AdapterResult:
        status, headers, payload = self.transport.request("DELETE", self.base_url.rstrip("/") + "/api/v1/statuses/" + platform_post_id, headers=self._headers())
        if status in {200, 202, 204}:
            return AdapterResult(self.platform, TransportStatus.SUCCESS, platform_post_id, None, utc_now(), provider_request_ids=tuple(filter(None, (headers.get("x-request-id"),))))
        return _transport_result(self.platform, status, headers, payload, id_key="id")

    def cancel(self, platform_post_id: str) -> AdapterResult:
        return self.delete(platform_post_id)


@dataclass
class BlueskyPublisherAdapter:
    service_url: str
    repository_did: str
    credential_ref: str
    credentials: CredentialResolver
    transport: HTTPTransport
    platform: str = "bluesky"
    adapter_ref: str = "promotion.publisher.bluesky@1"
    features: frozenset[str] = frozenset({"text", "image", "status"})

    def _headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.credentials.resolve(self.credential_ref), "Content-Type": "application/json"}

    def validate_credentials(self) -> str:
        status, _, _ = self.transport.request("GET", self.service_url.rstrip("/") + "/xrpc/com.atproto.server.getSession", headers=self._headers())
        return "VALID" if status == 200 else "INVALID"

    def validate_content(self, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> None:
        if variant.platform != self.platform or len(variant.text) > 300:
            raise ValueError("bluesky content constraint violation")
        if len(assets) > 4:
            raise ValueError("bluesky image limit exceeded")

    def publish(self, plan: PublicationPlan, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> AdapterResult:
        self.validate_content(variant, assets)
        images: list[dict[str, Any]] = []
        for asset in assets:
            if not asset.media_type.startswith("image/"):
                raise ValueError("bluesky v1 adapter supports image assets only")
            raw = pathlib.Path(asset.path).read_bytes()
            if len(raw) > 2_000_000:
                raise ValueError("bluesky image exceeds 2 MB")
            headers = self._headers(); headers["Content-Type"] = asset.media_type
            upload_status, _, upload = self.transport.request("POST", self.service_url.rstrip("/") + "/xrpc/com.atproto.repo.uploadBlob", headers=headers, body=raw)
            if upload_status not in {200, 201} or not upload.get("blob"):
                return AdapterResult(self.platform, TransportStatus.FAILED, None, None, utc_now(), retryable=upload_status >= 500, error_classification="MEDIA_UPLOAD_FAILED", redacted_error=f"provider HTTP {upload_status}")
            images.append({"alt": str(variant.metadata.get("alt_text", variant.title or "CGKN project update")), "image": upload["blob"]})
        record: dict[str, Any] = {"$type": "app.bsky.feed.post", "text": variant.text, "createdAt": utc_now()}
        if images:
            record["embed"] = {"$type": "app.bsky.embed.images", "images": images}
        body = {"repo": self.repository_did, "collection": "app.bsky.feed.post", "rkey": plan.idempotency_key[:32], "record": record}
        status, headers, payload = self.transport.request("POST", self.service_url.rstrip("/") + "/xrpc/com.atproto.repo.createRecord", headers=self._headers(), json_body=body)
        result = _transport_result(self.platform, status, headers, payload, id_key="uri", url_key="uri")
        if result.platform_post_id:
            result = dataclasses.replace(result, canonical_url=str(payload.get("uri")))
        return result

    def fetch_status(self, platform_post_id: str) -> AdapterResult:
        return AdapterResult(self.platform, TransportStatus.UNSUPPORTED, platform_post_id, None, utc_now(), error_classification="FETCH_STATUS_REQUIRES_RECORD_KEY")

    def fetch_metrics(self, platform_post_id: str) -> PlatformAnalyticsSnapshot:
        return PlatformAnalyticsSnapshot(self.platform, platform_post_id, utc_now(), {}, "NOT_AVAILABLE")

    def delete(self, platform_post_id: str) -> AdapterResult:
        rkey = platform_post_id.rsplit("/", 1)[-1]
        body = {"repo": self.repository_did, "collection": "app.bsky.feed.post", "rkey": rkey}
        status, headers, payload = self.transport.request("POST", self.service_url.rstrip("/") + "/xrpc/com.atproto.repo.deleteRecord", headers=self._headers(), json_body=body)
        if status in {200, 202, 204}:
            return AdapterResult(self.platform, TransportStatus.SUCCESS, platform_post_id, None, utc_now(), provider_request_ids=tuple(filter(None, (headers.get("x-request-id"),))))
        return _transport_result(self.platform, status, headers, payload, id_key="uri")

    def cancel(self, platform_post_id: str) -> AdapterResult:
        return self.delete(platform_post_id)


@dataclass
class YouTubePublisherAdapter:
    credential_ref: str
    credentials: CredentialResolver
    transport: HTTPTransport
    platform: str = "youtube"
    adapter_ref: str = "promotion.publisher.youtube@1"
    features: frozenset[str] = frozenset({"video", "status", "analytics", "delete"})
    upload_url: str = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.credentials.resolve(self.credential_ref), "Content-Type": "application/octet-stream"}

    def validate_credentials(self) -> str:
        status, _, _ = self.transport.request("GET", "https://www.googleapis.com/youtube/v3/channels?part=id&mine=true", headers=self._headers())
        return "VALID" if status == 200 else "INVALID"

    def validate_content(self, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> None:
        videos = [item for item in assets if item.media_type.startswith("video/")]
        if variant.platform != self.platform or not variant.title or not videos:
            raise ValueError("youtube requires title and video")
        if len(variant.title) > 100:
            raise ValueError("youtube title too long")

    def publish(self, plan: PublicationPlan, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> AdapterResult:
        self.validate_content(variant, assets)
        video = next(item for item in assets if item.media_type.startswith("video/"))
        metadata = {"snippet": {"title": variant.title, "description": variant.description, "tags": list(variant.hashtags)}, "status": {"privacyStatus": variant.visibility}}
        headers = self._headers(); headers["X-CGKN-Metadata"] = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        status, response_headers, payload = self.transport.request("POST", self.upload_url, headers=headers, body=pathlib.Path(video.path).read_bytes(), timeout=120.0)
        result = _transport_result(self.platform, status, response_headers, payload, id_key="id")
        if result.platform_post_id:
            result = dataclasses.replace(result, canonical_url="https://youtu.be/" + result.platform_post_id)
        return result

    def fetch_status(self, platform_post_id: str) -> AdapterResult:
        status, headers, payload = self.transport.request("GET", "https://www.googleapis.com/youtube/v3/videos?part=status&id=" + platform_post_id, headers=self._headers())
        item = (payload.get("items") or [{}])[0]
        return _transport_result(self.platform, status, headers, {"id": item.get("id"), "url": "https://youtu.be/" + platform_post_id}, id_key="id")

    def fetch_metrics(self, platform_post_id: str) -> PlatformAnalyticsSnapshot:
        status, _, payload = self.transport.request("GET", "https://www.googleapis.com/youtube/v3/videos?part=statistics&id=" + platform_post_id, headers=self._headers())
        if status != 200 or not payload.get("items"):
            return PlatformAnalyticsSnapshot(self.platform, platform_post_id, utc_now(), {}, "NOT_AVAILABLE")
        raw = payload["items"][0].get("statistics", {})
        metrics = {key: int(raw[key]) for key in ("viewCount", "likeCount", "commentCount") if key in raw}
        return PlatformAnalyticsSnapshot(self.platform, platform_post_id, utc_now(), metrics, "AVAILABLE")

    def delete(self, platform_post_id: str) -> AdapterResult:
        status, headers, _ = self.transport.request("DELETE", "https://www.googleapis.com/youtube/v3/videos?id=" + platform_post_id, headers=self._headers())
        if status in {200, 202, 204}:
            return AdapterResult(self.platform, TransportStatus.SUCCESS, platform_post_id, None, utc_now(), provider_request_ids=tuple(filter(None, (headers.get("x-request-id"),))))
        return AdapterResult(self.platform, TransportStatus.FAILED, platform_post_id, None, utc_now(), error_classification=f"HTTP_{status}", redacted_error=f"provider HTTP {status}")

    def cancel(self, platform_post_id: str) -> AdapterResult:
        return self.delete(platform_post_id)


@dataclass
class PostizBridgeAdapter:
    base_url: str
    credential_ref: str
    credentials: CredentialResolver
    transport: HTTPTransport
    platform: str = "postiz_bridge"
    adapter_ref: str = "promotion.publisher.postiz-bridge@1"
    features: frozenset[str] = frozenset({"text", "image", "video", "schedule", "analytics"})

    def _headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.credentials.resolve(self.credential_ref), "Content-Type": "application/json"}

    def validate_credentials(self) -> str:
        status, _, _ = self.transport.request("GET", self.base_url.rstrip("/") + "/public/v1/integrations", headers=self._headers())
        return "VALID" if status == 200 else "INVALID"

    def validate_content(self, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> None:
        if not variant.claim_ids:
            raise ValueError("bridge accepts only pre-grounded content")

    def publish(self, plan: PublicationPlan, variant: ContentVariant, assets: tuple[MediaAsset, ...]) -> AdapterResult:
        self.validate_content(variant, assets)
        payload = {"content": variant.text, "platform": variant.metadata.get("target_platform"), "scheduledAt": plan.scheduled_at, "idempotencyKey": plan.idempotency_key, "media": [a.content_hash for a in assets]}
        status, headers, body = self.transport.request("POST", self.base_url.rstrip("/") + "/public/v1/posts", headers=self._headers(), json_body=payload)
        return _transport_result(self.platform, status, headers, body, id_key="id")

    def fetch_status(self, platform_post_id: str) -> AdapterResult:
        status, headers, body = self.transport.request("GET", self.base_url.rstrip("/") + "/public/v1/posts/" + platform_post_id, headers=self._headers())
        return _transport_result(self.platform, status, headers, body, id_key="id")

    def fetch_metrics(self, platform_post_id: str) -> PlatformAnalyticsSnapshot:
        status, _, body = self.transport.request("GET", self.base_url.rstrip("/") + "/public/v1/analytics/post/" + platform_post_id, headers=self._headers())
        metrics = body.get("metrics", {}) if status == 200 else {}
        safe = {str(key): float(value) for key, value in metrics.items() if isinstance(value, (int, float))}
        return PlatformAnalyticsSnapshot(self.platform, platform_post_id, utc_now(), safe, "AVAILABLE" if status == 200 else "NOT_AVAILABLE")

    def delete(self, platform_post_id: str) -> AdapterResult:
        status, headers, body = self.transport.request("DELETE", self.base_url.rstrip("/") + "/public/v1/posts/" + platform_post_id, headers=self._headers())
        if status in {200, 202, 204}:
            return AdapterResult(self.platform, TransportStatus.SUCCESS, platform_post_id, None, utc_now(), provider_request_ids=tuple(filter(None, (headers.get("x-request-id"),))))
        return _transport_result(self.platform, status, headers, body, id_key="id")

    def cancel(self, platform_post_id: str) -> AdapterResult:
        return self.delete(platform_post_id)


class PublicationStore:
    """Atomic local publication state; PublicationPlan remains schedule authority."""

    def __init__(self, path: pathlib.Path | str) -> None:
        self.path = pathlib.Path(path)
        self._data: dict[str, Any] = {"plans": {}, "receipts": {}, "approvals": {}, "jobs": {}}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            self._data.setdefault("jobs", {})

    def save_approval(self, approval: Approval) -> None:
        self._data["approvals"][approval.approval_id] = dataclasses.asdict(approval); self._flush()

    def save_plan(self, plan: PublicationPlan) -> None:
        prior = self._data["plans"].get(plan.plan_id)
        if prior and prior["content_hash"] != plan.content_hash:
            raise ValueError("plan revision changed content under the same identity")
        self._data["plans"][plan.plan_id] = dataclasses.asdict(plan); self._flush()

    def receipt_for_key(self, key: str) -> PublicationReceipt | None:
        raw = self._data["receipts"].get(key)
        return PublicationReceipt(**raw) if raw else None

    def save_receipt(self, receipt: PublicationReceipt) -> None:
        self._data["receipts"][receipt.idempotency_key] = dataclasses.asdict(receipt); self._flush()

    def save_job(self, plan: PublicationPlan, variant: ContentVariant, assets: tuple[MediaAsset, ...], approval: Approval) -> None:
        self._data["jobs"][plan.plan_id] = {"plan": dataclasses.asdict(plan), "variant": dataclasses.asdict(variant), "assets": [dataclasses.asdict(a) for a in assets], "approval": dataclasses.asdict(approval), "state": "QUEUED"}
        self._flush()

    def update_job_state(self, plan_id: str, state: str) -> None:
        if plan_id in self._data["jobs"]:
            self._data["jobs"][plan_id]["state"] = state; self._flush()

    def queued_jobs(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(value for value in self._data["jobs"].values() if value.get("state") == "QUEUED")

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".promotion-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, sort_keys=True, indent=2, default=lambda x: x.value if hasattr(x, "value") else str(x)); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            pathlib.Path(name).unlink(missing_ok=True)


class PublicationEngine:
    def __init__(self, store: PublicationStore, adapters: Mapping[str, PublisherAdapter]) -> None:
        self.store = store; self.adapters = dict(adapters)

    @staticmethod
    def validate_approval(plan: PublicationPlan, variant: ContentVariant, assets: tuple[MediaAsset, ...], approval: Approval, *, allow_schedule: bool = False) -> None:
        if plan.privacy is not Privacy.PUBLIC:
            raise PermissionError("private preview cannot be externally published")
        valid_levels = {ApprovalLevel.APPROVED_TO_PUBLISH, ApprovalLevel.APPROVED_TO_SCHEDULE} if allow_schedule else {ApprovalLevel.APPROVED_TO_PUBLISH}
        if approval.level not in valid_levels:
            raise PermissionError("explicit publish approval required")
        if approval.campaign_id != plan.campaign_id or approval.approval_id != plan.approval_id:
            raise PermissionError("approval identity mismatch")
        if approval.binding_hash != plan.approval_binding_hash:
            raise PermissionError("approval binding mismatch")
        if variant.content_hash not in approval.content_hashes or plan.content_hash != variant.content_hash:
            raise PermissionError("approval does not bind exact content")
        if tuple(sorted(a.content_hash for a in assets)) != tuple(sorted(approval.media_hashes)):
            raise PermissionError("approval does not bind exact media")
        if plan.platform not in approval.platform_targets:
            raise PermissionError("approval does not bind platform")

    def execute(self, plan: PublicationPlan, variant: ContentVariant, assets: tuple[MediaAsset, ...], approval: Approval) -> PublicationReceipt:
        self.validate_approval(plan, variant, assets, approval)
        prior = self.store.receipt_for_key(plan.idempotency_key)
        if prior and prior.result in {PublicationStatus.PUBLISHED.value, PublicationStatus.ALREADY_PUBLISHED.value}:
            return dataclasses.replace(prior, result=PublicationStatus.ALREADY_PUBLISHED.value)
        if prior and prior.result == PublicationStatus.FAILED_FINAL.value:
            return prior
        if prior and prior.retry_count >= plan.max_retries:
            return prior
        adapter = self.adapters.get(plan.adapter_ref)
        if not adapter or adapter.platform != plan.platform:
            raise ValueError("publisher adapter unavailable or platform mismatch")
        attempts = 0
        while True:
            result = adapter.publish(plan, variant, assets); attempts += 1
            if result.status is TransportStatus.SUCCESS or not result.retryable or attempts > plan.max_retries:
                break
        outcome = PublicationStatus.PUBLISHED.value if result.status is TransportStatus.SUCCESS else (PublicationStatus.FAILED_RETRYABLE.value if result.retryable else PublicationStatus.FAILED_FINAL.value)
        receipt = PublicationReceipt(
            "publication-" + canonical_hash({"key": plan.idempotency_key})[7:23], plan.campaign_id, plan.variant_id,
            plan.platform, plan.content_hash, plan.media_hashes, plan.claim_ids, approval.approval_id,
            approval.binding_hash, plan.adapter_ref, result.provider_request_ids, outcome, result.platform_post_id,
            result.canonical_url, utc_now(), attempts - 1, plan.idempotency_key,
        )
        self.store.save_receipt(receipt)
        return receipt


class PublicationScheduler:
    """Restart-safe local queue; it stores authority but never grants approval."""

    def __init__(self, store: PublicationStore, engine: PublicationEngine) -> None:
        self.store = store; self.engine = engine

    def enqueue(self, plan: PublicationPlan, variant: ContentVariant, assets: tuple[MediaAsset, ...], approval: Approval) -> None:
        self.engine.validate_approval(plan, variant, assets, approval, allow_schedule=True)
        if approval.level not in {ApprovalLevel.APPROVED_TO_SCHEDULE, ApprovalLevel.APPROVED_TO_PUBLISH}:
            raise PermissionError("schedule approval required")
        self.store.save_approval(approval); self.store.save_plan(plan); self.store.save_job(plan, variant, assets, approval)

    def run_due(self, *, now: str | None = None) -> tuple[PublicationReceipt, ...]:
        current = dt.datetime.fromisoformat((now or utc_now()).replace("Z", "+00:00")); receipts: list[PublicationReceipt] = []
        for raw in self.store.queued_jobs():
            plan_data = dict(raw["plan"]); plan_data["privacy"] = Privacy(plan_data["privacy"]); plan_data["status"] = PublicationStatus(plan_data["status"])
            plan = PublicationPlan(**plan_data)
            scheduled = dt.datetime.fromisoformat(plan.scheduled_at.replace("Z", "+00:00")) if plan.scheduled_at else None
            if scheduled and scheduled > current:
                continue
            variant = ContentVariant(**raw["variant"])
            assets = tuple(MediaAsset(**item) for item in raw["assets"])
            approval_data = dict(raw["approval"]); approval_data["level"] = ApprovalLevel(approval_data["level"])
            approval = Approval(**approval_data)
            if approval.level is not ApprovalLevel.APPROVED_TO_PUBLISH:
                continue
            receipt = self.engine.execute(plan, variant, assets, approval)
            receipts.append(receipt)
            if receipt.result in {PublicationStatus.PUBLISHED.value, PublicationStatus.ALREADY_PUBLISHED.value, PublicationStatus.FAILED_FINAL.value}:
                self.store.update_job_state(plan.plan_id, receipt.result)
        return tuple(receipts)

