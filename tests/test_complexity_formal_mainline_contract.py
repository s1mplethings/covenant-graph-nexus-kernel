from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

from scripts import compose_local_pipeline
from scripts import discovery_selection_lane
from scripts import post_build_finalize
from scripts import run_local_pipeline_impl


GOAL = """
构建一个面向视频创作者的本地 AI 切片工作台。
实现 ingest_video、extract_audio、build_audio_chunk_manifest、transcribe_chunks、
merge_transcript、optional_analysis、select_segments、build_clip_manifest、
render_clips_batch、export_results。
提供 PipelineRunner、JobManager、取消、恢复和冷启动重放。
pytest 至少 50 个测试，GUI 与 CLI 必须共用领域核心。
"""


def video_plan() -> dict:
    selected_requirement = {
        "selected_requirement_id": "local_video_material_workbench_requirement",
        "selected_requirement_name": "Local video material processing workbench",
        "interpreted_need": "Local media processing and clip selection.",
        "selected_product_shape": "GUI plus CLI over a shared core.",
    }
    selected_direction = {
        "selected_id": "local_video_workbench",
        "selected_name": "Local Video Material Workbench",
    }
    selected = discovery_selection_lane.select_candidate(
        discovery_selection_lane.generate_candidates(GOAL)
    )
    assert selected is not None
    contract = discovery_selection_lane.build_contract(selected)
    return {
        "selected_requirement": selected_requirement,
        "selected_project_direction": selected_direction,
        "complexity_project_contract": contract,
    }


def test_generation_success_is_not_reported_as_formal_delivery_pass() -> None:
    boundary = run_local_pipeline_impl.generation_only_success_boundary()

    assert boundary["status"] == "pass"
    assert boundary["workflow_state"] == "generation_completed"
    assert boundary["evidence_status"] == "NOT_EVALUATED"
    assert boundary["post_build_required"] is True
    assert boundary["packaging_required"] is True
    assert boundary["final_delivery_allowed"] is False
    assert boundary["final_verdict"] == "NOT_EVALUATED"
    assert boundary["not_final_delivery"] is True


def test_post_build_video_option_is_not_forwarded_to_legacy_finalize(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    received: dict = {}
    video_option: dict = {}

    def legacy_run(**kwargs):
        received.update(kwargs)
        return {"status": "pass"}

    monkeypatch.setattr(
        post_build_finalize,
        "_legacy",
        lambda: SimpleNamespace(run_candidate_post_build_finalize=legacy_run),
    )
    monkeypatch.setattr(
        post_build_finalize,
        "ensure_candidate_review_artifacts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        post_build_finalize,
        "ensure_video_evidence",
        lambda *_args, **kwargs: video_option.update(kwargs),
    )
    monkeypatch.setattr(
        post_build_finalize,
        "apply_complexity_contract_gate",
        lambda *_args, **_kwargs: None,
    )

    result = post_build_finalize.run(
        project_dir=tmp_path,
        run_dir=tmp_path,
        timeout=10,
        video_requested=False,
        marker="preserved",
    )

    assert result["status"] == "pass"
    assert received["marker"] == "preserved"
    assert "video_requested" not in received
    assert video_option["explicit_requested"] is False


def test_requirement_direction_alignment_rejects_cross_domain_selection() -> None:
    mismatch = run_local_pipeline_impl.requirement_discovery_alignment(
        {
            "selected_requirement_id": "local_video_material_workbench_requirement",
            "selected_requirement_name": "Video workbench",
        },
        {
            "selected_id": "local_data_quality_studio",
            "selected_name": "Local Data Quality Studio",
        },
    )

    assert mismatch["status"] == "NEEDS_REWORK"
    assert mismatch["requirement_domain"] == "media"
    assert mismatch["direction_domain"] == "data_quality"


def test_specialized_analysis_requirement_and_discovery_align() -> None:
    aligned = run_local_pipeline_impl.requirement_discovery_alignment(
        {
            "selected_requirement_id": "goal_derived_specialized_analysis_requirement",
            "selected_requirement_name": "Goal-derived specialized analysis workbench",
        },
        {
            "selected_id": "goal_derived_specialized_analysis_workbench",
            "selected_name": "Goal-Derived Specialized Analysis Workbench",
        },
    )

    assert aligned["status"] == "PASS"
    assert aligned["requirement_domain"] == "specialized_analysis"
    assert aligned["direction_domain"] == "specialized_analysis"


def test_visual_novel_requirement_and_discovery_align() -> None:
    aligned = run_local_pipeline_impl.requirement_discovery_alignment(
        {
            "selected_requirement_id": "local_visual_novel_studio_requirement",
            "selected_requirement_name": "Local visual novel authoring studio",
        },
        {
            "selected_id": "local_visual_novel_studio",
            "selected_name": "Local Visual Novel Authoring Studio",
        },
    )

    assert aligned["status"] == "PASS"
    assert aligned["requirement_domain"] == "visual_novel"
    assert aligned["direction_domain"] == "visual_novel"


def test_component_leaf_work_graph_orders_exact_path_dependencies() -> None:
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "core",
        [
            {
                "path": "core/service.py",
                "purpose": "service",
                "dependencies": ["uses core/model.py"],
            },
            {"path": "core/model.py", "purpose": "model", "dependencies": []},
            {
                "path": "core/cli.py",
                "purpose": "cli",
                "dependencies": ["core/service.py"],
            },
        ],
    )

    assert graph["kind"] == "CGKNComponentLeafWorkGraph"
    assert graph["max_files_per_leaf"] == 1
    assert [path for leaf in graph["leaves"] for path in leaf["paths"]] == [
        "core/model.py",
        "core/service.py",
        "core/cli.py",
    ]
    assert graph["leaves"][1]["depends_on"] == ["core/model.py"]


def test_frontend_leaf_work_graph_breaks_asset_dom_dependency_cycle() -> None:
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "frontend",
        [
            {
                "path": "index.html",
                "dependencies": ["src/app.js", "src/styles.css"],
            },
            {
                "path": "src/app.js",
                "dependencies": ["index.html", "src/styles.css"],
            },
            {
                "path": "src/styles.css",
                "dependencies": ["index.html", "src/app.js"],
            },
        ],
    )

    assert [path for leaf in graph["leaves"] for path in leaf["paths"]] == [
        "index.html",
        "src/styles.css",
        "src/app.js",
    ]
    assert graph["leaves"][0]["depends_on"] == []
    assert graph["leaves"][1]["paths"] == ["src/styles.css", "src/app.js"]
    assert graph["leaves"][1]["depends_on"] == ["index.html"]
    assert any(
        warning.startswith("frontend_generation_dependency_normalized:")
        for warning in graph["ordering_warnings"]
    )
    assert not any(
        warning.startswith("cyclic_or_unresolved")
        for warning in graph["ordering_warnings"]
    )
    assert run_local_pipeline_impl.component_leaf_downstream_closure(
        graph,
        ["src/styles.css"],
    ) == ["src/styles.css", "src/app.js"]
    assert run_local_pipeline_impl.component_leaf_downstream_closure(
        graph,
        ["index.html"],
    ) == ["index.html", "src/styles.css", "src/app.js"]


