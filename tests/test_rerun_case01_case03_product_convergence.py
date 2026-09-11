from __future__ import annotations

import argparse
import json

from scripts import rerun_case01_case03_product_convergence as convergence


def args(tmp_path):
    return argparse.Namespace(
        model="qwen3.8-flash",
        run_id="fresh-convergence-test",
        output_root=tmp_path,
    )


def test_provider_quota_blocks_before_any_fresh_case(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        convergence,
        "benchmark_hashes",
        lambda: dict(convergence.EXPECTED_BENCHMARK_HASHES),
    )
    monkeypatch.setattr(
        convergence,
        "run_provider_preflight",
        lambda model: {
            "ok": False,
            "api": {"error": "HTTP 403: Free quota exhausted"},
        },
    )
    monkeypatch.setattr(
        convergence,
        "run_fresh_case",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("fresh cases must not run while Provider is blocked")
        ),
    )

    report_path, report = convergence.execute(args(tmp_path))

    assert report["status"] == "BLOCKED_PROVIDER_HTTP_403"
    assert report["workflow_state"] == "WAITING_FOR_PROVIDER_QUOTA"
    assert report["case_runs"] == []
    assert json.loads(report_path.read_text(encoding="utf-8"))["case_runs"] == []


def test_provider_ok_runs_fresh_case01_then_case03(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        convergence,
        "benchmark_hashes",
        lambda: dict(convergence.EXPECTED_BENCHMARK_HASHES),
    )
    monkeypatch.setattr(
        convergence,
        "run_provider_preflight",
        lambda model: {"ok": True, "api": {"status": "connected"}},
    )

    def fake_run(selector, *, run_id, output_root, model):
        calls.append(selector)
        run_dir = output_root / run_id
        return run_dir, {
            "case_results": [
                {
                    "result": "PROJECT_FAIL",
                    "score": 34 if selector == "01" else 26,
                }
            ]
        }

    monkeypatch.setattr(convergence, "run_fresh_case", fake_run)

    _, report = convergence.execute(args(tmp_path))

    assert calls == ["01", "03"]
    assert report["status"] == "COMPLETE"
    assert [row["score"] for row in report["case_runs"]] == [34, 26]
    assert report["benchmark_hash_unchanged"] is True


def test_frozen_benchmark_hash_mismatch_blocks_preflight(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        convergence,
        "benchmark_hashes",
        lambda: {"cases.json": "changed", "evaluator.py": "changed"},
    )
    monkeypatch.setattr(
        convergence,
        "run_provider_preflight",
        lambda model: (_ for _ in ()).throw(
            AssertionError("preflight must not run after a hash mismatch")
        ),
    )

    _, report = convergence.execute(args(tmp_path))

    assert report["status"] == "BENCHMARK_HASH_MISMATCH"
    assert report["case_runs"] == []


def test_convergence_wrapper_does_not_add_provider_scheduler() -> None:
    source = (convergence.ROOT / "scripts" / "rerun_case01_case03_product_convergence.py").read_text(
        encoding="utf-8"
    )
    assert "ThreadPoolExecutor" not in source
    assert "ProcessPoolExecutor" not in source
    assert "execute_provider_jobs" not in source
