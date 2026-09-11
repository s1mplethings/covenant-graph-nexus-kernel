from __future__ import annotations

import json
import pathlib
import threading
import time

import pytest

from scripts import provider_execution_metrics, provider_jobs, run_local_pipeline_impl


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "local_project_board_provider_plan.json"


def _repair_pipeline() -> dict:
    return {
        "components": [
            {
                "id": "frontend",
                "required_paths": ["frontend/index.html", "frontend/app.js"],
                "leaf_work_graph": {
                    "leaves": [
                        {
                            "leaf_id": "frontend.leaf.001",
                            "owns": ["frontend/index.html", "frontend/app.js"],
                        }
                    ]
                },
            }
        ]
    }


def _repair_plan() -> dict:
    return {
        "status": "pending",
        "stage": "provider_semantic_repair",
        "raw_user_goal": "repair the board",
        "attempt_number": 1,
        "provider_actions": [
            {
                "path": "frontend/app.js",
                "component": "frontend",
                "provider_job_id": "frontend.leaf.001",
                "bundle_id": "REPAIR-BUNDLE-1",
                "instruction": "Fix the observed product failure: Export JSON does nothing.",
            }
        ],
    }


def test_existing_provider_job_patch_applies_only_changed_owned_path(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    (candidate / "frontend").mkdir(parents=True)
    (candidate / "frontend" / "app.js").write_text(
        "document.getElementById('missing');\n", encoding="utf-8"
    )
    (candidate / "frontend" / "index.html").write_text(
        "<main id=\"present\">keep</main><script src=\"app.js\"></script>\n", encoding="utf-8"
    )

    captured: dict = {}

    def fake_generation(*args, **kwargs):
        captured.update(kwargs)
        captured["positional"] = args
        return {
            "files": [
                {"path": "frontend/app.js", "content": "document.getElementById('present');\n"},
                {"path": "frontend/index.html", "content": "<main id=\"present\">keep</main><script src=\"app.js\"></script>\n"},
            ]
        }

    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_generate_project_by_components",
        fake_generation,
    )
    result = run_local_pipeline_impl.execute_provider_job_patch_generation(
        candidate_dir=candidate,
        repair_plan=_repair_plan(),
        user_goal="repair the board",
        component_pipeline=_repair_pipeline(),
        plan_doc={},
        blueprint={},
        online_inputs={},
        market_research={},
        model="provider-model",
        timeout=90,
        internal_context="",
        deadline=time.monotonic() + 60,
        run_dir=tmp_path / "run",
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
    )

    assert result["status"] == "applied"
    assert result["changed_files"] == ["frontend/app.js"]
    assert result["execution_path"] == "provider_generate_project_by_components.split_file_provider_jobs"
    assert captured["repair_only_components"] is True
    assert captured["pending_repair_plan"]["stage"] == "provider_semantic_repair"
    assert captured["pending_repair_plan"]["raw_user_goal"] == "repair the board"
    assert captured["routing_policy"].enable_model_routing is False
    assert captured["routing_policy"].large_model == "provider-model"
    assert captured["positional"][6] == []
    assert "frontend" in captured["component_repair_instructions"]
    assert sorted(
        item["path"]
        for item in captured["repair_base_files_by_component"]["frontend"]
    ) == ["frontend/app.js", "frontend/index.html"]
    assert (candidate / "frontend" / "app.js").read_text(encoding="utf-8") == "document.getElementById('present');\n"
    assert (candidate / "frontend" / "index.html").read_text(encoding="utf-8") == '<main id="present">keep</main><script src="app.js"></script>\n'


def test_existing_provider_job_patch_rejects_no_actual_change(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    (candidate / "frontend").mkdir(parents=True)
    (candidate / "frontend" / "app.js").write_text("const unchanged = true;\n", encoding="utf-8")
    (candidate / "frontend" / "index.html").write_text("<main>keep</main>\n", encoding="utf-8")
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_generate_project_by_components",
        lambda *args, **kwargs: {
            "files": [
                {"path": "frontend/app.js", "content": "const unchanged = true;\n"},
                {"path": "frontend/index.html", "content": "<main>keep</main>\n"},
            ]
        },
    )

    result = run_local_pipeline_impl.execute_provider_job_patch_generation(
        candidate_dir=candidate,
        repair_plan=_repair_plan(),
        user_goal="repair the board",
        component_pipeline=_repair_pipeline(),
        plan_doc={},
        blueprint={},
        online_inputs={},
        market_research={},
        model="provider-model",
        timeout=90,
        internal_context="",
        deadline=time.monotonic() + 60,
        run_dir=tmp_path / "run",
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
    )

    assert result["status"] == "failed"
    assert result["reason"] == "NO_ACTUAL_CHANGE"
    assert result["changed_files"] == []


def test_existing_provider_job_patch_rejects_unrepaired_affected_behavior(
    tmp_path, monkeypatch
):
    candidate = tmp_path / "candidate"
    (candidate / "frontend").mkdir(parents=True)
    original = "document.getElementById('missing').addEventListener('click', run);\n"
    (candidate / "frontend" / "app.js").write_text(original, encoding="utf-8")
    (candidate / "frontend" / "index.html").write_text(
        '<button id="present">Run</button><script src="app.js"></script>\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_generate_project_by_components",
        lambda *args, **kwargs: {
            "files": [
                {
                    "path": "frontend/app.js",
                    "content": original + "const cosmeticOnly = true;\n",
                },
                {
                    "path": "frontend/index.html",
                    "content": '<button id="present">Run</button><script src="app.js"></script>\n',
                },
            ]
        },
    )

    result = run_local_pipeline_impl.execute_provider_job_patch_generation(
        candidate_dir=candidate,
        repair_plan=_repair_plan(),
        user_goal="repair the board",
        component_pipeline=_repair_pipeline(),
        plan_doc={},
        blueprint={},
        online_inputs={},
        market_research={},
        model="provider-model",
        timeout=90,
        internal_context="",
        deadline=time.monotonic() + 60,
        run_dir=tmp_path / "run",
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
    )

    assert result["status"] == "failed"
    assert result["reason"] == "AFFECTED_BEHAVIOR_VALIDATION_FAILED"
    assert result["patch_accepted"] is False
    assert result["rejected_target_files"]["frontend/app.js"]["issue_acceptance"][0][
        "coherence_checks_after"
    ][0]["kind"] == "dom_id_contract_mismatch"
    assert (candidate / "frontend" / "app.js").read_text(encoding="utf-8") == original


