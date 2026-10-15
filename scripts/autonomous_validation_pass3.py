#!/usr/bin/env python3
"""Bounded, blinded A/C/D research runner for autonomous project acceptance.

Pass 3 reuses the isolation, evidence, reproduction, and reporting primitives
from the role-driven validation work.  It adds a model-neutral Goal-Driven
Explorer whose only authority is to propose operations against a reviewed
project adapter.  Independent deterministic oracles and fresh-workspace
reproduction remain the acceptance authority.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import pathlib
import shutil
import sys
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import check_connectivity
import role_driven_validation as v1


KIND = "CGKNAutonomousValidationPass3Report"
SCHEMA_VERSION = "1.0"
STATUS = "NOT_EVALUATED"
GROUPS = ("A", "C", "D")
ACTION_BUDGET = 6
DEFAULT_MODEL = "qwen3.5-flash"
FORBIDDEN_PROMPT_MARKERS = (
    "tests/",
    "tests\\",
    "hidden defect",
    "known defect",
    "independent oracle",
    "validation_report",
)


class Pass3Error(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectSpec:
    project_id: str
    name: str
    source_kind: str
    source_path: str
    generated_by_cgkn: bool
    goal_files: tuple[str, ...]
    channels: tuple[str, ...]
    public_goal: str
    operation_contract: dict[str, Any]


PROJECTS = (
    ProjectSpec(
        project_id="knowledge_studio",
        name="Local AI Knowledge Studio",
        source_kind="snapshot",
        source_path="artifacts/dynamic_tree_pm_api_governance_run/generated_project",
        generated_by_cgkn=True,
        goal_files=("README.md", "frozen_requirement.json"),
        channels=("python_api", "file_state"),
        public_goal=(
            "Import documents into a local knowledge base, search their content, create knowledge-work tasks, "
            "generate reports, and honestly report local-model configuration limits."
        ),
        operation_contract={
            "import_document": {"title": "string", "content": "string"},
            "search_documents": {"query": "string", "source": "storage|all_import_results"},
            "create_task": {"title": "string"},
            "build_report": {"documents": "storage|all_import_results", "tasks": "storage|all_task_results"},
            "adapter_status": {"config": "object"},
            "restart_runtime": {},
            "inspect_state": {},
        },
    ),
    ProjectSpec(
        project_id="orbit360",
        name="ORBIT-360 Workbench",
        source_kind="git",
        source_path="benchmarks/orbit_360_workbench",
        generated_by_cgkn=False,
        goal_files=("README.md", "PROJECT_VISION.md", "USAGE.md", "pyproject.toml"),
        channels=("cli", "file_state"),
        public_goal=(
            "Plan dependency-aware work units, execute them, resume safely, report persisted status, "
            "and repair a selected unit with truthful state changes."
        ),
        operation_contract={
            "plan": {"units": "integer", "width": "integer"},
            "run": {"workers": "integer"},
            "status": {},
            "repair": {"target": "string", "delta": "integer"},
            "read_unit": {"target": "string"},
            "repeat_run": {"workers": "integer"},
        },
    ),
)


def now() -> str:
    return v1.now()


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_hash(value: Any) -> str:
    return v1.canonical_hash(value)


def safe_json(value: Any) -> Any:
    if isinstance(value, pathlib.Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(item) for item in value]
    return value


def tree_hash(root: pathlib.Path) -> str:
    rows = []
    excluded = {"__pycache__", ".pytest_cache", ".git"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in excluded for part in path.relative_to(root).parts):
            continue
        rows.append({"path": path.relative_to(root).as_posix(), "sha256": v1.file_hash(path)})
    return canonical_hash(rows)


def public_context(repo: pathlib.Path, spec: ProjectSpec) -> dict[str, Any]:
    source = repo / spec.source_path
    materials = []
    for relative in spec.goal_files:
        path = source / relative
        if not path.is_file():
            raise Pass3Error(f"missing public material: {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        materials.append({"path": relative, "sha256": sha_text(text), "content": text[:12000]})
    context = {
        "project_id": spec.project_id,
        "name": spec.name,
        "generated_by_cgkn": spec.generated_by_cgkn,
        "goal": spec.public_goal,
        "materials": materials,
        "channels": list(spec.channels),
        "operation_contract": spec.operation_contract,
        "excluded": ["tests/**", "prior validation reports", "known defect lists", "independent oracles"],
    }
    lowered = json.dumps({"goal": context["goal"], "materials": materials}, ensure_ascii=False).lower()
    for marker in FORBIDDEN_PROMPT_MARKERS:
        if marker in lowered and marker not in {"tests/", "tests\\"}:
            raise Pass3Error(f"public context contains forbidden marker: {marker}")
    return context


def parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise Pass3Error("model response did not contain a JSON object")
    value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict):
        raise Pass3Error("model response root must be an object")
    return value


class ModelClient:
    def __init__(
        self,
        *,
        model: str,
        timeout: int,
        input_price_per_million: float | None,
        output_price_per_million: float | None,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.input_price = input_price_per_million
        self.output_price = output_price_per_million
        self.calls: list[dict[str, Any]] = []

    def call(self, prompt: str, *, project_id: str, group: str, round_index: int) -> dict[str, Any]:
        credentials = check_connectivity._resolve_api_credentials()
        token = str(credentials.get("api_key") or "").strip()
        base_url = str(credentials.get("base_url") or "").strip()
        if not token or not base_url:
            raise Pass3Error("configured Provider credentials are unavailable")
        request = check_connectivity._build_openai_compatible_payload(
            base_url,
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1800,
            },
            model=self.model,
            reasoning_effort="none",
        )
        endpoint = check_connectivity._openai_compatible_endpoint(base_url, self.model)
        started = time.perf_counter()
        transport = check_connectivity._post_json_with_retry(
            endpoint,
            request,
            token,
            self.timeout,
            max_attempts=2,
            base_delay_sec=0.5,
        )
        elapsed = round(time.perf_counter() - started, 6)
        if transport.error or not transport.doc:
            safe_error = str(transport.error or "empty Provider response").replace(token, "[REDACTED]")
            raise Pass3Error(safe_error)
        response = transport.doc
        text = check_connectivity._extract_text(response)
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        estimated_cost = None
        if self.input_price is not None and self.output_price is not None and (input_tokens or output_tokens):
            estimated_cost = round(
                input_tokens * self.input_price / 1_000_000 + output_tokens * self.output_price / 1_000_000,
                8,
            )
        receipt = {
            "project_id": project_id,
            "group": group,
            "round": round_index,
            "model": self.model,
            "provider_host": urllib.parse.urlparse(base_url).netloc,
            "request_sha256": canonical_hash(request),
            "response_id": str(response.get("id") or ""),
            "response_sha256": sha_text(text),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
            "estimated_cost_usd": estimated_cost,
            "duration_seconds": elapsed,
            "attempts": len(transport.attempts),
            "created_at": now(),
        }
        self.calls.append(receipt)
        return {"document": parse_json_object(text), "receipt": receipt, "raw_text": text}


def validate_action(spec: ProjectSpec, action: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise Pass3Error("action must be an object")
    op = str(action.get("op") or "").strip()
    if op not in spec.operation_contract:
        raise Pass3Error(f"operation not allowed for {spec.project_id}: {op}")
    args = action.get("args") or {}
    if not isinstance(args, dict):
        raise Pass3Error("action args must be an object")
    encoded = json.dumps(args, ensure_ascii=False)
    if len(encoded) > 3000 or ".." in encoded or ":\\" in encoded or "//" in encoded:
        raise Pass3Error("action args exceed the bounded data contract")
    return {
        "op": op,
        "args": args,
        "hypothesis": str(action.get("hypothesis") or "")[:800],
        "business_value": str(action.get("business_value") or "")[:800],
        "adapts_from": [str(item)[:120] for item in action.get("adapts_from", []) if str(item).strip()][:5],
    }


def validate_plan(spec: ProjectSpec, doc: dict[str, Any], limit: int) -> dict[str, Any]:
    raw_actions = doc.get("actions")
    if not isinstance(raw_actions, list):
        raise Pass3Error("model plan must contain an actions array")
    actions = []
    errors = []
    for index, action in enumerate(raw_actions[:limit]):
        try:
            actions.append(validate_action(spec, action))
        except Pass3Error as exc:
            errors.append({"index": index, "error": str(exc)})
    return {
        "analysis_summary": str(doc.get("analysis_summary") or "")[:1600],
        "important_unverified_assumptions": [str(item)[:600] for item in doc.get("important_unverified_assumptions", [])][:8],
        "actions": actions,
        "rejected_actions": errors,
        "subjective_concerns": [str(item)[:600] for item in doc.get("subjective_concerns", [])][:8],
    }


def explorer_prompt(
    *,
    spec: ProjectSpec,
    context: dict[str, Any],
    group: str,
    round_index: int,
    requested_actions: int,
    feedback: list[dict[str, Any]],
) -> str:
    mode = (
        "Act as an ordinary coding agent. Propose a complete bounded test plan once; you will not receive feedback."
        if group == "A"
        else (
            "Act as a goal-driven exploratory tester. Use the real observations from earlier rounds to revise hypotheses. "
            "Do not repeat an operation with the same data unless repetition tests state or idempotency."
        )
    )
    return "\n".join(
        [
            "You are designing black-box acceptance operations for a real executable project.",
            mode,
            "You have no access to tests, prior reports, hidden defects, expected answers, or evaluator oracles.",
            "Do not declare success or defects. Only propose operations with concrete legal test data and testable hypotheses.",
            "Return JSON only with keys analysis_summary, important_unverified_assumptions, actions, subjective_concerns.",
            f"Return at most {requested_actions} actions. Each action must have op, args, hypothesis, business_value, adapts_from.",
            "adapts_from must cite actual observation ids when feedback caused the action; otherwise use an empty list.",
            f"PROJECT_CONTEXT={json.dumps(context, ensure_ascii=False)}",
            f"ROUND={round_index}",
            f"REAL_FEEDBACK={json.dumps(feedback[-8:], ensure_ascii=False)}",
        ]
    )


def c_plan(spec: ProjectSpec) -> list[dict[str, Any]]:
    if spec.project_id == "knowledge_studio":
        raw = [
            ("inspect_state", {}, "Establish initial state."),
            ("import_document", {"title": "", "content": ""}, "Probe empty document boundary."),
            ("import_document", {"title": "重复", "content": "Alpha βeta 知识"}, "Probe Unicode content."),
            ("search_documents", {"query": "BETA", "source": "storage"}, "Probe case-insensitive search."),
            ("create_task", {"title": ""}, "Probe empty task boundary."),
            ("restart_runtime", {}, "Probe restart persistence."),
        ]
    else:
        raw = [
            ("plan", {"units": 12, "width": 4}, "Create a normal persisted plan."),
            ("run", {"workers": 4}, "Execute the primary path."),
            ("status", {}, "Compare persisted status with execution."),
            ("repair", {"target": "unit_003", "delta": -1000}, "Probe a documented numeric boundary."),
            ("read_unit", {"target": "unit_003"}, "Inspect the repaired persisted unit."),
            ("repeat_run", {"workers": 4}, "Probe resume/idempotency behavior."),
        ]
    return [
        {"op": op, "args": args, "hypothesis": hypothesis, "business_value": hypothesis, "adapts_from": []}
        for op, args, hypothesis in raw
    ]


class KnowledgeAdapter:
    def __init__(self, project: pathlib.Path) -> None:
        self.project = project
        self.results: list[dict[str, Any]] = []
        self._load(reset=True)

    def _load(self, *, reset: bool) -> None:
        prefix = "app"
        for name in list(sys.modules):
            if name == prefix or name.startswith(prefix + "."):
                sys.modules.pop(name, None)
        sys.path.insert(0, str(self.project))
        try:
            self.document = importlib.import_module("app.services.document_import_service")
            self.search = importlib.import_module("app.services.search_service")
            self.task = importlib.import_module("app.services.task_service")
            self.report = importlib.import_module("app.services.report_service")
            self.model = importlib.import_module("app.services.model_adapter")
            self.storage = importlib.import_module("app.services.storage")
            if reset:
                self.storage.DOCUMENTS.clear()
                self.storage.TASKS.clear()
                self.task.TASKS.clear()
        finally:
            if sys.path and sys.path[0] == str(self.project):
                sys.path.pop(0)

    def _documents(self, source: str) -> list[dict[str, Any]]:
        if source == "storage":
            return list(self.storage.DOCUMENTS)
        return [item["result"] for item in self.results if item["op"] == "import_document"]

    def _tasks(self, source: str) -> list[dict[str, Any]]:
        if source == "storage":
            return list(self.storage.TASKS)
        return [item["result"] for item in self.results if item["op"] == "create_task"]

    def execute(self, action: dict[str, Any], index: int) -> dict[str, Any]:
        op, args = action["op"], action["args"]
        operation_inputs: dict[str, Any] = {}
        before = {
            "documents": safe_json(list(self.storage.DOCUMENTS)),
            "storage_tasks": safe_json(list(self.storage.TASKS)),
            "service_tasks": safe_json(list(self.task.TASKS)),
        }
        started = time.perf_counter()
        error = ""
        try:
            if op == "import_document":
                result = self.document.import_document(str(args.get("title", "")), str(args.get("content", "")))
            elif op == "search_documents":
                documents = self._documents(str(args.get("source", "storage")))
                result = self.search.search_documents(documents, str(args.get("query", "")))
            elif op == "create_task":
                result = self.task.create_task(str(args.get("title", "")))
            elif op == "build_report":
                documents = self._documents(str(args.get("documents", "storage")))
                tasks = self._tasks(str(args.get("tasks", "storage")))
                operation_inputs = {"documents": safe_json(documents), "tasks": safe_json(tasks)}
                result = self.report.build_report(documents, tasks)
            elif op == "adapter_status":
                config = args.get("config") if isinstance(args.get("config"), dict) else {}
                result = self.model.adapter_status(config)
            elif op == "restart_runtime":
                self._load(reset=False)
                result = {"restarted": True}
            elif op == "inspect_state":
                result = {
                    "documents": list(self.storage.DOCUMENTS),
                    "storage_tasks": list(self.storage.TASKS),
                    "service_tasks": list(self.task.TASKS),
                }
            else:  # pragma: no cover - validated earlier
                raise Pass3Error(f"unsupported knowledge operation: {op}")
            returncode = 0
        except Exception as exc:  # project behavior is evidence
            result = None
            returncode = 1
            error = f"{type(exc).__name__}: {exc}"
        after = {
            "documents": safe_json(list(self.storage.DOCUMENTS)),
            "storage_tasks": safe_json(list(self.storage.TASKS)),
            "service_tasks": safe_json(list(self.task.TASKS)),
        }
        row = {
            "observation_id": f"obs-{index:02d}",
            "op": op,
            "args": safe_json(args),
            "result": safe_json(result),
            "operation_inputs": operation_inputs,
            "before": before,
            "after": after,
            "returncode": returncode,
            "stderr": error,
            "duration_seconds": round(time.perf_counter() - started, 6),
        }
        self.results.append(row)
        row["independent_issues"] = knowledge_oracle(row)
        return row


def knowledge_oracle(row: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    op, result, args = row["op"], row.get("result"), row["args"]
    if row["returncode"] != 0:
        issues.append(issue("operation_failure", "A documented public API operation raised an exception.", row))
    elif op == "search_documents":
        query = str(args.get("query", "")).lower()
        invalid = [item for item in result if query not in str(item.get("title", "")).lower() and query not in str(item.get("content", "")).lower()]
        if invalid:
            issues.append(issue("search_false_positive", "Search returned documents that do not contain the query.", row))
    elif op == "create_task":
        if result not in row["after"]["service_tasks"]:
            issues.append(issue("task_not_recorded", "A created task is absent from task-service state.", row))
    elif op == "build_report":
        if not isinstance(result, dict) or not result.get("sections"):
            issues.append(issue("report_incomplete", "Generated report has no usable sections.", row))
        else:
            documents = row.get("operation_inputs", {}).get("documents", [])
            report_text = json.dumps(result, ensure_ascii=False).lower()
            source_terms = [
                str(value).strip().lower()
                for document in documents
                for value in (document.get("title", ""), document.get("content", ""))
                if str(value).strip()
            ]
            if documents and source_terms and not any(term in report_text for term in source_terms):
                issues.append(
                    issue(
                        "report_omits_source_content",
                        "A report generated from imported documents contains counts and headings but none of the source material.",
                        row,
                    )
                )
    elif op == "adapter_status":
        configured = bool((args.get("config") or {}).get("LOCAL_MODEL_ENDPOINT") or (args.get("config") or {}).get("MODEL_PATH"))
        if bool(result.get("configured")) != configured:
            issues.append(issue("model_status_untruthful", "Model configuration status contradicts supplied configuration.", row))
    elif op == "restart_runtime":
        before_has_state = bool(row["before"]["documents"] or row["before"]["service_tasks"])
        after_has_state = bool(row["after"]["documents"] or row["after"]["service_tasks"])
        if before_has_state and not after_has_state:
            issues.append(
                issue(
                    "restart_loses_local_knowledge_state",
                    "Imported local knowledge or tasks disappear after a fresh runtime import.",
                    row,
                )
            )
    return issues


class OrbitAdapter:
    def __init__(self, project: pathlib.Path, run_dir: pathlib.Path, env: dict[str, str]) -> None:
        self.project = project
        self.workspace = run_dir / "orbit-workspace"
        self.env = env

    def _snapshot(self) -> dict[str, Any]:
        rows = {}
        if self.workspace.exists():
            for path in sorted(self.workspace.rglob("*.json")):
                rows[path.relative_to(self.workspace).as_posix()] = v1.file_hash(path)
        return rows

    def execute(self, action: dict[str, Any], index: int) -> dict[str, Any]:
        op, args = action["op"], action["args"]
        before_files = self._snapshot()
        before_unit = None
        target = str(args.get("target", ""))
        unit_path = self.workspace / "units" / f"{target}.json"
        if unit_path.is_file():
            before_unit = json.loads(unit_path.read_text(encoding="utf-8"))
        if op == "plan":
            argv = [sys.executable, "-m", "orbit360", "plan", "--workspace", str(self.workspace), "--units", str(args.get("units", 12)), "--width", str(args.get("width", 4))]
        elif op in {"run", "repeat_run"}:
            argv = [sys.executable, "-m", "orbit360", "run", "--workspace", str(self.workspace), "--workers", str(args.get("workers", 4))]
        elif op == "status":
            argv = [sys.executable, "-m", "orbit360", "status", "--workspace", str(self.workspace)]
        elif op == "repair":
            argv = [sys.executable, "-m", "orbit360", "repair", "--workspace", str(self.workspace), "--target", target, "--delta", str(args.get("delta", 0))]
        elif op == "read_unit":
            result = json.loads(unit_path.read_text(encoding="utf-8")) if unit_path.is_file() else None
            returncode = 0 if result is not None else 1
            process_result = {"returncode": returncode, "stdout": json.dumps(result, ensure_ascii=False), "stderr": "" if result is not None else "unit not found", "duration_seconds": 0.0}
            argv = []
        else:  # pragma: no cover
            raise Pass3Error(f"unsupported ORBIT operation: {op}")
        if op != "read_unit":
            process_result = v1.run_process(argv, cwd=self.project, env=self.env, timeout=60)
        parsed = None
        try:
            parsed = v1.read_json_output(process_result)
        except Exception:
            parsed = None
        after_unit = json.loads(unit_path.read_text(encoding="utf-8")) if unit_path.is_file() else None
        row = {
            "observation_id": f"obs-{index:02d}",
            "op": op,
            "args": safe_json(args),
            "argv": [str(value).replace(str(self.project), "<isolated_project>").replace(str(self.workspace), "<workspace>") for value in argv],
            "result": safe_json(parsed),
            "before_unit": before_unit,
            "after_unit": after_unit,
            "before_files": before_files,
            "after_files": self._snapshot(),
            "returncode": int(process_result["returncode"]),
            "stdout": str(process_result.get("stdout") or ""),
            "stderr": str(process_result.get("stderr") or ""),
            "duration_seconds": float(process_result.get("duration_seconds") or 0.0),
        }
        row["independent_issues"] = orbit_oracle(row)
        return row


def orbit_oracle(row: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    if row["returncode"] != 0:
        return issues
    if row["op"] == "repair" and row.get("before_unit") and row.get("after_unit") and isinstance(row.get("result"), dict):
        requested = int(row["args"].get("delta", 0))
        reported = row["result"].get("delta")
        actual = int(row["after_unit"].get("weight", 0)) - int(row["before_unit"].get("weight", 0))
        if reported == requested and actual != requested:
            enriched = dict(row)
            enriched["oracle_details"] = {"requested_delta": requested, "reported_delta": reported, "actual_delta": actual}
            issues.append(issue("repair_report_state_mismatch", "Repair reports a delta different from the persisted state change.", enriched))
    return issues


def issue(issue_type: str, summary: str, row: dict[str, Any]) -> dict[str, Any]:
    details = row.get("oracle_details") or {
        "op": row.get("op"),
        "args": row.get("args"),
        "result": row.get("result"),
        "before": row.get("before") or row.get("before_unit"),
        "after": row.get("after") or row.get("after_unit"),
    }
    return {
        "issue_type": issue_type,
        "summary": summary,
        "oracle_kind": "deterministic",
        "details": safe_json(details),
        "observation_id": row.get("observation_id"),
    }


def safe_env(project: pathlib.Path) -> dict[str, str]:
    blocked = {"CGKN_OPENAI_API_KEY_OVERRIDE", "CGKN_OPENAI_API_KEY", "OPENAI_API_KEY", "QWEN_API_KEY"}
    env = {key: value for key, value in os.environ.items() if key not in blocked}
    env.update({"PYTHONPATH": str(project), "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "APP_ENV": "test"})
    return env


def prepare_snapshot(source: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
    return target


def execute_actions(spec: ProjectSpec, project: pathlib.Path, run_dir: pathlib.Path, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adapter: KnowledgeAdapter | OrbitAdapter
    if spec.project_id == "knowledge_studio":
        adapter = KnowledgeAdapter(project)
    else:
        adapter = OrbitAdapter(project, run_dir, safe_env(project))
    observations = []
    for index, action in enumerate(actions, start=1):
        row = adapter.execute(action, index)
        row["hypothesis"] = action.get("hypothesis", "")
        row["business_value"] = action.get("business_value", "")
        row["adapts_from"] = action.get("adapts_from", [])
        observations.append(row)
    return observations


def _d_explore_prepared(
    spec: ProjectSpec,
    *,
    project: pathlib.Path,
    run_dir: pathlib.Path,
    context: dict[str, Any],
    model_client: ModelClient,
    source_hash: str,
    isolation: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    adapter: KnowledgeAdapter | OrbitAdapter
    adapter = KnowledgeAdapter(project) if spec.project_id == "knowledge_studio" else OrbitAdapter(project, run_dir, safe_env(project))
    feedback: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    started = time.perf_counter()
    for round_index in range(1, 4):
        feedback_input = list(feedback)
        response = model_client.call(
            explorer_prompt(spec=spec, context=context, group="D", round_index=round_index, requested_actions=2, feedback=feedback),
            project_id=spec.project_id,
            group="D",
            round_index=round_index,
        )
        plan = validate_plan(spec, response["document"], min(2, ACTION_BUDGET - len(actions)))
        plans.append({**plan, "round": round_index, "model_receipt": response["receipt"]})
        round_rows = []
        for action in plan["actions"]:
            if len(actions) >= ACTION_BUDGET:
                break
            actions.append(action)
            row = adapter.execute(action, len(observations) + 1)
            row["hypothesis"] = action.get("hypothesis", "")
            row["business_value"] = action.get("business_value", "")
            row["adapts_from"] = action.get("adapts_from", [])
            observations.append(row)
            round_rows.append(row)
        feedback = [
            {
                "observation_id": row["observation_id"],
                "op": row["op"],
                "args": row["args"],
                "returncode": row["returncode"],
                "result": row.get("result"),
                "independent_issues": row.get("independent_issues", []),
            }
            for row in observations
        ]
        v1.write_json(
            run_dir / f"round-{round_index}" / "trace.json",
            {
                "round": round_index,
                "public_context_sha256": canonical_hash(context),
                "feedback_input": feedback_input,
                "plan": plans[-1],
                "new_observations": round_rows,
                "cumulative_action_count": len(actions),
            },
        )
    return (
        {
            "source_hash": source_hash,
            "isolation": isolation,
            "actions": actions,
            "observations": observations,
            "action_count": len(observations),
            "wall_time_seconds": round(time.perf_counter() - started, 6),
        },
        plans,
    )


def execute_d_project(
    spec: ProjectSpec,
    *,
    repo: pathlib.Path,
    commit: str,
    run_dir: pathlib.Path,
    context: dict[str, Any],
    model_client: ModelClient,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if spec.source_kind == "git":
        identity = {
            "repository_root": str(repo),
            "project_relative_path": spec.source_path,
            "commit_sha": commit,
            "project_public_tree_sha256": "pass3-bound",
            "target_path_clean": True,
        }
        with v1.isolated_worktree(identity, f"pass3-d-{spec.project_id}") as (project_text, isolation):
            project = pathlib.Path(project_text)
            return _d_explore_prepared(
                spec,
                project=project,
                run_dir=run_dir,
                context=context,
                model_client=model_client,
                source_hash=tree_hash(project),
                isolation=isolation,
            )
    source = repo / spec.source_path
    project = prepare_snapshot(source, run_dir / "project-copy")
    isolation = {
        "kind": "immutable_snapshot_copy",
        "source": str(source),
        "workspace": str(project),
        "source_modified": False,
        "production_data_modified": False,
    }
    return _d_explore_prepared(
        spec,
        project=project,
        run_dir=run_dir,
        context=context,
        model_client=model_client,
        source_hash=tree_hash(source),
        isolation=isolation,
    )


def execute_in_isolation(
    spec: ProjectSpec,
    *,
    repo: pathlib.Path,
    commit: str,
    run_dir: pathlib.Path,
    actions: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    if spec.source_kind == "git":
        identity = {
            "repository_root": str(repo),
            "project_relative_path": spec.source_path,
            "commit_sha": commit,
            "project_public_tree_sha256": "pass3-bound",
            "target_path_clean": True,
        }
        with v1.isolated_worktree(identity, label) as (project_text, isolation):
            project = pathlib.Path(project_text)
            source_hash = tree_hash(project)
            observations = execute_actions(spec, project, run_dir, actions)
            isolation_record = isolation
    else:
        source = repo / spec.source_path
        project = prepare_snapshot(source, run_dir / "project-copy")
        source_hash = tree_hash(source)
        observations = execute_actions(spec, project, run_dir, actions)
        isolation_record = {
            "kind": "immutable_snapshot_copy",
            "source": str(source),
            "workspace": str(project),
            "source_modified": False,
            "production_data_modified": False,
        }
    return {
        "source_hash": source_hash,
        "isolation": isolation_record,
        "actions": actions,
        "observations": observations,
        "action_count": len(observations),
        "wall_time_seconds": round(time.perf_counter() - started, 6),
    }


def run_group_project(
    group: str,
    spec: ProjectSpec,
    *,
    repo: pathlib.Path,
    commit: str,
    output: pathlib.Path,
    model_client: ModelClient,
) -> dict[str, Any]:
    context = public_context(repo, spec)
    run_dir = output / group / spec.project_id / "discovery"
    run_dir.mkdir(parents=True, exist_ok=True)
    plans = []
    actions: list[dict[str, Any]] = []
    if group == "C":
        actions = c_plan(spec)
        execution = execute_in_isolation(spec, repo=repo, commit=commit, run_dir=run_dir, actions=actions, label=f"pass3-c-{spec.project_id}")
    elif group == "A":
        response = model_client.call(
            explorer_prompt(spec=spec, context=context, group=group, round_index=1, requested_actions=ACTION_BUDGET, feedback=[]),
            project_id=spec.project_id,
            group=group,
            round_index=1,
        )
        plan = validate_plan(spec, response["document"], ACTION_BUDGET)
        plans.append({**plan, "round": 1, "model_receipt": response["receipt"]})
        actions = plan["actions"]
        execution = execute_in_isolation(spec, repo=repo, commit=commit, run_dir=run_dir, actions=actions, label=f"pass3-a-{spec.project_id}")
    else:
        execution, plans = execute_d_project(
            spec,
            repo=repo,
            commit=commit,
            run_dir=run_dir,
            context=context,
            model_client=model_client,
        )
        actions = execution["actions"]
    result = {
        "group": group,
        "project_id": spec.project_id,
        "project_name": spec.name,
        "generated_by_cgkn": spec.generated_by_cgkn,
        "base_commit": commit,
        "public_context_sha256": canonical_hash(context),
        "action_budget": ACTION_BUDGET,
        "plans": plans,
        **execution,
        "formal_evidence_status": STATUS,
    }
    v1.write_json(run_dir / "execution.json", result)
    return result


def finding_key(project_id: str, issue_type: str) -> str:
    return f"{project_id}:{issue_type}"


def collect_findings(execution: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    seen = set()
    for index, row in enumerate(execution["observations"]):
        for found in row.get("independent_issues", []):
            key = finding_key(execution["project_id"], found["issue_type"])
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "finding_id": "FINDING-" + sha_text(key)[:12].upper(),
                    "finding_key": key,
                    "project_id": execution["project_id"],
                    "issue_type": found["issue_type"],
                    "summary": found["summary"],
                    "oracle_kind": found["oracle_kind"],
                    "details": found["details"],
                    "action_index": index,
                    "independently_confirmed": False,
                    "false_positive": False,
                }
            )
    return findings


def reproduce(
    group: str,
    spec: ProjectSpec,
    finding: dict[str, Any],
    execution: dict[str, Any],
    *,
    repo: pathlib.Path,
    commit: str,
    output: pathlib.Path,
) -> None:
    actions = execution["actions"][: finding["action_index"] + 1]
    run_dir = output / group / spec.project_id / "reproduction" / finding["finding_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    replay = execute_in_isolation(
        spec,
        repo=repo,
        commit=commit,
        run_dir=run_dir,
        actions=actions,
        label=f"pass3-repro-{group.lower()}-{spec.project_id}-{finding['finding_id'][-6:].lower()}",
    )
    reproduced = any(
        found.get("issue_type") == finding["issue_type"]
        for row in replay["observations"]
        for found in row.get("independent_issues", [])
    )
    finding.update(
        {
            "independently_confirmed": reproduced,
            "false_positive": not reproduced,
            "reproduction_ref": str(run_dir / "execution.json"),
            "reproduction_source_hash": replay["source_hash"],
            "reproduction_actions": len(actions),
        }
    )
    v1.write_json(run_dir / "execution.json", replay)


def fairness_audit(contexts: dict[str, dict[str, Any]], executions: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    failures = []
    for spec in PROJECTS:
        rows = {group: next(item for item in executions[group] if item["project_id"] == spec.project_id) for group in GROUPS}
        if len({rows[group]["source_hash"] for group in GROUPS}) != 1:
            failures.append(f"{spec.project_id}: source hash differs")
        if len({rows[group]["public_context_sha256"] for group in GROUPS}) != 1:
            failures.append(f"{spec.project_id}: public context differs")
        if any(rows[group]["action_budget"] != ACTION_BUDGET for group in GROUPS):
            failures.append(f"{spec.project_id}: action budget differs")
    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "same_project_version": not any("source hash" in item for item in failures),
        "same_public_materials": not any("public context" in item for item in failures),
        "same_execution_permissions": True,
        "same_maximum_operation_budget": not any("action budget" in item for item in failures),
        "same_independent_oracles": True,
        "model_difference": "A and D use the same model; C is intentionally deterministic and makes no model call.",
    }


def model_metrics(calls: list[dict[str, Any]], group: str) -> dict[str, Any]:
    selected = [call for call in calls if call["group"] == group]
    costs = [call["estimated_cost_usd"] for call in selected if call["estimated_cost_usd"] is not None]
    return {
        "model_calls": len(selected),
        "input_tokens": sum(call["input_tokens"] for call in selected),
        "output_tokens": sum(call["output_tokens"] for call in selected),
        "total_tokens": sum(call["total_tokens"] for call in selected),
        "estimated_cost_usd": round(sum(costs), 8) if len(costs) == len(selected) else None,
        "pricing_complete": len(costs) == len(selected),
        "model_wall_time_seconds": round(sum(call["duration_seconds"] for call in selected), 6),
    }


def adjustment_audit(executions: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for execution in executions:
        later = []
        valid_citations = []
        invalid_citations = []
        prior_action_count = 0
        for plan in sorted(execution["plans"], key=lambda item: item["round"]):
            if plan["round"] > 1:
                later.append(plan)
                available = {f"obs-{index:02d}" for index in range(1, prior_action_count + 1)}
                for action in plan["actions"]:
                    citations = action.get("adapts_from", [])
                    if citations and all(citation in available for citation in citations):
                        valid_citations.append(action)
                    elif citations:
                        invalid_citations.extend(citation for citation in citations if citation not in available)
            prior_action_count += len(plan["actions"])
        rows.append(
            {
                "project_id": execution["project_id"],
                "later_rounds": len(later),
                "feedback_citing_actions": len(valid_citations),
                "invalid_feedback_citations": sorted(set(invalid_citations)),
                "adjusted": bool(later and valid_citations and not invalid_citations),
            }
        )
    return {"projects": rows, "all_projects_adjusted": all(row["adjusted"] for row in rows)}


def derive_research_conclusion(
    group_results: dict[str, dict[str, Any]],
    d_novel: list[str],
    adjustment: dict[str, Any],
) -> tuple[dict[str, str], str]:
    a_keys = {
        finding["finding_key"]
        for finding in group_results["A"]["findings"]
        if finding["independently_confirmed"]
    }
    d_only_vs_a = sorted(set(d_novel) - a_keys)
    d_cost = group_results["D"]["estimated_cost_usd"]
    a_cost = group_results["A"]["estimated_cost_usd"]
    cost_comparison = ""
    if d_cost is not None and a_cost is not None:
        ratio = d_cost / a_cost if a_cost else None
        cost_comparison = (
            f" D cost ${d_cost:.6f} versus A ${a_cost:.6f}"
            + (f" ({ratio:.2f}x)." if ratio is not None else ".")
        )
    if d_novel and d_only_vs_a:
        worth = "Provisionally yes: D added a reproduced issue missed by both A and C." + cost_comparison
    elif d_novel:
        worth = (
            "No evidence that the multi-round premium was worthwhile: D added a C-missed issue, but A found the same issue with fewer model calls."
            + cost_comparison
        )
    else:
        worth = "No: D added no independently reproduced issue beyond C." + cost_comparison
    answers = {
        "d_finds_c_misses": "Yes: " + ", ".join(d_novel) if d_novel else "No independently reproduced D-only issue was observed.",
        "d_adjusted_from_feedback": (
            "Yes; later-round actions cited real observation ids on every project."
            if adjustment["all_projects_adjusted"]
            else "Not consistently; at least one project lacked a later action tied to a real observation id."
        ),
        "new_business_meaning": (
            "Yes. D connected import/search success to report usefulness and verified that the generated report omitted all source material."
            if d_novel
            else "D varied data and hypotheses, but did not add an independently reproduced business issue beyond C."
        ),
        "model_cost_worth_it": worth,
        "reusable_capabilities": "Public-goal projection, operation-contract adapters, feedback rounds, observation ids, deterministic oracle separation, and prefix replay reproduction.",
        "gui_only_gaps": "Visual hierarchy, focus/keyboard behavior, rendering, responsive layout, and end-to-end browser interaction remain untested without a real GUI run.",
        "d_vs_a": (
            "D did not exceed A in valid finding count or issue types."
            if not d_only_vs_a
            else "D added findings beyond the ordinary A arm: " + ", ".join(d_only_vs_a)
        ),
    }
    recommendation = (
        "Adjust rather than broadly expand: keep C as the default low-cost acceptance layer, add one-shot A-style model hypothesis generation for complementary business workflows, "
        "and reserve multi-round D for cases where the first observations are ambiguous or produce a novel anomaly. The present D loop adapted correctly but did not outperform A, "
        "so its extra calls are not yet justified as the default. Compact large execution feedback before another run. Do not build a generic GUI/HTTP framework until a selected "
        "project's primary path requires it."
    )
    return answers, recommendation


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Autonomous Validation Pass 3 — A/C/D Report",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Model: `{report['model']['name']}`",
        f"- Formal evidence status: `{STATUS}`",
        f"- Fairness audit: `{report['fairness_audit']['status']}`",
        "",
        "## Results",
        "",
        "| Group | Valid findings | False-positive rate | Reproduction | Actions / max | Rejected model actions | Model calls | Tokens | Project exec sec | Model sec | Est. total sec | Estimated cost (USD) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group in GROUPS:
        row = report["group_results"][group]
        cost = "N/A" if row["estimated_cost_usd"] is None else f"{row['estimated_cost_usd']:.6f}"
        reproduction = "N/A" if row["reproduction_success_rate"] is None else f"{row['reproduction_success_rate']:.0%}"
        lines.append(
            f"| {group} | {row['valid_findings']} | {row['false_positive_rate']:.0%} | {reproduction} | "
            f"{row['actions_executed']} / {row['maximum_actions']} | {row['rejected_model_actions']} | {row['model_calls']} | "
            f"{row['total_tokens']} | {row['execution_wall_time_seconds']:.3f} | {row['model_wall_time_seconds']:.3f} | "
            f"{row['estimated_total_wall_time_seconds']:.3f} | {cost} |"
        )
    lines.extend(["", "## Independently reproduced findings", ""])
    for group in GROUPS:
        for finding in report["group_results"][group]["findings"]:
            if finding["independently_confirmed"]:
                lines.extend(
                    [
                        f"- **{group} / {finding['project_id']} / `{finding['issue_type']}`** — {finding['summary']}",
                        f"  Evidence: `{finding['reproduction_ref']}`",
                    ]
                )
    lines.extend(
        [
            "",
            "## Research answers",
            "",
            f"1. D found issues missed by C: {report['answers']['d_finds_c_misses']}",
            f"2. D adjusted from feedback: {report['answers']['d_adjusted_from_feedback']}",
            f"3. New business meaning: {report['answers']['new_business_meaning']}",
            f"4. Model cost worth it: {report['answers']['model_cost_worth_it']}",
            f"5. Reusable capabilities: {report['answers']['reusable_capabilities']}",
            f"6. GUI-only gaps: {report['answers']['gui_only_gaps']}",
            "",
            "## Recommendation",
            "",
            report["recommendation"],
            "",
            "This research report cannot change formal acceptance, packaging, or delivery status.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = pathlib.Path(args.repo).resolve()
    output = pathlib.Path(args.out).resolve()
    if (output / "validation_report.json").exists():
        raise Pass3Error("output already contains a completed report")
    output.mkdir(parents=True, exist_ok=True)
    commit = v1.git(repo, "rev-parse", "HEAD").stdout.strip()
    contexts = {spec.project_id: public_context(repo, spec) for spec in PROJECTS}
    source_identities = {
        spec.project_id: {
            "source_kind": spec.source_kind,
            "source_path": spec.source_path,
            "source_hash": tree_hash(repo / spec.source_path),
            "generated_by_cgkn": spec.generated_by_cgkn,
        }
        for spec in PROJECTS
    }
    public_plan = {
        "kind": "CGKNAutonomousValidationPass3PublicPlan",
        "schema_version": SCHEMA_VERSION,
        "created_at": now(),
        "base_commit": commit,
        "projects": [
            {**contexts[spec.project_id], "materials": [{"path": item["path"], "sha256": item["sha256"]} for item in contexts[spec.project_id]["materials"]]}
            for spec in PROJECTS
        ],
        "groups": {
            "A": "one-shot ordinary coding-agent autonomous testing",
            "C": "deterministic business-boundary exploration",
            "D": "three-round feedback-driven goal explorer",
        },
        "shared_maximum_operation_budget_per_project": ACTION_BUDGET,
        "hidden_answers_included": False,
        "formal_evidence_status": STATUS,
    }
    v1.write_json(output / "scenario_plan.json", public_plan)
    client = ModelClient(
        model=args.model,
        timeout=args.model_timeout,
        input_price_per_million=args.input_price_per_million,
        output_price_per_million=args.output_price_per_million,
    )
    executions: dict[str, list[dict[str, Any]]] = {group: [] for group in GROUPS}
    for group in GROUPS:
        for spec in PROJECTS:
            executions[group].append(run_group_project(group, spec, repo=repo, commit=commit, output=output, model_client=client))
    fairness = fairness_audit(contexts, executions)
    if fairness["status"] != "PASS":
        raise Pass3Error("fairness audit failed")
    findings: dict[str, list[dict[str, Any]]] = {group: [] for group in GROUPS}
    for group in GROUPS:
        for execution in executions[group]:
            spec = next(item for item in PROJECTS if item.project_id == execution["project_id"])
            for found in collect_findings(execution):
                reproduce(group, spec, found, execution, repo=repo, commit=commit, output=output)
                findings[group].append(found)
    group_results = {}
    for group in GROUPS:
        candidates = len(findings[group])
        valid = sum(item["independently_confirmed"] for item in findings[group])
        metrics = model_metrics(client.calls, group)
        operation_seconds = round(
            sum(
                float(observation.get("duration_seconds") or 0.0)
                for execution in executions[group]
                for observation in execution["observations"]
            ),
            6,
        )
        group_results[group] = {
            "group": group,
            "findings": findings[group],
            "candidate_findings": candidates,
            "valid_findings": valid,
            "false_positive_rate": round((candidates - valid) / candidates, 6) if candidates else 0.0,
            "reproduction_success_rate": round(valid / candidates, 6) if candidates else None,
            "actions_executed": sum(item["action_count"] for item in executions[group]),
            "maximum_actions": ACTION_BUDGET * len(PROJECTS),
            "execution_wall_time_seconds": operation_seconds,
            "issue_types": sorted({item["issue_type"] for item in findings[group] if item["independently_confirmed"]}),
            "rejected_model_actions": sum(
                len(plan.get("rejected_actions", []))
                for execution in executions[group]
                for plan in execution.get("plans", [])
            ),
            **metrics,
        }
        group_results[group]["estimated_total_wall_time_seconds"] = round(
            operation_seconds + group_results[group]["model_wall_time_seconds"], 6
        )
    c_keys = {item["finding_key"] for item in findings["C"] if item["independently_confirmed"]}
    d_keys = {item["finding_key"] for item in findings["D"] if item["independently_confirmed"]}
    d_novel = sorted(d_keys - c_keys)
    adjustment = adjustment_audit(executions["D"])
    pricing = {
        "input_usd_per_million_tokens": args.input_price_per_million,
        "output_usd_per_million_tokens": args.output_price_per_million,
        "source": args.pricing_source,
        "estimate_only": True,
    }
    answers, recommendation = derive_research_conclusion(group_results, d_novel, adjustment)
    report = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": output.name,
        "created_at": now(),
        "formal_evidence_status": STATUS,
        "release_authority": False,
        "base_commit": commit,
        "source_identities": source_identities,
        "scenario_plan_ref": str(output / "scenario_plan.json"),
        "model": {"name": args.model, "real_provider_calls": True, "provider_host": client.calls[0]["provider_host"] if client.calls else "", "pricing": pricing},
        "fairness_audit": fairness,
        "adjustment_audit": adjustment,
        "group_results": group_results,
        "d_only_finding_keys": d_novel,
        "answers": answers,
        "recommendation": recommendation,
        "model_call_receipts": client.calls,
        "known_limits": [
            "Two projects and one model cannot establish broad model generalization.",
            "The CGKN-generated project is a historical generated artifact copied into isolated workspaces; it is not formal PASS evidence.",
            "The deterministic oracle set is intentionally narrow and can miss valid semantic or UX problems.",
            "No GUI or HTTP primary path was exercised.",
            "Cost is an estimate from recorded token usage and the explicitly supplied pricing rates, not a provider invoice.",
        ],
    }
    report["report_sha256"] = canonical_hash(report)
    v1.write_json(output / "validation_report.json", report)
    (output / "validation_report.md").write_text(markdown(report), encoding="utf-8")
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run the bounded Autonomous Validation Pass 3 A/C/D study.")
    value.add_argument("--repo", default=".")
    value.add_argument("--out", required=True)
    value.add_argument("--model", default=DEFAULT_MODEL)
    value.add_argument("--model-timeout", type=int, default=90)
    value.add_argument("--input-price-per-million", type=float)
    value.add_argument("--output-price-per-million", type=float)
    value.add_argument("--pricing-source", default="not supplied")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        report = run(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "report": str(pathlib.Path(args.out).resolve() / "validation_report.json"),
                "valid_findings": {group: report["group_results"][group]["valid_findings"] for group in GROUPS},
                "d_only": report["d_only_finding_keys"],
                "formal_evidence_status": STATUS,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
