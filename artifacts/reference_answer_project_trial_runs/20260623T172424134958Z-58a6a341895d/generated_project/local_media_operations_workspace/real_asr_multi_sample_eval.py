from __future__ import annotations

import argparse
import json
import os
import pathlib
from typing import Any

try:
    import asr_quality_gate
except (ImportError, ModuleNotFoundError):  # pragma: no cover - package import path
    from scripts import asr_quality_gate

try:
    import real_asr_adapter_contract
except (ImportError, ModuleNotFoundError):  # pragma: no cover - package import path
    from scripts import real_asr_adapter_contract


ENV_ADAPTER_KIND = asr_quality_gate.ENV_ADAPTER_KIND
DEFAULT_THRESHOLDS: dict[str, Any] = {
    **asr_quality_gate.DEFAULT_THRESHOLDS,
    "min_samples": 3,
}


def evaluate(
    *,
    project_dir: pathlib.Path,
    sample_paths: list[pathlib.Path],
    output_path: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
    adapter_kind: str | None = None,
    timeout: float = 2.0,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    effective_env = env if env is not None else os.environ
    command = str(effective_env.get(real_asr_adapter_contract.ENV_COMMAND, "")).strip()
    kind = str(adapter_kind or effective_env.get(ENV_ADAPTER_KIND, "none")).strip()
    report_path = pathlib.Path(output_path or project / "asr_multi_sample_report.json")
    if not command:
        return asr_quality_gate.empty_report(
            project,
            output_path=report_path,
            reason="no_asr_configured: CGKN_REAL_ASR_CMD is not configured.",
        )
    if kind not in {"fixture", "real_local_asr"}:
        report = asr_quality_gate.empty_report(
            project,
            output_path=report_path,
            reason="not_ready: CGKN_REAL_ASR_ADAPTER_KIND must be fixture or real_local_asr.",
        )
        report["adapter_kind"] = "none"
        asr_quality_gate.write_json(report_path, report)
        return report
    merged_thresholds = dict(DEFAULT_THRESHOLDS)
    merged_thresholds.update(thresholds or {})
    return asr_quality_gate.run_quality_gate(
        project_dir=project,
        sample_paths=sample_paths,
        output_path=report_path,
        env=effective_env,
        timeout=timeout,
        adapter_kind=kind,
        thresholds=merged_thresholds,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--sample", action="append", default=[])
    parser.add_argument("--output", default="asr_multi_sample_report.json")
    parser.add_argument("--adapter-kind", choices=["fixture", "real_local_asr"], default="")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--min-success-rate", type=float, default=1.0)
    parser.add_argument("--min-non-empty-text-rate", type=float, default=1.0)
    parser.add_argument("--min-non-empty-segments-rate", type=float, default=1.0)
    parser.add_argument("--max-timeout-count", type=int, default=0)
    parser.add_argument("--max-invalid-output-count", type=int, default=0)
    parser.add_argument("--allow-missing-confidence-reason", action="store_true")
    args = parser.parse_args()
    project = pathlib.Path(args.project_dir)
    output = pathlib.Path(args.output)
    if not output.is_absolute():
        output = project / output
    report = evaluate(
        project_dir=project,
        sample_paths=[pathlib.Path(item) for item in args.sample],
        output_path=output,
        adapter_kind=args.adapter_kind or None,
        timeout=args.timeout,
        thresholds={
            "min_samples": args.min_samples,
            "min_success_rate": args.min_success_rate,
            "min_non_empty_text_rate": args.min_non_empty_text_rate,
            "min_non_empty_segments_rate": args.min_non_empty_segments_rate,
            "max_timeout_count": args.max_timeout_count,
            "max_invalid_output_count": args.max_invalid_output_count,
            "require_confidence_or_reason": not args.allow_missing_confidence_reason,
        },
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["asr_quality_status"] in {"contract_only", "production_candidate"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