def test_leaf_ready_batches_and_downstream_closure_are_dependency_scoped() -> None:
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "backend",
        [
            {"path": "backend/a.py", "dependencies": []},
            {"path": "backend/b.py", "dependencies": []},
            {"path": "backend/c.py", "dependencies": ["backend/a.py", "backend/b.py"]},
            {"path": "backend/d.py", "dependencies": ["backend/c.py"]},
        ],
    )

    assert [
        [path for leaf in batch for path in leaf["paths"]]
        for batch in run_local_pipeline_impl.component_leaf_ready_batches(graph)
    ] == [
        ["backend/a.py", "backend/b.py"],
        ["backend/c.py"],
        ["backend/d.py"],
    ]
    assert run_local_pipeline_impl.component_leaf_downstream_closure(
        graph,
        ["backend/a.py"],
    ) == ["backend/a.py", "backend/b.py", "backend/c.py", "backend/d.py"]


def test_interface_registry_records_python_javascript_and_html_consumers() -> None:
    registry = run_local_pipeline_impl.build_project_interface_registry(
        [
            {
                "path": "backend/model.py",
                "content": "class Job:\n    def run(self):\n        return True\n",
            },
            {
                "path": "backend/service.py",
                "content": "from backend.model import Job\njob = Job()\njob.run()\n",
            },
            {
                "path": "src/util.js",
                "content": "export function boot() { return true; }\n",
            },
            {
                "path": "src/app.js",
                "content": "import { boot } from './util.js';\nboot();\n",
            },
            {
                "path": "index.html",
                "content": '<script type="module" src="src/app.js"></script>\n',
            },
        ]
    )

    edges = {
        (
            edge["consumer_path"],
            edge["provider_path"],
            edge["contract_kind"],
        )
        for edge in registry["consumer_edges"]
    }
    assert ("backend/service.py", "backend/model.py", "python_import") in edges
    assert ("src/app.js", "src/util.js", "javascript_import") in edges
    assert ("index.html", "src/app.js", "html_asset") in edges
    javascript_edge = next(
        edge
        for edge in registry["consumer_edges"]
        if edge["consumer_path"] == "src/app.js"
        and edge["provider_path"] == "src/util.js"
    )
    assert javascript_edge["symbols"] == ["boot"]
    assert registry["registry_sha256"]


def test_component_quality_rejects_broken_cs_demo_frontend_facade() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="frontend",
        files=[
            {
                "path": "src/app_part_01.js",
                "content": (
                    "function el(id) { return document.getElementById(id); }\n"
                    "export function createApp() { return true; }\n"
                ),
            },
            {
                "path": "src/app_part_02.js",
                "content": (
                    "import { createApp } from './app_part_01.js';\n"
                    "export function renderEvidenceReport() { return el('report'); }\n"
                ),
            },
            {
                "path": "src/app.js",
                "content": (
                    "import { createApp } from './app_part_01.js';\n"
                    "export { createApp, renderEvidenceReport };\n"
                ),
            },
        ],
    )

    assert validation["status"] == "fail"
    assert any(
        "re-exports missing local binding renderEvidenceReport"
        in blocker
        for blocker in validation["blockers"]
    )
    assert any(
        "calls unimported sibling symbol el"
        in blocker
        for blocker in validation["blockers"]
    )


def test_component_quality_accepts_valid_split_frontend_interfaces() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="frontend",
        files=[
            {
                "path": "src/dom.js",
                "content": "export function el(id) { return document.getElementById(id); }\n",
            },
            {
                "path": "src/report.js",
                "content": (
                    "import { el } from './dom.js';\n"
                    "export function renderEvidenceReport() { return el('report'); }\n"
                ),
            },
            {
                "path": "src/app.js",
                "content": (
                    "import { renderEvidenceReport } from './report.js';\n"
                    "export { renderEvidenceReport };\n"
                ),
            },
        ],
    )

    assert validation["status"] == "pass"
    assert validation["blockers"] == []
    assert validation["receipt_sha256"]


def test_component_quality_rejects_missing_javascript_provider_export() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="frontend",
        files=[
            {"path": "src/provider.js", "content": "export const ready = true;\n"},
            {
                "path": "src/consumer.js",
                "content": "import { missing } from './provider.js';\nmissing();\n",
            },
        ],
    )

    assert validation["status"] == "fail"
    assert "src/consumer.js imports missing missing from src/provider.js" in validation["blockers"]


def test_component_quality_rejects_unpublished_manifest_symbol() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="frontend",
        files=[
            {"path": "src/app.js", "content": "export const ready = true;\n"},
        ],
        manifest_entries=[
            {
                "path": "src/app.js",
                "expected_symbols": ["ready", "runPipeline"],
            }
        ],
    )

    assert validation["status"] == "fail"
    assert "src/app.js does not implement expected symbols: runPipeline" in validation["blockers"]


def test_document_manifest_symbols_are_migrated_to_prose_anchors() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="docs",
        files=[
            {
                "path": "README.md",
                "content": "# CS2 Demo Anomaly Lab\n\nRun `python -m main --help` for the CLI.\n",
            }
        ],
        manifest_entries=[
            {
                "path": "README.md",
                "expected_symbols": ["main", "cs2-demo-anomaly-lab"],
                "estimated_complexity": "low",
            }
        ],
    )

    assert validation["status"] == "pass"
    assert validation["blockers"] == []


def test_document_anchor_contract_rejects_missing_required_prose() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="docs",
        files=[{"path": "README.md", "content": "# Project\n\nRun the command.\n"}],
        manifest_entries=[
            {
                "path": "README.md",
                "expected_anchors": ["human review required"],
                "estimated_complexity": "low",
            }
        ],
    )

    assert validation["status"] == "fail"
    assert any("omits expected documentation/config anchors" in item for item in validation["blockers"])


def test_requirements_contract_ignores_product_policy_prose_anchor() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="foundation",
        files=[
            {
                "path": "requirements.txt",
                "content": "demoparser2>=0.37\npy7zr>=0.22\n",
            }
        ],
        manifest_entries=[
            {
                "path": "requirements.txt",
                "expected_anchors": [
                    "demoparser2",
                    "no automatic ban or definitive cheating classifier",
                ],
                "estimated_complexity": "low",
            }
        ],
    )

    assert validation["status"] == "pass"
    assert validation["blockers"] == []


