from __future__ import annotations

import inspect
import json
import pathlib

import pytest
from jsonschema import Draft202012Validator

from benchmarks.project_generation_v1 import evaluator
from benchmarks.project_generation_v1.fixtures import create_fake_candidate, run_dry_case_probes
from benchmarks.project_generation_v1.run_benchmark import (
    CASES_PATH,
    ROOT,
    build_parser,
    execute,
    normalize_case_selector,
    provider_readiness_blocker,
    select_cases,
)


def _catalog() -> dict:
    return evaluator.load_case_catalog(CASES_PATH)


def _case(number: int) -> dict:
    prefix = f"CASE_{number:02d}_"
    return next(item for item in _catalog()["cases"] if item["case_id"].startswith(prefix))


def _fixture_result(tmp_path: pathlib.Path, number: int = 3, *, run_id: str = "TEST_RUN") -> tuple[dict, pathlib.Path, list[dict]]:
    case = _case(number)
    case_dir = tmp_path / case["case_id"]
    case_dir.mkdir(parents=True)
    candidate = create_fake_candidate(case, case_dir, {"user_goal": case["user_goal"]})
    observations = run_dry_case_probes(case, run_id, candidate, case_dir)
    return case, candidate, observations


def _repair_receipt() -> dict:
    return {
        "injected_after_happy_path": True,
        "affected_jobs": ["job_ui"],
        "provider_recalled_jobs": ["job_ui"],
        "invalidated_evidence": ["runtime"],
        "reemitted_evidence": ["runtime"],
        "recovery_status": "PASS",
    }


def _metrics() -> dict:
    return {"provider_api_calls": 3, "codex_invocations": 1, "elapsed_seconds": 2.5, "total_tokens": 700, "actual_cost": 0.02, "provider_generation_wall_time": 2.0}


def _add_visual_observation(case: dict, candidate: pathlib.Path, observations: list[dict], run_id: str) -> None:
    observations.append(evaluator.make_observation(
        case_id=case["case_id"], run_id=run_id, candidate_sha256=evaluator.candidate_tree_hash(candidate),
        criterion_id="visual.independent", status="PASS", producer="benchmark_browser_probe",
        details="real browser layout and interaction probe passed", requirement_ids=[],
    ))


