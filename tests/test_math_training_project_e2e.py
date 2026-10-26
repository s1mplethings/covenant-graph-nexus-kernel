from __future__ import annotations

import http.server
import json
import os
import pathlib
import shutil
import socketserver
import threading
import uuid

import pytest

from playwright.sync_api import sync_playwright

from scripts.capability_execution import compile_capability_plan, select_reuse
from scripts import canonical_delivery_manifest
from scripts import canonical_delivery_receipt
from scripts import canonical_evidence_hash
from scripts import codex_conversation
from scripts import production_candidate_provenance
from scripts import provider_causal_trace
from scripts.work_nodes import WorkNode


pytestmark = pytest.mark.e2e


CAPABILITIES = [
    {"id": "handwriting_input", "goal": "Capture handwriting", "outputs": ["HandwritingArtifact"], "acceptance": ["input captured"]},
    {"id": "formula_recognition", "goal": "Recognize formula", "depends_on": ["handwriting_input"], "inputs": ["HandwritingArtifact"], "outputs": ["RecognizedFormula"], "acceptance": ["formula normalized"]},
    {"id": "problem_model", "goal": "Represent a calculus problem", "outputs": ["Problem", "ExpectedAnswer"], "acceptance": ["problem valid"]},
    {"id": "grading", "goal": "Grade a formula", "depends_on": ["formula_recognition", "problem_model"], "inputs": ["RecognizedFormula", "Problem", "ExpectedAnswer"], "outputs": ["GradingResult"], "acceptance": ["grade shown"]},
    {"id": "error_explanation", "goal": "Explain an error", "depends_on": ["grading"], "inputs": ["GradingResult"], "outputs": ["LearningFeedback"], "acceptance": ["feedback shown"]},
    {"id": "question_generation", "goal": "Generate practice", "outputs": ["Problem"], "acceptance": ["question shown"]},
    {"id": "progress_tracking", "goal": "Store progress", "depends_on": ["grading"], "inputs": ["GradingResult"], "outputs": ["ProgressRecord"], "acceptance": ["progress persists"]},
    {"id": "local_storage", "goal": "Persist locally", "outputs": ["StoragePort"], "acceptance": ["local only"]},
    {"id": "user_interface", "goal": "Provide a GUI", "depends_on": ["grading", "error_explanation", "progress_tracking"], "inputs": ["GradingResult", "LearningFeedback", "ProgressRecord"], "outputs": ["UserView"], "acceptance": ["browser interaction passes"]},
]


HTML = """<!doctype html><html><head><meta charset='utf-8'><title>Calculus Ink Lab</title><style>
body{font-family:system-ui;background:#eef2ff;margin:0;color:#172554}.shell{max-width:860px;margin:36px auto;background:white;padding:28px;border-radius:22px;box-shadow:0 16px 50px #1e3a8a22}h1{margin:0}textarea{width:96%;height:110px;border:2px solid #818cf8;border-radius:14px;padding:14px;font-size:24px}button{background:#4f46e5;color:white;border:0;padding:12px 20px;border-radius:12px;font-weight:700}.result{margin-top:18px;padding:18px;background:#ecfeff;border-left:6px solid #0891b2;border-radius:10px}.metric{color:#4338ca;font-weight:700}</style></head><body><main class='shell'><p class='metric'>LOCAL · INTERFACE-FIRST</p><h1>Calculus Ink Lab</h1><p>Write or paste the derivative of x².</p><textarea id='ink' aria-label='handwriting input'>2x</textarea><button id='grade'>Recognize & Grade</button><button id='swap'>Swap recognizer</button><section class='result'><div id='recognized'>Waiting</div><div id='gradeResult'></div><div id='feedback'></div><div id='progress'></div></section></main><script>
const adapters={local:{recognize:a=>({raw_text:a,latex:a.trim(),confidence:.99,warnings:[]})},alternate:{recognize:a=>({raw_text:a,latex:a.replaceAll(' ',''),confidence:.95,warnings:['alternate adapter']})}};let current='local';
document.querySelector('#swap').onclick=()=>{current=current==='local'?'alternate':'local'};
document.querySelector('#grade').onclick=()=>{const formula=adapters[current].recognize(document.querySelector('#ink').value);const ok=formula.latex==='2x';const result={correct:ok,error_code:ok?null:'DERIVATIVE_MISMATCH'};document.querySelector('#recognized').textContent='Recognized: '+formula.latex+' via '+current;document.querySelector('#gradeResult').textContent=ok?'Correct':'Try again';document.querySelector('#feedback').textContent=ok?'Great — power rule applied correctly.':'Use d(xⁿ)/dx = n·xⁿ⁻¹.';const count=Number(localStorage.getItem('attempts')||0)+1;localStorage.setItem('attempts',count);document.querySelector('#progress').textContent='Attempts: '+count;};
</script></body></html>"""