def test_python_publication_contract_ignores_document_prose_anchors() -> None:
    contract = run_local_pipeline_impl.leaf_implementation_depth_contract(
        {
            "path": "backend/anomaly.py",
            "expected_symbols": ["detect_windows"],
            "expected_anchors": ["snap-before-shot human review explanation"],
            "estimated_complexity": "medium",
        }
    )

    assert contract["expected_symbols"] == ["detect_windows"]
    assert contract["expected_anchors"] == []


def test_application_entry_may_delegate_to_validated_backend_cli() -> None:
    blockers = run_local_pipeline_impl.application_entry_stage_violations(
        "main.py",
        (
            "from backend.cli import run_cli\n\n"
            "if __name__ == '__main__':\n"
            "    raise SystemExit(run_cli())\n"
        ),
        ["catalog_and_provenance", "bounded_acquisition"],
    )

    assert blockers == []


def test_test_component_rejects_direct_state_assumption_for_stage_result_envelope() -> None:
    component_contract = {
        "executable_interface_graph": {
            "stage_callable": {
                "symbols": ["parse_demo"],
                "result_fields": ["status", "output"],
            }
        }
    }
    files = [
        {
            "path": "backend/stages.py",
            "content": (
                "def parse_demo(state):\n"
                "    return {'status': 'success', 'output': {'ticks': 12}}\n"
            ),
        },
        {
            "path": "tests/test_pipeline.py",
            "content": (
                "from backend.stages import parse_demo\n\n"
                "def test_parse_demo():\n"
                "    result = parse_demo({})\n"
                "    assert result['ticks'] == 12\n"
            ),
        },
    ]

    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="tests",
        files=[files[1]],
        prior_files=[files[0]],
        component_contract=component_contract,
    )

    assert validation["status"] == "fail"
    assert any("treats stage result" in item for item in validation["blockers"])


def test_test_component_accepts_status_and_output_stage_result_contract() -> None:
    component_contract = {
        "executable_interface_graph": {
            "stage_callable": {"symbols": ["parse_demo"]}
        }
    }
    source = {
        "path": "backend/stages.py",
        "content": (
            "def parse_demo(state):\n"
            "    return {'status': 'success', 'output': {'ticks': 12}}\n"
        ),
    }
    test = {
        "path": "tests/test_pipeline.py",
        "content": (
            "from backend.stages import parse_demo\n\n"
            "def test_parse_demo():\n"
            "    result = parse_demo({})\n"
            "    assert result['status'] == 'success'\n"
            "    assert result['output']['ticks'] == 12\n"
        ),
    }

    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="tests",
        files=[test],
        prior_files=[source],
        component_contract=component_contract,
    )

    assert validation["status"] == "pass"


def test_foundation_quality_rejects_missing_goal_runtime_dependencies() -> None:
    component_contract = {
        "canonical_goal_spec": {
            "runtime_dependencies": ["demoparser2", "py7zr"],
        }
    }
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="foundation",
        files=[
            {
                "path": "pyproject.toml",
                "content": (
                    "[project]\n"
                    "name = 'cs2-demo-anomaly-lab'\n"
                    "version = '0.1.0'\n"
                    "dependencies = ['Flask>=3']\n"
                ),
            }
        ],
        component_contract=component_contract,
    )

    assert validation["status"] == "fail"
    assert any("demoparser2, py7zr" in item for item in validation["blockers"])


def test_foundation_quality_accepts_goal_runtime_dependencies() -> None:
    component_contract = {
        "canonical_goal_spec": {
            "runtime_dependencies": ["demoparser2", "py7zr"],
        }
    }
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="foundation",
        files=[
            {
                "path": "pyproject.toml",
                "content": (
                    "[project]\n"
                    "name = 'cs2-demo-anomaly-lab'\n"
                    "version = '0.1.0'\n"
                    "dependencies = ['demoparser2>=0.39', 'py7zr>=1.0']\n"
                ),
            }
        ],
        component_contract=component_contract,
    )

    assert validation["status"] == "pass"


def test_component_quality_accepts_python_facade_import_bindings_as_public_symbols() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="backend",
        files=[
            {
                "path": "backend/stages_part_01.py",
                "content": (
                    "def define_document_contracts(state):\n"
                    "    return {**state, 'contracts': True}\n"
                ),
            },
            {
                "path": "backend/stages.py",
                "content": (
                    "from .stages_part_01 import define_document_contracts\n"
                    "from .stages_part_01 import define_document_contracts as define_contracts\n"
                ),
            },
        ],
        manifest_entries=[
            {
                "path": "backend/stages.py",
                "expected_symbols": ["define_document_contracts", "define_contracts"],
                "generation_role": "compatibility_facade",
            }
        ],
    )

    assert validation["status"] == "pass"
    assert validation["blockers"] == []


def test_component_quality_accepts_collected_unittest_methods_as_test_symbols() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="tests",
        files=[
            {
                "path": "tests/test_app.py",
                "content": (
                    "import unittest\n\n"
                    "class TestApp(unittest.TestCase):\n"
                    "    def test_app_initialization(self):\n"
                    "        self.assertTrue(True)\n\n"
                    "    def test_basic_functionality(self):\n"
                    "        self.assertEqual(2 + 2, 4)\n"
                ),
            }
        ],
        manifest_entries=[
            {
                "path": "tests/test_app.py",
                "expected_symbols": ["test_app_initialization", "test_basic_functionality"],
            }
        ],
    )

    assert validation["status"] == "pass"
    assert validation["blockers"] == []


def test_assembled_project_quality_requires_component_receipts_and_clean_merge() -> None:
    files = [
        {"path": "src/value.js", "content": "export const value = 1;\n"},
        {
            "path": "src/app.js",
            "content": "import { value } from './value.js';\nexport { value };\n",
        },
    ]
    component_validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="frontend",
        files=files,
    )
    assembled = run_local_pipeline_impl.validate_assembled_project_quality(
        [
            {
                "component_id": "frontend",
                "files": files,
                "module_quality_validation": component_validation,
            }
        ],
        files,
    )

    assert component_validation["status"] == "pass"
    assert assembled["status"] == "pass"
    assert assembled["component_receipt_hashes"] == [
        component_validation["receipt_sha256"]
    ]


