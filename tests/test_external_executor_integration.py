from __future__ import annotations

import json
from pathlib import Path

from scripts import external_executor_integration as integration


def selection(package: str = "av", version: str = "14.0.1") -> dict:
    return {
        "results": [{
            "route": "external",
            "intent": {"capability_id": "video-frame-extraction"},
            "selected_executor": {
                "capability_id": "video-frame-extraction",
                "package": package,
                "version": version,
                "repository": "https://github.com/PyAV-Org/PyAV",
                "trust_provenance": {"candidate_id": "candidate.av"},
            },
        }]
    }


def make_project(root: Path, source: str, requirement: str = "av==14.0.1") -> None:
    (root / "src").mkdir(parents=True)
    (root / "requirements.txt").write_text(requirement + "\n", encoding="utf-8")
    (root / "src" / "extractor.py").write_text(source, encoding="utf-8")


def test_contract_is_bounded_and_exact() -> None:
    contracts = integration.build_integration_contracts(selection())
    assert len(contracts) == 1
    contract = contracts[0]
    assert contract["dependency"]["specifier"] == "av==14.0.1"
    assert contract["source_usage"]["required_api_symbols"] == ["av.open"]
    assert contract["release_authority"] is False
    assert "security" not in json.dumps(contract)


def test_ast_accepts_alias_call_and_exact_dependency(tmp_path: Path) -> None:
    make_project(tmp_path, "import av as video_lib\n\ndef extract(path):\n    return video_lib.open(path)\n")
    contracts = integration.build_integration_contracts(selection())
    receipt = integration.validate_project_integration(tmp_path, contracts)
    assert receipt["status"] == "PASS"
    assert receipt["results"][0]["observed_api_calls"] == ["av.open"]


def test_ast_accepts_import_from_call(tmp_path: Path) -> None:
    make_project(tmp_path, "from pypdf import PdfReader\n\ndef read(path):\n    return PdfReader(path)\n", "pypdf==5.1.0")
    receipt = integration.validate_project_integration(
        tmp_path, integration.build_integration_contracts(selection("pypdf", "5.1.0"))
    )
    assert receipt["status"] == "PASS"
    assert receipt["results"][0]["observed_api_calls"] == ["pypdf.PdfReader"]


def test_readme_comment_test_and_unused_import_are_not_usage(tmp_path: Path) -> None:
    make_project(tmp_path, "import av\n# av.open('movie.mp4')\n")
    (tmp_path / "README.md").write_text("Call av.open('movie.mp4')", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_fake.py").write_text("import av\nav.open('fake.mp4')\n", encoding="utf-8")
    receipt = integration.validate_project_integration(tmp_path, integration.build_integration_contracts(selection()))
    assert receipt["status"] == "FAIL"
    assert receipt["results"][0]["source_usage_status"] == "FAIL"


def test_missing_or_mismatched_pin_fails(tmp_path: Path) -> None:
    make_project(tmp_path, "import av\nav.open('movie.mp4')\n", requirement="av>=14")
    receipt = integration.validate_project_integration(tmp_path, integration.build_integration_contracts(selection()))
    assert receipt["status"] == "FAIL"
    assert receipt["results"][0]["dependency_status"] == "FAIL"
    assert "SELECTED_EXECUTOR_VERSION_MISMATCH" in receipt["results"][0]["failure_codes"]


def test_wrong_library_is_rejected(tmp_path: Path) -> None:
    make_project(tmp_path, "import ffmpeg\nffmpeg.input('movie.mp4')\n", requirement="ffmpeg-python==0.2.0")
    receipt = integration.validate_project_integration(tmp_path, integration.build_integration_contracts(selection()))
    assert receipt["status"] == "FAIL"
    assert set(receipt["results"][0]["failure_codes"]) == {
        "SELECTED_EXECUTOR_DEPENDENCY_MISSING", "SELECTED_EXECUTOR_SOURCE_USAGE_MISSING"
    }


def test_runtime_requires_exact_installed_version_api_and_output(tmp_path: Path) -> None:
    make_project(tmp_path, "import av\nav.open('movie.mp4')\n")
    contracts = integration.build_integration_contracts(selection())
    good = {"av": {"exit_code": 0, "installed_package": "av", "installed_version": "14.0.1", "external_api_used": True, "output_verified": True}}
    assert integration.validate_project_integration(tmp_path, contracts, runtime_evidence=good, require_runtime=True)["status"] == "PASS"
    bad = {"av": {**good["av"], "installed_version": "13.0.0"}}
    assert integration.validate_project_integration(tmp_path, contracts, runtime_evidence=bad, require_runtime=True)["status"] == "FAIL"


def test_receipt_rejects_stale_project_or_contract(tmp_path: Path) -> None:
    make_project(tmp_path, "import av\nav.open('movie.mp4')\n")
    contracts = integration.build_integration_contracts(selection())
    receipt = integration.validate_project_integration(tmp_path, contracts)
    assert integration.receipt_is_current(receipt, tmp_path, contracts)
    (tmp_path / "src" / "extractor.py").write_text("import av\n", encoding="utf-8")
    assert not integration.receipt_is_current(receipt, tmp_path, contracts)


def test_candidate_replacement_then_agent_fallback() -> None:
    results = [{"candidates": [
        {"candidate_id": "one", "trial": {"status": "PASS"}, "rejection_reasons": []},
        {"candidate_id": "two", "trial": {"status": "PASS"}, "rejection_reasons": []},
    ]}]
    assert integration.select_next_candidate(results, ["one"])["candidate"]["candidate_id"] == "two"
    fallback = integration.select_next_candidate(results, ["one", "two"])
    assert fallback == {"route": "agent_build", "candidate": None, "pipeline_fallback": "agent_build"}


def test_provider_projection_forbids_silent_substitution() -> None:
    text = integration.provider_projection(integration.build_integration_contracts(selection()))
    assert "av==14.0.1" in text
    assert "av.open" in text
    assert "substituting another library" in text
    assert "SELECTED_EXECUTOR_INTEGRATION_BLOCKED" in text
