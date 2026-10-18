from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .contracts import CapabilityPackage, CapabilitySpec
from .service import CapabilityStore, GeneratedCapabilityExecutor, _canonical_hash


class HealthDomainStatus(str, Enum):
    PASS = "PASS"
    REGISTRY_ENTRY_MISSING = "REGISTRY_ENTRY_MISSING"
    REGISTRY_ENTRY_CORRUPT = "REGISTRY_ENTRY_CORRUPT"
    PACKAGE_HASH_MISMATCH = "PACKAGE_HASH_MISMATCH"
    ADMISSION_RECEIPT_INVALID = "ADMISSION_RECEIPT_INVALID"
    PACKAGE_MISSING = "PACKAGE_MISSING"
    PACKAGE_SCHEMA_INVALID = "PACKAGE_SCHEMA_INVALID"
    EXECUTOR_LOAD_FAILURE = "EXECUTOR_LOAD_FAILURE"
    CONTRACT_LOAD_FAILURE = "CONTRACT_LOAD_FAILURE"
    CAPABILITY_DEPENDENCY_MISSING = "CAPABILITY_DEPENDENCY_MISSING"
    DEPENDENCY_HASH_DRIFT = "DEPENDENCY_HASH_DRIFT"
    DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
    INVALID_COMPOSITE_RISK = "INVALID_COMPOSITE_RISK"
    NOT_PROBED = "NOT_PROBED"


class ExternalAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    EXTERNAL_TRANSIENT_FAILURE = "EXTERNAL_TRANSIENT_FAILURE"
    EXTERNAL_RATE_LIMITED = "EXTERNAL_RATE_LIMITED"
    EXTERNAL_NOT_FOUND = "EXTERNAL_NOT_FOUND"
    EXTERNAL_AUTH_REQUIRED = "EXTERNAL_AUTH_REQUIRED"
    EXTERNAL_FORBIDDEN = "EXTERNAL_FORBIDDEN"
    EXTERNAL_UPSTREAM_5XX = "EXTERNAL_UPSTREAM_5XX"
    EXTERNAL_NETWORK_FAILURE = "EXTERNAL_NETWORK_FAILURE"
    EXTERNAL_RESPONSE_INVALID = "EXTERNAL_RESPONSE_INVALID"
    ENVIRONMENT_BLOCKED = "ENVIRONMENT_BLOCKED"
    NOT_PROBED = "NOT_PROBED"


@dataclass(frozen=True)
class ExternalHealthClassification:
    status: ExternalAvailability
    error_class: str
    retryable: bool
    status_code: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "error_class": self.error_class,
            "retryable": self.retryable,
            "status_code": self.status_code,
        }


@dataclass(frozen=True)
class CapabilityHealthReport:
    capability_ref: str
    registry_integrity: HealthDomainStatus
    package_integrity: HealthDomainStatus
    dependency_integrity: HealthDomainStatus
    external_availability: ExternalAvailability = ExternalAvailability.NOT_PROBED
    details: Mapping[str, Any] | None = None

    @property
    def local_healthy(self) -> bool:
        return all(value is HealthDomainStatus.PASS for value in (self.registry_integrity, self.package_integrity, self.dependency_integrity))

    @property
    def registry_regression(self) -> bool:
        return not self.local_healthy

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "CapabilityHealthReport",
            "schema_version": "1.0",
            "capability_ref": self.capability_ref,
            "domains": {
                "REGISTRY_INTEGRITY": self.registry_integrity.value,
                "PACKAGE_INTEGRITY": self.package_integrity.value,
                "DEPENDENCY_INTEGRITY": self.dependency_integrity.value,
                "EXTERNAL_AVAILABILITY": self.external_availability.value,
            },
            "local_healthy": self.local_healthy,
            "registry_regression": self.registry_regression,
            "details": dict(self.details or {}),
        }


def classify_github_response(status_code: int, body: str = "", headers: Mapping[str, str] | None = None) -> ExternalHealthClassification:
    lowered = body.lower()
    normalized_headers = {str(key).lower(): str(value).lower() for key, value in (headers or {}).items()}
    rate_limited = "rate limit" in lowered or normalized_headers.get("x-ratelimit-remaining") == "0"
    if 200 <= status_code < 300:
        try:
            value = json.loads(body)
        except json.JSONDecodeError:
            return ExternalHealthClassification(ExternalAvailability.EXTERNAL_RESPONSE_INVALID, "GITHUB_RESPONSE_INVALID", False, status_code)
        if not isinstance(value, dict):
            return ExternalHealthClassification(ExternalAvailability.EXTERNAL_RESPONSE_INVALID, "GITHUB_SCHEMA_MISMATCH", False, status_code)
        return ExternalHealthClassification(ExternalAvailability.AVAILABLE, "PASS", False, status_code)
    if status_code in {403, 429} and rate_limited:
        return ExternalHealthClassification(ExternalAvailability.EXTERNAL_RATE_LIMITED, "GITHUB_RATE_LIMITED", True, status_code)
    if status_code == 401:
        return ExternalHealthClassification(ExternalAvailability.EXTERNAL_AUTH_REQUIRED, "GITHUB_AUTH_REQUIRED", False, status_code)
    if status_code == 403:
        return ExternalHealthClassification(ExternalAvailability.EXTERNAL_FORBIDDEN, "GITHUB_FORBIDDEN", False, status_code)
    if status_code == 404:
        return ExternalHealthClassification(ExternalAvailability.EXTERNAL_NOT_FOUND, "GITHUB_NOT_FOUND", False, status_code)
    if status_code in {500, 502, 503, 504}:
        return ExternalHealthClassification(ExternalAvailability.EXTERNAL_TRANSIENT_FAILURE, "GITHUB_UPSTREAM_5XX", True, status_code)
    return ExternalHealthClassification(ExternalAvailability.EXTERNAL_RESPONSE_INVALID, "GITHUB_RESPONSE_INVALID", False, status_code)


