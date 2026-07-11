from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.adaptive_delivery as adaptive_delivery


def make_project(root: pathlib.Path, *, package: bool = True) -> tuple[pathlib.Path, dict]:
    project = root / "project"
    project.mkdir()
    (project / "README.md").write_text("# App\n", encoding="utf-8")
    (project / "TEST_PLAN.md").write_text("# Test plan\n", encoding="utf-8")
    (project / "app.py").write_text("print('real app')\n", encoding="utf-8")
    manifest = {
        "project_dir": str(project),
        "known_limits": [],
        "quality_evidence": {},
        "artifacts": {"preview_evidence": []},
    }
    if package:
        bundle = project / "final_project_bundle.zip"
        bundle.write_bytes(b"real zip")
        manifest["package_path"] = str(bundle)
        manifest["artifacts"]["delivery_zip"] = str(bundle)
    return project, manifest


def judge(project: pathlib.Path, manifest: dict, **kwargs):
    facts = adaptive_delivery.delivery_fact_check(project, manifest, **kwargs)
    return adaptive_delivery.agent_delivery_judgment(
        raw_user_goal="Build a local app",
        project_summary="Local app",
        delivery_fact_check=facts,
        quality_evidence=manifest.get("quality_evidence", {}),
        known_limits=manifest.get("known_limits", []),
        phase=kwargs.get("phase", "final"),
    )


def test_missing_project_is_fact_blocked() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir) / "missing"
        result = judge(project, {})

    assert result["verdict"] == "FACT_BLOCKED"
    assert result["delivery_allowed"] is False
    assert "project_dir_missing" in result["required_repairs"]


def test_final_without_zip_requests_review_instead_of_fake_pass() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project, manifest = make_project(pathlib.Path(temp_dir), package=False)
        result = judge(project, manifest)

    assert result["verdict"] == "ASK_USER_REVIEW"
    assert result["delivery_allowed"] is True
    assert result["is_final"] is False


def test_sample_zip_does_not_count_as_final_package() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project, manifest = make_project(pathlib.Path(temp_dir), package=False)
        samples = project / "samples"
        samples.mkdir()
        (samples / "data.zip").write_bytes(b"sample input")
        facts = adaptive_delivery.delivery_fact_check(project, manifest)
        result = adaptive_delivery.agent_delivery_judgment(
            raw_user_goal="Build app",
            project_summary="App",
            delivery_fact_check=facts,
            phase="final",
        )

    assert facts["facts"]["any_zip_found"] is True
    assert facts["facts"]["final_package_exists"] is False
    assert result["verdict"] != "PASS_FINAL"


def test_manifest_package_path_counts_as_final_package() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project, manifest = make_project(pathlib.Path(temp_dir), package=True)
        facts = adaptive_delivery.delivery_fact_check(project, manifest)

    assert facts["facts"]["final_package_exists"] is True
    assert facts["facts"]["zip_exists"] is True


def test_arbitrary_zip_not_in_manifest_is_not_package() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project, manifest = make_project(pathlib.Path(temp_dir), package=False)
        (project / "random.zip").write_bytes(b"not package")
        facts = adaptive_delivery.delivery_fact_check(project, manifest)

    assert facts["facts"]["any_zip_found"] is True
    assert facts["facts"]["final_package_exists"] is False
    assert not any(item["kind"] == "package" for item in facts["safe_artifacts"])


def test_missing_preview_and_incomplete_tests_can_deliver_with_warnings() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project, manifest = make_project(pathlib.Path(temp_dir))
        manifest["known_limits"] = ["Local image model is not configured.", "Real dataset is not available."]
        manifest["quality_evidence"] = {
            "test_report_found": False,
            "test_report_has_commands": False,
            "preview_evidence_found": False,
        }
        result = judge(project, manifest)

    assert result["verdict"] == "DELIVER_WITH_WARNINGS"
    assert result["delivery_allowed"] is True
    assert result["is_final"] is True
    assert result["user_visible_warnings"]


