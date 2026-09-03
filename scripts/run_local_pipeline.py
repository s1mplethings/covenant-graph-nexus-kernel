#!/usr/bin/env python3
"""Slim reviewed facade for the API/provider project-generation implementation."""
from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

try:
    from . import run_local_pipeline_impl as _impl
except ImportError:  # pragma: no cover - direct script execution
    import run_local_pipeline_impl as _impl


check_connectivity = _impl.check_connectivity
compose_local_pipeline = _impl.compose_local_pipeline
market_research_agent = _impl.market_research_agent
online_input_agent = _impl.online_input_agent
requirement_blueprint = _impl.requirement_blueprint

provider_text = _impl.provider_text
provider_generate_project_component = _impl.provider_generate_project_component
provider_generate_project_by_components = _impl.provider_generate_project_by_components
merge_component_files = _impl.merge_component_files
validate_provider_files = _impl.validate_provider_files
write_provider_files = _impl.write_provider_files
prepare_supervision_provider_repair = _impl.prepare_supervision_provider_repair

DEFAULT_GENERATED_DIR = _impl.DEFAULT_GENERATED_DIR
DEFAULT_RUN_DIR = _impl.DEFAULT_RUN_DIR
DEFAULT_RESULT_PATH = _impl.DEFAULT_RESULT_PATH
GENERATION_POLICY = _impl.GENERATION_POLICY
# Stable source-visible contract marker used by mutation guards and reviewers.
GENERATION_AUTHORITY = "api_provider_for_delivery_simulator_for_preflight_only"

RUNNABLE_ENTRYPOINTS = {"app.py", "main.py", "package.json", "index.html"}
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".vue", ".svelte"}
GENERIC_PROJECT_MARKERS = ("generic app", "template app", "placeholder project", "sample project")
PLACEHOLDER_SOURCE_MARKERS = ("todo: implement", "notimplementederror", "placeholder implementation")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_recoverable_repair_errors(result_path: pathlib.Path, goal: str) -> list[str]:
    if not result_path.is_file():
        return []
    try:
        prior = load_json(result_path)
    except (OSError, ValueError, TypeError):
        return []
    if (
        str(prior.get("status", "")).upper() != "BLOCKED"
        or prior.get("reason") != "provider_generation_failed"
        or str(prior.get("goal", "")).strip() != goal.strip()
    ):
        return []
    errors = prior.get("repair_errors", [])
    return [str(error) for error in errors[-5:] if str(error).strip()] if isinstance(errors, list) else []


def validate_provider_project_contract(doc: dict[str, Any], files: list[dict[str, str]]) -> None:
    paths = {str(item.get("path", "")).replace("\\", "/") for item in files}
    missing_docs = [name for name in ("README.md", "TEST_PLAN.md") if name not in paths]
    if missing_docs:
        raise RuntimeError("provider project payload missing required files: " + ", ".join(missing_docs))
    if not any(pathlib.PurePosixPath(path).name in RUNNABLE_ENTRYPOINTS for path in paths):
        raise RuntimeError("provider project payload missing runnable entrypoint")
    metadata = " ".join(str(doc.get(key, "")) for key in ("project_type", "summary")).lower()
    if any(marker in metadata for marker in GENERIC_PROJECT_MARKERS):
        raise RuntimeError("provider returned generic/template project metadata")
    source_files = [
        item
        for item in files
        if pathlib.PurePosixPath(item["path"]).suffix.lower() in SOURCE_SUFFIXES
        and not item["path"].replace("\\", "/").lower().startswith(("tests/", "test/"))
    ]
    if not source_files:
        raise RuntimeError("provider project payload missing implementation source files")
    placeholder_paths: list[str] = []
    for item in source_files:
        content = str(item["content"])
        compact = re.sub(r"\s+", " ", content).strip().lower()
        code_only = re.sub(r"(?m)^\s*(#|//).*$", "", content).strip()
        if any(marker in compact for marker in PLACEHOLDER_SOURCE_MARKERS) or re.fullmatch(
            r"(?:pass|raise\s+NotImplementedError(?:\([^)]*\))?)\s*", code_only
        ):
            placeholder_paths.append(item["path"])
    if placeholder_paths:
        raise RuntimeError("provider emitted placeholder project content: " + ", ".join(sorted(placeholder_paths)))


def _blocked_without_api(args: argparse.Namespace) -> dict[str, Any]:
    goal = str(getattr(args, "goal", "") or "").strip()
    out_dir = pathlib.Path(getattr(args, "out_dir", DEFAULT_GENERATED_DIR)).resolve()
    run_dir = pathlib.Path(getattr(args, "run_dir", DEFAULT_RUN_DIR)).resolve()
    result_path = pathlib.Path(getattr(args, "result", DEFAULT_RESULT_PATH)).resolve()
    result = {
        "kind": "RuntimeExecutionResult",
        "status": "BLOCKED",
        "generated_at": now(),
        "goal": goal,
        "generation_context_goal": goal,
        "project_dir": str(out_dir),
        "run_dir": str(run_dir),
        "reason": "provider_api_disabled_by_default",
        "message": "Project generation requires the reviewed API/provider route.",
        "missing_artifacts": ["package", "screenshot", "verify_report"],
        "provider": {"requested": False, "executed": False},
        "policy": GENERATION_POLICY,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if not bool(getattr(args, "use_api", False)):
        return _blocked_without_api(args)
    return _impl.execute(args)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.set_defaults(allow_network=False, allow_provider=False, use_api=False)
    parser.add_argument("--plan", default="")
    parser.add_argument("--goal", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_GENERATED_DIR))
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--resume-run-dir", default="")
    parser.add_argument("--codex-capability-brief", default="")
    parser.add_argument("--result", "--result-path", dest="result", default=str(DEFAULT_RESULT_PATH))
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-provider", action="store_true")
    parser.add_argument("--use-api", action="store_true")
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--small-model", default="")
    parser.add_argument("--large-model", default="")
    parser.add_argument("--disable-model-routing", action="store_true")
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--allow-model-usage-planning", action="store_true")
    parser.add_argument("--phase-log-path", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = execute(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"LOCAL_PIPELINE_EXECUTION: {str(result['status']).upper()}")
        print(f"project_dir={result['project_dir']}")
        print(f"run_dir={result['run_dir']}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