def classify_github_exception(exc: BaseException) -> ExternalHealthClassification:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return ExternalHealthClassification(ExternalAvailability.EXTERNAL_TRANSIENT_FAILURE, "GITHUB_NETWORK_FAILURE", True)
    if isinstance(exc, OSError):
        return ExternalHealthClassification(ExternalAvailability.EXTERNAL_NETWORK_FAILURE, "GITHUB_NETWORK_FAILURE", True)
    return ExternalHealthClassification(ExternalAvailability.EXTERNAL_RESPONSE_INVALID, "GITHUB_DEPENDENCY_FAILURE", False)


def inspect_capability_health(store: CapabilityStore, capability_ref: str) -> CapabilityHealthReport:
    root = store.path_for(capability_ref)
    if not root.is_dir():
        return CapabilityHealthReport(capability_ref, HealthDomainStatus.REGISTRY_ENTRY_MISSING, HealthDomainStatus.PACKAGE_MISSING, HealthDomainStatus.CAPABILITY_DEPENDENCY_MISSING)
    required = (root / "admission.json", root / "capability.json", root / "executor.py", root / "tests/test_capability.py")
    if any(not path.is_file() for path in required):
        return CapabilityHealthReport(capability_ref, HealthDomainStatus.REGISTRY_ENTRY_CORRUPT, HealthDomainStatus.PACKAGE_MISSING, HealthDomainStatus.CAPABILITY_DEPENDENCY_MISSING)
    try:
        admission = json.loads(required[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CapabilityHealthReport(capability_ref, HealthDomainStatus.ADMISSION_RECEIPT_INVALID, HealthDomainStatus.PASS, HealthDomainStatus.CAPABILITY_DEPENDENCY_MISSING)
    source_hash = "sha256:" + hashlib.sha256(required[2].read_bytes()).hexdigest()
    if admission.get("status") != "ADMITTED" or admission.get("capability_ref") != capability_ref:
        return CapabilityHealthReport(capability_ref, HealthDomainStatus.ADMISSION_RECEIPT_INVALID, HealthDomainStatus.PASS, HealthDomainStatus.CAPABILITY_DEPENDENCY_MISSING)
    if admission.get("source_hash") != source_hash:
        return CapabilityHealthReport(capability_ref, HealthDomainStatus.PACKAGE_HASH_MISMATCH, HealthDomainStatus.PASS, HealthDomainStatus.DEPENDENCY_HASH_DRIFT)
    try:
        spec = CapabilitySpec.from_dict(json.loads(required[1].read_text(encoding="utf-8")))
    except Exception:
        return CapabilityHealthReport(capability_ref, HealthDomainStatus.PASS, HealthDomainStatus.CONTRACT_LOAD_FAILURE, HealthDomainStatus.CAPABILITY_DEPENDENCY_MISSING)
    if spec.ref != capability_ref:
        return CapabilityHealthReport(capability_ref, HealthDomainStatus.REGISTRY_ENTRY_CORRUPT, HealthDomainStatus.PACKAGE_SCHEMA_INVALID, HealthDomainStatus.CAPABILITY_DEPENDENCY_MISSING)
    try:
        package = CapabilityPackage(spec, str(root), spec.ref, f"generated.{spec.ref}", source_hash, ("tests/test_capability.py",))
        GeneratedCapabilityExecutor(package)
    except Exception:
        return CapabilityHealthReport(capability_ref, HealthDomainStatus.PASS, HealthDomainStatus.EXECUTOR_LOAD_FAILURE, HealthDomainStatus.CAPABILITY_DEPENDENCY_MISSING)
    try:
        transitive = (
            store.validate_dependency_graph(
                CapabilitySpec.from_dict(spec.as_dict()),
                enforce_risk=admission.get("schema_version") == "1.1",
            )
            if spec.allowed_dependencies
            else ()
        )
        for pinned in admission.get("dependency_manifest", []):
            current = store.package_metadata(str(pinned.get("capability_ref", "")))
            if current["package_hash"] != pinned.get("package_hash") or current["contract_hash"] != pinned.get("contract_hash"):
                raise ValueError("DEPENDENCY_HASH_DRIFT")
    except ValueError as exc:
        marker = str(exc).split(":", 1)[0]
        status = HealthDomainStatus.__members__.get(marker, HealthDomainStatus.CAPABILITY_DEPENDENCY_MISSING)
        return CapabilityHealthReport(capability_ref, HealthDomainStatus.PASS, HealthDomainStatus.PASS, status)
    return CapabilityHealthReport(
        capability_ref,
        HealthDomainStatus.PASS,
        HealthDomainStatus.PASS,
        HealthDomainStatus.PASS,
        details={
            "package_hash": source_hash,
            "admission_receipt_hash": _canonical_hash(admission),
            "contract_hash": _canonical_hash({"input_schema": dict(spec.input_schema), "output_schema": dict(spec.output_schema)}),
            "direct_dependencies": list(spec.allowed_dependencies),
            "transitive_dependencies": list(transitive),
        },
    )