def test_case_catalog_validates_against_schema_and_has_exact_fixed_shape() -> None:
    catalog = _catalog()
    schema = json.loads((ROOT / "schemas" / "project_generation_benchmark_case_v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(catalog)
    assert len(catalog["cases"]) == 10
    assert [case["level"] for case in catalog["cases"]] == ["L1", "L1", "L2", "L2", "L3", "L3", "L3", "L4", "L4", "L5"]


def test_case_10_keeps_only_the_ambiguous_user_goal() -> None:
    case = _case(10)
    assert case["user_goal"] == "帮我做一个适合小团队使用的客户反馈管理工具。我们平时会收集客户提的问题和建议，希望能整理、跟踪处理情况，以后方便查找。你自己设计第一版。"
    assert "dashboard" not in case["user_goal"].lower()
    assert "workflow" not in case["user_goal"].lower()


def test_all_ten_user_goals_are_the_fixed_benchmark_inputs() -> None:
    expected = [
        "帮我做一个本地工具，可以导入 CSV，自动处理空值、重复行和明显格式问题，让我预览清洗前后差异，最后导出清洗后的 CSV。",
        "做一个批量处理 Markdown 文档的小工具，可以读取一个目录，生成 HTML，保留标题、列表、代码块和链接，最后输出到另一个目录。",
        "做一个我自己本机使用的项目任务看板，可以创建、编辑、删除和移动任务，关闭以后重新打开数据还在，并且能把当前任务导出成 JSON。",
        "帮我做一个个人物品管理工具，记录物品名称、分类、数量、购买日期和备注，可以搜索和筛选，数量改变以后保存，还可以导出数据。",
        "我想要一个本地个人收支管理工具，记录收入和支出，按月份和类别查看，有简单图表，可以导入和导出数据。",
        "做一个本地笔记工具，可以创建多篇笔记，加标签，快速搜索内容，支持 Markdown，关掉以后内容不能丢。",
        "做一个本地批量图片处理工具，我选一个文件夹，可以统一缩放图片，改输出格式，设置输出目录，并看到处理成功和失败的结果。",
        "做一个我自己用的 RSS 阅读工具，可以添加几个 RSS 地址，拉取文章，按来源查看，标记已读，下次打开还能记住。",
        "我想要一个本地运行的小服务，可以通过 API 管理一些记录，同时提供一个简单网页让我查看和编辑，API 和网页必须操作同一份数据。",
        "帮我做一个适合小团队使用的客户反馈管理工具。我们平时会收集客户提的问题和建议，希望能整理、跟踪处理情况，以后方便查找。你自己设计第一版。",
    ]
    assert [case["user_goal"] for case in _catalog()["cases"]] == expected


def test_hidden_acceptance_is_not_forwarded_to_fake_production(tmp_path: pathlib.Path) -> None:
    case = _case(1)
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    create_fake_candidate(case, case_dir, {"user_goal": case["user_goal"]})
    receipt = evaluator.read_json(case_dir / "production_context_receipt.json")
    assert receipt["visible_keys"] == ["user_goal"]
    assert receipt["hidden_acceptance_visible"] is False
    with pytest.raises(ValueError, match="hidden benchmark data"):
        create_fake_candidate(case, tmp_path / "bad", {"user_goal": case["user_goal"], "hidden_acceptance": "leak"})


def test_evaluator_has_no_production_verdict_parameter_or_runtime_import() -> None:
    signature = inspect.signature(evaluator.evaluate_case)
    source = inspect.getsource(evaluator)
    assert "production_result" not in signature.parameters
    assert "from scripts" not in source
    assert "production_verdict_used" in source


def test_live_runner_pins_requested_model_and_parallelism() -> None:
    source = inspect.getsource(__import__("benchmarks.project_generation_v1.run_benchmark", fromlist=["invoke_production"]).invoke_production)
    assert '"--small-model", args.model' in source
    assert '"--large-model", args.model' in source
    assert '"--disable-model-routing"' in source
    assert 'production_env["CGKN_PROVIDER_PARALLELISM"] = str(args.parallelism)' in source


def test_external_process_and_http_runtime_probes_are_real(tmp_path: pathlib.Path) -> None:
    _, _, csv_observations = _fixture_result(tmp_path / "csv", 1, run_id="RUNTIME")
    _, _, board_observations = _fixture_result(tmp_path / "board", 3, run_id="RUNTIME")
    csv_runtime = next(item for item in csv_observations if item["criterion_id"] == "csv.runtime")
    board_runtime = next(item for item in board_observations if item["criterion_id"] == "board.runtime")
    assert csv_runtime["producer"] == "benchmark_process_probe" and csv_runtime["status"] == "PASS"
    assert board_runtime["producer"] == "benchmark_http_probe" and board_runtime["status"] == "PASS"
    assert board_runtime["elapsed_ms"] > 0


def test_persistence_uses_a_fresh_process_and_export_matches(tmp_path: pathlib.Path) -> None:
    _, _, observations = _fixture_result(tmp_path, 3, run_id="PERSIST")
    by_id = {item["criterion_id"]: item for item in observations}
    assert by_id["board.persist"]["producer"] == "benchmark_persistence_probe"
    assert by_id["board.persist"]["status"] == "PASS"
    assert by_id["board.export"]["status"] == "PASS"


def test_full_external_evidence_can_score_100(tmp_path: pathlib.Path) -> None:
    case, candidate, observations = _fixture_result(tmp_path, 3, run_id="PERFECT")
    _add_visual_observation(case, candidate, observations, "PERFECT")
    result = evaluator.evaluate_case(case, run_id="PERFECT", candidate_dir=candidate, observations=observations, metrics=_metrics(), repair=_repair_receipt())
    assert result["score"] == 100
    assert result["result"] == "PROJECT_PASS"
    assert result["production_verdict_used"] is False


def test_hard_acceptance_failure_overrides_score_above_80(tmp_path: pathlib.Path) -> None:
    case, candidate, observations = _fixture_result(tmp_path, 3, run_id="HARD")
    _add_visual_observation(case, candidate, observations, "HARD")
    next(item for item in observations if item["criterion_id"] == "board.move")["status"] = "FAIL"
    result = evaluator.evaluate_case(case, run_id="HARD", candidate_dir=candidate, observations=observations, metrics=_metrics(), repair=_repair_receipt())
    assert result["score"] >= 80
    assert result["result"] == "PROJECT_FAIL"
    assert "board.move" in result["hard_failures"]


@pytest.mark.parametrize("error", ["HTTP 403 quota exhausted", "TLS certificate verify failed", "provider timeout", "BLOCKED_PROVIDER"])
def test_provider_outage_is_classified_blocked_provider(error: str, tmp_path: pathlib.Path) -> None:
    result = evaluator.evaluate_case(_case(1), run_id="BLOCKED", candidate_dir=tmp_path / "missing", observations=[], provider_error=error)
    assert result["result"] == "BLOCKED_PROVIDER"
    assert result["score"] is None


def test_ordinary_generation_failure_is_not_provider_blocker() -> None:
    assert evaluator.classify_provider_blocker("Provider returned invalid customer source files") is False
    assert evaluator.classify_provider_blocker("Core feature test failed") is False


def test_candidate_hash_change_invalidates_stale_evidence(tmp_path: pathlib.Path) -> None:
    case, candidate, observations = _fixture_result(tmp_path, 1, run_id="STALE")
    (candidate / "app.py").write_text((candidate / "app.py").read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    result = evaluator.evaluate_case(case, run_id="STALE", candidate_dir=candidate, observations=observations, metrics=_metrics())
    assert result["result"] == "PROJECT_FAIL"
    assert result["accepted_observation_count"] == 0
    assert any("stale_candidate_identity" in item for item in result["rejected_observations"])


def test_run_and_case_identity_mismatch_is_rejected(tmp_path: pathlib.Path) -> None:
    case, candidate, observations = _fixture_result(tmp_path, 1, run_id="ORIGINAL")
    result = evaluator.evaluate_case(case, run_id="OTHER", candidate_dir=candidate, observations=observations, metrics=_metrics())
    assert result["accepted_observation_count"] == 0
    assert any("run_identity_mismatch" in item for item in result["rejected_observations"])


def test_untrusted_self_reported_evidence_is_rejected(tmp_path: pathlib.Path) -> None:
    case, candidate, observations = _fixture_result(tmp_path, 1, run_id="TRUST")
    observations[0]["producer"] = "cgkn_final_verdict"
    result = evaluator.evaluate_case(case, run_id="TRUST", candidate_dir=candidate, observations=observations, metrics=_metrics())
    assert any("untrusted_producer" in item for item in result["rejected_observations"])


def test_repair_scope_rejects_provider_recall_outside_affected_jobs() -> None:
    valid, problems = evaluator.validate_repair_scope(_repair_receipt())
    assert valid and not problems
    escaped = _repair_receipt()
    escaped["provider_recalled_jobs"].append("unaffected_job")
    valid, problems = evaluator.validate_repair_scope(escaped)
    assert not valid
    assert any("escaped" in item for item in problems)


def test_repair_scope_requires_stale_evidence_reemission() -> None:
    receipt = _repair_receipt()
    receipt["reemitted_evidence"] = []
    valid, problems = evaluator.validate_repair_scope(receipt)
    assert not valid
    assert any("re-emitted" in item for item in problems)


def test_provider_and_codex_invocations_are_counted_by_unique_receipt_id(tmp_path: pathlib.Path) -> None:
    evaluator.write_json(tmp_path / "trace.json", {
        "events": [
            {"kind": "ProviderInvocationReceipt", "invocation_id": "p1", "job_id": "j1", "usage": {"total_tokens": 10}},
            {"kind": "ProviderInvocationReceipt", "invocation_id": "p1", "job_id": "j1"},
            {"kind": "ProviderInvocationReceipt", "invocation_id": "p2", "job_id": "j2"},
            {"kind": "CodexAuditInvocation", "invocation_id": "c1", "usage": {"total_tokens": 5, "estimated_cost": 0.01}},
        ]
    })
    metrics = evaluator.collect_invocation_metrics(tmp_path)
    assert metrics["provider_api_calls"] == 2
    assert metrics["codex_invocations"] == 1
    assert metrics["distinct_jobs"] == 2
    assert metrics["total_tokens"] == 15


def test_canonical_provider_execution_metrics_are_collected(tmp_path: pathlib.Path) -> None:
    evaluator.write_json(tmp_path / "provider_execution_metrics.json", {
        "kind": "CGKNProviderExecutionMetrics", "provider_api_call_count": 17,
        "provider_peak_concurrency": 2, "provider_jobs_total": 4,
        "provider_jobs_reused_after_pass": 1, "provider_jobs_repaired": 2,
        "wall_clock_stage_timing": {"component_file_generation": 285.077},
        "codex_supervisor_invocation_count": 1, "codex_kernel_repair_invocation_count": 1,
    })
    metrics = evaluator.collect_invocation_metrics(tmp_path)
    assert metrics["provider_api_calls"] == 17
    assert metrics["provider_peak_concurrency"] == 2
    assert metrics["provider_generation_wall_time"] == 285.077
    assert metrics["codex_invocations"] == 2


def test_aggregation_keeps_pass_fail_blocked_and_not_evaluated_separate() -> None:
    values = [{"result": value, "score": score, "metrics": {}} for value, score in [
        ("PROJECT_PASS", 90), ("PROJECT_FAIL", 40), ("BLOCKED_PROVIDER", None), ("NOT_EVALUATED", None)
    ]]
    summary = evaluator.aggregate_results(values)
    assert summary["counts"] == {"PROJECT_PASS": 1, "PROJECT_FAIL": 1, "BLOCKED_PROVIDER": 1, "NOT_EVALUATED": 1}
    assert summary["pass_rate"] == 0.5
    assert summary["average_score"] == 65.0


def test_dry_run_report_validates_and_never_claims_cgkn_pass(tmp_path: pathlib.Path) -> None:
    args = build_parser().parse_args(["--dry-run", "--run-id", "DRY_SCHEMA", "--output-root", str(tmp_path)])
    run_dir, report = execute(args)
    schema = json.loads((ROOT / "schemas" / "project_generation_benchmark_report_v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    assert report["summary"]["counts"]["NOT_EVALUATED"] == 2
    assert all(item["harness_probe_status"] == "PASS" for item in report["case_results"])
    assert all(item["result"] != "PROJECT_PASS" for item in report["case_results"])
    assert [item["score"] for item in report["case_results"]] == [85, 85]
    assert report["harness_checks"]["overall"] == "PASS"
    assert (run_dir / "benchmark_report.md").is_file()


def test_resume_reuses_case_results_without_overwriting(tmp_path: pathlib.Path) -> None:
    first = build_parser().parse_args(["--dry-run", "--run-id", "RESUME_RUN", "--output-root", str(tmp_path)])
    run_dir, _ = execute(first)
    result_path = run_dir / "cases" / "CASE_01_CSV_DATA_CLEANER" / "case_result.json"
    original = result_path.read_bytes()
    resumed = build_parser().parse_args(["--dry-run", "--resume", "--run-id", "RESUME_RUN", "--output-root", str(tmp_path)])
    _, report = execute(resumed)
    assert result_path.read_bytes() == original
    assert all(item.get("resumed_without_overwrite") for item in report["case_results"])
    assert list((run_dir / "reports").glob("benchmark_report_*.json"))


def test_existing_run_requires_resume(tmp_path: pathlib.Path) -> None:
    args = build_parser().parse_args(["--dry-run", "--run-id", "NO_OVERWRITE", "--output-root", str(tmp_path)])
    execute(args)
    with pytest.raises(FileExistsError):
        execute(args)


def test_report_only_does_not_execute_or_overwrite_case_results(tmp_path: pathlib.Path) -> None:
    args = build_parser().parse_args(["--dry-run", "--run-id", "REPORT_ONLY", "--output-root", str(tmp_path)])
    run_dir, _ = execute(args)
    result_path = run_dir / "cases" / "CASE_03_LOCAL_PROJECT_BOARD" / "case_result.json"
    original = result_path.read_bytes()
    report_args = build_parser().parse_args(["--report-only", "--run-id", "REPORT_ONLY", "--output-root", str(tmp_path)])
    _, report = execute(report_args)
    assert result_path.read_bytes() == original
    assert report["mode"] == "HARNESS_DRY_RUN"


def test_baseline_comparison_reports_long_term_deltas() -> None:
    current = {"run_id": "new", "summary": {"pass_rate": 0.8, "one_shot_success_rate": 0.7, "repair_success_rate": 0.9, "requirement_coverage": 0.95, "median_provider_calls": 12, "median_provider_wall_time": 100, "median_codex_calls": 3}}
    baseline = {"run_id": "old", "summary": {"pass_rate": 0.6, "one_shot_success_rate": 0.5, "repair_success_rate": 0.8, "requirement_coverage": 0.9, "median_provider_calls": 15, "median_provider_wall_time": 120, "median_codex_calls": 4}}
    comparison = evaluator.compare_reports(current, baseline)
    assert comparison["baseline_run_id"] == "old"
    assert comparison["deltas"]["pass_rate"] == pytest.approx(0.2)
    assert comparison["deltas"]["median_provider_calls"] == -3


def test_provider_readiness_file_blocks_without_running_cases(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "readiness.json"
    path.write_text(json.dumps({"status": "BLOCKED_PROVIDER", "error": "HTTP 403 quota exhausted"}), encoding="utf-8")
    assert "403" in provider_readiness_blocker(path)


def test_case_and_level_selection_are_deterministic() -> None:
    parser = build_parser()
    case_args = parser.parse_args(["--case", "03"])
    level_args = parser.parse_args(["--level", "L3"])
    pilot_args = parser.parse_args(["--pilot"])
    assert normalize_case_selector("3") == "CASE_03_"
    assert [item["case_id"] for item in select_cases(_catalog(), case_args)] == ["CASE_03_LOCAL_PROJECT_BOARD"]
    assert len(select_cases(_catalog(), level_args)) == 3
    assert [item["case_id"][:7] for item in select_cases(_catalog(), pilot_args)] == ["CASE_01", "CASE_03", "CASE_10"]


def test_contamination_guard_detects_fixture_marker_in_production_tree(tmp_path: pathlib.Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "bad.py").write_text('CASE_NAME = "CASE_01_CSV_DATA_CLEANER"\n', encoding="utf-8")
    findings = evaluator.scan_production_contamination(tmp_path)
    assert findings == [{"path": "scripts/bad.py", "marker": "case_01"}]


def test_current_production_tree_has_no_benchmark_contamination() -> None:
    assert evaluator.scan_production_contamination(ROOT) == []
