from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.agent import AgentComposer, AgentProjectLoop
from cgkn.execution import BlockExecutionRequest, TaskContext
from cgkn.executors import ExecutorRegistry, FileExecutor, LLMExecutor, PythonTestExecutor
from cgkn.providers import ModelRoleConfig, OpenAICompatibleClient
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore


def load_config(path: pathlib.Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("kind") != "CGKNAgentMVPConfig" or value.get("schema_version") != "1.0":
        raise ValueError("unsupported Agent MVP config")
    if value["agent"]["model"] == value["worker"]["model"]:
        raise ValueError("Agent and worker models must differ")
    return value


def role_config(role: str, value: dict) -> ModelRoleConfig:
    return ModelRoleConfig(role, str(value["model"]), int(value.get("timeout_seconds", 60)), int(value.get("max_output_tokens", 2000)), 0.0, str(value.get("reasoning_effort", "none")))


def run_initial_test(project: pathlib.Path) -> dict:
    environment = os.environ.copy()
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=project, text=True, capture_output=True, timeout=60, env=environment)
    return {"returncode": completed.returncode, "stdout": completed.stdout[-4000:], "stderr": completed.stderr[-4000:]}


def run_direct_baseline(root: pathlib.Path, client: OpenAICompatibleClient, high_model: ModelRoleConfig) -> dict:
    project = root / "baseline-project"
    shutil.copytree(ROOT / "examples" / "agent_mvp_bugfix", project)
    before = run_initial_test(project)
    request = BlockExecutionRequest(
        project_id="agent-mvp-baseline", run_id="direct", attempt_id="attempt-0001", node_id="fix",
        component_ref="code.modify@1", executor_ref="llm.cheap@1",
        task_context=TaskContext(node_goal="Correct add so it returns the sum", node_config={}, dependency_results={"inspect": {"path": "math_utils.py", "content": (project / "math_utils.py").read_text(encoding="utf-8")}}, acceptance=("pytest passes",)),
    )
    direct_config = ModelRoleConfig("worker", high_model.model, high_model.timeout_seconds, high_model.max_output_tokens, high_model.temperature, high_model.reasoning_effort)
    result = LLMExecutor(project, client, direct_config).execute(request)
    after = run_initial_test(project)
    return {"name": "high_agent_direct_file_task", "model": high_model.model, "provider_calls": 1, "initial_test_returncode": before["returncode"], "final_test_returncode": after["returncode"], "execution": result.as_dict(), "status": "PASS" if result.succeeded and after["returncode"] == 0 else "FAIL"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the bounded CGKN Agent + cheap LLM MVP vertical slice")
    parser.add_argument("--run-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", type=pathlib.Path, default=ROOT / "config" / "agent_mvp.json")
    parser.add_argument("--project-root", type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--benchmark", action="store_true", help="Also run a direct high-model baseline on a separate fixture copy")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    project = args.project_root.resolve() if args.project_root else (args.run_root / "project").resolve()
    if not args.project_root:
        if project.exists():
            raise FileExistsError(f"generated project path already exists: {project}")
        shutil.copytree(ROOT / "examples" / "agent_mvp_bugfix", project)
    args.run_root.mkdir(parents=True, exist_ok=True)
    initial_test = run_initial_test(project)
    run_id = f"agent-mvp-{uuid.uuid4().hex[:10]}"
    store = FileRunStore(args.run_root / "runs")
    client = OpenAICompatibleClient()
    agent_config, worker_config = role_config("agent", config["agent"]), role_config("worker", config["worker"])
    registry = ExecutorRegistry()
    registry.register(FileExecutor(project))
    registry.register(LLMExecutor(project, client, worker_config))
    registry.register(PythonTestExecutor(project))
    goal = "Fix the failing math_utils.add implementation in this small Python project. Compose exactly three executable nodes: inspect uses repo.inspect@1 with local.file@1 read_file math_utils.py; fix uses code.modify@1 with llm.cheap@1 and depends on inspect; test uses test.python@1 with local.python-test@1 and depends on fix. Request a run after composing. After a successful pytest result, finish. After a failure or worker escalation, make the smallest update_config plus retry_node repair and request another run."
    try:
        catalog = {
            "repo.inspect@1": {"executor_ref": "local.file@1", "action": "read_file", "path": "math_utils.py"},
            "code.modify@1": {"executor_ref": "llm.cheap@1", "goal": "Correct add so it returns the sum", "acceptance": ["pytest passes"]},
            "test.python@1": {"executor_ref": "local.python-test@1", "pytest_args": ["-q"]},
        }
        result = AgentProjectLoop(AgentComposer(client, agent_config), DAGRunner(registry, store), store, known_capabilities=set(catalog), worker_model=worker_config.model, capability_catalog=catalog, max_decisions=int(config.get("max_agent_decisions", 4))).run(project_id="agent-mvp", run_id=run_id, goal=goal, constraints=("worker actions are read/list/write/patch only", "do not modify project goal"))
        status = "PASS" if initial_test["returncode"] != 0 and result.status == "SUCCEEDED" and result.worker_calls >= 1 else "FAIL"
        benchmark = run_direct_baseline(args.run_root, client, agent_config) if args.benchmark else None
        report = {"kind": "CGKNAgentMVPResult", "schema_version": "1.0", "status": status, "functional_readiness_candidate": "LEVEL_4" if status == "PASS" else "LEVEL_3", "provider_validation": "REAL", "agent_model": agent_config.model, "worker_model": worker_config.model, "initial_test": initial_test, "project_root": str(project), "run_root": str(args.run_root), "run_id": run_id, "result": result.as_dict(), "benchmark": benchmark, "decision_efficiency": {"baseline_high_model_calls": benchmark["provider_calls"] if benchmark else None, "cgkn_high_agent_calls": result.agent_calls, "cgkn_cheap_worker_calls": result.worker_calls, "note": "The baseline is reported as observed; it is not throttled or degraded."}}
    except Exception as exc:
        report = {"kind": "CGKNAgentMVPResult", "schema_version": "1.0", "status": "BLOCKED_PROVIDER", "functional_readiness_candidate": "LEVEL_3", "provider_validation": "BLOCKED_PROVIDER", "agent_model": agent_config.model, "worker_model": worker_config.model, "initial_test": initial_test, "project_root": str(project), "run_root": str(args.run_root), "run_id": run_id, "error": str(exc)}
    output = args.run_root / "agent_mvp_result.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) if args.json else report["status"])
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
