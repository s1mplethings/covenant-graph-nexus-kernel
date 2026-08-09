from __future__ import annotations

import json
import pathlib
import sys
import threading
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import formal_model_contract
import post_build_repair
import run_local_pipeline_impl


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


def test_same_goal_semantic_resume_reuses_unforced_checkpoint_across_replanning_hash(
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

    assert calls == ["frontend"]


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
    assert [leaf["path"] for leaf in result["leaf_work_graph"]["leaves"]] == [
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

    assert [leaf["path"] for leaf in result["leaf_work_graph"]["leaves"]] == paths
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
                        {"path": path, "purpose": "independent", "dependencies": []}
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
        return json.dumps({"path": target, "content": "READY = True\n"})

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

    def fake_provider_text(_messages, *_args, **kwargs):
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps({"component": "backend", "files": manifest})
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
    assert expanded[1]["dependencies"] == [
        "backend/adapters.py",
        "backend/stages_part_01.py",
    ]
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
    assert [leaf["path"] for leaf in graph["leaves"]] == [
        "src/app_part_01.js",
        "src/app_part_02.js",
        "src/app_part_03.js",
        "src/app.js",
    ]
    assert not any(
        warning.startswith("cyclic_or_unresolved")
        for warning in graph["ordering_warnings"]
    )


def test_high_complexity_javascript_controller_with_three_symbols_still_splits() -> None:
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

    assert [item["path"] for item in expanded] == [
        "src/app_part_01.js",
        "src/app_part_02.js",
        "src/app_part_03.js",
        "src/app.js",
    ]
    assert [item["expected_symbols"] for item in expanded[:-1]] == [
        ["bootstrapApp"],
        ["renderStudioApp"],
        ["StudioController"],
    ]
    assert expanded[-1]["generation_role"] == "compatibility_facade"


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
    assert run_local_pipeline_impl.provider_component_prompt_policy()["max_tokens_file"] == 5000

    monkeypatch.setenv("CGNK_PROVIDER_COMPONENT_FILE_MAX_TOKENS", "8000")
    assert run_local_pipeline_impl.provider_component_prompt_policy()["max_tokens_file"] == 7000


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
    ordered_paths = [leaf["path"] for leaf in graph["leaves"]]
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
        return {"status": "pass", "blockers": [], "affected_files": []}

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

    assert normalized == {"component_id": "post_build", "files": files}
    assert conflicting["component_id"] == "frontend"


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