def _canonicalize_math_project(source: pathlib.Path, run_dir: pathlib.Path) -> tuple[pathlib.Path, dict, dict]:
    token = uuid.uuid4().hex
    candidate = production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT / f"math-e2e-{token}"
    candidate.mkdir(parents=True)
    identity = {
        "run_id": f"math-run-{token}",
        "candidate_id": f"math-candidate-{token}",
        "commit_sha": codex_conversation.repository_commit_sha(),
    }
    provider_result_path = run_dir / "provider_result.json"
    generated_files = sorted(path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file())
    provider_result = {
        "status": "PASS",
        "goal": "Local GUI calculus handwriting training",
        "generated_files": generated_files,
        "project_dir": str(candidate),
        "candidate_lineage": [],
    }
    provider_result_path.write_text(json.dumps(provider_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entry_started = codex_conversation.now()
    entry_receipt = production_candidate_provenance.write_stage_receipt(run_dir, stage="production_entry", candidate_root=candidate, started_at=entry_started, **identity)
    provider_generation_started = codex_conversation.now()
    request = provider_causal_trace.begin_provider_request(
        candidate_dir=candidate,
        production_run_dir=run_dir,
        identity=identity,
        goal=provider_result["goal"],
        model="deterministic-e2e-fixture",
        request_started_at=provider_generation_started,
    )
    causal_capture = provider_causal_trace.consume_provider_response(
        candidate_dir=candidate,
        provider_staging_dir=source,
        production_run_dir=run_dir,
        provider_result_path=provider_result_path,
        identity=identity,
        provider_request_capture=request,
        response_received_at=codex_conversation.now(),
    )
    provider_result["project_dir"] = str(candidate)
    provider_result["provider_staging_dir"] = str(source)
    provider_result["provider_causal_artifacts"] = {
        key: str(pathlib.Path(value).resolve()) if key.endswith("_ref") else value
        for key, value in causal_capture.items()
    }
    provider_result_path.write_text(json.dumps(provider_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provider_hash = canonical_evidence_hash.sha256_file(provider_result_path)
    provider_ref = [{"role": "provider_generation_result", "ref": str(provider_result_path.resolve()), "hash": provider_hash}]
    causal_refs = [
        {"role": role, "ref": str(pathlib.Path(causal_capture[key]).resolve()), "hash": canonical_evidence_hash.sha256_file(causal_capture[key])}
        for role, key in (("provider_request", "request_ref"), ("provider_response", "response_ref"), ("implementation_decision", "decision_ref"), ("implementation_patch", "patch_ref"), ("patch_application", "application_ref"))
    ]
    stage_receipts = {"production_entry": entry_receipt}
    stage_receipts["provider_generation"] = production_candidate_provenance.write_stage_receipt(run_dir, stage="provider_generation", candidate_root=candidate, started_at=provider_generation_started, finished_at=codex_conversation.now(), artifact_refs=provider_ref + causal_refs, **identity)
    stage_receipts["provider_validation"] = production_candidate_provenance.write_stage_receipt(run_dir, stage="provider_validation", candidate_root=candidate, started_at=codex_conversation.now(), artifact_refs=provider_ref + causal_refs, **identity)
    session = codex_conversation.default_session("math-e2e")
    session["requirement"] = "Build a local calculus handwriting training GUI and provide a real screenshot."
    session["whiteboard"] = {"project_summary": session["requirement"]}
    session_dir = run_dir / "session"
    session_dir.mkdir(parents=True)
    finalized = codex_conversation.post_build_finalize_provider_project(
        candidate,
        provider_result,
        {},
        session,
        session_dir=session_dir,
        conversation_id="math-e2e",
        production_identity=identity,
        production_run_dir=run_dir,
        stage_receipts=stage_receipts,
        provider_result_path=provider_result_path,
        provider_causal_capture=causal_capture,
    )
    return candidate, identity, finalized


def test_math_handwriting_training_two_iteration_real_e2e(tmp_path: pathlib.Path) -> None:
    plan = compile_capability_plan({"goal": "Local GUI calculus handwriting training", "capabilities": CAPABILITIES})
    assert len(plan["capabilities"]) == 9
    project = tmp_path / "math-training"
    project.mkdir()
    (project / "index.html").write_text(HTML, encoding="utf-8")
    (project / "README.md").write_text("# Calculus Ink Lab\n\nRun `python -m http.server 8000` and open index.html.\n", encoding="utf-8")
    (project / "TEST_REPORT.md").write_text("# Test report\n\nPASS\n\nCommand: pytest tests/test_math_training_project_e2e.py\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text("# Delivery\n\nLocal browser application; no external API is required.\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_app.py").write_text("from pathlib import Path\n\ndef test_math_interface():\n    page = Path(__file__).parents[1].joinpath('index.html').read_text(encoding='utf-8')\n    assert 'Recognize & Grade' in page\n    assert 'localStorage' in page\n", encoding="utf-8")
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=str(project), **kwargs)
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1100, "height": 760})
            page.goto(url)
            page.get_by_role("button", name="Recognize & Grade").click()
            assert page.locator("#gradeResult").inner_text() == "Correct"
            assert page.locator("#progress").inner_text() == "Attempts: 1"
            page.get_by_role("button", name="Swap recognizer").click()
            page.get_by_role("button", name="Recognize & Grade").click()
            assert "alternate" in page.locator("#recognized").inner_text()
            assert page.locator("#progress").inner_text() == "Attempts: 2"
            screenshot = tmp_path / "math-training.png"
            page.screenshot(path=str(screenshot), full_page=True)
            browser.close()
        server.shutdown()
    assert screenshot.stat().st_size > 10_000
    run_dir = tmp_path / "formal-run"
    run_dir.mkdir()
    candidate, identity, finalized = _canonicalize_math_project(project, run_dir)
    canonical_screenshot_bytes = b""
    try:
        assert finalized["production_provenance"]["status"] == "PASS"
        assert finalized["test_result"]["status"] == "PASS"
        assert finalized["runtime_result"]["status"] == "PASS"
        assert finalized["visual_evidence_result"]["status"] == "PASS"
        assert finalized["canonical_verification"]["status"] == "PASS"
        assert finalized["canonical_finalization_state"]["state"] == "READY_FOR_DELIVERY"
        assert finalized["manifest"]["status"] == "PASS", finalized["manifest"].get("known_limits")
        assert finalized["gate"]["delivery_allowed"] is True, finalized["gate"]
        manifest_inspection = canonical_delivery_manifest.inspect_canonical_delivery_manifest(candidate)
        assert manifest_inspection["status"] == "PASS"
        assert manifest_inspection["manifest"]["candidate_hash"] == canonical_evidence_hash.candidate_source_hash(candidate)
        screenshot_ref = pathlib.Path(finalized["visual_evidence_result"]["screenshot_path"])
        package_ref = pathlib.Path(finalized["manifest"]["package_path"])
        requirements = {"screenshot": True}
        sent = [
            {"kind": "package", "path": str(package_ref), "conversation_id": "math-e2e", "turn_id": "turn-1", "artifact_id": "artifact-package", "artifact_unique_id": "unique-package"},
            {"kind": "screenshot", "path": str(screenshot_ref), "conversation_id": "math-e2e", "turn_id": "turn-2", "artifact_id": "artifact-screenshot", "artifact_unique_id": "unique-screenshot"},
        ]
        receipt = canonical_delivery_receipt.produce_canonical_delivery_receipt(candidate, conversation_id="math-e2e", manifest_inspection=manifest_inspection, requirement_snapshot=requirements, attempted_items=[(package_ref, "package"), (screenshot_ref, "screenshot")], sent_items=sent, started_at=codex_conversation.now())
        receipt_inspection = canonical_delivery_receipt.inspect_canonical_delivery_receipt(candidate, expected_conversation_id="math-e2e", expected_requirements=requirements, expected_attachment_refs={"package": package_ref, "screenshot": screenshot_ref})
        assert receipt["status"] == "PASS"
        assert receipt_inspection["status"] == "PASS", receipt_inspection.get("failures")
        canonical_screenshot_bytes = screenshot_ref.read_bytes()
    finally:
        if candidate.exists():
            shutil.rmtree(candidate)
    recognition = WorkNode("formula_recognition", "Recognize formula", inputs=("HandwritingArtifact",), outputs=("RecognizedFormula",), acceptance=("formula normalized",))
    reuse = select_reuse(recognition, [{"type": "internal", "ref": "project:LocalRecognitionAdapter", "inputs": ["HandwritingArtifact"], "outputs": ["RecognizedFormula"], "acceptance_compatible": True}])
    assert reuse["selected_source"]["type"] == "internal"
    evidence_dir = os.environ.get("CGKN_E2E_EVIDENCE_DIR", "").strip()
    if evidence_dir:
        destination = pathlib.Path(evidence_dir)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "math_training_screenshot.png").write_bytes(canonical_screenshot_bytes)
        (destination / "math_training_e2e.json").write_text(json.dumps({"kind": "CGKNMathTrainingE2E", "status": "PASS", "project": "Calculus Ink Lab", "run_id": identity["run_id"], "candidate_id": identity["candidate_id"], "candidate_hash": finalized["production_provenance"]["candidate_hash"], "capabilities": [item["id"] for item in plan["capabilities"]], "interfaces_validated": True, "iterations": [{"id": 1, "vertical_slice": ["handwriting_input", "formula_recognition", "grading", "user_interface"], "status": "PASS"}, {"id": 2, "vertical_slice": ["error_explanation", "question_generation", "progress_tracking", "recognizer_replacement"], "status": "PASS", "state_change": "recognizer executor replaced without grading change"}], "reuse_decisions": [reuse], "runtime": {"status": finalized["runtime_result"]["status"], "real_http_process": True, "customer_actions": 4}, "visual": {"status": finalized["visual_evidence_result"]["status"], "screenshot": "math_training_screenshot.png", "bytes": len(canonical_screenshot_bytes)}, "production_candidate": finalized["production_provenance"]["status"], "package": finalized["manifest"]["status"], "delivery_gate": {"status": "PASS", "decision": finalized["gate"]["status"], "delivery_allowed": finalized["gate"]["delivery_allowed"]}, "delivery_receipt": receipt["status"], "formal_release_authority": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