def test_provider_job_success_not_rolled_back_by_later_job_failure(
    tmp_path, monkeypatch
):
    candidate = tmp_path / "candidate"
    (candidate / "app").mkdir(parents=True)
    (candidate / "frontend").mkdir(parents=True)
    original_backend = "value = b'x'.decode('UTF8-SIG')\n"
    original_frontend = "document.getElementById('missing').onclick = run;\n"
    (candidate / "app" / "main.py").write_text(original_backend, encoding="utf-8")
    (candidate / "frontend" / "app.js").write_text(original_frontend, encoding="utf-8")
    (candidate / "frontend" / "index.html").write_text(
        '<button id="present">Run</button><script src="app.js"></script>\n',
        encoding="utf-8",
    )
    repair_plan = {
        "status": "pending",
        "stage": "provider_semantic_repair",
        "raw_user_goal": "repair both",
        "attempt_number": 1,
        "provider_actions": [
            {
                "path": "app/main.py",
                "component": "backend",
                "provider_job_id": "backend.leaf.001",
                "instruction": "Use a registered codec.",
            },
            {
                "path": "frontend/app.js",
                "component": "frontend",
                "provider_job_id": "frontend.leaf.001",
                "instruction": "Use only published DOM ids.",
            },
        ],
    }
    pipeline = {
        "components": [
            {
                "id": "backend",
                "required_paths": ["app/main.py"],
                "leaf_work_graph": {
                    "leaves": [
                        {"leaf_id": "backend.leaf.001", "owns": ["app/main.py"]}
                    ]
                },
            },
            *_repair_pipeline()["components"],
        ]
    }
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_generate_project_by_components",
        lambda *args, **kwargs: {
            "files": [
                {"path": "app/main.py", "content": "value = b'x'.decode('utf-8-sig')\n"},
                {
                    "path": "frontend/app.js",
                    "content": original_frontend + "const cosmeticOnly = true;\n",
                },
                {
                    "path": "frontend/index.html",
                    "content": '<button id="present">Run</button><script src="app.js"></script>\n',
                },
            ]
        },
    )

    result = run_local_pipeline_impl.execute_provider_job_patch_generation(
        candidate_dir=candidate,
        repair_plan=repair_plan,
        user_goal="repair both",
        component_pipeline=pipeline,
        plan_doc={},
        blueprint={},
        online_inputs={},
        market_research={},
        model="provider-model",
        timeout=90,
        internal_context="",
        deadline=time.monotonic() + 60,
        run_dir=tmp_path / "run",
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
    )

    assert result["status"] == "applied"
    assert result["partial_application"] is True
    assert result["changed_files"] == ["app/main.py"]
    assert "frontend/app.js" in result["rejected_target_files"]
    assert "utf-8-sig" in (candidate / "app" / "main.py").read_text(encoding="utf-8")
    assert (candidate / "frontend" / "app.js").read_text(encoding="utf-8") == original_frontend


def test_provider_job_success_not_rolled_back_by_later_failure(
    tmp_path, monkeypatch
):
    test_provider_job_success_not_rolled_back_by_later_job_failure(
        tmp_path, monkeypatch
    )


def test_component_wide_rollback_for_repair_is_forbidden(
    tmp_path, monkeypatch
):
    test_provider_job_success_not_rolled_back_by_later_job_failure(
        tmp_path, monkeypatch
    )


def test_qwen_compact_repair_keeps_current_source_and_evidence() -> None:
    source = "value = b'x'.decode('UTF8-SIG')\n"
    compact = run_local_pipeline_impl.compact_provider_leaf_payload(
        {
            "component": {"id": "backend"},
            "target_file": "app/main.py",
            "target_file_purpose": "decode CSV uploads",
            "implementation_depth_contract": {},
            "repair_errors_summary": [
                "Observed bytes.decode('UTF8-SIG') raises LookupError; use a registered codec."
            ],
            "current_target_source": {
                "path": "app/main.py",
                "content": source,
            },
        }
    )

    assert compact["current_target_source"]["content"] == source
    assert "LookupError" in compact["repair"]["must_fix"]
    assert any("not a greenfield rewrite" in rule for rule in compact["generic_rules"])


