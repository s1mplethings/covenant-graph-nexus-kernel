from __future__ import annotations

import json
import pathlib
import threading
import time

import pytest

from scripts import run_local_pipeline_impl


pytestmark = [pytest.mark.benchmark]


def _layered_manifest(file_count: int, width: int) -> list[dict[str, object]]:
    paths = [f"backend/module_{index:03d}.py" for index in range(file_count)]
    return [
        {
            "path": path,
            "purpose": f"scale benchmark module {index}",
            "dependencies": [paths[index - width]] if index >= width else [],
            "estimated_complexity": "medium",
        }
        for index, path in enumerate(paths)
    ]


@pytest.mark.parametrize(
    ("scale_name", "file_count", "width"),
    [
        ("small", 3, 2),
        ("medium", 12, 4),
        ("large", 40, 8),
        ("xlarge", 96, 12),
        ("acfv_reference", 360, 35),
    ],
)
def test_provider_split_generation_scales_from_small_to_xlarge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    scale_name: str,
    file_count: int,
    width: int,
) -> None:
    manifest = _layered_manifest(file_count, width)
    active = 0
    max_active = 0
    generated_paths: list[str] = []
    lock = threading.Lock()

    def fake_provider_text(messages, model, timeout, **kwargs):
        nonlocal active, max_active
        stage = kwargs.get("stage")
        if stage == "component_file_manifest":
            return json.dumps({"component": "backend", "files": manifest})
        assert stage == "component_file_generation"
        payloads = []
        for message in reversed(messages):
            try:
                payloads.append(json.loads(message["content"]))
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
        targets = next(
            (
                list(payload.get("provider_job", {}).get("emission_paths", []))
                for payload in payloads
                if payload.get("provider_job", {}).get("emission_paths")
            ),
            [str(kwargs.get("target_file"))],
        )
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.003)
        with lock:
            generated_paths.extend(targets)
            active -= 1
        files = [
                    {
                        "path": target,
                        "content": (
                            f'"""Generated {scale_name} benchmark leaf."""\n\n'
                            "class GeneratedModule:\n"
                            "    def __init__(self, value: int):\n"
                            "        self.value = value\n\n"
                            "    def validate(self) -> None:\n"
                            "        if self.value < 0:\n"
                            "            raise ValueError(\"value must be non-negative\")\n\n"
                            "    def run(self) -> int:\n"
                            "        self.validate()\n"
                            "        return self.value\n\n"
                            f"MODULE = GeneratedModule({int(pathlib.PurePosixPath(target).stem.rsplit('_', 1)[-1])})\n"
                        ),
                    }
                    for target in targets
                ]
        return json.dumps({"files": files} if any("provider_job" in payload for payload in payloads) else files[0])

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    monkeypatch.setenv("CGKN_PROVIDER_LEAF_MAX_WORKERS", "8")
    checkpoint_dir = tmp_path / scale_name / "provider_components"
    component = {
        "id": "backend",
        "required_paths": [str(item["path"]) for item in manifest],
        "minimum_file_count": file_count,
    }
    pipeline = {
        "components": [component],
        "merge_policy": {
            "required_final_files": [str(item["path"]) for item in manifest],
        },
    }

    started = time.perf_counter()
    result = run_local_pipeline_impl.provider_generate_project_component_split(
        goal=f"{scale_name} deterministic scale benchmark",
        component=component,
        component_pipeline=pipeline,
        prior_manifest=[],
        prior_files=[],
        repair_errors=[],
        model="benchmark-model",
        timeout=30,
        deadline=None,
        checkpoint_dir=checkpoint_dir,
        run_dir=tmp_path / scale_name,
        spec_hash=f"{scale_name}-spec",
        phase_log_path=tmp_path / scale_name / "provider_phase_log.jsonl",
        routing_policy=run_local_pipeline_impl.ProviderModelRoutingPolicy(),
        split_reason="scale_ladder_benchmark",
        original_prompt_chars=0,
    )
    elapsed = time.perf_counter() - started

    assert len(result["files"]) == file_count
    leaf_count = int(result["leaf_work_graph"]["leaf_count"])
    assert 0 < leaf_count <= file_count
    assert result["interface_registry"]["provider_count"] == file_count
    assert len(result["boundary_check_receipts"]) == file_count
    assert {receipt["status"] for receipt in result["boundary_check_receipts"]} == {"PASS"}
    assert len(generated_paths) == file_count
    assert len(set(generated_paths)) == file_count
    assert max_active >= 1
    if file_count >= 12:
        assert max_active >= 2
    assert len(result["parallel_batches"]) == len(
        run_local_pipeline_impl.component_leaf_ready_batches(result["leaf_work_graph"])
    )
    assert result["context_librarian"]["query_count"] == leaf_count
    assert result["context_librarian"]["max_selected_chars"] <= 8000
    assert elapsed < (60 if file_count >= 360 else 30)
    assert (checkpoint_dir / "interface_registries" / "backend.json").exists()
    assert len(list((checkpoint_dir / "boundary_receipts" / "backend").glob("*.json"))) == file_count
    librarian_root = checkpoint_dir / "context_librarian" / "backend"
    assert (librarian_root / "index.json").exists()
    assert len(list((librarian_root / "queries").glob("*.json"))) == leaf_count