def test_generation_context_librarian_retrieves_direct_dependencies_with_fixed_budget(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CGKN_PROVIDER_LIBRARIAN_MAX_ITEMS", "6")
    monkeypatch.setenv("CGKN_PROVIDER_LIBRARIAN_MAX_CHARS", "5000")
    files = [
        {
            "path": f"backend/module_{index:02d}.py",
            "content": (
                f"class Module{index:02d}:\n"
                "    def run(self):\n"
                f"        return {index}\n"
                + ("# irrelevant implementation detail\n" * 200)
            ),
        }
        for index in range(60)
    ]
    manifest = [
        {"path": item["path"], "purpose": f"module {index}", "dependencies": []}
        for index, item in enumerate(files)
    ]
    target = {
        "leaf_id": "backend.leaf.061",
        "path": "backend/consumer.py",
        "depends_on": ["backend/module_00.py"],
        "declared_dependencies": ["backend/module_00.py"],
    }
    index_doc = run_local_pipeline_impl.build_generation_context_librarian_index(
        goal="build a modular backend",
        component={"id": "backend"},
        component_pipeline={"components": [{"id": "backend"}]},
        manifest=manifest,
        completed_files=files,
        prior_files=[],
        integration_feedforward={},
    )
    pack = run_local_pipeline_impl.query_generation_context_librarian(
        index_doc,
        leaf=target,
    )

    assert index_doc["entry_count"] > 100
    assert pack["context_budget"]["selected_items"] <= 6
    assert pack["context_budget"]["selected_chars"] <= 5000
    assert pack["excluded_entry_count"] > 100
    assert "backend/module_00.py" in [
        item["path"] for item in pack["selected_items"]
    ]
    assert "backend/module_59.py" not in [
        item["path"] for item in pack["selected_items"]
    ]


def test_implementation_depth_contract_rejects_thin_medium_leaf() -> None:
    entry = {
        "path": "backend/service.py",
        "purpose": "validate requests, persist records, and expose a query API",
        "estimated_complexity": "medium",
        "responsibilities": [
            "validate incoming records",
            "persist and query records",
        ],
        "acceptance_checks": [
            "invalid records are rejected",
            "saved records can be queried",
        ],
        "expected_symbols": ["RecordService"],
    }
    contract = run_local_pipeline_impl.leaf_implementation_depth_contract(entry)
    receipt = run_local_pipeline_impl.analyze_leaf_implementation_depth(
        entry["path"],
        "class RecordService:\n    pass\n",
        contract,
    )

    assert contract["enforcement_mode"] == "required"
    assert receipt["status"] == "FAIL"
    assert any("stub implementations" in blocker for blocker in receipt["blockers"])
    assert any("behavior units" in blocker for blocker in receipt["blockers"])


def test_implementation_depth_contract_accepts_substantive_medium_leaf() -> None:
    entry = {
        "path": "backend/service.py",
        "purpose": "validate requests, persist records, and expose a query API",
        "estimated_complexity": "medium",
        "responsibilities": [
            "validate incoming records",
            "persist and query records",
        ],
        "acceptance_checks": [
            "invalid records are rejected",
            "saved records can be queried",
        ],
        "expected_symbols": ["RecordService"],
    }
    content = '''class RecordService:
    def __init__(self):
        self._records = {}

    def save(self, key, value):
        if not key:
            raise ValueError("key is required")
        self._records[key] = value
        return value

    def get(self, key):
        if key not in self._records:
            raise KeyError(key)
        return self._records[key]
'''
    receipt = run_local_pipeline_impl.analyze_leaf_implementation_depth(
        entry["path"],
        content,
        run_local_pipeline_impl.leaf_implementation_depth_contract(entry),
    )

    assert receipt["status"] == "PASS"
    assert receipt["metrics"]["behavior_units"] >= 3
    assert receipt["metrics"]["substantive_statements"] >= 5


def test_implementation_depth_allows_idiomatic_exception_marker_classes() -> None:
    entry = {
        "path": "backend/errors.py",
        "purpose": "define the inventory error taxonomy",
        "estimated_complexity": "low",
        "responsibilities": ["define typed domain errors"],
        "acceptance_checks": ["callers can catch inventory errors by type"],
        "expected_symbols": ["InventoryError", "NotFoundError"],
    }
    content = '''class InventoryError(Exception):
    pass


class NotFoundError(InventoryError):
    pass
'''
    receipt = run_local_pipeline_impl.analyze_leaf_implementation_depth(
        entry["path"],
        content,
        run_local_pipeline_impl.leaf_implementation_depth_contract(entry),
    )

    assert receipt["status"] == "PASS"
    assert receipt["metrics"]["behavior_units"] == 2


def test_implementation_depth_allows_protocol_method_declarations_only() -> None:
    entry = {
        "path": "backend/interfaces.py",
        "purpose": "define a typed source research boundary",
        "estimated_complexity": "medium",
        "responsibilities": ["define the source-search and platform-research interfaces"],
        "acceptance_checks": ["concrete adapters can implement both interfaces"],
        "expected_symbols": ["SourceResearch"],
    }
    protocol_content = '''from typing import Protocol


class SourceResearch(Protocol):
    def search(self, query: str) -> list[str]:
        ...

    def research(self, platform: str) -> dict:
        ...

    def refresh(self, platform: str) -> dict:
        ...

    def cite(self, source_url: str) -> dict:
        ...

    def propose_adapter(self, platform: str) -> dict:
        ...
'''
    protocol_receipt = run_local_pipeline_impl.analyze_leaf_implementation_depth(
        entry["path"],
        protocol_content,
        run_local_pipeline_impl.leaf_implementation_depth_contract(entry),
    )
    concrete_receipt = run_local_pipeline_impl.analyze_leaf_implementation_depth(
        entry["path"],
        protocol_content.replace("class SourceResearch(Protocol):", "class SourceResearch:"),
        run_local_pipeline_impl.leaf_implementation_depth_contract(entry),
    )

    assert protocol_receipt["status"] == "PASS"
    assert concrete_receipt["status"] == "FAIL"
    assert any("stub implementations" in blocker for blocker in concrete_receipt["blockers"])


def test_implementation_depth_counts_css_selectors_and_declarations() -> None:
    entry = {
        "path": "src/styles.css",
        "purpose": "style the analysis review workspace",
        "estimated_complexity": "medium",
        "responsibilities": ["provide responsive review layout and visible risk states"],
        "acceptance_checks": ["the interface has usable layout and focus states"],
        "expected_symbols": [],
    }
    content = '''\
:root {
  --surface: #101828;
  --text: #f8fafc;
}
.workspace {
  display: grid;
  grid-template-columns: 16rem 1fr;
  min-height: 100vh;
}
.workspace button:focus-visible {
  outline: 3px solid #60a5fa;
  outline-offset: 2px;
}
@media (max-width: 48rem) {
  .workspace {
    grid-template-columns: 1fr;
  }
}
'''
    receipt = run_local_pipeline_impl.analyze_leaf_implementation_depth(
        entry["path"],
        content,
        run_local_pipeline_impl.leaf_implementation_depth_contract(entry),
    )

    assert receipt["status"] == "PASS"
    assert receipt["metrics"]["behavior_units"] >= 3
    assert receipt["metrics"]["substantive_statements"] >= 5


def test_leaf_interface_contract_uses_real_completed_python_interface() -> None:
    graph = run_local_pipeline_impl.build_component_leaf_work_graph(
        "core",
        [
            {"path": "core/model.py", "dependencies": []},
            {"path": "core/service.py", "dependencies": ["core/model.py"]},
        ],
    )
    contract = run_local_pipeline_impl.build_leaf_interface_contract(
        component_id="core",
        leaf=graph["leaves"][1],
        completed_files=[
            {
                "path": "core/model.py",
                "content": "class Job:\n    def cancel(self, reason):\n        return reason\n",
            }
        ],
        prior_files=[],
        integration_feedforward={},
    )

    assert contract["kind"] == "CGKNLeafInterfaceContract"
    assert contract["resolved_dependency_paths"] == ["core/model.py"]
    model_interface = contract["authoritative_interface_catalog"][0]
    assert model_interface["path"] == "core/model.py"
    assert model_interface["python"]["classes"][0]["name"] == "Job"
    assert "cancel(self, reason)" in model_interface["python"]["classes"][0]["methods"]


def test_leaf_interface_catalog_projection_is_bounded_without_losing_signatures() -> None:
    methods = "\n".join(
        f"    def operation_{index}(self, value, option=None):\n        return value\n"
        for index in range(40)
    )
    completed = [
        {
            "path": f"core/provider_{provider_index}.py",
            "content": f"class Provider{provider_index}:\n{methods}",
        }
        for provider_index in range(12)
    ]
    leaf = {
        "leaf_id": "tests.leaf.001",
        "path": "tests/test_integration.py",
        "depends_on": [item["path"] for item in completed],
        "declared_dependencies": [item["path"] for item in completed],
    }

    contract = run_local_pipeline_impl.build_leaf_interface_contract(
        component_id="tests",
        leaf=leaf,
        completed_files=[],
        prior_files=completed,
        integration_feedforward={},
    )

    encoded = json.dumps(contract["authoritative_interface_catalog"], ensure_ascii=False)
    assert len(contract["authoritative_interface_catalog"]) <= 8
    assert contract["authoritative_interface_catalog_chars"] <= 8000
    assert len(encoded) < 9000
    first = contract["authoritative_interface_catalog"][0]
    assert first["python"]["classes"][0]["name"] == "Provider0"
    assert "operation_0(self, value, option)" in first["python"]["classes"][0]["methods"]
    assert "method_contracts" not in encoded


def test_leaf_interface_catalog_budget_can_be_lowered(monkeypatch) -> None:
    monkeypatch.setenv("CGKN_PROVIDER_INTERFACE_CATALOG_MAX_CHARS", "4000")
    completed = [
        {
            "path": f"core/provider_{index}.py",
            "content": (
                f"class Provider{index}:\n"
                + "\n".join(
                    f"    def operation_{method}(self, value):\n        return value"
                    for method in range(20)
                )
            ),
        }
        for index in range(8)
    ]
    contract = run_local_pipeline_impl.build_leaf_interface_contract(
        component_id="tests",
        leaf={
            "leaf_id": "tests.leaf.001",
            "path": "tests/test_all.py",
            "depends_on": [item["path"] for item in completed],
            "declared_dependencies": [item["path"] for item in completed],
        },
        completed_files=[],
        prior_files=completed,
        integration_feedforward={},
    )

    assert contract["authoritative_interface_catalog_max_chars"] == 4000
    assert contract["authoritative_interface_catalog_chars"] <= 4000


def test_python_leaf_interface_validation_catches_missing_generated_method() -> None:
    violations = run_local_pipeline_impl.python_leaf_interface_violations(
        [
            {
                "path": "core/orchestrator.py",
                "content": "class Orchestrator:\n    def run(self):\n        return True\n",
            },
            {
                "path": "cli/main.py",
                "content": (
                    "from core.orchestrator import Orchestrator\n"
                    "runner = Orchestrator()\n"
                    "runner.resume()\n"
                ),
            },
        ],
        source_paths={"cli/main.py"},
    )

    assert violations == [
        "cli/main.py calls missing Orchestrator.resume from core/orchestrator.py"
    ]


def test_python_leaf_interface_validation_allows_implemented_generated_method() -> None:
    violations = run_local_pipeline_impl.python_leaf_interface_violations(
        [
            {
                "path": "core/orchestrator.py",
                "content": "class Orchestrator:\n    def resume(self):\n        return True\n",
            },
            {
                "path": "cli/main.py",
                "content": (
                    "from core.orchestrator import Orchestrator\n"
                    "runner = Orchestrator()\n"
                    "runner.resume()\n"
                ),
            },
        ],
        source_paths={"cli/main.py"},
    )

    assert violations == []


def test_python_leaf_interface_validation_tracks_instance_attribute_consumers() -> None:
    violations = run_local_pipeline_impl.python_leaf_interface_violations(
        [
            {
                "path": "core/orchestrator.py",
                "content": "class Orchestrator:\n    def run(self):\n        return True\n",
            },
            {
                "path": "gui/controller.py",
                "content": (
                    "from core.orchestrator import Orchestrator\n"
                    "class Controller:\n"
                    "    def __init__(self):\n"
                    "        self.runner = Orchestrator()\n"
                    "    def resume(self):\n"
                    "        self.runner.resume()\n"
                ),
            },
        ],
        source_paths={"gui/controller.py"},
    )

    assert violations == [
        "gui/controller.py calls missing Orchestrator.resume from core/orchestrator.py"
    ]


def test_python_leaf_interface_validation_resolves_relative_alias_imports() -> None:
    violations = run_local_pipeline_impl.python_leaf_interface_violations(
        [
            {
                "path": "core/model.py",
                "content": "class Job:\n    def run(self):\n        return True\n",
            },
            {
                "path": "core/service.py",
                "content": (
                    "from .model import Job as WorkItem\n"
                    "item = WorkItem()\n"
                    "item.cancel()\n"
                ),
            },
        ],
        source_paths={"core/service.py"},
    )

    assert violations == [
        "core/service.py calls missing Job.cancel from core/model.py"
    ]


def test_python_leaf_interface_validation_checks_constructor_and_function_signatures() -> None:
    files = [
        {
            "path": "backend/models.py",
            "content": (
                "from dataclasses import dataclass\n"
                "@dataclass\n"
                "class Product:\n"
                "    product_id: str\n"
                "    name: str\n"
                "    price: int\n"
            ),
        },
        {
            "path": "backend/validation.py",
            "content": "def validate_quantity(value, *, field):\n    return int(value)\n",
        },
        {
            "path": "backend/service.py",
            "content": (
                "from backend.models import Product\n"
                "from backend.validation import validate_quantity\n"
                "def build():\n"
                "    product = Product(product_id='sku', name='Keyboard', category='hardware')\n"
                "    return validate_quantity(1, 'stock')\n"
            ),
        },
    ]

    violations = run_local_pipeline_impl.python_leaf_interface_violations(
        files,
        source_paths={"backend/service.py"},
    )

    assert any("unsupported keywords category" in item for item in violations)
    assert any("missing required arguments price" in item for item in violations)
    assert any("2 positional arguments exceed 1" in item for item in violations)
    assert any("missing required arguments field" in item for item in violations)


def test_python_leaf_interface_validation_accepts_matching_call_signatures() -> None:
    files = [
        {
            "path": "backend/models.py",
            "content": (
                "from dataclasses import dataclass\n"
                "@dataclass\n"
                "class Product:\n"
                "    product_id: str\n"
                "    name: str\n"
                "    price: int\n"
            ),
        },
        {
            "path": "backend/validation.py",
            "content": "def validate_quantity(value, *, field):\n    return int(value)\n",
        },
        {
            "path": "backend/service.py",
            "content": (
                "from backend.models import Product\n"
                "from backend.validation import validate_quantity\n"
                "def build():\n"
                "    product = Product(product_id='sku', name='Keyboard', price=10)\n"
                "    return product, validate_quantity(1, field='stock')\n"
            ),
        },
    ]

    assert not run_local_pipeline_impl.python_leaf_interface_violations(
        files,
        source_paths={"backend/service.py"},
    )


def test_python_leaf_interface_validation_checks_factory_bound_method_signatures() -> None:
    files = [
        {
            "path": "backend/service.py",
            "content": (
                "class InventoryService:\n"
                "    def create_item(self, *, item_id, name):\n"
                "        return item_id, name\n"
            ),
        },
        {
            "path": "backend/tests/test_service.py",
            "content": (
                "from backend.service import InventoryService\n"
                "def make_service():\n"
                "    return InventoryService()\n"
                "def test_create():\n"
                "    service = make_service()\n"
                "    service.create_item('sku', 'Keyboard')\n"
            ),
        },
    ]

    violations = run_local_pipeline_impl.python_leaf_interface_violations(
        files,
        source_paths={"backend/tests/test_service.py"},
    )

    assert any("2 positional arguments exceed 0" in item for item in violations)
    assert any("missing required arguments item_id, name" in item for item in violations)
    assert any(
        "expected signature InventoryService.create_item(*, item_id, name)" in item
        for item in violations
    )


def test_python_leaf_interface_validation_checks_annotated_helper_parameter_methods() -> None:
    files = [
        {
            "path": "backend/artifact_store.py",
            "content": (
                "class ArtifactStore:\n"
                "    def save_stage_record(self, attempt_id, stage, *, record_kind):\n"
                "        return True\n"
            ),
        },
        {
            "path": "tests/test_artifacts.py",
            "content": (
                "from backend.artifact_store import ArtifactStore\n"
                "def assert_round_trip(store: ArtifactStore):\n"
                "    store.save_stage_record('a', 'stage', 'record')\n"
            ),
        },
    ]

    violations = run_local_pipeline_impl.python_leaf_interface_violations(
        files,
        source_paths={"tests/test_artifacts.py"},
    )

    assert any("3 positional arguments exceed 2" in item for item in violations)
    assert any("missing required arguments record_kind" in item for item in violations)


def test_python_leaf_interface_validation_rejects_calling_property_as_method() -> None:
    files = [
        {
            "path": "backend/artifact_store.py",
            "content": (
                "class ArtifactStore:\n"
                "    @property\n"
                "    def base_dir(self):\n"
                "        return 'artifacts'\n"
            ),
        },
        {
            "path": "backend/reporting.py",
            "content": (
                "from backend.artifact_store import ArtifactStore\n"
                "def report(store: ArtifactStore):\n"
                "    return store.base_dir()\n"
            ),
        },
    ]

    assert run_local_pipeline_impl.python_leaf_interface_violations(
        files,
        source_paths={"backend/reporting.py"},
    ) == [
        "backend/reporting.py calls property ArtifactStore.base_dir "
        "from backend/artifact_store.py as a method"
    ]


def test_component_quality_rejects_undefined_pytest_fixture_after_merge() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="tests",
        files=[
            {
                "path": "tests/test_catalog.py",
                "content": (
                    "def test_catalog(tmp_path, artifact_store):\n"
                    "    assert artifact_store is not None\n"
                ),
            }
        ],
        prior_files=[
            {
                "path": "backend/artifact_store.py",
                "content": "class ArtifactStore:\n    pass\n",
            }
        ],
    )

    assert validation["status"] == "fail"
    assert any(
        "undefined pytest fixtures: artifact_store" in blocker
        for blocker in validation["blockers"]
    )