def test_multi_file_provider_job_repair_keeps_current_emission_source(
    monkeypatch,
) -> None:
    captured: dict = {}

    def fake_provider_text(messages, *args, **kwargs):
        captured.update(json.loads(messages[-1]["content"]))
        return json.dumps(
            {
                "files": [
                    {
                        "path": "app/main.py",
                        "content": "value = b'x'.decode('utf-8-sig')\n",
                    }
                ]
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    result = run_local_pipeline_impl.provider_generate_component_job(
        goal="repair codec",
        component={"id": "backend"},
        component_pipeline={"components": [{"id": "backend"}]},
        manifest_entries=[{"path": "app/main.py", "dependencies": []}],
        prior_manifest=[],
        completed_files=[],
        component_file_manifest=[{"path": "app/main.py", "dependencies": []}],
        repair_errors=["UTF8-SIG raises LookupError"],
        model="provider-model",
        timeout=30,
        phase_log_path=None,
        routing_policy=None,
        last_transport_error=(
            "Provider emission may return only requested owned paths and no duplicates"
        ),
        current_target_sources={
            "app/main.py": {
                "path": "app/main.py",
                "content": "value = b'x'.decode('UTF8-SIG')\n",
            }
        },
    )

    assert result["file_items"][0]["path"] == "app/main.py"
    assert captured["current_target_sources"][0]["path"] == "app/main.py"
    assert "UTF8-SIG" in captured["current_target_sources"][0]["content"]
    assert any("affected-only repair" in rule for rule in captured["strict_rules"])
    assert "requested owned paths" in captured["previous_generation_error"]
    assert any(
        "Correct every item in previous_generation_error" in rule
        for rule in captured["strict_rules"]
    )


def test_build_coherence_finds_codec_dom_and_static_root_contradictions() -> None:
    issues = run_local_pipeline_impl.project_build_coherence_issues(
        [
            {
                "path": "app/main.py",
                "content": (
                    "import functools, http.server, os\n"
                    "directory = os.path.dirname(os.path.abspath(__file__))\n"
                    "handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)\n"
                    "value = b'x'.decode('UTF8-SIG')\n"
                ),
            },
            {
                "path": "frontend/index.html",
                "content": '<main id="board"></main><script src="app.js"></script>',
            },
            {
                "path": "frontend/app.js",
                "content": "document.getElementById('missing-form').addEventListener('submit', run);\n",
            },
        ]
    )

    assert {item["kind"] for item in issues} == {
        "invalid_literal_codec",
        "dom_id_contract_mismatch",
        "static_server_root_mismatch",
    }
    assert {item["path"] for item in issues} == {
        "app/main.py",
        "frontend/app.js",
    }
    assert all(item["authority"] == "deterministic_build_coherence" for item in issues)


def test_build_coherence_finds_frontend_backend_endpoint_mismatch() -> None:
    issues = run_local_pipeline_impl.project_build_coherence_issues(
        [
            {
                "path": "app/main.py",
                "content": "@app.route('/api/process', methods=['POST'])\ndef process(): return {}\n",
            },
            {
                "path": "frontend/index.html",
                "content": '<script src="app.js"></script>',
            },
            {
                "path": "frontend/app.js",
                "content": "fetch(`${API_BASE}/api/clean`, {method: 'POST'});\n",
            },
        ]
    )

    assert [item["kind"] for item in issues] == [
        "frontend_backend_endpoint_mismatch"
    ]
    assert issues[0]["path"] == "app/main.py"
    assert issues[0]["related_paths"] == ["frontend/app.js"]


def test_build_coherence_resolves_js_base_url_and_missing_html_script() -> None:
    issues = run_local_pipeline_impl.project_build_coherence_issues(
        [
            {
                "path": "app/main.py",
                "content": "@app.route('/api/process')\ndef process(): return {}\n",
            },
            {
                "path": "frontend/index.html",
                "content": '<script src="app.js"></script><script src="missing.js"></script>',
            },
            {
                "path": "frontend/app.js",
                "content": "const API_BASE = '/api'; fetch(`${API_BASE}/import`);\n",
            },
        ]
    )

    assert {item["kind"] for item in issues} == {
        "html_script_reference_missing",
        "frontend_backend_endpoint_mismatch",
    }
    endpoint = next(
        item for item in issues if item["kind"] == "frontend_backend_endpoint_mismatch"
    )
    assert "/api/import" in endpoint["message"]


def _source(path: str) -> str:
    symbol = pathlib.PurePosixPath(path).stem.title().replace("_", "")
    return (
        f"class {symbol}:\n"
        "    def __init__(self, value=1):\n"
        "        self.value = value\n"
        "    def validate(self):\n"
        "        if self.value < 0:\n"
        "            raise ValueError('value')\n"
        "        return True\n"
        "    def run(self):\n"
        "        self.validate()\n"
        "        return self.value\n"
        "    def describe(self):\n"
        "        return {'value': self.value}\n"
        "    def reset(self):\n"
        "        self.value = 0\n"
        "        return self.value\n"
        "    def increment(self):\n"
        "        self.value += 1\n"
        "        return self.value\n"
    )


def test_multi_file_provider_job_ownership_passes() -> None:
    job = provider_jobs.ProviderJob(
        id="frontend.unit.001",
        goal="build one frontend unit",
        owns=("frontend/index.html", "frontend/styles.css", "frontend/app.js"),
    )
    patch = provider_jobs.validate_patch_set(
        job,
        {
            "frontend/index.html": "<main>Ready</main>\n",
            "frontend/styles.css": ":root { --ready: 1; }\n",
            "frontend/app.js": "export const ready = true;\n",
        },
    )
    assert tuple(patch.files) == job.owns


def test_multi_file_provider_job_rejects_unowned_output() -> None:
    job = provider_jobs.ProviderJob(
        id="frontend.unit.001",
        goal="build one frontend unit",
        owns=("frontend/index.html", "frontend/styles.css"),
    )
    with pytest.raises(ValueError, match="patch_set.ownership"):
        provider_jobs.validate_patch_set(
            job,
            {
                "frontend/index.html": "<main>Ready</main>\n",
                "backend/foreign.py": "BAD = True\n",
            },
        )


def test_build_first_manifest_projection_defers_provider_optional_docs() -> None:
    manifest = [
        {"path": "README.md", "dependencies": []},
        {"path": "TEST_PLAN.md", "dependencies": ["README.md"]},
        {
            "path": "DELIVERY_NOTES.md",
            "dependencies": ["README.md", "docs/design_research.md"],
        },
        {"path": "docs/design_research.md", "dependencies": []},
        {"path": "docs/design_system.md", "dependencies": []},
    ]

    projected, deferred = run_local_pipeline_impl.build_first_manifest_projection(
        "docs",
        {
            "required_paths": [
                "README.md",
                "TEST_PLAN.md",
                "DELIVERY_NOTES.md",
                "docs/design_research.md",
                "docs/design_system.md",
            ],
            "build_required_paths": [
                "README.md",
                "TEST_PLAN.md",
                "DELIVERY_NOTES.md",
            ]
        },
        manifest,
    )

    assert [item["path"] for item in projected] == [
        "README.md",
        "TEST_PLAN.md",
        "DELIVERY_NOTES.md",
        "docs/design_research.md",
    ]
    assert projected[2]["dependencies"] == [
        "README.md",
        "docs/design_research.md",
    ]
    assert deferred == ["docs/design_system.md"]


def test_build_first_component_contract_uses_build_file_count_only() -> None:
    release_component = {
        "id": "docs",
        "required_paths": [
            "README.md",
            "TEST_PLAN.md",
            "DELIVERY_NOTES.md",
            "docs/design_research.md",
            "docs/design_system.md",
        ],
        "build_required_paths": [
            "README.md",
            "TEST_PLAN.md",
            "DELIVERY_NOTES.md",
        ],
        "minimum_file_count": 5,
    }

    build_component = run_local_pipeline_impl.build_first_component_contract(
        "docs", release_component
    )

    assert build_component["required_paths"] == [
        "README.md",
        "TEST_PLAN.md",
        "DELIVERY_NOTES.md",
    ]
    assert build_component["minimum_file_count"] == 3
    assert build_component["contract_level"] == "BUILD_HARD"
    assert release_component["minimum_file_count"] == 5


def test_build_first_manifest_projection_keeps_structural_test_children() -> None:
    manifest = [
        {
            "path": "tests/test_goal_behavior_tests.py",
            "dependencies": [
                "frontend/app.js",
                "tests/test_goal_behavior_tests_part_01.py",
            ],
            "facade_children": ["tests/test_goal_behavior_tests_part_01.py"],
        },
        {
            "path": "tests/test_goal_behavior_tests_part_01.py",
            "dependencies": ["frontend/app.js"],
            "expansion_parent": "tests/test_goal_behavior_tests.py",
        },
        {"path": "tests/provider_notes.md", "dependencies": []},
    ]

    projected, deferred = run_local_pipeline_impl.build_first_manifest_projection(
        "tests",
        {"build_required_paths": ["tests/test_goal_behavior_tests.py"]},
        manifest,
    )

    assert [item["path"] for item in projected] == [
        "tests/test_goal_behavior_tests.py",
        "tests/test_goal_behavior_tests_part_01.py",
    ]
    assert projected[0]["dependencies"] == [
        "frontend/app.js",
        "tests/test_goal_behavior_tests_part_01.py",
    ]
    assert deferred == ["tests/provider_notes.md"]
    assert run_local_pipeline_impl.manifest_missing_structural_children(projected) == []
    assert run_local_pipeline_impl.manifest_missing_structural_children(
        [manifest[0]]
    ) == ["tests/test_goal_behavior_tests_part_01.py"]


def test_same_dependency_small_files_merge() -> None:
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "backend",
        [
            {"path": "src/create.py", "dependencies": [], "estimated_complexity": "low"},
            {"path": "src/delete.py", "dependencies": [], "estimated_complexity": "low"},
        ],
    )
    assert graph["leaf_count"] == 1
    assert graph["leaves"][0]["paths"] == ["src/create.py", "src/delete.py"]


def test_different_external_dependencies_do_not_merge() -> None:
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "backend",
        [
            {"path": "backend/a.py", "dependencies": []},
            {"path": "backend/b.py", "dependencies": []},
            {"path": "backend/first.py", "dependencies": ["backend/a.py"]},
            {"path": "backend/second.py", "dependencies": ["backend/b.py"]},
        ],
    )
    owners = [leaf["paths"] for leaf in graph["leaves"]]
    assert not any({"backend/first.py", "backend/second.py"}.issubset(paths) for paths in map(set, owners))


def test_javascript_symbol_count_does_not_create_synthetic_fragments() -> None:
    expanded = run_local_pipeline_impl.expand_component_manifest_submodules(
        "frontend",
        [
            {
                "path": "frontend/app.js",
                "estimated_complexity": "high",
                "expected_symbols": ["Store", "Board", "render", "boot"],
            }
        ],
    )
    assert [entry["path"] for entry in expanded] == ["frontend/app.js"]


def test_combined_output_over_budget_remains_split() -> None:
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "backend",
        [
            {"path": "src/a.py", "dependencies": [], "estimated_complexity": "high"},
            {"path": "src/b.py", "dependencies": [], "estimated_complexity": "high"},
        ],
    )
    assert graph["leaf_count"] == 2
    assert all(len(leaf["paths"]) == 1 for leaf in graph["leaves"])