def test_external_packager_output_dir_is_allowed_when_manifest_claims_it() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        project, manifest = make_project(root, package=False)
        delivery_dir = root / "delivery"
        delivery_dir.mkdir()
        bundle = delivery_dir / "final_project_bundle.zip"
        bundle.write_bytes(b"real zip")
        manifest["output_dir"] = str(delivery_dir)
        manifest["package_path"] = str(bundle)
        manifest["artifacts"]["delivery_zip"] = str(bundle)
        facts = adaptive_delivery.delivery_fact_check(project, manifest)

    assert facts["facts"]["final_package_exists"] is True
    assert facts["facts"]["paths_safe"] is True
    assert not facts["unsafe_paths"]


def test_external_unclaimed_zip_is_unsafe_or_ignored() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        project, manifest = make_project(root, package=False)
        external = root / "external" / "final_project_bundle.zip"
        external.parent.mkdir()
        external.write_bytes(b"zip")
        facts = adaptive_delivery.delivery_fact_check(project, manifest)

    assert facts["facts"]["final_package_exists"] is False
    assert str(external.resolve()) not in [item["path"] for item in facts["safe_artifacts"]]


def test_placeholder_preview_is_excluded_even_when_agent_claims_pass() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project, manifest = make_project(pathlib.Path(temp_dir))
        preview = project / "screenshots" / "fallback_mock_screenshot.png"
        preview.parent.mkdir()
        preview.write_bytes(b"not real")
        manifest["artifacts"]["preview_evidence"] = [str(preview)]
        facts = adaptive_delivery.delivery_fact_check(project, manifest)

        def fake_agent(messages):
            return {
                "verdict": "PASS_FINAL",
                "delivery_allowed": True,
                "is_final": True,
                "confidence": 1.0,
                "reasons": ["looks good"],
                "user_visible_warnings": [],
                "required_repairs": [],
                "can_send_artifacts": [str(preview), str(project / "final_project_bundle.zip")],
                "must_not_claim": [],
            }

        result = adaptive_delivery.agent_delivery_judgment(
            raw_user_goal="Build app",
            project_summary="App",
            delivery_fact_check=facts,
            phase="final",
            agent=fake_agent,
        )

    assert str(preview.resolve()) not in result["can_send_artifacts"]
    assert any("placeholder/mock/fallback" in item for item in result["must_not_claim"])


def test_unsafe_or_missing_claimed_attachment_forces_fact_blocked() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        project, manifest = make_project(root)
        manifest["artifacts"]["preview_evidence"] = ["../outside.png", "screenshots/missing.png"]
        result = judge(project, manifest)

    assert result["verdict"] == "FACT_BLOCKED"
    assert result["delivery_allowed"] is False
    assert "unsafe_attachment_path" in result["required_repairs"]
    assert "claimed_attachment_missing" in result["required_repairs"]


def test_explicit_provider_failure_cannot_be_overridden() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project, manifest = make_project(pathlib.Path(temp_dir))
        facts = adaptive_delivery.delivery_fact_check(
            project,
            manifest,
            provider_result={"status": "BLOCKED", "reason": "provider failure"},
        )
        result = adaptive_delivery.agent_delivery_judgment(
            raw_user_goal="Build app",
            project_summary="App",
            delivery_fact_check=facts,
            provider_result={"status": "BLOCKED"},
        )

    assert result["verdict"] == "FACT_BLOCKED"
    assert result["delivery_allowed"] is False
    assert "provider_not_successful" in result["required_repairs"]


def test_invalid_agent_schema_falls_back_without_bypassing_facts() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project, manifest = make_project(pathlib.Path(temp_dir))
        facts = adaptive_delivery.delivery_fact_check(project, manifest)
        result = adaptive_delivery.agent_delivery_judgment(
            raw_user_goal="Build app",
            project_summary="App",
            delivery_fact_check=facts,
            agent=lambda messages: {"verdict": "PASS_FINAL"},
        )

    assert result["judgment_source"] == "local_agent_fallback"
    assert result["verdict"] == "DELIVER_WITH_WARNINGS"
    assert "agent_error" in result
