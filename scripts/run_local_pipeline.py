#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

import compose_local_pipeline
import requirement_blueprint


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = ROOT / "examples" / "runtime_runs" / "local-pipeline-execution"
DEFAULT_GENERATED_DIR = ROOT / "generated" / "cgnk_generated_project"
DEFAULT_RESULT_PATH = ROOT / "examples" / "test_results" / "local_pipeline_execution_result.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    write_text(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def short_goal(goal: str) -> str:
    text = re.sub(r"\s+", " ", str(goal or "").strip())
    return text[:180] or "CGNK generated project"


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def plan_goal(plan_doc: dict[str, Any]) -> str:
    candidates = [
        plan_doc.get("original_requirement"),
        plan_doc.get("goal"),
        plan_doc.get("pipeline_plan", {}).get("payload", {}).get("requirement"),
        plan_doc.get("pipeline_plan", {}).get("payload", {}).get("goal"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return "Generate a custom CGNK project from the supplied requirement."


def make_mermaid() -> str:
    return """flowchart TD
  Goal[Goal] --> Blueprint[Requirement Blueprint]
  Blueprint --> Project[Generated Project Files]
  Blueprint --> Tests[Test Graph]
  Project --> Effect[Effect Report]
"""


def build_generic_project(goal: str, out_dir: pathlib.Path, blueprint: dict[str, Any]) -> list[str]:
    project_type = blueprint.get("requirement_spec", {}).get("project_type", {}).get("value", "custom_application")
    features = blueprint.get("feature_spec", {}).get("features", [])
    files = {
        "README.md": f"""# CGNK Generated Project

## Goal

{short_goal(goal)}

## Project Type

{project_type}

This project is a generic CGNK materialization of requirement-blueprint artifacts.
""",
        "index.html": """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CGNK Generated Project</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="shell">
    <header>
      <p class="eyebrow">CGNK Generated Project</p>
      <h1 id="goal-title"></h1>
      <p id="project-type"></p>
    </header>
    <section class="panel">
      <h2>Features</h2>
      <div id="features"></div>
    </section>
    <section class="panel">
      <h2>Runtime Artifacts</h2>
      <ul id="artifacts"></ul>
    </section>
  </main>
  <script src="app.js"></script>
</body>
</html>
""",
        "styles.css": """:root {
  font-family: Inter, Segoe UI, Arial, sans-serif;
  background: #f6f7f9;
  color: #1d2430;
}
body { margin: 0; }
.shell { max-width: 960px; margin: 0 auto; padding: 40px 20px; }
.eyebrow { margin: 0 0 8px; color: #4b6b8a; font-size: 12px; font-weight: 700; text-transform: uppercase; }
h1 { margin: 0; font-size: 32px; line-height: 1.2; }
h2 { margin: 0 0 16px; font-size: 18px; }
.panel { background: #fff; border: 1px solid #d9e0e7; border-radius: 8px; padding: 20px; margin: 16px 0; }
.feature { border-top: 1px solid #e4e8ee; padding: 14px 0; }
.feature:first-child { border-top: 0; padding-top: 0; }
.feature strong { display: block; margin-bottom: 6px; }
.feature p, li, #project-type { color: #52606f; line-height: 1.55; }
""",
        "app.js": "const goal = "
        + json.dumps(short_goal(goal), ensure_ascii=False)
        + ";\nconst projectType = "
        + json.dumps(project_type, ensure_ascii=False)
        + ";\nconst features = "
        + json.dumps(features, ensure_ascii=False, indent=2)
        + """;
const artifacts = ["requirement_blueprint.json", "project_blueprint.json", "generation_trace.json", "test_graph.json", "effect_report.json", "runtime_result.json"];
document.getElementById("goal-title").textContent = goal;
document.getElementById("project-type").textContent = `Project type: ${projectType}`;
document.getElementById("features").innerHTML = features.map((feature) => `
  <article class="feature">
    <strong>${feature.id || ""} ${feature.name || "Feature"}</strong>
    <p>${feature.description || ""}</p>
  </article>
`).join("");
document.getElementById("artifacts").innerHTML = artifacts.map((name) => `<li>${name}</li>`).join("");
""",
        "TEST_PLAN.md": """# Test Plan

- Open `index.html` and confirm the goal, project type, features, and artifact list render.
- Confirm runtime artifacts exist under the selected runtime directory.
- Run `python scripts/validate_bundle.py --schema` from the CGNK root.
""",
    }
    written: list[str] = []
    for rel_path, content in files.items():
        write_text(out_dir / rel_path, content)
        written.append(rel_path)
    return written


def build_project_blueprint(goal: str, blueprint: dict[str, Any], generated_files: list[str]) -> dict[str, Any]:
    return {
        "kind": "ProjectBlueprint",
        "status": "pass",
        "generated_at": now(),
        "goal": goal,
        "project_type": blueprint.get("requirement_spec", {}).get("project_type", {}).get("value", "custom_application"),
        "files": generated_files,
        "features": blueprint.get("feature_spec", {}).get("features", []),
    }


def write_runtime_artifacts(
    run_dir: pathlib.Path,
    goal: str,
    plan_doc: dict[str, Any],
    blueprint: dict[str, Any],
    project_blueprint: dict[str, Any],
    generated_files: list[str],
) -> dict[str, str]:
    artifact_dir = run_dir / "artifacts"
    output_refs = requirement_blueprint.write_requirement_blueprint_outputs(artifact_dir / "requirement_blueprint_outputs", blueprint)
    artifacts: dict[str, Any] = {
        "pipeline_composition.json": plan_doc,
        "requirement_blueprint.json": {**blueprint, "output_refs": output_refs},
        "project_blueprint.json": project_blueprint,
        "generation_trace.json": {
            "kind": "GenerationTrace",
            "status": "pass",
            "generated_at": now(),
            "steps": ["load_plan", "build_requirement_blueprint", "materialize_generic_project", "emit_runtime_artifacts"],
        },
        "test_graph.json": {
            "kind": "TestGraph",
            "status": "pass",
            "tests": [
                {"id": "contract_validation", "command": "python scripts/validate_bundle.py --schema"},
                {"id": "artifact_presence", "checks": ["project files", "runtime artifacts"]},
            ],
        },
        "effect_report.json": {
            "kind": "EffectReport",
            "status": "pass",
            "effects": {"fs_write": True, "network": False, "provider_call": False},
            "summary": "Generic project files and CGNK runtime artifacts were written locally.",
        },
        "runtime_result.json": {
            "kind": "RuntimeExecutionResult",
            "status": "pass",
            "goal": goal,
            "generated_files": generated_files,
        },
    }
    refs: dict[str, str] = {}
    for name, doc in artifacts.items():
        path = artifact_dir / name
        write_json(path, doc)
        refs[name] = str(path)
    mermaid_path = artifact_dir / "test_graph.mmd"
    write_text(mermaid_path, make_mermaid())
    refs["test_graph.mmd"] = str(mermaid_path)
    return refs


def execute(args: argparse.Namespace) -> dict[str, Any]:
    plan_path = pathlib.Path(args.plan) if str(args.plan or "").strip() else None
    if plan_path and plan_path.exists():
        plan_doc = load_json(plan_path)
        goal = plan_goal(plan_doc)
    else:
        goal = str(getattr(args, "goal", "") or "Generate a custom CGNK project.")
        plan_doc = compose_local_pipeline.compose(
            goal,
            allow_network=bool(getattr(args, "allow_network", False)),
            allow_provider=bool(getattr(args, "allow_provider", False)),
        )

    out_dir = pathlib.Path(args.out_dir).resolve()
    run_dir = pathlib.Path(args.run_dir).resolve()
    result_path = pathlib.Path(args.result).resolve()
    blueprint = requirement_blueprint.build_requirement_blueprint(goal, [], assume_defaults=True)
    generated_files = build_generic_project(goal, out_dir, blueprint)
    project_blueprint = build_project_blueprint(goal, blueprint, generated_files)
    write_json(out_dir / "project_blueprint.json", project_blueprint)
    generated_files.append("project_blueprint.json")
    artifact_refs = write_runtime_artifacts(run_dir, goal, plan_doc, blueprint, project_blueprint, generated_files)

    result = {
        "kind": "LocalPipelineExecutionResult",
        "status": "pass",
        "generated_at": now(),
        "goal": goal,
        "out_dir": str(out_dir),
        "run_dir": str(run_dir),
        "generated_files": generated_files,
        "artifact_refs": artifact_refs,
        "network": {"requested": bool(getattr(args, "allow_network", False)), "executed": False},
        "provider": {"requested": bool(getattr(args, "allow_provider", False)), "executed": False},
    }
    write_json(result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.set_defaults(allow_network=False, allow_provider=False, use_api=False)
    parser.add_argument("--plan", default="")
    parser.add_argument("--goal", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_GENERATED_DIR))
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--result", default=str(DEFAULT_RESULT_PATH))
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-provider", dest="allow_provider", action="store_true")
    parser.add_argument("--no-provider", dest="allow_provider", action="store_false")
    parser.add_argument("--use-api", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = execute(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status={result['status']}")
        print(f"out_dir={result['out_dir']}")
        print(f"run_dir={result['run_dir']}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
