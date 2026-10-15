from __future__ import annotations

import json
import pathlib
import sys
import zipfile

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.benchmark]

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import generalization_benchmark_audit


def make_case(root: pathlib.Path, case_id: str, modules: list[str], *, same_content: bool = False, omit_bundle: bool = False) -> dict:
    project = root / case_id / "final_project"
    project.mkdir(parents=True)
    content_name = "Same Template" if same_content else case_id
    (project / "README.md").write_text(f"# {content_name}\n" + " ".join(modules), encoding="utf-8")
    (project / "index.html").write_text(f"<h1>{content_name}</h1>" + " ".join(modules), encoding="utf-8")
    (project / "app.js").write_text(" ".join(modules), encoding="utf-8")
    (project / "page_map.json").write_text(json.dumps({"pages": [{"id": item, "name": item} for item in modules]}), encoding="utf-8")
    (project / "feature_matrix.json").write_text(json.dumps({"modules": [{"id": item, "name": item} for item in modules]}), encoding="utf-8")
    (project / "acceptance_matrix.json").write_text(json.dumps({"expected_features": modules}), encoding="utf-8")
    demo = project / "demo_data" / "demo.json"
    demo.parent.mkdir()
    demo.write_text('{"privacy_notice":"synthetic demo data only","records":[{"id":"PX-1","display":"Demo Patient A"}]}', encoding="utf-8")
    shot = project / "artifacts" / "screenshots" / "overview.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"png")
    bundle = project / "final_project_bundle.zip"
    if not omit_bundle:
        with zipfile.ZipFile(bundle, "w") as zf:
            zf.writestr("README.md", "ok")
    (project / "delivery_manifest.json").write_text(json.dumps({"screenshot_path": str(shot), "public_final_gate": {"status": "READY"}}), encoding="utf-8")
    ledger = root / case_id / "run" / "artifacts" / "agent_decision_ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{}\n", encoding="utf-8")
    return {
        "case_id": case_id,
        "status": "pass",
        "run_dir": str(root / case_id / "run"),
        "final_project": str(project),
        "delivery_manifest": str(project / "delivery_manifest.json"),
        "final_bundle": str(bundle),
        "screenshot_evidence": str(shot),
        "agent_decision_ledger": str(ledger),
        "required_modules": modules,
        "complexity_status": "pass",
        "page_count": len(modules),
        "module_count": len(modules),
        "product_acceptance": "pass",
        "commercial_status": "COMMERCIAL_READY",
        "public_delivery_gate": "READY",
        "remaining_blockers": [],
    }


def test_less_than_three_cases_fails(tmp_path: pathlib.Path) -> None:
    case = make_case(tmp_path, "one", [f"module_{i}" for i in range(8)])

    audit = generalization_benchmark_audit.audit_report({"cases": [case]})

    assert audit["status"] != "pass"
    assert "insufficient_case_count" in audit["shared_failures"]


def test_missing_final_bundle_fails_case_and_global(tmp_path: pathlib.Path) -> None:
    modules = [f"module_{i}" for i in range(8)]
    cases = [
        make_case(tmp_path, "a", modules, omit_bundle=True),
        make_case(tmp_path, "b", [f"b_{i}" for i in range(8)]),
        make_case(tmp_path, "c", [f"c_{i}" for i in range(8)]),
    ]

    audit = generalization_benchmark_audit.audit_report({"cases": cases})

    assert audit["status"] != "pass"
    assert audit["case_results"][0]["status"] != "pass"
    assert "final_bundle_exists" in audit["case_results"][0]["failures"]


def test_required_module_missing_is_reported(tmp_path: pathlib.Path) -> None:
    modules = ["dashboard", "appointments", "visit_records", "prescriptions", "lab_orders", "billing_overview", "inventory", "staff_schedule"]
    case = make_case(tmp_path, "clinic_workflow_studio", modules)
    case["required_modules"] = ["dashboard", "patient_queue", *modules[1:]]

    audit = generalization_benchmark_audit.audit_report({"cases": [case, make_case(tmp_path, "b", [f"b_{i}" for i in range(8)]), make_case(tmp_path, "c", [f"c_{i}" for i in range(8)])]})

    assert "patient_queue" in audit["case_results"][0]["missing_modules"]


def test_domain_diversity_fails_for_identical_content(tmp_path: pathlib.Path) -> None:
    modules = [f"module_{i}" for i in range(8)]
    cases = [
        make_case(tmp_path, "a", modules, same_content=True),
        make_case(tmp_path, "b", modules, same_content=True),
        make_case(tmp_path, "c", modules, same_content=True),
    ]

    audit = generalization_benchmark_audit.audit_report({"cases": cases})

    assert audit["domain_diversity"] == "fail"
    assert "insufficient_domain_diversity" in audit["shared_failures"]


def test_clinic_demo_data_privacy_safety_passes_for_fake_data(tmp_path: pathlib.Path) -> None:
    modules = [f"module_{i}" for i in range(8)]
    case = make_case(tmp_path, "clinic_workflow_studio", modules)

    audit = generalization_benchmark_audit.audit_report({"cases": [case, make_case(tmp_path, "b", [f"b_{i}" for i in range(8)]), make_case(tmp_path, "c", [f"c_{i}" for i in range(8)])]})

    assert audit["case_results"][0]["privacy_safety"]["status"] == "pass"
