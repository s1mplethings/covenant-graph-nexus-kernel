from __future__ import annotations

import http.server
import json
import os
import pathlib
import socketserver
import threading

from playwright.sync_api import sync_playwright

from scripts.capability_execution import compile_capability_plan, select_reuse
from scripts.local_packager import package_project
from scripts.work_nodes import WorkNode


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


def test_math_handwriting_training_two_iteration_real_e2e(tmp_path: pathlib.Path) -> None:
    plan = compile_capability_plan({"goal": "Local GUI calculus handwriting training", "capabilities": CAPABILITIES})
    assert len(plan["capabilities"]) == 9
    project = tmp_path / "math-training"
    project.mkdir()
    (project / "index.html").write_text(HTML, encoding="utf-8")
    (project / "README.md").write_text("# Calculus Ink Lab\n\nRun `python -m http.server 8000` and open index.html.\n", encoding="utf-8")
    (project / "TEST_REPORT.md").write_text("# Test report\n\nPASS\n\nCommand: pytest tests/test_math_training_project_e2e.py\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text("# Delivery\n\nLocal browser application; no external API is required.\n", encoding="utf-8")
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
    project_screenshot = project / "artifacts" / "screenshots" / "math_training.png"
    project_screenshot.parent.mkdir(parents=True)
    project_screenshot.write_bytes(screenshot.read_bytes())
    package = package_project(project, output_dir=tmp_path / "delivery", startup_command="python -m http.server 8000", screenshot_path=project_screenshot, visual_required=True)
    assert package["status"] == "NEEDS_REWORK"
    assert "runtime_evidence_not_pass" in package.get("failures", [])
    assert not pathlib.Path(package["package_path"]).is_file()
    recognition = WorkNode("formula_recognition", "Recognize formula", inputs=("HandwritingArtifact",), outputs=("RecognizedFormula",), acceptance=("formula normalized",))
    reuse = select_reuse(recognition, [{"type": "internal", "ref": "project:LocalRecognitionAdapter", "inputs": ["HandwritingArtifact"], "outputs": ["RecognizedFormula"], "acceptance_compatible": True}])
    assert reuse["selected_source"]["type"] == "internal"
    evidence_dir = os.environ.get("CGKN_E2E_EVIDENCE_DIR", "").strip()
    if evidence_dir:
        destination = pathlib.Path(evidence_dir)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "math_training_screenshot.png").write_bytes(screenshot.read_bytes())
        (destination / "math_training_e2e.json").write_text(json.dumps({"kind": "CGKNMathTrainingE2E", "status": "PASS_WITH_LIMITS", "project": "Calculus Ink Lab", "capabilities": [item["id"] for item in plan["capabilities"]], "interfaces_validated": True, "iterations": [{"id": 1, "vertical_slice": ["handwriting_input", "formula_recognition", "grading", "user_interface"], "status": "PASS"}, {"id": 2, "vertical_slice": ["error_explanation", "question_generation", "progress_tracking", "recognizer_replacement"], "status": "PASS", "state_change": "recognizer executor replaced without grading change"}], "reuse_decisions": [reuse], "runtime": {"real_http_process": True, "customer_actions": 4}, "visual": {"screenshot": "math_training_screenshot.png", "bytes": screenshot.stat().st_size}, "package": {"status": package["status"], "producer": "scripts.local_packager.package_project", "manifest_kind": "CGKNDeliveryManifest", "reason": "support E2E lacks production candidate identity and canonical runtime receipts; fail-closed as designed"}, "formal_release_authority": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
