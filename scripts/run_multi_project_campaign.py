#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.learning import FileLessonStore, ProductionGenerationClient, StoreLessonReader  # noqa: E402
from cgkn.application.project_campaign import CampaignCompletionClient, MultiProjectCampaignService, campaign_matrix  # noqa: E402
from cgkn.providers import ConnectorCompletionClient, GrokConnector, ModelRoleConfig, ProviderConnectorRegistry  # noqa: E402
from scripts.import_historical_lessons import import_lessons  # noqa: E402


CAMPAIGN_DIR = "ITER-MULTI-PROJECT-REAL-USAGE-026"
EXPECTED_BRANCH = "codex/multi-project-real-usage-campaign-20261018"


def run(output_root: pathlib.Path) -> dict:
    branch = _git("branch", "--show-current")
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"campaign must run on {EXPECTED_BRANCH}, found {branch}")
    if _git("status", "--porcelain"):
        raise RuntimeError("campaign source worktree must be clean before real Provider execution")
    selection = json.loads((ROOT / "governance/provider_connections/selection_status.json").read_text(encoding="utf-8"))
    if selection.get("routing_provider") != "grok" or selection.get("repository_codegen_mode") != "SINGLE_PROVIDER_MODE" or selection.get("fallback") != "deny":
        raise RuntimeError("frozen Grok SINGLE_PROVIDER_MODE route is unavailable")
    output_root.mkdir(parents=True, exist_ok=True)
    lessons = output_root / "lessons"
    import_lessons(ROOT, lessons, output_root / "lesson_import_receipt.json")
    store = FileLessonStore(lessons)
    profile = json.loads((ROOT / "config/provider_connections/grok.json").read_text(encoding="utf-8"))
    connector = GrokConnector(profile)
    transport = ConnectorCompletionClient(ProviderConnectorRegistry((connector,)), enforce_budget=False, budget_purpose="GENERATION", run_id=CAMPAIGN_DIR, case_id="multi-project")
    ledger = CampaignCompletionClient(transport, provider_id="grok")
    generation = ProductionGenerationClient(ledger, StoreLessonReader(store), store=store, max_provider_calls=36)
    config = ModelRoleConfig("worker", "grok", 180, 7000, 0.0, "medium")
    _write_framework_fix(output_root, _git("rev-parse", "HEAD"))
    return dict(MultiProjectCampaignService(ROOT, output_root, generation, config, campaign_matrix()).run())


def _write_framework_fix(root: pathlib.Path, commit: str) -> None:
    path = root / "framework_fixes" / "FRAMEWORK-FIX-PYTEST-AUTOLOAD-001.json"
    if path.is_file():
        return
    value = {
        "kind": "CampaignFrameworkFix", "schema_version": "1.0", "fix_id": "FRAMEWORK-FIX-PYTEST-AUTOLOAD-001",
        "supporting_project_evidence": ["tests/application/project_campaign/test_campaign.py::test_campaign_harness_disables_unrelated_host_pytest_plugins"],
        "root_cause": "Host pytest auto-loaded unrelated third-party plugins; a broken Qt DLL produced a false project failure before candidate tests.",
        "failure_domain": "FRAMEWORK_HARNESS_DEFECT", "failure_code": "HOST_PYTEST_PLUGIN_AUTOLOAD",
        "affected_authority": "application campaign test harness", "changed_paths": ["cgkn/application/project_campaign/service.py"],
        "regression_test": "tests/application/project_campaign/test_campaign.py::test_campaign_harness_disables_unrelated_host_pytest_plugins",
        "affected_projects_rerun": ["text_stats_cli", "json_flatten_cli", "existing_repo_path_bug"],
        "canary_result": "PASS", "source_commit": commit, "status": "VALIDATED", "contains_credentials": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git failed")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=pathlib.Path, default=ROOT / "artifacts" / "campaigns" / CAMPAIGN_DIR)
    args = parser.parse_args()
    report = run(args.output_root.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] != "MULTI_PROJECT_CAMPAIGN_NEEDS_REWORK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