def test_large_scale_repair_regenerates_only_the_downstream_closure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    file_count = 40
    width = 8
    manifest = _layered_manifest(file_count, width)
    generated_paths: list[str] = []

    def fake_provider_text(messages, model, timeout, **kwargs):
        if kwargs.get("stage") == "component_file_manifest":
            return json.dumps({"component": "backend", "files": manifest})
        payloads = []
        for message in reversed(messages):
            try:
                payloads.append(json.loads(message["content"]))
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
        targets = next(
            (
                list(payload.get("provider_job", {}).get("emission_paths", []))
                for payload in payloads
                if payload.get("provider_job", {}).get("emission_paths")
            ),
            [str(kwargs.get("target_file"))],
        )
        generated_paths.extend(targets)
        files = [
                    {
                        "path": target,
                        "content": (
                            '"""Repair-closure benchmark implementation."""\n\n'
                            "class GeneratedModule:\n"
                            "    def __init__(self, value: int):\n"
                            "        self.value = value\n\n"
                            "    def validate(self) -> None:\n"
                            "        if self.value < 0:\n"
                            "            raise ValueError(\"value must be non-negative\")\n\n"
                            "    def run(self) -> int:\n"
                            "        self.validate()\n"
                            "        return self.value\n\n"
                            f"MODULE = GeneratedModule({int(pathlib.PurePosixPath(target).stem.rsplit('_', 1)[-1])})\n"
                        ),
                    }
                    for target in targets
                ]
        return json.dumps({"files": files} if any("provider_job" in payload for payload in payloads) else files[0])

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", fake_provider_text)
    checkpoint_dir = tmp_path / "repair" / "provider_components"
    component = {
        "id": "backend",
        "required_paths": [str(item["path"]) for item in manifest],
        "minimum_file_count": file_count,
    }
    pipeline = {"components": [component], "merge_policy": {"required_final_files": component["required_paths"]}}
    common = {
        "goal": "large repair closure benchmark",
        "component": component,
        "component_pipeline": pipeline,
        "prior_manifest": [],
        "prior_files": [],
        "repair_errors": [],
        "model": "benchmark-model",
        "timeout": 30,
        "deadline": None,
        "checkpoint_dir": checkpoint_dir,
        "run_dir": tmp_path / "repair",
        "spec_hash": "large-repair-spec",
        "phase_log_path": tmp_path / "repair" / "provider_phase_log.jsonl",
        "routing_policy": run_local_pipeline_impl.ProviderModelRoutingPolicy(),
        "split_reason": "scale_ladder_repair_benchmark",
        "original_prompt_chars": 0,
    }

    initial = run_local_pipeline_impl.provider_generate_project_component_split(**common)
    assert len(generated_paths) == file_count
    generated_paths.clear()
    target = "backend/module_008.py"
    expected_closure = [
        "backend/module_008.py",
        "backend/module_016.py",
        "backend/module_024.py",
        "backend/module_032.py",
    ]

    repaired = run_local_pipeline_impl.provider_generate_project_component_split(
        **common,
        repair_target_files=[target],
        existing_component_files=initial["files"],
    )

    assert generated_paths == expected_closure
    assert repaired["repair_scope"]["requested_paths"] == [target]
    assert repaired["repair_scope"]["downstream_closure"] == expected_closure
    assert len(repaired["files"]) == file_count
    assert {receipt["status"] for receipt in repaired["boundary_check_receipts"]} == {"PASS"}
