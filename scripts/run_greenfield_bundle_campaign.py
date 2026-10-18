#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.learning import FileLessonStore, ProductionGenerationClient, StoreLessonReader  # noqa: E402
from cgkn.application.project_campaign import CampaignCompletionClient  # noqa: E402
from cgkn.application.project_campaign.greenfield_v2 import GreenfieldV2Campaign, existing_repo_canary, mini_campaign_cases, targeted_cases  # noqa: E402
from cgkn.providers import ConnectorCompletionClient, GrokConnector, ModelRoleConfig, ProviderConnectorRegistry  # noqa: E402
from scripts.import_historical_lessons import import_lessons  # noqa: E402


CAMPAIGN_DIR = "ITER-GREENFIELD-BUNDLE-GENERATION-027"
EXPECTED_BRANCH = "codex/greenfield-bundle-generation-20261018"


def run(output_root: pathlib.Path, *, phase: str = "all") -> dict:
    branch = _git("branch", "--show-current")
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"greenfield V2 campaign must run on {EXPECTED_BRANCH}, found {branch}")
    if _git("status", "--porcelain"):
        raise RuntimeError("greenfield V2 source worktree must be clean before real Provider execution")
    selection = json.loads((ROOT / "governance/provider_connections/selection_status.json").read_text(encoding="utf-8"))
    if selection.get("routing_provider") != "grok" or selection.get("repository_codegen_mode") != "SINGLE_PROVIDER_MODE" or selection.get("fallback") != "deny":
        raise RuntimeError("frozen Grok SINGLE_PROVIDER_MODE route is unavailable")
    output_root.mkdir(parents=True, exist_ok=True)
    _write_connection_route(output_root)
    lessons = output_root / "lessons"
    if not (output_root / "lesson_import_receipt.json").is_file():
        import_lessons(ROOT, lessons, output_root / "lesson_import_receipt.json")
    store = FileLessonStore(lessons)
    profile = json.loads((ROOT / "config/provider_connections/grok.json").read_text(encoding="utf-8"))
    transport = ConnectorCompletionClient(ProviderConnectorRegistry((GrokConnector(profile),)), enforce_budget=False, budget_purpose="GENERATION", run_id=CAMPAIGN_DIR, case_id="greenfield-v2")
    ledger = CampaignCompletionClient(transport, provider_id="grok")
    generation = ProductionGenerationClient(ledger, StoreLessonReader(store), store=store, max_provider_calls=40)
    source = _git("rev-parse", "HEAD")
    previous = ROOT.parent / "multi-project-campaign" / "artifacts" / "campaigns" / "ITER-MULTI-PROJECT-REAL-USAGE-026" / "capability_registry"
    campaign = GreenfieldV2Campaign(ROOT, output_root, generation, ModelRoleConfig("worker", "grok", 180, 2800, 0.0, "low"), source_commit=source, previous_capability_store=previous)
    result: dict[str, object] = {"source_commit": source, "phase": phase}
    if phase in {"targeted", "all"}:
        targeted = campaign.run_cases(targeted_cases(), phase="TARGETED_REAL_4", partition="TARGETED_REAL_4")
        result["targeted"] = targeted
        passed = sum(item["final_status"] == "PASS" for item in targeted)
        _write(output_root / "targeted_summary.json", {"kind": "TargetedGreenfieldV2Summary", "schema_version": "1.0", "passed": passed, "total": 4, "projects": targeted, "contains_credentials": False})
        if passed < 3:
            result["status"] = "GREENFIELD_BUNDLE_GENERATION_NEEDS_REWORK"
            result["summary"] = campaign.summary(); _write(output_root / "final_report.json", result)
            return result
        canary = campaign.run_existing_canary(existing_repo_canary()); result["existing_repo_canary"] = canary
        if canary["status"] != "PASS":
            result["status"] = "GREENFIELD_BUNDLE_GENERATION_NEEDS_REWORK"
            result["summary"] = campaign.summary(); _write(output_root / "final_report.json", result)
            return result
    if phase in {"mini", "all"}:
        cases = mini_campaign_cases(); calibration = cases[:6]; holdout = cases[6:]
        _write(output_root / "source_freeze.json", {"kind": "GreenfieldV2SourceFreeze", "schema_version": "1.0", "source_commit": source, "manifest_version": campaign.compiler.VERSION, "bundle_policy_version": "1.0", "budget_policy_version": "1.0", "contains_credentials": False})
        result["calibration_generalization"] = campaign.run_cases(calibration, phase="MINI_CAMPAIGN", partition="CALIBRATION_GENERALIZATION")
        result["holdout_freeze"] = campaign.freeze_holdout(holdout)
        result["holdout"] = campaign.run_cases(holdout, phase="HOLDOUT", partition="HOLDOUT")
    summary = campaign.summary(); result["summary"] = summary
    if phase == "targeted":
        result["status"] = "TARGETED_GREENFIELD_PASS"
    else:
        mini_rows = [*result.get("calibration_generalization", ()), *result.get("holdout", ())]
        success = sum(item["final_status"] == "PASS" for item in mini_rows)
        holdout_success = sum(item["final_status"] == "PASS" for item in result.get("holdout", ()))
        transport = sum(item.get("failure_domain") == "PROVIDER_TRANSPORT_FAILURE" for item in mini_rows)
        result["status"] = "GREENFIELD_BUNDLE_MULTI_PROJECT_READY" if success >= 6 and holdout_success >= 1 and transport <= 2 else ("GREENFIELD_BUNDLE_PRODUCTION_PASS_WITH_LIMITS" if success == 5 and holdout_success >= 1 else "GREENFIELD_BUNDLE_CAMPAIGN_NEEDS_REWORK")
    _write(output_root / "final_report.json", result)
    return result


def _write_connection_route(root: pathlib.Path) -> None:
    raw = str(os.environ.get("HTTPS_PROXY", "") or os.environ.get("https_proxy", "")).strip()
    allowed = raw in {"http://127.0.0.1:7890", "http://localhost:7890"}
    if raw and not allowed:
        raise RuntimeError("campaign HTTPS proxy must be the operator-authorized loopback endpoint")
    _write(root / "connection_route.json", {"kind": "CampaignConnectionRoute", "schema_version": "1.0", "provider": "grok", "route": "LOOPBACK_PROXY" if allowed else "DIRECT", "proxy_endpoint": "127.0.0.1:7890" if allowed else "", "credentials_present": False, "contains_credentials": False})


def _write(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, timeout=30)
    if result.returncode: raise RuntimeError(result.stderr.strip() or "git failed")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-root", type=pathlib.Path, default=ROOT / "artifacts" / "campaigns" / CAMPAIGN_DIR); parser.add_argument("--phase", choices=("targeted", "mini", "all"), default="all")
    args = parser.parse_args(); result = run(args.output_root.resolve(), phase=args.phase); print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["status"] not in {"GREENFIELD_BUNDLE_GENERATION_NEEDS_REWORK", "GREENFIELD_BUNDLE_CAMPAIGN_NEEDS_REWORK"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