def test_component_quality_accepts_fixture_declared_in_conftest() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="tests",
        files=[
            {
                "path": "tests/conftest.py",
                "content": (
                    "import pytest\n"
                    "@pytest.fixture\n"
                    "def artifact_store():\n"
                    "    return object()\n"
                ),
            },
            {
                "path": "tests/test_catalog.py",
                "content": (
                    "def test_catalog(tmp_path, artifact_store):\n"
                    "    assert artifact_store is not None\n"
                ),
            },
        ],
    )

    assert validation["status"] == "pass"


def test_component_quality_rejects_test_assertion_that_contradicts_return_annotation() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="tests",
        files=[
            {
                "path": "tests/test_geometry.py",
                "content": (
                    "from backend.geometry import compute_features\n"
                    "def test_shape():\n"
                    "    result = compute_features([])\n"
                    "    assert isinstance(result, list)\n"
                ),
            }
        ],
        prior_files=[
            {
                "path": "backend/geometry.py",
                "content": (
                    "from typing import Any, Dict\n"
                    "def compute_features(rows: list) -> Dict[str, Any]:\n"
                    "    return {}\n"
                ),
            }
        ],
    )

    assert validation["status"] == "fail"
    assert any(
        "asserts result is list but its published return contract is dict" in blocker
        for blocker in validation["blockers"]
    )


