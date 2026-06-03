#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import compose_local_pipeline
import context_prompt
import local_intent_router
import requirement_blueprint
import run_local_pipeline
import run_product_studio

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_RESULT = ROOT / "examples" / "test_results" / "customer_generation_result.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", str(text or "").strip().lower())
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "generated-project"


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_phase_log(path: pathlib.Path, phase: str, status: str, message: str, artifacts_written: list[str] | None = None, started_at: datetime | None = None) -> None:
    elapsed = 0.0
    if started_at is not None:
        elapsed = round((datetime.now(timezone.utc) - started_at).total_seconds(), 3)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": now(),
                    "phase": phase,
                    "status": status,
                    "message": message,
                    "artifacts_written": artifacts_written or [],
                    "elapsed_seconds": elapsed,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def artifact_status(paths: dict[str, pathlib.Path]) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    for name, path in paths.items():
        (present if path.exists() else missing).append(name)
    return present, missing


def write_failure_result(
    path: pathlib.Path,
    *,
    reason: str,
    message: str,
    phase_log_path: pathlib.Path,
    artifact_paths: dict[str, pathlib.Path],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    present, missing = artifact_status(artifact_paths)
    result = {
        "kind": "CustomerProjectGenerationResult",
        "created_at": now(),
        "status": "BLOCKED",
        "reason": reason,
        "message": message,
        "last_known_phase": last_known_phase(phase_log_path),
        "artifacts_detected": present,
        "missing_artifacts": missing,
        "phase_log_path": str(phase_log_path),
        "can_retry": True,
        "retry_should_reuse": [
            "product_studio_run.json",
            "customer_intent.raw_user_message",
            "output_contract",
            "frozen_project_type",
        ],
    }
    if extra:
        result.update(extra)
    write_json(path, result)
    return result


def last_known_phase(phase_log_path: pathlib.Path) -> str:
    if not phase_log_path.exists():
        return ""
    last = ""
    for line in phase_log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict) and doc.get("phase"):
            last = str(doc["phase"])
    return last


def build_enriched_goal(requirement: str, answers: list[dict[str, str]], blueprint: dict[str, Any], max_chars: int) -> tuple[str, dict[str, Any]]:
    pack = context_prompt.build_prompt_pack(
        requirement,
        answers,
        blueprint,
        purpose="project_generation",
        max_chars=max_chars,
    )
    if pack.get("quality", {}).get("status") != "pass":
        issues = ", ".join(str(item) for item in pack.get("quality", {}).get("issues", []))
        raise SystemExit(f"context prompt quality failed: {issues}")
    return str(pack["prompt_text"]), pack


