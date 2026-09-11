from __future__ import annotations

import ast
import json
import pathlib
import sys
import threading
import time
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import formal_model_contract
import post_build_repair
import run_local_pipeline_impl


def test_post_build_audits_frozen_direct_cli_leaf_after_tests_pass(
    tmp_path: pathlib.Path,
) -> None:
    component_pipeline = {
        "components": [
            {
                "id": "backend",
                "contract_slice": {
                    "architecture_mode": "direct_cli_application"
                },
                "canonical_goal_spec": {
                    "domain": "local_record_cli",
                    "package_name": "projectpulse",
                    "entities": ["Task", "TaskRepository", "TaskService"],
                    "capabilities": [
                        "add_task",
                        "list_tasks",
                        "complete_task",
                        "delete_task",
                        "summary_tasks",
                        "export_tasks",
                        "import_tasks",
                    ],
                },
            }
        ]
    }
    cli_path = tmp_path / "projectpulse" / "cli.py"
    cli_path.parent.mkdir(parents=True)
    invalid_cli = """\
import argparse
import json
import sys

def build_parser():
    return argparse.ArgumentParser()

def main(argv=None):
    service = object()
    service.add('title').to_dict()
    service.list('all')
    service.complete('id').to_dict()
    service.delete('id').to_dict()
    service.summary()
    service.export_to('out.json')
    service.import_from('in.json', 'merge')
    print({'ok': True})
    if argv:
        return 0
    return 2
"""
    cli_path.write_text(invalid_cli, encoding="utf-8")

    issues = run_local_pipeline_impl.candidate_direct_cli_leaf_contract_issues(
        tmp_path,
        component_pipeline,
    )
    assert issues == [
        {
            "kind": "candidate_direct_cli_leaf_contract",
            "component_id": "backend",
            "path": "projectpulse/cli.py",
            "message": "projectpulse/cli.py: named direct CLI success output must use json.dumps for every command",
        }
    ]

    finalize = {
        "test_result": {"status": "pass", "argv": ["python", "-m", "pytest", "-q"]},
        "fixture_result": {"status": "pass"},
        "candidate_contract_issues": issues,
    }
    plan = post_build_repair.compile_post_build_repair_plan(tmp_path, finalize)

    assert "candidate_contract_failure" in plan["failure_types"]
    assert plan["target_files"][0] == "projectpulse/cli.py"
    assert plan["provider_actions"][0]["path"] == "projectpulse/cli.py"

    fixture_path = tmp_path / "demo" / "run_fixture.py"
    fixture_path.parent.mkdir(parents=True)
    fixture_path.write_text("raise RuntimeError('fixture failed')\n", encoding="utf-8")
    combined = {
        **finalize,
        "test_result": {
            "status": "failed",
            "stderr_tail": "tests/test_projectpulse_part_02.py failed",
        },
        "fixture_result": {
            "status": "failed",
            "error": "fixture workflow failed in demo/run_fixture.py",
        },
    }
    combined_plan = post_build_repair.compile_post_build_repair_plan(
        tmp_path,
        combined,
    )
    assert combined_plan["target_files"][0] == "projectpulse/cli.py"


def test_split_direct_cli_atomic_repair_keeps_three_owners_and_three_tests(
    tmp_path: pathlib.Path,
) -> None:
    owners = {
        "projectpulse/model.py": "class Task:\n    pass\n",
        "projectpulse/repository.py": "class JSONRepository:\n    pass\n",
        "projectpulse/service.py": "class TaskService:\n    pass\n",
    }
    tests = {
        "tests/test_projectpulse_part_01.py": "from projectpulse.model import Task\ndef test_one(): assert Task\n",
        "tests/test_projectpulse_part_02.py": "from projectpulse.repository import JSONRepository\ndef test_two(): assert JSONRepository\n",
        "tests/test_projectpulse_part_03.py": "from projectpulse.service import TaskService\ndef test_three(): assert TaskService\n",
    }
    for rel, content in {**owners, **tests}.items():
        path = tmp_path / pathlib.PurePosixPath(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    diagnostics = "\n".join(
        f"FAILED {rel}::test_failure" for rel in tests
    )
    plan = post_build_repair.compile_post_build_repair_plan(
        tmp_path,
        {
            "test_result": {
                "status": "failed",
                "stderr_tail": diagnostics,
            },
            "fixture_result": {"status": "pass"},
            "screenshot_blocked": "browser unavailable",
        },
    )

    assert plan["atomic_repair_required"] is True
    assert plan["atomic_repair_target_limit"] == 6
    assert set(owners).issubset(plan["target_files"])
    assert set(tests).issubset(plan["target_files"])
    assert len(plan["provider_actions"]) == 6


def test_semantic_review_stages_use_local_qa_task() -> None:
    for stage in ("semantic_component_review", "semantic_cross_component_review", "semantic_final_reducer"):
        assert run_local_pipeline_impl.local_model_task_for_provider_stage(stage) == "qa"


def test_leaf_semantic_repair_uses_code_model_task_without_new_generation_route() -> None:
    normal_prompt = '{"target_file":"src/app.js"}'
    repair_prompt = '{"target_file":"src/app.js","repair_acceptance":{"must_fix":"depth"}}'

    assert run_local_pipeline_impl.local_model_task_for_provider_request(
        "component_file_generation",
        normal_prompt,
    ) == "component_generation"
    assert run_local_pipeline_impl.local_model_task_for_provider_request(
        "component_file_generation",
        repair_prompt,
    ) == "component_reasoning_repair"
    assert "component_reasoning_repair" in run_local_pipeline_impl.local_model_router.LOCAL_GENERATION_TASKS
    assert "component_reasoning_repair" in run_local_pipeline_impl.local_model_router.LOCAL_CODE_TASKS


def test_local_manifest_can_omit_redundant_component_but_not_mismatch() -> None:
    doc = {"files": [{"path": "requirements.txt", "purpose": "dependencies"}]}
    assert run_local_pipeline_impl.local_provider_contract_error(
        doc,
        stage="component_file_manifest",
        component="foundation",
        target_file="",
    ) == ""
    assert "mismatch" in run_local_pipeline_impl.local_provider_contract_error(
        {"component": "frontend", "files": doc["files"]},
        stage="component_file_manifest",
        component="foundation",
        target_file="",
    )


def test_local_manifest_requires_component_minimum_paths() -> None:
    error = run_local_pipeline_impl.local_provider_contract_error(
        {"files": [{"path": "src/app.js", "purpose": "application logic"}]},
        stage="component_file_manifest",
        component="frontend",
        target_file="",
    )

    assert "index.html" in error
    assert "src/styles.css" in error
    assert run_local_pipeline_impl.component_path_allowed("data", "data/schema.json")
    assert not run_local_pipeline_impl.component_path_allowed("backend", "data/schema.json")
    assert "exactly main.py" in run_local_pipeline_impl.local_provider_contract_error(
        {"files": [{"path": "main.py"}, {"path": "api/tasks.py"}]},
        stage="component_file_manifest",
        component="backend",
        target_file="",
        prompt_text="Use browser localStorage as the sole task persistence layer.",
    )
    dynamic_prompt = json.dumps(
        {
            "required_paths": [
                "scripts/capture_workflow.py",
                "demo/run_fixture.py",
                "demo/fixture_manifest.json",
            ]
        }
    )
    dynamic_error = run_local_pipeline_impl.local_provider_contract_error(
        {
            "component": "media",
            "files": [{"path": "scripts/capture_workflow.py"}],
        },
        stage="component_file_manifest",
        component="media",
        target_file="",
        prompt_text=dynamic_prompt,
    )
    assert "demo/run_fixture.py" in dynamic_error
    assert "demo/fixture_manifest.json" in dynamic_error


def test_manifest_contract_failures_are_retryable() -> None:
    assert run_local_pipeline_impl.provider_component_error_is_retryable(
        "PROVIDER_RESPONSE_INVALID",
        "provider manifest missing required paths for component frontend: index.html",
    )


def test_placeholder_wording_is_repairable_without_weakening_validation() -> None:
    assert run_local_pipeline_impl.provider_component_error_is_retryable(
        "PROVIDER_UNKNOWN_ERROR",
        "split file contains placeholder wording: backend/image_adapters.py",
    )


@pytest.mark.parametrize(
    "message",
    [
        "executable media contract mismatch: capture workflow missing .save(",
        "uniform stage callable contract mismatch: stage must accept exactly one state parameter",
        "stage callable execution contract mismatch: orchestrator calls stage.execute(state)",
        "stage artifact schema contract mismatch: missing exact record fields",
        "media runtime dependency contract mismatch: requirements.txt does not declare Pillow",
    ],
)
def test_deterministic_leaf_contract_failures_are_repairable(message: str) -> None:
    assert run_local_pipeline_impl.provider_component_error_is_retryable(
        "PROVIDER_UNKNOWN_ERROR",
        message,
    )


def test_invented_local_module_import_is_semantically_retryable() -> None:
    assert run_local_pipeline_impl.provider_component_error_is_retryable(
        "PROVIDER_UNKNOWN_ERROR",
        "frontend module contract mismatch: JavaScript imports missing local modules: ./backend/shared-core",
    )
    assert run_local_pipeline_impl.provider_component_error_is_retryable(
        "PROVIDER_UNKNOWN_ERROR",
        "frontend module self-import contract mismatch: src/app.js imports itself via ./app",
    )


def test_content_repair_escalates_model_route_after_first_attempt() -> None:
    policy = run_local_pipeline_impl.ProviderModelRoutingPolicy(
        enable_model_routing=True,
        small_model="small-model",
        large_model="large-model",
    )

    route = run_local_pipeline_impl.choose_provider_model(
        "component_file_generation",
        100,
        "requested-model",
        policy,
        last_error="implementation depth contract mismatch: 6 < 10",
        attempt_number=2,
    )

    assert route["selected_model"] == "large-model"
    assert route["model_routing_reason"] == "semantic_repair_escalation"


def test_frontend_dom_contract_rejects_missing_controls_and_accepts_dynamic_markup() -> None:
    broken = [
        {"path": "index.html", "content": '<main id="app"></main><script src="src/app.js"></script>'},
        {
            "path": "src/app.js",
            "content": "document.getElementById('add-task-btn').addEventListener('click', addTask);",
        },
    ]
    assert "add-task-btn" in run_local_pipeline_impl.validate_frontend_dom_contract(broken)
    assert run_local_pipeline_impl.provider_component_error_is_retryable(
        "PROVIDER_RESPONSE_INVALID",
        run_local_pipeline_impl.validate_frontend_dom_contract(broken),
    )

    dynamic = [
        broken[0],
        {
            "path": "src/app.js",
            "content": (
                "document.getElementById('app').innerHTML = '<button id=\"add-task-btn\">Add</button>';\n"
                "document.getElementById('add-task-btn').addEventListener('click', addTask);"
            ),
        },
    ]
    assert run_local_pipeline_impl.validate_frontend_dom_contract(dynamic) == ""


def test_frontend_dom_contract_rejects_missing_literal_class_controls() -> None:
    files = [
        {"path": "index.html", "content": '<main id="app"><ul id="task-list"></ul></main>'},
        {
            "path": "src/app.js",
            "content": "document.querySelectorAll('.filter').forEach((button) => button.addEventListener('click', applyFilter));",
        },
    ]

    error = run_local_pipeline_impl.validate_frontend_dom_contract(files)
    assert "missing element classes" in error
    assert ".filter" in error


def test_frontend_dom_contract_rejects_eager_head_script_and_accepts_defer() -> None:
    javascript = "document.getElementById('task-list').textContent = 'ready';"
    eager = [
        {
            "path": "index.html",
            "content": '<html><head><script src="src/app.js"></script></head><body><div id="task-list"></div></body></html>',
        },
        {"path": "src/app.js", "content": javascript},
    ]
    assert "executes in <head>" in run_local_pipeline_impl.validate_frontend_dom_contract(eager)
    eager[0]["content"] = eager[0]["content"].replace("src/app.js\"", "src/app.js\" defer")
    assert run_local_pipeline_impl.validate_frontend_dom_contract(eager) == ""


def test_task_board_interaction_contract_rejects_unreachable_delete_and_accepts_wired_actions() -> None:
    html = """
    <main data-testid="task-board"><input id="new-task"><button id="add-task">Add</button>
      <button class="filter" data-mode="all">All</button>
      <button class="filter" data-mode="in-progress">In progress</button>
      <button class="filter" data-mode="completed">Completed</button>
      <ul id="task-list"></ul>
    </main>
    """
    unreachable = [
        {"path": "index.html", "content": html},
        {
            "path": "src/app.js",
            "content": """
            const tasks = JSON.parse(localStorage.getItem('tasks')) || [];
            function addTask() {} addTaskButton.onclick = addTask;
            function toggleTask() {} taskList.onclick = toggleTask;
            function deleteAllTasks() { tasks.splice(0); }
            function filterTasks() {} filters.forEach((button) => button.onclick = filterTasks);
            """,
        },
    ]
    error = run_local_pipeline_impl.validate_task_board_interaction_contract(unreachable)
    assert "delete action" in error

    wired = [
        unreachable[0],
        {
            "path": "src/app.js",
            "content": unreachable[1]["content"] + "\ndeleteButton.onclick = deleteAllTasks;",
        },
    ]
    assert run_local_pipeline_impl.validate_task_board_interaction_contract(wired) == ""


def test_task_board_interaction_contract_rejects_filtered_collection_ignored_by_renderer() -> None:
    files = [
        {
            "path": "index.html",
            "content": """
            <main><div id="task-list"></div><button onclick="deleteTask()">Delete</button>
            <button onclick="filterTasks('all')">All</button><button onclick="filterTasks('active')">Active</button>
            <button onclick="filterTasks('completed')">Completed</button></main>
            """,
        },
        {
            "path": "src/app.js",
            "content": """
            let tasks = JSON.parse(localStorage.getItem('tasks')) || [];
            function renderTasks() { taskList.textContent = tasks.length; }
            function deleteTask() { tasks.splice(0, 1); } deleteButton.onclick = deleteTask;
            function filterTasks(mode) { const filteredTasks = tasks.filter(Boolean); renderTasks(filteredTasks); }
            filterButton.onclick = filterTasks;
            """,
        },
    ]

    error = run_local_pipeline_impl.validate_task_board_interaction_contract(files)
    assert "renderer ignores all arguments" in error


def test_javascript_contract_rejects_const_collection_reassignment() -> None:
    broken = [
        {
            "path": "src/app.js",
            "content": "const tasks = [];\nfunction deleteTask(id) { tasks = tasks.filter(task => task.id !== id); }",
        }
    ]
    assert "const reassignment: tasks" in run_local_pipeline_impl.validate_javascript_const_reassignment(broken)
    fixed = [{"path": "src/app.js", "content": broken[0]["content"].replace("const tasks", "let tasks")}]
    assert run_local_pipeline_impl.validate_javascript_const_reassignment(fixed) == ""
    repeated_scopes = [{"path": "src/app.js", "content": "function a(){const taskId=1;} function b(){const taskId=2;}"}]
    assert run_local_pipeline_impl.validate_javascript_const_reassignment(repeated_scopes) == ""


def test_split_file_retry_receives_previous_dom_contract_error(monkeypatch) -> None:
    captured: dict[str, object] = {}
    captured_system: dict[str, str] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured_system["content"] = messages[0]["content"]
        captured.update(json.loads(messages[-1]["content"]))
        return '{"path":"src/app.js","content":"document.getElementById(\\"app\\").textContent = \\"Ready\\";"}'

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    item, _raw = run_local_pipeline_impl.provider_generate_component_file(
        goal="build local app",
        component={"id": "frontend"},
        component_pipeline={"components": [{"id": "frontend"}]},
        manifest_entry={"path": "src/app.js"},
        prior_manifest=[],
        completed_files=[{"path": "index.html", "content": '<main id="app"></main>'}],
        repair_errors=[],
        model="local",
        timeout=10,
        phase_log_path=None,
        routing_policy=None,
        last_transport_error="frontend DOM contract mismatch: missing add-task-btn",
        retry_attempt=2,
    )

    assert item["path"] == "src/app.js"
    assert "missing add-task-btn" in str(captured["previous_generation_error"])
    assert captured["repair_acceptance"]["attempt"] == 2
    assert any("repair_acceptance" in rule for rule in captured["strict_rules"])
    assert "CURRENT REPAIR REJECTION (highest precedence)" in captured_system["content"]
    assert "missing add-task-btn" in captured_system["content"]
    assert "All validators remain unchanged" in captured_system["content"]


def test_leaf_retry_accumulates_distinct_rejections_without_regression(monkeypatch) -> None:
    received_errors: list[str] = []
    attempts = 0

    def fake_generate(**kwargs):
        nonlocal attempts
        attempts += 1
        received_errors.append(str(kwargs.get("last_transport_error", "")))
        if attempts == 1:
            raise RuntimeError("python leaf interface contract mismatch: missing Alpha")
        if attempts == 2:
            raise RuntimeError("python leaf interface contract mismatch: missing Beta")
        return {"path": "tests/test_api.py", "content": "def test_api():\n    assert True\n"}, "raw"

    monkeypatch.setattr(run_local_pipeline_impl, "provider_generate_component_file", fake_generate)
    monkeypatch.setattr(run_local_pipeline_impl, "query_generation_context_librarian", lambda *_a, **_k: {})
    monkeypatch.setattr(run_local_pipeline_impl, "build_leaf_interface_contract", lambda **_k: {})
    monkeypatch.setenv("CGNK_PROVIDER_REPAIR_TRANSPORT_ATTEMPTS", "3")
    monkeypatch.setenv("CGKN_PROVIDER_RETRY_FAST", "1")

    result = run_local_pipeline_impl._provider_generate_leaf_with_retry(
        goal="test the published API",
        component={"id": "tests"},
        component_pipeline={"components": [{"id": "tests"}]},
        leaf={"path": "tests/test_api.py", "depends_on": []},
        entry={"path": "tests/test_api.py"},
        prior_manifest=[],
        completed_files=[],
        prior_files=[],
        manifest=[{"path": "tests/test_api.py"}],
        repair_errors=[],
        integration_feedforward={},
        interface_registry={},
        librarian_index={},
        model="local",
        timeout=10,
        deadline=None,
        phase_log_path=None,
        routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
        pending_context={},
        last_transport_error="",
    )

    assert result["file_item"]["path"] == "tests/test_api.py"
    assert received_errors[0] == ""
    assert "missing Alpha" in received_errors[1]
    assert "missing Alpha" in received_errors[2]
    assert "missing Beta" in received_errors[2]
    assert "ALL REJECTED CANDIDATE VIOLATIONS" in received_errors[2]
    assert received_errors[2].index("missing Beta") < received_errors[2].index("missing Alpha")
    assert run_local_pipeline_impl.latest_provider_leaf_repair_error(received_errors[2]).endswith(
        "missing Beta"
    )


def test_thin_leaf_is_retried_with_implementation_depth_feedback(monkeypatch, tmp_path) -> None:
    attempts = 0
    generation_payloads: list[dict[str, object]] = []
    manifest = [
        {
            "path": "backend/service.py",
            "purpose": "validate, store, and retrieve records",
            "dependencies": [],
            "estimated_complexity": "medium",
            "responsibilities": ["validate records", "store and retrieve records"],
            "acceptance_checks": ["invalid records fail", "saved records can be read"],
            "expected_symbols": ["RecordService"],
        }
    ]

    def fake_provider_text(messages, *_args, **kwargs):
        nonlocal attempts
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps({"component": "backend", "files": manifest})
        attempts += 1
        generation_payloads.append(json.loads(messages[-1]["content"]))
        if attempts == 1:
            return json.dumps(
                {
                    "path": "backend/service.py",
                    "content": "class RecordService:\n    pass\n",
                }
            )
        return json.dumps(
            {
                "path": "backend/service.py",
                "content": (
                    "class RecordService:\n"
                    "    def __init__(self):\n"
                    "        self._records = {}\n\n"
                    "    def save(self, key, value):\n"
                    "        if not key:\n"
                    "            raise ValueError(\"key is required\")\n"
                    "        self._records[key] = value\n"
                    "        return value\n\n"
                    "    def get(self, key):\n"
                    "        if key not in self._records:\n"
                    "            raise KeyError(key)\n"
                    "        return self._records[key]\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    monkeypatch.setenv("CGKN_PROVIDER_RETRY_FAST", "1")
    component = {
        "id": "backend",
        "required_paths": ["backend/service.py"],
        "minimum_file_count": 1,
    }
    result = run_local_pipeline_impl.provider_generate_project_component_split(
        goal="build a record service",
        component=component,
        component_pipeline={
            "components": [component],
            "merge_policy": {"required_final_files": ["backend/service.py"]},
        },
        prior_manifest=[],
        prior_files=[],
        repair_errors=[],
        model="test-model",
        timeout=30,
        deadline=None,
        checkpoint_dir=tmp_path / "provider_components",
        run_dir=tmp_path,
        spec_hash="depth-retry-spec",
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
        routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
        split_reason="depth_retry_test",
        original_prompt_chars=0,
    )

    assert attempts == 2
    assert "previous_generation_error" not in generation_payloads[0]
    assert "implementation depth contract mismatch" in str(
        generation_payloads[1]["previous_generation_error"]
    )
    assert generation_payloads[1]["repair_acceptance"]["attempt"] == 2
    assert generation_payloads[1]["repair_acceptance"]["minimum_nonblank_lines"] == 10
    assert result["boundary_check_receipts"][0]["status"] == "PASS"
    assert result["boundary_check_receipts"][0]["implementation_depth"]["status"] == "PASS"


def test_component_retry_promotes_pending_leaf_manifest() -> None:
    original = {"stage": "provider_semantic_repair", "root_causes": ["old"]}
    pending = {
        "stage": "component_file_generation",
        "component": "backend",
        "target_file": "backend/adapters_part_01.py",
        "file_manifest": [
            {"path": "backend/adapters_part_01.py"},
            {"path": "backend/adapters.py"},
        ],
        "completed_files": [{"path": "backend/artifact_store.py", "content": "x = 1\n"}],
    }

    promoted = run_local_pipeline_impl.promote_component_file_retry_plan(
        original,
        pending,
        "backend",
    )
    unrelated = run_local_pipeline_impl.promote_component_file_retry_plan(
        original,
        pending,
        "frontend",
    )

    assert promoted == pending
    assert promoted is not pending
    assert run_local_pipeline_impl.repair_target_files_for_component(
        promoted,
        "backend",
    ) == ["backend/adapters_part_01.py"]
    assert unrelated is original


def test_completed_pending_leaf_is_archived_before_downstream_work(
    tmp_path: pathlib.Path,
) -> None:
    pending_path = tmp_path / "artifacts" / "pending_repair_plan.json"
    run_local_pipeline_impl.write_pending_component_file_generation(
        pending_path,
        raw_user_goal="build a staged project",
        component_id="backend",
        target_file="backend/stages_part_01.py",
        file_manifest=[
            {"path": "backend/stages_part_01.py"},
            {"path": "backend/orchestrator.py"},
        ],
        completed_files=[],
        selected_model="local",
        next_retry_model="local",
        last_transport_error="thin implementation",
    )

    archived = run_local_pipeline_impl.archive_completed_pending_component_leaf(
        tmp_path,
        component_id="backend",
        target_file="backend/stages_part_01.py",
    )

    assert archived is True
    assert not pending_path.exists()
    completed = json.loads(
        (tmp_path / "artifacts" / "pending_repair_plan.completed.json").read_text(
            encoding="utf-8"
        )
    )
    assert completed["status"] == "completed"
    assert completed["target_file"] == "backend/stages_part_01.py"
    assert (
        run_local_pipeline_impl.archive_completed_pending_component_leaf(
            tmp_path,
            component_id="backend",
            target_file="backend/orchestrator.py",
        )
        is False
    )


def test_completed_wrapped_pending_leaf_is_archived_before_resume(
    tmp_path: pathlib.Path,
) -> None:
    pending_path = tmp_path / "artifacts" / "pending_repair_plan.json"
    pending_path.parent.mkdir(parents=True)
    pending_path.write_text(
        json.dumps(
            {
                "status": "pending",
                "stage": "provider_semantic_repair",
                "repair_plan": {
                    "status": "pending",
                    "stage": "component_file_generation",
                    "component": "media",
                    "target_file": "demo/run_fixture.py",
                },
            }
        ),
        encoding="utf-8",
    )

    archived = run_local_pipeline_impl.archive_completed_pending_component_leaf(
        tmp_path,
        component_id="media",
        target_file="demo/run_fixture.py",
    )

    assert archived is True
    assert not pending_path.exists()
    completed = json.loads(
        (tmp_path / "artifacts" / "pending_repair_plan.completed.json").read_text(
            encoding="utf-8"
        )
    )
    assert completed["status"] == "completed"
    assert completed["repair_plan"]["status"] == "completed"


def test_local_generation_uses_single_leaf_worker_by_default(monkeypatch) -> None:
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "local_first")
    monkeypatch.delenv("CGNK_LOCAL_PROVIDER_LEAF_MAX_WORKERS", raising=False)
    monkeypatch.setenv("CGKN_PROVIDER_LEAF_MAX_WORKERS", "8")

    assert run_local_pipeline_impl.provider_leaf_max_workers() == 1


def test_api_owned_run_switches_to_single_leaf_worker_after_local_fallback(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "api_only")
    monkeypatch.setenv("CGKN_PROVIDER_LEAF_MAX_WORKERS", "3")
    phase_log = tmp_path / "provider_phase_log.jsonl"
    phase_log.write_text(
        json.dumps(
            {
                "event": "fallback_executed",
                "to": "local_model",
                "task": "component_generation",
                "reason": "provider_key_usage_limit",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert run_local_pipeline_impl.provider_leaf_max_workers() == 3
    assert run_local_pipeline_impl.provider_leaf_max_workers(phase_log) == 1


def test_local_generation_allows_longer_manifest_timeout_without_changing_api_cap(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CGNK_PROVIDER_COMPONENT_MANIFEST_TIMEOUT_CAP", "220")
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "local_first")
    assert run_local_pipeline_impl.provider_component_manifest_timeout_cap() == 220

    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "api_only")
    assert run_local_pipeline_impl.provider_component_manifest_timeout_cap() == 120


def test_local_generation_file_and_review_timeouts_are_owner_aware(monkeypatch) -> None:
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "local_first")
    monkeypatch.delenv("CGNK_PROVIDER_COMPONENT_FILE_TIMEOUT_CAP", raising=False)
    monkeypatch.delenv("CGNK_PROVIDER_SEMANTIC_REVIEW_TIMEOUT_CAP", raising=False)
    assert run_local_pipeline_impl.provider_component_file_timeout_cap() == 180
    assert run_local_pipeline_impl.provider_semantic_review_timeout_cap() == 180

    monkeypatch.setenv("CGNK_PROVIDER_COMPONENT_FILE_TIMEOUT_CAP", "999")
    monkeypatch.setenv("CGNK_PROVIDER_SEMANTIC_REVIEW_TIMEOUT_CAP", "999")
    assert run_local_pipeline_impl.provider_component_file_timeout_cap() == 240
    assert run_local_pipeline_impl.provider_semantic_review_timeout_cap() == 240

    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "api_only")
    assert run_local_pipeline_impl.provider_component_file_timeout_cap() == 90
    assert run_local_pipeline_impl.provider_semantic_review_timeout_cap() == 90


def test_api_transport_fallback_gets_one_local_owned_attempt_and_timeout(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "balanced")
    monkeypatch.setenv("CGNK_LOCAL_PROVIDER_ATTEMPTS", "4")
    monkeypatch.delenv("CGNK_LOCAL_FALLBACK_PROVIDER_ATTEMPTS", raising=False)
    monkeypatch.delenv("CGNK_PROVIDER_COMPONENT_FILE_TIMEOUT_CAP", raising=False)
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "task_enabled", lambda _task: False)
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "call_text_task_fallback",
        lambda _task, _system, _prompt, timeout: calls.append(timeout) or {
            "ok": False,
            "provider": "ollama",
            "error": "timeout",
        },
    )

    result = run_local_pipeline_impl.try_local_provider_text(
        [{"role": "user", "content": '{"target_file":"projectpulse/model.py"}'}],
        stage="component_file_generation",
        component="backend",
        target_file="projectpulse/model.py",
        timeout=30,
        phase_log_path=None,
        force_transport_fallback=True,
    )

    assert result is None
    assert calls == [180]


def test_quota_after_inline_local_fallback_is_terminal_for_outer_repair_loop() -> None:
    info = run_local_pipeline_impl.provider_transport_error_info(
        'provider_api_request_failed: HTTP 403: {"error":"Key usage limit exceeded"} '
        '[retryable=false] [local_fallback_exhausted=true, local_fallback_attempts=1]'
    )

    assert info["is_transport"] is True
    assert info["terminal_provider_failure"] is True
    assert info["local_fallback_exhausted"] is True
    assert info["retryable"] is False


def test_exhausted_leaf_repair_is_not_retried_again_at_component_level() -> None:
    assert run_local_pipeline_impl.provider_component_error_is_retryable(
        "PROVIDER_UNKNOWN_ERROR",
        "provider leaf repair exhausted for foundation:projectpulse/__init__.py: depth mismatch",
    ) is False


def test_exhausted_leaf_repair_does_not_restart_semantic_generation(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    calls: list[int] = []

    def fail_generation(*args, **kwargs):
        calls.append(1)
        raise run_local_pipeline_impl.ProviderLeafRepairExhaustedError(
            "provider leaf repair exhausted for backend:projectpulse/cli.py: undefined names"
        )

    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_generate_project_by_components",
        fail_generation,
    )
    run_dir = tmp_path / "run"
    out_dir = tmp_path / "project"
    run_dir.mkdir()
    out_dir.mkdir()
    phase_log = run_dir / "provider_phase_log.jsonl"

    result = run_local_pipeline_impl.run_provider_semantic_review_with_repair(
        user_goal="Build ProjectPulse",
        plan_doc={},
        blueprint={},
        online_inputs={},
        market_research={},
        component_pipeline={"components": [{"id": "backend"}]},
        repair_errors=[],
        model="test",
        timeout=30,
        internal_context="",
        deadline=time.time() + 60,
        run_dir=run_dir,
        out_dir=out_dir,
        result_path=tmp_path / "result.json",
        max_repair_attempts=2,
        phase_log_path=phase_log,
    )

    assert result["status"] == "blocked"
    assert len(calls) == 1
    events = [json.loads(line) for line in phase_log.read_text(encoding="utf-8").splitlines()]
    assert not any(
        event.get("status") == "component_generation_repair_retry"
        for event in events
    )


def test_package_init_local_contract_requires_nonempty_substantive_statement() -> None:
    contract = run_local_pipeline_impl.local_provider_contract_prompt(
        "component_file_generation", "foundation", "projectpulse/__init__.py"
    )

    assert '"content":"COMPLETE_SOURCE_TEXT"' in contract
    assert "__all__: list[str] = []" in contract


def test_local_manifest_contract_uses_current_named_package_paths_not_legacy_defaults() -> None:
    paths = [
        "projectpulse/__main__.py",
        "projectpulse/model.py",
        "projectpulse/repository.py",
        "projectpulse/service.py",
        "projectpulse/cli.py",
    ]
    contract = run_local_pipeline_impl.local_provider_contract_prompt(
        "component_file_manifest",
        "backend",
        "",
        required_paths=paths,
    )
    doc = {
        "component": "backend",
        "files": [{"path": path} for path in paths],
    }

    assert "projectpulse/model.py" in contract
    assert '"main.py"' not in contract
    assert run_local_pipeline_impl.local_provider_contract_error(
        doc,
        stage="component_file_manifest",
        component="backend",
        target_file="",
        prompt_text=json.dumps({"required_paths": paths}),
    ) == ""


def test_local_manifest_fallback_gets_one_bounded_shape_correction(monkeypatch) -> None:
    paths = ["projectpulse/model.py", "projectpulse/cli.py"]
    calls: list[int] = []
    outputs = iter(
        [
            json.dumps({"component": "backend", "files": [{"path": "main.py"}]}),
            json.dumps({"component": "backend", "files": [{"path": path} for path in paths]}),
        ]
    )
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "balanced")
    monkeypatch.delenv("CGNK_LOCAL_MANIFEST_FALLBACK_ATTEMPTS", raising=False)
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "task_enabled", lambda _task: False)
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "call_text_task_fallback",
        lambda _task, _system, _prompt, timeout: calls.append(timeout) or {
            "ok": True,
            "provider": "ollama",
            "model": "test",
            "text": next(outputs),
        },
    )

    result = run_local_pipeline_impl.try_local_provider_text(
        [{"role": "user", "content": json.dumps({"required_paths": paths})}],
        stage="component_file_manifest",
        component="backend",
        target_file="",
        timeout=30,
        phase_log_path=None,
        force_transport_fallback=True,
    )

    assert json.loads(result or "{}")["files"] == [{"path": path} for path in paths]
    assert calls == [180, 180]


def test_local_manifest_shape_correction_uses_minimal_exact_template(monkeypatch) -> None:
    paths = [
        "projectpulse/__main__.py",
        "projectpulse/model.py",
        "projectpulse/repository.py",
        "projectpulse/service.py",
        "projectpulse/cli.py",
    ]
    prompts: list[str] = []
    systems: list[str] = []
    outputs = iter(
        [
            json.dumps({"component": "backend", "files": [{"path": "main.py"}]}),
            json.dumps({"component": "backend", "files": [{"path": path} for path in paths]}),
        ]
    )
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "balanced")
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "task_enabled", lambda _task: False)

    def fake_fallback(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        systems.append(system)
        prompts.append(prompt)
        return {
            "ok": True,
            "provider": "ollama",
            "model": "test",
            "text": next(outputs),
        }

    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "call_text_task_fallback",
        fake_fallback,
    )
    original_payload = {
        "required_paths": paths,
        "legacy_context": "main.py backend/model.py backend/cli.py",
        "irrelevant_context": "x" * 5000,
    }

    result = run_local_pipeline_impl.try_local_provider_text(
        [{"role": "user", "content": json.dumps(original_payload)}],
        stage="component_file_manifest",
        component="backend",
        target_file="",
        timeout=30,
        phase_log_path=None,
        force_transport_fallback=True,
    )

    assert result is not None
    assert len(prompts) == 2
    assert "bounded manifest-shape correction" in systems[1]
    assert len(prompts[1]) < 1000
    assert "backend/model.py" not in prompts[1]
    assert json.loads(prompts[1]) == {
        "component": "backend",
        "files": [
            {"path": path, "purpose": "planned component file"}
            for path in paths
        ],
    }


def test_local_named_package_manifest_projects_only_unambiguous_legacy_aliases(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    paths = [
        "projectpulse/__main__.py",
        "projectpulse/model.py",
        "projectpulse/repository.py",
        "projectpulse/service.py",
        "projectpulse/cli.py",
    ]
    calls: list[str] = []
    legacy_paths = [
        "backend/__main__.py",
        "backend/model.py",
        "backend/repository.py",
        "backend/service.py",
        "backend/cli.py",
    ]
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "balanced")
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "task_enabled", lambda _task: False)

    def fake_fallback(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        calls.append(prompt)
        return {
            "ok": True,
            "provider": "ollama",
            "model": "test",
            "text": json.dumps(
                {
                    "component": "backend",
                    "files": [
                        {"path": path, "purpose": f"legacy {path}"}
                        for path in legacy_paths
                    ],
                }
            ),
        }

    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "call_text_task_fallback",
        fake_fallback,
    )
    phase_log = tmp_path / "provider_phase_log.jsonl"

    raw = run_local_pipeline_impl.try_local_provider_text(
        [{"role": "user", "content": json.dumps({"required_paths": paths})}],
        stage="component_file_manifest",
        component="backend",
        target_file="",
        timeout=30,
        phase_log_path=phase_log,
        force_transport_fallback=True,
    )

    assert len(calls) == 1
    assert [item["path"] for item in json.loads(raw or "{}")["files"]] == paths
    events = [json.loads(line) for line in phase_log.read_text(encoding="utf-8").splitlines()]
    projected = [
        event
        for event in events
        if event.get("reason") == "named_package_manifest_alias_projection"
    ]
    assert len(projected) == 1
    assert projected[0]["path_projections"] == [
        {"from": source, "to": target}
        for source, target in zip(legacy_paths, paths)
    ]


def test_named_package_goal_plan_replaces_legacy_component_required_paths() -> None:
    component_pipeline = {
        "components": [
            {
                "id": "foundation",
                "required_paths": ["requirements.txt", "pyproject.toml"],
                "minimum_file_count": 2,
            },
            {
                "id": "backend",
                "required_paths": ["main.py", "backend/model.py", "backend/cli.py"],
                "minimum_file_count": 3,
                "depends_on": ["foundation"],
            },
            {
                "id": "tests",
                "required_paths": ["tests/test_pipeline.py"],
                "minimum_file_count": 1,
                "depends_on": ["backend"],
            },
            {
                "id": "docs",
                "required_paths": ["README.md", "docs/architecture.md"],
                "minimum_file_count": 2,
                "depends_on": ["tests"],
            },
        ]
    }
    goal_spec = {
        "status": "PASS",
        "package_name": "projectpulse",
        "interaction_modes": ["cli"],
    }
    backend_paths = [
        "projectpulse/__main__.py",
        "projectpulse/model.py",
        "projectpulse/repository.py",
        "projectpulse/service.py",
        "projectpulse/cli.py",
    ]
    project_plan = {
        "status": "PASS",
        "workstreams": [
            {
                "id": "foundation",
                "scope": "project shell",
                "expected_outputs": [
                    "pyproject.toml",
                    "requirements.txt",
                    "projectpulse/__init__.py",
                ],
            },
            *[
                {
                    "id": f"backend_{index}",
                    "scope": f"backend leaf {path}",
                    "expected_outputs": [path],
                }
                for index, path in enumerate(backend_paths)
            ],
            {
                "id": "record_behavior_tests",
                "scope": "behavior tests",
                "expected_outputs": ["tests/test_projectpulse.py"],
            },
            {
                "id": "delivery",
                "scope": "delivery docs",
                "expected_outputs": ["README.md", "TEST_PLAN.md", "DELIVERY_NOTES.md"],
            },
        ],
        "leaves": [],
    }

    enriched = run_local_pipeline_impl.enrich_component_pipeline_with_goal_plan(
        component_pipeline,
        goal_spec,
        project_plan,
    )
    by_id = {component["id"]: component for component in enriched["components"]}

    assert by_id["backend"]["required_paths"] == backend_paths
    assert by_id["backend"]["minimum_file_count"] == len(backend_paths)
    assert by_id["tests"]["required_paths"] == ["tests/test_projectpulse.py"]
    assert by_id["docs"]["required_paths"] == ["README.md", "TEST_PLAN.md", "DELIVERY_NOTES.md"]
    assert all(
        component["required_path_authority"] == "canonical_goal_project_plan"
        for component in by_id.values()
    )


def test_named_package_foundation_manifest_prunes_unplanned_package_files(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    required_paths = [
        "pyproject.toml",
        "requirements.txt",
        "projectpulse/__init__.py",
    ]
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_text",
        lambda *_args, **_kwargs: json.dumps(
            {
                "component": "foundation",
                "files": [
                    *[
                        {"path": path, "purpose": f"planned {path}"}
                        for path in required_paths
                    ],
                    {
                        "path": "projectpulse/cli.py",
                        "purpose": "unplanned application file",
                    },
                ],
            }
        ),
    )
    phase_log = tmp_path / "provider_phase_log.jsonl"

    manifest = run_local_pipeline_impl.provider_component_file_manifest(
        goal="Build ProjectPulse",
        component={
            "id": "foundation",
            "required_paths": required_paths,
            "minimum_file_count": len(required_paths),
            "canonical_goal_spec": {"package_name": "projectpulse"},
        },
        component_pipeline={"components": [{"id": "foundation"}]},
        prior_manifest=[],
        repair_errors=[],
        model="test",
        timeout=30,
        phase_log_path=phase_log,
        routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
    )

    assert [item["path"] for item in manifest] == required_paths
    events = [json.loads(line) for line in phase_log.read_text(encoding="utf-8").splitlines()]
    normalized = [
        event
        for event in events
        if event.get("reason") == "named_package_manifest_scope_normalization"
    ]
    assert normalized[0]["component"] == "foundation"
    assert normalized[0]["pruned_paths"] == ["projectpulse/cli.py"]


def test_named_package_direct_cli_manifest_freezes_layer_dependencies_and_symbols() -> None:
    paths = [
        "projectpulse/__main__.py",
        "projectpulse/model.py",
        "projectpulse/repository.py",
        "projectpulse/service.py",
        "projectpulse/cli.py",
    ]
    component = {
        "contract_slice": {"architecture_mode": "direct_cli_application"},
        "canonical_goal_spec": {
            "domain": "local_record_cli",
            "package_name": "projectpulse",
            "entities": ["Task", "JSONRepository", "TaskService"],
            "capabilities": ["add_task", "list_task", "complete_task", "delete_task"],
        },
        "required_paths": paths,
    }
    manifest = [{"path": path} for path in paths]

    normalized = run_local_pipeline_impl.normalize_direct_cli_manifest_contract(
        "backend",
        manifest,
        component,
    )
    by_path = {item["path"]: item for item in normalized}

    assert by_path["projectpulse/model.py"]["dependencies"] == []
    assert by_path["projectpulse/repository.py"]["dependencies"] == ["projectpulse/model.py"]
    assert by_path["projectpulse/service.py"]["dependencies"] == [
        "projectpulse/model.py",
        "projectpulse/repository.py",
    ]
    assert by_path["projectpulse/cli.py"]["dependencies"] == [
        "projectpulse/model.py",
        "projectpulse/repository.py",
        "projectpulse/service.py",
    ]
    assert by_path["projectpulse/__main__.py"]["dependencies"] == ["projectpulse/cli.py"]
    assert by_path["projectpulse/cli.py"]["expected_symbols"] == ["build_parser", "main"]
    service_contract = run_local_pipeline_impl.direct_cli_leaf_contract(
        component,
        "projectpulse/service.py",
    )
    cli_contract = run_local_pipeline_impl.direct_cli_leaf_contract(
        component,
        "projectpulse/cli.py",
    )
    assert "never redefine" in service_contract["ownership"]
    assert any("returns 0 on success and 2" in rule for rule in cli_contract["api"])
    assert any("service.add(...).to_dict()" in rule for rule in cli_contract["api"])
    assert "import json" in cli_contract["exact_imports"]
    assert "import sys" in cli_contract["exact_imports"]


@pytest.mark.parametrize(
    ("path", "source", "contract", "expected"),
    [
        (
            "projectpulse/model.py",
            "class Task:\n    def __init__(self, id, title):\n        self.id = id\n        self.title = title\n\n    def to_dict(self):\n        return {'id': self.id, 'title': self.title}\n\n    def from_dict(data):\n        return Task(data['id'], data['title'])\n",
            {"required_symbols": ["Task"]},
            "must not read persistence",
        ),
        (
            "projectpulse/repository.py",
            "class JSONRepository:\n    def __init__(self, path):\n        self.path = path\n    def load(self):\n        return []\n    def save(self):\n        return None\n",
            {"required_symbols": ["JSONRepository"]},
            "save must accept the complete task collection",
        ),
        (
            "projectpulse/service.py",
            "class TaskService:\n    def __init__(self, repository):\n        self.repository = repository\n    def add(self, title):\n        return title\n",
            {"required_symbols": ["TaskService"]},
            "missing required behaviors",
        ),
        (
            "projectpulse/cli.py",
            "import argparse\ndef build_parser():\n    return argparse.ArgumentParser()\ndef main(argv=None):\n    return 0\n",
            {"required_symbols": ["build_parser", "main"]},
            "missing exact standard-library imports: json, sys",
        ),
    ],
)
def test_named_direct_cli_leaf_rejects_shallow_cached_implementations(
    path: str,
    source: str,
    contract: dict[str, object],
    expected: str,
) -> None:
    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        path,
        source,
        ast.parse(source),
        contract,
    )

    assert expected in error


def test_local_output_gate_applies_named_direct_cli_leaf_contract() -> None:
    source = (
        "class TaskService:\n"
        "    def __init__(self, repository):\n"
        "        self.repository = repository\n"
        "    def add(self, title):\n"
        "        return title\n"
    )
    prompt = json.dumps(
        {
            "direct_cli_leaf_contract": {
                "required_symbols": ["TaskService"],
            }
        }
    )

    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "projectpulse/service.py", "content": source},
        stage="component_file_generation",
        component="backend",
        target_file="projectpulse/service.py",
        prompt_text=prompt,
    )

    assert "missing required behaviors" in error


def test_local_output_gate_rejects_unittest_or_lambda_direct_cli_tests() -> None:
    prompt = json.dumps({"direct_cli_leaf_contract": {"test_contract": ["pytest functions"]}})
    unittest_source = "import unittest\nclass TestTasks(unittest.TestCase):\n    def test_add(self):\n        assert True\n"
    lambda_source = "test_add = lambda tmp_path: bool(tmp_path)\n"

    unittest_error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_projectpulse.py", "content": unittest_source},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_projectpulse.py",
        prompt_text=prompt,
    )
    lambda_error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_projectpulse.py", "content": lambda_source},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_projectpulse.py",
        prompt_text=prompt,
    )

    assert "pytest top-level test functions" in unittest_error
    assert "pytest top-level test functions" in lambda_error


def test_named_direct_cli_rejects_chained_parser_and_raw_task_json() -> None:
    chained = (
        "import argparse\nimport json\nimport sys\n"
        "def build_parser():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_subparsers().add_parser('import').add_argument('path').add_argument('--mode')\n"
        "    return parser\n"
        "def main(argv=None):\n"
        "    service.add('x'); service.list(); service.complete('1'); service.delete('1')\n"
        "    service.summary(); service.export_to('x'); service.import_from('x', 'merge')\n"
        "    return 0 if argv else 2\n"
    )
    contract = {"required_symbols": ["build_parser", "main"]}

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "projectpulse/cli.py", chained, ast.parse(chained), contract
    )

    assert "never chain add_argument" in error

    unchained = chained.replace(
        "parser.add_subparsers().add_parser('import').add_argument('path').add_argument('--mode')",
        "parser.add_subparsers()",
    )
    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "projectpulse/cli.py", unchained, ast.parse(unchained), contract
    )
    assert "through to_dict" in error


def test_local_file_repair_gate_applies_frozen_direct_cli_test_contract() -> None:
    source = """def test_goal_11_duplicate_task_identifiers_are_rejected_without(task_service):
    duplicate_path = tmp_path / 'duplicates.json'
    task_service.import_from(duplicate_path, 'merge')
"""
    prompt = json.dumps(
        {
            "direct_cli_leaf_contract": {
                "test_contract": ["pytest"],
                "required_symbols": [
                    "test_goal_11_duplicate_task_identifiers_are_rejected_without"
                ],
                "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
            },
            "previous_validation_errors": [
                "named direct CLI duplicate-identifier tests must exercise repository.save() or service.import_from() with duplicate IDs"
            ],
        }
    )
    doc = {
        "component_id": "post_build",
        "files": [
            {"path": "tests/test_projectpulse_part_02.py", "content": source}
        ],
    }

    error = run_local_pipeline_impl.local_provider_contract_error(
        doc,
        stage="file_repair",
        component="post_build",
        target_file="tests/test_projectpulse_part_02.py",
        prompt_text=prompt,
    )

    assert "request tmp_path as a function parameter" in error


def test_named_direct_cli_module_entry_publishes_imported_main() -> None:
    source = (
        "from projectpulse.cli import main\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    )

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "projectpulse/__main__.py",
        source,
        ast.parse(source),
        {"required_symbols": ["main"]},
    )

    assert error == ""


@pytest.mark.parametrize(
    ("path", "source", "contract", "expected"),
    [
        (
            "projectpulse/repository.py",
            "import json\nimport os\nfrom projectpulse.model import Task\nclass JSONRepository:\n    def __init__(self, data_file): self.data_file = data_file\n    def load(self): return [Task(**row) for row in []]\n    def save(self, tasks):\n        payload = {'version': 1, 'tasks': [task.to_dict() for task in tasks]}\n        with open(str(self.data_file) + '.tmp', 'w') as stream: json.dump(payload, stream)\n        os.replace(str(self.data_file) + '.tmp', self.data_file)\n",
            {"required_symbols": ["JSONRepository"], "architecture": "Task model -> JSONRepository"},
            "reject duplicate identifiers",
        ),
        (
            "projectpulse/service.py",
            "from datetime import datetime\nfrom projectpulse.model import Task\nclass TaskService:\n    def __init__(self, repository): self.repository = repository\n    def add(self, title): return Task(1, title, False, datetime.now())\n    def list(self, status='all'): return []\n    def complete(self, task_id: int): return Task('1', 'x')\n    def delete(self, task_id: int): return Task('1', 'x')\n    def summary(self): return {'total': 0, 'open': 0, 'completed': 0}\n    def export_to(self, path): return None\n    def import_from(self, path, mode):\n        continue_flag = False\n        return 0\n",
            {"required_symbols": ["TaskService"], "architecture": "Task model -> JSONRepository -> TaskService"},
            "identifiers are strings",
        ),
        (
            "projectpulse/cli.py",
            "import argparse\nimport json\nimport sys\ndef build_parser(): return argparse.ArgumentParser()\ndef main(argv=None):\n    service.add('x'); service.list(); service.complete('1'); service.delete('1'); service.summary(); service.export_to('x'); service.import_from('x', 'merge')\n    print('not json')\n    task.to_dict()\n    return 0 if argv else 2\n",
            {"required_symbols": ["build_parser", "main"]},
            "json.dumps for every command",
        ),
        (
            "tests/test_projectpulse_part_01.py",
            "from pathlib import Path\ntmp_path = Path('/tmp')\ndef test_add():\n    main(['projectpulse', '--data-file', 'tasks.json', 'add', 'x'])\n",
            {"test_contract": ["pytest functions"]},
            "never define it globally",
        ),
    ],
)
def test_named_direct_cli_rejects_runtime_coherence_regressions(
    path: str,
    source: str,
    contract: dict[str, object],
    expected: str,
) -> None:
    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        path, source, ast.parse(source), contract
    )

    assert expected in error


def test_named_direct_cli_service_import_preserves_optional_iso_created_at() -> None:
    template = """from datetime import datetime
from projectpulse.model import Task
class TaskService:
    def __init__(self, repository): self.repository = repository
    def add(self, title): return Task('1', title)
    def list(self, status='all'): return []
    def complete(self, task_id): return Task(task_id, 'x')
    def delete(self, task_id): return Task(task_id, 'x')
    def summary(self): return {'total': 0, 'open': 0, 'completed': 0}
    def export_to(self, path): return None
    def import_from(self, path, mode):
        row = {'id': '1', 'title': 'x', 'completed': False}
        imported = IMPORT_EXPRESSION
        return len(imported)
"""
    contract = {
        "required_symbols": ["TaskService"],
        "architecture": "Task model -> JSONRepository -> TaskService",
    }
    bad = template.replace(
        "IMPORT_EXPRESSION",
        "[Task(row['id'], row['title'], row['completed'], datetime.fromisoformat(row['created_at']))]",
    )
    good = template.replace(
        "IMPORT_EXPRESSION",
        "[Task(row['id'], row['title'], row['completed'], row.get('created_at'))]",
    )
    good_with_iso_default = template.replace(
        "IMPORT_EXPRESSION",
        "[Task(row['id'], row['title'], row['completed'], row.get('created_at', datetime.now().isoformat()))]",
    )

    bad_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "projectpulse/service.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "projectpulse/service.py", good, ast.parse(good), contract
    )
    good_with_iso_default_error = (
        run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
            "projectpulse/service.py",
            good_with_iso_default,
            ast.parse(good_with_iso_default),
            contract,
        )
    )

    assert "preserve optional created_at as an ISO-8601 string" in bad_error
    assert good_error == ""
    assert good_with_iso_default_error == ""


def test_named_direct_cli_readme_requires_copyable_complete_usage() -> None:
    bad = """# ProjectPulse
```bash
projectpulse add "Task"
projectpulse import import.json --mode merge
```
"""
    good = """# ProjectPulse
```bash
projectpulse --data-file tasks.json add "Task"
projectpulse --data-file tasks.json list --status open
projectpulse --data-file tasks.json complete 1
projectpulse --data-file tasks.json delete 1
projectpulse --data-file tasks.json summary
projectpulse --data-file tasks.json export export.json
projectpulse --data-file tasks.json import import.json --mode merge
projectpulse --data-file tasks.json import import.json --mode replace
python -m projectpulse --data-file tasks.json summary
```
"""

    bad_error = run_local_pipeline_impl.named_direct_cli_readme_contract_error(
        bad, "projectpulse"
    )
    good_error = run_local_pipeline_impl.named_direct_cli_readme_contract_error(
        good, "projectpulse"
    )

    assert "copyable --data-file usage examples" in bad_error
    assert "python -m entry" in bad_error
    assert "list status filter" in bad_error
    assert "import replace" in bad_error
    assert good_error == ""


def test_named_direct_cli_rejects_runtime_none_placeholder() -> None:
    source = """import json
import os
datetime = None
from projectpulse.model import Task
class JSONRepository:
    def __init__(self, data_file): self.data_file = data_file
    def load(self): return [Task(**row) for row in []]
    def reject_duplicate_ids(self, tasks):
        if len({task.id for task in tasks}) != len(tasks): raise ValueError('duplicate')
    def save(self, tasks):
        self.reject_duplicate_ids(tasks)
        payload = {'version': 1, 'tasks': [task.to_dict() for task in tasks]}
        with open(str(self.data_file) + '.tmp', 'w') as stream: json.dump(payload, stream)
        os.replace(str(self.data_file) + '.tmp', self.data_file)
"""
    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "projectpulse/repository.py",
        source,
        ast.parse(source),
        {
            "required_symbols": ["JSONRepository"],
            "architecture": "Task model -> JSONRepository",
        },
    )

    assert "must not assign None placeholders" in error
    assert "datetime" in error


def test_named_direct_cli_service_import_must_propagate_data_errors() -> None:
    template = """import json
from projectpulse.model import Task
class TaskService:
    def __init__(self, repository): self.repository = repository
    def add(self, title): return Task('1', title)
    def list(self, status='all'): return []
    def complete(self, task_id): return Task(task_id, 'x')
    def delete(self, task_id): return Task(task_id, 'x')
    def summary(self): return {'total': 0, 'open': 0, 'completed': 0}
    def export_to(self, path): return None
    def import_from(self, path, mode):
        try:
            data = json.load(open(path, encoding='utf-8'))
        except json.JSONDecodeError as exc:
            ERROR_ACTION
        return len(data)
"""
    bad = template.replace("ERROR_ACTION", "return 2")
    good = template.replace(
        "ERROR_ACTION", "raise ValueError('Malformed input') from exc"
    )
    contract = {
        "required_symbols": ["TaskService"],
        "architecture": "Task model -> JSONRepository -> TaskService",
    }

    bad_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "projectpulse/service.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "projectpulse/service.py", good, ast.parse(good), contract
    )

    assert "must raise ValueError for malformed input" in bad_error
    assert good_error == ""


def test_named_direct_cli_serializes_each_task_returning_cli_branch() -> None:
    template = """import argparse
import json
import sys
def build_parser(): return argparse.ArgumentParser()
def main(argv=None):
    try:
        task = service.add('x')
        print(json.dumps(task.to_dict()))
        print(json.dumps([task.to_dict() for task in service.list()]))
        task = service.complete('1')
        print(json.dumps(task.to_dict()))
        deleted = service.delete('1')
        print(json.dumps(DELETE_OUTPUT))
        print(json.dumps(service.summary()))
        service.export_to('out.json')
        print(json.dumps({'exported_to': 'out.json'}))
        imported = service.import_from('in.json', 'merge')
        print(json.dumps({'imported': imported}))
    except Exception:
        return 2
    return 0
"""
    bad = template.replace("DELETE_OUTPUT", "deleted")
    good = template.replace("DELETE_OUTPUT", "deleted.to_dict()")
    contract = {"required_symbols": ["build_parser", "main"]}

    bad_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "projectpulse/cli.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "projectpulse/cli.py", good, ast.parse(good), contract
    )

    assert "serialize each Task-returning success command" in bad_error
    assert bad_error.endswith("delete")
    assert good_error == ""


def test_named_direct_cli_duplicate_id_goal_uses_collection_boundary() -> None:
    fixture = """import pytest
from projectpulse.model import Task
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

@pytest.fixture
def task_service(tmp_path):
    return TaskService(JSONRepository(tmp_path / 'tasks.json'))

"""
    bad = fixture + """def test_goal_11_duplicate_task_identifiers_are_rejected_without(task_service):
    with pytest.raises(ValueError):
        task_service.add('same title')
        task_service.add('same title')
"""
    good = fixture + """def test_goal_11_duplicate_task_identifiers_are_rejected_without(tmp_path):
    repository = JSONRepository(tmp_path / 'tasks.json')
    repository.save([Task('seed', 'existing')])
    before = repository.data_file.read_text()
    with pytest.raises(ValueError):
        repository.save([Task('same', 'first'), Task('same', 'second')])
    assert repository.data_file.read_text() == before
"""
    contract = {
        "test_contract": ["pytest functions"],
        "required_symbols": [
            "test_goal_11_duplicate_task_identifiers_are_rejected_without"
        ],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    bad_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", good, ast.parse(good), contract
    )

    assert "adding the same title twice" in bad_error
    assert good_error == ""


def test_named_direct_cli_duplicate_import_uses_list_and_proves_unchanged() -> None:
    source = """import json
import pytest
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

@pytest.fixture
def task_service(tmp_path):
    return TaskService(JSONRepository(tmp_path / 'tasks.json'))

def test_goal_11_duplicate_task_identifiers_are_rejected_without(task_service, tmp_path):
    payload = {'tasks': [{'id': 'same'}, {'id': 'same'}]}
    path = tmp_path / 'duplicates.json'
    with path.open('w') as stream:
        json.dump(payload, stream)
    with pytest.raises(ValueError):
        task_service.import_from(path, 'merge')
"""
    contract = {
        "test_contract": ["pytest functions"],
        "required_symbols": [
            "test_goal_11_duplicate_task_identifiers_are_rejected_without"
        ],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", source, ast.parse(source), contract
    )

    assert "must write a top-level JSON list" in error

    same_path = source.replace(
        "payload = {'tasks': [{'id': 'same'}, {'id': 'same'}]}",
        "task_service.add('existing')\n    payload = [{'id': 'same'}, {'id': 'same'}]",
    ).replace(
        "path = tmp_path / 'duplicates.json'",
        "path = task_service.repository.data_file",
    ) + "    assert path.read_text()\n"
    same_path_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py",
        same_path,
        ast.parse(same_path),
        contract,
    )

    assert "keep the import JSON path separate" in same_path_error

    unseeded = source.replace(
        "payload = {'tasks': [{'id': 'same'}, {'id': 'same'}]}",
        "payload = [{'id': 'same'}, {'id': 'same'}]",
    ) + "    assert task_service.repository.data_file.read_text()\n"
    unseeded_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py",
        unseeded,
        ast.parse(unseeded),
        contract,
    )

    assert "must create valid pre-existing repository state" in unseeded_error


def test_duplicate_identifier_micro_freezes_separate_path_control_flow() -> None:
    payload = {
        "target_file": "tests/test_projectpulse_part_02.py",
        "previous_validation_errors": [
            "named direct CLI duplicate-identifier tests must exercise repository.save() or service.import_from()"
        ],
        "target_file_contents": [
            {
                "path": "tests/test_projectpulse_part_02.py",
                "content": "def test_goal_11_duplicate_task_identifiers_are_rejected_without():\n    pass\n",
            }
        ],
        "direct_cli_leaf_contract": {
            "required_symbols": [
                "test_goal_11_duplicate_task_identifiers_are_rejected_without",
                "test_goal_14_cli_returns_exit_code_0_on_success_and_exit_code",
            ]
        },
    }

    prompt = run_local_pipeline_impl.compact_local_post_build_direct_cli_repair_prompt(
        json.dumps(payload), "tests/test_projectpulse_part_02.py"
    )

    assert "mandatory_import_control_flow" in prompt
    assert "storage_path = task_service.repository.data_file" in prompt
    assert "import_path = tmp_path / 'duplicates.json'" in prompt
    assert "task_service.import_from(import_path, 'merge')" in prompt
    assert "composed_goal_14_control_flow" in prompt
    assert "main(['--data-file', str(data_file), 'add', 'existing']) == 0" in prompt


def test_named_direct_cli_goal_14_exercises_main_exit_codes() -> None:
    bad = """def test_goal_14_cli_returns_exit_code_0_on_success_and_exit_code():
    with pytest.raises(SystemExit):
        main([])
"""
    good = """from projectpulse.cli import main

def test_goal_14_cli_returns_exit_code_0_on_success_and_exit_code(tmp_path):
    data_file = tmp_path / 'tasks.json'
    assert main(['--data-file', str(data_file), 'add', 'existing']) == 0
    assert main(['--data-file', str(data_file), 'complete', 'missing-id']) == 2
"""
    assigned = good.replace(
        "assert main(['--data-file', str(data_file), 'add', 'existing']) == 0",
        "success_code = main(['--data-file', str(data_file), 'add', 'existing'])\n    assert success_code == 0",
    ).replace(
        "assert main(['--data-file', str(data_file), 'complete', 'missing-id']) == 2",
        "error_code = main(['--data-file', str(data_file), 'complete', 'missing-id'])\n    assert error_code == 2",
    )
    contract = {
        "test_contract": ["pytest functions"],
        "required_symbols": [
            "test_goal_14_cli_returns_exit_code_0_on_success_and_exit_code"
        ],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    bad_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", good, ast.parse(good), contract
    )
    assigned_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", assigned, ast.parse(assigned), contract
    )

    assert "must assert main([...]) == 0/2" in bad_error
    assert good_error == ""
    assert assigned_error == ""


def test_named_direct_cli_service_errors_use_value_error() -> None:
    fixture = """import pytest
from projectpulse.service import TaskService
from projectpulse.repository import JSONRepository

@pytest.fixture
def task_service(tmp_path):
    return TaskService(JSONRepository(tmp_path / 'tasks.json'))

"""
    bad = fixture + """def test_goal_03_delete_removes_an_existing_task_and_reports_a_st(task_service):
    created = task_service.add('existing')
    task_service.delete(created.id)
    with pytest.raises(SystemExit) as excinfo:
        task_service.delete(created.id)
    assert excinfo.value.code == 2
"""
    good = bad.replace(
        "with pytest.raises(SystemExit) as excinfo:",
        "with pytest.raises(ValueError):",
    ).replace("    assert excinfo.value.code == 2\n", "")
    contract = {
        "test_contract": ["pytest functions"],
        "required_symbols": [
            "test_goal_03_delete_removes_an_existing_task_and_reports_a_st"
        ],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    bad_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_03.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_03.py", good, ast.parse(good), contract
    )

    assert "service-layer error tests must expect ValueError" in bad_error
    assert good_error == ""


def test_service_value_error_repairs_compose_across_part03_leaf() -> None:
    target = "tests/test_projectpulse_part_03.py"
    source = """import pytest

def test_goal_03_delete_removes_an_existing_task_and_reports_a_st(task_service):
    with pytest.raises(SystemExit) as delete_error:
        task_service.delete('missing')
    assert delete_error.value.code == 2

def test_goal_09_corrupt_storage_fails_safely_without_overwriting(task_service):
    with pytest.raises(SystemExit) as corrupt_error:
        task_service.list()
    assert corrupt_error.value.code == 2

def test_goal_15_python_m_projectpulse_and_the_projectpulse_conso():
    with pytest.raises(SystemExit):
        raise SystemExit(0)
"""
    compact_prompt = json.dumps(
        {
            "target_file_contents": [{"path": target, "content": source}],
            "highest_precedence_repair": {},
        }
    )

    repaired_prompt = json.loads(
        run_local_pipeline_impl.compose_exact_service_value_error_repairs(
            compact_prompt, target
        )
    )
    repair = repaired_prompt["highest_precedence_repair"]
    repaired_source = repair["exact_expected_complete_source"]

    assert repaired_source.count("pytest.raises(ValueError)") == 2
    assert ".value.code" not in repaired_source
    assert "def test_goal_15" in repaired_source
    assert "pytest.raises(SystemExit)" in repaired_source
    assert repair["repair_kind"] == "composed_exact_service_value_error_test_repairs"


def test_named_direct_cli_goal_12_proves_import_id_is_nonconflicting() -> None:
    fixture = """import pytest
from projectpulse.service import TaskService
from projectpulse.repository import JSONRepository

@pytest.fixture
def task_service(tmp_path):
    return TaskService(JSONRepository(tmp_path / 'tasks.json'))

"""
    bad = fixture + """def test_goal_12_import_merge_adds_non_conflicting_task_records_a(task_service):
    task_service.add('existing')
    task_service.import_from('import.json', 'merge')
"""
    good = fixture + """def test_goal_12_import_merge_adds_non_conflicting_task_records_a(task_service):
    created = task_service.add('existing')
    imported_id = '2'
    assert imported_id != created.id
    task_service.import_from('import.json', 'merge')
"""
    contract = {
        "test_contract": ["pytest functions"],
        "required_symbols": [
            "test_goal_12_import_merge_adds_non_conflicting_task_records_a"
        ],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    bad_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_03.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_03.py", good, ast.parse(good), contract
    )

    assert "goal-12 non-conflicting merge tests must capture" in bad_error
    assert good_error == ""


def test_goal_12_exact_merge_repair_composes_with_active_complete_source() -> None:
    target = "tests/test_projectpulse_part_03.py"
    source = """import json

def test_goal_03_delete_removes_an_existing_task_and_reports_a_st():
    assert True

def test_goal_12_import_merge_adds_non_conflicting_task_records_a(task_service, tmp_path):
    task_service.add('existing')
    task_service.import_from(tmp_path / 'import.json', 'merge')
"""
    compact_prompt = json.dumps(
        {
            "target_file_contents": [{"path": target, "content": "stale"}],
            "direct_cli_leaf_contract": {
                "required_symbols": [
                    "test_goal_03_delete_removes_an_existing_task_and_reports_a_st",
                    "test_goal_12_import_merge_adds_non_conflicting_task_records_a",
                ]
            },
            "highest_precedence_repair": {
                "repair_kind": "earlier_exact_repair",
                "exact_expected_complete_source": source,
            },
        }
    )

    repaired_prompt = json.loads(
        run_local_pipeline_impl.compose_exact_goal_12_merge_repair(
            compact_prompt, target
        )
    )
    repair = repaired_prompt["highest_precedence_repair"]
    repaired_source = repair["exact_expected_complete_source"]

    assert "def test_goal_03_delete_removes_an_existing_task_and_reports_a_st" in repaired_source
    assert "created = task_service.add('existing')" in repaired_source
    assert "assert imported_id != created.id" in repaired_source
    assert "assert any(task.id == imported_id for task in tasks)" in repaired_source
    assert repair["repair_kind"] == "composed_exact_goal_12_merge_test_repair"
    assert repair["formal_model_participation"] is False


def test_goal_15_entrypoint_boundary_and_exact_composition() -> None:
    target = "tests/test_projectpulse_part_03.py"
    bad = """import pytest
from projectpulse.service import TaskService
from projectpulse.repository import JSONRepository

@pytest.fixture
def task_service(tmp_path):
    return TaskService(JSONRepository(tmp_path / 'tasks.json'))

def test_goal_15_python_m_projectpulse_and_the_projectpulse_conso(task_service):
    task_service.add('existing')
"""
    good = """import subprocess
import sys
import tomllib
from pathlib import Path

def test_goal_15_python_m_projectpulse_and_the_projectpulse_conso(tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-m', 'projectpulse', '--data-file', str(tmp_path / 'tasks.json'), 'summary'])
    assert result.returncode == 0
    document = tomllib.loads((root / 'pyproject.toml').read_text())
    assert document['project']['scripts']['projectpulse'] == 'projectpulse.cli:main'
"""
    attribute_bad = good.replace(
        "document['project']['scripts']['projectpulse']",
        "document['project'].scripts.projectpulse",
    )
    contract = {
        "test_contract": ["pytest functions"],
        "required_symbols": [
            "test_goal_15_python_m_projectpulse_and_the_projectpulse_conso"
        ],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    bad_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        target, bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        target, good, ast.parse(good), contract
    )
    attribute_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        target, attribute_bad, ast.parse(attribute_bad), contract
    )
    compact_prompt = json.dumps(
        {
            "target_file_contents": [{"path": target, "content": bad}],
            "direct_cli_leaf_contract": contract,
            "highest_precedence_repair": {},
        }
    )
    repaired_prompt = json.loads(
        run_local_pipeline_impl.compose_exact_goal_15_entrypoint_repair(
            compact_prompt, target
        )
    )
    repair = repaired_prompt["highest_precedence_repair"]
    repaired_source = repair["exact_expected_complete_source"]

    assert "goal-15 entrypoint tests must execute" in bad_error
    assert good_error == ""
    assert "document['project']['scripts']['projectpulse']" in attribute_error
    assert "task_service, tmp_path" in repaired_source
    assert "subprocess.run(" in repaired_source
    assert "'projectpulse.cli:main'" in repaired_source
    assert repair["repair_kind"] == "composed_exact_goal_15_entrypoint_test_repair"


def test_combined_goal_11_goal_14_micro_gets_one_final_correction(
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "CGNK_LOCAL_COMPOSED_DIRECT_CLI_TEST_FALLBACK_ATTEMPTS", raising=False
    )
    combined_prompt = (
        "named direct CLI duplicate-identifier tests must exercise import_from; "
        "test_goal_14_cli_returns_exit_code_0_on_success_and_exit_code"
    )

    assert (
        run_local_pipeline_impl.composed_direct_cli_test_attempt_limit(
            combined_prompt, 3
        )
        == 4
    )
    assert (
        run_local_pipeline_impl.composed_direct_cli_test_attempt_limit(
            "named direct CLI duplicate-identifier tests must exercise import_from",
            3,
        )
        == 3
    )


def test_file_repair_retry_rebinds_latest_syntax_valid_rejected_module() -> None:
    target = "tests/test_projectpulse_part_02.py"
    original = "def test_goal_11_old():\n    assert False\n"
    latest = "def test_goal_11_fixed():\n    assert True\n"
    compact_prompt = json.dumps(
        {
            "target_file_contents": [{"path": target, "content": original}],
            "direct_cli_leaf_contract": {"required_symbols": []},
        }
    )
    previous_raw = json.dumps(
        {
            "component_id": "post_build",
            "files": [{"path": target, "content": latest}],
        }
    )

    rebound = json.loads(
        run_local_pipeline_impl.bind_latest_syntax_valid_rejected_target_source(
            compact_prompt, previous_raw, target
        )
    )
    syntax_invalid = json.loads(
        run_local_pipeline_impl.bind_latest_syntax_valid_rejected_target_source(
            compact_prompt,
            json.dumps({"path": target, "content": "def broken(:\n"}),
            target,
        )
    )

    assert rebound["target_file_contents"][0]["content"] == latest
    assert rebound["latest_rejected_source_rebound"] is True
    assert syntax_invalid["target_file_contents"][0]["content"] == original


def test_duplicate_import_seed_is_composed_into_next_model_prompt() -> None:
    target = "tests/test_projectpulse_part_02.py"
    source = """def test_goal_11_duplicate_task_identifiers_are_rejected_without(task_service, tmp_path):
    storage_path = task_service.repository.data_file
    before = storage_path.read_text()
    import_path = tmp_path / 'duplicates.json'
    with pytest.raises(ValueError):
        task_service.import_from(import_path, 'merge')
    assert storage_path.read_text() == before
"""
    compact_prompt = json.dumps(
        {"target_file_contents": [{"path": target, "content": source}]}
    )
    error = (
        "named direct CLI duplicate-identifier import tests must create valid "
        "pre-existing repository state with add() or save() before import_from()"
    )

    rebound = json.loads(
        run_local_pipeline_impl.bind_duplicate_import_seed_into_repair_prompt(
            compact_prompt, error, target
        )
    )
    repaired_source = rebound["target_file_contents"][0]["content"]

    assert "task_service.add('existing')" in repaired_source
    assert repaired_source.index("task_service.add('existing')") < repaired_source.index(
        "storage_path ="
    )
    assert rebound["deterministic_prompt_seed_repair"]["formal_model_participation"] is True


def test_goal_14_exact_micro_replaces_only_cli_exit_test_body() -> None:
    target = "tests/test_projectpulse_part_02.py"
    source = """import pytest
from projectpulse.service import TaskService

def test_goal_11_duplicate_task_identifiers_are_rejected_without():
    assert True

def test_goal_14_cli_returns_exit_code_0_on_success_and_exit_code(task_service, tmp_path):
    with pytest.raises(SystemExit):
        task_service.complete('missing-id')
"""
    compact_prompt = json.dumps(
        {
            "target_file_contents": [{"path": target, "content": source}],
            "highest_precedence_repair": {},
        }
    )
    error = (
        "named direct CLI goal-14 CLI exit-code tests must assert main([...]) "
        "== 0/2 or assert equivalent local variables"
    )

    repaired_prompt = json.loads(
        run_local_pipeline_impl.bind_exact_goal_14_cli_exit_repair(
            compact_prompt, error, target
        )
    )
    repair = repaired_prompt["highest_precedence_repair"]
    repaired_source = repair["exact_expected_complete_source"]

    assert "from projectpulse.cli import main" in repaired_source
    assert "def test_goal_11_duplicate_task_identifiers_are_rejected_without" in repaired_source
    assert "assert main(['--data-file', str(data_file), 'add', 'existing']) == 0" in repaired_source
    assert "assert main(['--data-file', str(data_file), 'complete', 'missing-id']) == 2" in repaired_source
    assert "task_service.complete('missing-id')" not in repaired_source
    assert repair["formal_model_participation"] is False


def test_named_direct_cli_tests_request_tmp_path_before_use() -> None:
    source = """def test_goal_11_duplicate_task_identifiers_are_rejected_without(task_service):
    duplicate_path = tmp_path / 'duplicates.json'
    task_service.import_from(duplicate_path, 'merge')
"""
    contract = {
        "test_contract": ["pytest functions"],
        "required_symbols": [
            "test_goal_11_duplicate_task_identifiers_are_rejected_without"
        ],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", source, ast.parse(source), contract
    )

    assert "request tmp_path as a function parameter" in error


def test_named_direct_cli_tests_project_versioned_data_file_tasks() -> None:
    bad = """import json
def test_storage(tmp_path):
    data_path = tmp_path / 'tasks.json'
    main(['--data-file', str(data_path), 'add', 'one'])
    with open(data_path, 'r') as handle:
        tasks = json.load(handle)
    assert len(tasks) == 1
    assert tasks[0]['title'] == 'one'
"""
    good = bad.replace(
        "tasks = json.load(handle)",
        "document = json.load(handle)\n        tasks = document['tasks']",
    )
    export_list = """import json
def test_export(tmp_path):
    data_path = tmp_path / 'tasks.json'
    export_path = tmp_path / 'export.json'
    main(['--data-file', str(data_path), 'export', str(export_path)])
    with open(export_path, 'r') as handle:
        tasks = json.load(handle)
    assert len(tasks) == 1
"""
    contract = {"test_contract": ["pytest functions"]}

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_01.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_01.py", good, ast.parse(good), contract
    )
    export_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_01.py",
        export_list,
        ast.parse(export_list),
        contract,
    )

    assert "must inspect versioned data-file tasks through document['tasks']" in error
    assert good_error == ""
    assert export_error == ""


def test_named_direct_cli_tests_enforce_bound_task_service_arities() -> None:
    bad = """import pytest
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

@pytest.fixture
def task_service(tmp_path):
    repository = JSONRepository(tmp_path / 'tasks.json')
    service = TaskService(repository)
    yield service

def test_add(task_service, tmp_path):
    task_service.add('one', str(tmp_path / 'tasks.json'))
"""
    good = bad.replace(
        "task_service.add('one', str(tmp_path / 'tasks.json'))",
        "task_service.add('one')",
    )
    contract = {
        "test_contract": ["pytest functions"],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_01.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_01.py", good, ast.parse(good), contract
    )

    assert "must call TaskService methods with exact bound argument counts" in error
    assert "invalid call add received 2" in error
    assert good_error == ""


def test_named_direct_cli_tests_reject_integer_task_id_literals() -> None:
    bad = """import pytest
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

@pytest.fixture
def task_service(tmp_path):
    service = TaskService(JSONRepository(tmp_path / 'tasks.json'))
    yield service

def test_complete(task_service):
    task_service.add('one')
    task_service.complete(1)
"""
    good = bad.replace(
        "task_service.add('one')\n    task_service.complete(1)",
        "created = task_service.add('one')\n    task_service.complete(created.id)",
    )
    contract = {
        "test_contract": ["pytest functions"],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_01.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_01.py", good, ast.parse(good), contract
    )

    assert "must pass string task identifiers to complete/delete" in error
    assert "Capture the Task returned by add()" in error
    assert good_error == ""


def test_named_direct_cli_tests_reject_returned_task_object_as_identifier() -> None:
    bad = """import pytest
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

@pytest.fixture
def task_service(tmp_path):
    service = TaskService(JSONRepository(tmp_path / 'tasks.json'))
    yield service

def test_complete(task_service):
    task_id = task_service.add('one')
    task_service.complete(task_id)
"""
    good = bad.replace("task_service.complete(task_id)", "task_service.complete(task_id.id)")
    contract = {
        "test_contract": ["pytest functions"],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_01.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_01.py", good, ast.parse(good), contract
    )

    assert "must pass the returned Task .id" in error
    assert "use task_id.id" in error
    assert good_error == ""


def test_named_direct_cli_success_tests_reject_title_as_task_identifier() -> None:
    bad = """import pytest
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

@pytest.fixture
def task_service(tmp_path):
    service = TaskService(JSONRepository(tmp_path / 'tasks.json'))
    yield service

def test_summary(task_service):
    task_service.add('Task 1')
    task_service.complete('Task 1')
"""
    good = bad.replace(
        "task_service.add('Task 1')\n    task_service.complete('Task 1')",
        "created = task_service.add('Task 1')\n    task_service.complete(created.id)",
    )
    not_found = bad.replace(
        "task_service.complete('Task 1')",
        "with pytest.raises(ValueError):\n        task_service.complete('missing')",
    )
    contract = {
        "test_contract": ["pytest functions"],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", good, ast.parse(good), contract
    )
    not_found_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", not_found, ast.parse(not_found), contract
    )

    assert "success tests must pass the Task .id returned by add()" in error
    assert "not the title or guessed string literal" in error
    assert good_error == ""
    assert not_found_error == ""


def test_named_direct_cli_tests_require_same_module_service_fixture() -> None:
    bad = """import pytest
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

def test_list(task_service, capsys):
    assert task_service.list() == []
"""
    good = bad.replace(
        "def test_list(task_service, capsys):",
        "@pytest.fixture\ndef task_service(tmp_path):\n    return TaskService(JSONRepository(tmp_path / 'tasks.json'))\n\ndef test_list(task_service):",
    )
    contract = {
        "test_contract": ["pytest functions"],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", good, ast.parse(good), contract
    )

    assert "must define service fixtures in the same module" in error
    assert "missing local fixture definitions: task_service" in error
    assert good_error == ""


def test_named_direct_cli_tests_use_attributes_for_listed_tasks() -> None:
    bad = """import pytest
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

@pytest.fixture
def task_service(tmp_path):
    return TaskService(JSONRepository(tmp_path / 'tasks.json'))

def test_list(task_service):
    task_service.add('Task 1')
    result = task_service.list()
    assert result[0]['title'] == 'Task 1'
"""
    good = bad.replace("result[0]['title']", "result[0].title")
    contract = {
        "test_contract": ["pytest functions"],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", good, ast.parse(good), contract
    )

    assert "must access Task values returned by service.list() through attributes" in error
    assert "result[0].title" in error
    assert good_error == ""


def test_named_direct_cli_service_tests_reject_capsys_output_assumptions() -> None:
    bad = """import pytest
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

@pytest.fixture
def task_service(tmp_path):
    return TaskService(JSONRepository(tmp_path / 'tasks.json'))

def test_list(task_service, capsys):
    result = task_service.list()
    captured = capsys.readouterr()
    assert result == []
    assert captured.out == '[]'
"""
    good = bad.replace(
        "def test_list(task_service, capsys):",
        "def test_list(task_service):",
    ).replace(
        "    captured = capsys.readouterr()\n",
        "",
    ).replace(
        "    assert captured.out == '[]'\n",
        "",
    )
    contract = {
        "test_contract": ["pytest functions"],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_02.py", good, ast.parse(good), contract
    )

    assert "must assert TaskService return values, not capsys output" in error
    assert good_error == ""


def test_named_direct_cli_corrupt_test_must_execute_storage_read() -> None:
    bad = """import pytest
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

def test_corrupt_storage(tmp_path):
    repository = JSONRepository(tmp_path / 'tasks.json')
    with pytest.raises(ValueError):
        service = TaskService(repository)
"""
    good = bad.replace("service = TaskService(repository)", "repository.load()")
    contract = {
        "test_contract": ["pytest functions"],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_03.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_03.py", good, ast.parse(good), contract
    )

    assert "corrupt-storage tests must execute repository.load()" in error
    assert "constructing TaskService alone" in error
    assert good_error == ""


def test_named_direct_cli_corrupt_test_rejects_invented_exact_message() -> None:
    bad = """import pytest
from projectpulse.repository import JSONRepository

def test_corrupt_storage(tmp_path):
    path = tmp_path / 'tasks.json'
    path.write_text('invalid_json', encoding='utf-8')
    repository = JSONRepository(path)
    with pytest.raises(ValueError) as excinfo:
        repository.load()
    assert str(excinfo.value) == 'Invalid JSON format'
"""
    good = bad.replace(
        "assert str(excinfo.value) == 'Invalid JSON format'",
        "assert path.read_text(encoding='utf-8') == 'invalid_json'",
    )
    contract = {
        "test_contract": ["pytest functions"],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_03.py", bad, ast.parse(bad), contract
    )
    good_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_03.py", good, ast.parse(good), contract
    )

    assert "original malformed file remains unchanged" in error
    assert "invented exact exception message" in error
    assert good_error == ""


def test_post_build_recovers_the_frozen_direct_cli_leaf_contract(
    tmp_path: pathlib.Path,
) -> None:
    phase_log = tmp_path / "run" / "provider_phase_log.jsonl"
    artifacts = phase_log.parent / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "pending_repair_plan.json").write_text(
        json.dumps(
            {
                "component_pipeline": {
                    "components": [
                        {
                            "id": "backend",
                            "required_paths": ["projectpulse/service.py"],
                            "contract_slice": {
                                "architecture_mode": "direct_cli_application"
                            },
                            "canonical_goal_spec": {
                                "domain": "local_record_cli",
                                "package_name": "projectpulse",
                                "entities": ["Task", "JSONRepository", "TaskService"],
                                "capabilities": ["add_task", "list_task"],
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    contract = post_build_repair.post_build_direct_cli_leaf_contract(
        phase_log, "projectpulse/service.py"
    )

    assert contract["required_symbols"] == ["TaskService"]
    assert "import_from(path, mode)" in " ".join(contract["api"])


def test_local_named_direct_cli_leaf_prompt_compaction_keeps_exact_authority() -> None:
    prompt = json.dumps(
        {
            "raw_user_goal": "very long project-wide narration",
            "raw_user_goal_reference": {"sha256": "goal-hash", "bounded_excerpt": "ProjectPulse"},
            "component": {"id": "backend"},
            "direct_cli_leaf_contract": {"required_symbols": ["Task"]},
            "target_file": "projectpulse/model.py",
            "leaf_interface_contract": {"contract_sha256": "interface-hash"},
            "exact_implemented_dependency_symbols": [],
            "implementation_depth_contract": {"expected_symbols": ["Task"]},
            "strict_rules": ["Generate exactly one file."],
            "unrelated_project_catalog": "x" * 10000,
        }
    )

    compact = json.loads(run_local_pipeline_impl.compact_local_direct_cli_leaf_prompt(prompt))

    assert compact["target_file"] == "projectpulse/model.py"
    assert compact["direct_cli_leaf_contract"]["required_symbols"] == ["Task"]
    assert compact["leaf_interface_contract"]["contract_sha256"] == "interface-hash"
    assert "raw_user_goal" not in compact
    assert "unrelated_project_catalog" not in compact
    assert len(json.dumps(compact)) < len(prompt) // 2


def test_direct_cli_split_test_contract_assigns_current_goal_symbols_by_part() -> None:
    goal_tests = [
        {"test_symbol": f"test_goal_{index:02d}_behavior", "intent": f"goal {index}"}
        for index in range(1, 16)
    ]
    component = {
        "id": "tests",
        "contract_slice": {"architecture_mode": "direct_cli_application"},
        "canonical_goal_spec": {
            "domain": "local_record_cli",
            "entities": ["Task", "JSONRepository", "TaskService"],
            "package_name": "projectpulse",
            "capabilities": ["add_task", "list_task"],
        },
        "goal_acceptance_tests": goal_tests,
    }

    contract = run_local_pipeline_impl.direct_cli_leaf_contract(
        component, "tests/test_projectpulse_part_02.py"
    )

    assert contract["required_symbols"] == [
        "test_goal_02_behavior",
        "test_goal_05_behavior",
        "test_goal_08_behavior",
        "test_goal_11_behavior",
        "test_goal_14_behavior",
    ]


def test_direct_cli_split_test_boundary_rejects_stale_goal_symbol_set() -> None:
    contract = {
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
        "required_symbols": ["test_goal_01_old", "test_goal_10_new"],
        "test_contract": ["pytest"],
    }
    stale = """def test_goal_01_old():
    assert True
"""
    current = stale + """
def test_goal_10_new():
    assert True
"""

    error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_01.py", stale, ast.parse(stale), contract
    )
    current_error = run_local_pipeline_impl.named_direct_cli_leaf_contract_error(
        "tests/test_projectpulse_part_01.py", current, ast.parse(current), contract
    )

    assert "must define required symbols" in error
    assert "test_goal_10_new" in error
    assert current_error == ""


def test_local_component_test_undefined_name_retry_uses_exact_micro_prompt() -> None:
    prompt = json.dumps(
        {
            "raw_user_goal_reference": "ProjectPulse CLI",
            "component": "tests",
            "target_file": "tests/test_projectpulse.py",
            "component_file_manifest": {
                "path": "tests/test_projectpulse.py",
                "expected_symbols": ["test_goal_01_add"],
            },
            "direct_cli_leaf_contract": {
                "test_contract": ["Use pytest top-level tests and tmp_path."]
            },
            "leaf_interface_contract": {
                "required_symbols": ["test_goal_01_add"]
            },
            "exact_implemented_dependency_symbols": {
                "projectpulse/service.py": ["TaskService"]
            },
            "python_local_import_contract": {
                "allowed_local_modules": ["projectpulse.service"]
            },
            "python_undefined_name_repair_contract": {
                "missing_names_exact": ["json"],
                "rule": "Add an ordinary explicit import.",
            },
            "previous_generation_error": "Python contains undefined names: json",
            "repair_acceptance": {"must_fix": "json"},
            "strict_rules": ["Return one complete file."],
            "codex_capability_supervision": {"summary": "X" * 9000},
            "librarian_context": {"excerpt": "Y" * 9000},
            "project_goal_constraints": ["Z" * 9000],
        }
    )

    compact_text = run_local_pipeline_impl.compact_local_direct_cli_leaf_prompt(prompt)
    compact = json.loads(compact_text)

    repair = compact["highest_precedence_repair"]
    assert repair["repair_kind"] == "exact_component_test_undefined_name_import"
    assert repair["exact_import_lines_to_add"] == ["import json"]
    assert compact["component_file_manifest"]["expected_symbols"] == [
        "test_goal_01_add"
    ]
    assert compact["exact_implemented_dependency_symbols"] == {
        "projectpulse/service.py": ["TaskService"]
    }
    assert "codex_capability_supervision" not in compact
    assert "librarian_context" not in compact
    assert "project_goal_constraints" not in compact
    assert len(compact_text) < 5000


def test_direct_cli_pyproject_contract_freezes_python_and_console_entry() -> None:
    component = {
        "contract_slice": {"architecture_mode": "direct_cli_application"},
        "canonical_goal_spec": {
            "domain": "local_record_cli",
            "package_name": "projectpulse",
            "entities": ["Task", "JSONRepository", "TaskService"],
            "capabilities": ["add_task"],
        },
    }

    contract = run_local_pipeline_impl.direct_cli_leaf_contract(
        component, "pyproject.toml"
    )

    api = " ".join(contract["api"])
    assert 'requires-python = \">=3.11\"' in api
    assert 'projectpulse = "projectpulse.cli:main"' in api
    assert "build-backend" in api


def test_named_direct_cli_manifest_uses_literal_pyproject_anchors() -> None:
    paths = [
        "pyproject.toml",
        "requirements.txt",
        "projectpulse/__init__.py",
    ]
    component = {
        "contract_slice": {"architecture_mode": "direct_cli_application"},
        "canonical_goal_spec": {
            "domain": "local_record_cli",
            "package_name": "projectpulse",
            "entities": ["Task", "JSONRepository", "TaskService"],
            "capabilities": ["add_task"],
        },
        "required_paths": paths,
    }

    normalized = run_local_pipeline_impl.normalize_direct_cli_manifest_contract(
        "foundation",
        [{"path": path, "expected_anchors": ["Python version requirement"]} for path in paths],
        component,
    )
    by_path = {item["path"]: item for item in normalized}

    assert by_path["pyproject.toml"]["expected_anchors"] == [
        "requires-python",
        "dependencies",
        "project.scripts",
        "build-backend",
        "tool.setuptools",
    ]
    assert "Python version requirement" not in by_path["pyproject.toml"]["expected_anchors"]
    assert by_path["requirements.txt"]["expected_anchors"] == []
    assert "Python 3.11 package metadata" in by_path["pyproject.toml"]["purpose"]


def test_local_direct_cli_pyproject_gate_rejects_missing_python_requirement() -> None:
    prompt = json.dumps(
        {
            "direct_cli_leaf_contract": {
                "api": ["requires-python = \">=3.11\""]
            }
        }
    )
    source = (
        "[project]\nname = \"projectpulse\"\nversion = \"0.1.0\"\n"
        "dependencies = []\n[project.scripts]\nprojectpulse = \"projectpulse.cli:main\"\n"
        "[build-system]\nrequires = [\"setuptools\"]\nbuild-backend = \"setuptools.build_meta\"\n"
    )

    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "pyproject.toml", "content": source},
        stage="component_file_generation",
        component="foundation",
        target_file="pyproject.toml",
        prompt_text=prompt,
    )

    assert 'requires-python = \">=3.11\"' in error


def test_direct_cli_pyproject_rejects_non_pep621_project_properties(
    tmp_path: pathlib.Path,
) -> None:
    source = (
        "[project]\nname = \"ProjectPulse\"\nversion = \"0.1.0\"\n"
        "script-name = \"projectpulse\"\nrequires-python = \">=3.11\"\n"
        "dependencies = []\n[project.scripts]\n"
        "projectpulse = \"projectpulse.cli:main\"\n[build-system]\n"
        "requires = [\"setuptools\", \"wheel\"]\n"
        "build-backend = \"setuptools.build_meta\"\n"
    )
    error = run_local_pipeline_impl.named_direct_cli_pyproject_contract_error(
        source
    )
    assert error.endswith("unsupported project properties: script-name")
    missing_package_config = source.replace(
        "script-name = \"projectpulse\"\n",
        "",
    )
    package_error = (
        run_local_pipeline_impl.named_direct_cli_pyproject_contract_error(
            missing_package_config
        )
    )
    assert '[tool.setuptools] packages = ["projectpulse"]' in package_error

    (tmp_path / "pyproject.toml").write_text(source, encoding="utf-8")
    pipeline = {
        "components": [
            {
                "id": "foundation",
                "contract_slice": {
                    "architecture_mode": "direct_cli_application"
                },
                "canonical_goal_spec": {
                    "domain": "local_record_cli",
                    "package_name": "projectpulse",
                    "interaction_modes": ["cli"],
                },
            }
        ]
    }
    issues = run_local_pipeline_impl.candidate_direct_cli_leaf_contract_issues(
        tmp_path,
        pipeline,
    )
    assert issues[0]["path"] == "pyproject.toml"
    assert "script-name" in issues[0]["message"]


def test_local_direct_cli_pyproject_fallback_corrects_one_missing_metadata_line(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    calls: list[str] = []
    invalid = (
        "[project]\nname = \"projectpulse\"\nversion = \"0.1.0\"\n"
        "requires-python = \">=3.11\"\n[project.scripts]\n"
        "projectpulse = \"projectpulse.cli:main\"\n[build-system]\n"
        "requires = [\"setuptools\"]\nbuild-backend = \"setuptools.build_meta\"\n"
        "[tool.setuptools]\npackages = [\"projectpulse\"]\n"
    )
    valid = invalid.replace(
        "requires-python = \">=3.11\"\n",
        "requires-python = \">=3.11\"\ndependencies = []\n",
    )

    def fake_call(_task, _system, prompt, _timeout):
        calls.append(prompt)
        content = invalid if len(calls) == 1 else valid
        return {
            "ok": True,
            "text": json.dumps({"path": "pyproject.toml", "content": content}),
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
        }

    monkeypatch.setenv("CGNK_LOCAL_FALLBACK_PROVIDER_ATTEMPTS", "1")
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "call_text_task_fallback",
        fake_call,
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "task_enabled",
        lambda _task: False,
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "model_routing_profile",
        lambda: "balanced",
    )
    prompt = json.dumps(
        {
            "target_file": "pyproject.toml",
            "direct_cli_leaf_contract": {
                "api": ["requires-python, dependencies, and project.scripts"]
            },
        }
    )

    raw = run_local_pipeline_impl.try_local_provider_text(
        [
            {"role": "system", "content": "Generate one exact config leaf."},
            {"role": "user", "content": prompt},
        ],
        stage="component_file_generation",
        component="foundation",
        target_file="pyproject.toml",
        timeout=30,
        phase_log_path=tmp_path / "phase.jsonl",
        force_transport_fallback=True,
    )

    assert "dependencies = []" in json.loads(raw)["content"]
    assert len(calls) == 2
    assert "literal line `dependencies = []`" in calls[1]


def test_component_leaf_retry_publishes_exact_undefined_name_guidance(monkeypatch) -> None:
    captured: list[str] = []

    def stop_after_prompt(messages, model, timeout, **kwargs):
        captured.extend(str(message.get("content", "")) for message in messages)
        raise RuntimeError("captured prompt")

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", stop_after_prompt)
    component = {
        "id": "backend",
        "contract_slice": {"architecture_mode": "direct_cli_application"},
        "canonical_goal_spec": {
            "domain": "local_record_cli",
            "package_name": "projectpulse",
            "entities": ["Task", "JSONRepository", "TaskService"],
            "capabilities": ["add_task", "list_task"],
        },
    }

    with pytest.raises(RuntimeError, match="captured prompt"):
        run_local_pipeline_impl.provider_generate_component_file(
            goal="Build ProjectPulse",
            component=component,
            component_pipeline={"components": [component]},
            manifest_entry={
                "path": "projectpulse/cli.py",
                "dependencies": [],
                "expected_symbols": ["build_parser", "main"],
            },
            prior_manifest=[],
            completed_files=[],
            repair_errors=[],
            model="test",
            timeout=30,
            phase_log_path=None,
            routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
            last_transport_error=(
                "ALL REJECTED CANDIDATE VIOLATIONS: local split-file Python contains "
                "undefined names: datetime, json, sys, uuid"
            ),
            retry_attempt=3,
        )

    prompt = "\n".join(captured)
    assert "CURRENT PYTHON UNDEFINED-NAME REPAIR" in prompt
    assert "datetime, json, sys, uuid" in prompt
    assert "import json" in prompt


def test_component_leaf_retry_publishes_small_syntax_repair_guidance(monkeypatch) -> None:
    captured: list[str] = []

    def stop_after_prompt(messages, model, timeout, **kwargs):
        captured.extend(str(message.get("content", "")) for message in messages)
        raise RuntimeError("captured prompt")

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", stop_after_prompt)
    component = {
        "id": "backend",
        "contract_slice": {"architecture_mode": "direct_cli_application"},
        "canonical_goal_spec": {
            "domain": "local_record_cli",
            "package_name": "projectpulse",
            "entities": ["Task", "JSONRepository", "TaskService"],
            "capabilities": ["add_task", "list_task"],
        },
    }

    with pytest.raises(RuntimeError, match="captured prompt"):
        run_local_pipeline_impl.provider_generate_component_file(
            goal="Build ProjectPulse",
            component=component,
            component_pipeline={"components": [component]},
            manifest_entry={
                "path": "projectpulse/cli.py",
                "dependencies": [],
                "expected_symbols": ["build_parser", "main"],
                "maximum_nonblank_lines": 110,
                "maximum_source_chars": 10000,
            },
            prior_manifest=[],
            completed_files=[],
            repair_errors=[],
            model="test",
            timeout=30,
            phase_log_path=None,
            routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
            last_transport_error="local split-file Python syntax invalid: '{' was never closed at line 41",
            retry_attempt=2,
        )

    prompt = "\n".join(captured)
    assert "CURRENT PYTHON SYNTAX REPAIR" in prompt
    assert "Avoid f-strings containing mapping lookups" in prompt
    assert "CURRENT NAMED CLI SYNTAX SHAPE" in prompt
    assert "use only a single simple variable or attribute" in prompt
    assert "no more than 110 nonblank lines" in prompt


def test_named_record_model_syntax_retry_avoids_decorator_indentation_trap(monkeypatch) -> None:
    captured: list[str] = []

    def stop_after_prompt(messages, model, timeout, **kwargs):
        captured.extend(str(message.get("content", "")) for message in messages)
        raise RuntimeError("captured prompt")

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", stop_after_prompt)
    component = {
        "id": "backend",
        "contract_slice": {"architecture_mode": "direct_cli_application"},
        "canonical_goal_spec": {
            "domain": "local_record_cli",
            "package_name": "projectpulse",
            "entities": ["Task", "JSONRepository", "TaskService"],
        },
    }

    with pytest.raises(RuntimeError, match="captured prompt"):
        run_local_pipeline_impl.provider_generate_component_file(
            goal="Build ProjectPulse",
            component=component,
            component_pipeline={"components": [component]},
            manifest_entry={"path": "projectpulse/model.py", "expected_symbols": ["Task"]},
            prior_manifest=[],
            completed_files=[],
            repair_errors=[],
            model="test",
            timeout=30,
            phase_log_path=None,
            routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
            last_transport_error="local split-file Python syntax invalid: unexpected unindent at line 21",
            retry_attempt=2,
        )

    prompt = "\n".join(captured)
    assert "CURRENT NAMED RECORD MODEL SYNTAX SHAPE" in prompt
    assert "do not use @staticmethod" in prompt
    assert "do not define from_dict" in prompt
    assert "repository.load owns" in prompt


def test_named_direct_cli_test_retry_requires_tmp_path_runtime_files(monkeypatch) -> None:
    captured: list[str] = []

    def stop_after_prompt(messages, model, timeout, **kwargs):
        captured.extend(str(message.get("content", "")) for message in messages)
        raise RuntimeError("captured prompt")

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", stop_after_prompt)
    component = {
        "id": "tests",
        "contract_slice": {"architecture_mode": "direct_cli_application"},
        "canonical_goal_spec": {
            "domain": "local_record_cli",
            "package_name": "projectpulse",
            "entities": ["Task", "JSONRepository", "TaskService"],
        },
    }

    with pytest.raises(RuntimeError, match="captured prompt"):
        run_local_pipeline_impl.provider_generate_component_file(
            goal="Build ProjectPulse",
            component=component,
            component_pipeline={"components": [component]},
            manifest_entry={"path": "tests/test_projectpulse_part_01.py", "expected_symbols": ["test_export"]},
            prior_manifest=[],
            completed_files=[],
            repair_errors=[],
            model="test",
            timeout=30,
            phase_log_path=None,
            routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
            last_transport_error=(
                "local test file references project files absent from supplied context: test_output.txt"
            ),
            retry_attempt=2,
        )

    prompt = "\n".join(captured)
    assert "CURRENT DIRECT CLI TEST PATH REPAIR" in prompt
    assert "tmp_path / 'tasks.json'" in prompt
    assert "Path('test_output.txt')" in prompt


def test_named_package_cli_manifest_sets_bounded_source_budget() -> None:
    paths = [
        "projectpulse/__main__.py",
        "projectpulse/model.py",
        "projectpulse/repository.py",
        "projectpulse/service.py",
        "projectpulse/cli.py",
    ]
    component = {
        "contract_slice": {"architecture_mode": "direct_cli_application"},
        "canonical_goal_spec": {
            "domain": "local_record_cli",
            "package_name": "projectpulse",
            "entities": ["Task", "JSONRepository", "TaskService"],
        },
        "required_paths": paths,
    }
    normalized = run_local_pipeline_impl.normalize_direct_cli_manifest_contract(
        "backend",
        [{"path": path} for path in paths],
        component,
    )
    cli_entry = next(item for item in normalized if item["path"] == "projectpulse/cli.py")
    depth = run_local_pipeline_impl.leaf_implementation_depth_contract(cli_entry)

    assert depth["maximum_nonblank_lines"] == 110
    assert depth["maximum_source_chars"] == 10000


def test_named_package_direct_cli_manifest_metadata_is_stable_across_model_wording() -> None:
    paths = [
        "projectpulse/__main__.py",
        "projectpulse/model.py",
        "projectpulse/repository.py",
        "projectpulse/service.py",
        "projectpulse/cli.py",
    ]
    component = {
        "contract_slice": {"architecture_mode": "direct_cli_application"},
        "canonical_goal_spec": {
            "domain": "local_record_cli",
            "package_name": "projectpulse",
            "entities": ["Task", "JSONRepository", "TaskService"],
            "capabilities": [
                "add_task",
                "list_task",
                "complete_task",
                "delete_task",
                "summary_task",
                "import_task",
                "export_task",
            ],
        },
        "required_paths": paths,
    }
    first = [
        {
            "path": path,
            "purpose": "first model wording",
            "responsibilities": ["invented first responsibility"],
            "acceptance_checks": ["invented first check"],
        }
        for path in paths
    ]
    second = [
        {
            "path": path,
            "purpose": "different model wording",
            "responsibilities": ["different responsibility"],
            "acceptance_checks": ["different check"],
        }
        for path in paths
    ]

    normalized_first = run_local_pipeline_impl.normalize_direct_cli_manifest_contract(
        "backend", first, component
    )
    normalized_second = run_local_pipeline_impl.normalize_direct_cli_manifest_contract(
        "backend", second, component
    )

    assert normalized_first == normalized_second
    service = next(item for item in normalized_first if item["path"] == "projectpulse/service.py")
    assert "never redefine" in service["purpose"]
    assert service["estimated_complexity"] == "high"
    assert service["submodules"] == []


def test_invalid_local_source_output_remains_retryable_leaf_contract_error(monkeypatch) -> None:
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "balanced")
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "task_enabled", lambda _task: False)
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "call_text_task_fallback",
        lambda _task, _system, _prompt, _timeout: {
            "ok": True,
            "provider": "ollama",
            "model": "test",
            "text": json.dumps(
                {
                    "path": "projectpulse/model.py",
                    "content": "def load():\n    return json.loads('{}')\n",
                }
            ),
        },
    )

    with pytest.raises(
        run_local_pipeline_impl.ProviderOutputContractError,
        match="undefined names: json",
    ):
        run_local_pipeline_impl.try_local_provider_text(
            [{"role": "user", "content": '{"target_file":"projectpulse/model.py"}'}],
            stage="component_file_generation",
            component="backend",
            target_file="projectpulse/model.py",
            timeout=30,
            phase_log_path=None,
            force_transport_fallback=True,
        )


def test_local_direct_cli_test_leaf_repairs_one_undefined_stdlib_import(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "balanced")
    monkeypatch.setenv("CGNK_LOCAL_DIRECT_CLI_TEST_FALLBACK_ATTEMPTS", "2")
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "task_enabled",
        lambda _task: False,
    )
    prompts: list[str] = []

    def fake_fallback(_task, _system, prompt, _timeout):
        prompts.append(prompt)
        content = "def test_goal_10_status():\n    assert json.loads('{}') == {}\n"
        return {
            "ok": True,
            "provider": "ollama",
            "model": "test",
            "text": json.dumps(
                {"path": "tests/test_projectpulse.py", "content": content}
            ),
        }

    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "call_text_task_fallback",
        fake_fallback,
    )
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse.py",
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "component_file_manifest": {
                "path": "tests/test_projectpulse.py",
                "expected_symbols": ["test_goal_10_status"],
            },
        }
    )

    raw = run_local_pipeline_impl.try_local_provider_text(
        [{"role": "user", "content": prompt}],
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_projectpulse.py",
        timeout=30,
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
        force_transport_fallback=True,
    )

    assert len(prompts) == 1
    assert "import json" in json.loads(raw)["content"]
    events = [json.loads(line) for line in (tmp_path / "provider_phase_log.jsonl").read_text(encoding="utf-8").splitlines()]
    repair_event = next(
        event
        for event in events
        if event.get("reason") == "local_component_test_stdlib_import_deterministic_repair"
    )
    assert repair_event["imports_added"] == ["import json"]
    assert repair_event["source_model_output_preserved"] is True
    assert repair_event["formal_model_participation"] is True


def test_pending_leaf_manifest_is_component_scoped() -> None:
    pending = {
        "stage": "component_file_generation",
        "component": "backend",
        "file_manifest": [{"path": "backend/service.py"}],
    }

    assert run_local_pipeline_impl.pending_file_manifest_for_component(
        pending,
        "backend",
    ) == [{"path": "backend/service.py"}]
    assert run_local_pipeline_impl.pending_file_manifest_for_component(
        pending,
        "frontend",
    ) is None


def test_stale_pending_leaf_cannot_resume_after_named_package_plan_changes() -> None:
    stale = {
        "stage": "component_file_generation",
        "component": "backend",
        "target_file": "backend/record_model_repository.py",
        "file_manifest": [{"path": "backend/record_model_repository.py"}],
    }
    pipeline = {
        "components": [
            {
                "id": "backend",
                "required_paths": [
                    "projectpulse/model.py",
                    "projectpulse/repository.py",
                    "projectpulse/service.py",
                    "projectpulse/cli.py",
                    "projectpulse/__main__.py",
                ],
            }
        ]
    }
    current = {
        **stale,
        "target_file": "projectpulse/model.py",
        "file_manifest": [{"path": path} for path in pipeline["components"][0]["required_paths"]],
    }

    assert run_local_pipeline_impl.pending_component_leaf_matches_pipeline(stale, pipeline) is False
    assert run_local_pipeline_impl.pending_component_leaf_matches_pipeline(current, pipeline) is True


def test_identity_bound_automatic_leaf_resumes_from_exact_expanded_manifest(
    tmp_path: pathlib.Path,
) -> None:
    component = {"id": "backend", "required_paths": ["main.py"]}
    manifest = [
        {"path": "backend/stages_part_01.py", "dependencies": []},
        {
            "path": "backend/stages_part_02.py",
            "dependencies": ["backend/artifact_store.py"],
        },
        {"path": "backend/artifact_store.py", "dependencies": []},
        {
            "path": "main.py",
            "dependencies": ["backend/stages_part_02.py"],
        },
    ]
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "backend", manifest
    )
    identity = run_local_pipeline_impl.component_leaf_resume_identity(
        component_id="backend",
        component_contract_hash=run_local_pipeline_impl.component_checkpoint_contract_hash(
            component
        ),
        component_spec_hash="frozen-spec",
        manifest=manifest,
        leaf_work_graph=graph,
        target_file="backend/stages_part_02.py",
    )
    pending = {
        "stage": "component_file_generation",
        "component": "backend",
        "target_file": "backend/stages_part_02.py",
        "file_manifest": manifest,
        "resume_identity": identity,
    }
    pipeline = {"components": [component]}

    assert run_local_pipeline_impl.pending_component_leaf_matches_pipeline(
        pending, pipeline
    ) is True
    assert (
        run_local_pipeline_impl.pending_split_checkpoint_spec_hash(
            tmp_path, pending, "backend"
        )
        == "frozen-spec"
    )


def test_identity_bound_pending_rejects_manifest_or_component_contract_tampering() -> None:
    component = {"id": "backend", "required_paths": ["main.py"]}
    manifest = [
        {"path": "backend/stages_part_01.py", "dependencies": []},
        {"path": "main.py", "dependencies": ["backend/stages_part_01.py"]},
    ]
    identity = run_local_pipeline_impl.component_leaf_resume_identity(
        component_id="backend",
        component_contract_hash=run_local_pipeline_impl.component_checkpoint_contract_hash(
            component
        ),
        component_spec_hash="frozen-spec",
        manifest=manifest,
        leaf_work_graph=run_local_pipeline_impl.build_component_leaf_work_graph(
            "backend", manifest
        ),
        target_file="backend/stages_part_01.py",
    )
    pending = {
        "stage": "component_file_generation",
        "component": "backend",
        "target_file": "backend/stages_part_01.py",
        "file_manifest": manifest,
        "resume_identity": identity,
    }

    changed_manifest = json.loads(json.dumps(pending))
    changed_manifest["file_manifest"][0]["purpose"] = "changed contract"
    assert run_local_pipeline_impl.pending_component_leaf_matches_pipeline(
        changed_manifest, {"components": [component]}
    ) is False
    assert run_local_pipeline_impl.pending_component_leaf_matches_pipeline(
        pending,
        {"components": [{"id": "backend", "required_paths": ["main.py", "other.py"]}]},
    ) is False


def test_pending_component_writer_persists_complete_shared_resume_identity(
    tmp_path: pathlib.Path,
) -> None:
    pending_path = tmp_path / "pending_repair_plan.json"
    manifest = [
        {"path": "src/repository.py", "dependencies": []},
        {
            "path": "src/service.py",
            "dependencies": ["src/repository.py"],
        },
    ]
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "backend", manifest
    )

    run_local_pipeline_impl.write_pending_component_file_generation(
        pending_path,
        raw_user_goal="Build a local application",
        component_id="backend",
        target_file="src/service.py",
        file_manifest=manifest,
        completed_files=[
            {"path": "src/repository.py", "content": "class Repository: pass\n"}
        ],
        selected_model="large-model",
        next_retry_model="large-model",
        last_transport_error="RemoteDisconnected",
        component_contract_hash="a" * 64,
        component_spec_hash="b" * 64,
        leaf_work_graph=graph,
    )
    pending = json.loads(pending_path.read_text(encoding="utf-8"))

    assert pending["resume_identity"] == {
        "component_id": "backend",
        "component_contract_sha256": "a" * 64,
        "component_spec_sha256": "b" * 64,
        "file_manifest_sha256": run_local_pipeline_impl.component_file_manifest_hash(
            manifest
        ),
        "leaf_work_graph_sha256": graph["graph_sha256"],
        "target_file": "src/service.py",
        "target_manifest_entry_sha256": run_local_pipeline_impl.split_file_manifest_entry_hash(
            manifest[1]
        ),
    }


def test_pending_leaf_target_is_excluded_from_cache_without_provider_actions() -> None:
    pending = {
        "stage": "component_file_generation",
        "component": "frontend",
        "target_file": "src/app.js",
        "file_manifest": [
            {"path": "index.html"},
            {"path": "src/styles.css"},
            {"path": "src/app.js"},
        ],
        "provider_actions": [],
    }

    assert run_local_pipeline_impl.repair_target_files_for_component(
        pending,
        "frontend",
    ) == ["src/app.js"]
    assert run_local_pipeline_impl.repair_target_files_for_component(
        pending,
        "backend",
    ) == []


def test_wrapped_component_leaf_resume_plan_keeps_leaf_stage_authoritative(
    tmp_path: pathlib.Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    pending = {
        "stage": "provider_semantic_repair",
        "selected_model": "review-model",
        "repair_plan": {
            "stage": "component_file_generation",
            "component": "frontend",
            "target_file": "src/app_part_02.js",
            "payload_mode": "file_manifest",
            "file_manifest": [
                {"path": "index.html"},
                {"path": "src/app_part_02.js"},
                {"path": "src/app.js"},
            ],
            "completed_files": [{"path": "index.html", "content": "<main></main>"}],
            "remaining_files": ["src/app_part_02.js", "src/app.js"],
        },
    }
    (artifacts / "pending_repair_plan.json").write_text(
        json.dumps(pending),
        encoding="utf-8",
    )

    loaded = run_local_pipeline_impl.load_pending_repair_plan(tmp_path)

    assert loaded["stage"] == "component_file_generation"
    assert loaded["component"] == "frontend"
    assert loaded["target_file"] == "src/app_part_02.js"
    assert loaded["payload_mode"] == "file_manifest"
    assert loaded["file_manifest"] == pending["repair_plan"]["file_manifest"]
    assert loaded["completed_files"] == pending["repair_plan"]["completed_files"]
    assert loaded["remaining_files"] == pending["repair_plan"]["remaining_files"]
    assert loaded["selected_model"] == "review-model"


def test_pending_split_checkpoint_restores_exact_same_run_spec_identity(
    tmp_path: pathlib.Path,
) -> None:
    manifest_entry = {
        "path": "src/app_part_01.js",
        "purpose": "bounded frontend state",
        "dependencies": ["index.html"],
    }
    run_local_pipeline_impl.write_split_file_checkpoint(
        tmp_path,
        component_id="frontend",
        spec_hash="original-spec",
        file_item={
            "path": "src/app_part_01.js",
            "content": "export const state = {};\n",
        },
        manifest_entry=manifest_entry,
    )
    pending = {
        "stage": "component_file_generation",
        "component": "frontend",
        "file_manifest": [manifest_entry],
        "completed_files": ["src/app_part_01.js"],
    }

    restored = run_local_pipeline_impl.pending_split_checkpoint_spec_hash(
        tmp_path,
        pending,
        "frontend",
    )

    assert restored == "original-spec"
    assert (
        run_local_pipeline_impl.pending_split_checkpoint_spec_hash(
            tmp_path,
            pending,
            "backend",
        )
        == ""
    )


def test_same_run_upstream_checkpoint_may_ignore_replanning_hash(
    tmp_path: pathlib.Path,
) -> None:
    run_local_pipeline_impl.write_provider_component_checkpoint(
        tmp_path,
        component_id="foundation",
        spec_hash="original-spec",
        status="pass",
        raw_output="{}",
        parsed_result={"component_id": "foundation"},
        files=[{"path": "requirements.txt", "content": "# standard library only\n"}],
        semantic_review={"status": "pass"},
    )

    strict = run_local_pipeline_impl.load_provider_component_checkpoint(
        tmp_path,
        component_id="foundation",
        spec_hash="replanned-spec",
    )
    resumed = run_local_pipeline_impl.load_provider_component_checkpoint(
        tmp_path,
        component_id="foundation",
        spec_hash="replanned-spec",
        allow_spec_mismatch=True,
    )

    assert strict is None
    assert resumed is not None
    assert resumed[1] == [
        {"path": "requirements.txt", "content": "# standard library only\n"}
    ]


def test_same_goal_leaf_resume_ignores_only_spec_hash_not_manifest_contract(
    tmp_path: pathlib.Path,
) -> None:
    entry = {
        "path": "index.html",
        "purpose": "render the approved studio shell",
        "expected_symbols": [],
    }
    run_local_pipeline_impl.write_split_file_checkpoint(
        tmp_path,
        component_id="frontend",
        spec_hash="approved-spec",
        file_item={"path": "index.html", "content": "<main><h1>Studio</h1></main>\n"},
        manifest_entry=entry,
    )

    strict = run_local_pipeline_impl.load_split_file_checkpoint(
        tmp_path,
        component_id="frontend",
        spec_hash="replanned-spec",
        path_value="index.html",
        manifest_entry=entry,
    )
    resumed = run_local_pipeline_impl.load_split_file_checkpoint(
        tmp_path,
        component_id="frontend",
        spec_hash="replanned-spec",
        path_value="index.html",
        manifest_entry=entry,
        allow_spec_mismatch=True,
    )
    changed_contract = run_local_pipeline_impl.load_split_file_checkpoint(
        tmp_path,
        component_id="frontend",
        spec_hash="replanned-spec",
        path_value="index.html",
        manifest_entry={**entry, "purpose": "a different contract"},
        allow_spec_mismatch=True,
    )

    assert strict is None
    assert resumed == {"path": "index.html", "content": "<main><h1>Studio</h1></main>\n"}
    assert changed_contract is None


def test_same_goal_semantic_resume_does_not_reuse_legacy_checkpoint_across_replanning_hash(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    goal = "Build a visual novel studio."
    foundation = {"id": "foundation", "required_paths": ["requirements.txt"]}
    frontend = {"id": "frontend", "required_paths": ["index.html"]}
    pipeline = {
        "components": [foundation, frontend],
        "merge_policy": {"required_final_files": ["requirements.txt", "index.html"]},
    }
    checkpoint_dir = tmp_path / "provider_components"
    run_local_pipeline_impl.write_provider_component_checkpoint(
        checkpoint_dir,
        component_id="foundation",
        spec_hash="approved-but-replanned-spec",
        status="pass",
        raw_output="{}",
        parsed_result={"component_id": "foundation"},
        files=[{"path": "requirements.txt", "content": "# standard library only\n"}],
        semantic_review={"status": "pass"},
    )
    calls: list[str] = []

    def stop_at_forced_component(**kwargs):
        calls.append(str(kwargs.get("component", {}).get("id", "")))
        raise RuntimeError("forced frontend probe")

    monkeypatch.setattr(run_local_pipeline_impl, "provider_transport_repair_attempts", lambda: 1)
    monkeypatch.setattr(run_local_pipeline_impl, "should_split_component_generation", lambda *args, **kwargs: (False, ""))
    monkeypatch.setattr(run_local_pipeline_impl, "provider_generate_project_component", stop_at_forced_component)

    with pytest.raises(RuntimeError, match="forced frontend probe"):
        run_local_pipeline_impl.provider_generate_project_by_components(
            goal,
            pipeline,
            {},
            {},
            {},
            {},
            [],
            "gpt-test",
            30,
            checkpoint_dir=checkpoint_dir,
            run_dir=tmp_path,
            force_components={"frontend"},
            pending_repair_plan={
                "stage": "provider_semantic_repair",
                "raw_user_goal": goal,
                "provider_actions": [
                    {
                        "component": "frontend",
                        "path": "index.html",
                        "instruction": "repair frontend only",
                    }
                ],
            },
        )

    assert calls == ["foundation"]


def test_same_goal_resume_invalidates_upstream_checkpoint_missing_current_required_path(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    goal = "Build a multi-stage visual novel studio."
    backend = {
        "id": "backend",
        "required_paths": ["main.py", "backend/stages.py", "backend/orchestrator.py"],
    }
    tests_component = {"id": "tests", "required_paths": []}
    pipeline = {
        "components": [backend, tests_component],
        "merge_policy": {"required_final_files": ["main.py", "backend/stages.py", "backend/orchestrator.py"]},
    }
    checkpoint_dir = tmp_path / "provider_components"
    run_local_pipeline_impl.write_provider_component_checkpoint(
        checkpoint_dir,
        component_id="backend",
        spec_hash="old-small-spec",
        status="pass",
        raw_output="{}",
        parsed_result={"component_id": "backend"},
        files=[{"path": "main.py", "content": "def main():\n    return 0\n"}],
        semantic_review={"status": "pass"},
    )
    calls: list[str] = []

    def stop_on_invalidated_backend(**kwargs):
        calls.append(str(kwargs.get("component", {}).get("id", "")))
        raise RuntimeError("missing-path checkpoint was invalidated")

    monkeypatch.setattr(run_local_pipeline_impl, "provider_transport_repair_attempts", lambda: 1)
    monkeypatch.setattr(run_local_pipeline_impl, "should_split_component_generation", lambda *_a, **_k: (False, ""))
    monkeypatch.setattr(run_local_pipeline_impl, "provider_generate_project_component", stop_on_invalidated_backend)

    with pytest.raises(RuntimeError, match="missing-path checkpoint was invalidated"):
        run_local_pipeline_impl.provider_generate_project_by_components(
            goal,
            pipeline,
            {},
            {},
            {},
            {},
            [],
            "gpt-test",
            30,
            checkpoint_dir=checkpoint_dir,
            run_dir=tmp_path,
            pending_repair_plan={
                "stage": "component_file_generation",
                "component": "tests",
                "target_file": "tests/test_app.py",
                "raw_user_goal": goal,
            },
        )

    assert calls == ["backend"]
    phase_log = (tmp_path / "provider_phase_log.jsonl").read_text(encoding="utf-8")
    assert "component_checkpoint_contract_invalidated" in phase_log
    assert "backend/stages.py" in phase_log
    assert "backend/orchestrator.py" in phase_log


def test_cached_component_is_revalidated_before_reuse(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    component = {"id": "frontend", "required_paths": ["src/app.js"]}
    pipeline = {"components": [component], "merge_policy": {"required_final_files": []}}
    snapshot = run_local_pipeline_impl.build_integration_feedforward_snapshot(
        goal="Build a browser module.",
        component=component,
        component_pipeline=pipeline,
        plan_doc={},
        prior_component_results=[],
        prior_files=[],
        repair_errors=[],
    )
    spec_hash = run_local_pipeline_impl.provider_component_spec_hash(
        "Build a browser module.",
        pipeline,
        component,
        run_local_pipeline_impl.integration_feedforward_checkpoint_hash(snapshot),
    )
    checkpoint_dir = tmp_path / "provider_components"
    broken_files = [
        {
            "path": "src/app.js",
            "content": "export { missing };\n",
        }
    ]
    run_local_pipeline_impl.write_provider_component_checkpoint(
        checkpoint_dir,
        component_id="frontend",
        spec_hash=spec_hash,
        status="pass",
        raw_output='{"component_id":"frontend"}',
        parsed_result={"component_id": "frontend", "files": broken_files},
        files=broken_files,
        semantic_review={"status": "pass"},
    )
    calls: list[dict] = []

    def valid_component(**kwargs):
        calls.append(kwargs)
        files = [
            {"path": "src/value.js", "content": "export const value = 1;\n"},
            {
                "path": "src/app.js",
                "content": "import { value } from './value.js';\nexport { value };\n",
            },
        ]
        return {
            "component_id": "frontend",
            "summary": "validated replacement",
            "files": files,
            "quality_gate": {"status": "pass"},
            "self_test": {"status": "pass", "checks": []},
        }

    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_transport_repair_attempts",
        lambda: 1,
    )
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "should_split_component_generation",
        lambda *args, **kwargs: (False, ""),
    )
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_generate_project_component",
        valid_component,
    )

    result = run_local_pipeline_impl.provider_generate_project_by_components(
        "Build a browser module.",
        pipeline,
        {},
        {},
        {},
        {},
        [],
        "gpt-test",
        30,
        checkpoint_dir=checkpoint_dir,
        run_dir=tmp_path,
    )

    assert len(calls) == 1
    assert result["module_quality_validation"]["status"] == "pass"
    assert result["cross_validation_feedforward_receipt"]["status"] == "pass"
    assert result["components"][0]["cross_validation_feedforward_receipt"]["status"] == "pass"
    assert (
        tmp_path
        / "artifacts"
        / "cross_validation_feedforward"
        / "components"
        / "frontend.json"
    ).exists()
    assert (
        tmp_path / "artifacts" / "cross_validation_feedforward" / "assembled_project.json"
    ).exists()
    assert any(
        "cached component quality validation failed"
        in message
        for message in result["component_errors"]["frontend"]
    )


def test_same_run_manifest_is_recovered_from_exact_leaf_checkpoints(
    tmp_path: pathlib.Path,
) -> None:
    entries = [
        {"path": "tests/test_core.py", "purpose": "core tests"},
        {
            "path": "tests/test_integration.py",
            "purpose": "integration tests",
            "dependencies": ["tests/test_core.py"],
        },
    ]
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "tests",
        entries,
    )
    run_local_pipeline_impl.write_json(
        tmp_path / "leaf_work_graphs" / "tests.json",
        {"spec_hash": "old-spec", **graph},
    )
    for entry in entries:
        run_local_pipeline_impl.write_split_file_checkpoint(
            tmp_path,
            component_id="tests",
            spec_hash="old-spec",
            file_item={
                "path": entry["path"],
                "content": "def test_contract():\n    assert 1 == 1\n",
            },
            manifest_entry=entry,
        )

    recovered = (
        run_local_pipeline_impl.recover_component_manifest_from_split_checkpoints(
            tmp_path,
            "tests",
        )
    )

    assert recovered == entries
    assert (
        run_local_pipeline_impl.recover_component_manifest_from_split_checkpoints(
            tmp_path,
            "docs",
        )
        is None
    )


def test_recovered_manifest_must_cover_current_component_required_paths() -> None:
    component = {
        "id": "backend",
        "required_paths": ["main.py", "backend/stages.py", "backend/orchestrator.py"],
    }
    old_manifest = [
        {"path": "main.py"},
        {"path": "backend/story_graph.py"},
    ]

    missing = run_local_pipeline_impl.component_manifest_missing_required_paths(
        "backend",
        component,
        old_manifest,
    )

    assert missing == ["backend/stages.py", "backend/orchestrator.py"]


def test_test_manifest_dependencies_are_bound_to_existing_upstream_interfaces() -> None:
    manifest = [
        {"path": "tests/test_app.py", "purpose": "test app startup", "dependencies": []},
        {
            "path": "tests/test_pipeline_unit.py",
            "purpose": "test pipeline stages",
            "dependencies": [],
            "expected_symbols": ["Stage", "test_stage_contract"],
        },
        {"path": "tests/test_artifact_contracts.py", "purpose": "test artifacts", "dependencies": []},
        {"path": "tests/test_cancel_resume.py", "purpose": "test cancel and resume", "dependencies": []},
        {"path": "tests/test_degraded_mode.py", "purpose": "test degraded mode", "dependencies": []},
    ]
    prior = [
        "main.py",
        "backend/stages.py",
        "backend/orchestrator.py",
        "backend/artifact_store.py",
        "backend/adapters.py",
        "backend/image_adapters.py",
    ]

    normalized = run_local_pipeline_impl.normalize_test_manifest_dependency_contract(
        manifest,
        prior,
    )
    by_path = {item["path"]: item["dependencies"] for item in normalized}

    assert by_path["tests/test_app.py"] == ["main.py"]
    assert by_path["tests/test_pipeline_unit.py"] == [
        "backend/stages.py",
        "backend/orchestrator.py",
    ]
    assert by_path["tests/test_artifact_contracts.py"] == ["backend/artifact_store.py"]
    assert by_path["tests/test_cancel_resume.py"] == ["backend/orchestrator.py"]
    assert by_path["tests/test_degraded_mode.py"] == [
        "backend/adapters.py",
        "backend/image_adapters.py",
    ]
    assert all(dependency in prior for dependencies in by_path.values() for dependency in dependencies)
    by_entry = {item["path"]: item for item in normalized}
    assert by_entry["tests/test_pipeline_unit.py"]["expected_symbols"] == [
        "test_stage_contract"
    ]


def test_required_pipeline_stages_expand_generic_stages_leaf() -> None:
    manifest = [
        {
            "path": "backend/stages.py",
            "purpose": "dispatch every required pipeline stage",
            "estimated_complexity": "medium",
            "expected_symbols": ["STAGE_DEFS", "run_stage"],
            "responsibilities": ["execute the reviewed stage contract"],
            "acceptance_checks": ["all required stages are importable"],
        },
        {
            "path": "backend/orchestrator.py",
            "purpose": "coordinate the reviewed stage graph",
            "estimated_complexity": "medium",
            "expected_symbols": ["Orchestrator"],
            "responsibilities": [],
            "acceptance_checks": [],
        },
    ]
    stages = [
        "research_platform_sources",
        "acquire_authorized_input",
        "validate_input",
        "parse_evidence",
        "normalize_evidence",
        "extract_features",
        "score_review_risk",
        "render_evidence_report",
    ]

    expanded = run_local_pipeline_impl.expand_component_manifest_submodules(
        "backend",
        manifest,
        required_pipeline_stages=stages,
    )

    facade = next(item for item in expanded if item["path"] == "backend/stages.py")
    orchestrator = next(item for item in expanded if item["path"] == "backend/orchestrator.py")
    children = [item for item in expanded if item.get("generation_role") == "bounded_submodule"]
    child_symbols = [symbol for child in children for symbol in child["expected_symbols"]]
    assert facade["generation_role"] == "compatibility_facade"
    assert facade["estimated_complexity"] == "low"
    assert orchestrator["estimated_complexity"] == "medium"
    assert orchestrator["expected_symbols"] == ["ProjectOrchestrator"]
    assert any("Execute the frozen pipeline stages in order" in item for item in orchestrator["responsibilities"])
    assert len(children) == 5
    assert all(stage in child_symbols for stage in stages)
    assert "run_stage" in child_symbols


def test_split_leaf_generation_orders_dependencies_and_repairs_interface_mismatch(monkeypatch) -> None:
    generated_targets: list[str] = []
    service_payloads: list[dict[str, object]] = []

    def fake_provider_text(messages, *_args, **kwargs):
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps(
                {
                    "component": "backend",
                    "files": [
                        {
                            "path": "backend/service.py",
                            "purpose": "consumer",
                            "dependencies": ["backend/model.py"],
                        },
                        {
                            "path": "backend/model.py",
                            "purpose": "contract",
                            "dependencies": [],
                        },
                    ],
                }
            )
        target = str(kwargs.get("target_file"))
        generated_targets.append(target)
        payload = json.loads(messages[-1]["content"])
        if target == "backend/model.py":
            return json.dumps(
                {
                    "path": target,
                    "content": "class Job:\n    def run(self):\n        return True\n",
                }
            )
        service_payloads.append(payload)
        method = "resume" if len(service_payloads) == 1 else "run"
        return json.dumps(
            {
                "path": target,
                "content": (
                    "from backend.model import Job\n"
                    "job = Job()\n"
                    f"job.{method}()\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    monkeypatch.setenv("CGKN_PROVIDER_RETRY_FAST", "1")
    monkeypatch.setenv("CGNK_PROVIDER_REPAIR_TRANSPORT_ATTEMPTS", "2")
    result = run_local_pipeline_impl.provider_generate_project_component_split(
        goal="build a backend",
        component={
            "id": "backend",
            "required_paths": ["backend/model.py", "backend/service.py"],
        },
        component_pipeline={"components": [{"id": "backend"}]},
        prior_manifest=[],
        repair_errors=[],
        model="test-model",
        timeout=10,
        deadline=None,
        checkpoint_dir=None,
        run_dir=None,
        spec_hash="spec",
        phase_log_path=None,
        routing_policy=None,
        split_reason="test",
        original_prompt_chars=50000,
    )

    assert generated_targets == [
        "backend/model.py",
        "backend/service.py",
        "backend/service.py",
    ]
    assert [path for leaf in result["leaf_work_graph"]["leaves"] for path in leaf["paths"]] == [
        "backend/model.py",
        "backend/service.py",
    ]
    catalog = service_payloads[0]["leaf_interface_contract"]["authoritative_interface_catalog"]
    assert catalog[0]["python"]["classes"][0]["name"] == "Job"
    assert "missing Job.resume" in str(service_payloads[1]["previous_generation_error"])


def test_twelve_leaf_chain_keeps_interfaces_ordered_bounded_and_checkpointed(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    paths = [f"backend/layer_{index:02d}.py" for index in range(12)]
    manifest = [
        {
            "path": path,
            "purpose": f"layer {index}",
            "dependencies": [paths[index - 1]] if index else [],
        }
        for index, path in reversed(list(enumerate(paths)))
    ]
    generated_targets: list[str] = []
    payloads_by_target: dict[str, list[dict[str, object]]] = {}
    attempts_by_target: dict[str, int] = {}

    def fake_provider_text(messages, *_args, **kwargs):
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps({"component": "backend", "files": manifest})
        target = str(kwargs.get("target_file"))
        generated_targets.append(target)
        payload = json.loads(messages[-1]["content"])
        payloads_by_target.setdefault(target, []).append(payload)
        attempts_by_target[target] = attempts_by_target.get(target, 0) + 1
        index = int(pathlib.PurePosixPath(target).stem.rsplit("_", 1)[-1])
        class_name = f"Layer{index:02d}"
        if index == 0:
            content = (
                f"class {class_name}:\n"
                "    def run(self):\n"
                "        return 0\n"
            )
        else:
            previous_class = f"Layer{index - 1:02d}"
            method = "missing" if index == 6 and attempts_by_target[target] == 1 else "run"
            content = (
                f"from backend.layer_{index - 1:02d} import {previous_class}\n"
                f"class {class_name}:\n"
                "    def __init__(self):\n"
                f"        self.upstream = {previous_class}()\n"
                "    def run(self):\n"
                f"        return self.upstream.{method}()\n"
            )
        return json.dumps({"path": target, "content": content})

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    monkeypatch.setenv("CGKN_PROVIDER_RETRY_FAST", "1")
    monkeypatch.setenv("CGNK_PROVIDER_REPAIR_TRANSPORT_ATTEMPTS", "2")
    checkpoint_dir = tmp_path / "run" / "artifacts" / "provider_components"
    phase_log = tmp_path / "run" / "provider_phase_log.jsonl"
    result = run_local_pipeline_impl.provider_generate_project_component_split(
        goal="build a twelve layer backend",
        component={"id": "backend", "required_paths": paths},
        component_pipeline={"components": [{"id": "backend"}]},
        prior_manifest=[],
        repair_errors=[],
        model="test-model",
        timeout=30,
        deadline=None,
        checkpoint_dir=checkpoint_dir,
        run_dir=tmp_path / "run",
        spec_hash="twelve-leaf-spec",
        phase_log_path=phase_log,
        routing_policy=None,
        split_reason="scale_test",
        original_prompt_chars=90000,
    )

    assert [path for leaf in result["leaf_work_graph"]["leaves"] for path in leaf["paths"]] == paths
    assert [item["path"] for item in result["files"]] == paths
    assert generated_targets == [*paths[:7], paths[6], *paths[7:]]
    assert attempts_by_target[paths[6]] == 2
    assert "missing Layer05.missing" in str(
        payloads_by_target[paths[6]][1]["previous_generation_error"]
    )
    final_contract = payloads_by_target[paths[-1]][0]["leaf_interface_contract"]
    assert final_contract["resolved_dependency_paths"] == [paths[-2]]
    assert final_contract["authoritative_interface_catalog"][0]["path"] == paths[-2]
    assert len(final_contract["authoritative_interface_catalog"]) <= 24
    graph_artifact = run_local_pipeline_impl.load_json(
        checkpoint_dir / "leaf_work_graphs" / "backend.json"
    )
    assert graph_artifact["spec_hash"] == "twelve-leaf-spec"
    assert graph_artifact["leaf_count"] == 12
    events = [
        json.loads(line)
        for line in phase_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len([event for event in events if event.get("event") == "component_leaf_completed"]) == 12


def test_leaf_chain_resumes_from_middle_without_regenerating_passed_leaves(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    paths = [f"backend/resume_{index:02d}.py" for index in range(8)]
    manifest = [
        {
            "path": path,
            "purpose": f"resume layer {index}",
            "dependencies": [paths[index - 1]] if index else [],
        }
        for index, path in enumerate(paths)
    ]
    first_run_targets: list[str] = []

    def content_for(target: str) -> str:
        index = int(pathlib.PurePosixPath(target).stem.rsplit("_", 1)[-1])
        class_name = f"Resume{index:02d}"
        if index == 0:
            return f"class {class_name}:\n    def run(self):\n        return 0\n"
        previous_class = f"Resume{index - 1:02d}"
        return (
            f"from backend.resume_{index - 1:02d} import {previous_class}\n"
            f"class {class_name}:\n"
            "    def __init__(self):\n"
            f"        self.upstream = {previous_class}()\n"
            "    def run(self):\n"
            "        return self.upstream.run()\n"
        )

    def interrupted_provider_text(messages, *_args, **kwargs):
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps({"component": "backend", "files": manifest})
        target = str(kwargs.get("target_file"))
        first_run_targets.append(target)
        if target == paths[5]:
            raise RuntimeError(
                "provider_api_request_failed: HTTP 504: timeout [retryable=true]"
            )
        return json.dumps({"path": target, "content": content_for(target)})

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", interrupted_provider_text)
    monkeypatch.setenv("CGNK_PROVIDER_REPAIR_TRANSPORT_ATTEMPTS", "1")
    checkpoint_dir = tmp_path / "run" / "artifacts" / "provider_components"
    run_dir = tmp_path / "run"
    with pytest.raises(RuntimeError, match="component backend generation failed"):
        run_local_pipeline_impl.provider_generate_project_component_split(
            goal="build resumable layers",
            component={"id": "backend", "required_paths": paths},
            component_pipeline={"components": [{"id": "backend"}]},
            prior_manifest=[],
            repair_errors=[],
            model="test-model",
            timeout=30,
            deadline=None,
            checkpoint_dir=checkpoint_dir,
            run_dir=run_dir,
            spec_hash="resume-spec",
            phase_log_path=run_dir / "provider_phase_log.jsonl",
            routing_policy=None,
            split_reason="resume_test",
            original_prompt_chars=70000,
        )

    pending = run_local_pipeline_impl.load_json(
        run_dir / "artifacts" / "pending_repair_plan.json"
    )
    assert first_run_targets == paths[:6]
    assert pending["target_file"] == paths[5]
    assert pending["completed_files"] == paths[:5]
    assert pending["remaining_files"] == paths[5:]

    resumed_targets: list[str] = []
    resumed_payloads: dict[str, dict[str, object]] = {}

    def resumed_provider_text(messages, *_args, **kwargs):
        assert kwargs.get("stage") != "component_file_manifest"
        target = str(kwargs.get("target_file"))
        resumed_targets.append(target)
        resumed_payloads[target] = json.loads(messages[-1]["content"])
        return json.dumps({"path": target, "content": content_for(target)})

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", resumed_provider_text)
    result = run_local_pipeline_impl.provider_generate_project_component_split(
        goal="build resumable layers",
        component={"id": "backend", "required_paths": paths},
        component_pipeline={"components": [{"id": "backend"}]},
        prior_manifest=[],
        repair_errors=[],
        model="test-model",
        timeout=30,
        deadline=None,
        checkpoint_dir=checkpoint_dir,
        run_dir=run_dir,
        spec_hash="resume-spec",
        phase_log_path=run_dir / "provider_phase_log.jsonl",
        routing_policy=None,
        split_reason="pending_component_file_generation",
        original_prompt_chars=70000,
        pending_context=pending,
    )

    assert resumed_targets == paths[5:]
    assert [item["path"] for item in result["files"]] == paths
    resumed_contract = resumed_payloads[paths[5]]["leaf_interface_contract"]
    assert resumed_contract["resolved_dependency_paths"] == [paths[4]]
    assert resumed_contract["authoritative_interface_catalog"][0]["path"] == paths[4]


def test_leaf_interface_prompt_stays_bounded_with_forty_completed_modules(
    monkeypatch,
) -> None:
    completed_files = [
        {
            "path": f"backend/module_{index:02d}.py",
            "content": (
                f"class Module{index:02d}:\n"
                "    def run(self):\n"
                f"        return {index}\n"
                + ("# implementation detail\n" * 300)
            ),
        }
        for index in range(40)
    ]
    leaf = {
        "leaf_id": "backend.leaf.041",
        "path": "backend/consumer.py",
        "depends_on": ["backend/module_00.py"],
        "declared_dependencies": ["backend/module_00.py"],
    }
    contract = run_local_pipeline_impl.build_leaf_interface_contract(
        component_id="backend",
        leaf=leaf,
        completed_files=completed_files,
        prior_files=[],
        integration_feedforward={},
    )
    captured: dict[str, object] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured["prompt_chars"] = sum(len(message.get("content", "")) for message in messages)
        captured["payload"] = json.loads(messages[-1]["content"])
        return json.dumps(
            {
                "path": "backend/consumer.py",
                "content": "READY = True\n",
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    item, _raw = run_local_pipeline_impl.provider_generate_component_file(
        goal="build a large modular backend",
                component={"id": "backend", "required_paths": ["backend/stages.py"]},
        component_pipeline={"components": [{"id": "backend"}]},
        manifest_entry={
            "path": "backend/consumer.py",
            "purpose": "bounded consumer",
            "dependencies": ["backend/module_00.py"],
        },
        prior_manifest=[],
        completed_files=completed_files,
        prior_files=[],
        component_file_manifest=[
            *[{"path": file_item["path"]} for file_item in completed_files],
            {"path": "backend/consumer.py"},
        ],
        repair_errors=[],
        leaf_interface_contract=contract,
        model="test-model",
        timeout=30,
        phase_log_path=None,
        routing_policy=None,
    )

    assert item["path"] == "backend/consumer.py"
    assert int(captured["prompt_chars"]) < 40000
    payload_contract = captured["payload"]["leaf_interface_contract"]
    assert len(payload_contract["authoritative_interface_catalog"]) <= 24
    assert payload_contract["authoritative_interface_catalog"][0]["path"] == "backend/module_00.py"
    librarian_context = captured["payload"]["librarian_context"]
    assert librarian_context["kind"] == "CGKNLibrarianContextPack"
    assert librarian_context["context_budget"]["selected_chars"] <= 8000
    assert "backend/module_00.py" in [
        item["path"] for item in librarian_context["selected_items"]
    ]
    assert "completed_component_files" not in captured["payload"]


def test_python_leaf_without_declared_dependencies_receives_empty_local_import_contract(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    captured_system: dict[str, str] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured_system["content"] = messages[0]["content"]
        captured.update(json.loads(messages[-1]["content"]))
        return json.dumps(
            {
                "path": "main.py",
                "content": (
                    "from flask import Flask\n\n"
                    "app = Flask(__name__)\n\n"
                    "@app.get('/')\n"
                    "def index():\n"
                    "    return {'status': 'ready'}\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    item, _raw = run_local_pipeline_impl.provider_generate_component_file(
        goal="build a local studio",
        component={"id": "backend"},
        component_pipeline={"components": [{"id": "backend"}]},
        manifest_entry={
            "path": "main.py",
            "estimated_complexity": "low",
            "responsibilities": ["expose the application entrypoint"],
            "expected_symbols": ["app"],
            "dependencies": [],
        },
        prior_manifest=[],
        completed_files=[
            {
                "path": "backend/preview.py",
                "content": "class PreviewGenerator:\n    pass\n",
            }
        ],
        component_file_manifest=[
            {"path": "backend/preview.py"},
            {"path": "main.py"},
        ],
        repair_errors=[],
        model="local",
        timeout=10,
        phase_log_path=None,
        routing_policy=None,
    )

    assert captured["python_local_import_contract"]["allowed_project_local_imports"] == []
    assert "CURRENT PYTHON LOCAL IMPORT CONTRACT (highest precedence)" in captured_system["content"]
    assert "Librarian source excerpts are context, not import permission" in captured_system["content"]
    assert item["path"] == "main.py"


def test_independent_leaves_run_in_parallel_and_publish_receipts(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    paths = [f"backend/parallel_{index}.py" for index in range(4)]
    lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_provider_text(_messages, *_args, **kwargs):
        nonlocal active, max_active
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps(
                {
                    "component": "backend",
                    "files": [
                        {
                            "path": path,
                            "purpose": "independent",
                            "dependencies": [],
                            "estimated_complexity": "low",
                            "expected_output_chars": 15000,
                        }
                        for path in paths
                    ],
                }
            )
        target = str(kwargs.get("target_file"))
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return json.dumps(
            {
                "path": target,
                "content": "READY = True\nNAME = 'parallel'\nCOUNT = 1\nENABLED = True\n",
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    monkeypatch.setenv("CGKN_PROVIDER_LEAF_MAX_WORKERS", "3")
    checkpoint_dir = tmp_path / "provider_components"
    result = run_local_pipeline_impl.provider_generate_project_component_split(
        goal="build parallel backend leaves",
        component={"id": "backend", "required_paths": paths},
        component_pipeline={"components": [{"id": "backend"}]},
        prior_manifest=[],
        repair_errors=[],
        model="test-model",
        timeout=30,
        deadline=None,
        checkpoint_dir=checkpoint_dir,
        run_dir=tmp_path,
        spec_hash="parallel-spec",
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
        routing_policy=None,
        split_reason="parallel_test",
        original_prompt_chars=80000,
    )

    assert max_active >= 2
    assert result["parallel_batches"] == [paths]
    assert [item["path"] for item in result["files"]] == paths
    assert all(receipt["status"] == "PASS" for receipt in result["boundary_check_receipts"])
    assert result["interface_registry"]["provider_count"] == 4
    assert (
        checkpoint_dir / "interface_registries" / "backend.json"
    ).exists()
    assert len(list((checkpoint_dir / "boundary_receipts" / "backend").glob("*.json"))) == 4


def test_repair_regenerates_only_target_and_transitive_consumers(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    paths = [f"backend/closure_{index}.py" for index in range(5)]
    manifest = [
        {
            "path": path,
            "purpose": "repair closure",
            "dependencies": [paths[index - 1]] if index else [],
        }
        for index, path in enumerate(paths)
    ]
    generated: list[str] = []

    def content_for(target: str) -> str:
        index = int(pathlib.PurePosixPath(target).stem.rsplit("_", 1)[-1])
        if index == 0:
            return "class Closure0:\n    def run(self):\n        return 0\n"
        return (
            f"from backend.closure_{index - 1} import Closure{index - 1}\n"
            f"class Closure{index}:\n"
            "    def __init__(self):\n"
            f"        self.upstream = Closure{index - 1}()\n"
            "    def run(self):\n"
            "        return self.upstream.run()\n"
        )

    def fake_provider_text(messages, *_args, **kwargs):
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps({"component": "backend", "files": manifest})
        if kwargs.get("payload_mode") == "multi_file":
            owns = json.loads(messages[-1]["content"])["provider_job"]["owns"]
            generated.extend(owns)
            return json.dumps(
                {
                    "files": [
                        {
                            "path": path,
                            "content": (
                                f"class {pathlib.PurePosixPath(path).stem.title()}:\n"
                                "    def run(self):\n"
                                "        return True\n"
                            ),
                        }
                        for path in owns
                    ]
                }
            )
        target = str(kwargs.get("target_file"))
        generated.append(target)
        return json.dumps({"path": target, "content": content_for(target)})

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    checkpoint_dir = tmp_path / "provider_components"
    common = {
        "goal": "build repair closure",
        "component": {"id": "backend", "required_paths": paths},
        "component_pipeline": {"components": [{"id": "backend"}]},
        "prior_manifest": [],
        "repair_errors": [],
        "model": "test-model",
        "timeout": 30,
        "deadline": None,
        "checkpoint_dir": checkpoint_dir,
        "run_dir": tmp_path,
        "spec_hash": "closure-spec",
        "phase_log_path": tmp_path / "provider_phase_log.jsonl",
        "routing_policy": None,
        "split_reason": "closure_test",
        "original_prompt_chars": 80000,
    }
    run_local_pipeline_impl.provider_generate_project_component_split(**common)
    assert generated == paths

    generated.clear()
    repaired = run_local_pipeline_impl.provider_generate_project_component_split(
        **common,
        repair_target_files=[paths[2]],
    )

    assert generated == paths[2:]
    assert repaired["repair_scope"]["downstream_closure"] == paths[2:]


def test_forced_component_repair_regenerates_all_split_leaves(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    paths = ["backend/first.py", "backend/second.py"]
    manifest = [
        {"path": paths[0], "purpose": "first leaf", "dependencies": []},
        {"path": paths[1], "purpose": "second leaf", "dependencies": []},
    ]
    generated: list[str] = []

    def fake_provider_text(messages, *_args, **kwargs):
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps({"component": "backend", "files": manifest})
        if kwargs.get("payload_mode") == "multi_file":
            owns = json.loads(messages[-1]["content"])["provider_job"]["owns"]
            generated.extend(owns)
            return json.dumps(
                {
                    "files": [
                        {
                            "path": path,
                            "content": (
                                f"class {pathlib.PurePosixPath(path).stem.title()}:\n"
                                "    def run(self):\n"
                                "        return True\n"
                            ),
                        }
                        for path in owns
                    ]
                }
            )
        target = str(kwargs.get("target_file"))
        generated.append(target)
        symbol = pathlib.PurePosixPath(target).stem.title()
        return json.dumps(
            {
                "path": target,
                "content": f"class {symbol}:\n    def run(self):\n        return True\n",
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    checkpoint_dir = tmp_path / "provider_components"
    phase_log_path = tmp_path / "provider_phase_log.jsonl"
    common = {
        "goal": "build two independent backend leaves",
        "component": {"id": "backend", "required_paths": paths},
        "component_pipeline": {"components": [{"id": "backend"}]},
        "prior_manifest": [],
        "repair_errors": [],
        "model": "test-model",
        "timeout": 30,
        "deadline": None,
        "checkpoint_dir": checkpoint_dir,
        "run_dir": tmp_path,
        "spec_hash": "forced-component-spec",
        "phase_log_path": phase_log_path,
        "routing_policy": None,
        "split_reason": "forced_component_test",
        "original_prompt_chars": 80000,
    }
    run_local_pipeline_impl.provider_generate_project_component_split(**common)
    assert sorted(generated) == paths

    generated.clear()
    run_local_pipeline_impl.provider_generate_project_component_split(
        **common,
        force_leaf_regeneration=True,
    )

    assert sorted(generated) == paths
    cache_events = [
        json.loads(line)
        for line in phase_log_path.read_text(encoding="utf-8").splitlines()
        if '"event": "component_leaf_cache_scanned"' in line
    ]
    assert {
        entry["source"] for entry in cache_events[-1]["entries"]
    } == {"forced_component_repair"}


def test_manifest_submodules_expand_inside_component_boundary(monkeypatch) -> None:
    def fake_provider_text(_messages, *_args, **_kwargs):
        return json.dumps(
            {
                "component": "backend",
                "files": [
                    {
                        "path": "backend/orchestrator.py",
                        "purpose": "facade",
                        "estimated_complexity": "high",
                        "dependencies": [],
                        "fragmentation_reason": "stable run-state and recovery interfaces exceed one bounded orchestrator output",
                        "submodules": [
                            {
                                "path": "backend/run_state.py",
                                "purpose": "state",
                                "dependencies": [],
                            },
                            {
                                "path": "backend/recovery.py",
                                "purpose": "recovery",
                                "dependencies": ["backend/run_state.py"],
                            },
                            {
                                "path": "src/not_backend.js",
                                "purpose": "illegal owner",
                                "dependencies": [],
                            },
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    manifest = run_local_pipeline_impl.provider_component_file_manifest(
        goal="build modular backend",
        component={"id": "backend", "required_paths": ["backend/orchestrator.py"]},
        component_pipeline={"components": [{"id": "backend"}]},
        prior_manifest=[],
        repair_errors=[],
        model="test-model",
        timeout=30,
        phase_log_path=None,
        routing_policy=None,
    )

    assert [entry["path"] for entry in manifest] == [
        "backend/run_state.py",
        "backend/recovery.py",
        "backend/orchestrator.py",
    ]
    assert manifest[-1]["dependencies"] == [
        "backend/run_state.py",
        "backend/recovery.py",
    ]
    assert manifest[-1]["generation_role"] == "compatibility_facade"
    assert manifest[-1]["estimated_complexity"] == "low"


def test_provider_manifest_rejects_url_fragment_as_file_path(monkeypatch) -> None:
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_text",
        lambda *_args, **_kwargs: json.dumps(
            {
                "component": "frontend",
                "files": [
                    {
                        "path": "src/app.js#offlineArtifacts",
                        "purpose": "invalid symbol-like path",
                        "estimated_complexity": "low",
                    }
                ],
            }
        ),
    )

    with pytest.raises(
        run_local_pipeline_impl.ProviderOutputContractError,
        match="without URL query/fragment",
    ):
        run_local_pipeline_impl.provider_component_file_manifest(
            goal="build a frontend",
            component={"id": "frontend"},
            component_pipeline={"components": [{"id": "frontend"}]},
            prior_manifest=[],
            repair_errors=[],
            model="test-model",
            timeout=30,
            phase_log_path=None,
            routing_policy=None,
        )


def test_frontend_module_self_import_is_rejected() -> None:
    assert "imports or re-exports itself" in run_local_pipeline_impl.validate_frontend_module_self_import(
        [
            {
                "path": "src/app.js",
                "content": "export { loadArtifacts } from './app.js';\n",
            }
        ]
    )
    assert run_local_pipeline_impl.validate_frontend_module_self_import(
        [
            {
                "path": "src/app.js",
                "content": "export { loadArtifacts } from './app_part_01.js';\n",
            }
        ]
    ) == ""


def test_high_complexity_python_leaf_auto_expands_into_symbol_groups() -> None:
    entry = {
        "path": "backend/stages.py",
        "purpose": "implement the complete stage pipeline",
        "dependencies": ["backend/adapters.py"],
        "estimated_complexity": "high",
        "responsibilities": [
            "register stages",
            "run ingestion stages",
            "run analysis stages",
        ],
        "acceptance_checks": [
            "all stages are registered",
            "all stage functions are importable",
        ],
        "expected_symbols": [
            "STAGES_REGISTRY",
            "register_stage",
            "run_ingest",
            "run_extract",
            "run_transcribe",
            "run_merge",
            "run_analyze",
            "run_select",
            "run_render",
            "run_export",
            "run_verify",
        ],
    }

    expanded = run_local_pipeline_impl.expand_component_manifest_submodules(
        "backend",
        [entry],
    )

    assert [item["path"] for item in expanded] == [
        "backend/stages_part_01.py",
        "backend/stages_part_02.py",
        "backend/stages_part_03.py",
        "backend/stages_part_04.py",
        "backend/stages_part_05.py",
        "backend/stages_part_06.py",
        "backend/stages.py",
    ]
    assert all(
        item["generation_role"] == "bounded_submodule"
        for item in expanded[:-1]
    )
    assert [len(item["expected_symbols"]) for item in expanded[:-1]] == [2, 2, 2, 2, 2, 1]
    assert expanded[0]["dependencies"] == ["backend/adapters.py"]
    assert expanded[1]["dependencies"] == ["backend/adapters.py"]
    assert expanded[-1]["generation_role"] == "compatibility_facade"
    assert expanded[-1]["facade_children"] == [
        "backend/stages_part_01.py",
        "backend/stages_part_02.py",
        "backend/stages_part_03.py",
        "backend/stages_part_04.py",
        "backend/stages_part_05.py",
        "backend/stages_part_06.py",
    ]
    assert expanded[-1]["expected_symbols"] == entry["expected_symbols"]

    graph = run_local_pipeline_impl.build_component_leaf_work_graph("backend", expanded)
    assert graph["leaf_count"] == 7
    assert graph["leaves"][-1]["generation_role"] == "compatibility_facade"
    assert graph["leaves"][-1]["facade_children"] == expanded[-1]["facade_children"]


def test_high_complexity_javascript_leaf_auto_expands_into_real_modules() -> None:
    entry = {
        "path": "src/app.js",
        "purpose": "render and control the offline analysis workspace",
        "dependencies": ["index.html", "src/styles.css"],
        "estimated_complexity": "high",
        "responsibilities": [
            "load workspace artifacts",
            "render evidence",
            "edit and persist story nodes",
        ],
        "acceptance_checks": ["the browser entry remains importable"],
        "expected_symbols": [
            "CSDemoIntegrityLabApp",
            "createApp",
            "loadWorkspaceArtifacts",
            "renderEvidenceReport",
            "initStoryEditor",
            "persistStoryGraph",
        ],
        "expected_output_chars": 20000,
    }

    expanded = run_local_pipeline_impl.expand_component_manifest_submodules(
        "frontend",
        [entry],
    )

    assert [item["path"] for item in expanded] == [
        "src/app_part_01.js",
        "src/app_part_02.js",
        "src/app_part_03.js",
        "src/app.js",
    ]
    assert all(
        item["generation_role"] == "bounded_submodule"
        for item in expanded[:-1]
    )
    assert expanded[-1]["generation_role"] == "compatibility_facade"
    assert expanded[-1]["facade_children"] == [
        "src/app_part_01.js",
        "src/app_part_02.js",
        "src/app_part_03.js",
    ]
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "frontend",
        expanded,
    )
    assert [path for leaf in graph["leaves"] for path in leaf["paths"]] == [
        "src/app_part_01.js",
        "src/app_part_02.js",
        "src/app_part_03.js",
        "src/app.js",
    ]
    assert not any(
        warning.startswith("cyclic_or_unresolved")
        for warning in graph["ordering_warnings"]
    )


def test_automatic_stage_siblings_keep_shared_provider_without_split_order_dependency() -> None:
    component = {
        "id": "backend",
        "contract_slice": {
            "required_pipeline_stages": [
                "create_questions",
                "record_answers",
                "schedule_reviews",
                "show_dashboard",
                "search_records",
                "export_backup",
            ]
        },
    }
    manifest = [
        {
            "path": "backend/artifact_store.py",
            "dependencies": [],
            "expected_symbols": ["ArtifactStore", "get_store"],
        },
        {
            "path": "backend/stages.py",
            "purpose": "implement all workflow stages",
            "dependencies": ["backend/artifact_store.py"],
            "estimated_complexity": "high",
            "expected_symbols": component["contract_slice"]["required_pipeline_stages"],
        },
    ]

    expanded = run_local_pipeline_impl.expand_component_manifest_submodules(
        "backend",
        manifest,
        required_pipeline_stages=component["contract_slice"]["required_pipeline_stages"],
    )
    normalized = run_local_pipeline_impl.normalize_backend_stage_dependency_contract(
        "backend", expanded, component
    )
    children = [
        entry
        for entry in normalized
        if entry["path"].startswith("backend/stages_part_")
    ]

    assert len(children) == 3
    assert all("backend/artifact_store.py" in entry["dependencies"] for entry in children)
    assert all(
        not any(
            dependency.startswith("backend/stages_part_")
            for dependency in entry["dependencies"]
        )
        for entry in children
    )
def test_high_complexity_javascript_controller_with_three_symbols_stays_natural() -> None:
    expanded = run_local_pipeline_impl.expand_component_manifest_submodules(
        "frontend",
        [
            {
                "path": "src/app.js",
                "purpose": "control a large visual-novel workspace",
                "dependencies": ["index.html", "src/styles.css"],
                "estimated_complexity": "high",
                "responsibilities": [
                    "bootstrap the workspace",
                    "render the editing surface",
                    "coordinate interactive state",
                ],
                "acceptance_checks": ["the module entry remains importable"],
                "expected_symbols": [
                    "bootstrapApp",
                    "renderStudioApp",
                    "StudioController",
                ],
            }
        ],
    )

    assert [item["path"] for item in expanded] == ["src/app.js"]
    assert expanded[0]["expected_symbols"] == [
        "bootstrapApp",
        "renderStudioApp",
        "StudioController",
    ]
    assert "generation_role" not in expanded[0]


def test_canonical_backend_domain_model_leaf_inherits_owned_bounded_submodules() -> None:
    symbols = [
        "StudyPlan",
        "KnowledgeMap",
        "Question",
        "AnswersExplanationsMastery",
        "WrongAnswerNotebook",
        "DueReview",
        "StudySession",
        "CompletionAccuracyStreak",
        "GlobalSearchFilter",
        "JsonBackupRestore",
        "ApplicationState",
    ]
    expanded = run_local_pipeline_impl.expand_component_manifest_submodules(
        "backend",
        [
            {
                "path": "src/domain_models.py",
                "purpose": "Define shared serializable domain records.",
                "dependencies": [],
                "estimated_complexity": "high",
                "responsibilities": ["Implement validated local-first records."],
                "acceptance_checks": ["All records are importable and serializable."],
                "expected_symbols": symbols,
            }
        ],
    )

    children = expanded[:-1]
    facade = expanded[-1]
    assert [entry["path"] for entry in children] == [
        f"src/domain_models_part_{index:02d}.py" for index in range(1, 7)
    ]
    assert [symbol for entry in children for symbol in entry["expected_symbols"]] == symbols
    assert all(entry["automatic_expansion"] for entry in children)
    assert facade["path"] == "src/domain_models.py"
    assert facade["generation_role"] == "compatibility_facade"
    assert facade["facade_children"] == [entry["path"] for entry in children]
    assert run_local_pipeline_impl.automatic_submodule_path_is_safe(
        "src/domain_models.py", "src/domain_models_part_01.py"
    )
    assert not run_local_pipeline_impl.automatic_submodule_path_is_safe(
        "src/domain_models.py", "src/service.py"
    )


def test_high_complexity_pytest_module_expands_into_collected_parts_and_anchor() -> None:
    expanded = run_local_pipeline_impl.expand_component_manifest_submodules(
        "tests",
        [
            {
                "path": "tests/test_app.py",
                "purpose": "offline CLI end-to-end behavior",
                "dependencies": ["tests/conftest.py"],
                "estimated_complexity": "high",
                "responsibilities": [],
                "acceptance_checks": [],
                "expected_symbols": [],
            }
        ],
    )

    assert [item["path"] for item in expanded] == [
        "tests/test_app_part_01.py",
        "tests/test_app_part_02.py",
        "tests/test_app_part_03.py",
        "tests/test_app.py",
    ]
    assert all(
        item["generation_role"] == "bounded_test_module"
        for item in expanded[:-1]
    )
    assert all(
        item["dependencies"] == ["tests/conftest.py"]
        for item in expanded[:-1]
    )
    assert expanded[-1]["generation_role"] == "test_suite_anchor"
    assert expanded[-1]["expected_symbols"] == ["SUITE_PARTS"]
    assert expanded[-1]["facade_children"] == [
        "tests/test_app_part_01.py",
        "tests/test_app_part_02.py",
        "tests/test_app_part_03.py",
    ]
    anchor_contract = run_local_pipeline_impl.leaf_implementation_depth_contract(
        expanded[-1]
    )
    assert anchor_contract["implementation_kind"] == "facade_source"
    assert anchor_contract["maximum_nonblank_lines"] == 80


def test_goal_tests_are_never_reassigned_to_a_split_suite_anchor() -> None:
    expanded = run_local_pipeline_impl.expand_component_manifest_submodules(
        "tests",
        [
            {
                "path": "tests/test_projectpulse.py",
                "estimated_complexity": "high",
                "expected_symbols": [f"test_goal_{index}" for index in range(1, 7)],
            }
        ],
    )
    goal_tests = [
        {"test_symbol": f"test_goal_{index}", "intent": f"goal {index}"}
        for index in range(1, 7)
    ]

    normalized = run_local_pipeline_impl.normalize_test_manifest_dependency_contract(
        expanded,
        ["projectpulse/service.py"],
        {
            "contract_slice": {"architecture_mode": "direct_cli_application"},
            "goal_acceptance_tests": goal_tests,
        },
    )
    anchor = next(item for item in normalized if item["generation_role"] == "test_suite_anchor")
    parts = [item for item in normalized if item["generation_role"] == "bounded_test_module"]

    assert anchor["expected_symbols"] == ["SUITE_PARTS"]
    assert all(not symbol.startswith("test_") for symbol in anchor["expected_symbols"])
    assert {
        symbol for item in parts for symbol in item["expected_symbols"]
    } == {item["test_symbol"] for item in goal_tests}


def test_broad_direct_cli_goal_test_contract_splits_even_if_manifest_says_medium() -> None:
    goal_tests = [
        {"test_symbol": f"test_goal_{index:02d}_behavior", "intent": f"goal {index}"}
        for index in range(1, 16)
    ]
    expanded = run_local_pipeline_impl.expand_component_manifest_submodules(
        "tests",
        [
            {
                "path": "tests/test_projectpulse.py",
                "estimated_complexity": "medium",
                "expected_symbols": [item["test_symbol"] for item in goal_tests],
            }
        ],
    )
    normalized = run_local_pipeline_impl.normalize_test_manifest_dependency_contract(
        expanded,
        ["projectpulse/service.py"],
        {
            "contract_slice": {"architecture_mode": "direct_cli_application"},
            "goal_acceptance_tests": goal_tests,
        },
    )
    parts = [
        item for item in normalized if item.get("generation_role") == "bounded_test_module"
    ]
    anchor = next(
        item for item in normalized if item.get("generation_role") == "test_suite_anchor"
    )

    assert [item["path"] for item in parts] == [
        "tests/test_projectpulse_part_01.py",
        "tests/test_projectpulse_part_02.py",
        "tests/test_projectpulse_part_03.py",
    ]
    assert [len(item["expected_symbols"]) for item in parts] == [5, 5, 5]
    assert {
        symbol for item in parts for symbol in item["expected_symbols"]
    } == {item["test_symbol"] for item in goal_tests}
    assert anchor["expected_symbols"] == ["SUITE_PARTS"]


def test_leaf_split_context_references_full_goal_without_copying_it() -> None:
    goal = (
        "Build a specialized analysis product. "
        + ("platform discovery and evidence analysis. " * 60)
        + "TAIL_REQUIREMENT_MUST_NOT_BE_COPIED_TO_EVERY_LEAF"
    )
    payload = run_local_pipeline_impl.summarize_component_context_for_split(
        goal=goal,
        component={"id": "tests", "goal": "verify one bounded behavior"},
        component_pipeline={"components": [{"id": "tests"}]},
        prior_manifest=[],
        repair_errors=[],
        librarian_context_pack={
            "query_kind": "leaf_generation",
            "index_sha256": "index",
            "query_sha256": "query",
            "selected_items": [],
        },
    )

    assert payload["raw_user_goal"] == ""
    assert payload["raw_user_goal_reference"]["sha256"]
    assert len(payload["raw_user_goal_reference"]["bounded_excerpt"]) <= 600
    assert "TAIL_REQUIREMENT" not in json.dumps(payload, ensure_ascii=False)


def test_auto_expansion_keeps_independent_submodule_checkpoints(tmp_path) -> None:
    children = run_local_pipeline_impl.automatic_manifest_submodules(
        "backend",
        {
            "path": "backend/stages.py",
            "estimated_complexity": "high",
            "expected_symbols": [f"stage_{index}" for index in range(8)],
        },
    )

    for child in children:
        run_local_pipeline_impl.write_split_file_checkpoint(
            tmp_path,
            component_id="backend",
            spec_hash="bounded-spec",
            file_item={"path": child["path"], "content": "VALUE = 1\n"},
            manifest_entry=child,
        )

    first = run_local_pipeline_impl.load_split_file_checkpoint(
        tmp_path,
        component_id="backend",
        spec_hash="bounded-spec",
        path_value=children[0]["path"],
        manifest_entry=children[0],
    )
    second = run_local_pipeline_impl.load_split_file_checkpoint(
        tmp_path,
        component_id="backend",
        spec_hash="bounded-spec",
        path_value=children[1]["path"],
        manifest_entry=children[1],
    )
    assert first and first["path"] == "backend/stages_part_01.py"
    assert second and second["path"] == "backend/stages_part_02.py"
    changed_contract = dict(children[0])
    changed_contract["expected_symbols"] = ["different_symbol"]
    assert run_local_pipeline_impl.load_split_file_checkpoint(
        tmp_path,
        component_id="backend",
        spec_hash="bounded-spec",
        path_value=children[0]["path"],
        manifest_entry=changed_contract,
    ) is None


def test_pending_legacy_manifest_is_expanded_before_resume(monkeypatch) -> None:
    captured_paths: list[str] = []

    def capture_graph(_component_id, manifest):
        captured_paths.extend(str(item["path"]) for item in manifest)
        raise RuntimeError("captured expanded resume manifest")

    monkeypatch.setattr(
        run_local_pipeline_impl,
        "build_component_leaf_work_graph",
        capture_graph,
    )
    with pytest.raises(RuntimeError, match="captured expanded resume manifest"):
        run_local_pipeline_impl.provider_generate_project_component_split(
            goal="resume the media pipeline",
            component={"id": "backend", "required_paths": ["backend/stages.py"]},
            component_pipeline={"components": [{"id": "backend"}]},
            prior_manifest=[],
            prior_files=[],
            repair_errors=[],
            model="test-model",
            timeout=30,
            deadline=None,
            checkpoint_dir=None,
            run_dir=None,
            spec_hash="resume-spec",
            phase_log_path=None,
            routing_policy=None,
            split_reason="pending_component_file_generation",
            original_prompt_chars=32763,
            pending_context={
                "stage": "component_file_generation",
                "component": "backend",
                "target_file": "backend/stages.py",
                "file_manifest": [
                    {
                        "path": "backend/stages.py",
                        "estimated_complexity": "high",
                        "expected_symbols": [f"stage_{index}" for index in range(8)],
                    }
                ],
            },
        )

    assert captured_paths == [
        "backend/stages_part_01.py",
        "backend/stages_part_02.py",
        "backend/stages_part_03.py",
        "backend/stages_part_04.py",
        "backend/stages.py",
    ]


def test_provider_file_budget_defaults_to_safe_region_and_caps_override(monkeypatch) -> None:
    monkeypatch.delenv("CGNK_PROVIDER_COMPONENT_FILE_MAX_TOKENS", raising=False)
    assert run_local_pipeline_impl.provider_component_prompt_policy()["max_tokens_file"] == 7000

    monkeypatch.setenv("CGNK_PROVIDER_COMPONENT_FILE_MAX_TOKENS", "8000")
    assert run_local_pipeline_impl.provider_component_prompt_policy()["max_tokens_file"] == 7000


def test_qwen_compact_leaf_request_keeps_only_executable_contract() -> None:
    direct_interface = {
        "path": "src/repository.py",
        "python": {
            "classes": [
                {
                    "name": "TaskRepository",
                    "constructor": "TaskRepository(path: Path)",
                    "methods": ["save(task: Task)", "get(task_id: str)"],
                }
            ],
            "functions": [],
        },
    }
    payload = {
        "raw_user_goal": "project-wide narrative " * 1000,
        "raw_user_goal_reference": {"sha256": "goal-hash", "bounded_excerpt": "bounded goal"},
        "component": {"id": "backend", "goal": "build every project capability", "required_paths": ["unrelated.py"]},
        "component_ids": ["foundation", "backend", "tests", "docs"],
        "prior_manifest": [f"unrelated_{index}.py" for index in range(120)],
        "target_file": "src/model.py",
        "target_file_purpose": "Define the validated Task record.",
        "target_file_dependencies": ["src/repository.py"],
        "project_goal_constraints": ["Python 3.11", "standard library only"],
        "implementation_depth_contract": {
            "implementation_kind": "product_source",
            "estimated_complexity": "low",
            "responsibilities": ["Define Task and serialize it"],
            "acceptance_checks": ["title is non-empty", "timestamps are ISO-8601"],
            "expected_symbols": ["Task"],
            "minimum_nonblank_lines": 4,
            "minimum_substantive_statements": 2,
        },
        "required_symbol_contract": {
            "exact_names": ["Task"],
            "publication_rule": "Define Task at module top level.",
        },
        "leaf_interface_contract": {
            "declared_dependencies": ["src/repository.py"],
            "resolved_dependency_paths": ["src/repository.py"],
            "available_implemented_paths": ["src/repository.py", "src/unrelated.py"],
            "authoritative_interface_catalog": [
                direct_interface,
                {"path": "src/unrelated.py", "python": {"functions": ["noise"]}},
            ],
        },
        "librarian_context": {
            "index_sha256": "index-hash",
            "query_sha256": "query-hash",
            "selected_items": [
                {
                    "kind": "source_interface",
                    "path": "src/repository.py",
                    "interface": direct_interface,
                    "content_excerpt": "class TaskRepository:\n    ...\n",
                },
                {
                    "kind": "source_interface",
                    "path": "src/unrelated.py",
                    "content_excerpt": "UNRELATED = '" + ("x" * 6000) + "'",
                },
            ],
        },
        "previous_generation_error": "src/model.py missing required symbol Task",
        "repair_acceptance": {"attempt": 2, "must_fix": "src/model.py missing required symbol Task"},
    }
    messages = [
        {"role": "system", "content": "repeated global rules " * 500},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]

    compact_messages, profile = run_local_pipeline_impl.compact_provider_leaf_messages(messages)
    compact = json.loads(compact_messages[-1]["content"])

    assert profile["profile"] == "qwen_compact_leaf"
    assert profile["effective_prompt_chars"] < profile["legacy_prompt_chars"] * 0.25
    assert profile["effective_prompt_chars"] < 6000
    assert compact["target"]["path"] == "src/model.py"
    assert compact["target"]["required_symbols"] == ["Task"]
    assert compact["interfaces"]["resolved_dependency_paths"] == ["src/repository.py"]
    assert [item["path"] for item in compact["interfaces"]["authoritative_interfaces"]] == [
        "src/repository.py"
    ]
    assert compact["interfaces"]["authoritative_interfaces"][0]["python"]["classes"][0]["name"] == "TaskRepository"
    assert [item["path"] for item in compact["source_context"]] == ["src/repository.py"]
    assert compact["repair"]["must_fix"] == "src/model.py missing required symbol Task"
    assert "raw_user_goal" not in compact
    assert "component_ids" not in compact
    assert "prior_manifest" not in compact
    assert "src/unrelated.py" not in compact_messages[-1]["content"]
    assert run_local_pipeline_impl.provider_compact_leaf_output_tokens(compact_messages, 7000) == 1600


def test_qwen_compact_leaf_request_enforces_hard_budget_for_oversized_contract(monkeypatch) -> None:
    monkeypatch.setenv("CGKN_QWEN_COMPACT_LEAF_MAX_CHARS", "6000")
    repeated_contract = {
        f"rule_{index}": ("preserve this detailed generated-project requirement " * 80)
        for index in range(32)
    }
    payload = {
        "target_file": "src/model.py",
        "target_file_purpose": "Define Task with one validated title input and one dictionary output.",
        "target_file_dependencies": ["src/repository.py"],
        "component": {"id": "backend"},
        "implementation_depth_contract": {
            "implementation_kind": "product_source",
            "estimated_complexity": "low",
            "responsibilities": ["Define Task", "Reject a blank title", "Serialize with to_dict"],
            "acceptance_checks": ["Task is importable", "blank title raises ValueError"],
            "expected_symbols": ["Task"],
        },
        "required_symbol_contract": repeated_contract,
        "leaf_interface_contract": {
            "declared_dependencies": ["src/repository.py"],
            "resolved_dependency_paths": ["src/repository.py"],
            "authoritative_interface_catalog": [
                {"path": "src/repository.py", "python": repeated_contract}
            ],
        },
        "project_goal_constraints": ["Python 3.11", "standard library only"],
        "previous_generation_error": "src/model.py must define importable Task",
    }
    messages = [
        {"role": "system", "content": "legacy global context " * 2000},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]

    compact_messages, profile = run_local_pipeline_impl.compact_provider_leaf_messages(messages)
    compact = json.loads(compact_messages[-1]["content"])

    assert profile["profile"] == "qwen_compact_leaf"
    assert profile["budget_trimmed"] is True
    assert profile["effective_prompt_chars"] <= profile["max_prompt_chars"] == 6000
    assert compact["target"]["path"] == "src/model.py"
    assert compact["target"]["required_symbols"] == ["Task"]
    assert "blank title raises ValueError" in compact["target"]["acceptance_checks"]
    assert compact["interfaces"]["resolved_dependency_paths"] == ["src/repository.py"]
    assert compact["repair"]["must_fix"] == "src/model.py must define importable Task"


def test_qwen_compact_leaf_request_preserves_frozen_feature_interface() -> None:
    feature_contract = {
        "feature_id": "normalize_title",
        "public_entrypoint": {
            "name": "normalize_title",
            "signature": "normalize_title(value: str) -> str",
            "inputs": [{"name": "value", "type": "str"}],
            "output": {"type": "str"},
        },
        "errors": ["ValueError when the normalized value is blank"],
        "side_effects": [],
        "dependencies": [],
        "owned_paths": ["qwen_leaf_probe/normalize_title.py"],
        "acceptance_checks": [
            "surrounding whitespace is stripped",
            "blank normalized input raises ValueError",
        ],
        "interface_sha256": "a" * 64,
    }
    payload = {
        "raw_user_goal": "unrelated project narrative " * 1000,
        "target_file": "qwen_leaf_probe/normalize_title.py",
        "target_file_purpose": "Implement only normalize_title.",
        "target_file_dependencies": [],
        "component": {"id": "backend"},
        "implementation_depth_contract": {
            "implementation_kind": "product_source",
            "estimated_complexity": "low",
            "responsibilities": ["Implement only the frozen normalize_title feature"],
            "acceptance_checks": feature_contract["acceptance_checks"],
            "expected_symbols": ["normalize_title"],
            "maximum_nonblank_lines": 80,
            "maximum_source_chars": 6000,
        },
        "leaf_interface_contract": {
            "declared_dependencies": [],
            "resolved_dependency_paths": [],
            "authoritative_interface_catalog": [],
        },
        "feature_contracts": [feature_contract],
        "feature_interface_freeze_sha256": "b" * 64,
        "project_goal_constraints": [
            "standard library only",
            "no persistence",
            "no networking",
            "no frameworks",
            "no unrelated features",
        ],
    }
    messages = [
        {"role": "system", "content": "large global prompt " * 500},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]

    compact_messages, profile = run_local_pipeline_impl.compact_provider_leaf_messages(messages)
    compact = json.loads(compact_messages[-1]["content"])

    assert profile["profile"] == "qwen_compact_leaf"
    assert profile["effective_prompt_chars"] <= profile["max_prompt_chars"]
    assert compact["feature_contracts"] == [feature_contract]
    assert compact["feature_interface_freeze_sha256"] == "b" * 64
    assert compact["feature_contracts"][0]["public_entrypoint"]["signature"] == (
        "normalize_title(value: str) -> str"
    )
    assert compact["feature_contracts"][0]["side_effects"] == []
    assert compact["feature_contracts"][0]["owned_paths"] == [
        "qwen_leaf_probe/normalize_title.py"
    ]
    assert "raw_user_goal" not in compact
    assert "unrelated project narrative" not in compact_messages[-1]["content"]


def test_feature_unit_source_boundary_rejects_undeclared_cli_and_error_behavior() -> None:
    contract = {
        "feature_id": "normalize_title",
        "public_entrypoint": {
            "name": "normalize_title",
            "inputs": [{"name": "value", "type": "str", "required": True}],
            "output": {"type": "str"},
        },
        "errors": [{"type": "ValueError", "condition": "normalized input is blank"}],
        "side_effects": [],
        "dependencies": [],
        "owned_paths": ["qwen_leaf_probe/normalize_title.py"],
    }
    content = '''import json
import sys

def normalize_title(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("blank")
    return normalized

if __name__ == "__main__":
    print(json.dumps({"normalized_title": normalize_title(sys.argv[1])}))
'''
    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "qwen_leaf_probe/normalize_title.py", "content": content},
        stage="component_file_generation",
        component="backend",
        target_file="qwen_leaf_probe/normalize_title.py",
        prompt_text=json.dumps({"feature_contracts": [contract]}),
    )

    assert "must not duplicate CLI behavior" in error


def test_feature_unit_test_boundary_rejects_invented_cli_module() -> None:
    contract = {
        "feature_id": "normalize_title",
        "public_entrypoint": {"name": "normalize_title"},
        "errors": [],
        "side_effects": [],
        "dependencies": [],
        "owned_paths": ["qwen_leaf_probe/normalize_title.py"],
    }
    content = '''import subprocess
import sys

def test_goal_01_cli():
    subprocess.run([sys.executable, "-m", "qwen_leaf_probe.cli", "title"], check=True)
'''
    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_normalize_title.py", "content": content},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_normalize_title.py",
        prompt_text=json.dumps({"feature_contracts": [contract]}),
    )

    assert "invented CLI modules are forbidden" in error


def test_feature_unit_test_boundary_enforces_frozen_quality_and_stdin_contract() -> None:
    contract = {
        "feature_id": "normalize_title",
        "public_entrypoint": {"name": "normalize_title"},
        "errors": [{"type": "ValueError", "condition": "declared invalid input"}],
        "side_effects": [],
        "dependencies": [],
        "owned_paths": ["qwen_leaf_probe/normalize_title.py"],
    }
    test_contract = {
        "stdin_json_cli": True,
        "cli_result_parsed_json": True,
        "determinism_required": True,
        "declared_error_coverage_required": True,
        "exact_error_messages": ["declared invalid input"],
    }
    incomplete = '''import json
import subprocess
import sys
from qwen_leaf_probe import normalize_title

def test_success():
    assert normalize_title(" title ") == "title"
'''
    missing_determinism = run_local_pipeline_impl.feature_unit_leaf_contract_error(
        "tests/test_normalize_title.py",
        incomplete,
        ast.parse(incomplete),
        {"feature_contracts": [contract], "feature_test_contract": test_contract},
    )
    assert "test_*determin*" in missing_determinism
    assert "ValueError assertion" in missing_determinism
    assert "subprocess.run" in missing_determinism
    assert "operation and nested payload" in missing_determinism

    wrong_cli = '''import json
import subprocess
import sys
from qwen_leaf_probe import normalize_title

def test_feature_determinism():
    assert normalize_title(" title ") == normalize_title(" title ")

def test_invalid_input():
    try:
        normalize_title("")
    except ValueError as exc:
        assert str(exc) == "declared invalid input"
    else:
        raise AssertionError("expected ValueError")

def test_cli():
    request = {"operation": "normalize_title", "value": "title"}
    subprocess.run([sys.executable, "-m", "qwen_leaf_probe", "title"], check=True)
'''
    wrong_cli_error = run_local_pipeline_impl.feature_unit_leaf_contract_error(
        "tests/test_normalize_title.py",
        wrong_cli,
        ast.parse(wrong_cli),
        {"feature_contracts": [contract], "feature_test_contract": test_contract},
    )
    assert "subprocess input keyword" in wrong_cli_error

    complete = '''import json
import subprocess
import sys
from qwen_leaf_probe import normalize_title

def test_feature_determinism():
    assert normalize_title(" title ") == normalize_title(" title ")

def test_invalid_input():
    try:
        normalize_title("")
    except ValueError as exc:
        assert str(exc) == "declared invalid input"
    else:
        raise AssertionError("expected ValueError")

def test_cli():
    request = {"operation": "normalize_title", "payload": {"value": "title"}}
    subprocess.run(
        [sys.executable, "-m", "qwen_leaf_probe"],
        input=json.dumps(request),
        text=True,
        check=True,
    )
'''
    assert run_local_pipeline_impl.feature_unit_leaf_contract_error(
        "tests/test_normalize_title.py",
        complete,
        ast.parse(complete),
        {"feature_contracts": [contract], "feature_test_contract": test_contract},
    ) == ""

    wrong_result_type = complete.replace(
        "assert response['ok'] is True" if "assert response['ok'] is True" in complete else "def test_cli():",
        "def test_cli_result_type():\n    response = {'result': []}\n    assert isinstance(response.get('result'), str)\n\ndef test_cli():",
    )
    parsed_result_error = run_local_pipeline_impl.feature_unit_leaf_contract_error(
        "tests/test_normalize_title.py",
        wrong_result_type,
        ast.parse(wrong_result_type),
        {"feature_contracts": [contract], "feature_test_contract": test_contract},
    )
    assert "must not assert" in parsed_result_error

    double_parse = complete.replace(
        "def test_cli():",
        "def test_cli_result_parse():\n    response = {'result': []}\n    json.loads(response['result'])\n\ndef test_cli():",
    )
    double_parse_error = run_local_pipeline_impl.feature_unit_leaf_contract_error(
        "tests/test_normalize_title.py",
        double_parse,
        ast.parse(double_parse),
        {"feature_contracts": [contract], "feature_test_contract": test_contract},
    )
    assert "must not call json.loads" in double_parse_error


def test_cached_feature_unit_component_revalidates_test_contract() -> None:
    contract = {
        "feature_id": "normalize_title",
        "public_entrypoint": {"name": "normalize_title"},
        "errors": [{"type": "ValueError", "condition": "declared invalid input"}],
        "side_effects": [],
        "dependencies": [],
        "owned_paths": ["probe/normalize_title.py"],
    }
    content = '''import json
import subprocess
import sys
from probe import normalize_title

def test_feature_determinism():
    assert normalize_title("x") == normalize_title("x")

def test_invalid():
    try:
        normalize_title("")
    except ValueError as exc:
        assert str(exc) == "declared invalid input"

def test_cli():
    request = {"operation": "normalize_title", "payload": {"value": "x"}}
    completed = subprocess.run(
        [sys.executable, "-m", "probe"], input=json.dumps(request), text=True
    )
    response = {"result": []}
    json.loads(response["result"])
'''
    entry = {
        "path": "tests/test_normalize_title.py",
        "feature_contracts": [contract],
        "feature_test_contract": {
            "stdin_json_cli": True,
            "cli_result_parsed_json": True,
            "determinism_required": True,
            "declared_error_coverage_required": True,
            "exact_error_messages": ["declared invalid input"],
        },
    }

    receipt = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="tests",
        files=[{"path": entry["path"], "content": content}],
        manifest_entries=[entry],
    )

    assert receipt["status"] == "fail"
    assert receipt["affected_files"] == ["tests/test_normalize_title.py"]
    assert any("must not call json.loads" in blocker for blocker in receipt["blockers"])


def test_api_provider_feature_leaf_rejects_undeclared_error(monkeypatch) -> None:
    contract = {
        "feature_id": "normalize_title",
        "public_entrypoint": {
            "name": "normalize_title",
            "signature": "normalize_title(value: str) -> str",
            "inputs": [{"name": "value", "type": "str", "required": True}],
            "output": {"type": "str"},
        },
        "errors": [{"type": "ValueError", "condition": "normalized input is blank"}],
        "side_effects": [],
        "dependencies": [],
        "owned_paths": ["qwen_leaf_probe/normalize_title.py"],
    }
    manifest_entry = {
        "path": "qwen_leaf_probe/normalize_title.py",
        "purpose": "implement the frozen feature",
        "dependencies": [],
        "feature_contracts": [contract],
        "feature_interface_freeze_sha256": "a" * 64,
        "expected_symbols": ["normalize_title"],
        "estimated_complexity": "low",
    }
    component = {
        "id": "backend",
        "required_paths": ["qwen_leaf_probe/normalize_title.py"],
        "canonical_goal_spec": {
            "domain": "feature_unit_application",
            "feature_contracts": [contract],
        },
    }
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_text",
        lambda *_args, **_kwargs: json.dumps(
            {
                "path": "qwen_leaf_probe/normalize_title.py",
                "content": (
                    "def normalize_title(value: str) -> str:\n"
                    "    if not isinstance(value, str):\n"
                    "        raise TypeError('value must be a string')\n"
                    "    normalized = value.strip()\n"
                    "    if not normalized:\n"
                    "        raise ValueError('blank')\n"
                    "    return normalized\n"
                ),
            }
        ),
    )

    with pytest.raises(
        run_local_pipeline_impl.ProviderOutputContractError,
        match="raises undeclared errors: TypeError",
    ):
        run_local_pipeline_impl.provider_generate_component_file(
            goal="Create qwen_leaf_probe.",
            component=component,
            component_pipeline={"components": [component]},
            manifest_entry=manifest_entry,
            prior_manifest=[],
            completed_files=[],
            prior_files=[],
            component_file_manifest=[manifest_entry],
            repair_errors=[],
            integration_feedforward={},
            leaf_interface_contract={},
            librarian_context_pack={"selected_items": []},
            model="qwen3.8-max",
            timeout=30,
            phase_log_path=None,
            routing_policy=None,
        )


def test_feature_unit_semantic_review_uses_one_bounded_request() -> None:
    feature_goal = {
        "domain": "feature_unit_application",
        "constraints": ["no_persistence", "no_network", "no_frameworks"],
        "interaction_modes": ["cli"],
        "entrypoints": ["qwen_leaf_probe.__main__"],
        "feature_contracts": [
            {
                "feature_id": "normalize_title",
                "public_entrypoint": {
                    "name": "normalize_title",
                    "signature": "normalize_title(value: str) -> str",
                },
                "side_effects": [],
                "dependencies": [],
                "owned_paths": ["qwen_leaf_probe/normalize_title.py"],
            }
        ],
        "feature_interface_freeze": {"freeze_sha256": "a" * 64},
    }
    generation = {
        "component_pipeline": {
            "components": [
                {"id": "backend", "canonical_goal_spec": feature_goal}
            ],
            "oversized_unrelated_context": "x" * 200000,
        }
    }
    payload = run_local_pipeline_impl.semantic_review_full_payload(
        "Create qwen_leaf_probe.",
        {"large_plan": "x" * 200000},
        {"large_blueprint": "x" * 200000},
        {},
        {},
        generation,
        [
            {
                "path": "qwen_leaf_probe/normalize_title.py",
                "content": "def normalize_title(value: str) -> str:\n    return value.strip()\n",
            },
            {"path": "README.md", "content": "documentation " * 2000},
        ],
    )

    assert payload["kind"] == "CGKNFeatureUnitSemanticReviewRequest"
    assert "large_plan" not in payload
    assert "oversized_unrelated_context" not in payload
    assert run_local_pipeline_impl.semantic_review_prompt_chars(payload) < 12000
    readme = next(item for item in payload["files"] if item["path"] == "README.md")
    assert len(readme["content"]) == 600
    assert readme["truncated"] is True


def test_feature_unit_research_is_recorded_as_not_applicable(tmp_path) -> None:
    online, market, design = (
        run_local_pipeline_impl.compile_feature_unit_research_contexts(
            "Create one typed nonvisual function.", tmp_path
        )
    )

    assert online["workflow_state"] == "not_applicable"
    assert online["examples"] == []
    assert market["workflow_state"] == "not_applicable"
    assert market["feature_research"] == []
    assert design["workflow_state"] == "not_applicable"
    assert design["visual_surface_required"] is False
    assert (tmp_path / "input_examples" / "online_input_examples.json").is_file()
    assert (tmp_path / "market_research" / "market_research.json").is_file()
    assert (tmp_path / "design_research" / "design_research.json").is_file()


def test_feature_unit_review_uses_short_qwen_review_stage(monkeypatch) -> None:
    captured: dict[str, object] = {}
    feature_goal = {
        "domain": "feature_unit_application",
        "constraints": ["no_network"],
        "interaction_modes": ["cli"],
        "entrypoints": ["probe.__main__"],
        "feature_contracts": [
            {
                "feature_id": "normalize_title",
                "public_entrypoint": {
                    "name": "normalize_title",
                    "signature": "normalize_title(value: str) -> str",
                },
                "errors": ["TypeError"],
                "side_effects": [],
                "dependencies": [],
                "owned_paths": ["probe/normalize_title.py"],
            }
        ],
        "feature_interface_freeze": {"freeze_sha256": "a" * 64},
    }
    generation = {
        "component_pipeline": {
            "components": [{"id": "backend", "canonical_goal_spec": feature_goal}]
        }
    }

    def fake_provider_text(messages, model, timeout, **kwargs):
        captured.update({"messages": messages, "model": model, "timeout": timeout, **kwargs})
        return json.dumps(
            {
                "status": "pass",
                "issues": [],
                "strengths": ["focused"],
                "expected_artifacts": [],
                "review_summary": "bounded review passed",
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    result = run_local_pipeline_impl.provider_review_project(
        "Create probe.",
        {},
        {},
        {},
        {},
        generation,
        [{"path": "probe/normalize_title.py", "content": "def normalize_title(value: str) -> str:\n    return value.strip()\n"}],
        "qwen3.8-max",
        120,
    )

    assert result["status"] == "pass"
    assert captured["stage"] == "semantic_feature_unit_review"
    assert captured["max_tokens"] == 1800
    assert captured["payload_mode"] == "review_feature_unit"
    assert captured["max_attempts"] == 1


def test_qwen_feature_unit_review_uses_reasoning_none() -> None:
    base_url = "https://llm-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"

    assert run_local_pipeline_impl.provider_qwen_feature_unit_review_enabled(
        base_url, "qwen3.8-max", "semantic_feature_unit_review"
    )
    assert run_local_pipeline_impl.provider_reasoning_effort(
        base_url, "qwen3.8-max", "semantic_feature_unit_review"
    ) == "none"
    assert not run_local_pipeline_impl.provider_qwen_feature_unit_review_enabled(
        base_url, "qwen3.8-max", "semantic_review"
    )


def test_qualified_qwen_bounded_generation_uses_reasoning_none_only_in_scope() -> None:
    base_url = "https://llm-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"

    for model in ("qwen3.5-flash", "qwen3.6-plus", "qwen3.7-flash", "qwen3.7-plus", "qwen3.8-max"):
        assert run_local_pipeline_impl.provider_reasoning_effort(
            base_url, model, "component_file_manifest"
        ) == "none"
        assert run_local_pipeline_impl.provider_reasoning_effort(
            base_url, model, "component_file_generation"
        ) == "none"
    assert run_local_pipeline_impl.provider_reasoning_effort(
        base_url, "qwen-plus", "component_file_generation"
    ) == ""
    assert run_local_pipeline_impl.provider_reasoning_effort(
        base_url, "qwen3.7-flash", "semantic_review"
    ) == ""
    assert run_local_pipeline_impl.provider_reasoning_effort(
        "https://api.example.test/v1", "qwen3.7-flash", "component_file_generation"
    ) == ""


def test_nonvisual_post_build_failure_never_invents_html_repair(tmp_path: pathlib.Path) -> None:
    test_file = tmp_path / "tests" / "test_feature.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_feature():\n    assert False\n", encoding="utf-8")
    finalize = {
        "visual_surface_required": False,
        "test_result": {
            "status": "failed",
            "stdout_tail": "FAILED tests/test_feature.py::test_feature",
        },
        "goal_acceptance": {"applicable": True, "status": "NEEDS_REWORK"},
        "agent_usage": {"status": "partial"},
        "screenshots": [],
        "screenshot_capture": {"status": "skipped", "reason": "not applicable"},
        "video_failure_reason": "startup_failed",
    }

    failures = post_build_repair.classify_post_build_failures(finalize)
    plan = post_build_repair.compile_post_build_repair_plan(tmp_path, finalize)

    assert "test_failure" in failures
    assert "screenshot_failure" not in failures
    assert "startup_failure" not in failures
    assert "missing_entrypoint" not in failures
    assert "index.html" not in plan["target_files"]
    assert plan["target_files"] == ["tests/test_feature.py"]


def test_provider_text_uses_compact_reasoning_none_qwen_leaf_payload(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(run_local_pipeline_impl, "try_local_provider_text", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_resolve_api_credentials",
        lambda: {
            "api_key": "secret-test-key",
            "base_url": "https://llm-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        },
    )

    def fake_post(endpoint, payload, token, timeout):
        captured.update({"endpoint": endpoint, "payload": payload, "token": token, "timeout": timeout})
        return {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({"path": "src/model.py", "content": "VALUE = 1\\n"}),
                        }
                    ],
                }
            ],
        }, ""

    monkeypatch.setattr(run_local_pipeline_impl.check_connectivity, "_post_json", fake_post)
    phase_log = tmp_path / "provider_phase_log.jsonl"
    payload = {
        "target_file": "src/model.py",
        "target_file_purpose": "publish one value",
        "component": {"id": "backend"},
        "implementation_depth_contract": {
            "implementation_kind": "product_source",
            "estimated_complexity": "low",
            "responsibilities": ["publish VALUE"],
            "acceptance_checks": ["VALUE equals 1"],
            "expected_symbols": ["VALUE"],
            "minimum_nonblank_lines": 1,
        },
        "project_goal_constraints": ["Python 3.11"],
        "raw_user_goal": "large project goal " * 1000,
    }
    raw = run_local_pipeline_impl.provider_text(
        [
            {"role": "system", "content": "global generation rules " * 300},
            {"role": "user", "content": json.dumps(payload)},
        ],
        "qwen3.8-max",
        30,
        max_attempts=1,
        stage="component_file_generation",
        component="backend",
        target_file="src/model.py",
        max_tokens=7000,
        payload_mode="split_file",
        phase_log_path=phase_log,
        routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(
            small_model="qwen3.8-max",
            large_model="qwen3.8-max",
        ),
    )

    assert json.loads(raw)["path"] == "src/model.py"
    provider_payload = captured["payload"]
    assert provider_payload["reasoning"] == {"effort": "none"}
    assert provider_payload["max_output_tokens"] == 1600
    assert "CGKNCompactProviderLeafRequest" in provider_payload["input"]
    assert "large project goal" not in provider_payload["input"]
    events = [json.loads(line) for line in phase_log.read_text(encoding="utf-8").splitlines()]
    request_event = next(item for item in events if item.get("event") == "provider_request")
    assert request_event["request_profile"] == "qwen_compact_leaf"
    assert request_event["effective_prompt_chars"] < request_event["legacy_prompt_chars"]
    assert request_event["reasoning_effort"] == "none"
    assert request_event["max_tokens"] == 1600
    assert "secret-test-key" not in phase_log.read_text(encoding="utf-8")


def test_compact_test_plan_leaf_has_bounded_larger_output_budget() -> None:
    messages = [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "kind": "CGKNCompactProviderLeafRequest",
                    "target": {
                        "path": "TEST_PLAN.md",
                        "implementation": {
                            "implementation_kind": "supporting_artifact",
                            "estimated_complexity": "low",
                        },
                    },
                }
            ),
        }
    ]

    assert (
        run_local_pipeline_impl.provider_compact_leaf_output_tokens(messages, 7000)
        == 1800
    )

    messages[0]["content"] = messages[0]["content"].replace(
        "TEST_PLAN.md", "README.md"
    )
    assert (
        run_local_pipeline_impl.provider_compact_leaf_output_tokens(messages, 7000)
        == 1200
    )

def test_bounded_submodule_depth_contract_rejects_overgrown_leaf() -> None:
    entry = {
        "path": "backend/stages_part_01.py",
        "estimated_complexity": "medium",
        "generation_role": "bounded_submodule",
        "responsibilities": ["implement the assigned stage pair"],
        "acceptance_checks": ["the assigned stages are importable"],
        "expected_symbols": ["run_stage"],
    }
    contract = run_local_pipeline_impl.leaf_implementation_depth_contract(entry)
    content = (
        "def run_stage(value):\n"
        "    return value\n"
        + "".join(f"VALUE_{index} = {index}\n" for index in range(330))
    )

    receipt = run_local_pipeline_impl.analyze_leaf_implementation_depth(
        entry["path"],
        content,
        contract,
    )

    assert contract["maximum_nonblank_lines"] == 320
    assert receipt["status"] == "FAIL"
    assert "nonblank implementation lines 332 > 320" in receipt["blockers"]


def test_high_javascript_leaf_has_provider_safe_size_budget() -> None:
    entry = {
        "path": "src/app.js",
        "estimated_complexity": "high",
        "responsibilities": ["coordinate a large interactive workspace"],
        "acceptance_checks": ["the workspace remains executable"],
        "expected_symbols": ["bootstrapApp", "renderStudioApp", "StudioController"],
    }

    contract = run_local_pipeline_impl.leaf_implementation_depth_contract(entry)

    assert contract["maximum_nonblank_lines"] == 260
    assert contract["maximum_source_chars"] == 22000


def test_bounded_javascript_submodule_has_stricter_dual_size_budget() -> None:
    contract = run_local_pipeline_impl.leaf_implementation_depth_contract(
        {
            "path": "src/app_part_01.js",
            "estimated_complexity": "medium",
            "generation_role": "bounded_submodule",
            "responsibilities": ["bootstrap the interactive workspace"],
            "expected_symbols": ["bootstrapApp"],
        }
    )

    assert contract["maximum_nonblank_lines"] == 220
    assert contract["maximum_source_chars"] == 18000


def test_html_depth_uses_semantic_ui_structure_instead_of_code_punctuation() -> None:
    entry = {
        "path": "index.html",
        "estimated_complexity": "medium",
        "responsibilities": ["render a usable authoring workspace"],
        "acceptance_checks": ["editing controls are visible"],
    }
    contract = run_local_pipeline_impl.leaf_implementation_depth_contract(entry)
    meaningful = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Studio</title></head>
<body>
  <header><h1>Story Studio</h1></header>
  <main>
    <section><h2>Story tree</h2><p>Select a node to edit.</p></section>
    <form><label>Title<input id="title"></label><button type="submit">Save</button></form>
  </main>
</body>
</html>
"""

    receipt = run_local_pipeline_impl.analyze_leaf_implementation_depth(
        entry["path"], meaningful, contract
    )

    assert receipt["status"] == "PASS"
    assert receipt["metrics"]["substantive_statements"] >= 5
    assert receipt["metrics"]["behavior_units"] >= 1


def test_html_depth_still_rejects_empty_shell() -> None:
    entry = {
        "path": "index.html",
        "estimated_complexity": "low",
        "responsibilities": ["render the application"],
    }
    contract = run_local_pipeline_impl.leaf_implementation_depth_contract(entry)
    shell = """<!doctype html>
<html>
<head><title>App</title></head>
<body><div id="app"></div></body>
</html>
"""

    receipt = run_local_pipeline_impl.analyze_leaf_implementation_depth(
        entry["path"], shell, contract
    )

    assert receipt["status"] == "FAIL"
    assert any("substantive statements" in blocker for blocker in receipt["blockers"])


def test_index_generation_receives_executable_semantic_structure_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured.update(json.loads(messages[-1]["content"]))
        return json.dumps(
            {
                "path": "index.html",
                "content": (
                    "<!doctype html>\n<html>\n<body>\n<header>\n<h1>Story Studio</h1>\n</header>\n"
                    "<main>\n<section>\n<h2>Story tree</h2>\n<p>Edit a branch.</p>\n"
                    "<button id='add-node'>Add node</button>\n</section>\n</main>\n"
                    "<script type='module' src='src/app.js'></script>\n</body>\n</html>\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    item, _raw = run_local_pipeline_impl.provider_generate_component_file(
        goal="build a visual novel studio",
        component={"id": "frontend"},
        component_pipeline={"components": [{"id": "frontend"}]},
        manifest_entry={
            "path": "index.html",
            "estimated_complexity": "medium",
            "responsibilities": ["render the story authoring workspace"],
        },
        prior_manifest=[],
        completed_files=[],
        component_file_manifest=[
            {"path": "index.html"},
            {"path": "src/app.js"},
        ],
        repair_errors=[],
        model="local",
        timeout=10,
        phase_log_path=None,
        routing_policy=None,
    )

    contract = captured["html_semantic_structure_contract"]
    assert contract["minimum_substantive_elements"] == 5
    assert contract["minimum_behavior_regions_or_controls"] == 1
    assert "<main>" in contract["adaptable_reference"]
    assert any("literal body markup" in rule for rule in captured["target_specific_rules"])
    assert item["path"] == "index.html"


def test_design_document_leaf_receives_exact_research_traceability_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}
    captured_system: dict[str, str] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured_system["content"] = messages[0]["content"]
        captured.update(json.loads(messages[-1]["content"]))
        return json.dumps(
            {
                "path": "docs/design_research.md",
                "content": (
                    "# Design research\n\nSelected direction: Narrative Atelier.\n\n"
                    "Sources: https://one.example/ https://two.example/ https://three.example/\n\n"
                    "Do not copy any reference's exact layout, assets, or branding; "
                    "references inform principles only.\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    item, _raw = run_local_pipeline_impl.provider_generate_component_file(
        goal="build a visual novel studio",
        component={"id": "docs"},
        component_pipeline={
            "components": [{"id": "docs"}],
            "design_context": {
                "references": [
                    {"url": "https://one.example/"},
                    {"url": "https://two.example/"},
                    {"url": "https://three.example/"},
                ],
                "design_contract": {
                    "selected_direction_name": "Narrative Atelier",
                },
            },
        },
        manifest_entry={
            "path": "docs/design_research.md",
            "estimated_complexity": "medium",
            "responsibilities": ["record design research and selection"],
        },
        prior_manifest=[],
        completed_files=[],
        component_file_manifest=[{"path": "docs/design_research.md"}],
        repair_errors=[],
        model="local",
        timeout=10,
        phase_log_path=None,
        routing_policy=None,
    )

    contract = captured["design_documentation_contract"]
    assert contract["exact_selected_direction_name"] == "Narrative Atelier"
    assert contract["minimum_distinct_source_urls"] == 3
    assert contract["available_source_urls"] == [
        "https://one.example/",
        "https://two.example/",
        "https://three.example/",
    ]
    assert "CURRENT DESIGN DOCUMENTATION CONTRACT (highest precedence)" in captured_system["content"]
    assert "Narrative Atelier" in captured_system["content"]
    assert "Do not copy any reference's exact layout" in captured_system["content"]
    assert item["path"] == "docs/design_research.md"


def test_artifact_store_leaf_receives_exact_stage_artifact_schema_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}
    captured_system: dict[str, str] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured_system["content"] = messages[0]["content"]
        captured.update(json.loads(messages[-1]["content"]))
        return json.dumps(
            {
                "path": "backend/artifact_store.py",
                "content": (
                    "REQUIRED_FIELDS = ('stage', 'status', 'count', 'items')\n\n"
                    "class ArtifactStore:\n"
                    "    def __init__(self):\n"
                    "        self.records = []\n\n"
                    "    def store(self, record):\n"
                    "        missing = [key for key in REQUIRED_FIELDS if key not in record]\n"
                    "        if missing:\n"
                    "            raise ValueError(','.join(missing))\n"
                    "        self.records.append(dict(record))\n"
                    "        return len(self.records) - 1\n\n"
                    "    def retrieve(self, index):\n"
                    "        if index < 0 or index >= len(self.records):\n"
                    "            raise IndexError(index)\n"
                    "        return dict(self.records[index])\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    item, _raw = run_local_pipeline_impl.provider_generate_component_file(
        goal="build a staged visual authoring studio",
        component={
            "id": "backend",
            "contract_slice": {
                "required_artifact_fields": ["stage", "status", "count", "items"],
                "required_stage_artifacts": ["project.json", "export_manifest.json"],
            },
        },
        component_pipeline={"components": [{"id": "backend"}]},
        manifest_entry={
            "path": "backend/artifact_store.py",
            "estimated_complexity": "medium",
            "responsibilities": ["validate and persist stage artifact records"],
            "expected_symbols": ["ArtifactStore"],
        },
        prior_manifest=[],
        completed_files=[],
        component_file_manifest=[{"path": "backend/artifact_store.py"}],
        repair_errors=[],
        model="local",
        timeout=10,
        phase_log_path=None,
        routing_policy=None,
    )

    contract = captured["stage_artifact_schema_contract"]
    assert contract["required_fields_exact"] == ["stage", "status", "count", "items"]
    assert contract["required_stage_artifact_names"] == [
        "project.json",
        "export_manifest.json",
    ]
    assert "CURRENT STAGE ARTIFACT SCHEMA CONTRACT (highest precedence)" in captured_system["content"]
    assert "stage, status, count, items" in captured_system["content"]
    assert "opaque bytes only" in captured_system["content"]
    assert item["path"] == "backend/artifact_store.py"


def test_artifact_store_leaf_rejects_opaque_bytes_and_missing_record_fields(monkeypatch) -> None:
    def fake_provider_text(_messages, *_args, **_kwargs):
        return json.dumps(
            {
                "path": "backend/artifact_store.py",
                "content": (
                    "from typing import Dict\n\n"
                    "class ArtifactStore:\n"
                    "    def __init__(self):\n"
                    "        self.artifacts: Dict[str, bytes] = {}\n\n"
                    "    def store(self, key, value):\n"
                    "        if not key:\n"
                    "            raise ValueError('key')\n"
                    "        self.artifacts[key] = value\n\n"
                    "    def retrieve(self, key):\n"
                    "        if key not in self.artifacts:\n"
                    "            raise KeyError(key)\n"
                    "        return self.artifacts[key]\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    with pytest.raises(RuntimeError, match="stage artifact schema contract mismatch") as exc_info:
        run_local_pipeline_impl.provider_generate_component_file(
            goal="build a staged studio",
            component={
                "id": "backend",
                "contract_slice": {
                    "required_artifact_fields": ["stage", "status", "count", "items"],
                    "required_stage_artifacts": ["project.json"],
                },
            },
            component_pipeline={"components": [{"id": "backend"}]},
            manifest_entry={
                "path": "backend/artifact_store.py",
                "estimated_complexity": "medium",
                "responsibilities": ["validate artifact records"],
                "expected_symbols": ["ArtifactStore"],
            },
            prior_manifest=[],
            completed_files=[],
            component_file_manifest=[{"path": "backend/artifact_store.py"}],
            repair_errors=[],
            model="local",
            timeout=10,
            phase_log_path=None,
            routing_policy=None,
        )

    assert "missing exact record fields" in str(exc_info.value)
    assert "ArtifactStore still stores opaque bytes" in str(exc_info.value)


def test_visual_generation_manifest_is_enriched_with_executable_media_contract() -> None:
    component = {
        "id": "backend",
        "contract_slice": {
            "required_pipeline_stages": [
                "generate_background_assets",
                "generate_sprite_assets",
            ]
        },
    }
    backend_manifest = run_local_pipeline_impl.normalize_executable_media_manifest_contract(
        "backend",
        [
            {
                "path": "backend/image_adapters.py",
                "responsibilities": ["generate images"],
                "acceptance_checks": ["images exist"],
                "expected_symbols": ["ImageAdapter"],
            }
        ],
        component,
    )
    media_manifest = run_local_pipeline_impl.normalize_executable_media_manifest_contract(
        "media",
        [
            {"path": "scripts/capture_workflow.py"},
            {"path": "demo/run_fixture.py"},
        ],
        component,
    )

    assert backend_manifest[0]["expected_symbols"] == ["OfflinePngGenerator", "ImageAdapter"]
    assert "decodable offline PNG" in backend_manifest[0]["responsibilities"][0]
    capture = media_manifest[0]
    fixture = media_manifest[1]
    assert capture["expected_symbols"] == ["capture_background", "generate_sprite"]
    assert capture["dependencies"] == [
        "backend/asset_library.py",
        "backend/image_adapters.py",
    ]
    assert "read and verify" in capture["acceptance_checks"][0]
    assert fixture["expected_symbols"] == ["run_fixture"]
    assert "two distinct backgrounds" in fixture["responsibilities"][0]
    pipeline_source = pathlib.Path(run_local_pipeline_impl.__file__).read_text(encoding="utf-8")
    assert '"required_constant_name": "REQUIRED_STAGE_ARTIFACTS"' in pipeline_source
    assert '"from main import initialize_app"' in pipeline_source
    assert '"from pathlib import Path"' in pipeline_source
    assert "undefined convenience helper" in pipeline_source


def test_capture_leaf_receives_adapter_writer_and_readback_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}
    captured_system: dict[str, str] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured_system["content"] = messages[0]["content"]
        captured.update(json.loads(messages[-1]["content"]))
        return json.dumps(
            {
                "path": "scripts/capture_workflow.py",
                "content": (
                    "import hashlib\nfrom pathlib import Path\n\n"
                    "PNG_SIGNATURE = b'\\x89PNG\\r\\n\\x1a\\n'\n\n"
                    "def _verified_png(output_path):\n"
                    "    output_path = Path(output_path)\n"
                    "    if not output_path.is_file():\n"
                    "        raise RuntimeError('missing PNG')\n"
                    "    png_bytes = output_path.read_bytes()\n"
                    "    if not png_bytes.startswith(PNG_SIGNATURE):\n"
                    "        raise RuntimeError('invalid PNG')\n"
                    "    return png_bytes\n\n"
                    "def capture_background(generator, prompt, seed, output_path, **details):\n"
                    "    output_path = Path(output_path)\n"
                    "    result = generator.generate_background(prompt, seed, str(output_path), **details)\n"
                    "    png_bytes = _verified_png(output_path)\n"
                    "    return {'prompt': prompt, 'seed': seed, 'sha256': hashlib.sha256(png_bytes).hexdigest(), 'generator': result['generator'], 'asset_type': 'background', 'path': str(output_path)}\n\n"
                    "def generate_sprite(generator, prompt, seed, output_path, **details):\n"
                    "    output_path = Path(output_path)\n"
                    "    result = generator.generate_sprite(prompt, seed, str(output_path), **details)\n"
                    "    png_bytes = _verified_png(output_path)\n"
                    "    return {'prompt': prompt, 'seed': seed, 'sha256': hashlib.sha256(png_bytes).hexdigest(), 'generator': result['generator'], 'asset_type': 'sprite', 'path': str(output_path)}\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    item, _raw = run_local_pipeline_impl.provider_generate_component_file(
        goal="build a visual novel studio with real PNG assets",
        component={
            "id": "media",
            "contract_slice": {
                "required_pipeline_stages": [
                    "generate_background_assets",
                    "generate_sprite_assets",
                ]
            },
        },
        component_pipeline={"components": [{"id": "media"}]},
        manifest_entry={
            "path": "scripts/capture_workflow.py",
            "estimated_complexity": "high",
            "responsibilities": ["capture and verify generated PNG files"],
            "expected_symbols": ["capture_background", "generate_sprite"],
        },
        prior_manifest=[],
        completed_files=[],
        component_file_manifest=[{"path": "scripts/capture_workflow.py"}],
        repair_errors=[],
        model="local",
        timeout=10,
        phase_log_path=None,
        routing_policy=None,
    )

    shape = captured["executable_media_contract"]["implementation_shape"]
    assert shape["writer_owner"] == "backend.image_adapters.OfflinePngGenerator"
    assert "output_path.read_bytes()" in shape["verification"]
    assert "PNG_SIGNATURE = b'\\x89PNG\\r\\n\\x1a\\n'" in shape["verification"]
    assert "png_bytes.startswith(PNG_SIGNATURE)" in shape["verification"]
    assert "Do not re-render or duplicate" in captured_system["content"]
    assert "raise ValueError('invalid PNG signature')" in captured_system["content"]
    assert item["path"] == "scripts/capture_workflow.py"


def test_deterministic_complexity_gate_routes_simulated_media_to_exact_leaves() -> None:
    goal = (
        "generate_background_assets -> generate_sprite_assets with real local PNG files"
    )
    plan_doc = {
        "complexity_project_contract": {
            "contract_id": "complexity_project_contract_v1",
            "required_pipeline_stages": [
                "generate_background_assets",
                "generate_sprite_assets",
            ],
        }
    }
    files = [
        {
            "path": "backend/image_adapters.py",
            "content": "class ImageAdapter:\n    def generate_image(self, prompt): return prompt\n",
        },
        {
            "path": "scripts/capture_workflow.py",
            "content": "def capture_media(prompt): return 'Generated image for prompt: ' + prompt\n",
        },
        {
            "path": "demo/run_fixture.py",
            "content": "def run_fixture(): return {'status': 'success'}\n",
        },
    ]

    blockers = run_local_pipeline_impl.deterministic_complexity_blockers(
        goal=goal,
        plan_doc=plan_doc,
        component_pipeline={"components": []},
        files=files,
    )

    media_blockers = [
        blocker
        for blocker in blockers
        if blocker["kind"] == "executable_media_contract_incomplete"
    ]
    assert [blocker["files"][0] for blocker in media_blockers] == [
        "backend/image_adapters.py",
        "scripts/capture_workflow.py",
        "demo/run_fixture.py",
    ]
    assert [blocker["component"] for blocker in media_blockers] == [
        "backend",
        "media",
        "media",
    ]
    assert "contains simulated-success behavior" in media_blockers[1]["message"]


def test_deterministic_complexity_gate_accepts_adapter_writer_and_capture_verifier_split() -> None:
    goal = "generate_background_assets -> generate_sprite_assets with real local PNG files"
    plan_doc = {
        "complexity_project_contract": {
            "contract_id": "complexity_project_contract_v1",
            "required_pipeline_stages": ["generate_background_assets", "generate_sprite_assets"],
        }
    }
    files = [
        {
            "path": "backend/image_adapters.py",
            "content": (
                "class OfflinePngGenerator:\n"
                "    def generate_background(self, prompt, seed, path): Path(path).write_bytes(b'png')\n"
                "    def generate_sprite(self, prompt, seed, path): Path(path).write_bytes(b'png rgba alpha')\n"
            ),
        },
        {
            "path": "scripts/capture_workflow.py",
            "content": (
                "PNG_SIGNATURE = b'\\x89PNG\\r\\n\\x1a\\n'\n"
                "def capture_background(prompt, seed, path, generator):\n"
                "    generator.generate_background(prompt, seed, path)\n"
                "    data = Path(path).read_bytes()\n"
                "    assert data.startswith(PNG_SIGNATURE)\n"
                "    return {'sha256': hashlib.sha256(data).hexdigest()}\n"
                "def generate_sprite(prompt, seed, path, generator):\n"
                "    generator.generate_sprite(prompt, seed, path)\n"
                "    data = Path(path).read_bytes()\n"
                "    assert data.startswith(PNG_SIGNATURE)\n"
                "    return {'sha256': hashlib.sha256(data).hexdigest()}\n"
            ),
        },
        {
            "path": "demo/run_fixture.py",
            "content": "def run_fixture(): capture_background(); generate_sprite(); return {'sha256': 'checked'}\n",
        },
    ]

    blockers = run_local_pipeline_impl.deterministic_complexity_blockers(
        goal=goal,
        plan_doc=plan_doc,
        component_pipeline={"components": []},
        files=files,
    )

    assert not [
        blocker
        for blocker in blockers
        if blocker["kind"] == "executable_media_contract_incomplete"
    ]


def test_backend_stage_manifest_receives_canonical_dependency_edges() -> None:
    component = {
        "id": "backend",
        "contract_slice": {
            "required_pipeline_stages": [
                "define_document_contracts",
                "generate_background_assets",
                "export_project",
            ]
        },
    }
    paths = [
        "main.py",
        "backend/story_graph.py",
        "backend/asset_library.py",
        "backend/image_adapters.py",
        "backend/persistence.py",
        "backend/preview.py",
        "backend/stages.py",
        "backend/orchestrator.py",
        "backend/artifact_store.py",
        "backend/stages_part_01.py",
        "backend/stages_part_02.py",
        "backend/stages_part_03.py",
        "backend/stages_part_04.py",
        "backend/stages_part_05.py",
    ]
    manifest = [{"path": path, "dependencies": []} for path in paths]

    normalized = run_local_pipeline_impl.normalize_backend_stage_dependency_contract(
        "backend", manifest, component
    )
    by_path = {entry["path"]: entry for entry in normalized}

    assert by_path["main.py"]["dependencies"] == [
        "backend/orchestrator.py",
        "backend/stages.py",
    ]
    assert by_path["backend/story_graph.py"]["dependencies"] == []
    assert by_path["backend/artifact_store.py"]["dependencies"] == []
    assert by_path["backend/stages.py"]["dependencies"] == [
        "backend/stages_part_01.py",
        "backend/stages_part_02.py",
        "backend/stages_part_03.py",
        "backend/stages_part_04.py",
        "backend/stages_part_05.py",
    ]
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "backend", normalized
    )
    ordered_paths = [path for leaf in graph["leaves"] for path in leaf["paths"]]
    assert graph["ordering_warnings"] == []
    assert ordered_paths[-3:] == [
        "backend/stages.py",
        "backend/orchestrator.py",
        "main.py",
    ]
    assert by_path["main.py"]["expected_symbols"] == ["initialize_app"]
    assert by_path["backend/orchestrator.py"]["dependencies"] == [
        "backend/stages.py",
        "backend/artifact_store.py",
    ]
    assert by_path["backend/orchestrator.py"]["expected_symbols"] == [
        "ProjectOrchestrator"
    ]
    assert "stage(state)" in by_path["backend/orchestrator.py"]["acceptance_checks"][0]
    assert "exactly one evolving state" in by_path["backend/stages_part_03.py"][
        "responsibilities"
    ][-1]
    assert by_path["backend/persistence.py"]["dependencies"] == [
        "backend/story_graph.py",
        "backend/asset_library.py",
    ]
    assert by_path["backend/stages_part_03.py"]["dependencies"] == [
        "backend/image_adapters.py",
        "backend/asset_library.py",
        "backend/artifact_store.py",
    ]


def test_stage_leaf_rejects_extra_required_parameters(monkeypatch) -> None:
    def fake_provider_text(_messages, *_args, **_kwargs):
        return json.dumps(
            {
                "path": "backend/stages_part_01.py",
                "content": (
                    "def define_document_contracts(state, schema):\n"
                    "    if not isinstance(state, dict):\n"
                    "        return {'status': 'error', 'output': {}}\n"
                    "    output = {'schema': schema, 'document': dict(state)}\n"
                    "    return {'status': 'success', 'output': output}\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    with pytest.raises(RuntimeError, match="uniform stage callable contract mismatch") as exc_info:
        run_local_pipeline_impl.provider_generate_component_file(
            goal="build a staged visual novel studio",
            component={
                "id": "backend",
                "contract_slice": {
                    "required_pipeline_stages": ["define_document_contracts"]
                },
            },
            component_pipeline={"components": [{"id": "backend"}]},
            manifest_entry={
                "path": "backend/stages_part_01.py",
                "estimated_complexity": "medium",
                "responsibilities": ["define and validate document contracts"],
                "expected_symbols": ["define_document_contracts"],
            },
            prior_manifest=[],
            completed_files=[],
            component_file_manifest=[{"path": "backend/stages_part_01.py"}],
            repair_errors=[],
            model="local",
            timeout=10,
            phase_log_path=None,
            routing_policy=None,
        )

    assert "must accept exactly one state parameter" in str(exc_info.value)


def test_orchestrator_leaf_rejects_object_style_stage_execution(monkeypatch) -> None:
    def fake_provider_text(_messages, *_args, **_kwargs):
        return json.dumps(
            {
                "path": "backend/orchestrator.py",
                "content": (
                    "class ProjectOrchestrator:\n"
                    "    def __init__(self, stages):\n"
                    "        self.stages = list(stages)\n"
                    "\n"
                    "    def execute(self, initial_state):\n"
                    "        state = dict(initial_state)\n"
                    "        for stage in self.stages:\n"
                    "            result = stage.execute(state)\n"
                    "            if result.get('status') != 'success':\n"
                    "                return result\n"
                    "            state.update(result.get('output', {}))\n"
                    "        return {'status': 'success', 'output': state}\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    with pytest.raises(RuntimeError, match="stage callable execution contract mismatch") as exc_info:
        run_local_pipeline_impl.provider_generate_component_file(
            goal="build a staged visual novel studio",
            component={"id": "backend"},
            component_pipeline={"components": [{"id": "backend"}]},
            manifest_entry={
                "path": "backend/orchestrator.py",
                "estimated_complexity": "medium",
                "responsibilities": ["execute the ordered pipeline"],
                "expected_symbols": ["ProjectOrchestrator"],
            },
            prior_manifest=[],
            completed_files=[],
            component_file_manifest=[{"path": "backend/orchestrator.py"}],
            repair_errors=[],
            model="local",
            timeout=10,
            phase_log_path=None,
            routing_policy=None,
        )

    assert "calls stage.execute(state)" in str(exc_info.value)


def test_media_fixture_leaf_rejects_missing_execution_entrypoint(monkeypatch) -> None:
    def fake_provider_text(_messages, *_args, **_kwargs):
        return json.dumps(
            {
                "path": "demo/run_fixture.py",
                "content": (
                    "import hashlib\n"
                    "\n"
                    "def capture_background(prompt, seed):\n"
                    "    return {'path': f'background-{seed}.png', 'sha256': hashlib.sha256(prompt.encode()).hexdigest()}\n"
                    "\n"
                    "def generate_sprite(prompt, seed):\n"
                    "    return {'path': f'sprite-{seed}.png', 'sha256': hashlib.sha256((prompt + str(seed)).encode()).hexdigest()}\n"
                    "\n"
                    "def run_fixture():\n"
                    "    backgrounds = [capture_background('room', 1), capture_background('garden', 2)]\n"
                    "    sprites = [generate_sprite('hero', 3), generate_sprite('rival', 4)]\n"
                    "    hashes = {item['sha256'] for item in backgrounds + sprites}\n"
                    "    if len(hashes) != 4:\n"
                    "        raise RuntimeError('sha256 collision')\n"
                    "    return {'backgrounds': backgrounds, 'sprites': sprites}\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    with pytest.raises(RuntimeError, match="has no __main__ execution guard"):
        run_local_pipeline_impl.provider_generate_component_file(
            goal="generate real visual novel fixture images",
            component={"id": "media"},
            component_pipeline={"components": [{"id": "media"}]},
            manifest_entry={
                "path": "demo/run_fixture.py",
                "estimated_complexity": "medium",
                "responsibilities": ["execute and verify the generated media fixture"],
                "expected_symbols": ["run_fixture"],
            },
            prior_manifest=[],
            completed_files=[],
            component_file_manifest=[{"path": "demo/run_fixture.py"}],
            repair_errors=[],
            model="local",
            timeout=10,
            phase_log_path=None,
            routing_policy=None,
        )


def test_python_test_leaf_rejects_fixture_function_as_parametrize_argvalues() -> None:
    content = (
        "import pytest\n\n"
        "@pytest.fixture\n"
        "def stages():\n"
        "    return [lambda state: state]\n\n"
        "@pytest.mark.parametrize('stage', stages)\n"
        "def test_stage(stage):\n"
        "    assert stage({}) == {}\n"
    )

    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_pipeline.py", "content": content},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_pipeline.py",
        prompt_text="",
    )

    assert "parametrize argvalues references fixture function(s): stages" in error


def test_post_build_fixture_repair_rejects_fixed_compressed_png_offsets(
    tmp_path: pathlib.Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    content = (
        "from pathlib import Path\n\n"
        "def run_fixture():\n"
        "    png_bytes = Path('sprite.png').read_bytes()\n"
        "    return png_bytes[13] == 255\n\n"
        "if __name__ == '__main__':\n"
        "    run_fixture()\n"
    )

    with pytest.raises(RuntimeError, match="compressed PNG bytes at fixed offsets"):
        post_build_repair.validate_post_build_repair_files(
            candidate_dir,
            [{"path": "demo/run_fixture.py", "content": content}],
            ["demo/run_fixture.py"],
        )


def test_post_build_python_repair_rejects_undefined_names(
    tmp_path: pathlib.Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    content = (
        "def run_fixture():\n"
        "    return Image.open('sprite.png')\n"
        "if __name__ == '__main__': run_fixture()\n"
    )

    with pytest.raises(RuntimeError, match="undefined names.*Image"):
        post_build_repair.validate_post_build_repair_files(
            candidate_dir,
            [{"path": "demo/run_fixture.py", "content": content}],
            ["demo/run_fixture.py"],
        )


def test_post_build_direct_cli_contract_precedes_ordinary_undefined_name_repair(
    tmp_path: pathlib.Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    content = """import pytest
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

@pytest.fixture
def task_service(tmp_path):
    service = TaskService(JSONRepository(tmp_path / 'tasks.json'))
    yield service

def test_add(task_service):
    task_id = str(uuid.uuid4())
    task_service.add('one', task_id=task_id)
"""
    contract = {
        "test_contract": ["pytest functions"],
        "architecture": "Task model -> JSONRepository -> TaskService -> argparse CLI -> main",
    }

    with pytest.raises(RuntimeError, match="direct CLI contract mismatch.*bound argument counts"):
        post_build_repair.validate_post_build_repair_files(
            candidate_dir,
            [{"path": "tests/test_projectpulse_part_01.py", "content": content}],
            ["tests/test_projectpulse_part_01.py"],
            direct_cli_leaf_contract=contract,
        )


def test_post_build_rejects_cached_invalid_direct_cli_pyproject(
    tmp_path: pathlib.Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    content = (
        "[project]\nname = \"ProjectPulse\"\nversion = \"0.1.0\"\n"
        "script-name = \"projectpulse\"\nrequires-python = \">=3.11\"\n"
        "dependencies = []\n[project.scripts]\n"
        "projectpulse = \"projectpulse.cli:main\"\n[build-system]\n"
        "requires = [\"setuptools\", \"wheel\"]\n"
        "build-backend = \"setuptools.build_meta\"\n"
    )

    with pytest.raises(
        RuntimeError,
        match="direct CLI pyproject contract mismatch.*script-name",
    ):
        post_build_repair.validate_post_build_repair_files(
            candidate_dir,
            [{"path": "pyproject.toml", "content": content}],
            ["pyproject.toml"],
            direct_cli_leaf_contract={"api": ["PEP 621"]},
        )


def test_python_syntax_retry_keeps_last_syntax_valid_complete_base() -> None:
    baseline = "import json\n\ndef test_import(tmp_path):\n    assert tmp_path\n"
    truncated = "import json\n\ndef test_import(tmp_path):\n    f.write('[{\n"

    syntax_selection = post_build_repair.post_build_leaf_repair_base_selection(
        "tests/test_projectpulse_part_03.py",
        "post-build repaired Python syntax failure in tests/test_projectpulse_part_03.py: unterminated string literal",
        baseline,
        truncated,
        truncated,
        1,
    )
    ordinary_selection = post_build_repair.post_build_leaf_repair_base_selection(
        "tests/test_projectpulse_part_03.py",
        "named direct CLI generated tests must request tmp_path",
        baseline,
        truncated,
        truncated,
        1,
    )
    latest_valid = "def test_delete(task_service):\n    task_service.delete(1)\n"
    progressed_selection = post_build_repair.post_build_leaf_repair_base_selection(
        "tests/test_projectpulse_part_03.py",
        "named direct CLI generated tests must pass string task identifiers; invalid call",
        baseline,
        truncated,
        latest_valid,
        1,
    )

    assert syntax_selection["source"] == "last_syntax_valid_candidate"
    assert syntax_selection["content"] == baseline
    assert truncated not in syntax_selection["content"]
    assert ordinary_selection["source"] == "closest_rejected_candidate"
    assert ordinary_selection["content"] == truncated
    assert progressed_selection["source"] == "latest_syntax_valid_rejected_candidate"
    assert progressed_selection["content"] == latest_valid


def test_python_safety_rejects_runtime_annotation_shadowing_in_post_build(
    tmp_path: pathlib.Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    content = (
        "class Service:\n"
        "    def list(self):\n"
        "        return []\n"
        "    def search(self) -> list[dict]:\n"
        "        return []\n"
    )
    blockers = run_local_pipeline_impl.generated_python_safety_violations(
        "backend/service.py", content
    )
    assert any("future__ import annotations" in blocker for blocker in blockers)
    with pytest.raises(RuntimeError, match="annotation"):
        post_build_repair.validate_post_build_repair_files(
            candidate_dir,
            [{"path": "backend/service.py", "content": content}],
            ["backend/service.py"],
        )
    safe_content = "from __future__ import annotations\n" + content
    assert not run_local_pipeline_impl.generated_python_safety_violations(
        "backend/service.py", safe_content
    )


def test_post_build_command_retains_actionable_pytest_diagnostics(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    monkeypatch.delenv("CGNK_POST_BUILD_COMMAND_OUTPUT_CHARS", raising=False)
    result = run_local_pipeline_impl.run_allowed_command(
        ["python", "-c", "print('traceback-detail-' * 300)"],
        tmp_path,
        timeout=10,
    )

    assert result["status"] == "pass"
    assert len(result["stdout_tail"]) > 1200
    assert "traceback-detail-" in result["stdout_tail"]


def test_post_build_pytest_disables_unrelated_host_plugin_autoload(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    observed: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["env"] = kwargs.get("env", {})
        return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(run_local_pipeline_impl.subprocess, "run", fake_run)
    result = run_local_pipeline_impl.run_allowed_command(
        ["python", "-m", "pytest", "-q"], tmp_path, timeout=10
    )

    assert result["status"] == "pass"
    assert observed["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_generated_fixture_requires_transparency_and_stage_artifact_writes() -> None:
    blockers = run_local_pipeline_impl.generated_fixture_source_violations(
        "from PIL import Image\n"
        "def run_fixture():\n"
        "    with Image.open('sprite.png') as image:\n"
        "        alpha = image.convert('RGBA').getchannel('A').getextrema()[0]\n"
        "        assert alpha == 255\n"
    )

    assert any("minimum must be less than 255" in item for item in blockers)
    assert any("stage-artifact write operation" in item for item in blockers)

    wrong_order = run_local_pipeline_impl.generated_fixture_source_violations(
        "import json\nfrom pathlib import Path\nfrom PIL import Image\n"
        "def run_fixture():\n"
        "    alpha_min, alpha_max = Image.open('sprite.png').convert('RGBA').getchannel('A').getextrema()\n"
        "    assert alpha_min < 255\n"
        "    artifact_path = Path('stage.json')\n"
        "    existing = json.load(artifact_path.open())\n"
        "    artifact_path.write_text(json.dumps(existing), encoding='utf-8')\n"
    )
    assert any("before writing its structured receipt" in item for item in wrong_order)


def test_post_build_provider_retries_rejected_multi_file_output_atomically(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    candidate_dir = tmp_path / "candidate"
    fixture_path = candidate_dir / "demo" / "run_fixture.py"
    test_path = candidate_dir / "tests" / "test_pipeline.py"
    fixture_path.parent.mkdir(parents=True)
    test_path.parent.mkdir(parents=True)
    fixture_path.write_text("old fixture\n", encoding="utf-8")
    test_path.write_text("old test\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    bad_test = (
        "import pytest\n"
        "@pytest.fixture\n"
        "def stages(): return []\n"
        "@pytest.mark.parametrize('stage', stages)\n"
        "def test_stage(stage): assert stage\n"
    )
    good_test = (
        "import pytest\n"
        "@pytest.fixture\n"
        "def stages(): return []\n"
        "def test_stages(stages): assert stages == []\n"
    )
    good_fixture = (
        "import json\n"
        "from pathlib import Path\n"
        "from PIL import Image\n"
        "def run_fixture():\n"
        "    with Image.open('sprite.png') as image:\n"
        "        alpha_min, alpha_max = image.convert('RGBA').getchannel('A').getextrema()\n"
        "        assert alpha_min < 255 and alpha_max > 0\n"
        "    Path('artifact.json').write_text(json.dumps({'alpha_min': alpha_min}), encoding='utf-8')\n"
        "    return alpha_min, alpha_max\n"
        "if __name__ == '__main__': run_fixture()\n"
    )

    def fake_provider_text(messages, *_args, **_kwargs):
        request = json.loads(messages[-1]["content"])
        calls.append(request)
        target_file = request["target_file"]
        if target_file == "demo/run_fixture.py":
            content = good_fixture
        else:
            content = bad_test if "previous_validation_errors" not in request else good_test
        return json.dumps(
            {
                "files": [
                    {"path": target_file, "content": content},
                ]
            }
        )

    original_legacy_call = post_build_repair._legacy_call

    def fake_legacy_call(name, *args, **kwargs):
        if name == "provider_text":
            return fake_provider_text(*args, **kwargs)
        return original_legacy_call(name, *args, **kwargs)

    monkeypatch.setattr(post_build_repair, "_legacy_call", fake_legacy_call)
    result = post_build_repair.provider_post_build_file_repair(
        candidate_dir=candidate_dir,
        repair_plan={
            "failure_types": ["fixture_failure", "test_failure"],
            "provider_actions": [
                {"path": "demo/run_fixture.py"},
                {"path": "tests/test_pipeline.py"},
            ],
        },
        model="local",
        timeout=10,
        phase_log_path=tmp_path / "phase.jsonl",
        routing_policy=None,
    )

    assert result["status"] == "applied"
    assert result["output_validation_attempts"] == 3
    assert [call["target_file"] for call in calls] == [
        "demo/run_fixture.py",
        "tests/test_pipeline.py",
        "tests/test_pipeline.py",
    ]
    assert "previous_validation_errors" in calls[2]
    assert calls[2]["rejected_replacement_content"] == bad_test
    assert fixture_path.read_text(encoding="utf-8") == good_fixture
    assert test_path.read_text(encoding="utf-8") == good_test


def test_ui_repair_feedback_normalizes_rejection_and_escapes_stagnation(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    (candidate_dir / "index.html").write_text("old shell", encoding="utf-8")
    bad_html = """<!doctype html><html><head><style>body{color:red}</style></head><body>
    <main><section><h1>Editor</h1><button>Edit</button></section></main>
    <script>alert('not implemented')</script></body></html>"""
    good_html = """<!doctype html><html><head><link rel="stylesheet" href="src/styles.css"></head><body>
    <header><h1>Visual Novel Authoring Studio</h1><p>Build typed branching narratives.</p></header><main>
    <section><h2>Edit story graph</h2><input><button>Edit node</button><button>Validate graph</button>
    <ul><li data-node-id="start">Start node</li><li data-node-id="choice">Choice node</li></ul></section>
    <section><h2>Asset library</h2><button>Generate background</button><button>Generate sprite</button>
    <button>Bind asset</button><select><option>Character</option></select>
    <img src="output/background1.png" alt="Background"><img src="output/sprite1.png" alt="Sprite"></section>
    <aside><h2>Preview branch and export</h2><textarea>Preview dialogue and scene state</textarea>
    <output data-preview="branch">Scene preview ready</output>
    <button>Preview branch</button><button>Export project</button>
    <p>Visual Novel Authoring Studio manages typed branching choices, validation results, generated sprites,
    background scenes, node bindings, persistent story state, branch previews, and portable project exports.</p></aside>
    <p id="workspace-status" role="status" aria-live="polite">Workspace ready</p>
    </main><script src="src/app.js"></script></body></html>"""
    contract = {
        "domain_keywords": ["Visual", "Novel", "Authoring", "Studio"],
        "capability_groups": [
            {"stage": "edit_story_graph", "terms": ["edit", "graph"]},
            {"stage": "validate_story_graph", "terms": ["validate"]},
            {"stage": "generate_background_assets", "terms": ["background"]},
            {"stage": "generate_sprite_assets", "terms": ["sprite"]},
            {"stage": "bind_assets_to_nodes", "terms": ["bind"]},
            {"stage": "preview_story_branch", "terms": ["preview", "branch"]},
            {"stage": "export_project", "terms": ["export"]},
        ],
    }
    calls: list[dict[str, object]] = []

    def fake_provider_text(messages, *_args, **_kwargs):
        request = json.loads(messages[-1]["content"])
        calls.append(request)
        content = bad_html if len(calls) < 3 else good_html
        return json.dumps({"files": [{"path": "index.html", "content": content}]})

    original_legacy_call = post_build_repair._legacy_call

    def fake_legacy_call(name, *args, **kwargs):
        if name == "provider_text":
            return fake_provider_text(*args, **kwargs)
        return original_legacy_call(name, *args, **kwargs)

    monkeypatch.setenv("CGNK_POST_BUILD_OUTPUT_REPAIR_ATTEMPTS", "3")
    monkeypatch.setattr(post_build_repair, "_legacy_call", fake_legacy_call)
    result = post_build_repair.provider_post_build_file_repair(
        candidate_dir=candidate_dir,
        repair_plan={
            "failure_types": ["ui_quality_failure"],
            "provider_actions": [{"path": "index.html"}],
            "ui_acceptance_contract": contract,
        },
        model="local",
        timeout=10,
        phase_log_path=tmp_path / "phase.jsonl",
        routing_policy=None,
    )

    assert result["status"] == "applied"
    assert "<style>" not in str(calls[1]["target_file_contents"][0]["content"])
    assert "<script>alert" not in str(calls[1]["target_file_contents"][0]["content"])
    assert calls[2]["stagnation_detected"] is True
    assert calls[2]["rejected_replacement_content_ref"] == (
        "target_file_contents[0].content"
    )
    assert calls[2]["repair_base_selection"]["single_source"] is True
    assert calls[2]["target_file_contents"][0]["source"] == (
        "closest_rejected_candidate"
    )
    assert "rejected_replacement_content" not in calls[2]
    assert calls[2]["stagnation_escape_contract"]["required_region_content"]
    assert calls[0]["ui_repair_brief"]["required_body_identity_line"] == (
        "Visual Novel Authoring Studio"
    )
    region_contract = calls[0]["ui_repair_brief"]["required_region_content"]
    assert [item["stage"] for item in region_contract] == [
        group["stage"] for group in contract["capability_groups"]
    ]
    assert calls[0]["ui_repair_brief"]["maximum_heading_button_only_regions"] == 1
    assert calls[0]["repair_set_context"] == []
    assert calls[0]["accepted_sibling_replacements"] == []
    assert calls[0]["librarian_context_slice"]["current_source_owner"] == (
        "target_file_contents"
    )
    assert region_contract[0]["required_state_bearing_elements"] == [
        "label",
        "input_or_textarea",
        "list_or_output",
    ]
    staged_leaf = (
        tmp_path
        / "artifacts"
        / "post_build_accepted_leaves"
        / "index.html.json"
    )
    assert staged_leaf.is_file()
    assert json.loads(staged_leaf.read_text(encoding="utf-8"))[
        "semantic_adapter_policy"
    ] == "interface_ownership_only_v2"
    rejected_leaf = (
        tmp_path
        / "artifacts"
        / "post_build_rejections"
        / "index.html__attempt_2.json"
    )
    assert json.loads(rejected_leaf.read_text(encoding="utf-8"))[
        "semantic_adapter_policy"
    ] == "interface_ownership_only_v2"
    assert (candidate_dir / "index.html").read_text(encoding="utf-8") == good_html
    memory = post_build_repair.latest_rejected_repair_feedback(
        tmp_path / "phase.jsonl", "index.html", contract
    )
    assert memory["evidence_path"].endswith("index.html__attempt_2.json")
    assert "<style>" not in memory["content"]
    assert "<script>alert" not in memory["content"]

    legacy_leaf = (
        tmp_path
        / "artifacts"
        / "post_build_rejections"
        / "index.html__attempt_9.json"
    )
    legacy_leaf.write_text(
        json.dumps(
            {
                "target_file": "index.html",
                "validation_attempt": 9,
                "validation_error": "legacy artificial UI",
                "content": '<li data-node-id="start">Start node</li>',
                "candidate_only": True,
            }
        ),
        encoding="utf-8",
    )
    legacy_memory = post_build_repair.latest_rejected_repair_feedback(
        tmp_path / "phase.jsonl", "index.html", contract
    )
    assert legacy_memory["evidence_path"].endswith("index.html__attempt_2.json")

    calls.clear()
    second = post_build_repair.provider_post_build_file_repair(
        candidate_dir=candidate_dir,
        repair_plan={
            "failure_types": ["ui_quality_failure"],
            "provider_actions": [{"path": "index.html"}],
            "ui_acceptance_contract": contract,
        },
        model="local",
        timeout=10,
        phase_log_path=tmp_path / "phase.jsonl",
        routing_policy=None,
    )
    assert second["status"] == "applied"
    assert calls == []
    assert "accepted_leaf_revalidated" in (tmp_path / "phase.jsonl").read_text(
        encoding="utf-8"
    )


def test_post_build_reuses_validated_direct_cli_leaf_without_provider_call(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    candidate_dir = tmp_path / "candidate"
    cli_path = candidate_dir / "projectpulse" / "cli.py"
    cli_path.parent.mkdir(parents=True)
    cli_path.write_text("old source\n", encoding="utf-8")
    accepted_dir = tmp_path / "artifacts" / "post_build_accepted_leaves"
    accepted_dir.mkdir(parents=True)
    accepted_source = "def main(argv=None):\n    return 0\n"
    (accepted_dir / "projectpulse__cli.py.json").write_text(
        json.dumps(
            {
                "target_file": "projectpulse/cli.py",
                "content": accepted_source,
                "candidate_only": True,
                "status": "validated_pending_atomic_commit",
                "semantic_adapter_policy": "interface_ownership_only_v2",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        post_build_repair,
        "post_build_direct_cli_leaf_contract",
        lambda _phase, _target: {"required_symbols": ["main"]},
    )
    monkeypatch.setattr(
        post_build_repair,
        "validate_post_build_repair_files",
        lambda _candidate, items, _targets, **_kwargs: items,
    )
    original_legacy_call = post_build_repair._legacy_call

    def reject_provider(name, *args, **kwargs):
        if name == "provider_text":
            raise AssertionError(
                "provider must not be called for a revalidated direct-CLI leaf"
            )
        return original_legacy_call(name, *args, **kwargs)

    monkeypatch.setattr(post_build_repair, "_legacy_call", reject_provider)

    result = post_build_repair.provider_post_build_file_repair(
        candidate_dir=candidate_dir,
        repair_plan={
            "failure_types": ["test_failure"],
            "provider_actions": [{"path": "projectpulse/cli.py"}],
        },
        model="local",
        timeout=10,
        phase_log_path=tmp_path / "phase.jsonl",
        routing_policy=None,
    )

    assert result["status"] == "applied"
    assert cli_path.read_text(encoding="utf-8") == accepted_source
    assert "accepted_leaf_revalidated" in (tmp_path / "phase.jsonl").read_text(
        encoding="utf-8"
    )


def test_post_build_test_dependency_context_follows_facade_reexports(
    tmp_path: pathlib.Path,
) -> None:
    candidate_dir = tmp_path / "candidate"
    (candidate_dir / "tests").mkdir(parents=True)
    (candidate_dir / "backend").mkdir(parents=True)
    (candidate_dir / "tests" / "test_pipeline.py").write_text(
        "from backend.stages import run_stage, STAGE_REGISTRY\n",
        encoding="utf-8",
    )
    (candidate_dir / "backend" / "stages.py").write_text(
        "from backend.stages_part_01 import run_stage, STAGE_REGISTRY\n",
        encoding="utf-8",
    )
    (candidate_dir / "backend" / "stages_part_01.py").write_text(
        "class STAGE_REGISTRY:\n"
        "    @classmethod\n"
        "    def ordered_stages(cls): return ['one']\n\n"
        "def run_stage(stage_name: str, state: dict) -> dict:\n"
        "    return {'status': 'success', 'output': state}\n",
        encoding="utf-8",
    )

    context = post_build_repair.python_test_dependency_context(
        candidate_dir, "tests/test_pipeline.py"
    )

    assert [item["path"] for item in context] == [
        "backend/stages_part_01.py"
    ]
    assert "def run_stage(stage_name: str, state: dict)" in context[0][
        "source_excerpt"
    ]
    assert "def ordered_stages(cls)" in context[0]["source_excerpt"]


def test_pyproject_leaf_rejects_requirements_syntax_inside_toml(monkeypatch) -> None:
    def fake_provider_text(_messages, *_args, **_kwargs):
        return json.dumps(
            {
                "path": "pyproject.toml",
                "content": (
                    "[tool.poetry]\n"
                    "name = 'broken-project'\n"
                    "version = '0.1.0'\n"
                    "[tool.poetry.dependencies]\n"
                    "python = '>=3.11'\n"
                    "flask == 2.1.2\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    with pytest.raises(RuntimeError, match="pyproject TOML contract mismatch"):
        run_local_pipeline_impl.provider_generate_component_file(
            goal="build a Python application foundation",
            component={"id": "foundation"},
            component_pipeline={"components": [{"id": "foundation"}]},
            manifest_entry={
                "path": "pyproject.toml",
                "estimated_complexity": "low",
                "responsibilities": ["declare valid Python project metadata"],
            },
            prior_manifest=[],
            completed_files=[],
            component_file_manifest=[{"path": "pyproject.toml"}],
            repair_errors=[],
            model="local",
            timeout=10,
            phase_log_path=None,
            routing_policy=None,
        )


def test_cached_component_quality_rejects_invalid_pyproject_toml() -> None:
    receipt = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="foundation",
        files=[
            {
                "path": "pyproject.toml",
                "content": "[tool.poetry.dependencies]\nflask == 2.1.2\n",
            },
            {"path": "requirements.txt", "content": "flask==2.1.2\n"},
        ],
    )

    assert receipt["status"] == "fail"
    assert "toml_syntax" in receipt["checks"]
    assert any("pyproject.toml has invalid TOML syntax" in item for item in receipt["blockers"])
    assert receipt["affected_files"] == ["pyproject.toml"]


def test_python_interfaces_follow_constructor_injected_types() -> None:
    files = [
        {
            "path": "backend/story_graph.py",
            "content": "class StoryGraph:\n    def save(self, path): return path\n",
        },
        {
            "path": "backend/preview.py",
            "content": (
                "from backend.story_graph import StoryGraph\n"
                "class PreviewGenerator:\n"
                "    def __init__(self, graph: StoryGraph):\n"
                "        self.graph = graph\n"
                "    def preview(self):\n"
                "        return self.graph.get_branch('start')\n"
            ),
        },
    ]

    violations = run_local_pipeline_impl.python_leaf_interface_violations(files)

    assert violations == [
        "backend/preview.py calls missing StoryGraph.get_branch from backend/story_graph.py"
    ]


def test_cached_backend_quality_rejects_empty_graph_bad_stage_and_unsafe_placeholder() -> None:
    receipt = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="backend",
        files=[
            {
                "path": "main.py",
                "content": (
                    "from backend.orchestrator import ProjectOrchestrator\n"
                    "def initialize_app():\n"
                    "    return ProjectOrchestrator(stages=[]).execute()\n"
                ),
            },
            {
                "path": "backend/orchestrator.py",
                "content": (
                    "class ProjectOrchestrator:\n"
                    "    def __init__(self, stages): self.stages = stages\n"
                    "    def execute(self):\n"
                    "        state = {}\n"
                    "        for stage in self.stages:\n"
                    "            result = stage(state)\n"
                    "            state.update(result['output'])\n"
                    "        return state\n"
                ),
            },
            {
                "path": "backend/stages_part_01.py",
                "content": (
                    "def import_inputs(state):\n"
                    "    # Simulate workflow logic here\n"
                    "    state['output'] = eval(state.get('raw', '{}'))\n"
                    "    return state\n"
                ),
            },
        ],
        manifest_entries=[
            {
                "path": "main.py",
                "expected_symbols": ["initialize_app"],
                "required_stage_symbols": ["import_inputs"],
            },
            {
                "path": "backend/stages_part_01.py",
                "expected_symbols": ["import_inputs"],
                "stage_callable_symbols": ["import_inputs"],
            },
        ],
    )

    assert receipt["status"] == "fail"
    blockers = "\n".join(receipt["blockers"])
    assert "empty or opaque stage graph" in blockers
    assert "pass stages=[import_inputs] directly" in blockers
    assert "returns state instead of a stage result" in blockers
    assert "unsafe dynamic execution: eval" in blockers
    assert "executable placeholder implementation" in blockers
    assert "does not validate stage result fields: status" in blockers


def test_cached_artifact_store_rejects_opaque_bytes() -> None:
    receipt = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="backend",
        files=[
            {
                "path": "backend/artifact_store.py",
                "content": (
                    "from typing import Dict\n"
                    "class ArtifactStore:\n"
                    "    def __init__(self): self.records: Dict[str, bytes] = {}\n"
                ),
            }
        ],
        manifest_entries=[
            {
                "path": "backend/artifact_store.py",
                "expected_symbols": ["ArtifactStore"],
                "required_artifact_fields": ["stage", "status", "count", "items"],
            }
        ],
    )

    assert receipt["status"] == "fail"
    blockers = "\n".join(receipt["blockers"])
    assert "omits required artifact fields" in blockers
    assert "stores opaque bytes instead of structured records" in blockers


def test_post_build_fixture_failure_targets_fixture_and_stage_graph(tmp_path: pathlib.Path) -> None:
    for rel in (
        "demo/run_fixture.py",
        "backend/orchestrator.py",
        "backend/stages.py",
        "backend/artifact_store.py",
        "src/app.js",
    ):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# generated\n", encoding="utf-8")

    plan = run_local_pipeline_impl.compile_post_build_repair_plan(
        tmp_path,
        {
            "test_result": {"status": "pass", "argv": ["python", "-m", "pytest"]},
            "fixture_result": {
                "status": "fail",
                "blockers": ["required stage artifact missing: export_manifest.json"],
            },
            "screenshots": [],
        },
    )

    assert "fixture_failure" in plan["failure_types"]
    assert "stage_artifact_failure" in plan["failure_types"]
    assert plan["target_files"][:3] == [
        "demo/run_fixture.py",
        "backend/orchestrator.py",
        "backend/stages.py",
    ]
    assert "src/app.js" not in plan["target_files"]


def test_generated_fixture_cannot_print_error_and_exit_zero(
    tmp_path: pathlib.Path,
) -> None:
    project_dir = tmp_path / "project"
    run_dir = tmp_path / "run"
    fixture = project_dir / "demo" / "run_fixture.py"
    fixture.parent.mkdir(parents=True)
    (run_dir / "discovery").mkdir(parents=True)
    fixture.write_text(
        "import json\nprint(json.dumps({'status': 'error', 'message': 'unavailable'}))\n",
        encoding="utf-8",
    )
    (run_dir / "discovery" / "complexity_project_contract.json").write_text(
        "{}\n", encoding="utf-8"
    )

    receipt = run_local_pipeline_impl.run_generated_project_fixture(
        project_dir, run_dir, timeout=10
    )

    assert receipt["status"] == "failed"
    assert receipt["command"]["status"] == "pass"
    assert (
        "generated fixture declared failure while exiting successfully"
        in receipt["blockers"]
    )


def test_generated_fixture_accepts_square_transparent_sprites(
    tmp_path: pathlib.Path,
) -> None:
    from PIL import Image, ImageDraw

    project_dir = tmp_path / "project"
    run_dir = tmp_path / "run"
    fixture = project_dir / "demo" / "run_fixture.py"
    fixture.parent.mkdir(parents=True)
    (run_dir / "discovery").mkdir(parents=True)
    fixture.write_text("# prebuilt deterministic fixture media\n", encoding="utf-8")
    output_dir = project_dir / "output"
    output_dir.mkdir(parents=True)

    for index in range(2):
        background = Image.new("RGB", (640, 360), (20 + index * 50, 40, 80))
        draw = ImageDraw.Draw(background)
        for x in range(0, 640, 16):
            draw.rectangle((x, 0, x + 7, 359), fill=((x + index * 31) % 255, 90, 160))
        background.save(output_dir / f"background{index}.png")

        sprite = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        sprite_draw = ImageDraw.Draw(sprite)
        sprite_draw.ellipse(
            (48 + index * 8, 24, 464, 500),
            fill=(100 + index * 60, 80, 180, 220),
        )
        sprite_draw.rectangle((180, 180, 332, 440), fill=(220, 140, 90, 255))
        sprite.save(output_dir / f"sprite{index}.png")

    (run_dir / "discovery" / "complexity_project_contract.json").write_text(
        json.dumps(
            {
                "required_pipeline_stages": [
                    "generate_background_assets",
                    "generate_sprite_assets",
                ]
            }
        ),
        encoding="utf-8",
    )

    receipt = run_local_pipeline_impl.run_generated_project_fixture(
        project_dir, run_dir, timeout=10
    )

    assert receipt["status"] == "pass"
    assert receipt["media"]["png_count"] == 4
    assert receipt["media"]["distinct_sha256_count"] == 4
    assert len(receipt["media"]["transparent_sprite_paths"]) == 2


def test_candidate_ui_smoke_uses_selected_project_contract_keywords(
    tmp_path: pathlib.Path,
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "discovery").mkdir(parents=True)
    (run_dir / "discovery" / "complexity_project_contract.json").write_text(
        json.dumps(
            {
                "selected_project_name": "Local Visual Novel Authoring Studio",
                "selected_project_summary": "A branching story graph and sprite editor",
            }
        ),
        encoding="utf-8",
    )

    keywords = run_local_pipeline_impl.candidate_ui_domain_keywords(run_dir)
    result = run_local_pipeline_impl.candidate_ui_smoke(
        {
            "page_title": "Visual Novel Authoring Studio",
            "body_text_length": 180,
            "body_text_sample": "VISUAL NOVEL AUTHORING STUDIO — Story Editor",
            "interactive_control_count": 1,
            "section_count": 1,
            "heading_count": 2,
            "console_errors": [],
            "network_errors": [],
        },
        keywords,
    )

    assert keywords[:4] == ["Visual", "Novel", "Authoring", "Studio"]
    assert result["status"] == "pass"
    assert result["domain_keywords"] == keywords
    assert result["keywords_found"][:4] == keywords[:4]


def test_complex_candidate_ui_smoke_rejects_titled_shell_and_accepts_workspace(
    tmp_path: pathlib.Path,
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "discovery").mkdir(parents=True)
    (run_dir / "discovery" / "complexity_project_contract.json").write_text(
        json.dumps(
            {
                "selected_project_name": "Visual Novel Studio",
                "required_pipeline_stages": [
                    "edit_story_graph",
                    "validate_story_graph",
                    "generate_background_assets",
                    "generate_sprite_assets",
                    "bind_assets_to_nodes",
                    "preview_story_branch",
                    "export_project",
                ],
            }
        ),
        encoding="utf-8",
    )
    groups = run_local_pipeline_impl.candidate_ui_capability_groups(run_dir)
    shell = run_local_pipeline_impl.candidate_ui_smoke(
        {
            "page_title": "Visual Novel Studio",
            "body_text_length": 80,
            "body_text_sample": "Visual Novel Studio Story Editor",
            "interactive_control_count": 2,
            "section_count": 1,
            "heading_count": 2,
            "console_errors": [],
            "network_errors": [],
        },
        ["Visual", "Novel", "Studio"],
        groups,
    )
    workspace = run_local_pipeline_impl.candidate_ui_smoke(
        {
            "page_title": "Visual Novel Studio",
            "body_text_length": 420,
            "body_text_sample": (
                "Visual Novel Studio Edit graph Validate graph Background Sprite "
                "Bind library Preview branch Export project character scene controls"
            ),
            "interactive_control_count": 9,
            "section_count": 4,
            "heading_count": 6,
            "console_errors": [],
            "network_errors": [],
        },
        ["Visual", "Novel", "Studio"],
        groups,
    )

    assert shell["status"] == "fail"
    assert "required_capabilities_missing" in shell["issues"]
    assert "interactive_controls_too_few" in shell["issues"]
    assert workspace["status"] == "pass"
    low_density = run_local_pipeline_impl.candidate_ui_smoke(
        {
            "page_title": "Visual Novel Studio",
            "body_text_length": 420,
            "body_text_sample": (
                "Visual Novel Studio Edit graph Validate graph Background Sprite "
                "Bind library Preview branch Export project character scene controls"
            ),
            "interactive_control_count": 9,
            "section_count": 4,
            "heading_count": 6,
            "blank_score": 0.96,
            "viewport_width": 1280,
            "document_scroll_width": 1500,
            "undersized_control_count": 1,
            "oversized_media_count": 1,
            "empty_workspace_region_count": 3,
            "status_region_count": 1,
            "nonempty_status_region_count": 0,
            "console_errors": [],
            "network_errors": [],
        },
        ["Visual", "Novel", "Studio"],
        groups,
    )
    assert "workspace_visual_density_too_low" in low_density["issues"]
    assert "workspace_horizontal_overflow" in low_density["issues"]
    assert "control_hit_targets_too_small" in low_density["issues"]
    assert "asset_previews_oversized" in low_density["issues"]
    assert "workspace_regions_lack_content" in low_density["issues"]
    assert "workspace_status_empty" in low_density["issues"]


def test_ui_quality_repair_targets_only_existing_frontend_owners(
    tmp_path: pathlib.Path,
) -> None:
    for rel in (
        "index.html",
        "src/app.js",
        "src/styles.css",
        "demo/run_fixture.py",
        "tests/test_pipeline.py",
    ):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# existing\n", encoding="utf-8")

    finalize = {
        "test_result": {"status": "pass", "argv": ["python", "-m", "pytest"]},
        "fixture_result": {
            "status": "pass",
            "fixture": str(tmp_path / "demo" / "run_fixture.py"),
        },
        "screenshots": [str(tmp_path / "candidate_home.png")],
        "screenshot_capture": {
            "status": "pass",
            "startup": {"mode": "static_html", "path": "index.html"},
        },
        "ui_smoke": {
            "status": "fail",
            "issues": [
                "required_capabilities_missing",
                "interactive_controls_too_few",
            ],
        },
    }

    failures = post_build_repair.classify_post_build_failures(finalize)
    plan = post_build_repair.compile_post_build_repair_plan(tmp_path, finalize)

    assert failures == ["ui_quality_failure"]
    assert plan["target_files"] == [
        "index.html",
        "src/app.js",
        "src/styles.css",
    ]
    assert [item["path"] for item in plan["provider_actions"]] == plan[
        "target_files"
    ]


def test_frontend_repair_source_boundary_rejects_shell_and_accepts_workspace() -> None:
    contract = {
        "capability_groups": [
            {"stage": "edit_story_graph", "terms": ["edit", "graph"]},
            {"stage": "validate_story_graph", "terms": ["validate"]},
            {"stage": "generate_background_assets", "terms": ["background"]},
            {"stage": "generate_sprite_assets", "terms": ["sprite"]},
            {"stage": "bind_assets_to_nodes", "terms": ["bind"]},
            {"stage": "preview_story_branch", "terms": ["preview", "branch"]},
            {"stage": "export_project", "terms": ["export"]},
        ]
    }
    shell = (
        "<main><section><h1>Visual Novel Studio</h1>"
        "<input><button>Edit story</button></section></main>"
    )
    workspace = """<!doctype html><html><head><link rel="stylesheet" href="src/styles.css"></head><body>
    <header><h1>Visual Novel Authoring Studio</h1><p>Shape typed branching stories and scene direction.</p></header><main>
    <section><h2>Edit story graph</h2><input><button>Edit node</button><button>Validate graph</button>
    <ul><li data-node-id="start">Start node</li><li data-node-id="choice">Choice node</li></ul></section>
    <section><h2>Asset library</h2><button>Generate background</button><button>Generate sprite</button>
    <button>Bind asset</button><select><option>Character</option></select>
    <img src="output/background1.png" alt="Generated background"><img src="output/sprite1.png" alt="Generated sprite"></section>
    <aside><h2>Preview branch</h2><textarea>Preview dialogue and scene state</textarea>
    <output data-preview="branch">Scene preview ready</output>
    <button>Preview branch</button><button>Export project</button>
    <p>Inspect choices, validation results, generated character sprites, background scenes, node bindings, and export status in this authoring workspace.</p></aside>
    <p id="status" role="status" aria-live="polite">Workspace ready</p></main><script src="src/app.js"></script></body></html>"""
    app = """const a=document.querySelector('#a');const b=document.querySelector('#b');const c=document.querySelector('#c');
    a.addEventListener('click', save);b.addEventListener('change', preview);c.addEventListener('click', exportProject);
    localStorage.setItem('workspace', JSON.stringify({nodes:[]}));
    const output = document.querySelector('#output'); output.textContent = localStorage.getItem('workspace');
    output.textContent = JSON.stringify({status:'ready'});
    const blob = new Blob([output.textContent], {type:'application/json'}); URL.createObjectURL(blob);"""
    css = """:root{--bg:#111;--surface:#222;--text:#eee;--accent:#8ad;--space:1rem;--radius:12px;--border:#456}
    body{background:var(--bg);color:var(--text);margin:0}
    header{padding:var(--space);background:var(--surface);border-bottom:1px solid var(--border)}
    main{display:grid;max-width:1200px;background:var(--bg);color:var(--text);border-radius:var(--radius);box-shadow:0 8px 30px #0004;gap:var(--space)}
    button{min-height:44px;background:var(--accent);color:var(--bg);border-radius:var(--radius)}
    input,select,textarea{min-height:44px}
    img{max-width:100%;object-fit:cover}
    button:focus-visible{outline:3px solid var(--accent)}
    @media(max-width:700px){main{display:flex}}\n""" + "\n".join(
        f".panel-{index}{{display: grid; gap: {index + 1}px}}" for index in range(18)
    )

    assert post_build_repair.generated_frontend_workspace_source_violations(
        "index.html", shell, contract
    )
    assert not post_build_repair.generated_frontend_workspace_source_violations(
        "index.html", workspace, contract
    )
    assert not post_build_repair.generated_frontend_workspace_source_violations(
        "src/app.js", app, contract
    )
    assert not post_build_repair.generated_frontend_workspace_source_violations(
        "src/styles.css", css, contract
    )

    title_cannot_fill_body = (
        "<!doctype html><html><head><title>"
        + ("Studio " * 40)
        + "</title></head><body>"
        + shell
        + "</body></html>"
    )
    title_errors = post_build_repair.generated_frontend_workspace_source_violations(
        "index.html", title_cannot_fill_body, contract
    )
    assert any("HTML body has" in error for error in title_errors)

    placeholder_app = app + "\nfunction edit(){ console.log('not implemented'); }"
    placeholder_errors = post_build_repair.generated_frontend_workspace_source_violations(
        "src/app.js", placeholder_app, contract
    )
    assert any("non-functional placeholder phrases" in error for error in placeholder_errors)
    assert any("console.log as workspace behavior" in error for error in placeholder_errors)

    modular_with_inline = workspace.replace(
        "</body>",
        "<style>.legacy{color:red}</style><script>alert('not implemented')</script></body>",
    )
    normalized, actions = post_build_repair.normalize_ui_repair_html_ownership(
        modular_with_inline, contract
    )
    assert "<style>" not in normalized
    assert "not implemented" not in normalized
    assert actions == [
        "removed_inline_script_for_src_app_owner",
        "removed_inline_style_for_src_css_owner",
    ]

    sparse_css = "\n".join(
        f".panel-{index}{{padding:{index + 1}px}}" for index in range(4)
    )
    css_errors = post_build_repair.generated_frontend_workspace_source_violations(
        "src/styles.css", sparse_css, contract
    )
    assert any("requires at least 8 meaningful rules" in error for error in css_errors)
    assert any("0 responsive breakpoints" in error for error in css_errors)
    assert any("no grid/flex layout" in error for error in css_errors)
    assert any("input/select/textarea controls" in error for error in css_errors)
    assert any("distinct design tokens" in error for error in css_errors)
    assert any("body theme" in error for error in css_errors)


def test_post_build_review_readiness_requires_all_current_quality_gates() -> None:
    accepted = {
        "test_result": {"status": "pass"},
        "fixture_result": {"status": "pass"},
        "ui_smoke": {"status": "pass"},
        "screenshots": ["candidate.png"],
        "screenshot_blocked": "",
    }
    assert post_build_repair.post_build_candidate_review_ready(accepted)

    for failed_gate in ("test_result", "fixture_result", "ui_smoke"):
        rejected = json.loads(json.dumps(accepted))
        rejected[failed_gate]["status"] = "fail"
        assert not post_build_repair.post_build_candidate_review_ready(rejected)

    no_visual_evidence = json.loads(json.dumps(accepted))
    no_visual_evidence["screenshots"] = []
    assert not post_build_repair.post_build_candidate_review_ready(no_visual_evidence)

    cli_only = json.loads(json.dumps(no_visual_evidence))
    cli_only["visual_surface_required"] = False
    cli_only["ui_smoke"]["status"] = "skipped"
    assert post_build_repair.post_build_candidate_review_ready(cli_only)


def test_frozen_cli_interaction_mode_does_not_require_visual_evidence() -> None:
    pipeline = {
        "design_context": {"visual_surface_required": False},
        "components": [
            {
                "canonical_goal_spec": {
                    "interaction_modes": ["cli"],
                }
            }
        ],
    }
    assert not run_local_pipeline_impl.candidate_visual_surface_required(pipeline)

    visual_pipeline = {
        "components": [
            {
                "canonical_goal_spec": {
                    "interaction_modes": ["web"],
                }
            }
        ],
    }
    assert run_local_pipeline_impl.candidate_visual_surface_required(visual_pipeline)


def test_frontend_repair_set_rejects_cross_owner_interface_drift(
    tmp_path: pathlib.Path,
) -> None:
    project = tmp_path / "candidate"
    (project / "output").mkdir(parents=True)
    (project / "output" / "background.png").write_bytes(b"png")
    html = """<header><h1>Studio</h1></header><main id="studio-grid" class="workspace">
    <button id="edit" data-action="edit">Edit</button><p id="status" role="status"></p>
    <img src="output/background.png" alt="Background"></main>"""
    script = """const edit=document.getElementById('edit');const status=document.getElementById('status');
    document.addEventListener('DOMContentLoaded',()=>{});document.querySelectorAll('[data-action]').forEach(
    button=>button.addEventListener('click',()=>{status.textContent=button.dataset.action;}));"""
    css = "#studio-grid{display:grid}"

    assert not post_build_repair.frontend_repair_set_violations(
        project,
        [
            {"path": "index.html", "content": html},
            {"path": "src/app.js", "content": script},
            {"path": "src/styles.css", "content": css},
        ],
        {},
    )
    drift = post_build_repair.frontend_repair_set_violations(
        project,
        [
            {"path": "index.html", "content": html},
            {
                "path": "src/app.js",
                "content": script + "\ndocument.getElementById('missing-control');",
            },
            {"path": "src/styles.css", "content": ".other{display:grid}"},
        ],
        {},
    )
    assert any("absent from accepted HTML" in error for error in drift)
    assert any("does not style the accepted main workspace owner" in error for error in drift)

    literal_bindings = "\n".join(
        [
            "document.querySelector('[data-action=\"edit\"]').addEventListener('click',()=>{status.textContent='edited'});",
            "document.querySelector('[data-action=\"save\"]').addEventListener('click',()=>{status.textContent='saved'});",
            "document.querySelector('[data-action=\"preview\"]').addEventListener('click',()=>{status.textContent='previewed'});",
        ]
    )
    action_html = html.replace(
        "</main>",
        '<button data-action="save">Save</button><button data-action="preview">Preview</button></main>',
    )
    assert not post_build_repair.frontend_repair_set_violations(
        project,
        [
            {"path": "index.html", "content": action_html},
            {"path": "src/app.js", "content": literal_bindings},
        ],
        {},
    )


def test_complex_workspace_rejects_button_only_regions_and_unmatched_css_js(
    tmp_path: pathlib.Path,
) -> None:
    project = tmp_path / "candidate"
    project.mkdir()
    contract = {
        "domain_keywords": ["Visual", "Novel", "Studio"],
        "capability_groups": [
            {"stage": "edit_story_graph", "terms": ["edit", "graph"]},
            {"stage": "validate_story_graph", "terms": ["validate", "graph"]},
            {"stage": "preview_story_branch", "terms": ["preview", "branch"]},
            {"stage": "export_project", "terms": ["export"]},
        ],
    }
    html = """<header><h1>Visual Novel Studio</h1><p id="status" role="status">Ready.</p></header>
    <main class="workspace"><section id="edit"><h2>Edit story graph</h2>
    <ul><li data-node-id="start">Start</li><li data-node-id="choice">Choice</li></ul>
    <button data-action="edit">Edit</button></section>
    <section id="validate"><h2>Validate graph</h2><button data-action="validate">Validate</button></section>
    <section id="preview"><h2>Preview branch</h2><button data-action="preview">Preview</button></section>
    <section id="export"><h2>Export project</h2><button data-action="export">Export</button></section>
    <section id="assets"><h2>Assets</h2><output id="assets-result">Assets ready</output></section>
    <canvas id="preview-canvas"></canvas><img src="data:image/png;base64,eA=="><img src="data:image/png;base64,eA==">
    </main><link rel="stylesheet" href="src/styles.css"><script src="src/app.js"></script>"""
    html_errors = post_build_repair.generated_frontend_workspace_source_violations(
        "index.html", html, contract
    )
    region_error = next(
        error
        for error in html_errors
        if "workspace regions containing only headings/buttons" in error
    )
    assert "#validate" in region_error
    assert "#preview" in region_error
    assert "#export" in region_error

    duplicate_html = html.replace(
        '<canvas id="preview-canvas"></canvas>',
        '<canvas id="preview-canvas"></canvas><output id="preview-canvas">Ready</output>',
    )
    duplicate_errors = post_build_repair.generated_frontend_workspace_source_violations(
        "index.html", duplicate_html, contract
    )
    assert any("duplicate DOM ids" in error and "preview-canvas" in error for error in duplicate_errors)

    script = """document.querySelector('[data-action="edit"]').addEventListener('click',()=>{
    prompt('Edit');});document.querySelector('[data-action="validate"]').addEventListener('click',()=>alert('ok'));
    document.querySelector('[data-action="export"]').addEventListener('click',()=>{});
    document.getElementById('edit').textContent='edited';document.getElementById('validate').textContent='valid';
    localStorage.setItem('story','{}');const blob=new Blob(['{}']);URL.createObjectURL(blob);"""
    script_errors = post_build_repair.generated_frontend_workspace_source_violations(
        "src/app.js", script, contract
    )
    assert any("blocking browser modal behavior" in error for error in script_errors)

    drift = post_build_repair.frontend_repair_set_violations(
        project,
        [
            {"path": "index.html", "content": html},
            {"path": "src/app.js", "content": script},
            {"path": "src/styles.css", "content": ".workspace{display:grid;max-width:80rem}#edit{padding:1rem}"},
        ],
        contract,
    )
    assert any("neither delegates by data-action nor binds each action" in error for error in drift)
    css_drift = next(error for error in drift if "CSS selectors cover only" in error)
    assert "#validate" in css_drift
    assert "#preview" in css_drift
    assert any("does not render to any accepted preview surface" in error for error in drift)
    assert any("canvas preview ids that JavaScript never draws" in error for error in drift)
    assert any("remains a single-column stack" in error for error in drift)

    solid_canvas_script = script + """
    const previewCanvas=document.getElementById('preview-canvas');
    const previewContext=previewCanvas.getContext('2d');
    previewContext.fillRect(0,0,100,100);"""
    solid_canvas_drift = post_build_repair.frontend_repair_set_violations(
        project,
        [
            {"path": "index.html", "content": html},
            {"path": "src/app.js", "content": solid_canvas_script},
        ],
        contract,
    )
    assert any("generic geometry operation" in error for error in solid_canvas_drift)

    false_tag_coverage = post_build_repair.frontend_repair_set_violations(
        project,
        [
            {"path": "index.html", "content": html},
            {"path": "src/styles.css", "content": ".workspace{display:grid;max-width:80rem}.section{padding:1rem}"},
        ],
        contract,
    )
    assert any("CSS selectors cover only" in error for error in false_tag_coverage)

    squeezed_columns = post_build_repair.frontend_repair_set_violations(
        project,
        [
            {"path": "index.html", "content": html},
            {
                "path": "src/styles.css",
                "content": ".workspace{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;max-width:800px}section{padding:1rem}",
            },
        ],
        contract,
    )
    assert any("desktop columns are estimated" in error for error in squeezed_columns)

    roomy_columns = post_build_repair.frontend_repair_set_violations(
        project,
        [
            {"path": "index.html", "content": html},
            {
                "path": "src/styles.css",
                "content": ".workspace{display:grid;grid-template-columns:repeat(2,1fr);gap:20px;max-width:800px}section{padding:1rem}",
            },
        ],
        contract,
    )
    assert not any("desktop columns are estimated" in error for error in roomy_columns)

    dom_contract = post_build_repair.frontend_dom_action_contract(html)
    preview_binding = next(
        item
        for item in dom_contract["action_region_bindings"]
        if item["action"] == "preview"
    )
    assert preview_binding["region_id"] == "preview"
    assert dom_contract["status_region_ids"] == ["status"]
    assert "preview-canvas" in dom_contract["preview_surface_ids"]

    css_contract = post_build_repair.frontend_css_selector_contract(html)
    assert css_contract["workspace_owner_selectors"] == [".workspace"]
    assert css_contract["minimum_region_coverage"] == 3
    assert css_contract["semantic_region_selector_groups"] == [
        ["#edit", "section"],
        ["#validate", "section"],
        ["#preview", "section"],
        ["#export", "section"],
        ["#assets", "section"],
    ]
    assert css_contract["required_form_control_selector"] == "input, select, textarea"
    assert css_contract["visual_asset_selectors"] == ["img"]
    assert css_contract["required_visual_asset_properties"] == [
        "width or max-width",
        "object-fit",
    ]
    assert css_contract["preview_surface_selectors"] == ["#preview-canvas"]
    assert css_contract["desktop_region_min_width_px"] == 320
    assert css_contract["minimum_regions_per_desktop_row"] == 2

    nested_asset_contract = post_build_repair.frontend_css_selector_contract(
        '<main class="workspace"><div id="asset-preview"><img src="a.png"></div></main>'
    )
    assert nested_asset_contract["visual_asset_selectors"] == [
        "#asset-preview img",
        "img",
    ]

    css_escape, css_retry_rule = (
        post_build_repair.frontend_stagnation_escape_contract(
            "src/styles.css", {"accepted_css_selector_contract": css_contract}
        )
    )
    assert css_escape == css_contract
    assert "semantic_region_selector_groups" in css_retry_rule
    assert "desktop_region_min_width_px * column_count" in css_retry_rule
    assert "Do not return the same max-width/column/gap values" in css_retry_rule
    assert "Do not follow JavaScript interface rules" in css_retry_rule
    assert "allowed_dom_ids" not in css_retry_rule

    javascript_escape, javascript_retry_rule = (
        post_build_repair.frontend_stagnation_escape_contract(
            "src/app.js",
            {
                "javascript_repair_interface": {
                    "canvas_preview_contract": {
                        "canvas_ids": ["preview-canvas"],
                        "minimum_drawing_operations": 2,
                    }
                }
            },
        )
    )
    assert javascript_escape["canvas_preview_contract"]["canvas_ids"] == [
        "preview-canvas"
    ]
    assert "allowed_content_bearing_operation" in javascript_retry_rule
    assert "single solid geometry draw" in javascript_retry_rule
    assert post_build_repair.frontend_repair_validation_distance(
        "CSS selectors cover only 1/7 accepted semantic regions; style at least 5"
    ) > post_build_repair.frontend_repair_validation_distance(
        "CSS must bound visual asset preview width inside the workspace; "
        "CSS must define object-fit for visual asset previews"
    )

    css_payload = post_build_repair.apply_frontend_repair_librarian_slice(
        "src/styles.css",
        {
            "repair_set_context": [{"path": "index.html", "content": html}],
            "accepted_sibling_replacements": [
                {"path": "index.html", "content": html}
            ],
            "ui_repair_brief": {},
            "accepted_css_selector_contract": css_contract,
        },
    )
    assert css_payload["repair_set_context"] == []
    assert css_payload["accepted_sibling_replacements"] == []
    assert css_payload["librarian_context_slice"]["retained_interface_contracts"] == [
        "ui_repair_brief",
        "accepted_css_selector_contract",
    ]
    assert (
        css_payload["librarian_context_slice"][
            "duplicate_sibling_source_characters_removed"
        ]
        == len(html) * 2
    )

    invalid_owner_script = script + "\ndocument.getElementById('edit').value='x';"
    invalid_owner_drift = post_build_repair.frontend_repair_set_violations(
        project,
        [
            {"path": "index.html", "content": html},
            {"path": "src/app.js", "content": invalid_owner_script},
        ],
        contract,
    )
    assert any(".value on non-form HTML owners" in error for error in invalid_owner_drift)


def test_ui_semantic_adapter_converts_owned_actions_without_inventing_product_ui() -> None:
    source = """<main><section id="story-graph-edit"><h2>Story graph</h2>
    <button onclick="editStoryGraph()">Edit</button><div id="graph-editor"></div>
    </section></main>"""
    contract = {
        "capability_groups": [
            {"stage": "edit_story_graph", "terms": ["edit", "graph"]},
            {"stage": "preview_story_branch", "terms": ["preview"]},
            {"stage": "generate_background", "terms": ["background"]},
            {"stage": "export_project", "terms": ["export"]},
        ]
    }

    adapted, actions = post_build_repair.ui_semantic_adapter.adapt_complex_workspace_html(
        source, contract
    )

    assert "onclick=" not in adapted
    assert 'data-action="editStoryGraph"' in adapted
    assert "data-node-id=" not in adapted
    assert "Start node" not in adapted
    assert "Choice node" not in adapted
    assert "<output" not in adapted
    assert actions == ["converted_inline_button_actions_to_data_action"]
    violations = post_build_repair.generated_frontend_workspace_source_violations(
        "index.html", adapted, contract
    )
    assert any("semantic controls" in item for item in violations)
    assert any("visible graph/tree nodes" in item for item in violations)

    missing_edit = """<main><section><h2>Story graph</h2>
    <button data-action="validate-story-graph">Validate graph</button></section>
    <section><h2>Preview branch</h2><button data-action="preview">Preview</button></section>
    <section><h2>Export project</h2><button data-action="export">Export</button></section></main>"""
    adapted_controls, control_actions = (
        post_build_repair.ui_semantic_adapter.adapt_complex_workspace_html(
            missing_edit, contract
        )
    )
    assert 'data-action="edit-story-graph"' not in adapted_controls
    assert adapted_controls == missing_edit
    assert control_actions == []


def test_ui_semantic_adapter_removes_stale_and_competing_frontend_owners() -> None:
    source = """<!doctype html><html><head>
    <link rel="stylesheet" href="styles.css">
    <link rel="stylesheet" href="src/styles.css">
    <script src="app.js"></script></head><body>
    <div id="root"></div><main><h1>Visual Novel Studio</h1>
    <section><h2>Story graph</h2><p>Ready.</p></section></main>
    <script src="src/app.js"></script>
    <script type="module" src="./src/main.js"></script></body></html>"""
    contract = {
        "capability_groups": [
            {"stage": "edit_story_graph", "terms": ["story", "graph"]},
        ]
    }

    adapted, actions = post_build_repair.ui_semantic_adapter.adapt_complex_workspace_html(
        source, contract
    )

    assert 'href="styles.css"' not in adapted
    assert 'src="app.js"' not in adapted
    assert "src/main.js" not in adapted
    assert 'id="root"' not in adapted
    assert adapted.count('href="src/styles.css"') == 1
    assert adapted.count('src="src/app.js"') == 1
    assert {
        "removed_stale_root_css_owner",
        "removed_stale_root_javascript_owner",
        "removed_competing_frontend_owner",
        "removed_orphaned_empty_root",
    }.issubset(actions)


def test_ui_semantic_adapter_only_reconciles_existing_status_and_output_interfaces() -> None:
    source = """<header><p role="status">Ready.</p></header><main>
    <section id="validate"><h2>Validate</h2><button data-action="validate-project">Validate</button></section>
    <section id="export"><h2>Export</h2><button data-action="export-project">Export</button></section>
    <section id="edit"><h2>Edit</h2><input id="title"><button data-action="edit">Edit</button></section>
    </main>"""
    contract = {
        "capability_groups": [
            {"stage": "validate_project", "terms": ["validate"]},
            {"stage": "export_project", "terms": ["export"]},
            {"stage": "edit_project", "terms": ["edit"]},
            {"stage": "preview_project", "terms": ["preview"]},
        ]
    }

    adapted, actions = post_build_repair.ui_semantic_adapter.adapt_complex_workspace_html(
        source, contract
    )

    assert 'id="workspace-status"' in adapted
    assert 'id="validate-project-result"' not in adapted
    assert 'id="export-project-result"' not in adapted
    assert "added_stable_workspace_status_id" in actions

    unterminated = source.replace("</main>", "")
    closed, close_actions = post_build_repair.ui_semantic_adapter.adapt_complex_workspace_html(
        unterminated, contract
    )
    assert closed.count("<main") == closed.count("</main>") == 1
    assert "closed_unterminated_main_owner" in close_actions

    accepted_with_outputs = adapted.replace(
        '<button data-action="validate-project">Validate</button>',
        '<button data-action="validate-project">Validate</button><output id="validate-project-result"></output>',
    ).replace(
        '<button data-action="export-project">Export</button>',
        '<button data-action="export-project">Export</button><output id="export-project-result"></output>',
    )
    javascript = """document.getElementById('missing-result').textContent='Missing fixed';
    document.getElementById('validate').textContent='Validated';
    document.getElementById('export').innerHTML='Exported';"""
    adapted_javascript, javascript_actions = (
        post_build_repair.ui_semantic_adapter.adapt_complex_workspace_javascript(
            javascript, accepted_with_outputs
        )
    )
    assert "missing-result" in adapted_javascript
    assert "getElementById('validate-project-result').textContent" in adapted_javascript
    assert "getElementById('export-project-result').innerHTML" in adapted_javascript
    assert "retargeted_region_result_write_to_output_interface" in javascript_actions

    canvas_html = accepted_with_outputs.replace(
        '<output id="validate-project-result"',
        '<canvas id="preview-canvas"></canvas><output id="validate-project-result"',
    )
    canvas_javascript, canvas_actions = (
        post_build_repair.ui_semantic_adapter.adapt_complex_workspace_javascript(
            "document.getElementById('preview-canvas').innerHTML='<p>Preview</p>';",
            canvas_html,
        )
    )
    assert "getElementById('validate-project-result').innerHTML" in canvas_javascript
    assert "retargeted_invalid_canvas_html_write_to_output_interface" in canvas_actions

    adapted_css, css_actions = (
        post_build_repair.ui_semantic_adapter.adapt_complex_workspace_css(
            "button { min-height: 44px; }"
        )
    )
    assert "input, select, textarea" not in adapted_css
    assert "min-height: 44px" in adapted_css
    assert css_actions == []

    retargeted_css, retarget_actions = (
        post_build_repair.ui_semantic_adapter.adapt_complex_workspace_css(
            ".workspace{display:grid}.section{padding:1rem}.section h2{margin:0}",
            adapted,
        )
    )
    assert ".section" not in retargeted_css
    assert "section{" in retargeted_css
    assert "section h2" in retargeted_css
    assert "retargeted_unowned_semantic_class_to_region_tag" in retarget_actions

    owned_class_html = adapted.replace(
        '<section id="validate">',
        '<section id="validate" class="section">',
    )
    owned_css, owned_actions = (
        post_build_repair.ui_semantic_adapter.adapt_complex_workspace_css(
            ".section{padding:1rem}input{min-height:44px}", owned_class_html
        )
    )
    assert ".section" in owned_css
    assert "retargeted_unowned_semantic_class_to_region_tag" not in owned_actions


def test_post_build_large_fixture_repair_keeps_exact_traceback_and_media_owners(
    tmp_path: pathlib.Path,
) -> None:
    for rel in (
        "demo/run_fixture.py",
        "backend/stages_part_02.py",
        "backend/image_adapters.py",
        "scripts/capture_workflow.py",
        "backend/orchestrator.py",
        "backend/stages.py",
        "backend/artifact_store.py",
    ):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# generated\n", encoding="utf-8")

    plan = run_local_pipeline_impl.compile_post_build_repair_plan(
        tmp_path,
        {
            "test_result": {
                "status": "failed",
                "argv": ["python", "-m", "pytest"],
                "stdout_tail": (
                    "backend\\stages_part_02.py:7: KeyError: 'story_graph'\n"
                ),
            },
            "fixture_result": {
                "status": "failed",
                "command": {
                    "stdout_tail": "Image generation adapter not available"
                },
                "blockers": [
                    "fixture produced fewer than four decoder-valid PNG files"
                ],
            },
            "screenshots": [],
        },
    )

    assert "media_generation_failure" in plan["failure_types"]
    assert plan["target_files"] == [
        "demo/run_fixture.py",
        "backend/stages_part_02.py",
        "backend/image_adapters.py",
        "scripts/capture_workflow.py",
        "backend/orchestrator.py",
    ]
    assert [action["path"] for action in plan["provider_actions"]] == plan[
        "target_files"
    ]


def test_post_build_fixture_repair_prioritizes_exact_pytest_traceback(
    tmp_path: pathlib.Path,
) -> None:
    for rel in (
        "demo/run_fixture.py",
        "tests/test_pipeline_part_02.py",
        "backend/image_adapters.py",
        "scripts/capture_workflow.py",
        "backend/orchestrator.py",
        "backend/stages.py",
    ):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# generated\n", encoding="utf-8")

    plan = run_local_pipeline_impl.compile_post_build_repair_plan(
        tmp_path,
        {
            "test_result": {
                "status": "failed",
                "argv": ["python", "-m", "pytest"],
                "stdout_tail": "tests\\test_pipeline_part_02.py:12: TypeError: fixture is not iterable",
            },
            "fixture_result": {
                "status": "failed",
                "command": {"stderr_tail": "AssertionError while validating sprite PNG"},
                "blockers": ["fixture produced fewer than two transparent sprite PNG files"],
            },
            "screenshots": [],
        },
    )

    assert plan["target_files"][:2] == [
        "demo/run_fixture.py",
        "tests/test_pipeline_part_02.py",
    ]
    assert len(plan["provider_actions"]) == 5


def test_post_build_fixture_self_traceback_does_not_expand_secondary_symptoms(
    tmp_path: pathlib.Path,
) -> None:
    for rel in (
        "demo/run_fixture.py",
        "tests/test_pipeline_part_02.py",
        "backend/image_adapters.py",
        "scripts/capture_workflow.py",
        "backend/orchestrator.py",
        "backend/stages.py",
    ):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# generated\n", encoding="utf-8")

    plan = run_local_pipeline_impl.compile_post_build_repair_plan(
        tmp_path,
        {
            "test_result": {
                "status": "failed",
                "argv": ["python", "-m", "pytest"],
                "stdout_tail": "tests\\test_pipeline_part_02.py:12: TypeError: fixture is not iterable",
            },
            "fixture_result": {
                "status": "failed",
                "command": {
                    "stderr_tail": "demo\\run_fixture.py:56: AssertionError"
                },
                "blockers": [
                    "required stage artifact missing: export_manifest.json",
                    "fixture produced fewer than four decoder-valid PNG files",
                    "fixture produced fewer than two transparent sprite PNG files",
                ],
            },
            "screenshots": [],
        },
    )

    assert plan["target_files"] == [
        "demo/run_fixture.py",
        "tests/test_pipeline_part_02.py",
    ]
    assert [action["path"] for action in plan["provider_actions"]] == plan[
        "target_files"
    ]
    fixture_diagnostic = json.loads(
        plan["target_diagnostics"]["demo/run_fixture.py"]
    )
    assert (
        fixture_diagnostic["command"]["stderr_tail"]
        == "demo\\run_fixture.py:56: AssertionError"
    )
    assert "tests\\test_pipeline_part_02.py:12" in plan[
        "target_diagnostics"
    ]["tests/test_pipeline_part_02.py"]


def test_mixed_deterministic_and_fixture_failures_keep_provider_repairs(
    tmp_path: pathlib.Path,
) -> None:
    for rel in ("demo/run_fixture.py", "backend/orchestrator.py", "index.html"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# generated\n", encoding="utf-8")

    plan = run_local_pipeline_impl.compile_post_build_repair_plan(
        tmp_path,
        {
            "test_result": {
                "status": "failed",
                "stdout_tail": "failed to fetch /api and required stage artifact missing",
            },
            "fixture_result": {
                "status": "failed",
                "blockers": ["required stage artifact missing: project.json"],
            },
            "screenshots": [],
        },
    )

    assert "frontend_backend_start_mismatch" in plan["failure_types"]
    assert "fixture_failure" in plan["failure_types"]
    assert [action["path"] for action in plan["provider_actions"]]


def test_deterministic_complexity_gate_requires_pillow_for_pil_imports() -> None:
    plan_doc = {
        "complexity_project_contract": {
            "contract_id": "complexity_project_contract_v1",
            "required_pipeline_stages": [
                "generate_background_assets",
                "generate_sprite_assets",
            ],
        }
    }
    valid_media_shells = [
        {
            "path": "backend/image_adapters.py",
            "content": (
                "from PIL import Image\nclass OfflinePngGenerator:\n"
                " def generate_background(self): image.save('background.png'); return 'PNG'\n"
                " def generate_sprite(self): image.save('sprite.png'); return 'RGBA PNG'\n"
            ),
        },
        {
            "path": "scripts/capture_workflow.py",
            "content": (
                "def capture_background(): generator.generate_background(); output_path.is_file(); output_path.read_bytes(); return {'sha256':'x','generator':'offline','path':'a.png'}\n"
                "def generate_sprite(): generator.generate_sprite(); output_path.is_file(); output_path.read_bytes(); return {'sha256':'y','generator':'offline','path':'s.png'}\n"
            ),
        },
        {
            "path": "demo/run_fixture.py",
            "content": "def run_fixture(): capture_background(); generate_sprite(); return sha256\n",
        },
        {"path": "requirements.txt", "content": "flask==2.1.2\n"},
    ]

    blockers = run_local_pipeline_impl.deterministic_complexity_blockers(
        goal="generate real background and sprite assets",
        plan_doc=plan_doc,
        component_pipeline={"components": []},
        files=valid_media_shells,
    )

    dependency_blockers = [
        blocker
        for blocker in blockers
        if blocker["kind"] == "external_dependency_contract_incomplete"
    ]
    assert len(dependency_blockers) == 1
    assert dependency_blockers[0]["files"] == [
        "requirements.txt",
        "backend/image_adapters.py",
    ]


def test_javascript_leaf_receives_exact_exported_symbol_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}
    captured_system: dict[str, str] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured_system["content"] = messages[0]["content"]
        captured.update(json.loads(messages[-1]["content"]))
        return json.dumps(
            {
                "path": "src/app.js",
                "content": (
                    "export function initializeApp() {\n"
                    "  const root = document.getElementById('app');\n"
                    "  if (!root) throw new Error('app root missing');\n"
                    "  root.dataset.ready = 'true';\n"
                    "  return root;\n"
                    "}\n\n"
                    "export function handleUserInput(value) {\n"
                    "  if (typeof value !== 'string') throw new TypeError('value');\n"
                    "  const normalized = value.trim();\n"
                    "  if (!normalized) return '';\n"
                    "  return normalized;\n"
                    "}\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    item, _raw = run_local_pipeline_impl.provider_generate_component_file(
        goal="build a visual novel studio",
        component={"id": "frontend"},
        component_pipeline={"components": [{"id": "frontend"}]},
        manifest_entry={
            "path": "src/app.js",
            "estimated_complexity": "medium",
            "responsibilities": ["initialize the editor and handle user input"],
            "expected_symbols": ["initializeApp", "handleUserInput"],
        },
        prior_manifest=[],
        completed_files=[
            {
                "path": "index.html",
                "content": "<html><body><main id='app' data-testid='app-root'>Studio</main></body></html>",
            }
        ],
        component_file_manifest=[{"path": "index.html"}, {"path": "src/app.js"}],
        repair_errors=[],
        model="local",
        timeout=10,
        phase_log_path=None,
        routing_policy=None,
    )

    contract = captured["required_symbol_contract"]
    assert contract["exact_names"] == ["initializeApp", "handleUserInput"]
    assert contract["declaration_forms"] == [
        "export function initializeApp(...)",
        "export function handleUserInput(...)",
    ]
    assert "private declaration is not published" in contract["publication_rule"]
    assert "overrides historical names" in contract["precedence_rule"]
    assert "CURRENT TARGET SYMBOL CONTRACT (highest precedence)" in captured_system["content"]
    assert "export function initializeApp(...)" in captured_system["content"]
    assert captured["javascript_local_import_contract"]["allowed_local_module_paths"] == []
    assert "no local JavaScript module import is allowed" in captured_system["content"]
    assert "Python backend files are not JavaScript modules" in captured_system["content"]
    assert captured["frontend_dom_binding_contract"]["allowed_existing_element_ids"] == ["app"]
    assert captured["frontend_dom_binding_contract"]["available_data_testids"] == ["app-root"]
    assert captured["frontend_dom_binding_contract"]["testid_to_element_id"] == {"app-root": "app"}
    assert captured["frontend_dom_binding_contract"]["exact_binding_examples"] == [
        'app-root: document.getElementById("app")'
    ]
    assert "EXACT DOM BINDING CONTRACT: allowed existing element ids are app" in captured_system["content"]
    assert "A data-testid is not an id" in captured_system["content"]
    assert 'EXACT EXISTING CONTROL BINDINGS (use these forms): app-root: document.getElementById("app")' in captured_system["content"]
    assert any("Never import CSS/SCSS" in rule for rule in captured["target_specific_rules"])
    assert item["path"] == "src/app.js"


def test_python_consumer_receives_dependency_api_allowlist_at_system_level(monkeypatch) -> None:
    captured_system: dict[str, str] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured_system["content"] = messages[0]["content"]
        return json.dumps(
            {
                "path": "tests/test_story_graph.py",
                "content": (
                    "from backend.story_graph import StoryGraph\n\n"
                    "def test_story_graph_round_trip(tmp_path):\n"
                    "    graph = StoryGraph()\n"
                    "    graph.add_node('start', {'text': 'hello'})\n"
                    "    graph.add_node('end', {'text': 'bye'})\n"
                    "    graph.add_edge('start', 'end')\n"
                    "    target = tmp_path / 'story.json'\n"
                    "    graph.save(target)\n"
                    "    loaded = StoryGraph.load(target)\n"
                    "    assert loaded is not None\n"
                    "    assert loaded.nodes\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    run_local_pipeline_impl.provider_generate_component_file(
        goal="build a visual novel studio",
        component={"id": "tests"},
        component_pipeline={"components": [{"id": "tests"}]},
        manifest_entry={
            "path": "tests/test_story_graph.py",
            "dependencies": ["backend/story_graph.py"],
            "estimated_complexity": "low",
            "responsibilities": ["exercise the published story graph API"],
        },
        prior_manifest=["backend/story_graph.py"],
        completed_files=[],
        prior_files=[
            {
                "path": "backend/story_graph.py",
                "content": (
                    "class StoryGraph:\n"
                    "    def add_node(self, key, payload): return payload\n"
                    "    def add_edge(self, source, target): return (source, target)\n"
                    "    def save(self, path): return path\n"
                    "    @classmethod\n"
                    "    def load(cls, path): return cls()\n"
                ),
            }
        ],
        component_file_manifest=[{"path": "tests/test_story_graph.py"}],
        repair_errors=[],
        model="local",
        timeout=10,
        phase_log_path=None,
        routing_policy=None,
    )

    system = captured_system["content"]
    assert "CURRENT PYTHON DEPENDENCY API ALLOWLIST (highest precedence)" in system
    assert "backend/story_graph.py: imports=[StoryGraph]" in system
    assert "StoryGraph.add_node(self, key, payload)" in system
    assert "StoryGraph.add_edge(self, source, target)" in system
    assert "StoryGraph.save(self, path)" in system
    assert "StoryGraph.load(cls, path)" in system
    assert "storygraph_instance = StoryGraph(...)" in system
    assert "storygraph_instance.add_node(key, payload)" in system
    assert "storygraph_instance.load(path)" in system
    assert "never move a method onto a different class instance" in system
    assert "Do not invent helper classes" in system


def test_python_current_manifest_symbol_names_override_historical_context(monkeypatch) -> None:
    captured: dict[str, object] = {}
    captured_system: dict[str, str] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured_system["content"] = messages[0]["content"]
        captured.update(json.loads(messages[-1]["content"]))
        return json.dumps(
            {
                "path": "backend/preview.py",
                "content": (
                    "class StoryPreview:\n"
                    "    def __init__(self, graph):\n"
                    "        self.graph = graph\n\n"
                    "    def render(self, node_id):\n"
                    "        if not node_id:\n"
                    "            raise ValueError('node_id')\n"
                    "        node = self.graph.get(node_id)\n"
                    "        if node is None:\n"
                    "            raise KeyError(node_id)\n"
                    "        return {'node_id': node_id, 'node': node}\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    item, _raw = run_local_pipeline_impl.provider_generate_component_file(
        goal="build a visual novel studio",
        component={"id": "backend"},
        component_pipeline={"components": [{"id": "backend"}]},
        manifest_entry={
            "path": "backend/preview.py",
            "estimated_complexity": "medium",
            "responsibilities": ["render a validated story preview"],
            "acceptance_checks": ["reject an empty node id and return the selected node"],
            "expected_symbols": ["StoryPreview"],
        },
        prior_manifest=[],
        completed_files=[],
        component_file_manifest=[{"path": "backend/preview.py"}],
        repair_errors=[],
        librarian_context_pack={
            "selected_items": [
                {
                    "kind": "historical_example",
                    "path": "backend/preview.py",
                    "content": "class StoryBranchPreview: pass",
                }
            ]
        },
        model="local",
        timeout=10,
        phase_log_path=None,
        routing_policy=None,
    )

    contract = captured["required_symbol_contract"]
    assert contract["exact_names"] == ["StoryPreview"]
    assert "class StoryPreview" in captured_system["content"]
    assert "historical name" in captured_system["content"]
    assert "CURRENT TARGET IMPLEMENTATION DEPTH (mandatory)" in captured_system["content"]
    assert "validator requires at least 10 nonblank implementation lines" in captured_system["content"]
    assert "Generate at least 14 nonblank useful implementation lines" in captured_system["content"]
    assert captured["implementation_generation_target"] == {
        "validator_minimum_nonblank_lines": 10,
        "generation_safety_target_nonblank_lines": 14,
        "rule": "The safety target absorbs counting/formatting variance; meet it with useful behavior only.",
    }
    assert "5 substantive statements" in captured_system["content"]
    assert "1 behavior units" in captured_system["content"]
    assert "one-statement save/load/preview wrappers are rejected" in captured_system["content"]
    assert "class StoryPreview" in item["content"]


def test_css_leaf_receives_selected_palette_and_quality_literals(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured.update(json.loads(messages[-1]["content"]))
        return json.dumps(
            {
                "path": "src/styles.css",
                "content": (
                    ":root {\n--canvas: #F4EFE8;\n--surface: #FFF9F2;\n--ink: #211A24;\n"
                    "--accent: #B94167;\n--space: 1rem;\n--radius: .8rem;\n}\n"
                    "main { display: grid; grid-template-areas: 'tree editor'; gap: var(--space); "
                    "max-inline-size: 80rem; color: var(--ink); background: var(--canvas); }\n"
                    "button { color: var(--surface); background: var(--accent); transition: 120ms; }\n"
                    "button:hover { opacity: .9; }\nbutton:focus-visible { outline: 2px solid var(--accent); }\n"
                    "@media (max-width: 50rem) { main { grid-template-areas: 'tree' 'editor'; } }\n"
                    "@media (prefers-reduced-motion: reduce) { * { transition: none; } }\n"
                ),
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    item, _raw = run_local_pipeline_impl.provider_generate_component_file(
        goal="build a visual novel studio",
        component={"id": "frontend"},
        component_pipeline={
            "components": [{"id": "frontend"}],
            "design_context": {
                "design_contract": {
                    "selected_direction_name": "Narrative Atelier",
                    "design_tokens": {
                        "color": {
                            "canvas": "#F4EFE8",
                            "surface": "#FFF9F2",
                            "ink": "#211A24",
                            "accent": "#B94167",
                        }
                    },
                    "implementation_requirements": {
                        "minimum_css_custom_properties": 8,
                        "minimum_css_declarations": 24,
                    },
                }
            },
        },
        manifest_entry={
            "path": "src/styles.css",
            "estimated_complexity": "medium",
            "responsibilities": ["implement the selected responsive visual system"],
        },
        prior_manifest=[],
        completed_files=[],
        component_file_manifest=[{"path": "src/styles.css"}],
        repair_errors=[],
        model="local",
        timeout=10,
        phase_log_path=None,
        routing_policy=None,
    )

    contract = captured["css_quality_contract"]
    assert contract["selected_direction"] == "Narrative Atelier"
    assert contract["minimum_palette_values_to_use"] == 3
    assert "#B94167" in contract["required_palette_values"]
    assert "prefers-reduced-motion" in contract["required_literals"]
    assert "grid-template-areas" in contract["adaptable_focal_reference"]
    assert "max-inline-size" in contract["adaptable_focal_reference"]
    assert item["path"] == "src/styles.css"


def test_component_quality_failure_retries_only_affected_leaf_files(monkeypatch, tmp_path) -> None:
    component = {"id": "frontend", "required_paths": []}
    pipeline = {"components": [component], "merge_policy": {"required_final_files": []}}
    files = [
        {"path": "index.html", "content": "<main id='app'>Studio</main>"},
        {"path": "src/styles.css", "content": ":root { --ink: #211A24; }"},
        {
            "path": "src/app.js",
            "content": "export function initializeApp() { return document.getElementById('app'); }",
        },
    ]
    leaves = [
        {"path": "index.html", "dependencies": []},
        {"path": "src/styles.css", "dependencies": ["index.html"]},
        {
            "path": "src/app.js",
            "dependencies": ["index.html", "src/styles.css"],
            "expected_symbols": ["initializeApp"],
        },
    ]
    calls: list[dict[str, object]] = []
    quality_calls = 0

    def fake_split(**kwargs):
        calls.append(kwargs)
        return {
            "component_id": "frontend",
            "files": files,
            "component_file_manifest": leaves,
            "leaf_work_graph": {
                "leaves": [
                    {**leaf, "execution_plan": {"stages": ["build", "verify", "publish"]}}
                    for leaf in leaves
                ]
            },
            "quality_gate": {"status": "pass"},
            "self_test": {"status": "pass", "checks": []},
        }

    def fake_quality(**_kwargs):
        nonlocal quality_calls
        quality_calls += 1
        if quality_calls == 1:
            return {
                "status": "fail",
                "blockers": [
                    "src/app.js does not publish expected symbols: initializeApp",
                    "design quality: stylesheet does not respect prefers-reduced-motion",
                ],
                "affected_files": ["src/app.js", "src/styles.css"],
            }
        receipt = {
            "kind": "CGKNGeneratedComponentQualityValidation",
            "schema_version": 1,
            "component_id": "frontend",
            "status": "pass",
            "checks": ["mocked_source_contracts"],
            "validated_paths": sorted(item["path"] for item in files),
            "blockers": [],
            "affected_files": [],
        }
        canonical = json.dumps(
            receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        receipt["receipt_sha256"] = run_local_pipeline_impl.hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
        return receipt

    monkeypatch.setattr(run_local_pipeline_impl, "provider_transport_repair_attempts", lambda: 2)
    monkeypatch.setattr(run_local_pipeline_impl, "should_split_component_generation", lambda *args, **kwargs: (True, "test"))
    monkeypatch.setattr(run_local_pipeline_impl, "provider_generate_project_component_split", fake_split)
    monkeypatch.setattr(run_local_pipeline_impl, "provider_component_semantic_review", lambda *_args, **_kwargs: {"status": "pass"})
    monkeypatch.setattr(run_local_pipeline_impl, "validate_generated_component_quality", fake_quality)
    monkeypatch.setenv("CGKN_PROVIDER_RETRY_FAST", "1")

    result = run_local_pipeline_impl.provider_generate_project_by_components(
        "Build a visual novel studio.",
        pipeline,
        {},
        {},
        {},
        {},
        [],
        "gpt-test",
        30,
        checkpoint_dir=tmp_path / "provider_components",
        run_dir=tmp_path,
    )

    assert result["module_quality_validation"]["status"] == "pass"
    assert len(calls) == 2
    assert calls[1]["repair_target_files"] == ["src/app.js", "src/styles.css"]
    assert calls[1]["pending_context"]["file_manifest"] == leaves
    assert all("execution_plan" not in item for item in calls[1]["pending_context"]["file_manifest"])
    events = (tmp_path / "provider_phase_log.jsonl").read_text(encoding="utf-8")
    assert "component_quality_targeted_repair_planned" in events
    assert "cross_validation_feedforward_passed" in events
    assert "project_cross_validation_feedforward_passed" in events


def test_python_test_leaf_has_separate_bounded_output_contract(monkeypatch) -> None:
    monkeypatch.delenv("CGKN_PROVIDER_TEST_LEAF_MAX_LINES", raising=False)
    contract = run_local_pipeline_impl.leaf_implementation_depth_contract(
        {
            "path": "tests/test_artifact_contracts.py",
            "estimated_complexity": "medium",
            "responsibilities": ["validate generated artifact contracts"],
            "acceptance_checks": ["malformed artifacts are rejected"],
        }
    )

    assert contract["implementation_kind"] == "test_source"
    assert contract["maximum_nonblank_lines"] == 360

    monkeypatch.setenv("CGKN_PROVIDER_TEST_LEAF_MAX_LINES", "999")
    capped = run_local_pipeline_impl.leaf_implementation_depth_contract(
        {
            "path": "tests/test_pipeline.py",
            "estimated_complexity": "high",
        }
    )
    assert capped["maximum_nonblank_lines"] == 480


def test_json_test_fixture_has_representative_data_bound(monkeypatch) -> None:
    monkeypatch.delenv("CGKN_PROVIDER_TEST_FIXTURE_MAX_LINES", raising=False)
    contract = run_local_pipeline_impl.leaf_implementation_depth_contract(
        {
            "path": "tests/fixtures/suspicious_snap.json",
            "estimated_complexity": "medium",
            "responsibilities": ["represent one snap-and-fire trajectory"],
        }
    )
    assert contract["implementation_kind"] == "supporting_artifact"
    assert contract["maximum_nonblank_lines"] == 180

    content = "{\n" + ",\n".join(
        f'  \"tick_{index}\": {index}' for index in range(181)
    ) + "\n}\n"
    receipt = run_local_pipeline_impl.analyze_leaf_implementation_depth(
        contract["path"],
        content,
        contract,
    )
    assert receipt["status"] == "FAIL"
    assert any("> 180" in blocker for blocker in receipt["blockers"])


def test_provider_text_rejects_length_truncated_output(monkeypatch) -> None:
    monkeypatch.setattr(run_local_pipeline_impl, "try_local_provider_text", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_resolve_api_credentials",
        lambda: {"api_key": "sk-test-secret-value", "base_url": "https://api.gptsapi.net/v1"},
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_post_json",
        lambda *_args, **_kwargs: (
            {
                "choices": [
                    {
                        "message": {"content": "{\"path\":\"backend/stages.py\",\"content\":\"partial\"}"},
                        "finish_reason": "length",
                    }
                ]
            },
            "",
        ),
    )

    with pytest.raises(
        run_local_pipeline_impl.ProviderOutputContractError,
        match="provider output truncated",
    ):
        run_local_pipeline_impl.provider_text(
            [{"role": "user", "content": "generate one bounded file"}],
            "gpt-5.4-nano",
            30,
            max_attempts=1,
            stage="component_file_generation",
            component="backend",
            target_file="backend/stages.py",
            max_tokens=5000,
        )


def test_exact_component_wrapper_is_normalized_without_accepting_wrong_component() -> None:
    wrapped = {
        "foundation": {
            "files": [{"path": "requirements.txt", "purpose": "dependencies"}],
        }
    }
    normalized = run_local_pipeline_impl.normalize_local_provider_doc(
        wrapped,
        stage="component_file_manifest",
        component="foundation",
    )

    assert normalized["component"] == "foundation"
    assert normalized["files"][0]["path"] == "requirements.txt"
    assert run_local_pipeline_impl.normalize_local_provider_doc(
        {"frontend": wrapped["foundation"]},
        stage="component_file_manifest",
        component="foundation",
    ) == {"frontend": wrapped["foundation"]}


def test_local_file_repair_adds_only_missing_requested_component_id() -> None:
    files = [{"path": "backend/orchestrator.py", "content": "READY = True\n"}]
    bare_leaf = {
        "path": "tests/test_projectpulse_part_03.py",
        "content": "import pytest\n\ndef test_clean():\n    assert True\n",
    }

    normalized = run_local_pipeline_impl.normalize_local_provider_doc(
        {"files": files},
        stage="file_repair",
        component="post_build",
    )
    conflicting = run_local_pipeline_impl.normalize_local_provider_doc(
        {"component_id": "frontend", "files": files},
        stage="file_repair",
        component="post_build",
    )
    normalized_bare_leaf = run_local_pipeline_impl.normalize_local_provider_doc(
        bare_leaf,
        stage="file_repair",
        component="post_build",
    )

    assert normalized == {"component_id": "post_build", "files": files}
    assert normalized_bare_leaf == {
        "component_id": "post_build",
        "files": [bare_leaf],
    }
    assert conflicting["component_id"] == "frontend"
    assert "exact requested target" in run_local_pipeline_impl.local_provider_contract_error(
        {"component_id": "post_build", "files": files},
        stage="file_repair",
        component="post_build",
        target_file="backend/record_service_cli.py",
    )
    assert not run_local_pipeline_impl.local_provider_contract_error(
        {
            "component_id": "post_build",
            "files": [{"path": "backend/record_service_cli.py", "content": "READY = True\n"}],
        },
        stage="file_repair",
        component="post_build",
        target_file="backend/record_service_cli.py",
    )


def test_local_file_repair_fallback_gets_a_bounded_correction_attempt(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CGNK_LOCAL_FALLBACK_PROVIDER_ATTEMPTS", "1")
    monkeypatch.delenv("CGNK_LOCAL_FILE_REPAIR_FALLBACK_ATTEMPTS", raising=False)

    assert run_local_pipeline_impl.local_provider_attempt_limit(
        "file_repair", force_transport_fallback=True
    ) == 2

    contract = run_local_pipeline_impl.local_provider_contract_prompt(
        "file_repair",
        "post_build",
        "projectpulse/model.py",
    )
    assert "exactly one files entry" in contract
    assert "projectpulse/model.py" in contract
    assert "Never return a sibling" in contract
    assert (
        '{"component_id":"post_build","files":[{"path":"projectpulse/model.py",'
        '"content":"COMPLETE CORRECTED SOURCE"}]}'
    ) in contract


def test_local_file_repair_bare_leaf_keeps_cleaned_source_without_shape_retry(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    calls: list[str] = []
    cleaned_source = (
        "import pytest\n"
        "from datetime import datetime, timezone\n\n"
        "def test_created_at_is_iso():\n"
        "    assert datetime.now(timezone.utc).isoformat()\n"
    )

    def fake_call(_task, _system, prompt, _timeout):
        calls.append(prompt)
        return {
            "ok": True,
            "text": json.dumps(
                {
                    "path": "tests/test_projectpulse_part_03.py",
                    "content": cleaned_source,
                }
            ),
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
        }

    monkeypatch.setenv("CGNK_LOCAL_FALLBACK_PROVIDER_ATTEMPTS", "1")
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "call_text_task_fallback",
        fake_call,
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "task_enabled",
        lambda _task: False,
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "model_routing_profile",
        lambda: "balanced",
    )

    raw = run_local_pipeline_impl.try_local_provider_text(
        [
            {"role": "system", "content": "Repair one candidate leaf."},
            {
                "role": "user",
                "content": json.dumps(
                    {"target_file": "tests/test_projectpulse_part_03.py"}
                ),
            },
        ],
        stage="file_repair",
        component="post_build",
        target_file="tests/test_projectpulse_part_03.py",
        timeout=30,
        phase_log_path=tmp_path / "phase.jsonl",
        force_transport_fallback=True,
    )

    response = json.loads(raw)
    assert len(calls) == 1
    assert response == {
        "component_id": "post_build",
        "files": [
            {
                "path": "tests/test_projectpulse_part_03.py",
                "content": cleaned_source,
            }
        ],
    }
    assert "datetime = None" not in response["files"][0]["content"]


def test_local_file_repair_fallback_retry_corrects_a_wrong_target(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    calls: list[str] = []

    def fake_call(_task, _system, prompt, _timeout):
        calls.append(prompt)
        if len(calls) == 1:
            response = {
                "component_id": "post_build",
                "files": [{"path": "projectpulse/cli.py", "content": "WRONG = True\n"}],
            }
        else:
            response = {
                "component_id": "post_build",
                "files": [{"path": "projectpulse/model.py", "content": "READY = True\n"}],
            }
        return {
            "ok": True,
            "text": json.dumps(response),
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
        }

    monkeypatch.setenv("CGNK_LOCAL_FALLBACK_PROVIDER_ATTEMPTS", "1")
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "call_text_task_fallback",
        fake_call,
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "task_enabled",
        lambda _task: False,
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "model_routing_profile",
        lambda: "balanced",
    )

    raw = run_local_pipeline_impl.try_local_provider_text(
        [
            {"role": "system", "content": "Repair one candidate leaf."},
            {"role": "user", "content": json.dumps({"target_file": "projectpulse/model.py"})},
        ],
        stage="file_repair",
        component="post_build",
        target_file="projectpulse/model.py",
        timeout=30,
        phase_log_path=tmp_path / "phase.jsonl",
        force_transport_fallback=True,
    )

    assert json.loads(raw)["files"][0]["path"] == "projectpulse/model.py"
    assert len(calls) == 2
    assert "exact requested target" in calls[1]


def test_local_post_build_test_repair_prompt_keeps_only_the_failing_leaf_and_apis() -> None:
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_01.py",
            "target_file_contents": [
                {
                    "path": "tests/test_projectpulse_part_01.py",
                    "content": "def test_add(tmp_path):\n    assert tmp_path\n",
                }
            ],
            "repair_set_context": [
                {"path": "projectpulse/cli.py", "content": "X" * 20000}
            ],
            "failure_log_summary": "Y" * 12000,
            "target_diagnostic": "assertion failed" * 500,
            "direct_cli_leaf_contract": {
                "test_contract": ["Use pytest top-level test functions."]
            },
            "exact_dependency_context": [
                {
                    "path": "projectpulse/service.py",
                    "selected_symbols": ["TaskService"],
                    "source_excerpt": "class TaskService:\n    pass\n" * 1000,
                }
            ],
            "strict_rules": ["Use tmp_path."],
            "validation_commands": [["python", "-m", "pytest", "-q"]],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
            prompt, "tests/test_projectpulse_part_01.py"
        )
    )

    assert compact["target_file"] == "tests/test_projectpulse_part_01.py"
    assert compact["local_repair_output_contract"]["files_count"] == 1
    assert compact["exact_dependency_context"][0]["path"] == "projectpulse/service.py"
    assert "repair_set_context" not in compact
    assert "failure_log_summary" not in compact
    assert len(json.dumps(compact)) < len(prompt)


def test_local_post_build_direct_cli_implementation_prompt_keeps_exact_correction() -> None:
    prompt = json.dumps(
        {
            "target_file": "projectpulse/service.py",
            "target_file_contents": [
                {
                    "path": "projectpulse/service.py",
                    "content": "class TaskService:\n    pass\n",
                }
            ],
            "repair_set_context": [{"path": "projectpulse/cli.py", "content": "X" * 18000}],
            "failure_log_summary": "Y" * 9000,
            "target_diagnostic": "task_id must remain a string",
            "direct_cli_leaf_contract": {
                "required_symbols": ["TaskService"],
                "architecture": "Task model -> JSONRepository -> TaskService",
            },
            "direct_cli_runtime_coherence_repair": [
                "Write complete(self, task_id: str)."
            ],
            "previous_validation_errors": [
                "named direct CLI success output must use json.dumps for every command"
            ],
            "validation_error_history": ["first error", "second error"],
            "repair_base_selection": {"source": "closest_rejected_candidate"},
            "strict_rules": ["Return one file."],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_direct_cli_repair_prompt(
            prompt, "projectpulse/service.py"
        )
    )

    assert compact["target_file"] == "projectpulse/service.py"
    assert compact["direct_cli_leaf_contract"]["required_symbols"] == ["TaskService"]
    assert compact["direct_cli_runtime_coherence_repair"] == [
        "Write complete(self, task_id: str)."
    ]
    assert compact["highest_precedence_repair"]["previous_validation_errors"] == [
        "named direct CLI success output must use json.dumps for every command"
    ]
    assert compact["highest_precedence_repair"]["validation_error_history"] == [
        "first error",
        "second error",
    ]
    assert compact["repair_base_selection"]["source"] == "closest_rejected_candidate"
    assert "repair_set_context" not in compact
    assert len(json.dumps(compact)) < len(prompt)


def test_post_build_direct_cli_runtime_rules_make_service_types_concrete() -> None:
    rules = post_build_repair.direct_cli_runtime_coherence_repair_rules(
        "projectpulse/service.py",
        {"architecture": "Task model -> JSONRepository -> TaskService"},
    )

    assert any("task_id: str" in rule for rule in rules)
    assert any("datetime.now().isoformat()" in rule for rule in rules)
    assert any("task_id is not None: raise ValueError" in rule for rule in rules)

    cli_rules = post_build_repair.direct_cli_runtime_coherence_repair_rules(
        "projectpulse/cli.py",
        {"architecture": "Task model -> JSONRepository -> TaskService"},
    )
    assert any("service.delete(args.task_id).to_dict()" in rule for rule in cli_rules)
    assert any("exported_to" in rule and "imported" in rule for rule in cli_rules)
    assert any("print(result)" in rule and "AST boundary" in rule for rule in cli_rules)

    test_rules = post_build_repair.direct_cli_runtime_coherence_repair_rules(
        "tests/test_projectpulse_part_01.py",
        {"architecture": "Task model -> JSONRepository -> TaskService"},
    )
    assert any("Delete every module-level assignment to tmp_path" in rule for rule in test_rules)
    assert any("datetime = None" in rule and "Path = None" in rule for rule in test_rules)
    assert any("main(['projectpulse', ...])" in rule for rule in test_rules)
    assert any("document['tasks']" in rule for rule in test_rules)
    assert any("add(title)" in rule and "never be passed as a second argument" in rule for rule in test_rules)
    assert any("created.id" in rule and "complete(1)" in rule for rule in test_rules)

    readme_rules = post_build_repair.direct_cli_runtime_coherence_repair_rules(
        "README.md",
        {"package_name": "projectpulse"},
    )
    assert any("python -m projectpulse" in rule for rule in readme_rules)
    assert any("--mode merge" in rule and "--mode replace" in rule for rule in readme_rules)


def test_local_post_build_test_prompt_makes_tmp_path_scope_executable() -> None:
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_01.py",
            "target_file_contents": [
                {
                    "path": "tests/test_projectpulse_part_01.py",
                    "content": "from pathlib import Path\ntmp_path = Path('/tmp/x')\ndatetime = None\ndef test_x(tmp_path):\n    pass\n",
                }
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "direct_cli_runtime_coherence_repair": [
                "Delete every module-level assignment to tmp_path."
            ],
            "previous_validation_errors": [
                "named direct CLI generated tests must request tmp_path as a pytest parameter, never define it globally"
            ],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
            prompt, "tests/test_projectpulse_part_01.py"
        )
    )

    fixture_contract = compact["highest_precedence_repair"]["pytest_fixture_contract"]
    assert fixture_contract["forbidden_module_scope_assignment"] == "tmp_path = ..."
    assert fixture_contract["forbidden_cli_call_prefix"] == "main(['projectpulse', ...])"
    assert "datetime = None" in fixture_contract["forbidden_runtime_name_placeholders"]
    assert compact["highest_precedence_repair"]["exact_module_lines_to_delete"] == [
        "tmp_path = Path('/tmp/x')",
        "datetime = None",
    ]
    assert compact["highest_precedence_repair"][
        "required_runtime_imports_after_deletion"
    ] == {"datetime": "from datetime import datetime, timezone"}
    assert "exact_dependency_context" not in compact


def test_local_post_build_runtime_prompt_deletes_exact_none_placeholder() -> None:
    source = """import os
import json
datetime = None

from .model import Task

class JSONRepository:
    pass
"""
    prompt = json.dumps(
        {
            "target_file": "projectpulse/repository.py",
            "target_file_contents": [
                {"path": "projectpulse/repository.py", "content": source}
            ],
            "direct_cli_leaf_contract": {
                "required_symbols": ["JSONRepository"],
                "architecture": "Task model -> JSONRepository",
            },
            "direct_cli_runtime_coherence_repair": [
                "Delete every module-level runtime-name None placeholder."
            ],
            "previous_validation_errors": [
                "named direct CLI runtime leaves must not assign None placeholders to standard-library names at module scope: datetime"
            ],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_direct_cli_repair_prompt(
            prompt, "projectpulse/repository.py"
        )
    )

    repair = compact["highest_precedence_repair"]
    assert repair["exact_module_lines_to_delete"] == ["datetime = None"]
    assert repair["required_runtime_imports_after_deletion"] == {
        "datetime": "from datetime import datetime, timezone"
    }
    assert compact["target_file_contents"] == [
        {"path": "projectpulse/repository.py", "content": source}
    ]
    assert "repair_set_context" not in compact


def test_local_post_build_service_prompt_repairs_exact_malformed_import_handler() -> None:
    source = """import json
class TaskService:
    def import_from(self, path, mode):
        try:
            data = json.load(open(path, encoding='utf-8'))
            return len(data)
        except json.JSONDecodeError:
            return 2
"""
    prompt = json.dumps(
        {
            "target_file": "projectpulse/service.py",
            "target_file_contents": [
                {"path": "projectpulse/service.py", "content": source}
            ],
            "direct_cli_leaf_contract": {
                "required_symbols": ["TaskService"],
                "architecture": "Task model -> JSONRepository -> TaskService",
            },
            "previous_validation_errors": [
                "named direct CLI service import must raise ValueError for malformed input; it must not swallow data errors and return a CLI exit code"
            ],
            "repair_set_context": [
                {"path": "projectpulse/cli.py", "content": "X" * 12000}
            ],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_direct_cli_repair_prompt(
            prompt, "projectpulse/service.py"
        )
    )

    repair = compact["highest_precedence_repair"]
    expected = repair["exact_expected_complete_source"]
    assert repair["repair_kind"] == "exact_malformed_import_exception_boundary"
    assert "except json.JSONDecodeError as exc:" in expected
    assert "raise ValueError('Malformed input') from exc" in expected
    assert "            return 2" not in expected
    assert compact["target_file_contents"] == [
        {"path": "projectpulse/service.py", "content": source}
    ]
    assert "repair_set_context" not in compact
    assert len(json.dumps(compact)) < len(prompt)


def test_local_post_build_cli_prompt_repairs_exact_task_json_serialization() -> None:
    source = """import argparse
import json
import sys
def build_parser(): return argparse.ArgumentParser()
def main(argv=None):
    task = service.add('x')
    print(json.dumps(task.to_dict()))
    task = service.complete('1')
    print(json.dumps(task.to_dict()))
    result = service.delete('1')
    print(json.dumps(result))
    imported = service.import_from('in.json', 'merge')
    print(json.dumps({'imported': imported}))
    return 0
"""
    prompt = json.dumps(
        {
            "target_file": "projectpulse/cli.py",
            "target_file_contents": [
                {"path": "projectpulse/cli.py", "content": source}
            ],
            "direct_cli_leaf_contract": {
                "required_symbols": ["build_parser", "main"]
            },
            "previous_validation_errors": [
                "named direct CLI adapter must serialize each Task-returning success command through to_dict(): delete"
            ],
            "repair_set_context": [
                {"path": "projectpulse/service.py", "content": "X" * 12000}
            ],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_direct_cli_repair_prompt(
            prompt, "projectpulse/cli.py"
        )
    )

    repair = compact["highest_precedence_repair"]
    expected = repair["exact_expected_complete_source"]
    assert repair["repair_kind"] == "exact_task_command_json_serialization"
    assert repair["exact_source_replacements"] == [
        {
            "old": "json.dumps(result)",
            "new": "json.dumps(result.to_dict())",
            "occurrence_index": 1,
        }
    ]
    assert "print(json.dumps(result.to_dict()))" in expected
    assert "{'imported': imported}" in expected
    assert "repair_set_context" not in compact
    assert len(json.dumps(compact)) < len(prompt)


def test_local_post_build_readme_prompt_appends_only_missing_invocations() -> None:
    source = """# ProjectPulse
```bash
projectpulse --data-file tasks.json add "Example task"
projectpulse --data-file tasks.json list --status open
projectpulse --data-file tasks.json complete 1
projectpulse --data-file tasks.json delete 1
projectpulse --data-file tasks.json summary
projectpulse --data-file tasks.json export export.json
projectpulse --data-file tasks.json import import.json --mode merge
```
"""
    prompt = json.dumps(
        {
            "target_file": "README.md",
            "target_file_contents": [{"path": "README.md", "content": source}],
            "direct_cli_leaf_contract": {"package_name": "projectpulse"},
            "previous_validation_errors": [
                "named direct CLI README must include copyable --data-file usage examples for: python -m entry, import replace"
            ],
            "repair_set_context": [
                {"path": "projectpulse/cli.py", "content": "X" * 12000}
            ],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_direct_cli_repair_prompt(
            prompt, "README.md"
        )
    )

    repair = compact["highest_precedence_repair"]
    assert repair["repair_kind"] == "exact_readme_usage_completion"
    assert repair["exact_lines_to_append"] == [
        "projectpulse --data-file tasks.json import import.json --mode replace",
        "python -m projectpulse --data-file tasks.json summary",
    ]
    expected = repair["exact_expected_complete_source"]
    assert run_local_pipeline_impl.named_direct_cli_readme_contract_error(
        expected, "projectpulse"
    ) == ""
    assert "repair_set_context" not in compact
    assert len(json.dumps(compact)) < len(prompt)


def test_local_post_build_test_prompt_makes_versioned_task_projection_executable() -> None:
    source = """import json
def test_storage(tmp_path):
    data_path = tmp_path / 'tasks.json'
    main(['--data-file', str(data_path), 'add', 'one'])
    with open(data_path, 'r') as handle:
        tasks = json.load(handle)
    assert len(tasks) == 1
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_01.py",
            "target_file_contents": [
                {
                    "path": "tests/test_projectpulse_part_01.py",
                    "content": source,
                }
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "named direct CLI generated tests must inspect versioned data-file tasks through document['tasks'], not treat the json.load(...) document as a task list"
            ],
        }
    )

    compact_text = run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
        prompt, "tests/test_projectpulse_part_01.py"
    )
    compact = json.loads(compact_text)
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_versioned_storage_task_projection"
    assert repair["required_shape"] == [
        "document = json.load(handle)",
        "tasks = document['tasks']",
    ]
    assert compact["target_file_contents"][0]["content"] == source
    assert "exact_dependency_context" not in compact
    assert len(compact_text) < 5000


def test_local_post_build_test_prompt_makes_task_service_arity_executable() -> None:
    source = """def test_add(task_service, tmp_path):
    task_service.add('one', str(tmp_path / 'tasks.json'))
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_01.py",
            "target_file_contents": [
                {
                    "path": "tests/test_projectpulse_part_01.py",
                    "content": source,
                }
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "named direct CLI generated tests must call TaskService methods with exact bound argument counts: add(title)=1; invalid call add received 2"
            ],
        }
    )

    compact_text = run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
        prompt, "tests/test_projectpulse_part_01.py"
    )
    compact = json.loads(compact_text)
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_task_service_call_arity"
    assert "add(title)" in repair["exact_bound_signatures"]
    assert "never service.add(title, data_file)" in repair["repository_binding_rule"]
    assert repair["exact_source_replacements"] == [
        {
            "old": "task_service.add('one', str(tmp_path / 'tasks.json'))",
            "new": "task_service.add('one')",
        }
    ]
    assert repair["exact_expected_complete_source"] == source.replace(
        "task_service.add('one', str(tmp_path / 'tasks.json'))",
        "task_service.add('one')",
    )
    assert compact["target_file_contents"][0]["content"] == source
    assert "exact_dependency_context" not in compact
    assert len(compact_text) < 5000


def test_local_post_build_test_prompt_makes_string_task_id_executable() -> None:
    source = """def test_complete(task_service):
    task_service.add('one')
    task_service.complete(1)
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_01.py",
            "target_file_contents": [
                {
                    "path": "tests/test_projectpulse_part_01.py",
                    "content": source,
                }
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "named direct CLI generated tests must pass string task identifiers to complete/delete; integer literal 1 is invalid. Capture the Task returned by add() and pass created.id."
            ],
        }
    )

    compact_text = run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
        prompt, "tests/test_projectpulse_part_01.py"
    )
    compact = json.loads(compact_text)
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_task_id_from_add_result"
    assert "task_service.complete(created.id)" in repair["required_shape"]
    assert {
        "old": "task_service.add('one')",
        "new": "created = task_service.add('one')",
    } in repair["exact_source_replacements"]
    assert {
        "old": "task_service.complete(1)",
        "new": "task_service.complete(created.id)",
    } in repair["exact_source_replacements"]
    assert "byte-for-byte" in repair["rule"]
    assert "created.id" in repair["exact_expected_complete_source"]
    assert compact["target_file_contents"][0]["content"] == source
    assert "exact_dependency_context" not in compact
    assert len(compact_text) < 5000


def test_local_post_build_task_id_prompt_also_executes_detected_corrupt_read() -> None:
    source = """import pytest

def test_delete(repository):
    service = TaskService(repository)
    service.add('one')
    service.delete(1)

def test_corrupt(repository, tmp_path):
    with open(tmp_path / 'tasks.json', 'w') as handle:
        handle.write('invalid_json')
    with pytest.raises(ValueError) as excinfo:
        service = TaskService(repository)
    assert str(excinfo.value) == 'Invalid JSON format'
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_03.py",
            "target_file_contents": [
                {
                    "path": "tests/test_projectpulse_part_03.py",
                    "content": source,
                }
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "named direct CLI generated tests must pass string task identifiers to complete/delete; integer literal 1 is invalid. Capture the Task returned by add() and pass created.id."
            ],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
            prompt, "tests/test_projectpulse_part_03.py"
        )
    )
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_task_id_from_add_result"
    assert "service.delete(created.id)" in repair[
        "exact_expected_complete_source"
    ]
    assert "repository.load()" in repair["exact_expected_complete_source"]
    assert repair["exact_expected_complete_source"].count(
        "service = TaskService(repository)"
    ) == 1
    assert "read_text(encoding='utf-8') == 'invalid_json'" in repair[
        "exact_expected_complete_source"
    ]
    assert "Invalid JSON format" not in repair["exact_expected_complete_source"]
    assert {
        "old": "service = TaskService(repository)",
        "new": "repository.load()",
        "occurrence_index": 1,
    } in repair["exact_source_replacements"]
    assert {
        "old": "assert str(excinfo.value) == 'Invalid JSON format'",
        "new": "assert (tmp_path / 'tasks.json').read_text(encoding='utf-8') == 'invalid_json'",
    } in repair["exact_source_replacements"]


def test_local_post_build_test_prompt_projects_returned_task_id() -> None:
    source = """def test_complete(task_service):
    task_id = task_service.add('one')
    task_service.complete(task_id)
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_01.py",
            "target_file_contents": [
                {
                    "path": "tests/test_projectpulse_part_01.py",
                    "content": source,
                }
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "named direct CLI generated tests must pass the returned Task .id to complete/delete, not the Task object task_id; use task_id.id"
            ],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
            prompt, "tests/test_projectpulse_part_01.py"
        )
    )
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_task_id_from_add_result"
    assert {
        "old": "task_service.complete(task_id)",
        "new": "task_service.complete(task_id.id)",
    } in repair["exact_source_replacements"]
    assert "task_service.complete(task_id.id)" in repair[
        "exact_expected_complete_source"
    ]
    assert "byte-for-byte" in repair["rule"]


def test_local_post_build_test_prompt_replaces_title_with_returned_id() -> None:
    source = """def test_summary(task_service):
    task_service.add('Task 1')
    task_service.complete('Task 1')
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_02.py",
            "target_file_contents": [
                {"path": "tests/test_projectpulse_part_02.py", "content": source}
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "named direct CLI generated success tests must pass the Task .id returned by add() to complete/delete, not the title or guessed string literal 'Task 1'"
            ],
        }
    )

    compact_text = run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
        prompt, "tests/test_projectpulse_part_02.py"
    )
    compact = json.loads(compact_text)
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_task_id_from_add_result"
    assert "created = task_service.add('Task 1')" in repair[
        "exact_expected_complete_source"
    ]
    assert "task_service.complete(created.id)" in repair[
        "exact_expected_complete_source"
    ]
    assert "task_service.complete('Task 1')" not in repair[
        "exact_expected_complete_source"
    ]


def test_local_post_build_test_prompt_adds_same_module_service_fixture() -> None:
    source = """import pytest
from projectpulse.repository import JSONRepository
from projectpulse.service import TaskService

def test_list(task_service, capsys):
    assert task_service.list() == []
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_02.py",
            "target_file_contents": [
                {"path": "tests/test_projectpulse_part_02.py", "content": source}
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "named direct CLI generated tests must define service fixtures in the same module or conftest.py; missing local fixture definitions: task_service"
            ],
        }
    )

    compact_text = run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
        prompt, "tests/test_projectpulse_part_02.py"
    )
    compact = json.loads(compact_text)
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_local_task_service_fixture"
    assert "def task_service(tmp_path):" in repair["required_fixture_block"]
    assert any(
        line.strip() == "return TaskService(repository)"
        for line in repair["required_fixture_block"]
    )
    assert compact["target_file_contents"][0]["content"] == source
    assert len(compact_text) < 5000


def test_local_post_build_test_prompt_projects_listed_task_attribute() -> None:
    source = """def test_list(task_service):
    result = task_service.list()
    assert result[0]['title'] == 'Task 1'
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_02.py",
            "target_file_contents": [
                {"path": "tests/test_projectpulse_part_02.py", "content": source}
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "named direct CLI generated tests must access Task values returned by service.list() through attributes, for example result[0].title, not result[0]['title']"
            ],
        }
    )

    compact_text = run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
        prompt, "tests/test_projectpulse_part_02.py"
    )
    compact = json.loads(compact_text)
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_task_attribute_projection"
    assert repair["exact_source_replacements"] == [
        {"old": "result[0]['title']", "new": "result[0].title"}
    ]
    assert "result[0].title" in repair["exact_expected_complete_source"]
    assert "result[0]['title']" not in repair["exact_expected_complete_source"]


def test_local_post_build_test_prompt_removes_service_capsys_assumptions() -> None:
    source = """def test_list(task_service, capsys):
    result = task_service.list()
    captured = capsys.readouterr()
    assert result == []
    assert captured.out == '[]'
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_02.py",
            "target_file_contents": [
                {"path": "tests/test_projectpulse_part_02.py", "content": source}
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "named direct CLI generated service-layer tests must assert TaskService return values, not capsys output; remove capsys"
            ],
        }
    )

    compact_text = run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
        prompt, "tests/test_projectpulse_part_02.py"
    )
    compact = json.loads(compact_text)
    repair = compact["highest_precedence_repair"]
    expected = repair["exact_expected_complete_source"]

    assert repair["repair_kind"] == "exact_service_return_value_assertions"
    assert "def test_list(task_service):" in expected
    assert "assert result == []" in expected
    assert "capsys" not in expected
    assert "captured" not in expected


def test_local_post_build_test_prompt_executes_corrupt_storage_read() -> None:
    source = """def test_corrupt_storage(tmp_path):
    repository = JSONRepository(tmp_path / 'tasks.json')
    with pytest.raises(ValueError):
        service = TaskService(repository)
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_03.py",
            "target_file_contents": [
                {"path": "tests/test_projectpulse_part_03.py", "content": source}
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "named direct CLI corrupt-storage tests must execute repository.load() or a service read inside pytest.raises; constructing TaskService alone does not read or validate the JSON file"
            ],
        }
    )

    compact_text = run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
        prompt, "tests/test_projectpulse_part_03.py"
    )
    compact = json.loads(compact_text)
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_corrupt_storage_read_execution"
    assert repair["exact_source_replacements"] == [
        {
            "old": "service = TaskService(repository)",
            "new": "repository.load()",
            "occurrence_index": 0,
        }
    ]
    assert "repository.load()" in repair["exact_expected_complete_source"]
    assert "TaskService(repository)" not in repair["exact_expected_complete_source"]


def test_local_post_build_test_prompt_proves_corrupt_file_is_unchanged() -> None:
    source = """import pytest

def test_corrupt_storage(tmp_path):
    with open(tmp_path / 'tasks.json', 'w') as handle:
        handle.write('invalid_json')
    with pytest.raises(ValueError) as excinfo:
        repository.load()
    assert str(excinfo.value) == 'Invalid JSON format'
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_03.py",
            "target_file_contents": [
                {"path": "tests/test_projectpulse_part_03.py", "content": source}
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "AssertionError: assert 'Malformed input: parse failure' == 'Invalid JSON format'"
            ],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
            prompt, "tests/test_projectpulse_part_03.py"
        )
    )
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_corrupt_storage_unchanged_assertion"
    assert repair["exact_source_replacements"] == [
        {
            "old": "assert str(excinfo.value) == 'Invalid JSON format'",
            "new": "assert (tmp_path / 'tasks.json').read_text(encoding='utf-8') == 'invalid_json'",
        }
    ]
    assert "read_text(encoding='utf-8') == 'invalid_json'" in repair[
        "exact_expected_complete_source"
    ]
    assert "Invalid JSON format" not in repair["exact_expected_complete_source"]


def test_exact_expected_file_repair_uses_copy_only_valid_json_envelope() -> None:
    expected = "def test_complete(task_service):\n    task_service.complete(created.id)\n"
    compact = json.dumps(
        {
            "highest_precedence_repair": {
                "repair_kind": "exact_task_id_from_add_result",
                "exact_expected_complete_source": expected,
            }
        }
    )

    envelope_text = run_local_pipeline_impl.exact_expected_file_repair_envelope(
        compact,
        component="post_build",
        target_file="tests/test_projectpulse_part_03.py",
    )
    envelope = json.loads(envelope_text)

    assert envelope == {
        "component_id": "post_build",
        "files": [
            {
                "path": "tests/test_projectpulse_part_03.py",
                "content": expected,
            }
        ],
    }
    assert run_local_pipeline_impl.exact_expected_file_repair_envelope(
        json.dumps({"highest_precedence_repair": {}}),
        component="post_build",
        target_file="tests/test_projectpulse_part_03.py",
    ) == ""


def test_local_post_build_normalizes_overlong_same_goal_test_symbols() -> None:
    required = [
        "test_goal_01_add_creates_and_persists_one_valid_task",
        "test_goal_07_export_emits_the_current_task_records_without_ch",
        "test_goal_10_list_status_filtering_returns_only_open_or_compl",
    ]
    source = """def test_goal_01_add_creates_and_persists_one_valid_task():
    assert True

def test_goal_07_export_emits_the_current_task_records_without_changing():
    assert True

def test_goal_10_list_status_filtering_returns_only_open_or_completed_tasks():
    assert True
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_01.py",
            "target_file_contents": [
                {"path": "tests/test_projectpulse_part_01.py", "content": source}
            ],
            "direct_cli_leaf_contract": {
                "test_contract": ["pytest"],
                "required_symbols": required,
            },
            "previous_validation_errors": [
                "named direct CLI leaf must define required symbols: "
                + ", ".join(required[1:])
            ],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
            prompt, "tests/test_projectpulse_part_01.py"
        )
    )
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_frozen_goal_test_symbol_normalization"
    assert repair["exact_source_replacements"] == [
        {
            "old": "test_goal_07_export_emits_the_current_task_records_without_changing",
            "new": required[1],
        },
        {
            "old": "test_goal_10_list_status_filtering_returns_only_open_or_completed_tasks",
            "new": required[2],
        },
    ]
    expected = repair["exact_expected_complete_source"]
    assert f"def {required[1]}():" in expected
    assert f"def {required[2]}():" in expected
    assert "without_changing" not in expected
    assert "completed_tasks" not in expected


def test_local_post_build_duplicate_id_test_uses_bounded_substantive_micro() -> None:
    source = """import pytest
from projectpulse.model import Task
from projectpulse.repository import JSONRepository

def test_goal_11_duplicate_task_identifiers_are_rejected_without(task_service):
    with pytest.raises(ValueError):
        task_service.add('same')
        task_service.add('same')
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_02.py",
            "target_file_contents": [
                {"path": "tests/test_projectpulse_part_02.py", "content": source}
            ],
            "direct_cli_leaf_contract": {
                "test_contract": ["pytest"],
                "required_symbols": [
                    "test_goal_11_duplicate_task_identifiers_are_rejected_without"
                ],
            },
            "previous_validation_errors": [
                "named direct CLI duplicate-identifier tests must exercise repository.save() or service.import_from() with duplicate IDs"
            ],
            "exact_dependency_context": {"large": "omitted" * 10000},
        }
    )

    compact_text = run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
        prompt, "tests/test_projectpulse_part_02.py"
    )
    compact = json.loads(compact_text)
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "substantive_duplicate_identifier_test_repair"
    assert repair["required_goal_symbols"] == [
        "test_goal_11_duplicate_task_identifiers_are_rejected_without"
    ]
    assert "repository.save" in " ".join(repair["accepted_behavior_shapes"])
    checklist = " ".join(repair["required_import_test_checklist"])
    assert "import json" in checklist
    assert "function signature requests tmp_path" in checklist
    assert "top level is a list" in checklist
    assert "do not wrap it" in checklist
    assert "path that was never written" in checklist
    assert "Calling add(title) twice" in repair["forbidden_behavior"]
    assert compact["target_file_contents"][0]["content"] == source
    assert "exact_dependency_context" not in compact
    assert len(compact_text) < 6000


def test_duplicate_id_micro_retry_preserves_complete_split_test_module() -> None:
    prompt = json.dumps(
        {
            "previous_validation_errors": [
                "named direct CLI duplicate-identifier tests must exercise repository.save() or service.import_from()"
            ]
        }
    )

    instruction = (
        run_local_pipeline_impl.local_source_validation_regeneration_instruction(
            prompt, "file_repair"
        )
    )
    generic = run_local_pipeline_impl.local_source_validation_regeneration_instruction(
        "{}", "file_repair"
    )

    assert "Return the complete module from target_file_contents" in instruction
    assert "preserving every import, fixture, frozen test function name" in instruction
    assert "Modify only the currently named goal-11 duplicate-ID or goal-14 CLI-exit test body" in instruction
    assert "Discard the previous source entirely" not in instruction
    assert "Discard the previous source entirely" in generic


def test_local_post_build_test_prompt_recovers_syntax_without_raw_nested_json() -> None:
    source = """import json
def test_import(tmp_path):
    payload = []
    assert payload == []
"""
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_03.py",
            "target_file_contents": [
                {
                    "path": "tests/test_projectpulse_part_03.py",
                    "content": source,
                    "source": "last_syntax_valid_candidate",
                }
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "repair_base_selection": {"source": "last_syntax_valid_candidate"},
            "previous_validation_errors": [
                "post-build repaired Python syntax failure in tests/test_projectpulse_part_03.py: unterminated string literal"
            ],
            "target_diagnostic": "repair the import test",
        }
    )

    compact_text = run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
        prompt, "tests/test_projectpulse_part_03.py"
    )
    compact = json.loads(compact_text)
    repair = compact["highest_precedence_repair"]

    assert repair["repair_kind"] == "exact_python_syntax_completion"
    assert repair["repair_base_selection"]["source"] == "last_syntax_valid_candidate"
    assert "json.dump(payload, handle)" in repair["nested_json_rule"]
    assert compact["target_file_contents"][0]["content"] == source
    assert "truncated rejected source is omitted" in compact["local_prompt_scope"]
    assert len(compact_text) < 5000


def test_local_post_build_test_prompt_carries_exact_undefined_name_import() -> None:
    prompt = json.dumps(
        {
            "target_file": "tests/test_projectpulse_part_03.py",
            "target_file_contents": [
                {
                    "path": "tests/test_projectpulse_part_03.py",
                    "content": "def test_created():\n    assert datetime.now()\n",
                }
            ],
            "direct_cli_leaf_contract": {"test_contract": ["pytest"]},
            "previous_validation_errors": [
                "post-build repaired Python leaf contains undefined names in tests/test_projectpulse_part_03.py: datetime"
            ],
        }
    )

    compact = json.loads(
        run_local_pipeline_impl.compact_local_post_build_test_repair_prompt(
            prompt, "tests/test_projectpulse_part_03.py"
        )
    )
    contract = compact["highest_precedence_repair"][
        "python_undefined_name_repair_contract"
    ]

    assert compact["highest_precedence_repair"]["repair_kind"] == (
        "exact_python_undefined_name_import"
    )
    assert contract["missing_names_exact"] == ["datetime"]
    assert contract["required_ordinary_imports"] == {
        "datetime": "from datetime import datetime, timezone"
    }
    assert compact["highest_precedence_repair"]["exact_import_lines_to_insert"] == [
        "from datetime import datetime, timezone"
    ]
    assert "None placeholder" in contract["rule"]
    assert "exact_dependency_context" not in compact
    assert "direct_cli_leaf_contract" not in compact


def test_exact_component_bare_object_array_wrapper_is_bounded_and_normalized() -> None:
    entries = [
        {"path": "requirements.txt", "purpose": "runtime dependencies"},
        {"path": "pyproject.toml", "purpose": "build metadata"},
    ]

    normalized = run_local_pipeline_impl.normalize_local_provider_doc(
        {"foundation": entries},
        stage="component_file_manifest",
        component="foundation",
    )

    assert normalized == {"component": "foundation", "files": entries}
    assert run_local_pipeline_impl.normalize_local_provider_doc(
        {"frontend": entries},
        stage="component_file_manifest",
        component="foundation",
    ) == {"frontend": entries}
    assert run_local_pipeline_impl.normalize_local_provider_doc(
        {"foundation": []},
        stage="component_file_manifest",
        component="foundation",
    ) == {"foundation": []}
    assert run_local_pipeline_impl.normalize_local_provider_doc(
        {"foundation": ["requirements.txt"]},
        stage="component_file_manifest",
        component="foundation",
    ) == {"foundation": ["requirements.txt"]}


def test_component_manifest_timeout_cap_is_bounded(monkeypatch) -> None:
    monkeypatch.delenv("CGNK_PROVIDER_COMPONENT_MANIFEST_TIMEOUT_CAP", raising=False)
    assert run_local_pipeline_impl.provider_component_manifest_timeout_cap() == 90

    monkeypatch.setenv("CGNK_PROVIDER_COMPONENT_MANIFEST_TIMEOUT_CAP", "120")
    assert run_local_pipeline_impl.provider_component_manifest_timeout_cap() == 120

    monkeypatch.setenv("CGNK_PROVIDER_COMPONENT_MANIFEST_TIMEOUT_CAP", "999")
    assert run_local_pipeline_impl.provider_component_manifest_timeout_cap() == 120

    monkeypatch.setenv("CGNK_PROVIDER_COMPONENT_MANIFEST_TIMEOUT_CAP", "1")
    assert run_local_pipeline_impl.provider_component_manifest_timeout_cap() == 30


def test_local_manifest_normalizes_generic_component_object_wrapper() -> None:
    wrapped = {
        "component": {
            "id": "foundation",
            "files": [{"path": "requirements.txt", "purpose": "stdlib dependencies"}],
        }
    }
    normalized = run_local_pipeline_impl.normalize_local_provider_doc(
        wrapped,
        stage="component_file_manifest",
        component="foundation",
    )
    assert normalized["component"] == "foundation"
    assert normalized["files"][0]["path"] == "requirements.txt"
    assert run_local_pipeline_impl.local_provider_contract_error(
        {
            "component": {"id": "foundation"},
            "files": [{"path": "requirements.txt"}],
        },
        stage="component_file_manifest",
        component="foundation",
        target_file="",
    ) == ""
    assert run_local_pipeline_impl.provider_manifest_component_id(
        {"component": {"id": "foundation", "goal": "foundation setup"}}
    ) == "foundation"


def test_api_manifest_uses_the_same_bounded_component_wrapper_normalization(monkeypatch) -> None:
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_text",
        lambda *args, **kwargs: json.dumps(
            {
                "component": {
                    "id": "foundation",
                    "files": [
                        {
                            "path": "requirements.txt",
                            "purpose": "declare standard-library runtime",
                            "dependencies": [],
                            "estimated_complexity": "low",
                        }
                    ],
                }
            }
        ),
    )

    manifest = run_local_pipeline_impl.provider_component_file_manifest(
        goal="Build a local application.",
        component={"id": "foundation", "required_paths": ["requirements.txt"]},
        component_pipeline={"components": [{"id": "foundation"}], "merge_policy": {}},
        prior_manifest=[],
        repair_errors=[],
        model="gpt-test",
        timeout=30,
        phase_log_path=None,
        routing_policy=None,
    )

    assert [item["path"] for item in manifest] == ["requirements.txt"]


def test_provider_manifest_prompt_uses_project_relative_path_example(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured["payload"] = json.loads(messages[-1]["content"])
        return json.dumps(
            {
                "component": "foundation",
                "files": [
                    {
                        "path": "requirements.txt",
                        "purpose": "declare standard-library runtime",
                        "dependencies": [],
                        "estimated_complexity": "low",
                    }
                ],
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)

    run_local_pipeline_impl.provider_component_file_manifest(
        goal="Build a local application.",
        component={"id": "foundation", "required_paths": ["requirements.txt"]},
        component_pipeline={"components": [{"id": "foundation"}], "merge_policy": {}},
        prior_manifest=[],
        repair_errors=[],
        model="gpt-test",
        timeout=30,
        phase_log_path=None,
        routing_policy=None,
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["required_output_shape"]["files"][0]["path"] == "requirements.txt"
    assert all("project root" in rule or "component/" not in rule for rule in payload["manifest_rules"])


def test_provider_manifest_normalizes_only_bounded_array_aliases() -> None:
    entry = {"path": "requirements.txt", "purpose": "dependencies"}
    for alias in ("file_manifest", "manifest"):
        normalized = run_local_pipeline_impl.normalize_provider_doc(
            {"component": "foundation", alias: [entry]},
            stage="component_file_manifest",
            component="foundation",
        )
        assert normalized["files"] == [entry]

    ambiguous = run_local_pipeline_impl.normalize_provider_doc(
        {"component": "foundation", "file_manifest": [entry], "manifest": [entry]},
        stage="component_file_manifest",
        component="foundation",
    )
    assert "files" not in ambiguous


def test_provider_manifest_accepts_only_a_nonempty_bare_object_array() -> None:
    parsed = run_local_pipeline_impl.parse_provider_manifest_doc(
        json.dumps([{"path": "requirements.txt", "purpose": "dependencies"}]),
        component="foundation",
    )
    assert parsed["component"] == "foundation"
    assert parsed["files"][0]["path"] == "requirements.txt"

    for invalid in ("[]", '["requirements.txt"]'):
        try:
            run_local_pipeline_impl.parse_provider_manifest_doc(invalid, component="foundation")
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"invalid bare manifest must be rejected: {invalid}")


def test_provider_output_contract_error_keeps_bounded_redacted_diagnostics() -> None:
    raw = '{"error":"Authorization: Bearer sk-1234567890abcdefghijklmnop","files":[]}'
    exc = run_local_pipeline_impl.ProviderOutputContractError(
        "provider manifest missing files for component foundation",
        raw_output=raw,
        parsed_result={"component": "foundation"},
    )

    diagnostic = run_local_pipeline_impl.bounded_provider_diagnostic_output(exc.raw_output)

    assert run_local_pipeline_impl.provider_exception_error_type(exc) == "PROVIDER_OUTPUT_CONTRACT"
    assert "sk-1234567890abcdefghijklmnop" not in diagnostic
    assert "REDACTED" in diagnostic
    assert run_local_pipeline_impl.provider_component_error_is_retryable(
        run_local_pipeline_impl.provider_exception_error_type(exc),
        str(exc),
    )


def test_generation_repair_targets_failed_component_without_mutating_shared_feedforward_errors(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    calls: list[dict[str, object]] = []
    original_repair_errors = ["initial bounded validation signal"]

    def fake_generate(*args, **kwargs):
        calls.append(
            {
                "repair_errors": list(args[6]),
                "force_components": set(kwargs.get("force_components", set())),
            }
        )
        if len(calls) == 1:
            raise run_local_pipeline_impl.ProviderOutputContractError(
                "component backend generation failed: provider returned non-json project payload",
                raw_output="not-json",
            )
        return {
            "project_type": "test",
            "files": [{"path": "main.py", "content": "print('ok')\n"}],
        }

    monkeypatch.setattr(run_local_pipeline_impl, "provider_generate_project_by_components", fake_generate)
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_review_project",
        lambda *args, **kwargs: {"status": "pass", "issues": [], "review_summary": "pass"},
    )

    result = run_local_pipeline_impl.run_provider_semantic_review_with_repair(
        user_goal="Build a local app.",
        plan_doc={},
        blueprint={},
        online_inputs={},
        market_research={},
        component_pipeline={"components": [{"id": "foundation"}, {"id": "backend"}]},
        repair_errors=original_repair_errors,
        model="gpt-test",
        timeout=30,
        internal_context="",
        deadline=run_local_pipeline_impl.time.time() + 60,
        run_dir=tmp_path,
        out_dir=tmp_path / "project",
        result_path=tmp_path / "result.json",
        max_repair_attempts=1,
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
    )

    assert result["status"] == "pass"
    assert original_repair_errors == ["initial bounded validation signal"]
    assert calls[0]["force_components"] == set()
    assert calls[1]["force_components"] == {"backend"}
    assert calls[0]["repair_errors"] == calls[1]["repair_errors"]


def test_failed_forced_repair_preserves_last_pass_checkpoint(monkeypatch, tmp_path: pathlib.Path) -> None:
    component = {"id": "foundation", "required_paths": ["requirements.txt"]}
    pipeline = {"components": [component], "merge_policy": {"required_final_files": []}}
    snapshot = run_local_pipeline_impl.build_integration_feedforward_snapshot(
        goal="Build a local app.",
        component=component,
        component_pipeline=pipeline,
        plan_doc={},
        prior_component_results=[],
        prior_files=[],
        repair_errors=[],
    )
    spec_hash = run_local_pipeline_impl.provider_component_spec_hash(
        "Build a local app.",
        pipeline,
        component,
        snapshot["snapshot_sha256"],
    )
    checkpoint_dir = tmp_path / "provider_components"
    files = [{"path": "requirements.txt", "content": "# standard library only\n"}]
    run_local_pipeline_impl.write_provider_component_checkpoint(
        checkpoint_dir,
        component_id="foundation",
        spec_hash=spec_hash,
        status="pass",
        raw_output='{"component_id":"foundation"}',
        parsed_result={"component_id": "foundation", "files": files},
        files=files,
        semantic_review={"status": "pass"},
    )
    monkeypatch.setattr(run_local_pipeline_impl, "provider_transport_repair_attempts", lambda: 1)
    monkeypatch.setattr(run_local_pipeline_impl, "should_split_component_generation", lambda *args, **kwargs: (False, ""))
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_generate_project_component",
        lambda **kwargs: (_ for _ in ()).throw(
            run_local_pipeline_impl.ProviderOutputContractError(
                "provider returned non-json project payload",
                raw_output="not-json",
            )
        ),
    )

    try:
        run_local_pipeline_impl.provider_generate_project_by_components(
            "Build a local app.",
            pipeline,
            {},
            {},
            {},
            {},
            [],
            "gpt-test",
            30,
            checkpoint_dir=checkpoint_dir,
            force_components={"foundation"},
            run_dir=tmp_path,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("forced repair failure must propagate")

    checkpoint = json.loads((checkpoint_dir / "foundation.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "pass"
    failure = json.loads((checkpoint_dir / "failure_attempts" / "foundation.json").read_text(encoding="utf-8"))
    assert failure["status"] == "failed"
    assert failure["preserved_last_pass_checkpoint"] is True


def test_split_file_validation_allows_html_placeholder_attribute_but_rejects_stub_claim() -> None:
    accepted = run_local_pipeline_impl.validate_split_file_for_component(
        component_id="frontend",
        target_file="src/app.js",
        file_item={"path": "src/app.js", "content": "input.placeholder = 'Add a task';"},
        prior_manifest=[],
        completed_paths=set(),
    )
    assert accepted["path"] == "src/app.js"
    todo_label = run_local_pipeline_impl.validate_split_file_for_component(
        component_id="frontend",
        target_file="index.html",
        file_item={"path": "index.html", "content": "<main><h1>Task Board</h1><button>Todo</button></main>"},
        prior_manifest=[],
        completed_paths=set(),
    )
    assert todo_label["path"] == "index.html"
    try:
        run_local_pipeline_impl.validate_split_file_for_component(
            component_id="frontend",
            target_file="src/app.js",
            file_item={"path": "src/app.js", "content": "// placeholder implementation\nconst ready = false;"},
            prior_manifest=[],
            completed_paths=set(),
        )
    except RuntimeError as exc:
        assert "placeholder wording" in str(exc)
    else:
        raise AssertionError("placeholder implementation claim must be rejected")
    try:
        run_local_pipeline_impl.validate_split_file_for_component(
            component_id="frontend",
            target_file="src/app.js",
            file_item={"path": "src/app.js", "content": "// TODO: implement filter\nconst ready = false;"},
            prior_manifest=[],
            completed_paths=set(),
        )
    except RuntimeError as exc:
        assert "placeholder wording" in str(exc)
    else:
        raise AssertionError("TODO implementation marker must be rejected")


def test_frontend_asset_contract_requires_manifest_paths() -> None:
    files = [{"path": "index.html", "content": '<link href="/styles.css"><script src="/app.js"></script>'}]
    error = run_local_pipeline_impl.validate_frontend_asset_contract(
        files,
        ["index.html", "src/app.js", "src/styles.css"],
    )
    assert "/app.js" in error
    assert "/styles.css" in error
    assert run_local_pipeline_impl.validate_frontend_asset_contract(
        [{"path": "index.html", "content": '<link href="/src/styles.css"><script src="/src/app.js"></script>'}],
        ["index.html", "src/app.js", "src/styles.css"],
    ) == ""


def test_task_board_source_and_tests_must_cover_real_files_and_features() -> None:
    feature_prompt = "The task-board frontend must implement usable add, status toggle, delete, filter, localStorage persistence, and stable data-testid behavior."
    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "src/app.js", "content": "function addTask() {}\nfunction toggle() {}\nfunction deleteTask() {}"},
        stage="component_file_generation",
        component="frontend",
        target_file="src/app.js",
        prompt_text=feature_prompt,
    )
    assert "filter" in error
    assert "localStorage" in error

    test_error = run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "tests/test_app.py",
            "content": "from pathlib import Path\ndef test_js():\n    index_html = Path('index.html').read_text()\n    assert 'addTask(value)' in index_html\n",
        },
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text='{"prior_component_contract_excerpts":[{"path":"index.html"},{"path":"src/app.js"}]}',
    )
    assert "src/app.js" in test_error
    main_error = run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "tests/test_app.py",
            "content": "import main\ndef test_main():\n    main.__main__()\n",
        },
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text="",
    )
    assert "function named __main__" in main_error


def test_foundation_review_cannot_claim_missing_frontend_or_entrypoint() -> None:
    blocker = {
        "kind": "missing_entry_html|frontend_backend_mismatch",
        "component": "foundation",
        "files": ["requirements.txt"],
        "message": "missing frontend and main.py",
    }

    assert not run_local_pipeline_impl.component_review_blocker_in_scope(blocker, "foundation")
    assert run_local_pipeline_impl.component_review_blocker_in_scope(
        {"kind": "module_mismatch", "files": ["requirements.txt"]},
        "foundation",
    )


def test_semantic_review_uncertainty_is_warning_not_hard_blocker() -> None:
    blocker = run_local_pipeline_impl.normalize_semantic_blocker_evidence(
        {
            "kind": "generic",
            "severity": "hard",
            "component": "backend",
            "message": "The stage implementation cannot be verified from the provided snippets.",
        }
    )
    assert blocker["severity"] == "warning"
    assert blocker["evidence_basis"] == "review_uncertainty_not_direct_failure"

    direct = run_local_pipeline_impl.normalize_semantic_blocker_evidence(
        {
            "kind": "module_mismatch",
            "severity": "hard",
            "component": "frontend",
            "message": "src/app.js imports itself from ./app.js.",
        }
    )
    assert direct["severity"] == "hard"


def test_semantic_review_reason_schema_and_parenthetical_truncation_are_normalized() -> None:
    blocker = run_local_pipeline_impl.normalize_review_blockers(
        [
            {
                "severity": "hard",
                "reason": "README excerpt ends mid-sentence (truncated).",
                "repair_targets": ["Provide complete README evidence."],
            }
        ]
    )[0]
    normalized = run_local_pipeline_impl.normalize_semantic_blocker_evidence(blocker)

    assert normalized["message"] == "README excerpt ends mid-sentence (truncated)."
    assert normalized["repair_hint"] == "Provide complete README evidence."
    assert normalized["severity"] == "warning"


def test_component_review_fail_after_out_of_scope_filter_stays_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_text",
        lambda *args, **kwargs: json.dumps(
            {
                "component": "foundation",
                "verdict": "fail",
                "blockers": [],
                "summary": (
                    "Foundation owned files are present, but backend/*.py modules and tests "
                    "are not present in the provided manifest and cannot be verified."
                ),
            }
        ),
    )

    review = run_local_pipeline_impl.provider_semantic_component_review(
        goal="Build a CLI",
        component_id="foundation",
        component_files=[{"path": "requirements.txt", "content": "pytest>=8\n"}],
        component_pipeline={"components": [{"id": "foundation"}]},
        model="unused",
        timeout=30,
        phase_log_path=None,
        routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
    )

    assert len(review["blockers"]) == 1
    assert review["blockers"][0]["severity"] == "warning"
    assert review["blockers"][0]["evidence_basis"] in {
        "review_uncertainty_not_direct_failure",
        "review_out_of_scope_without_direct_failure",
    }


def test_component_review_rejects_cross_owner_missing_implementation_claims() -> None:
    assert not run_local_pipeline_impl.component_review_blocker_in_scope(
        {
            "kind": "generic",
            "message": "Foundation does not implement the required artifacts and pipeline stages.",
        },
        "foundation",
    )
    assert not run_local_pipeline_impl.component_review_blocker_in_scope(
        {
            "kind": "weak_tests",
            "message": "No backend-owned test files or fixtures are included.",
        },
        "backend",
    )
    assert not run_local_pipeline_impl.component_review_blocker_in_scope(
        {
            "kind": "weak_tests",
            "message": "No frontend test files are included in this component.",
        },
        "frontend",
    )
    assert not run_local_pipeline_impl.component_review_blocker_in_scope(
        {
            "kind": "generic",
            "message": "Foundation omits required owned backend modules under backend/.",
        },
        "foundation",
    )


def test_semantic_reducer_cannot_invent_hard_blocker(monkeypatch) -> None:
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_semantic_component_review",
        lambda **kwargs: {
            "component": "backend",
            "verdict": "fail",
            "blockers": [
                {
                    "kind": "generic",
                    "severity": "warning",
                    "component": "backend",
                    "files": [],
                    "message": "The selected excerpt is truncated and cannot be confirmed.",
                }
            ],
        },
    )
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_semantic_cross_component_review",
        lambda **kwargs: {"verdict": "pass", "blockers": []},
    )
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_semantic_final_reducer",
        lambda **kwargs: {
            "verdict": "fail",
            "blockers": [
                {
                    "kind": "generic",
                    "severity": "hard",
                    "component": "backend",
                    "files": [],
                    "message": "Invented promotion of review uncertainty.",
                }
            ],
            "repair_priority": ["backend"],
        },
    )

    result = run_local_pipeline_impl.split_semantic_review_pipeline(
        goal="Build a CLI",
        component_pipeline={"components": [{"id": "backend"}]},
        files=[{"path": "main.py", "content": "print('ok')\n"}],
        model="unused",
        timeout=30,
        phase_log_path=None,
        routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
        original_prompt_chars=100000,
    )

    assert result["status"] == "pass"
    assert len(result["structured_blockers"]) == 1
    assert result["structured_blockers"][0]["severity"] == "warning"


def test_explicit_stdlib_localstorage_goal_becomes_generation_constraints() -> None:
    constraints = run_local_pipeline_impl.infer_project_goal_constraints(
        "只使用 Python 标准库，原生 HTML/CSS/JavaScript，不依赖外部网络或数据库，使用 localStorage。"
    )
    joined = " ".join(constraints)

    assert "Do not add Flask" in joined
    assert "without frontend package or CDN" in joined
    assert "localStorage as the sole task persistence" in joined


def test_post_build_traceback_absolute_path_maps_to_candidate_file(tmp_path: pathlib.Path) -> None:
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    traceback = f'File "{tmp_path / "main.py"}", line 9\nSyntaxError: unterminated string literal'

    assert "main.py" in run_local_pipeline_impl.extract_post_build_target_files(tmp_path, traceback)


def test_post_build_invalid_pyproject_targets_configuration_not_frontend(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry.dependencies]\nflask == 2.1.2\n",
        encoding="utf-8",
    )
    (tmp_path / "index.html").write_text("<main>App</main>\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("export const app = 1;\n", encoding="utf-8")
    finalize_result = {
        "test_result": {
            "status": "failed",
            "stderr_tail": (
                f"ERROR: {tmp_path / 'pyproject.toml'}: "
                "Invalid value (at line 2, column 7)"
            ),
        },
        "screenshots": [],
    }

    failures = run_local_pipeline_impl.classify_post_build_failures(finalize_result)
    plan = run_local_pipeline_impl.compile_post_build_repair_plan(
        tmp_path,
        finalize_result,
    )

    assert "configuration_syntax_failure" in failures
    assert plan["target_files"][0] == "pyproject.toml"
    assert "src/app.js" not in plan["target_files"]


def test_generated_project_fixture_executes_and_validates_stage_artifacts(
    tmp_path: pathlib.Path,
) -> None:
    project_dir = tmp_path / "project"
    run_dir = tmp_path / "run"
    (project_dir / "demo").mkdir(parents=True)
    (run_dir / "discovery").mkdir(parents=True)
    (project_dir / "demo" / "run_fixture.py").write_text(
        (
            "import json\n"
            "from pathlib import Path\n"
            "\n"
            "def run_fixture():\n"
            "    record = {'stage': 'export', 'status': 'success', 'count': 1, 'items': ['project']}\n"
            "    Path('export_manifest.json').write_text(json.dumps(record), encoding='utf-8')\n"
            "    return record\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    print(json.dumps(run_fixture()))\n"
        ),
        encoding="utf-8",
    )
    (run_dir / "discovery" / "complexity_project_contract.json").write_text(
        json.dumps(
            {
                "required_pipeline_stages": ["export_project"],
                "required_stage_artifacts": ["export_manifest.json"],
                "required_artifact_fields": ["stage", "status", "count", "items"],
            }
        ),
        encoding="utf-8",
    )

    receipt = run_local_pipeline_impl.run_generated_project_fixture(
        project_dir,
        run_dir,
        timeout=30,
    )

    assert receipt["status"] == "pass"
    assert receipt["command"]["returncode"] == 0
    assert receipt["artifacts"] == [
        {
            "name": "export_manifest.json",
            "path": str(project_dir / "export_manifest.json"),
            "status": "pass",
            "missing_fields": [],
        }
    ]
    assert pathlib.Path(receipt["receipt_path"]).exists()


def test_generated_project_fixture_fails_when_declared_fixture_is_missing(
    tmp_path: pathlib.Path,
) -> None:
    project_dir = tmp_path / "project"
    run_dir = tmp_path / "run"
    project_dir.mkdir()
    (run_dir / "discovery").mkdir(parents=True)
    (run_dir / "discovery" / "complexity_project_contract.json").write_text(
        json.dumps(
            {
                "required_pipeline_stages": ["export_project"],
                "required_stage_artifacts": ["export_manifest.json"],
            }
        ),
        encoding="utf-8",
    )

    receipt = run_local_pipeline_impl.run_generated_project_fixture(
        project_dir,
        run_dir,
        timeout=30,
    )

    assert receipt["status"] == "failed"
    assert "demo/run_fixture.py is required but missing" in receipt["blockers"]
    assert "required stage artifact missing: export_manifest.json" in receipt["blockers"]


def test_local_split_python_and_stdlib_constraints_are_validated() -> None:
    prompt = "Use only the Python standard library at runtime. Use browser localStorage as the sole task persistence layer."
    assert "syntax invalid" in run_local_pipeline_impl.local_provider_contract_error(
        {"path": "main.py", "content": "print('broken)"},
        stage="component_file_generation",
        component="backend",
        target_file="main.py",
        prompt_text=prompt,
    )
    assert "localStorage" in run_local_pipeline_impl.local_provider_contract_error(
        {"path": "main.py", "content": "value = localStorage.getItem('tasks')\n"},
        stage="component_file_generation",
        component="backend",
        target_file="main.py",
        prompt_text=prompt,
    )
    assert run_local_pipeline_impl.local_provider_contract_error(
        {"path": "main.py", "content": "# localStorage belongs to the browser\nfrom http.server import SimpleHTTPRequestHandler\n"},
        stage="component_file_generation",
        component="backend",
        target_file="main.py",
        prompt_text=prompt,
    ) == ""


def test_native_localstorage_html_cannot_be_an_empty_app_shell() -> None:
    prompt = (
        "Use only the Python standard library at runtime. Use browser localStorage as the sole task persistence layer. "
        "Implement the frontend with native HTML, CSS, and JavaScript without frontend package or CDN dependencies."
    )
    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "index.html", "content": '<!doctype html><body><main id="app"></main></body>'},
        stage="component_file_generation",
        component="frontend",
        target_file="index.html",
        prompt_text=prompt,
    )
    assert "no visible initial interface" in error
    assert run_local_pipeline_impl.local_provider_contract_error(
        {"path": "index.html", "content": '<!doctype html><body><h1>Task Board</h1><button>Add task</button></body>'},
        stage="component_file_generation",
        component="frontend",
        target_file="index.html",
        prompt_text=prompt,
    ) == ""


def test_local_index_contract_requires_exact_split_asset_paths() -> None:
    prompt = (
        'Use only the Python standard library at runtime. Use browser localStorage as the sole task persistence layer. '
        '"component_file_manifest": ["index.html", "src/app.js", "src/styles.css"]'
    )
    error = run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "index.html",
            "content": '<body>Task Board controls<script src="/app.js"></script><link href="/styles.css"></body>',
        },
        stage="component_file_generation",
        component="frontend",
        target_file="index.html",
        prompt_text=prompt,
    )
    assert "src/app.js" in error
    assert "src/styles.css" in error
    assert run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "index.html",
            "content": '<body>Task Board controls<script src="/src/app.js"></script><link href="/src/styles.css"></body>',
        },
        stage="component_file_generation",
        component="frontend",
        target_file="index.html",
        prompt_text=prompt,
    ) == ""
    task_prompt = prompt + " Task-board frontend must implement usable add, toggle, delete, filter, localStorage and data-testid behavior."
    assert run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "src/app.js",
            "content": "function addTask(){}\nfunction toggle(){}\nfunction removeTask(){ tasks.splice(0, 1); }\nfunction applyFilter(){ return tasks.filter(Boolean); }\nlocalStorage.setItem('tasks', '[]');\n",
        },
        stage="component_file_generation",
        component="frontend",
        target_file="src/app.js",
        prompt_text=task_prompt,
    ) == ""
    assert "data-testid" in run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "index.html",
            "content": '<body>Task Board controls<script src="/src/app.js"></script><link href="/src/styles.css"></body>',
        },
        stage="component_file_generation",
        component="frontend",
        target_file="index.html",
        prompt_text=task_prompt,
    )
    assert "forbidden task API" in run_local_pipeline_impl.local_provider_contract_error(
        {"path": "main.py", "content": "from http.server import SimpleHTTPRequestHandler\nclass Handler(SimpleHTTPRequestHandler):\n    def do_POST(self): pass\n"},
        stage="component_file_generation",
        component="backend",
        target_file="main.py",
        prompt_text=prompt,
    )
    assert "comments only" in run_local_pipeline_impl.local_provider_contract_error(
        {"path": "requirements.txt", "content": "flask==2.0.1\n"},
        stage="component_file_generation",
        component="foundation",
        target_file="requirements.txt",
        prompt_text=prompt,
    )
    assert "undefined pytest fixtures: httpd" in run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_app.py", "content": "def test_server(httpd):\n    assert httpd\n"},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text=prompt,
    )
    assert "undefined names: socketserver" in run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_app.py", "content": "def test_server():\n    assert socketserver.TCPServer\n"},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text=prompt,
    )
    assert any(
        marker in run_local_pipeline_impl.local_provider_contract_error(
            {"path": "tests/test_app.py", "content": "def test_server(server):\n    server.serve_forever()\n"},
            stage="component_file_generation",
            component="tests",
            target_file="tests/test_app.py",
            prompt_text="def server(): pass\n" + prompt,
        )
        for marker in ("blocking serve_forever", "offline file assertions")
    )
    assert "offline file assertions" in run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "tests/test_app.py",
            "content": "from urllib.request import " + "url" + "open\ndef test_live():\n    assert " + "url" + "open('http://localhost')\n",
        },
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text=prompt,
    )
    assert "non-Python content" in run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_app.py", "content": "import ast\ndef test_html(index_html_content):\n    assert ast.parse(index_html_content)\n"},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text="def index_html_content(): pass\n" + prompt,
    )
    assert run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_app.py", "content": "def test_file(tmp_path):\n    assert tmp_path.exists()\n"},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text=prompt,
    ) == ""
    assert run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "tests/test_app.py",
            "content": "def test_module_guard():\n    main_source = \"if __name__ == '__main__': pass\"\n    assert \"__main__\" in main_source\n",
        },
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text=prompt,
    ) == ""
    assert "function named __main__" in run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "tests/test_app.py",
            "content": "import main\ndef test_bad_contract():\n    main.__main__()\n",
        },
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text=prompt,
    )
    assert run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "tests/test_app.py",
            "content": "from unittest.mock import patch\n@patch.object(object, '__str__')\ndef test_patch(mock_str):\n    assert mock_str\n",
        },
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text=prompt,
    ) == ""


def test_ollama_code_tasks_request_native_json_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.delenv("CGNK_LOCAL_MODEL_CONTEXT_WINDOW", raising=False)
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "ensure_ollama_running", lambda host: {"ok": True})
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "choose_ollama_model", lambda host, task: "unit-code")

    def fake_post(url, payload, timeout):
        captured.update(payload)
        return {"response": '{"path":"main.py","content":"print(1)\\n"}'}

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "post_json", fake_post)
    result = run_local_pipeline_impl.local_model_router._call_ollama("component_generation", "system", "prompt", 30)

    assert result["ok"] is True
    assert captured["format"] == "json"
    assert captured["options"]["num_predict"] == 4096
    assert captured["options"]["num_ctx"] == 16384


def test_local_generation_timeout_reaches_ollama_without_hidden_api_cap(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.delenv("CGNK_LOCAL_MODEL_REQUEST_TIMEOUT_CAP", raising=False)
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "ensure_ollama_running", lambda host: {"ok": True})
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "choose_ollama_model", lambda host, task: "unit-code")

    def fake_post(url, payload, timeout):
        captured["timeout"] = timeout
        return {"response": '{"foundation":[{"path":"requirements.txt"}]}' }

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "post_json", fake_post)
    result = run_local_pipeline_impl.local_model_router._call_ollama(
        "component_generation",
        "Stage: component_file_manifest. Do not include file contents.",
        "prompt",
        180,
    )

    assert result["ok"] is True
    assert captured["timeout"] == 180
    assert run_local_pipeline_impl.local_model_router.local_model_request_timeout("component_generation", 999) == 240
    assert run_local_pipeline_impl.local_model_router.local_model_request_timeout("customer_public_reply", 999) == 120


def test_ollama_manifest_can_use_a_smaller_bounded_prediction_budget(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("CGNK_LOCAL_MODEL_MANIFEST_NUM_PREDICT", "2048")
    monkeypatch.setenv("CGNK_LOCAL_MODEL_NUM_PREDICT", "4096")
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "ensure_ollama_running", lambda host: {"ok": True})
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "choose_ollama_model", lambda host, task: "unit-code")

    def fake_post(url, payload, timeout):
        captured.update(payload)
        return {"response": '{"foundation":[{"path":"requirements.txt"}]}' }

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "post_json", fake_post)
    result = run_local_pipeline_impl.local_model_router._call_ollama(
        "component_generation",
        "Stage: component_file_manifest. Do not include file contents.",
        "prompt",
        30,
    )

    assert result["ok"] is True
    assert captured["options"]["num_predict"] == 2048
    assert run_local_pipeline_impl.local_model_router.local_model_num_predict(
        "component_generation",
        system="ordinary component_file_generation",
    ) == 4096


def test_local_test_contract_prompt_avoids_fragile_embedded_source() -> None:
    contract = run_local_pipeline_impl.local_provider_contract_prompt(
        "component_file_generation",
        "tests",
        "tests/test_app.py",
    )

    assert "unittest.TestCase" in contract
    assert "pathlib.Path.read_text" in contract
    assert "do not embed multiline source snippets" in contract
    assert "never invent fixtures such as src/tasks.json" in contract


def test_local_test_contract_rejects_project_paths_missing_from_context() -> None:
    error = run_local_pipeline_impl.local_provider_contract_error(
        {
            "path": "tests/test_app.py",
            "content": "from pathlib import Path\ndef test_tasks():\n    assert Path('src/tasks.json').exists()\n",
        },
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text='{"prior_component_contract_excerpts":[{"path":"main.py"},{"path":"src/app.js"}]}',
    )

    assert "src/tasks.json" in error


def test_local_test_contract_rejects_assertin_javascript_template_against_index_html() -> None:
    content = """
from pathlib import Path
import unittest
class TestApp(unittest.TestCase):
    def test_dynamic_markup(self):
        index_html = Path('index.html').read_text()
        self.assertIn('<span>${task.text}</span>', index_html)
"""
    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_app.py", "content": content},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text='{"prior_component_contract_excerpts":[{"path":"index.html"},{"path":"src/app.js"}]}',
    )

    assert "instead of src/app.js" in error


def test_local_test_contract_rejects_python_launcher_marker_against_index_html() -> None:
    content = """
from pathlib import Path
import unittest
class TestApp(unittest.TestCase):
    def test_launcher(self):
        index_html = Path('index.html').read_text()
        self.assertIn('__main__', index_html)
"""
    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_app.py", "content": content},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text='{"prior_component_contract_excerpts":[{"path":"index.html"},{"path":"main.py"}]}',
    )

    assert "instead of main.py" in error


def test_local_task_board_test_contract_requires_all_owned_sources_and_behaviors() -> None:
    content = """
from pathlib import Path
import unittest
class TestApp(unittest.TestCase):
    def test_incomplete(self):
        index_html = Path('index.html').read_text()
        self.assertIn('data-testid', index_html)
"""
    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_app.py", "content": content},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text='The task-board frontend must implement usable add, status toggle, delete, filter, localStorage persistence, and stable data-testid behavior. {"prior_component_contract_excerpts":[{"path":"main.py"},{"path":"index.html"},{"path":"src/app.js"}]}',
    )

    assert "required generated sources" in error


def test_local_task_board_test_contract_accepts_complete_owned_source_checks() -> None:
    content = """
from pathlib import Path
import ast
import unittest
class TestApp(unittest.TestCase):
    def test_contracts(self):
        main_source = Path('main.py').read_text()
        index_html = Path('index.html').read_text()
        app_js = Path('src/app.js').read_text()
        ast.parse(main_source)
        self.assertIn('SimpleHTTPRequestHandler', main_source)
        self.assertIn('data-testid', index_html)
        self.assertIn('task-input', index_html)
        self.assertIn('task-list', index_html)
        self.assertIn('addTask', app_js)
        self.assertIn('toggle', app_js)
        self.assertIn('delete', app_js)
        self.assertIn('all-filter', index_html)
        self.assertIn('active-filter', index_html)
        self.assertIn('completed-filter', index_html)
        self.assertIn('localStorage', app_js)
"""
    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_app.py", "content": content},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text='The task-board frontend must implement usable add, status toggle, delete, filter, localStorage persistence, and stable data-testid behavior. {"prior_component_contract_excerpts":[{"path":"main.py"},{"path":"index.html"},{"path":"src/app.js"}]}',
    )

    assert error == ""


def test_local_task_board_test_contract_accepts_root_joined_source_reads() -> None:
    content = """
from pathlib import Path
import ast
import unittest
ROOT = Path(__file__).resolve().parents[1]
class TestApp(unittest.TestCase):
    def test_contracts(self):
        main_source = (ROOT / 'main.py').read_text()
        index_html = (ROOT / 'index.html').read_text()
        app_js = (ROOT / 'src/app.js').read_text()
        ast.parse(main_source)
        self.assertIn('SimpleHTTPRequestHandler', main_source)
        self.assertIn('data-testid', index_html)
        self.assertIn('task-input', index_html)
        self.assertIn('task-list', index_html)
        self.assertIn('addTask', app_js)
        self.assertIn('completed', app_js)
        self.assertIn('delete', app_js)
        self.assertIn('all-filter', index_html)
        self.assertIn('active-filter', index_html)
        self.assertIn('completed-filter', index_html)
        self.assertIn('localStorage', app_js)
"""
    error = run_local_pipeline_impl.local_provider_contract_error(
        {"path": "tests/test_app.py", "content": content},
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        prompt_text='The task-board frontend must implement usable add, status toggle, delete, filter, localStorage persistence, and stable data-testid behavior. {"prior_component_contract_excerpts":[{"path":"main.py"},{"path":"index.html"},{"path":"src/app.js"}]}',
    )

    assert error == ""


def test_local_task_board_retry_supplies_minimal_three_file_reference(monkeypatch) -> None:
    prompts: list[str] = []
    incomplete = {
        "path": "tests/test_app.py",
        "content": "from pathlib import Path\ndef test_html():\n    assert Path('index.html').read_text()\n",
    }
    complete = {
        "path": "tests/test_app.py",
        "content": """from pathlib import Path
import ast
import unittest
ROOT = Path(__file__).resolve().parents[1]
class TestApp(unittest.TestCase):
    def test_generated_contracts(self):
        main_source = (ROOT / 'main.py').read_text()
        index_html = (ROOT / 'index.html').read_text()
        app_js = (ROOT / 'src/app.js').read_text()
        ast.parse(main_source)
        self.assertIn('SimpleHTTPRequestHandler', main_source)
        for token in ('data-testid', 'task-input', 'task-list', 'all-filter', 'active-filter', 'completed-filter'):
            self.assertIn(token, index_html)
        for token in ('addTask', 'completed', 'delete', 'filter', 'localStorage'):
            self.assertIn(token, app_js)
""",
    }
    outputs = [json.dumps(incomplete), json.dumps(complete)]
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "task_enabled", lambda task: True)

    def fake_local(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        prompts.append(prompt)
        return {"ok": True, "provider": "ollama", "model": "unit-code", "text": outputs[len(prompts) - 1]}

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "call_text_task", fake_local)
    result = run_local_pipeline_impl.try_local_provider_text(
        [
            {"role": "system", "content": "Return JSON."},
            {
                "role": "user",
                "content": "The task-board frontend must implement usable add, status toggle, delete, filter, localStorage persistence, and stable data-testid behavior. main.py index.html src/app.js",
            },
        ],
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        timeout=30,
        phase_log_path=None,
    )

    assert result is not None
    assert len(prompts) == 2
    assert "test_generated_contracts" in prompts[1]
    assert "ROOT / 'src/app.js'" in prompts[1]
    assert "for label in ('All', 'Active', 'Completed')" in prompts[1]


def test_local_standard_library_requirements_retry_supplies_exact_comment_contract(monkeypatch) -> None:
    prompts: list[str] = []
    outputs = [
        '{"path":"requirements.txt","content":"pytest==8.0\\n"}',
        '{"path":"requirements.txt","content":"# Standard library runtime; no third-party runtime dependencies.\\n"}',
    ]
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "task_enabled", lambda task: True)

    def fake_local(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        prompts.append(prompt)
        return {"ok": True, "provider": "ollama", "model": "unit-code", "text": outputs[len(prompts) - 1]}

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "call_text_task", fake_local)
    raw = run_local_pipeline_impl.try_local_provider_text(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Use only the Python standard library at runtime."},
        ],
        stage="component_file_generation",
        component="foundation",
        target_file="requirements.txt",
        timeout=30,
        phase_log_path=None,
    )

    assert raw is not None
    assert len(prompts) == 2
    assert "return exactly one file" in prompts[1]
    assert "Do not list pytest" in prompts[1]


def test_local_unsafe_dynamic_test_retry_requires_direct_imports(monkeypatch) -> None:
    prompts: list[str] = []
    outputs = [
        '{"path":"tests/test_app.py","content":"def test_app():\\n    assert eval(\\\"1 + 1\\\") == 2\\n"}',
        '{"path":"tests/test_app.py","content":"from backend.record_service_cli import RecordService\\ndef test_app(tmp_path):\\n    service = RecordService(tmp_path / \'notes.json\')\\n    assert service.list() == []\\n"}',
    ]
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "task_enabled", lambda task: True)

    def fake_local(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        prompts.append(prompt)
        return {"ok": True, "provider": "ollama", "model": "unit-code", "text": outputs[len(prompts) - 1]}

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "call_text_task", fake_local)
    raw = run_local_pipeline_impl.try_local_provider_text(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": 'Test files: backend/record_service_cli.py tests/test_app.py'},
        ],
        stage="component_file_generation",
        component="tests",
        target_file="tests/test_app.py",
        timeout=30,
        phase_log_path=None,
    )

    assert raw is not None
    assert len(prompts) == 2
    assert "do not use eval, exec, compile" in prompts[1]
    assert "call them directly" in prompts[1]


def test_local_undefined_json_retry_requires_explicit_import(monkeypatch) -> None:
    prompts: list[str] = []
    outputs = [
        '{"path":"backend/service.py","content":"def encode(value):\\n    return json.dumps(value)\\n"}',
        '{"path":"backend/service.py","content":"import json\\ndef encode(value):\\n    return json.dumps(value)\\n"}',
    ]
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "task_enabled", lambda task: True)

    def fake_local(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        prompts.append(prompt)
        return {"ok": True, "provider": "ollama", "model": "unit-code", "text": outputs[len(prompts) - 1]}

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "call_text_task", fake_local)
    raw = run_local_pipeline_impl.try_local_provider_text(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Generate backend/service.py."},
        ],
        stage="component_file_generation",
        component="backend",
        target_file="backend/service.py",
        timeout=30,
        phase_log_path=None,
    )

    assert raw is not None
    assert len(prompts) == 2
    assert "these exact names are undefined: json" in prompts[1]
    assert "write `import json`" in prompts[1]


def test_backend_semantic_review_rejects_false_missing_index_blocker_for_simple_http_server() -> None:
    blocker = {
        "kind": "generic",
        "message": "The backend is missing logic to serve index.html at the root path.",
    }

    in_scope = run_local_pipeline_impl.component_review_blocker_in_scope(
        blocker,
        "backend",
        [{"path": "main.py", "content": "from http.server import SimpleHTTPRequestHandler\n"}],
    )

    assert in_scope is False


def test_backend_semantic_review_keeps_missing_index_blocker_without_static_handler() -> None:
    blocker = {
        "kind": "generic",
        "message": "The backend is missing logic to serve index.html at the root path.",
    }

    in_scope = run_local_pipeline_impl.component_review_blocker_in_scope(
        blocker,
        "backend",
        [{"path": "main.py", "content": "print('no server')\n"}],
    )

    assert in_scope is True


def test_local_source_retry_accumulates_all_rejected_constraints(monkeypatch, tmp_path: pathlib.Path) -> None:
    prompts: list[str] = []
    outputs = [
        '{"path":"src/app.js","content":"function addTask(){}\\nfunction toggle(){}\\nfunction applyFilter(){return tasks.filter(Boolean)}\\nlocalStorage.setItem(\'tasks\',\'[]\')"}',
        '{"path":"src/app.js","content":"function addTask(){}\\nfunction toggle(){}\\nfunction removeTask(){tasks.splice(0,1)}\\nfunction applyFilter(){return tasks.filter(Boolean)}"}',
        '{"path":"src/app.js","content":"function addTask(){}\\nfunction toggle(){}\\nfunction removeTask(){tasks.splice(0,1)}\\nfunction applyFilter(){return tasks.filter(Boolean)}\\nlocalStorage.setItem(\'tasks\',\'[]\')"}',
    ]
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "task_enabled", lambda task: True)

    def fake_local(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        prompts.append(prompt)
        return {"ok": True, "provider": "ollama", "model": "unit-code", "text": outputs[len(prompts) - 1]}

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "call_text_task", fake_local)
    raw = run_local_pipeline_impl.try_local_provider_text(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Task-board frontend must implement usable add, toggle, delete, filter and localStorage behavior."},
        ],
        stage="component_file_generation",
        component="frontend",
        target_file="src/app.js",
        timeout=30,
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
    )

    assert raw is not None
    assert "missing required behavior: delete" in prompts[2]
    assert "missing required behavior: localStorage" in prompts[2]


def test_local_empty_html_retry_keeps_explicit_visible_scaffold(monkeypatch, tmp_path: pathlib.Path) -> None:
    prompts: list[str] = []
    outputs = [
        '{"path":"index.html","content":"<html><body><div id=\\"app\\"></div></body></html>"}',
        '{"path":"index.html","content":"<html><head><link rel=\\"stylesheet\\" href=\\"src/styles.css\\"><script src=\\"src/app.js\\" defer></script></head><body><h1>Task Board</h1><input data-testid=\\"task-input\\"><button data-testid=\\"add-task\\">Add Task</button><button data-testid=\\"filter-all\\">All</button><button data-testid=\\"filter-active\\">Active</button><button data-testid=\\"filter-completed\\">Completed</button><ul data-testid=\\"task-list\\"></ul></body></html>"}',
    ]
    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "task_enabled", lambda task: True)

    def fake_local(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        prompts.append(prompt)
        return {"ok": True, "provider": "ollama", "model": "unit-code", "text": outputs[len(prompts) - 1]}

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "call_text_task", fake_local)
    raw = run_local_pipeline_impl.try_local_provider_text(
        [
            {"role": "system", "content": "Return JSON."},
            {
                "role": "user",
                "content": "Use browser localStorage as the sole task persistence layer without frontend package or CDN dependencies. "
                "The task-board frontend must implement usable controls and stable data-testid behavior.",
            },
        ],
        stage="component_file_generation",
        component="frontend",
        target_file="index.html",
        timeout=30,
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
    )

    assert raw is not None
    assert len(prompts) == 2
    assert "smaller does not mean blank" in prompts[1]
    assert "All/Active/Completed filter buttons" in prompts[1]


def test_api_504_triggers_local_model_fallback_and_ledger(monkeypatch, tmp_path: pathlib.Path) -> None:
    def fake_call_json_task(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        assert task == "component_repair"
        return {
            "ok": True,
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
            "text": '{"decision":"retry_component"}',
            "json": {
                "decision": "retry_component",
                "failed_component": "runtime_execution",
                "resume_from": ["foundation"],
                "repair_actions": [
                    {"component": "runtime_execution", "path": "", "instruction": "retry from checkpoint"}
                ],
                "validation_commands": [],
                "reason": "provider transport failed",
            },
        }

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "call_json_task", fake_call_json_task)
    error = (
        "component runtime_execution provider_api_request_failed after transport attempts: 3: "
        'provider_api_request_failed: HTTP 504: {"status":504} '
        '[endpoint=https://api.' + 'gpts' + 'api.net, retryable=true, provider_headers={"cf-ray":"abc-HKG","date":"Fri, 26 Jun 2026 13:31:45 GMT","server":"cloudflare"}]'
    )

    diagnostics = run_local_pipeline_impl.write_provider_transport_blocked_failure(
        tmp_path,
        tmp_path / "requested_project",
        error,
        {"status": "pending", "selected_model": "gpt-5.5", "stage": "provider_semantic_repair"},
        [],
        None,
        failed_component="runtime_execution",
    )

    fallback = diagnostics["provider_fallback_evidence"]
    assert fallback["primary_provider"] == "api_agent"
    assert fallback["primary_status"] == "failed_504"
    assert fallback["fallback_provider"] == "local_model_router"
    assert fallback["fallback_status"] == "planned"
    assert fallback["formal_chain_continued"] is False
    assert fallback["recovery_plan_ready"] is True
    assert fallback["recovery_plan"]["decision"] == "retry_component"
    assert fallback["requires_reverify"] is True

    records = formal_model_contract.read_ledger(tmp_path)
    assert any(row["provider"] == "api_agent" and row["status"] == "timeout" for row in records)
    assert any(row["provider"] == "local_model_router" and row["status"] == "ok" for row in records)
    assert formal_model_contract.evaluate_model_participation(
        context="repair",
        run_dir=tmp_path,
        usage_plan={"requires_model": True, "uses_model": True},
    )["status"] == "pass"


def test_component_provider_uses_local_coder_before_api(monkeypatch, tmp_path: pathlib.Path) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "task_enabled",
        lambda task: task == "component_generation",
    )

    def fake_local(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        calls.append(task)
        return {
            "ok": True,
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
            "text": '{"component_id":"backend","status":"ok","files":[{"path":"server/app.py","content":"print(1)"}]}',
        }

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "call_text_task", fake_local)
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_resolve_api_credentials",
        lambda: (_ for _ in ()).throw(AssertionError("API must not be called when local output is valid")),
    )
    phase_log = tmp_path / "provider_phase_log.jsonl"

    raw = run_local_pipeline_impl.provider_text(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Generate backend component."},
        ],
        "gpt-test",
        30,
        stage="component_generation",
        component="backend",
        phase_log_path=phase_log,
    )

    assert calls == ["component_generation"]
    assert json.loads(raw)["component_id"] == "backend"
    ledger = formal_model_contract.read_ledger(tmp_path)
    assert any(row["provider"] == "local_model_router" and row["status"] == "ok" for row in ledger)


def test_invalid_local_component_output_falls_back_to_api(monkeypatch, tmp_path: pathlib.Path) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "task_enabled",
        lambda task: task == "component_generation",
    )

    def fake_local(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        calls.append("local")
        return {
            "ok": True,
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
            "text": "This is not valid JSON.",
        }

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "call_text_task", fake_local)
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_resolve_api_credentials",
        lambda: {"api_key": "test-key", "base_url": "https://provider.example/v1"},
    )

    def fake_api(endpoint: str, payload: dict[str, object], token: str, timeout: int):
        calls.append("api")
        return {"choices": [{"message": {"content": '{"component_id":"backend","status":"ok","files":[]}'}}]}, ""

    monkeypatch.setattr(run_local_pipeline_impl.check_connectivity, "_post_json", fake_api)
    phase_log = tmp_path / "provider_phase_log.jsonl"

    raw = run_local_pipeline_impl.provider_text(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Generate backend component."},
        ],
        "gpt-test",
        30,
        stage="component_generation",
        component="backend",
        phase_log_path=phase_log,
    )

    assert calls == ["local", "local", "local", "local", "api"]
    assert '"component_id":"backend"' in raw
    ledger = formal_model_contract.read_ledger(tmp_path)
    assert any(row["provider"] == "local_model_router" and row["status"] == "failed" for row in ledger)
    assert any(row["provider"] == "api_agent" and row["status"] == "ok" for row in ledger)


def test_local_component_contract_normalizes_missing_component_id(monkeypatch, tmp_path: pathlib.Path) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "task_enabled",
        lambda task: task == "component_generation",
    )

    def fake_local(task: str, system: str, prompt: str, timeout: int) -> dict[str, object]:
        calls.append(prompt)
        text = (
            '{"files":[{"path":"server/app.py","content":"print(1)"}]}'
            if len(calls) == 1
            else '{"component_id":"backend","files":[{"path":"server/app.py","content":"print(1)"}]}'
        )
        return {"ok": True, "provider": "ollama", "model": "qwen2.5-coder:7b", "text": text}

    monkeypatch.setattr(run_local_pipeline_impl.local_model_router, "call_text_task", fake_local)
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_resolve_api_credentials",
        lambda: (_ for _ in ()).throw(AssertionError("corrected local output must avoid API fallback")),
    )

    raw = run_local_pipeline_impl.provider_text(
        [{"role": "system", "content": "Return JSON."}, {"role": "user", "content": "Generate backend."}],
        "gpt-test",
        30,
        stage="component_generation",
        component="backend",
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
    )

    assert len(calls) == 1
    assert json.loads(raw)["component_id"] == "backend"
    ledger = formal_model_contract.read_ledger(tmp_path)
    assert [row["status"] for row in ledger if row["provider"] == "local_model_router"] == ["ok"]


def test_large_component_repair_keeps_split_generation() -> None:
    policy = run_local_pipeline_impl.provider_component_prompt_policy()

    split, reason = run_local_pipeline_impl.should_split_component_generation(
        "backend",
        int(policy["max_prompt_chars_hard"]) + 1,
        repair_actions=[{"component": "backend", "path": "", "instruction": "repair backend"}],
    )

    assert split is True
    assert reason == "prompt_exceeds_hard_limit"


def test_local_component_repair_splits_before_hard_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "task_enabled",
        lambda task: task == "component_repair",
    )
    policy = run_local_pipeline_impl.provider_component_prompt_policy()

    split, reason = run_local_pipeline_impl.should_split_component_generation(
        "foundation",
        int(policy["local_model_max_prompt_chars"]) + 1,
        repair_actions=[{"component": "foundation", "path": "", "instruction": "repair foundation"}],
    )

    assert split is True
    assert reason == "prompt_exceeds_local_model_limit"


def test_large_component_uses_librarian_split_before_monolithic_prompt() -> None:
    policy = run_local_pipeline_impl.provider_component_prompt_policy()

    split, reason = run_local_pipeline_impl.should_split_component_generation(
        "backend",
        int(policy["librarian_split_prompt_chars"]) + 1,
    )

    assert split is True
    assert reason == "prompt_uses_librarian_split"


def test_semantic_repair_splits_component_label_and_preserves_localstorage_contract() -> None:
    pipeline = {
        "components": [
            {"id": "foundation"},
            {"id": "backend"},
            {"id": "frontend"},
            {"id": "tests"},
        ]
    }
    blocker = {
        "kind": "api_alignment",
        "severity": "hard",
        "component": "frontend, backend",
        "files": [],
        "message": "The product must remain fully local with localStorage and no backend dependency.",
        "repair_hint": "Remove backend API endpoints and remove all fetch calls; use localStorage only.",
    }

    parsed = run_local_pipeline_impl.parse_review_blocker(blocker, pipeline)
    plan = run_local_pipeline_impl.compile_repair_plan([blocker], {}, component_pipeline=pipeline)

    assert parsed["components"] == ["backend", "frontend"]
    assert parsed["persistence_contract"] == "browser_local"
    assert "frontend, backend" not in plan["affected_components"]
    assert plan["affected_components"] == ["backend", "frontend"]
    assert "frontend_localstorage_persistence" in plan["validation_checks"]
    assert "frontend_uses_fetch_api" not in plan["validation_checks"]
    prompts = "\n".join(run_local_pipeline_impl.repair_plan_component_instructions(plan)["frontend"])
    assert "localStorage" in prompts
    assert "do not invent a backend API" in prompts


def test_stylesheet_quality_requirement_is_not_misclassified_as_commonjs() -> None:
    pipeline = {
        "components": [
            {"id": "foundation"},
            {"id": "backend"},
            {"id": "frontend"},
            {"id": "tests"},
        ]
    }
    blocker = (
        "component quality validation failed: frontend: src/app.js imports JavaScript bindings "
        "from non-module src/styles.css; design quality: stylesheet requires at least two "
        "focal-composition signatures"
    )

    parsed = run_local_pipeline_impl.parse_review_blocker(blocker, pipeline)
    plan = run_local_pipeline_impl.compile_repair_plan([blocker], {}, component_pipeline=pipeline)

    assert parsed["kind"] == "generic_semantic_blocker"
    assert parsed["components"] == ["frontend"]
    assert run_local_pipeline_impl.repair_plan_provider_components(plan) == ["frontend"]


def test_structured_generic_blocker_preserves_file_evidence_and_deduplicates() -> None:
    pipeline = {
        "components": [
            {"id": "foundation"},
            {"id": "backend"},
            {"id": "frontend"},
            {"id": "media"},
            {"id": "tests"},
            {"id": "docs"},
        ]
    }
    blocker = {
        "kind": "artifact_schema_incomplete",
        "severity": "hard",
        "component": "backend",
        "files": ["backend/artifact_store.py", "docs/artifact_contract.md"],
        "message": "stage artifact schema fields missing: count, input_path, items",
        "repair_hint": "Implement every required artifact field.",
    }

    plan = run_local_pipeline_impl.compile_repair_plan(
        [blocker, blocker], {}, component_pipeline=pipeline
    )

    assert len(plan["parsed_blockers"]) == 1
    assert plan["affected_components"] == ["backend", "docs"]
    assert plan["affected_files"] == [
        "backend/artifact_store.py",
        "docs/artifact_contract.md",
    ]
    assert [(action["component"], action["path"]) for action in plan["provider_actions"]] == [
        ("backend", "backend/artifact_store.py"),
        ("docs", "docs/artifact_contract.md"),
    ]
    assert len(plan["must_disappear_blockers"]) == 1


def test_pending_semantic_refresh_keeps_parsed_file_hints() -> None:
    pipeline = {
        "components": [
            {"id": "backend"},
            {"id": "docs"},
        ]
    }
    pending = {
        "status": "pending",
        "stage": "provider_semantic_repair",
        "blockers": ["stage artifact schema fields missing: count, items"],
        "parsed_blockers": [
            {
                "kind": "generic_semantic_blocker",
                "raw": "stage artifact schema fields missing: count, items",
                "components": ["backend"],
                "files_hint": [
                    "backend/artifact_store.py",
                    "docs/artifact_contract.md",
                ],
                "severity": "hard",
                "repair_hint": "Implement the complete schema.",
            }
        ],
    }

    refreshed = run_local_pipeline_impl.refresh_pending_semantic_repair_plan(
        pending, {}, pipeline
    )

    assert refreshed["affected_components"] == ["backend", "docs"]
    assert refreshed["affected_files"] == [
        "backend/artifact_store.py",
        "docs/artifact_contract.md",
    ]
    assert [(action["component"], action["path"]) for action in refreshed["provider_actions"]] == [
        ("backend", "backend/artifact_store.py"),
        ("docs", "docs/artifact_contract.md"),
    ]
    assert refreshed["repair_plan_refreshed_on_resume"] is True


def test_invented_local_module_import_repairs_only_the_consumer_leaf() -> None:
    pipeline = {
        "components": [
            {"id": "foundation"},
            {"id": "backend"},
            {"id": "frontend"},
            {"id": "tests"},
        ]
    }
    blocker = (
        "component frontend generation failed: frontend module contract mismatch: "
        "JavaScript imports missing local modules: ./backend/shared-core"
    )

    parsed = run_local_pipeline_impl.parse_review_blocker(blocker, pipeline)
    plan = run_local_pipeline_impl.compile_repair_plan([blocker], {}, component_pipeline=pipeline)

    assert parsed["kind"] == "broken_runtime"
    assert parsed["components"] == ["frontend"]
    assert parsed["files_hint"] == ["src/app.js"]
    assert plan["affected_components"] == ["frontend"]
    assert plan["affected_files"] == ["src/app.js"]
    assert run_local_pipeline_impl.repair_plan_provider_components(plan) == ["frontend"]
    action = plan["provider_actions"][0]
    assert action["path"] == "src/app.js"
    assert "do not create or regenerate an upstream component" in action["instruction"]


def test_frontend_self_import_repairs_only_app_leaf() -> None:
    pipeline = {
        "components": [
            {"id": "foundation"},
            {"id": "backend"},
            {"id": "frontend"},
            {"id": "tests"},
        ]
    }
    blocker = (
        "component frontend generation failed: frontend module self-import contract mismatch: "
        "src/app.js imports or re-exports itself via ./app"
    )

    parsed = run_local_pipeline_impl.parse_review_blocker(blocker, pipeline)
    plan = run_local_pipeline_impl.compile_repair_plan([blocker], {}, component_pipeline=pipeline)

    assert parsed["kind"] == "broken_runtime"
    assert parsed["components"] == ["frontend"]
    assert parsed["files_hint"] == ["src/app.js"]
    assert plan["affected_components"] == ["frontend"]
    assert plan["affected_files"] == ["src/app.js"]
    assert run_local_pipeline_impl.repair_plan_provider_components(plan) == ["frontend"]


def test_resume_refreshes_stale_broad_semantic_plan_but_preserves_leaf_plan() -> None:
    pipeline = {
        "components": [
            {"id": "foundation"},
            {"id": "backend"},
            {"id": "frontend"},
            {"id": "tests"},
        ]
    }
    blocker = (
        "component frontend generation failed: frontend module contract mismatch: "
        "JavaScript imports missing local modules: ./backend/shared-core"
    )
    stale = {
        "status": "pending",
        "stage": "provider_semantic_repair",
        "blockers": [blocker],
        "affected_components": ["backend", "frontend"],
        "provider_actions": [
            {"component": "backend", "path": "", "instruction": blocker},
            {"component": "frontend", "path": "", "instruction": blocker},
        ],
    }

    refreshed = run_local_pipeline_impl.refresh_pending_semantic_repair_plan(
        stale,
        {},
        pipeline,
    )

    assert refreshed["repair_plan_refreshed_on_resume"] is True
    assert refreshed["affected_components"] == ["frontend"]
    assert refreshed["affected_files"] == ["src/app.js"]
    assert run_local_pipeline_impl.repair_plan_provider_components(refreshed) == ["frontend"]

    leaf_plan = {
        "stage": "component_file_generation",
        "component": "frontend",
        "target_file": "src/app.js",
    }
    assert run_local_pipeline_impl.refresh_pending_semantic_repair_plan(
        leaf_plan,
        {},
        pipeline,
    ) is leaf_plan


def test_same_run_semantic_retry_plan_keeps_goal_and_resume_stage() -> None:
    pipeline = {"components": [{"id": "foundation"}, {"id": "frontend"}]}
    issue = "component frontend generation failed: imports missing local modules: ./backend/shared-core"
    base = run_local_pipeline_impl.compile_repair_plan([issue], {}, component_pipeline=pipeline)
    base["raw_user_goal"] = ""
    base["component_pipeline"] = {}

    prepared = run_local_pipeline_impl.prepare_semantic_repair_retry_plan(
        base,
        [issue],
        "Build a visual novel studio.",
        pipeline,
    )

    assert prepared["status"] == "pending"
    assert prepared["stage"] == "provider_semantic_repair"
    assert prepared["blockers"] == [issue]
    assert prepared["raw_user_goal"] == "Build a visual novel studio."
    assert prepared["component_pipeline"] == pipeline
    assert run_local_pipeline_impl.repair_plan_provider_components(prepared) == ["frontend"]


def test_resume_recovers_missing_exact_leaf_target_from_structured_phase_log(
    tmp_path: pathlib.Path,
) -> None:
    phase_log = tmp_path / "provider_phase_log.jsonl"
    phase_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "component_leaf_attempt_failed",
                        "component": "backend",
                        "target_file": "backend/preview.py",
                    }
                ),
                json.dumps(
                    {
                        "event": "component_leaf_attempt_failed",
                        "component": "frontend",
                        "target_file": "src/app.js",
                        "error_summary": "implementation depth contract mismatch",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    pending = {
        "stage": "provider_semantic_repair",
        "failed_component": "frontend",
        "affected_components": ["frontend"],
        "affected_files": [],
        "provider_actions": [
            {"component": "frontend", "path": "", "instruction": "repair frontend"}
        ],
        "blockers": ["component frontend generation failed: depth mismatch"],
    }

    recovered = run_local_pipeline_impl.recover_pending_leaf_target_from_phase_log(
        pending,
        phase_log,
    )

    assert recovered["leaf_target_recovered_from_phase_log"] is True
    assert recovered["affected_components"] == ["frontend"]
    assert recovered["affected_files"] == ["src/app.js"]
    assert run_local_pipeline_impl.repair_target_files_for_component(
        recovered,
        "frontend",
    ) == ["src/app.js"]


def test_actual_commonjs_require_call_still_routes_module_system_repair() -> None:
    pipeline = {"components": [{"id": "foundation"}, {"id": "frontend"}, {"id": "tests"}]}
    parsed = run_local_pipeline_impl.parse_review_blocker(
        "src/app.js mixes require('./legacy') CommonJS with ESM export syntax",
        pipeline,
    )

    assert parsed["kind"] == "module_system_mismatch"


def test_browser_local_complexity_contract_does_not_invent_backend_pipeline() -> None:
    goal = (
        "Build a fully local task board with Python standard-library launcher, native HTML/CSS/JavaScript, "
        "localStorage persistence, and no database."
    )
    selected = run_local_pipeline_impl.discovery_selection_lane.select_candidate(
        run_local_pipeline_impl.discovery_selection_lane.generate_candidates(goal)
    )
    assert selected is not None
    contract = run_local_pipeline_impl.discovery_selection_lane.build_contract(selected)
    plan = {
        "selected_requirement": {
            "selected_requirement_id": "local_task_board_requirement",
            "selected_requirement_name": "Local task board",
        },
        "selected_project_direction": {
            "selected_id": "local_task_board",
            "selected_name": "Local Task Board",
        },
        "complexity_project_contract": contract,
    }

    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(goal, plan)
    components = {row["id"]: row for row in pipeline["components"]}

    assert components["backend"]["required_paths"] == ["main.py"]
    assert components["backend"]["contract_slice"]["browser_local_static"] is True
    assert "backend/artifact_store.py" not in components["backend"]["required_paths"]
    assert components["tests"]["required_paths"] == ["tests/test_app.py"]
    assert any("localStorage" in item for item in components["frontend"]["acceptance"])


def test_web_python_architecture_uses_explicit_runtime_boundary_not_js_import() -> None:
    goal = "Build a local visual novel studio with a Python story core and browser editor."
    selected = run_local_pipeline_impl.discovery_selection_lane.select_candidate(
        run_local_pipeline_impl.discovery_selection_lane.generate_candidates(goal)
    )
    assert selected is not None
    contract = run_local_pipeline_impl.discovery_selection_lane.build_contract(selected)
    plan = {
        "selected_requirement": {
            "selected_requirement_id": "local_visual_novel_studio_requirement",
            "selected_requirement_name": "Local visual novel studio",
        },
        "selected_project_direction": {
            "selected_id": "local_visual_novel_studio",
            "selected_name": "Local Visual Novel Authoring Studio",
        },
        "complexity_project_contract": contract,
    }

    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(goal, plan)
    components = {row["id"]: row for row in pipeline["components"]}
    backend_acceptance = " ".join(components["backend"]["acceptance"])
    frontend_acceptance = " ".join(components["frontend"]["acceptance"])

    assert "HTTP or server-rendered adapter contract" in backend_acceptance
    assert "JavaScript must never import Python modules" in backend_acceptance
    assert "explicit HTTP endpoints or server-rendered adapters" in frontend_acceptance
    assert "never import Python/backend paths" in frontend_acceptance
    assert "shared-core API" not in frontend_acceptance