def test_component_quality_rejects_test_assertion_that_contradicts_model_field() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="tests",
        files=[
            {
                "path": "tests/test_parser.py",
                "content": (
                    "from typing import Any\n"
                    "from backend.parser import Evidence\n"
                    "def assert_shape(value: Any):\n"
                    "    assert isinstance(value, Evidence)\n"
                    "    assert isinstance(value.ticks_present, bool)\n"
                ),
            }
        ],
        prior_files=[
            {
                "path": "backend/parser.py",
                "content": (
                    "from dataclasses import dataclass\n"
                    "from typing import List\n"
                    "@dataclass\n"
                    "class Evidence:\n"
                    "    ticks_present: List[int]\n"
                ),
            }
        ],
    )

    assert validation["status"] == "fail"
    assert any(
        "asserts Evidence.ticks_present is bool but its published field contract is list"
        in blocker
        for blocker in validation["blockers"]
    )


def test_component_quality_rejects_executable_split_test_anchor() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="tests",
        files=[
            {
                "path": "tests/test_suite.py",
                "content": (
                    "import importlib\n"
                    "SUITE_PARTS = ('tests/test_suite_part_01.py',)\n"
                    "def test_parts_importable():\n"
                    "    importlib.import_module('tests.test_suite_part_01')\n"
                ),
            },
            {
                "path": "tests/test_suite_part_01.py",
                "content": "def test_behavior():\n    assert True\n",
            },
        ],
        manifest_entries=[
            {
                "path": "tests/test_suite.py",
                "generation_role": "test_suite_anchor",
                "facade_children": ["tests/test_suite_part_01.py"],
                "expected_symbols": ["SUITE_PARTS"],
            },
            {
                "path": "tests/test_suite_part_01.py",
                "generation_role": "bounded_test_module",
            },
        ],
    )

    assert validation["status"] == "fail"
    assert any(
        "test suite anchor must not define executable tests or dynamically import child suites"
        in blocker
        for blocker in validation["blockers"]
    )


