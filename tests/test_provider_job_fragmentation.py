from __future__ import annotations

import json
import pathlib
import threading
import time

import pytest

from scripts import provider_execution_metrics, provider_jobs, run_local_pipeline_impl


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "local_project_board_provider_plan.json"


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


def test_multi_file_failure_reruns_only_ownership_unit(monkeypatch, tmp_path) -> None:
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
            owns = list(payload["provider_job"]["owns"])
            generated_units.append(owns)
            return json.dumps(
                {"files": [{"path": path, "content": _source(path)} for path in owns]}
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
    assert generated_units == [["src/a.py", "src/b.py"]]
    assert repaired["repair_scope"]["downstream_closure"] == ["src/a.py", "src/b.py"]
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
