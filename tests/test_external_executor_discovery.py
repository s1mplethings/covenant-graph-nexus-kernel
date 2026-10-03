from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts import capability_execution
from scripts import external_executor_discovery as discovery


class Response:
    def __init__(self, url: str, payload: Any) -> None:
        self.url = url
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def opener_for(payloads: dict[str, Any]):
    def open_(request: Any, timeout: int) -> Response:
        url = request.full_url
        for marker, payload in payloads.items():
            if marker in url:
                return Response(url, payload)
        raise OSError("offline")
    return open_


def video_capability() -> dict[str, str]:
    return {"id": "video_frame_extraction", "label": "video frame extraction", "goal": "extract exact video frames"}


def complete_candidate() -> dict[str, Any]:
    intent = discovery.build_search_intent(video_capability())
    candidate = discovery._blank_candidate(intent, name="ffmpeg-python", candidate_kind="package", ecosystem="pypi", package_name="ffmpeg-python", sources=("pypi", "deps.dev"))
    candidate.update({"version": "0.2.0", "latest_release": "0.2.0", "metadata_status": "COMPLETE"})
    candidate["license"] = {"spdx": "Apache-2.0", "status": "KNOWN", "policy": "ALLOW"}
    now = datetime.now(timezone.utc).isoformat()
    candidate["maintenance"].update({"status": "PASS", "activity": "ACTIVE", "last_push_at": now, "evaluated_at": now, "sources": ["github_repository"]})
    candidate["security"] = {"known_advisories": [], "status": "PASS", "exact_version_checked": "0.2.0", "affected": False, "max_severity": None, "fixed_versions": [], "patched_version_available": False, "sources": ["osv"], "reasons": ["exact_version_no_known_osv_vulnerabilities"], "evaluated_at": now}
    candidate["compatibility"] = {"language": "PASS", "platform": "PASS", "runtime": "PASS", "project_constraints": "PASS"}
    candidate["requirement_fit"] = {"status": "PASS", "reasons": ["fixture"]}
    return candidate


def test_local_and_skill_priority_avoid_network() -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network source must not run")
    local = {"executor": {"type": "deterministic"}, "interface_compatible": True, "acceptance_compatible": True}
    result = discovery.discover_external_executor(video_capability(), local_candidates=[local], opener=forbidden)
    assert result["route"] == "local_reuse"
    skill = {"executor": {"type": "skill"}, "interface_compatible": True, "acceptance_compatible": True}
    result = discovery.discover_external_executor(video_capability(), skill_candidates=[skill], opener=forbidden)
    assert result["route"] == "skill_reuse"


def test_search_intent_and_eligibility_are_bounded() -> None:
    intent = discovery.build_search_intent(video_capability(), required_interfaces=[f"i{i}" for i in range(20)], max_candidates=999)
    assert len(intent["query_terms"]) <= discovery.MAX_QUERIES
    assert len(intent["required_interfaces"]) == 8
    assert intent["max_candidates"] == discovery.MAX_CANDIDATES
    assert discovery.should_discover_external_executor(video_capability())
    assert not discovery.should_discover_external_executor({"id": "customer_specific_business_rule", "goal": "custom approval domain policy"})


def test_github_normalization_and_candidate_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [{"full_name": f"org/repo{i}", "html_url": f"https://github.com/org/repo{i}", "description": "video frames", "language": "Python", "stargazers_count": 50 - i, "forks_count": i, "archived": False, "disabled": False, "license": {"spdx_id": "MIT"}, "updated_at": "2026-01-01", "pushed_at": "2026-01-02", "default_branch": "main"} for i in range(30)]
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    values, errors = discovery.discover_from_github(discovery.build_search_intent(video_capability()), opener=opener_for({"search/repositories": {"items": items}}))
    assert not errors
    assert len(values) <= discovery.MAX_CANDIDATES
    assert values[0]["sources"] == ["github"]
    assert values[0]["license"]["policy"] == "ALLOW"


