from __future__ import annotations

import json
import pathlib
import subprocess
import sys
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
    candidate["security"] = {"known_advisories": [], "status": "PASS"}
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
    assert candidate["security"]["status"] == "PASS"


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
        (lambda c: c["maintenance"].update(archived=True), "repository_archived"),
        (lambda c: c["maintenance"].update(deprecated=True), "candidate_deprecated"),
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

