from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import product_acceptance


def test_internal_readiness_terms_do_not_become_missing_core_features(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "task_board"
    project.mkdir()
    (project / "README.md").write_text(
        "# Task Board\n\nAdd, edit, delete, and move tasks across Todo, Doing, and Done.\n",
        encoding="utf-8",
    )
    (project / "index.html").write_text(
        "<header><form><select><option>Todo</option><option>Doing</option><option>Done</option></select><button>Add</button></form></header>",
        encoding="utf-8",
    )
    (project / "app-core.js").write_text(
        "const seedTasks=[]; localStorage.setItem('tasks','[]'); function add(){} function edit(){} function deleteTask(){} function move(){} function save(){}",
        encoding="utf-8",
    )
    (project / "TEST_REPORT.md").write_text("commands_run:\n- npm test\n", encoding="utf-8")
    (project / "package.json").write_text('{"scripts":{"test":"node tests/task-board.test.js"}}', encoding="utf-8")
    (project / "project_spec.json").write_text('{"core_features":["task board","add task","edit task","delete task"]}\n', encoding="utf-8")
    (project / "acceptance_matrix.json").write_text('{"expected_features":["move task","local persistence"]}\n', encoding="utf-8")
    (project / "page_map.json").write_text('{"pages":[{"name":"Task Board","features":["todo","doing","done"]}]}\n', encoding="utf-8")

    report = product_acceptance.evaluate_product_acceptance(
        project,
        goal="commercial_status commercial_readiness gate reason beta delivery readiness",
        screenshot_metadata={"valid": True, "path": str(project / "artifacts" / "screenshots" / "screen.png")},
        ui_smoke_result={"status": "pass"},
        known_limits=["commercial_status: COMMERCIAL_BETA", "gate reason: final bundle missing"],
    )

    polluted = {"commercial", "readiness", "commercial_ready", "commercial_readiness", "beta", "delivery", "gate"}
    assert polluted.isdisjoint(set(report["missing_core_features"]))
    assert polluted.isdisjoint(set(report["metadata"]["expected_feature_sources"]["features"]))
    assert "project_spec.json" in report["metadata"]["expected_feature_sources"]["allowed_source_files"]
    assert "acceptance_matrix.json" in report["metadata"]["expected_feature_sources"]["allowed_source_files"]
    assert isinstance(report["metadata"]["ux_score_inputs"], dict)
    assert "low_ux_score" not in report["weak_features"]
