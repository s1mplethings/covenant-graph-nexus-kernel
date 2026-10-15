from __future__ import annotations

import json

from benchmarks.project_generation_v1 import run_trimmed_case_debug as trimmed


def test_trimmed_case_debug_routes_factory_app_and_methods(tmp_path) -> None:
    app = tmp_path / "app" / "main.py"
    app.parent.mkdir()
    app.write_text(
        """
from flask import Flask
app = Flask(__name__)
@app.route('/health', methods=['GET'])
def health(): ...
@app.post('/api/upload')
def upload(): ...
""",
        encoding="utf-8",
    )

    routes = trimmed.route_methods(tmp_path)

    assert routes == {"/health": {"GET"}, "/api/upload": {"POST"}}


def test_trimmed_case_debug_links_issue_job_delta_and_rejection(tmp_path) -> None:
    artifacts = tmp_path / "production_slots" / "slot" / "run" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "post_build_issue_ledger_attempt_1.json").write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "issue_id": "ISSUE-EXPORT",
                        "failed_requirement": "export_download_failure",
                        "observed_behavior": "CSV download failed",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "post_build_repair_plan_attempt_1.json").write_text(
        json.dumps({"repair_bundles": [{"bundle_id": "JOB-1", "issue_ids": ["ISSUE-EXPORT"]}]}),
        encoding="utf-8",
    )
    (artifacts / "repair_call_accounting.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "issue_ids": ["ISSUE-EXPORT"],
                        "provider_calls_in_batch": 1,
                        "issue_level_acceptance": False,
                        "pre_acceptance_failure": "AFFECTED_BEHAVIOR_VALIDATION_FAILED",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    linked = trimmed.link_behavior_to_repair(
        tmp_path,
        trimmed._behavior("export_csv", "download", "HTTP 500", False),
    )

    assert linked["mapped_issue"] == "ISSUE-EXPORT"
    assert linked["provider_job_created"] is True
    assert linked["provider_called"] is True
    assert linked["delta_returned"] is True
    assert linked["delta_accepted"] is False
    assert linked["why_not_fixed"].startswith("delta_rejected:")


def test_trimmed_case_debug_reports_semantic_block_before_materialization(tmp_path) -> None:
    production = {
        "candidate_materialized": False,
        "diagnostics": {
            "stage": "provider_semantic_review",
            "blockers": ["tests/test_board.py imports test-local browser driver dependency selenium"],
        },
        "fatal_fact_blockers": ["canonical project plan files missing: tests/test_board.py"],
        "repairable_fact_blockers": [],
    }

    result = trimmed.semantic_handoff_diagnosis(production, tmp_path)

    assert result["candidate_materialized"] is False
    assert result["blocked_stage"] == "provider_semantic_review"
    assert result["semantic_violation_repairable"] is False
    assert result["fatal_or_repairable"] == "fatal_materialization_block"
    assert result["reached_post_build_issue_ledger"] is False


def test_trimmed_case_debug_detects_forbidden_side_branch_artifact(tmp_path) -> None:
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "provider_phase_log.jsonl").write_text(
        json.dumps({"event": "component_leaf_completed", "phase": "project_generation"}) + "\n",
        encoding="utf-8",
    )
    assert trimmed.scan_side_branches(clean) == []

    forbidden = tmp_path / "forbidden"
    forbidden.mkdir()
    (forbidden / "provider_phase_log.jsonl").write_text(
        json.dumps({"event": "final_promotion_started"}) + "\n",
        encoding="utf-8",
    )
    assert trimmed.scan_side_branches(forbidden) == ["phase:final_promotion_started"]


def test_trimmed_case_debug_has_no_delivery_or_scale_imports() -> None:
    source = (trimmed.ROOT / "benchmarks" / "project_generation_v1" / "run_trimmed_case_debug.py").read_text(encoding="utf-8")

    assert "from scripts import final_promotion" not in source
    assert "import run_acfv_scale_benchmark" not in source
    assert "import run_commercial_readiness" not in source
    assert "telegram_delivery" not in source


def test_trimmed_case_debug_live_case01_http_probe(tmp_path) -> None:
    app = tmp_path / "app" / "main.py"
    app.parent.mkdir()
    app.write_text(
        """
from flask import Flask, jsonify, request, Response
app = Flask(__name__)
@app.route('/')
def root(): return '<input type="file">'
@app.route('/health')
def health(): return jsonify(status='ok')
@app.route('/upload', methods=['POST'])
def upload():
    assert request.files['file']
    return jsonify(before_preview=[{'name':' Alice '}], preview=[{'name':'Alice'}], stats={'raw_nulls':1, 'malformed_rows':1})
@app.route('/export', methods=['POST'])
def export(): return Response('name\\nAlice\\n', mimetype='text/csv')
""",
        encoding="utf-8",
    )

    records, extra = trimmed.probe_case01(tmp_path)

    assert [row["pass"] for row in records] == [True, True, True, True]
    assert extra == {"missing": True, "malformed": True}


def test_trimmed_case_debug_probes_api_even_when_static_root_is_404(tmp_path) -> None:
    app = tmp_path / "app" / "main.py"
    app.parent.mkdir()
    app.write_text(
        """
from flask import Flask, jsonify, request, Response
app = Flask(__name__)
@app.route('/clean', methods=['POST'])
def clean():
    assert request.files['file']
    return jsonify(before_preview=[{'name':' Alice '}], preview=[{'name':'Alice'}], stats={'raw_nulls':1, 'malformed_rows':1})
@app.route('/export', methods=['POST'])
def export(): return Response('name\\nAlice\\n', mimetype='text/csv')
""",
        encoding="utf-8",
    )

    records, _extra = trimmed.probe_case01(tmp_path)

    assert records[0]["pass"] is False
    assert "HTTP 404" in records[0]["observed"]
    assert [row["pass"] for row in records[1:]] == [True, True, True]


def test_trimmed_case_debug_supports_split_import_clean_preview_session(tmp_path) -> None:
    app = tmp_path / "app" / "main.py"
    app.parent.mkdir()
    app.write_text(
        """
from flask import Flask, jsonify, request, Response, session
app = Flask(__name__); app.secret_key = 'test'
@app.route('/import', methods=['POST'])
def import_csv():
    assert request.files['file']; session['loaded'] = True
    return jsonify(status='loaded', stats={'raw_nulls':1, 'malformed_rows':1})
@app.route('/clean', methods=['POST'])
def clean():
    assert session['loaded']; session['cleaned'] = True
    return jsonify(status='cleaned')
@app.route('/preview')
def preview():
    assert session['cleaned']
    return jsonify(original_head=[{'name':' Alice '}], cleaned_head=[{'name':'Alice'}])
@app.route('/export')
def export():
    assert session['cleaned']; return Response('name\\nAlice\\n', mimetype='text/csv')
""",
        encoding="utf-8",
    )

    records, extra = trimmed.probe_case01(tmp_path)

    assert records[0]["pass"] is False
    assert [row["pass"] for row in records[1:]] == [True, True, True]
    assert extra == {"missing": True, "malformed": True}