def test_pypi_and_deps_dev_fact_enrichment() -> None:
    candidate = discovery._blank_candidate(discovery.build_search_intent(video_capability()), name="ffmpeg-python", candidate_kind="package", ecosystem="pypi", package_name="ffmpeg-python")
    opener = opener_for({
        "pypi/ffmpeg-python/json": {"info": {"name": "ffmpeg-python", "version": "0.2.0", "requires_python": ">=3.8", "license": "Apache-2.0", "project_urls": {"Source": "https://github.com/kkroening/ffmpeg-python"}, "classifiers": []}},
        "api.deps.dev": {"licenses": ["Apache-2.0"], "links": [{"label": "SOURCE_REPO", "url": "https://github.com/kkroening/ffmpeg-python"}], "advisoryKeys": []},
    })
    candidate, error = discovery.enrich_from_pypi(candidate, opener=opener)
    assert error is None and candidate["version"] == "0.2.0"
    candidate, error = discovery.enrich_from_deps_dev(candidate, opener=opener)
    assert error is None
    assert candidate["metadata_status"] == "COMPLETE"
    assert candidate["security"]["status"] == "UNKNOWN"


def test_dedup_uses_package_then_repository() -> None:
    left = complete_candidate()
    right = json.loads(json.dumps(left))
    right["sources"] = ["github"]
    assert discovery.merge_candidates([left, right])[0]["sources"] == ["pypi", "deps.dev", "github"]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda c: c["license"].update(policy="BLOCK"), "license_not_automatically_allowed"),
        (lambda c: c["security"].update(status="BLOCK"), "security_not_cleared"),
        (lambda c: c["maintenance"].update(status="BLOCK", archived=True), "maintenance_not_cleared"),
        (lambda c: c["maintenance"].update(status="BLOCK", deprecated=True), "maintenance_not_cleared"),
        (lambda c: c["compatibility"].update(platform="FAIL"), "compatibility_failed"),
        (lambda c: c.update(metadata_status="PARTIAL"), "metadata_incomplete"),
    ],
)
def test_hard_filters(mutation: Any, reason: str) -> None:
    candidate = complete_candidate()
    mutation(candidate)
    assert reason in discovery.candidate_rejection_reasons(candidate)