def run_generation(args: argparse.Namespace) -> dict[str, Any]:
    requirement = str(args.requirement or "").strip()
    if not requirement:
        raise SystemExit("--requirement is required")
    answers: list[dict[str, str]] = []
    project_slug = args.project_slug or slug(requirement)[:60]
    run_dir = ROOT / "examples" / "runtime_runs" / project_slug
    artifacts_dir = run_dir / "artifacts"
    phase_log_path = artifacts_dir / "generation_phase_log.jsonl"
    result_path = pathlib.Path(args.result_path).resolve()
    phase_started = datetime.now(timezone.utc)
    append_phase_log(phase_log_path, "intake", "started", "Captured generation requirement.", started_at=phase_started)
    intent = local_intent_router.classify_project_type(requirement)
    append_phase_log(phase_log_path, "intent_routing", "completed", f"Routed project_type={intent.get('project_type')}.", started_at=phase_started)
    blueprint = requirement_blueprint.build_requirement_blueprint(
        requirement,
        answers,
        assume_defaults=False,
    )
    composition_path = ROOT / "examples" / "test_results" / f"{project_slug}_composition.json"
    execution_path = ROOT / "examples" / "test_results" / f"{project_slug}_execution.json"
    requirement_blueprint_path = ROOT / "examples" / "test_results" / f"{project_slug}_requirement_blueprint.json"
    context_prompt_path = ROOT / "examples" / "test_results" / f"{project_slug}_context_prompt.json"
    out_dir = ROOT / "generated" / project_slug
    product_studio_run_path = artifacts_dir / "product_studio_run.json"
    product_studio_run = run_product_studio.build_product_studio_run(
        str(intent.get("raw_user_message") or requirement),
        "CSGO2 demo file" if intent.get("project_type") == "game_demo_telemetry_analyzer" else "",
        "operation statistics, heatmap/frequency visualizations, image report, PDF report",
        ["Do not claim deep ML cheat detection or final cheat verdicts."],
    )
    write_json(product_studio_run_path, product_studio_run)
    append_phase_log(phase_log_path, "product_studio_run", "completed", "Product Studio run artifact written.", [str(product_studio_run_path)])
    enriched_goal, prompt_pack = build_enriched_goal(requirement, answers, blueprint, int(args.prompt_max_chars))

    composition = compose_local_pipeline.compose(
        enriched_goal,
        allow_network=bool(args.allow_network),
        allow_provider=bool(args.allow_provider),
        use_local_model=bool(args.use_local_model),
    )
    composition["original_requirement"] = requirement
    composition["requirement_blueprint"] = blueprint
    composition["requirement_blueprint_ref"] = str(requirement_blueprint_path)
    composition["context_prompt_ref"] = str(context_prompt_path)
    write_json(composition_path, composition)
    write_json(requirement_blueprint_path, blueprint)
    write_json(context_prompt_path, prompt_pack)

    ns = argparse.Namespace(
        goal=enriched_goal,
        plan=str(composition_path),
        out_dir=str(out_dir),
        run_dir=str(run_dir),
        result=str(execution_path),
        allow_network=bool(args.allow_network),
        allow_provider=bool(args.allow_provider),
        use_api=bool(args.use_api),
        model=str(args.model),
        timeout=int(args.timeout),
        allow_model_usage_planning=bool(getattr(args, "allow_model_usage_planning", False)),
        phase_log_path=str(phase_log_path),
        json=False,
    )
    artifact_paths = {
        "product_studio_run.json": product_studio_run_path,
        "composition.json": composition_path,
        "requirement_blueprint.json": requirement_blueprint_path,
        "context_prompt.json": context_prompt_path,
        "execution.json": execution_path,
        "effect_report.json": run_dir / "artifacts" / "effect_report.json",
        "test_graph.mmd": run_dir / "artifacts" / "test_graph.mmd",
    }
    try:
        execution = run_local_pipeline.execute(ns)
    except Exception as exc:
        append_phase_log(phase_log_path, "delivery_bundle", "failed", str(exc))
        return write_failure_result(
            result_path,
            reason="generation_pipeline_error",
            message=str(exc),
            phase_log_path=phase_log_path,
            artifact_paths=artifact_paths,
        )

    effect_report_path = run_dir / "artifacts" / "effect_report.json"
    test_graph_path = run_dir / "artifacts" / "test_graph.mmd"
    if str(execution.get("status", "")).upper() == "BLOCKED":
        append_phase_log(phase_log_path, "delivery_bundle", "failed", str(execution.get("reason", "blocked")))
        return write_failure_result(
            result_path,
            reason=str(execution.get("reason", "blocked")),
            message="Project generation was blocked before delivery.",
            phase_log_path=phase_log_path,
            artifact_paths=artifact_paths,
            extra={"execution": execution},
        )
    append_phase_log(phase_log_path, "delivery_bundle", "completed", "Generation result written.", [str(result_path)])
    result = {
        "kind": "CustomerProjectGenerationResult",
        "created_at": now(),
        "requirement": requirement,
        "customer_service": {
            "answers": answers,
            "mode": "local_requirement_blueprint",
            "policy": "No domain-specific local question template or product default answers are applied during generation.",
        },
        "requirement_blueprint_path": str(requirement_blueprint_path),
        "context_prompt_path": str(context_prompt_path),
        "context_prompt_budget": prompt_pack.get("budget", {}),
        "requirement_blueprint_status": blueprint.get("status", "unknown"),
        "composition_path": str(composition_path),
        "execution_path": str(execution_path),
        "project_dir": str(out_dir),
        "runtime_dir": str(run_dir),
        "effect_report_path": str(effect_report_path),
        "test_graph_path": str(test_graph_path),
        "phase_log_path": str(phase_log_path),
        "product_studio_run_path": str(product_studio_run_path),
        "status": execution.get("status", "unknown"),
    }
    write_json(pathlib.Path(args.result_path).resolve(), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.set_defaults(allow_network=True, allow_provider=True, use_api=True, use_local_model=False)
    parser.add_argument("--requirement", required=True)
    parser.add_argument("--project-slug", default="")
    parser.add_argument("--assume-defaults", action="store_true", help="Deprecated no-op. Local default-answer templates are disabled.")
    parser.add_argument("--allow-network", dest="allow_network", action="store_true", help="Allow network routes. Enabled by default for provider project generation.")
    parser.add_argument("--no-network", dest="allow_network", action="store_false", help="Disable network routes. Project-file generation will fail under provider-only policy.")
    parser.add_argument("--allow-provider", dest="allow_provider", action="store_true", help="Allow provider/API calls. Enabled by default for provider project generation.")
    parser.add_argument("--no-provider", dest="allow_provider", action="store_false", help="Disable provider/API calls.")
    parser.add_argument("--use-api", dest="use_api", action="store_true", help="Use API for provider-side generation. Enabled by default.")
    parser.add_argument("--no-api", dest="use_api", action="store_false", help="Disable API generation. Project-file generation will fail under provider-only policy.")
    parser.add_argument("--use-local-model", dest="use_local_model", action="store_true", help="Use CGNK_LOCAL_MODEL_CMD or local Ollama for route hints.")
    parser.add_argument("--prompt-max-chars", type=int, default=6000, help="Maximum local compressed context prompt size before route/generation use.")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--result-path", default=str(DEFAULT_RESULT))
    parser.add_argument("--allow-model-usage-planning", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_generation(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"CUSTOMER_PROJECT_GENERATION: {str(result['status']).upper()}")
        print(f"project_dir={result['project_dir']}")
        print(f"effect_report={result['effect_report_path']}")
        print(f"test_graph={result['test_graph_path']}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