def test_component_quality_accepts_declarative_split_test_anchor() -> None:
    validation = run_local_pipeline_impl.validate_generated_component_quality(
        component_id="tests",
        files=[
            {
                "path": "tests/test_suite.py",
                "content": "SUITE_PARTS = ('tests/test_suite_part_01.py',)\n",
            },
            {
                "path": "tests/test_suite_part_01.py",
                "content": "def test_behavior():\n    assert True\n",
            },
        ],
        manifest_entries=[
            {
                "path": "tests/test_suite.py",
                "generation_role": "test_suite_anchor",
                "facade_children": ["tests/test_suite_part_01.py"],
                "expected_symbols": ["SUITE_PARTS"],
            },
            {
                "path": "tests/test_suite_part_01.py",
                "generation_role": "bounded_test_module",
            },
        ],
    )

    assert validation["status"] == "pass"


def test_python_leaf_interface_validation_rejects_misnamed_instance_receiver() -> None:
    files = [
        {
            "path": "backend/service.py",
            "content": (
                "class InventoryService:\n"
                "    def filter_items(filtering_indent_anchor, *, name=None):\n"
                "        return self._repository.filter(name=name)\n"
            ),
        }
    ]

    violations = run_local_pipeline_impl.python_leaf_interface_violations(files)

    assert violations == [
        "python leaf interface contract mismatch: backend/service.py "
        "InventoryService.filter_items uses self but declares first parameter filtering_indent_anchor"
    ]


def test_python_leaf_interface_validation_keeps_local_names_function_scoped() -> None:
    violations = run_local_pipeline_impl.python_leaf_interface_violations(
        [
            {
                "path": "core/model.py",
                "content": "class Job:\n    def run(self):\n        return True\n",
            },
            {
                "path": "core/service.py",
                "content": (
                    "from .model import Job\n"
                    "def execute():\n"
                    "    runner = Job()\n"
                    "    runner.run()\n"
                    "def unrelated():\n"
                    "    runner = object()\n"
                    "    return runner.missing_dynamic_method()\n"
                ),
            },
        ],
        source_paths={"core/service.py"},
    )

    assert violations == []


def test_complexity_contract_enriches_canonical_component_manifests() -> None:
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(GOAL, video_plan())
    components = {row["id"]: row for row in pipeline["components"]}

    assert pipeline["complexity_contract_enforced"] is True
    assert "backend/orchestrator.py" in components["backend"]["required_paths"]
    assert "backend/stages.py" in components["backend"]["required_paths"]
    assert "backend/cli.py" in components["backend"]["required_paths"]
    assert "backend/gui.py" in components["backend"]["required_paths"]
    assert "backend/job_manager.py" in components["backend"]["required_paths"]
    assert "demo/run_fixture.py" in components["media"]["required_paths"]
    assert "tests/test_pipeline_unit.py" in components["tests"]["required_paths"]
    assert "docs/technical_plan.md" in components["docs"]["required_paths"]
    assert components["tests"]["contract_slice"]["minimum_tests"] == 50
    assert components["backend"]["contract_slice"]["required_pipeline_stages"] == [
        "ingest_video",
        "extract_audio",
        "build_audio_chunk_manifest",
        "transcribe_chunks",
        "merge_transcript",
        "optional_analysis",
        "select_segments",
        "build_clip_manifest",
        "render_clips_batch",
        "export_results",
    ]
    assert {"cli", "gui"}.issubset(components["backend"]["contract_slice"]["required_interfaces"])


def test_deterministic_complexity_gate_overrides_small_skeleton() -> None:
    plan = video_plan()
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(GOAL, plan)
    files = [
        {"path": "main.py", "content": "print('small demo')"},
        {"path": "tests/test_app.py", "content": "def test_one():\n    assert True\n"},
    ]

    blockers = run_local_pipeline_impl.deterministic_complexity_blockers(
        goal=GOAL,
        plan_doc=plan,
        component_pipeline=pipeline,
        files=files,
    )
    kinds = {blocker["kind"] for blocker in blockers}

    assert "required_files_missing" in kinds
    assert "pipeline_stage_coverage_missing" in kinds
    assert "minimum_test_count_not_met" in kinds
    assert any("PipelineRunner" in blocker["message"] for blocker in blockers)
    assert any("JobManager" in blocker["message"] for blocker in blockers)


def test_raw_browser_frontend_rejects_missing_modules_and_jsx() -> None:
    error = run_local_pipeline_impl.validate_frontend_dom_contract(
        [
            {
                "path": "index.html",
                "content": '<body><div id="app"></div><script type="module" src="src/app.js"></script></body>',
            },
            {
                "path": "src/app.js",
                "content": "import React from 'react'; import reducer from './reducer'; "
                "function App(){ return (<main>Broken</main>); }",
            },
        ]
    )

    assert "frontend module contract mismatch" in error


def test_raw_browser_frontend_does_not_treat_import_prefixed_identifiers_as_modules() -> None:
    error = run_local_pipeline_impl.validate_frontend_dom_contract(
        [
            {
                "path": "index.html",
                "content": (
                    '<body><button id="import-button">Import</button>'
                    '<p id="status"></p><script type="module" src="src/app.js"></script></body>'
                ),
            },
            {
                "path": "src/app.js",
                "content": (
                    "function importVideo() {\n"
                    "  document.getElementById('status').textContent = 'Ready';\n"
                    "}\n"
                    "document.getElementById('import-button').addEventListener('click', importVideo);\n"
                ),
            },
        ]
    )

    assert error == ""


