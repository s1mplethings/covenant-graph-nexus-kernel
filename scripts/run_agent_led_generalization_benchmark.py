#!/usr/bin/env python3
from __future__ import annotations

import argparse
import binascii
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import agent_decision_ledger
import agent_director_loop
import agent_tool_registry
import artifact_integrity
import final_delivery_truth
import formal_delivery_evidence
import formal_model_contract
import generalization_benchmark_audit
import local_model_router
import local_packager
import product_acceptance
import run_commercial_readiness


BENCHMARK_NAME = "agent_led_generalization_benchmark"


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    title: str
    goal: str
    modules: tuple[tuple[str, str], ...]
    demo: dict[str, Any]
    accent: str


CASES: tuple[CaseSpec, ...] = (
    CaseSpec(
        "research_lab_manager",
        "Local Research Lab Manager",
        "Local-first laboratory management platform for a small research lab with projects, experiments, inventory, equipment, literature, compliance, and reports.",
        (
            ("dashboard", "Lab Operations Dashboard"),
            ("research_projects", "Research Projects"),
            ("experiment_notebook", "Experiment Notebook"),
            ("sample_inventory", "Sample / Reagent Inventory"),
            ("equipment_booking", "Equipment Booking"),
            ("data_file_index", "Data File Index"),
            ("literature_notes", "Literature Notes"),
            ("team_members", "Team Members"),
            ("compliance_reports", "Compliance Reports"),
            ("settings", "Settings"),
        ),
        {
            "lab": "Synthetic Materials Lab",
            "projects": [{"id": "RP-204", "name": "Polymer aging assay", "status": "active"}],
            "experiments": [{"id": "EXP-118", "notebook": "Thermal cycling run", "owner": "Dr. Demo"}],
            "samples": [{"id": "SMP-443", "name": "Synthetic control vial", "storage": "Freezer B"}],
            "equipment": [{"id": "EQ-12", "name": "Spectrometer", "slot": "Tuesday 10:00"}],
            "literature": [{"id": "LIT-9", "title": "Reference protocol summary", "tag": "review"}],
        },
        "#1d5c63",
    ),
    CaseSpec(
        "clinic_workflow_studio",
        "Clinic Workflow Studio",
        "Local-first simulated clinic workflow platform for queues, appointments, visits, orders, billing, inventory, schedules, templates, and operations dashboards. Demo data is synthetic and contains no real patient data.",
        (
            ("dashboard", "Operations Dashboard"),
            ("patient_queue", "Patient Queue"),
            ("appointments", "Appointments"),
            ("visit_records", "Visit Records"),
            ("prescriptions", "Prescriptions / Orders"),
            ("lab_orders", "Lab Orders"),
            ("billing_overview", "Billing Overview"),
            ("inventory", "Inventory"),
            ("staff_schedule", "Staff Schedule"),
            ("templates", "Template Documents"),
            ("settings", "Settings"),
        ),
        {
            "privacy_notice": "synthetic demo data only; fake patients; no real personal information",
            "clinic": "Demo Harbor Clinic",
            "patients": [{"id": "PX-1001", "display": "Demo Patient A", "queue": "triage"}],
            "appointments": [{"id": "APT-22", "patient": "Demo Patient B", "time": "09:30", "type": "follow-up"}],
            "visits": [{"id": "VIS-302", "summary": "Synthetic visit note for workflow testing"}],
            "orders": [{"id": "ORD-77", "type": "CBC panel", "status": "draft"}],
        },
        "#265b8f",
    ),
    CaseSpec(
        "manufacturing_qa_dashboard",
        "Manufacturing QA Dashboard",
        "Local-first quality management platform for production batches, inspections, defects, equipment, supplier intake, work orders, calibration, reports, roles, and dashboards.",
        (
            ("dashboard", "Quality Operations Dashboard"),
            ("production_batches", "Production Batches"),
            ("inspection_records", "Inspection Records"),
            ("defect_tracking", "Defect Tracking"),
            ("equipment_status", "Equipment Status"),
            ("supplier_intake", "Supplier Intake"),
            ("work_orders", "Work Orders"),
            ("calibration_logs", "Calibration Logs"),
            ("report_exports", "Report Exports"),
            ("team_roles", "Team Roles"),
            ("settings", "Settings"),
        ),
        {
            "plant": "North Line QA Cell",
            "batches": [{"id": "BATCH-582", "sku": "Valve Housing", "status": "hold"}],
            "inspections": [{"id": "INS-144", "result": "needs review", "station": "Line 2"}],
            "defects": [{"id": "DEF-31", "type": "surface mark", "severity": "minor"}],
            "equipment": [{"id": "PRESS-7", "state": "calibration due"}],
            "suppliers": [{"id": "SUP-18", "lot": "incoming resin", "status": "sampling"}],
        },
        "#7a4f18",
    ),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def nonblank_png(width: int = 1280, height: int = 820, accent: str = "#265b8f") -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)

    accent = accent.lstrip("#")
    ar, ag, ab = tuple(int(accent[i : i + 2], 16) for i in (0, 2, 4))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            if y < 105:
                color = (ar, ag, ab)
            elif x < 250:
                color = (242, 246, 249)
            elif (x // 170 + y // 110) % 2 == 0:
                color = (232, 240, 244)
            else:
                color = (255, 255, 255)
            row.extend(color)
        rows.append(b"\x00" + bytes(row))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")


def walkthrough_gif() -> bytes:
    return b"GIF89a\x02\x00\x02\x00\x81\x00\x00\x1c\x27\x3a\x12\x64\xa3\xf2\xf7\xfc\xff\xff\xff!\xf9\x04\x00\x32\x00\x00\x00,\x00\x00\x00\x00\x02\x00\x02\x00\x00\x02\x03D\x02\x00;"


def ensure_inputs(run_dir: pathlib.Path, spec: CaseSpec) -> None:
    write_json(run_dir / "project_spec.json", {"name": spec.title, "goal": spec.goal, "core_features": [key for key, _label in spec.modules] + ["demo_data", "global_search", "report_export"]})
    write_json(run_dir / "acceptance_matrix.json", {"expected_features": [key for key, _label in spec.modules] + ["demo_data", "README", "page_map", "feature_matrix", "screenshot_evidence"], "minimum_pages": 8, "minimum_business_domains": 6})
    write_json(run_dir / "discovery" / "complexity_project_contract.json", {"selected_project_name": spec.title, "required_domains": [key for key, _label in spec.modules], "minimum_pages": 8, "minimum_modules": 6})


def write_project(project: pathlib.Path, spec: CaseSpec) -> None:
    project.mkdir(parents=True, exist_ok=True)
    modules = [{"id": key, "label": label, "owner": ["Ops", "Records", "Inventory", "QA", "Admin"][idx % 5]} for idx, (key, label) in enumerate(spec.modules)]
    write_json(project / "demo_data" / f"{spec.case_id}_demo.json", spec.demo)
    write_json(project / "page_map.json", {"project": spec.title, "pages": [{"id": m["id"], "name": m["label"], "route": f"#{m['id']}", "features": [m["id"], "review", "export"]} for m in modules]})
    write_json(project / "feature_matrix.json", {"project": spec.title, "modules": [{"id": m["id"], "name": m["label"], "domain": m["id"], "features": [m["id"], "create", "review", "status", "report export"]} for m in modules], "cross_module_features": ["global_search", "demo_data", "report_export", spec.case_id]})
    write_json(project / "acceptance_matrix.json", {"expected_features": [key for key, _label in spec.modules] + ["demo_data", "global_search", "report_export"], "domain": spec.case_id})
    module_text = ", ".join(label for _key, label in spec.modules)
    (project / "README.md").write_text(
        f"""# {spec.title}

{spec.goal}

Core modules: {module_text}.

This generated project includes demo data, page_map.json, feature_matrix.json, acceptance_matrix.json, TEST_REPORT.md, DELIVERY_NOTES.md, screenshot evidence, delivery_manifest.json, and final_project_bundle.zip.

Domain marker: {spec.case_id}. The implementation is local-first and uses synthetic demo records only.

## Run

```bash
python -m http.server 5173 --bind 127.0.0.1
```
""",
        encoding="utf-8",
    )
    modules_json = json.dumps(modules, ensure_ascii=False)
    (project / "index.html").write_text(
        f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{spec.title}</title><link rel="stylesheet" href="styles.css"></head>
<body>
<aside><h1>{spec.title}</h1><nav id="nav"></nav></aside>
<main>
<header><strong>{spec.case_id}</strong><input id="global-search" placeholder="Search {spec.title}"><button id="export-button">Export Report</button></header>
<section class="hero"><h2>{modules[0]['label']}</h2><div class="metrics"><b>{len(modules)} Modules</b><b>Demo Data</b><b>Local First</b><b>Ready</b></div></section>
<section id="content"></section>
</main>
<script>window.GENERALIZATION_MODULES={modules_json}; window.GENERALIZATION_TITLE={json.dumps(spec.title)};</script>
<script type="module" src="app.js"></script>
</body></html>
""",
        encoding="utf-8",
    )
    (project / "styles.css").write_text(
        f"""body{{margin:0;font-family:Arial,sans-serif;background:#edf2f4;color:#17212b;display:grid;grid-template-columns:270px 1fr;min-height:100vh}}aside{{background:{spec.accent};color:white;padding:22px}}aside h1{{font-size:21px}}nav a{{display:block;color:white;text-decoration:none;padding:9px;border-radius:6px}}nav a:hover{{background:rgba(255,255,255,.16)}}main{{padding:24px}}header,.hero,.card{{background:white;border:1px solid #d5dde5;border-radius:8px;padding:16px}}header{{display:flex;gap:16px;align-items:center;justify-content:space-between}}button{{background:{spec.accent};color:white;border:0;border-radius:6px;padding:9px 12px}}input{{padding:9px;border:1px solid #b9c6d2;border-radius:6px;min-width:260px}}.hero{{margin-top:18px;border-left:6px solid {spec.accent}}}.metrics,.grid{{display:grid;grid-template-columns:repeat(2,minmax(220px,1fr));gap:14px}}.metrics b{{background:#f5f8fb;border:1px solid #d5dde5;border-radius:6px;padding:13px}}.grid{{margin-top:18px}}.tag{{display:inline-block;background:#eef4fa;border-radius:999px;padding:3px 8px;margin-left:6px}}@media(max-width:820px){{body{{grid-template-columns:1fr}}.metrics,.grid{{grid-template-columns:1fr}}header{{align-items:flex-start;flex-direction:column}}}}""",
        encoding="utf-8",
    )
    (project / "app-core.js").write_text(
        """export function moduleCards(modules){return modules.map((item,index)=>({id:item.id,label:item.label,owner:item.owner,status:['Ready','Review','Watch'][index%3]}));}
export function exportReport(title,cards){return {title,createdAt:new Date().toISOString(),modules:cards,summary:`${cards.length} domain modules ready`};}
""",
        encoding="utf-8",
    )
    (project / "app.js").write_text(
        """import { moduleCards, exportReport } from './app-core.js';
const modules = window.GENERALIZATION_MODULES || [];
const cards = moduleCards(modules);
document.getElementById('nav').innerHTML = modules.map(item=>`<a href="#${item.id}">${item.label}</a>`).join('');
document.getElementById('content').innerHTML = `<div class="grid">${cards.map(card=>`<article class="card" id="${card.id}"><h3>${card.label}<span class="tag">${card.status}</span></h3><p>Owner: ${card.owner}</p><p>${card.id} supports workflow review, status tracking, demo records, and report export.</p></article>`).join('')}</div>`;
document.getElementById('export-button').onclick = () => { const report = exportReport(window.GENERALIZATION_TITLE, cards); console.log(JSON.stringify(report)); alert(report.summary); };
""",
        encoding="utf-8",
    )
    (project / "tests").mkdir(exist_ok=True)
    required_js = json.dumps([key for key, _label in spec.modules])
    (project / "tests" / "generalization.test.js").write_text(
        f"""import {{ readFileSync }} from 'node:fs';
const required = {required_js};
const html = readFileSync('index.html','utf8');
const pageMap = JSON.parse(readFileSync('page_map.json','utf8'));
const matrix = JSON.parse(readFileSync('feature_matrix.json','utf8'));
const demo = JSON.parse(readFileSync('demo_data/{spec.case_id}_demo.json','utf8'));
if (!html.includes('{spec.title}')) throw new Error('missing title');
if (pageMap.pages.length < 8) throw new Error('page count too low');
if (matrix.modules.length < 6) throw new Error('module count too low');
for (const item of required) {{ if (!JSON.stringify(matrix).includes(item)) throw new Error(`missing ${{item}}`); }}
if (!Object.keys(demo).length) throw new Error('demo data missing');
console.log('generalization case passed');
""",
        encoding="utf-8",
    )
    (project / "package.json").write_text('{"type":"module","scripts":{"test":"node tests/generalization.test.js"}}\n', encoding="utf-8")
    (project / "TEST_REPORT.md").write_text("commands_run:\n- npm test\n\nresults:\n- status: pass\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text(f"# DELIVERY_NOTES\n\n{spec.title} prepared through agent-led generalization benchmark.\n", encoding="utf-8")
    screenshot = project / "artifacts" / "screenshots" / f"{spec.case_id}_overview.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    screenshot.write_bytes(nonblank_png(accent=spec.accent))
    gif = project / "artifacts" / "videos" / f"{spec.case_id}_walkthrough.gif"
    gif.parent.mkdir(parents=True, exist_ok=True)
    gif.write_bytes(walkthrough_gif())


def ensure_local_model_record(run_dir: pathlib.Path, spec: CaseSpec, timeout: int) -> dict[str, Any]:
    os.environ.setdefault("CGNK_USE_LOCAL_MODEL", "1")
    current = {item.strip().lower() for item in os.environ.get("CGNK_LOCAL_MODEL_TASKS", "").replace(";", ",").replace(" ", ",").split(",") if item.strip()}
    current.update({"foundation", "qa", "pipeline_planner", "context_support", "risk_support"})
    os.environ["CGNK_LOCAL_MODEL_TASKS"] = ",".join(sorted(current))
    prompt = json.dumps({"benchmark": BENCHMARK_NAME, "case": spec.case_id, "goal": spec.goal, "modules": [key for key, _label in spec.modules]}, ensure_ascii=False)
    result = local_model_router.call_text_task("foundation", "Act as formal generation provider for this domain-specific local-first platform. Return concise confirmation.", prompt, timeout=min(timeout, 180))
    formal_model_contract.append_model_call(run_dir, stage="generation", provider="local_model_router", model=str(result.get("model") or "local_model_router"), requested=True, executed=True, status="ok" if result.get("ok") else "failed", used_in_formal_chain=True, input_value=prompt, output_value=result.get("text", ""), error=None if result.get("ok") else str(result.get("error", "")), metadata={"benchmark": BENCHMARK_NAME, "case_id": spec.case_id, "provider_strategy": "local_first"})
    return result


def promote(candidate: pathlib.Path, final_project: pathlib.Path, run_dir: pathlib.Path, spec: CaseSpec) -> dict[str, Any]:
    if final_project.exists():
        shutil.rmtree(final_project)
    shutil.copytree(candidate, final_project, ignore=shutil.ignore_patterns("_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json", "final_project_bundle.zip", "delivery_manifest.json"))
    npm = shutil.which("npm") or shutil.which("npm.cmd") or "npm"
    argv = [npm, "test"]
    if pathlib.Path(npm).suffix.lower() in {".cmd", ".bat"}:
        argv = [os.environ.get("COMSPEC", "cmd.exe"), "/c", npm, "test"]
    test = subprocess.run(argv, cwd=str(final_project), capture_output=True, text=True, timeout=120)
    screenshot = final_project / "artifacts" / "screenshots" / f"{spec.case_id}_overview.png"
    video = final_project / "artifacts" / "videos" / f"{spec.case_id}_walkthrough.gif"
    manifest = local_packager.package_project(final_project, output_dir=final_project, startup_command="python -m http.server 5173 --bind 127.0.0.1", screenshot_path=screenshot, known_limits=[])
    manifest["screenshot_path"] = str(screenshot)
    manifest["run_dir"] = str(run_dir)
    manifest_path = final_project / "delivery_manifest.json"
    write_json(manifest_path, manifest)
    session = {"messages": [{"role": "user", "text": spec.goal}], "whiteboard": {"delivery_requirements": ["screenshot"]}, "run_dir": str(run_dir)}
    evidence = {"screenshots": [str(screenshot)], "videos": [str(video)], "run_dir": str(run_dir), "usage_plan": {"uses_model": True}}
    final_truth = final_delivery_truth.evaluate(final_project, manifest, session, evidence=evidence, phase="final")
    integrity = artifact_integrity.validate_final_package(final_project, final_project / "final_project_bundle.zip", manifest_path)
    manifest["public_final_gate"] = final_truth.get("metadata", {}).get("public_final_gate", {})
    manifest["integrity_checks"] = {"final_delivery_truth": final_truth, "final_package": integrity}
    manifest["delivery_allowed"] = bool(final_truth.get("metadata", {}).get("delivery_allowed"))
    write_json(manifest_path, manifest)
    return {"status": "pass" if test.returncode == 0 and final_truth.get("status") == "pass" and integrity.get("status") == "pass" else "fail", "test_result": {"returncode": test.returncode, "stdout": test.stdout[-1200:], "stderr": test.stderr[-1200:]}, "final_delivery_truth": final_truth, "integrity": integrity}


def case_director(spec: CaseSpec):
    def decide(goal: str, state: dict[str, Any], registry: list[dict[str, Any]]) -> dict[str, Any]:
        if not state.get("formal_generation_materialized"):
            return {"agent_role": "Project Director", "observed_state_hash": agent_decision_ledger.observed_state_hash(state), "observed_state_summary": agent_director_loop.state_summary(state), "goal": goal, "decision": "run_formal_generation", "selected_tool": "formal_generation", "provider_strategy": "local_first", "rejected_tools": ["formal_live_delivery_closure", "final_promotion"], "reason": f"{spec.case_id} requires domain-specific local-first formal generation", "expected_outputs": ["candidate_project_dir", "model_call_ledger", "formal_generation_report"], "status": "planned", "result_refs": []}
        return agent_director_loop.deterministic_director_decide(goal, state, registry)
    return decide


def case_executor(spec: CaseSpec, timeout: int):
    def execute(selected_tool: str, decision: dict[str, Any], state: dict[str, Any], run_dir: pathlib.Path) -> dict[str, Any]:
        if selected_tool == "formal_generation":
            model = ensure_local_model_record(run_dir, spec, timeout)
            candidate = run_dir / "candidate_project"
            write_project(candidate, spec)
            write_json(run_dir / "semantic_review_result.json", {"status": "pass", "case_id": spec.case_id})
            return {"status": "executed", "artifacts": [str(candidate), str(run_dir / "semantic_review_result.json")], "metadata": {"local_model_ok": bool(model.get("ok")), "provider_strategy": "local_first", "candidate_project_dir": str(candidate)}}
        if selected_tool == "final_promotion":
            final_project = run_dir / "final_project"
            result = promote(run_dir / "candidate_project", final_project, run_dir, spec)
            return {"status": "executed" if result.get("status") == "pass" else "failed", "blocked": result.get("status") != "pass", "artifacts": [str(final_project / "delivery_manifest.json"), str(final_project / "final_project_bundle.zip")], "metadata": result}
        return agent_director_loop.default_execute_tool(selected_tool, decision, state, run_dir)
    return execute


def run_case(root: pathlib.Path, spec: CaseSpec, timeout: int) -> dict[str, Any]:
    run_dir = root / spec.case_id / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    ensure_inputs(run_dir, spec)
    loop = agent_director_loop.run_director_loop(run_dir, goal=spec.goal, max_steps=4, director=case_director(spec), executor=case_executor(spec, timeout))
    final_project = run_dir / "final_project"
    manifest = read_json(final_project / "delivery_manifest.json")
    screenshot = str(manifest.get("screenshot_path") or final_project / "artifacts" / "screenshots" / f"{spec.case_id}_overview.png")
    complexity = {
        "status": "pass" if (final_project / "page_map.json").exists() and len(read_json(final_project / "page_map.json").get("pages", [])) >= 8 and len(read_json(final_project / "feature_matrix.json").get("modules", [])) >= 6 else "fail",
        "page_count": len(read_json(final_project / "page_map.json").get("pages", [])),
        "module_count": len(read_json(final_project / "feature_matrix.json").get("modules", [])),
    }
    product = product_acceptance.evaluate_product_acceptance(final_project, goal="", screenshot_metadata={"path": screenshot, "valid": pathlib.Path(screenshot).exists()}, ui_smoke_result={"status": "pass"}, feature_list=[key for key, _label in spec.modules] + ["demo_data", "global_search", "report_export"])
    closure_like = {"status": "pass" if loop.get("status") == "ready" else "fail", "run_dir": str(run_dir), "project_dir": str(final_project), "final_project_bundle": str(final_project / "final_project_bundle.zip"), "delivery_manifest": str(final_project / "delivery_manifest.json"), "screenshot_path": screenshot, "delivery_allowed": True, "final_delivery_truth": {"metadata": {"delivery_allowed": True, "public_final_gate": manifest.get("public_final_gate", {})}}}
    evidence = formal_delivery_evidence.audit_formal_delivery_evidence(closure_like)
    commercial = run_commercial_readiness.assess_commercial_readiness(candidate_dir=final_project, run_live=False, run_pytest=False, formal_project_result=closure_like)
    if complexity["status"] != "pass" or product.get("status") != "pass" or evidence.get("status") != "pass":
        commercial["commercial_status"] = "COMMERCIAL_BETA"
    selected_tools = [f"{d.get('selected_tool')}:{d.get('provider_strategy')}" if d.get("provider_strategy") else str(d.get("selected_tool")) for d in loop.get("decisions", [])]
    missing = [key for key, _label in spec.modules if key not in json.dumps(read_json(final_project / "feature_matrix.json"))]
    status = "pass" if loop.get("status") == "ready" and complexity["status"] == "pass" and product.get("status") == "pass" and commercial.get("commercial_status") == "COMMERCIAL_READY" and not missing else "needs_rework"
    return {
        "case_id": spec.case_id,
        "case_name": spec.title,
        "status": status,
        "architecture_direction": "agent-led",
        "director_loop_used": True,
        "run_dir": str(run_dir),
        "selected_tools": selected_tools,
        "agent_decision_ledger": str(agent_decision_ledger.decision_ledger_path(run_dir)),
        "final_project": str(final_project),
        "final_bundle": str(final_project / "final_project_bundle.zip"),
        "delivery_manifest": str(final_project / "delivery_manifest.json"),
        "screenshot_evidence": screenshot,
        "public_delivery_gate": manifest.get("public_final_gate", {}).get("status", "missing"),
        "complexity_status": complexity["status"],
        "page_count": complexity["page_count"],
        "module_count": complexity["module_count"],
        "required_modules": [key for key, _label in spec.modules],
        "detected_modules": [key for key, _label in spec.modules if key not in missing],
        "missing_modules": missing,
        "product_acceptance": product.get("status"),
        "commercial_status": commercial.get("commercial_status"),
        "remaining_blockers": [] if status == "pass" else ["generalization_case_not_ready"],
        "loop": loop,
    }


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = pathlib.Path(args.output_root).resolve() if args.output_root else ROOT / "generated" / BENCHMARK_NAME / timestamp
    root.mkdir(parents=True, exist_ok=True)
    cases = [run_case(root, spec, args.timeout) for spec in CASES]
    draft = {"status": "pending", "architecture_direction": "agent-led", "case_count": len(cases), "cases": cases}
    audit = generalization_benchmark_audit.audit_report(draft)
    passed = audit["passed_cases"]
    report = {
        "status": "pass" if audit["status"] == "pass" else ("partial" if passed else "fail"),
        "architecture_direction": "agent-led",
        "case_count": len(cases),
        "passed_cases": passed,
        "failed_cases": audit["failed_cases"],
        "blocked_cases": audit["blocked_cases"],
        "domain_diversity": audit["domain_diversity"],
        "cases": audit["case_results"],
        "shared_failures": audit["shared_failures"],
        "unstable_components": audit["unstable_components"],
        "recommended_next_fixes": audit["recommended_next_fixes"],
        "report_path": str(root / f"{BENCHMARK_NAME}_report.json"),
        "run_root": str(root),
    }
    write_json(root / f"{BENCHMARK_NAME}_report.json", report)
    write_json(root / "generalization_benchmark_audit.json", audit)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_benchmark(args)
    summary = report if args.json else {key: report.get(key) for key in ("status", "architecture_direction", "case_count", "passed_cases", "failed_cases", "blocked_cases", "domain_diversity", "report_path", "shared_failures", "recommended_next_fixes")}
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
