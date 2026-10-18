from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

from cgkn.application.capability_builder import (
    CapabilityRisk,
    CapabilitySpec,
    CapabilityStore,
    ExternalAvailability,
    HealthDomainStatus,
    classify_github_exception,
    classify_github_response,
    inspect_capability_health,
)


def _install(root: Path, spec: CapabilitySpec, code: str = "def execute(value):\n    return value\n") -> Path:
    path = CapabilityStore(root).path_for(spec.ref)
    (path / "tests").mkdir(parents=True)
    (path / "executor.py").write_bytes(code.encode("utf-8"))
    (path / "tests/test_capability.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    (path / "capability.json").write_text(json.dumps(spec.as_dict()), encoding="utf-8")
    source_hash = "sha256:" + hashlib.sha256(code.encode()).hexdigest()
    (path / "admission.json").write_text(json.dumps({"status":"ADMITTED","capability_ref":spec.ref,"source_hash":source_hash,"schema_version":"1.0"}), encoding="utf-8")
    return path


def _spec(ref: str = "demo.echo@1") -> CapabilitySpec:
    capability_id, version = ref.rsplit("@", 1)
    return CapabilitySpec(capability_id, version, "echo", {}, {}, ({"input":"x","output":"x"},), ("echo",))


def test_valid_registry_package_and_contract_are_locally_healthy(tmp_path: Path):
    store = CapabilityStore(tmp_path / "store"); _install(store.root, _spec())
    report = inspect_capability_health(store, "demo.echo@1")
    assert report.local_healthy and not report.registry_regression
    assert set(report.as_dict()["domains"]) == {"REGISTRY_INTEGRITY", "PACKAGE_INTEGRITY", "DEPENDENCY_INTEGRITY", "EXTERNAL_AVAILABILITY"}


def test_missing_registry_entry_is_a_registry_regression(tmp_path: Path):
    report = inspect_capability_health(CapabilityStore(tmp_path / "store"), "missing.capability@1")
    assert report.registry_integrity is HealthDomainStatus.REGISTRY_ENTRY_MISSING and report.registry_regression


def test_package_hash_mismatch_is_a_registry_regression(tmp_path: Path):
    store = CapabilityStore(tmp_path / "store"); path = _install(store.root, _spec())
    (path / "executor.py").write_text("def execute(value): return 'changed'\n", encoding="utf-8")
    report = inspect_capability_health(store, "demo.echo@1")
    assert report.registry_integrity is HealthDomainStatus.PACKAGE_HASH_MISMATCH and report.registry_regression


def test_executor_load_failure_is_a_package_regression(tmp_path: Path):
    store = CapabilityStore(tmp_path / "store"); path = _install(store.root, _spec(), "def broken(:\n")
    report = inspect_capability_health(store, "demo.echo@1")
    assert report.package_integrity is HealthDomainStatus.EXECUTOR_LOAD_FAILURE and report.registry_regression


def test_github_not_found_is_not_retryable():
    value = classify_github_response(404, "{}")
    assert value.error_class == "GITHUB_NOT_FOUND" and not value.retryable


def test_github_429_is_rate_limited():
    value = classify_github_response(429, '{"message":"rate limit exceeded"}')
    assert value.status is ExternalAvailability.EXTERNAL_RATE_LIMITED and value.retryable


def test_github_403_with_rate_evidence_is_rate_limited():
    assert classify_github_response(403, "rate limit exceeded").error_class == "GITHUB_RATE_LIMITED"


def test_github_403_without_rate_evidence_is_forbidden():
    value = classify_github_response(403, '{"message":"forbidden"}')
    assert value.error_class == "GITHUB_FORBIDDEN" and not value.retryable


def test_github_503_is_transient():
    value = classify_github_response(503, "unavailable")
    assert value.status is ExternalAvailability.EXTERNAL_TRANSIENT_FAILURE and value.retryable


def test_network_timeout_is_transient():
    value = classify_github_exception(socket.timeout("late"))
    assert value.status is ExternalAvailability.EXTERNAL_TRANSIENT_FAILURE and value.retryable


def test_invalid_json_is_response_invalid():
    value = classify_github_response(200, "not-json")
    assert value.error_class == "GITHUB_RESPONSE_INVALID" and not value.retryable


def test_transient_external_failure_does_not_mark_registry_regression(tmp_path: Path):
    store = CapabilityStore(tmp_path / "store"); _install(store.root, _spec())
    local = inspect_capability_health(store, "demo.echo@1")
    external = classify_github_response(503, "temporary")
    assert local.local_healthy and not local.registry_regression
    assert external.status is ExternalAvailability.EXTERNAL_TRANSIENT_FAILURE