def _run_four_ready_jobs(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, *, considered: bool) -> tuple[int, dict]:
    paths = [f"backend/parallel_{index}.py" for index in range(4)]
    manifest = [
        {
            "path": path,
            "purpose": "independently verifiable unit",
            "dependencies": [],
            "estimated_complexity": "high",
        }
        for path in paths
    ]
    barrier = threading.Barrier(4)
    lock = threading.Lock()
    active = 0
    peak = 0

    def fake_provider_text(_messages, *_args, **kwargs):
        nonlocal active, peak
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps({"component": "backend", "files": manifest})
        target = str(kwargs.get("target_file"))
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=3)
        time.sleep(0.02)
        with lock:
            active -= 1
        return json.dumps({"path": target, "content": _source(target)})

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "api_only")
    monkeypatch.setenv("CGKN_PROVIDER_PARALLELISM", "4")
    phase_log = tmp_path / "provider_phase_log.jsonl"
    if considered:
        run_local_pipeline_impl.append_provider_event_log(
            phase_log,
            {
                "event": "fallback_considered",
                "to": "local_model",
                "task": "component_generation",
            },
        )
    result = run_local_pipeline_impl.provider_generate_project_component_split(
        goal="build four independent units",
        component={"id": "backend", "required_paths": paths},
        component_pipeline={"components": [{"id": "backend"}]},
        prior_manifest=[],
        repair_errors=[],
        model="test-model",
        timeout=30,
        deadline=None,
        checkpoint_dir=tmp_path / "provider_components",
        run_dir=tmp_path,
        spec_hash="parallel-four",
        phase_log_path=phase_log,
        routing_policy=None,
        split_reason="parallel_four_test",
        original_prompt_chars=0,
    )
    return peak, result


def test_production_executor_reaches_four_workers_for_four_ready_jobs(monkeypatch, tmp_path) -> None:
    peak, result = _run_four_ready_jobs(monkeypatch, tmp_path, considered=False)
    assert peak == 4
    assert result["provider_dag_quality_metrics"]["provider_dag_wave_widths"] == [4]


def test_fallback_considered_does_not_reduce_concurrency(monkeypatch, tmp_path) -> None:
    peak, _result = _run_four_ready_jobs(monkeypatch, tmp_path, considered=True)
    assert peak == 4


def test_fallback_executed_applies_local_limit(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "api_only")
    monkeypatch.setenv("CGKN_PROVIDER_PARALLELISM", "4")
    phase_log = tmp_path / "provider_phase_log.jsonl"
    run_local_pipeline_impl.append_provider_event_log(
        phase_log,
        {
            "event": "fallback_executed",
            "to": "local_model",
            "task": "component_generation",
        },
    )
    assert run_local_pipeline_impl.provider_leaf_max_workers(phase_log) == 1


