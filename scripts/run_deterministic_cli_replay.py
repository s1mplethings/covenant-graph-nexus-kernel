from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

from cgkn.application.project_campaign.greenfield_v2 import _csv_profile_case
from cgkn.application.project_campaign.matrix import campaign_matrix
from cgkn.application.project_campaign.service import _compile, _evaluate, _pytest, _render_tests
from cgkn.application.software_project.greenfield import DeterministicCLICompiler, StructuredCLIPlan


REPLAY_IDS = ("duplicate_finder_cli", "env_audit_cli", "csv_column_profile_cli", "rename_plan_cli")
ERROR_ARGV = {
    "duplicate_finder_cli": ["missing-root"],
    "env_audit_cli": ["missing.env"],
    "csv_column_profile_cli": ["missing.csv"],
    "rename_plan_cli": ["missing-root", "--pattern", "*.txt", "--template", "file-{index}.txt"],
}


def _domain_source(project_root: pathlib.Path, package: str) -> tuple[pathlib.Path, dict]:
    candidates = sorted(project_root.glob(f"greenfield_v2/candidate_lifecycle/candidate_runs/*domain*/**/revision.json"))
    if not candidates:
        raise FileNotFoundError("OLD_DOMAIN_REVISION_MISSING")
    revision_path = candidates[-1]
    revision = json.loads(revision_path.read_text(encoding="utf-8"))
    source = revision_path.parent / "source" / package / "core.py"
    if not source.is_file():
        raise FileNotFoundError("OLD_DOMAIN_SOURCE_MISSING")
    row = next(item for item in revision["source_manifest"] if item["path"] == f"{package}/core.py")
    actual = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    if actual != row["sha256"]:
        raise ValueError("OLD_DOMAIN_SOURCE_HASH_MISMATCH")
    return source, revision


def run(source_root: pathlib.Path, output_root: pathlib.Path) -> dict:
    by_id = {case.project_id: case for case in campaign_matrix()}
    by_id["csv_column_profile_cli"] = _csv_profile_case()
    compiler = DeterministicCLICompiler(); rows = []
    for project_id in REPLAY_IDS:
        case = by_id[project_id]; old_root = source_root / "projects" / project_id
        workspace = output_root / "projects" / project_id / "workspace"
        if workspace.exists(): shutil.rmtree(workspace)
        workspace.mkdir(parents=True)
        result = {"project_id": project_id, "domain_reused": False, "provider_calls": 0, "cli_provider_calls": 0}
        try:
            core, revision = _domain_source(old_root, case.package_name)
            package = workspace / case.package_name; package.mkdir()
            shutil.copyfile(core, package / "core.py")
            plan = StructuredCLIPlan.from_dict(case.cli_contract)
            domain_exports = ("execute", "ProjectError")
            (package / "__init__.py").write_text(compiler.render_init(domain_module=f"{case.package_name}.core", exports=domain_exports), encoding="utf-8", newline="\n")
            (package / "__main__.py").write_text(compiler.render_main(plan), encoding="utf-8", newline="\n")
            for name in ("pyproject.toml", "README.md"):
                source = old_root / "workspace" / name
                if source.is_file(): shutil.copyfile(source, workspace / name)
            _render_tests(workspace, case)
            help_run = subprocess.run([sys.executable, "-m", case.package_name, "--help"], cwd=workspace, text=True, capture_output=True, timeout=30)
            error_run = subprocess.run([sys.executable, "-m", case.package_name, *ERROR_ARGV[project_id]], cwd=workspace, text=True, capture_output=True, timeout=30)
            result.update(help_pass=help_run.returncode == 0 and "usage:" in help_run.stdout.lower() and not help_run.stderr,
                          exact_error_pass=error_run.returncode == 2 and bool(error_run.stderr.strip()) and "Traceback" not in error_run.stderr)
            compile_result = _compile(workspace, case); tests = _pytest(workspace)
            oracle = _evaluate(workspace, case.package_name, case.public_cases, "oracle")
            hidden = _evaluate(workspace, case.package_name, case.hidden_cases, "hidden")
            result.update(status="PASS", domain_reused=True, domain_revision_id=revision["revision_id"], domain_source_hash=revision["source_hash"],
                          plan_hash=plan.plan_hash, compiler_version=compiler.VERSION, compile=compile_result, tests=tests, oracle=oracle, hidden=hidden,
                          cli_source_hash="sha256:" + hashlib.sha256((package / "__main__.py").read_bytes()).hexdigest())
        except Exception as exc:
            result.update(status="FAIL", failure_class=type(exc).__name__, failure=str(exc)[-1200:])
        rows.append(result)
    passed = sum(row["status"] == "PASS" for row in rows)
    return {"kind": "DeterministicCLIReplayReceipt", "schema_version": "1.0", "status": "PASS" if passed >= 3 else "DETERMINISTIC_CLI_NEEDS_REWORK",
            "passed": passed, "total": 4, "cli_provider_calls": 0, "help_passed": sum(bool(row.get("help_pass")) for row in rows),
            "exact_error_passed": sum(bool(row.get("exact_error_pass")) for row in rows), "projects": rows, "contains_credentials": False}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--source-root", type=pathlib.Path, required=True); parser.add_argument("--output-root", type=pathlib.Path, required=True)
    args = parser.parse_args(); value = run(args.source_root.resolve(), args.output_root.resolve())
    args.output_root.mkdir(parents=True, exist_ok=True); target = args.output_root / "cli_replay_receipt.json"
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False)); return 0 if value["status"] == "PASS" else 2


if __name__ == "__main__": raise SystemExit(main())
