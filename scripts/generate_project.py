#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

import compose_local_pipeline
import context_prompt
import requirement_blueprint
import run_local_pipeline

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
    run_dir = ROOT / "examples" / "runtime_runs" / project_slug
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
        json=False,
    )
    execution = run_local_pipeline.execute(ns)

    effect_report_path = run_dir / "artifacts" / "effect_report.json"
    test_graph_path = run_dir / "artifacts" / "test_graph.mmd"
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