def test_https_allowlist_and_network_failure_are_structured() -> None:
    payload, error = discovery._safe_json_get("https://example.com/value", source="test")
    assert payload is None and error and error.classification == "ENDPOINT_REJECTED"
    payload, error = discovery._safe_json_get("https://api.github.com/value", source="github", opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    assert payload is None and error and error.classification == "SOURCE_UNAVAILABLE"


def test_trial_pass_fail_timeout_and_secret_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = complete_candidate()
    monkeypatch.setenv("CGKN_OPENAI_API_KEY", "must-not-leak")
    calls: list[dict[str, str]] = []
    def passing(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs["env"])
        stdout = "CGKN_TRIAL_OK" if command[-2:-1] == ["-c"] else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
    assert discovery.run_bounded_python_trial(candidate, runner=passing)["trial"]["status"] == "PASS"
    assert all("CGKN_OPENAI_API_KEY" not in env for env in calls)
    def failing(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="no")
    assert discovery.run_bounded_python_trial(candidate, runner=failing)["trial"]["status"] == "FAIL"
    def timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(args[0], 1)
    assert discovery.run_bounded_python_trial(candidate, runner=timeout)["trial"]["status"] == "BLOCKED"
    assert not list(pathlib.Path(discovery.tempfile.gettempdir()).glob("cgkn-executor-trial-*"))


def test_selected_requires_trial_and_all_fail_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = complete_candidate()
    monkeypatch.setattr(discovery, "discover_from_github", lambda *a, **k: ([], []))
    monkeypatch.setattr(discovery, "discover_from_registry", lambda *a, **k: ([candidate], []))
    passed = discovery.discover_external_executor(video_capability(), trial_runner=lambda value: dict(value) | {"trial": {"status": "PASS", "command": "fixture", "evidence": ["ok"]}})
    assert passed["route"] == "external"
    assert passed["selected_executor"]["version"] == "0.2.0"
    failed = discovery.discover_external_executor(video_capability(), trial_runner=lambda value: dict(value) | {"trial": {"status": "FAIL", "command": "fixture", "evidence": ["bad"]}})
    assert failed["route"] == "agent_build"
    assert failed["pipeline_fallback"] == "agent_build"
    assert failed["status"] == "NOT_EVALUATED"


def test_capability_plan_projects_selected_external_worknode_without_provider() -> None:
    requirement = {"goal": "extract frames", "language": "python", "platform": "windows", "constraints": ["local-first"], "capabilities": [{"id": "video_frame_extraction", "goal": "extract frames", "depends_on": [], "inputs": ["VideoPath"], "outputs": ["FrameImage"], "acceptance": ["frame exists"]}]}
    selected = discovery._selected_executor(complete_candidate() | {"trial": {"status": "PASS", "command": "fixture", "evidence": ["ok"]}}, discovery.build_search_intent(video_capability()))
    def fake(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"kind": "CGKNExternalExecutorDiscoveryResult", "status": "PASS", "route": "external", "selected_executor": selected, "candidates": [], "source_errors": [], "pipeline_fallback": None, "release_authority": False}
    result = capability_execution.discover_capability_executors(requirement, allow_network=False, discovery=fake)
    node = result["capability_plan"]["work_nodes"][0]
    assert node["executor"]["type"] == "external"
    assert node["executor"]["selected_executor"]["package"] == "ffmpeg-python"
    assert result["provider_calls"] == 0
    assert result["release_authority"] is False


def test_safe_post_and_osv_payload_are_exact_and_private() -> None:
    seen: dict[str, Any] = {}
    def opener(request: Any, timeout: int) -> Response:
        seen["url"] = request.full_url
        seen["method"] = request.method
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return Response(request.full_url, {"vulns": []})
    document, error = discovery.query_osv_exact_version("pypi", "pypdf", "6.1.1", opener=opener)
    assert error is None and document == {"vulns": []}
    assert seen == {"url": "https://api.osv.dev/v1/query", "method": "POST", "body": {"package": {"ecosystem": "PyPI", "name": "pypdf"}, "version": "6.1.1"}}
    assert not any(key in json.dumps(seen) for key in ("goal", "path", "token", "source code", "user text"))


@pytest.mark.parametrize(
    ("payload", "severity", "status"),
    [
        ({"database_specific": {"severity": "CRITICAL"}}, "CRITICAL", "BLOCK"),
        ({"database_specific": {"severity": "HIGH"}}, "HIGH", "BLOCK"),
        ({"database_specific": {"severity": "MODERATE"}}, "MEDIUM", "REVIEW"),
        ({"database_specific": {"severity": "LOW"}}, "LOW", "REVIEW"),
        ({}, "UNKNOWN", "REVIEW"),
    ],
)
def test_osv_exact_version_severity_policy(payload: dict[str, Any], severity: str, status: str) -> None:
    candidate = complete_candidate()
    vulnerability = {"id": "OSV-1", "summary": "bounded", "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "0.2.1"}]}]}], **payload}
    enriched, error = discovery.enrich_security_from_osv(candidate, opener=opener_for({"api.osv.dev": {"vulns": [vulnerability]}}))
    assert error is None
    assert enriched["security"]["exact_version_checked"] == "0.2.0"
    assert enriched["security"]["max_severity"] == severity
    assert enriched["security"]["status"] == status
    assert enriched["security"]["fixed_versions"] == ["0.2.1"]
    assert enriched["security"]["patched_version_available"] is True


def test_osv_clean_is_pass_and_unavailable_never_passes() -> None:
    candidate = complete_candidate()
    clean, error = discovery.enrich_security_from_osv(candidate, opener=opener_for({"api.osv.dev": {"vulns": []}}))
    assert error is None and clean["security"]["status"] == "PASS"
    assert clean["security"]["affected"] is False
    unavailable, error = discovery.enrich_security_from_osv(candidate, opener=lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")))
    assert error and unavailable["security"]["status"] == "UNKNOWN"
    candidate["security"]["known_advisories"] = ["GHSA-hint"]
    hinted, error = discovery.enrich_security_from_osv(candidate, opener=lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")))
    assert error and hinted["security"]["status"] == "REVIEW"


def test_deps_dev_conflict_is_review_not_silently_overwritten() -> None:
    candidate = complete_candidate()
    candidate["security"]["known_advisories"] = ["GHSA-deps-only"]
    candidate["security"]["sources"] = ["deps.dev"]
    enriched, error = discovery.enrich_security_from_osv(candidate, opener=opener_for({"api.osv.dev": {"vulns": []}}))
    assert error is None
    assert enriched["security"]["status"] == "REVIEW"
    assert "security_source_conflict" in enriched["security"]["reasons"]


def test_missing_version_and_version_identity_cannot_pass() -> None:
    candidate = complete_candidate()
    candidate["version"] = None
    enriched, error = discovery.enrich_security_from_osv(candidate)
    assert error and enriched["security"]["status"] == "UNKNOWN"
    candidate = complete_candidate()
    candidate["security"]["exact_version_checked"] = "0.2.1"
    assert "security_version_identity_mismatch" in discovery.candidate_rejection_reasons(candidate)


def test_fixed_version_must_be_independently_rechecked() -> None:
    vulnerable = complete_candidate()
    vulnerability = {"id": "OSV-1", "database_specific": {"severity": "HIGH"}, "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "0.2.1"}]}]}]}
    vulnerable, _ = discovery.enrich_security_from_osv(vulnerable, opener=opener_for({"api.osv.dev": {"vulns": [vulnerability]}}))
    assert vulnerable["security"]["status"] == "BLOCK"
    fixed = complete_candidate()
    fixed["version"] = "0.2.1"
    fixed["security"] = discovery._blank_candidate(discovery.build_search_intent(video_capability()), name="x", candidate_kind="package", ecosystem="pypi")["security"]
    assert "security_not_cleared" in discovery.candidate_rejection_reasons(fixed)
    fixed, error = discovery.enrich_security_from_osv(fixed, opener=opener_for({"api.osv.dev": {"vulns": []}}))
    assert error is None and fixed["security"]["status"] == "PASS"
    assert fixed["security"]["exact_version_checked"] == "0.2.1"


def test_parse_github_repository_is_strict() -> None:
    assert discovery.parse_github_repository("https://github.com/org/repo.git/") == ("org", "repo")
    assert discovery.parse_github_repository("https://github.com/org/repo?x=1") is None
    assert discovery.parse_github_repository("http://github.com/org/repo") is None
    assert discovery.parse_github_repository("https://example.com/org/repo") is None
    assert discovery.parse_github_repository("https://github.com/org/repo/extra") is None


@pytest.mark.parametrize(
    ("maintenance", "status", "activity"),
    [
        ({"last_push_at": "2025-12-15T00:00:00Z", "has_published_release": False}, "PASS", "ACTIVE"),
        ({"last_push_at": "2024-08-01T00:00:00Z", "latest_release_at": "2025-12-01T00:00:00Z"}, "PASS", "ACTIVE"),
        ({"last_push_at": "2025-12-15T00:00:00Z", "latest_release_at": "2020-01-01T00:00:00Z"}, "PASS", "ACTIVE"),
        ({"last_push_at": "2020-01-01T00:00:00Z", "has_published_release": False}, "REVIEW", "STALE"),
        ({"archived": True, "last_push_at": "2025-12-15T00:00:00Z"}, "BLOCK", "ARCHIVED"),
        ({"disabled": True, "last_push_at": "2025-12-15T00:00:00Z"}, "BLOCK", "ARCHIVED"),
    ],
)
def test_maintenance_policy(maintenance: dict[str, Any], status: str, activity: str) -> None:
    candidate = complete_candidate()
    candidate["maintenance"].update(maintenance)
    evaluated = discovery.evaluate_maintenance(candidate, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert evaluated["maintenance"]["status"] == status
    assert evaluated["maintenance"]["activity"] == activity


def test_github_maintenance_no_release_recent_push_passes() -> None:
    candidate = complete_candidate()
    candidate["repository"] = "https://github.com/org/repo"
    def opener(request: Any, timeout: int) -> Response:
        if request.full_url.endswith("/releases/latest"):
            raise discovery.urllib.error.HTTPError(request.full_url, 404, "none", {}, None)
        return Response(request.full_url, {"archived": False, "disabled": False, "pushed_at": "2025-12-15T00:00:00Z"})
    result, errors = discovery.enrich_github_maintenance(candidate, now=datetime(2026, 1, 1, tzinfo=timezone.utc), opener=opener)
    assert not errors
    assert result["maintenance"]["has_published_release"] is False
    assert result["maintenance"]["status"] == "PASS"


def test_github_unavailable_is_unknown_and_stars_have_no_authority() -> None:
    candidate = complete_candidate()
    candidate["repository"] = "https://github.com/org/repo"
    candidate["maintenance"].update({"status": "UNKNOWN", "last_push_at": None, "latest_release_at": None})
    candidate["popularity"]["stars"] = 1_000_000
    result, errors = discovery.enrich_github_maintenance(candidate, now=datetime(2026, 1, 1, tzinfo=timezone.utc), opener=lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")))
    assert errors and result["maintenance"]["status"] == "UNKNOWN"


def test_trust_failure_stops_trial_and_full_trust_selects(monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = complete_candidate()
    blocked["security"]["status"] = "BLOCK"
    trusted = complete_candidate()
    calls = {"trial": 0}
    def runner(value: dict[str, Any]) -> dict[str, Any]:
        calls["trial"] += 1
        return dict(value) | {"trial": {"status": "PASS", "command": "fixture", "evidence": ["ok"]}}
    monkeypatch.setattr(discovery, "discover_from_github", lambda *a, **k: ([], []))
    monkeypatch.setattr(discovery, "discover_from_registry", lambda *a, **k: ([blocked], []))
    monkeypatch.setattr(discovery, "enrich_github_maintenance", lambda value, **k: (value, []))
    monkeypatch.setattr(discovery, "enrich_security_from_osv", lambda value, **k: (value, None))
    result = discovery.discover_external_executor(video_capability(), trial_runner=runner)
    assert result["route"] == "agent_build" and calls["trial"] == 0
    blocked = complete_candidate()
    blocked["maintenance"]["status"] = "REVIEW"
    result = discovery.discover_external_executor(video_capability(), trial_runner=runner)
    assert result["route"] == "agent_build" and calls["trial"] == 0
    monkeypatch.setattr(discovery, "discover_from_registry", lambda *a, **k: ([trusted], []))
    result = discovery.discover_external_executor(video_capability(), trial_runner=runner)
    assert result["route"] == "external" and calls["trial"] == 1
    assert result["selected_executor"]["trust_provenance"]["exact_version"] == "0.2.0"


def test_all_trust_fail_falls_back_and_trust_enrichment_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [complete_candidate() for _ in range(8)]
    for index, candidate in enumerate(candidates):
        candidate["candidate_id"] = f"candidate.{index}"
        candidate["package_name"] = f"package-{index}"
        candidate["security"]["status"] = "REVIEW" if index < 4 else "BLOCK"
    calls = {"maintenance": 0, "security": 0}
    monkeypatch.setattr(discovery, "discover_from_github", lambda *a, **k: ([], []))
    monkeypatch.setattr(discovery, "discover_from_registry", lambda *a, **k: (candidates, []))
    monkeypatch.setattr(discovery, "enrich_github_maintenance", lambda value, **k: (calls.__setitem__("maintenance", calls["maintenance"] + 1) or value, []))
    monkeypatch.setattr(discovery, "enrich_security_from_osv", lambda value, **k: (calls.__setitem__("security", calls["security"] + 1) or value, None))
    result = discovery.discover_external_executor(video_capability(), trial_runner=lambda _v: pytest.fail("trial must not run"))
    assert result["route"] == "agent_build"
    assert calls == {"maintenance": discovery.MAX_TRUST_CANDIDATES, "security": discovery.MAX_TRUST_CANDIDATES}


def test_trust_freshness_binds_selected_version_and_ttls() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    selected = discovery._selected_executor(complete_candidate() | {"maintenance": complete_candidate()["maintenance"] | {"evaluated_at": now.isoformat()}, "security": complete_candidate()["security"] | {"evaluated_at": now.isoformat()}, "trial": {"status": "PASS", "command": "fixture", "evidence": ["ok"]}}, discovery.build_search_intent(video_capability()))
    result = {"selected_executor": selected}
    assert discovery.discovery_result_trust_is_fresh(result, now=now + timedelta(hours=1))
    assert not discovery.discovery_result_trust_is_fresh(result, now=now + timedelta(hours=7))
    selected["security"]["exact_version_checked"] = "different"
    assert not discovery.discovery_result_trust_is_fresh(result, now=now)