def test_post_build_complexity_gate_updates_delivery_manifest(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    discovery_selection_lane.run_discovery_selection(GOAL, run_dir / "discovery")
    manifest_path = project_dir / "delivery_manifest.json"
    manifest_path.write_text(
        json.dumps({"status": "PASS", "failures": [], "known_limits": []}),
        encoding="utf-8",
    )
    result = {"status": "pass", "known_limits": []}

    post_build_finalize.apply_complexity_contract_gate(project_dir, run_dir, result)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["status"] == "needs_rework"
    assert result["complexity_contract_blockers"]
    assert manifest["status"] == "NEEDS_REWORK"
    assert "complexity_project_contract_not_passed" in manifest["failures"]


def test_integration_feedforward_carries_real_upstream_interfaces() -> None:
    plan = video_plan()
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(GOAL, plan)
    components = {row["id"]: row for row in pipeline["components"]}
    prior_results = [
        {
            "component_id": "foundation",
            "summary": "Package foundation",
            "public_contract": {"exports": ["video_workbench package"]},
        },
        {
            "component_id": "backend",
            "summary": "Shared pipeline core",
            "public_contract": {"exports": ["PipelineRunner", "JobManager"]},
        },
    ]
    prior_files = [
        {
            "path": "backend/orchestrator.py",
            "content": (
                "class PipelineRunner:\n"
                "    def run(self, run_id):\n"
                "        return run_id\n"
                "    def resume(self, run_id):\n"
                "        return run_id\n"
            ),
        },
        {
            "path": "backend/job_manager.py",
            "content": "class JobManager:\n    def cancel(self, run_id):\n        return run_id\n",
        },
        {
            "path": "demo/fixture_manifest.json",
            "content": '{"schema_version": 1, "run_id": "fixture"}',
        },
    ]

    snapshot = run_local_pipeline_impl.build_integration_feedforward_snapshot(
        goal=GOAL,
        component=components["frontend"],
        component_pipeline=pipeline,
        plan_doc=plan,
        prior_component_results=prior_results,
        prior_files=prior_files,
        repair_errors=[],
    )

    assert snapshot["kind"] == "CGKNIntegrationFeedforwardSnapshot"
    assert snapshot["current_component"] == "frontend"
    assert snapshot["current_contract"]["missing_upstream_components"] == []
    assert snapshot["global_contract"]["minimum_tests"] == 50
    catalog = {item["path"]: item for item in snapshot["upstream_state"]["interface_catalog"]}
    runner = catalog["backend/orchestrator.py"]["python"]["classes"][0]
    assert runner["name"] == "PipelineRunner"
    assert "run(self, run_id)" in runner["methods"]
    assert "resume(self, run_id)" in runner["methods"]
    assert catalog["demo/fixture_manifest.json"]["json"]["top_level_keys"] == ["run_id", "schema_version"]
    assert snapshot["snapshot_sha256"]


def test_integration_feedforward_invalidates_stale_downstream_checkpoint() -> None:
    plan = video_plan()
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(GOAL, plan)
    component = next(row for row in pipeline["components"] if row["id"] == "tests")
    common = {
        "goal": GOAL,
        "component": component,
        "component_pipeline": pipeline,
        "plan_doc": plan,
        "prior_component_results": [{"component_id": "backend", "public_contract": {"exports": ["PipelineRunner"]}}],
        "repair_errors": [],
    }
    first = run_local_pipeline_impl.build_integration_feedforward_snapshot(
        **common,
        prior_files=[{"path": "backend/orchestrator.py", "content": "class PipelineRunner:\n    pass\n"}],
    )
    second = run_local_pipeline_impl.build_integration_feedforward_snapshot(
        **common,
        prior_files=[{"path": "backend/orchestrator.py", "content": "class PipelineRunner:\n    def run(self):\n        pass\n"}],
    )

    assert first["snapshot_sha256"] != second["snapshot_sha256"]
    first_spec = run_local_pipeline_impl.provider_component_spec_hash(
        GOAL,
        pipeline,
        component,
        run_local_pipeline_impl.integration_feedforward_checkpoint_hash(first),
    )
    second_spec = run_local_pipeline_impl.provider_component_spec_hash(
        GOAL,
        pipeline,
        component,
        run_local_pipeline_impl.integration_feedforward_checkpoint_hash(second),
    )
    assert first_spec != second_spec


def test_checkpoint_hash_ignores_transient_repair_text_but_keeps_interface_changes() -> None:
    component = {"id": "backend"}
    pipeline = {"components": [component]}
    common = {
        "goal": "build a project",
        "component": component,
        "component_pipeline": pipeline,
        "plan_doc": {},
        "prior_component_results": [],
    }
    baseline = run_local_pipeline_impl.build_integration_feedforward_snapshot(
        **common,
        prior_files=[{"path": "main.py", "content": "def run():\n    return 1\n"}],
        repair_errors=[],
    )
    narrated = run_local_pipeline_impl.build_integration_feedforward_snapshot(
        **common,
        prior_files=[{"path": "main.py", "content": "def run():\n    return 1\n"}],
        repair_errors=["temporary provider wording changed"],
    )
    changed_interface = run_local_pipeline_impl.build_integration_feedforward_snapshot(
        **common,
        prior_files=[{"path": "main.py", "content": "def run(value):\n    return value\n"}],
        repair_errors=[],
    )

    assert baseline["snapshot_sha256"] != narrated["snapshot_sha256"]
    assert (
        run_local_pipeline_impl.integration_feedforward_checkpoint_hash(baseline)
        == run_local_pipeline_impl.integration_feedforward_checkpoint_hash(narrated)
    )
    assert (
        run_local_pipeline_impl.integration_feedforward_checkpoint_hash(baseline)
        != run_local_pipeline_impl.integration_feedforward_checkpoint_hash(changed_interface)
    )


def test_component_payload_includes_integration_feedforward() -> None:
    plan = video_plan()
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(GOAL, plan)
    component = next(row for row in pipeline["components"] if row["id"] == "frontend")
    snapshot = {"kind": "CGKNIntegrationFeedforwardSnapshot", "snapshot_sha256": "abc123"}

    payload = run_local_pipeline_impl.provider_component_payload(
        goal=GOAL,
        component=component,
        component_pipeline=pipeline,
        plan_doc=plan,
        blueprint={},
        online_inputs={},
        market_research={},
        prior_manifest=["backend/orchestrator.py"],
        repair_errors=[],
        integration_feedforward=snapshot,
    )
    split_payload = run_local_pipeline_impl.summarize_component_context_for_split(
        goal=GOAL,
        component=component,
        component_pipeline=pipeline,
        prior_manifest=["backend/orchestrator.py"],
        repair_errors=[],
        integration_feedforward=snapshot,
    )

    assert payload["integration_feedforward"] == snapshot
    assert split_payload["integration_feedforward"] == snapshot