def test_multi_file_repair_calls_only_exact_evaluator_target_in_ownership_unit(monkeypatch, tmp_path) -> None:
    manifest = [
        {"path": "src/a.py", "dependencies": [], "estimated_complexity": "low"},
        {"path": "src/b.py", "dependencies": [], "estimated_complexity": "low"},
        {"path": "backend/unrelated.py", "dependencies": [], "estimated_complexity": "low"},
    ]
    generated_units: list[list[str]] = []

    def fake_provider_text(messages, *_args, **kwargs):
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps({"component": "backend", "files": manifest})
        payload = json.loads(messages[-1]["content"])
        if kwargs.get("payload_mode") == "multi_file":
            emission_paths = list(payload["provider_job"]["emission_paths"])
            generated_units.append(emission_paths)
            return json.dumps(
                {"files": [{"path": path, "content": _source(path)} for path in emission_paths]}
            )
        target = str(kwargs.get("target_file"))
        generated_units.append([target])
        return json.dumps({"path": target, "content": _source(target)})

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    checkpoint_dir = tmp_path / "provider_components"
    common = {
        "goal": "build scoped repair units",
        "component": {"id": "backend", "required_paths": [entry["path"] for entry in manifest]},
        "component_pipeline": {"components": [{"id": "backend"}]},
        "prior_manifest": [],
        "repair_errors": [],
        "model": "test-model",
        "timeout": 30,
        "deadline": None,
        "checkpoint_dir": checkpoint_dir,
        "run_dir": tmp_path,
        "spec_hash": "multi-repair",
        "phase_log_path": tmp_path / "provider_phase_log.jsonl",
        "routing_policy": None,
        "split_reason": "multi_repair_test",
        "original_prompt_chars": 0,
    }
    initial = run_local_pipeline_impl.provider_generate_project_component_split(**common)
    generated_units.clear()
    repaired = run_local_pipeline_impl.provider_generate_project_component_split(
        **common,
        repair_target_files=["src/b.py"],
        existing_component_files=initial["files"],
    )
    assert generated_units == [["src/b.py"]]
    assert repaired["repair_scope"]["downstream_closure"] == ["src/b.py"]
    assert "backend/unrelated.py" in [item["path"] for item in repaired["files"]]
    metrics = json.loads(
        (tmp_path / "artifacts" / "provider_execution_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    assert metrics["provider_jobs_reused_after_pass"] >= 1


def test_legacy_single_path_job_and_checkpoint_are_readable(tmp_path) -> None:
    job = provider_jobs.ProviderJob.from_dict(
        {"id": "legacy", "goal": "read old job", "path": "frontend/styles.css"}
    )
    assert job.owns == ("frontend/styles.css",)
    assert run_local_pipeline_impl.provider_leaf_owned_paths(
        {"leaf_id": "frontend.leaf.002", "path": "frontend/styles.css"}
    ) == ["frontend/styles.css"]
    checkpoint_dir = tmp_path / "provider_components"
    entry = {"path": "frontend/styles.css", "dependencies": []}
    run_local_pipeline_impl.write_split_file_checkpoint(
        checkpoint_dir,
        component_id="frontend",
        spec_hash="legacy-spec",
        file_item={"path": "frontend/styles.css", "content": "body { color: black; }\n"},
        manifest_entry=entry,
    )
    loaded = run_local_pipeline_impl.load_split_file_checkpoint(
        checkpoint_dir,
        component_id="frontend",
        spec_hash="legacy-spec",
        path_value="frontend/styles.css",
        manifest_entry=entry,
    )
    assert loaded and loaded["path"] == "frontend/styles.css"
    assert run_local_pipeline_impl.load_split_file_checkpoint(
        checkpoint_dir,
        component_id="frontend",
        spec_hash="new-build-spec",
        path_value="frontend/styles.css",
        manifest_entry={"path": "frontend/styles.css", "purpose": "wording changed"},
        allow_spec_mismatch=True,
        allow_manifest_mismatch=True,
    ) == loaded


def test_local_project_board_frozen_plan_reduces_fragmentation() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    graphs = [
        run_local_pipeline_impl.build_component_leaf_work_graph(
            component["id"],
            run_local_pipeline_impl.expand_component_manifest_submodules(
                component["id"], component["manifest"]
            ),
        )
        for component in fixture["components"]
    ]
    jobs = sum(graph["leaf_count"] for graph in graphs)
    owned_files = sum(
        graph["quality_metrics"]["provider_owned_files_total"] for graph in graphs
    )
    waves = [
        len(batch)
        for graph in graphs
        for batch in run_local_pipeline_impl.component_leaf_ready_batches(graph)
    ]
    all_paths = [
        path
        for graph in graphs
        for leaf in graph["leaves"]
        for path in leaf["paths"]
    ]
    assert jobs <= 8
    assert jobs == 6
    assert waves == [1, 3, 1, 1]
    assert len(waves) < fixture["before"]["provider_dag_critical_path_waves"]
    assert owned_files / jobs > 1
    assert max(waves) >= 2
    assert not any("app_part_" in path for path in all_paths)
    assert all(provider_jobs.validate_jobs(provider_jobs.provider_jobs_from_leaf_graph(graph["component_id"], graph)) == [] for graph in graphs)


def test_output_budget_is_bounded_by_natural_unit_size() -> None:
    css_cap = run_local_pipeline_impl.provider_job_output_token_budget(
        [{"path": "frontend/styles.css", "estimated_complexity": "medium"}]
    )
    frontend_cap = run_local_pipeline_impl.provider_job_output_token_budget(
        [
            {"path": "frontend/index.html", "estimated_complexity": "medium"},
            {"path": "frontend/styles.css", "estimated_complexity": "medium"},
            {"path": "frontend/app.js", "estimated_complexity": "high"},
        ]
    )
    assert css_cap == 1200
    assert css_cap < frontend_cap <= 7000


def test_frontend_natural_job_uses_bounded_emissions_without_fragmenting_paths() -> None:
    entries = [
        {"path": "frontend/index.html", "expected_output_chars": 2500},
        {"path": "frontend/styles.css", "expected_output_chars": 3500},
        {"path": "frontend/app.js", "expected_output_chars": 6000},
    ]
    plan = run_local_pipeline_impl.plan_provider_job_emissions(
        entries, model="qwen3.8-max"
    )
    assert plan["ownership_paths"] == [
        "frontend/index.html",
        "frontend/styles.css",
        "frontend/app.js",
    ]
    assert [item["paths"] for item in plan["emissions"]] == [
        ["frontend/index.html", "frontend/styles.css"],
        ["frontend/app.js"],
    ]
    assert [item["estimated_output_tokens"] for item in plan["emissions"]] == [
        2321,
        2160,
    ]
    assert [item["requested_output_cap"] for item in plan["emissions"]] == [
        4000,
        4000,
    ]
    assert all(
        emission["requested_output_cap"]
        >= min(
            emission["estimated_output_tokens"],
            plan["effective_reliable_output_cap"],
        )
        for emission in plan["emissions"]
    )
    assert not any("app_part_" in path for path in plan["ownership_paths"])


def test_self_imposed_truncation_does_not_become_a_model_reliability_cap(
    tmp_path: pathlib.Path,
) -> None:
    phase_log = tmp_path / "provider_phase_log.jsonl"
    phase_log.write_text(
        json.dumps(
            {
                "event": "provider_transport_attempt",
                "selected_model": "qwen3.8-max",
                "actual_output_tokens": 2000,
                "requested_output_cap": 2000,
                "finish_reason": "max_output_tokens",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    observed = run_local_pipeline_impl.provider_observed_output_limit(
        phase_log, "qwen3.8-max"
    )

    assert observed["truncated_count"] == 1
    assert observed["derived_reliable_cap"] == 0


def test_provider_enforced_truncation_below_request_updates_reliable_cap(
    tmp_path: pathlib.Path,
) -> None:
    phase_log = tmp_path / "provider_phase_log.jsonl"
    phase_log.write_text(
        json.dumps(
            {
                "event": "provider_transport_attempt",
                "selected_model": "qwen3.8-max",
                "actual_output_tokens": 1800,
                "requested_output_cap": 3000,
                "finish_reason": "max_output_tokens",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    observed = run_local_pipeline_impl.provider_observed_output_limit(
        phase_log, "qwen3.8-max"
    )

    assert observed["derived_reliable_cap"] == 1800


def test_existing_retry_expands_self_imposed_truncation_cap_without_new_job() -> None:
    entries = [{"path": "app/main.py", "expected_output_chars": 3000}]

    initial = run_local_pipeline_impl.plan_provider_job_emissions(
        entries,
        model="qwen3.7-flash",
    )
    retry = run_local_pipeline_impl.plan_provider_job_emissions(
        entries,
        model="qwen3.7-flash",
        previous_generation_error=(
            "provider output truncated before contract validation: "
            "finish_reason=max_output_tokens"
        ),
    )
    final_retry = run_local_pipeline_impl.plan_provider_job_emissions(
        entries,
        model="qwen3.7-flash",
        previous_generation_error=(
            "provider output truncated before contract validation: "
            "finish_reason=max_output_tokens"
        ),
        attempt_number=3,
    )

    assert initial["requested_output_cap"] == 1200
    assert retry["estimated_output_cap"] == 1200
    assert retry["requested_output_cap"] == 1800
    assert retry["emissions"][0]["requested_output_cap"] == 1800
    assert retry["ownership_paths"] == initial["ownership_paths"]
    assert final_retry["requested_output_cap"] == 2700
    assert final_retry["emissions"][0]["requested_output_cap"] == 2700
    assert final_retry["ownership_paths"] == initial["ownership_paths"]


def test_existing_plus_retry_reaches_reliable_cap_without_extra_attempt() -> None:
    entries = [{"path": "tests/test_goal_behavior_tests_part_03.py", "expected_output_chars": 5200}]
    error = (
        "provider output truncated before contract validation: "
        "finish_reason=max_output_tokens"
    )

    second = run_local_pipeline_impl.provider_retry_output_token_cap(
        entries,
        model="qwen3.7-plus",
        previous_generation_error=error,
        attempt_number=2,
    )
    third = run_local_pipeline_impl.provider_retry_output_token_cap(
        entries,
        model="qwen3.7-plus",
        previous_generation_error=error,
        attempt_number=3,
    )

    assert second == 2601
    assert third == 3000


def test_affected_only_emission_cap_fits_complete_current_source() -> None:
    entry = {"path": "frontend/app.js", "expected_output_chars": 3000}
    current_source = "const value = 'working';\n" * 240

    output_cap = run_local_pipeline_impl.provider_emission_output_token_cap(
        [entry],
        1200,
        model="qwen3.7-flash",
        current_target_sources={
            "frontend/app.js": {
                "path": "frontend/app.js",
                "content": current_source,
            }
        },
    )

    assert output_cap > 1200
    assert output_cap <= run_local_pipeline_impl.provider_model_reliable_output_cap(
        "qwen3.7-flash"
    )
    assert run_local_pipeline_impl.provider_emission_output_token_cap(
        [entry],
        1200,
        model="qwen3.7-flash",
    ) == 1200


def _frontend_contract_fixture() -> tuple[list[dict], list[dict]]:
    manifest = [
        {
            "path": "frontend/index.html",
            "dependencies": [],
            "expected_symbols": [],
            "expected_output_chars": 800,
        },
        {
            "path": "frontend/styles.css",
            "dependencies": [],
            "expected_symbols": [],
            "expected_output_chars": 800,
        },
        {
            "path": "frontend/app.js",
            "dependencies": [],
            "expected_symbols": ["initApp", "createTask"],
            "expected_output_chars": 1200,
        },
    ]
    files = [
        {
            "path": "frontend/index.html",
            "content": '<main id="root"></main><script type="module" src="app.js"></script>\n',
        },
        {"path": "frontend/styles.css", "content": "body { color: black; }\n"},
        {
            "path": "frontend/app.js",
            "content": (
                "function createTask(title) {\n"
                "  const task = { title };\n"
                "  if (!title) return null;\n"
                "  return task;\n"
                "}\n"
                "function initApp() {\n"
                "  const ready = true;\n"
                "  if (!ready) return false;\n"
                "  document.body.dataset.ready = 'true';\n"
                "  return ready;\n"
                "}\n"
            ),
        },
    ]
    return manifest, files


def test_internal_unconsumed_javascript_symbol_is_not_hard_frozen() -> None:
    manifest, files = _frontend_contract_fixture()
    receipt = run_local_pipeline_impl.build_leaf_boundary_check_receipt(
        component_id="frontend",
        target_file="frontend/app.js",
        component_files=files,
        manifest_paths=[item["path"] for item in manifest],
        manifest_entry=manifest[-1],
    )
    assert receipt["status"] == "PASS"
    assert receipt["javascript_hard_export_contract"]["hard_required_symbols"] == []
    assert receipt["structured_violations"] == []


def test_cross_component_imported_javascript_symbol_is_hard_frozen() -> None:
    manifest, files = _frontend_contract_fixture()
    consumer = {
        "path": "frontend/consumer.js",
        "content": 'import { createTask, initApp } from "./app.js";\ninitApp();\n',
    }
    receipt = run_local_pipeline_impl.build_leaf_boundary_check_receipt(
        component_id="frontend",
        target_file="frontend/app.js",
        component_files=files,
        prior_files=[consumer],
        manifest_paths=[item["path"] for item in manifest],
        manifest_entry=manifest[-1],
    )
    violations = receipt["structured_violations"]
    assert receipt["status"] == "FAIL"
    assert [item["rule_id"] for item in violations] == [
        "REQUIRED_EXPORT_MISSING",
        "REQUIRED_EXPORT_MISSING",
    ]
    assert {item["symbol"] for item in violations} == {"createTask", "initApp"}
    assert all(item["path"] == "frontend/app.js" for item in violations)
    assert all(item["line"] for item in violations)


def test_public_api_javascript_symbol_is_hard_frozen() -> None:
    manifest, files = _frontend_contract_fixture()
    receipt = run_local_pipeline_impl.build_leaf_boundary_check_receipt(
        component_id="frontend",
        target_file="frontend/app.js",
        component_files=files,
        manifest_paths=[item["path"] for item in manifest],
        manifest_entry=manifest[-1],
        public_api_symbols=["createTask"],
    )
    assert receipt["status"] == "FAIL"
    assert receipt["javascript_hard_export_contract"]["public_api_symbols"] == [
        "createTask"
    ]
    assert [item["symbol"] for item in receipt["structured_violations"]] == [
        "createTask"
    ]


def test_component_quality_uses_projectspec_public_api_authority() -> None:
    manifest, files = _frontend_contract_fixture()
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="frontend",
        files=files,
        manifest_entries=manifest,
        component_contract={
            "id": "frontend",
            "contract_slice": {
                "public_api_symbols_by_path": {
                    "frontend/app.js": ["createTask"],
                }
            },
        },
    )
    assert validation["status"] == "fail"
    assert "frontend/app.js does not publish hard-required exports: createTask" in validation[
        "blockers"
    ]


def test_classic_script_cannot_load_hard_es_export_contract() -> None:
    manifest, files = _frontend_contract_fixture()
    files[0]["content"] = '<main id="root"></main><script src="app.js"></script>\n'
    files[-1]["content"] = files[-1]["content"].replace(
        "function createTask", "export function createTask"
    )
    receipt = run_local_pipeline_impl.build_leaf_boundary_check_receipt(
        component_id="frontend",
        target_file="frontend/app.js",
        component_files=files,
        manifest_paths=[item["path"] for item in manifest],
        manifest_entry=manifest[-1],
        public_api_symbols=["createTask"],
    )
    assert receipt["status"] == "FAIL"
    assert any(
        item["rule_id"] == "CONTRACT_RUNTIME_CONTRADICTION"
        for item in receipt["structured_violations"]
    )


def test_const_reassignment_is_structured_but_arrow_parameter_is_not() -> None:
    real = run_local_pipeline_impl.javascript_const_reassignment_violations(
        [
            {
                "path": "frontend/app.js",
                "content": "const state = [];\nstate = [];\n",
            }
        ]
    )
    arrow = run_local_pipeline_impl.javascript_const_reassignment_violations(
        [
            {
                "path": "frontend/app.js",
                "content": (
                    "const task = {};\n"
                    "items.forEach(task => task.id);\n"
                    "html += '<button data-task=\"id\" title=\"task\">';\n"
                ),
            }
        ]
    )
    assert real == [
        {
            "rule_id": "CONST_REASSIGNMENT",
            "path": "frontend/app.js",
            "symbol": "state",
            "line": 2,
            "expected": "state remains immutable after its const declaration",
            "observed": "state is assigned again",
            "repair_hint": "Declare the binding with let only when replacement is required, or mutate the existing value without reassigning the const binding.",
        }
    ]
    assert arrow == []


def _repair_contract_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    responses: list[str],
) -> tuple[dict, list[dict]]:
    manifest, files = _frontend_contract_fixture()
    consumer = {
        "path": "frontend/consumer.js",
        "content": 'import { createTask, initApp } from "./app.js";\ninitApp();\n',
    }
    receipts = run_local_pipeline_impl.provider_job_boundary_receipts(
        component_id="frontend",
        owned_paths=[item["path"] for item in manifest],
        files=files,
        prior_files=[consumer],
        manifest=manifest,
        manifest_by_path={item["path"]: item for item in manifest},
    )
    violations = run_local_pipeline_impl.structured_provider_job_violations(receipts)
    calls: list[dict] = []

    def fake_provider_text(messages, *_args, **kwargs):
        calls.append({"payload": json.loads(messages[-1]["content"]), **kwargs})
        return responses.pop(0)

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    result = run_local_pipeline_impl.repair_provider_job_contract(
        goal="build a local board",
        component={"id": "frontend", "required_paths": [item["path"] for item in manifest]},
        provider_job_id="frontend.leaf.001",
        owned_paths=[item["path"] for item in manifest],
        current_files=files,
        prior_files=[consumer],
        manifest=manifest,
        manifest_by_path={item["path"]: item for item in manifest},
        leaf_interface_contract={"frozen": True},
        violations=violations,
        model="test-model",
        timeout=30,
        deadline=None,
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
        routing_policy=None,
        checkpoint_dir=tmp_path / "provider_components",
        spec_hash="frontend-spec",
    )
    return result, calls


def test_contract_repair_returns_only_app_and_preserves_html_css(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    manifest, before = _frontend_contract_fixture()
    repaired_source = before[-1]["content"].replace(
        "function createTask", "export function createTask"
    ).replace("function initApp", "export function initApp")
    result, calls = _repair_contract_call(
        monkeypatch,
        tmp_path,
        [json.dumps({"files": [{"path": "frontend/app.js", "content": repaired_source}]})],
    )
    assert len(calls) == 1
    assert calls[0]["payload_mode"] == "contract_repair"
    assert calls[0]["target_file"] == "frontend/app.js"
    assert calls[0]["payload"]["frozen_frontend_interface"]["target_path"] == "frontend/app.js"
    assert calls[0]["payload"]["frozen_frontend_interface"]["expected_symbols"] == [
        "createTask",
        "initApp",
    ]
    assert calls[0]["payload"]["frozen_frontend_interface"]["implementation_symbols"] == [
        "initApp",
        "createTask",
    ]
    assert "frontend/index.html" not in calls[0]["payload"]["current_source"]
    assert before[0] == result["files"][0]
    assert before[1] == result["files"][1]
    assert result["attempts"][0]["status"] == "PASS"
    assert all(receipt["status"] == "PASS" for receipt in result["boundary_receipts"])


def test_second_contract_repair_uses_latest_source_and_violations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    _manifest, files = _frontend_contract_fixture()
    first_source = files[-1]["content"].replace(
        "function createTask", "export function createTask"
    )
    final_source = first_source.replace("function initApp", "export function initApp")
    result, calls = _repair_contract_call(
        monkeypatch,
        tmp_path,
        [
            json.dumps({"files": [{"path": "frontend/app.js", "content": first_source}]}),
            json.dumps({"files": [{"path": "frontend/app.js", "content": final_source}]}),
        ],
    )
    assert len(calls) == 2
    assert calls[1]["payload"]["current_source"] == first_source
    assert [
        item["symbol"] for item in calls[1]["payload"]["structured_violations"]
    ] == ["initApp"]
    assert result["attempts"][1]["status"] == "PASS"
    repair_base = json.loads(
        (
            tmp_path
            / "provider_components/repairable_failed/frontend/frontend.leaf.001.json"
        ).read_text(encoding="utf-8")
    )
    assert repair_base["evidence_status"] == "NOT_EVALUATED"
    assert repair_base["repair_classification"] == "REPAIRABLE_FAILED"
    assert repair_base["verified_artifact"] is False
    assert repair_base["candidate_eligible"] is False


def test_contract_repair_exhausts_cleanly_after_two_requests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    _manifest, files = _frontend_contract_fixture()
    unchanged = json.dumps({"files": [files[-1]]})
    responses = [unchanged, unchanged]
    with pytest.raises(
        run_local_pipeline_impl.ProviderContractRepairExhaustedError,
        match="after 2 requests",
    ):
        _repair_contract_call(monkeypatch, tmp_path, responses)
    assert responses == []


def test_contract_repair_budget_covers_current_source_within_model_cap() -> None:
    entry = {
        "path": "frontend/app.js",
        "expected_output_chars": 6000,
    }
    budget = run_local_pipeline_impl.provider_contract_repair_output_token_budget(
        entry,
        "x" * 8180,
        model="qwen3.8-max",
    )
    assert budget == 3047
    assert budget <= run_local_pipeline_impl.provider_model_reliable_output_cap(
        "qwen3.8-max"
    )


def test_verified_provider_job_clears_only_its_repair_base(
    tmp_path: pathlib.Path,
) -> None:
    target = run_local_pipeline_impl.repairable_failed_provider_job_path(
        tmp_path, "frontend", "frontend.leaf.001"
    )
    assert target is not None
    target.parent.mkdir(parents=True)
    target.write_text("diagnostic", encoding="utf-8")
    peer = target.with_name("frontend.leaf.002.json")
    peer.write_text("peer", encoding="utf-8")

    run_local_pipeline_impl.clear_repairable_failed_provider_job(
        tmp_path,
        component_id="frontend",
        provider_job_id="frontend.leaf.001",
    )

    assert not target.exists()
    assert peer.exists()


def test_large_frontend_files_remain_one_natural_job_before_emission_planning() -> None:
    manifest = [
        {
            "path": "frontend/index.html",
            "dependencies": [],
            "expected_output_chars": 3500,
        },
        {
            "path": "frontend/styles.css",
            "dependencies": ["frontend/index.html"],
            "expected_output_chars": 6500,
        },
        {
            "path": "frontend/app.js",
            "dependencies": ["frontend/index.html", "frontend/styles.css"],
            "expected_output_chars": 28500,
            "estimated_complexity": "high",
            "fragmentation_reason": "expected_output_exceeds_bounded_job_budget",
        },
    ]
    expanded = run_local_pipeline_impl.expand_component_manifest_submodules(
        "frontend", manifest
    )
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "frontend", expanded
    )
    assert len(graph["provider_jobs"]) == 1
    assert graph["provider_jobs"][0]["owns"] == [
        "frontend/index.html",
        "frontend/styles.css",
        "frontend/app.js",
    ]
    plan = run_local_pipeline_impl.plan_provider_job_emissions(
        graph["leaves"][0]["manifest_entries"],
        model="qwen3.7-plus",
    )
    assert len(plan["emissions"]) >= 2
    assert not any(
        "app_part_" in path
        for emission in plan["emissions"]
        for path in emission["paths"]
    )


def test_incomplete_emission_keeps_completed_paths_and_completes_missing_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    entries = [
        {"path": "README.md", "dependencies": [], "estimated_complexity": "low"},
        {"path": "TEST_PLAN.md", "dependencies": [], "estimated_complexity": "low"},
        {"path": "DELIVERY_NOTES.md", "dependencies": [], "estimated_complexity": "low"},
    ]
    calls: list[dict] = []

    def fake_provider_text(messages, *_args, **kwargs):
        run_local_pipeline_impl.provider_execution_metrics.mark_call_origin("primary")
        payload = json.loads(messages[-1]["content"])
        job = payload["provider_job"]
        calls.append(job)
        requested = list(job["emission_paths"])
        returned = requested if job["completion_only"] else requested[:2]
        return json.dumps(
            {
                "files": [
                    {
                        "path": path,
                        "content": f"# {path}\n\nComplete governed documentation for local use.\n",
                    }
                    for path in returned
                ]
            }
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "plan_provider_job_emissions",
        lambda values, **_kwargs: {
            "kind": "CGKNProviderJobEmissionPlan",
            "model": "test-model",
            "ownership_paths": [item["path"] for item in values],
            "requested_output_cap": 1800,
            "model_reliable_output_cap": 5000,
            "effective_reliable_output_cap": 1800,
            "previous_observed_output": {},
            "emissions": [
                {
                    "emission_index": 1,
                    "paths": [item["path"] for item in values],
                    "estimated_output_tokens": 900,
                    "requested_output_cap": 1800,
                }
            ],
            "_entry_chunks": [values],
        },
    )
    result = run_local_pipeline_impl._provider_generate_job_with_retry(
        goal="Write local project documentation",
        component={"id": "docs", "required_paths": [item["path"] for item in entries]},
        component_pipeline={"components": [{"id": "docs"}]},
        leaf={
            "leaf_id": "docs.leaf.001",
            "path": "README.md",
            "paths": [item["path"] for item in entries],
            "owns": [item["path"] for item in entries],
            "dependencies": [],
        },
        entries=entries,
        prior_manifest=[],
        completed_files=[],
        prior_files=[],
        manifest=entries,
        repair_errors=[],
        integration_feedforward=None,
        interface_registry={},
        librarian_index={},
        model="test-model",
        timeout=30,
        deadline=None,
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
        routing_policy=None,
        pending_context={},
        last_transport_error=None,
    )
    assert [item["path"] for item in result["file_items"]] == [
        "README.md",
        "TEST_PLAN.md",
        "DELIVERY_NOTES.md",
    ]
    assert result["missing_path_recovery_calls"] == 1
    assert len(calls) == 2
    assert calls[0]["id"] == calls[1]["id"] == "docs.leaf.001"
    assert calls[0]["owns"] == calls[1]["owns"]
    assert calls[1]["completion_only"] is True
    assert calls[1]["emission_paths"] == ["DELIVERY_NOTES.md"]
    assert calls[1]["completed_owned_paths"] == ["README.md", "TEST_PLAN.md"]
    metrics = run_local_pipeline_impl.provider_execution_metrics.snapshot(
        tmp_path / "provider_phase_log.jsonl"
    )
    assert metrics["files_authored_by_primary"] == [
        "DELIVERY_NOTES.md",
        "README.md",
        "TEST_PLAN.md",
    ]


def _three_path_job_inputs() -> tuple[list[dict], dict, dict]:
    entries = [
        {"path": "A.md", "dependencies": [], "estimated_complexity": "low"},
        {"path": "B.md", "dependencies": [], "estimated_complexity": "low"},
        {"path": "C.md", "dependencies": [], "estimated_complexity": "low"},
    ]
    leaf = {
        "leaf_id": "docs.leaf.001",
        "path": "A.md",
        "paths": [entry["path"] for entry in entries],
        "owns": [entry["path"] for entry in entries],
        "dependencies": [],
    }
    component = {"id": "docs", "required_paths": list(leaf["owns"])}
    return entries, leaf, component


def _two_emission_plan(values: list[dict], **_kwargs) -> dict:
    chunks = [values[:2], values[2:]] if len(values) == 3 else [values]
    return {
        "kind": "CGKNProviderJobEmissionPlan",
        "model": "test-model",
        "ownership_paths": [entry["path"] for entry in values],
        "requested_output_cap": 1800,
        "model_reliable_output_cap": 5000,
        "effective_reliable_output_cap": 1800,
        "previous_observed_output": {},
        "emissions": [
            {
                "emission_index": index,
                "paths": [entry["path"] for entry in chunk],
                "estimated_output_tokens": 600,
                "requested_output_cap": 1200,
            }
            for index, chunk in enumerate(chunks, start=1)
        ],
        "_entry_chunks": chunks,
    }


def test_partial_job_persists_each_emission_and_reserves_prioritized_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    entries, leaf, component = _three_path_job_inputs()
    calls: list[dict] = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return {
            "file_items": [
                {
                    "path": entry["path"],
                    "content": f"# {entry['path']}\n\nVerified output.\n",
                }
                for entry in kwargs["manifest_entries"]
            ],
            "raw_output": "{}",
            "author_origin": "primary",
        }

    monkeypatch.setattr(run_local_pipeline_impl, "plan_provider_job_emissions", _two_emission_plan)
    monkeypatch.setattr(run_local_pipeline_impl, "provider_generate_component_job", fake_generate)
    deadline = run_local_pipeline_impl.ProgressDeadline(
        time.time() + 400,
        extension_seconds=900,
    )
    hard_deadline = deadline.hard_deadline
    deadline.mark_progress("test", "extension must not move the hard budget")
    result = run_local_pipeline_impl._provider_generate_job_with_retry(
        goal="Write bounded docs",
        component=component,
        component_pipeline={"components": [component]},
        leaf=leaf,
        entries=entries,
        prior_manifest=[],
        completed_files=[],
        prior_files=[],
        manifest=entries,
        repair_errors=[],
        integration_feedforward=None,
        interface_registry={},
        librarian_index={},
        model="test-model",
        timeout=90,
        deadline=deadline,
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
        routing_policy=None,
        pending_context={},
        last_transport_error=None,
        checkpoint_dir=tmp_path,
        spec_hash="spec-1",
    )

    assert deadline.hard_deadline == hard_deadline
    assert [entry["path"] for entry in calls[0]["manifest_entries"]] == ["A.md", "B.md"]
    assert calls[0]["completion_only"] is False
    assert calls[0]["budget_deadline"] <= hard_deadline - run_local_pipeline_impl.MIN_COMPLETION_RESERVE_SECONDS + 0.01
    assert [entry["path"] for entry in calls[1]["manifest_entries"]] == ["C.md"]
    assert calls[1]["completed_owned_paths"] == ["A.md", "B.md"]
    assert calls[1]["completion_only"] is True
    assert calls[1]["budget_deadline"] == hard_deadline
    assert result["missing_path_recovery_calls"] == 1
    assert [entry["path"] for entry in result["file_items"]] == ["A.md", "B.md", "C.md"]
    assert all(
        run_local_pipeline_impl.split_file_checkpoint_path(tmp_path, "docs", path).exists()
        for path in ("A.md", "B.md", "C.md")
    )


def test_failed_prioritized_completion_keeps_partial_checkpoints_and_does_not_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    entries, leaf, component = _three_path_job_inputs()
    calls: list[list[str]] = []

    def fake_generate(**kwargs):
        paths = [entry["path"] for entry in kwargs["manifest_entries"]]
        calls.append(paths)
        if kwargs["completion_only"]:
            raise RuntimeError("completion transport failed")
        return {
            "file_items": [
                {"path": path, "content": f"# {path}\n\nVerified output.\n"}
                for path in paths
            ],
            "raw_output": "{}",
            "author_origin": "primary",
        }

    monkeypatch.setattr(run_local_pipeline_impl, "plan_provider_job_emissions", _two_emission_plan)
    monkeypatch.setattr(run_local_pipeline_impl, "provider_generate_component_job", fake_generate)
    with pytest.raises(
        run_local_pipeline_impl.ProviderLeafRepairExhaustedError,
        match="prioritized missing-path completion",
    ):
        run_local_pipeline_impl._provider_generate_job_with_retry(
            goal="Write bounded docs",
            component=component,
            component_pipeline={"components": [component]},
            leaf=leaf,
            entries=entries,
            prior_manifest=[],
            completed_files=[],
            prior_files=[],
            manifest=entries,
            repair_errors=[],
            integration_feedforward=None,
            interface_registry={},
            librarian_index={},
            model="test-model",
            timeout=90,
            deadline=None,
            phase_log_path=tmp_path / "provider_phase_log.jsonl",
            routing_policy=None,
            pending_context={},
            last_transport_error=None,
            checkpoint_dir=tmp_path,
            spec_hash="spec-1",
        )

    assert calls == [["A.md", "B.md"], ["C.md"]]
    assert all(
        run_local_pipeline_impl.split_file_checkpoint_path(tmp_path, "docs", path).exists()
        for path in ("A.md", "B.md")
    )
    assert not run_local_pipeline_impl.split_file_checkpoint_path(
        tmp_path, "docs", "C.md"
    ).exists()


def test_cached_partial_job_requests_only_missing_path_and_preserves_coowned_peers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    entries, leaf, component = _three_path_job_inputs()
    completed = [
        {"path": path, "content": f"# {path}\n\nVerified checkpoint.\n"}
        for path in ("A.md", "B.md")
    ]
    calls: list[dict] = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return {
            "file_items": [{"path": "C.md", "content": "# C.md\n\nCompleted.\n"}],
            "raw_output": "{}",
            "author_origin": "fallback",
        }

    monkeypatch.setattr(run_local_pipeline_impl, "plan_provider_job_emissions", _two_emission_plan)
    monkeypatch.setattr(run_local_pipeline_impl, "provider_generate_component_job", fake_generate)
    result = run_local_pipeline_impl._provider_generate_job_with_retry(
        goal="Write bounded docs",
        component=component,
        component_pipeline={"components": [component]},
        leaf=leaf,
        entries=entries,
        prior_manifest=[],
        completed_files=completed,
        prior_files=[],
        manifest=entries,
        repair_errors=[],
        integration_feedforward=None,
        interface_registry={},
        librarian_index={},
        model="test-model",
        timeout=90,
        deadline=None,
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
        routing_policy=None,
        pending_context={},
        last_transport_error=None,
    )

    assert len(calls) == 1
    assert [entry["path"] for entry in calls[0]["manifest_entries"]] == ["C.md"]
    assert calls[0]["completion_only"] is True
    assert [entry["path"] for entry in result["file_items"]] == ["A.md", "B.md", "C.md"]
    assert run_local_pipeline_impl.component_manifest_missing_path_dependents(
        [*entries, {"path": "D.md", "dependencies": ["C.md"]}],
        ["C.md"],
    ) == ["C.md", "D.md"]
