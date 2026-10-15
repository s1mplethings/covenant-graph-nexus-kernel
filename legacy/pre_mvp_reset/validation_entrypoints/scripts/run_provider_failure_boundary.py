#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import pathlib
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_connectivity, provider_transport


DEFAULT_OUTPUT = ROOT / "artifacts" / "provider_failure_boundary_20260729" / "results.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _padded_prompt(instruction: str, target_chars: int) -> str:
    marker = "\nREFERENCE CONTEXT (do not repeat):\n"
    if len(instruction) >= target_chars:
        return instruction[:target_chars]
    remaining = target_chars - len(instruction) - len(marker)
    if remaining <= 0:
        return (instruction + marker)[:target_chars]
    unit = "stable_context_token "
    padding = (unit * ((remaining // len(unit)) + 1))[:remaining]
    return instruction + marker + padding


def _case_definitions() -> dict[str, dict[str, Any]]:
    short_instruction = (
        "Read the reference context, ignore its contents, and reply with exactly PONG. "
        "Do not add punctuation, reasoning, or markdown."
    )
    medium_output = (
        "Return only a valid Python module. Define 220 tiny functions named item_001 through "
        "item_220. Each function takes value and returns value plus its own integer index. "
        "No markdown, no omissions, no generated-code shortcuts, and no commentary."
    )
    complex_output = (
        "Return only a complete valid Python module for a modular project pipeline. "
        "Implement typed dataclasses for ContextSlice, StageInput, StageOutput, QualityFinding, "
        "Checkpoint, and InterfaceContract; twelve concrete pipeline stage classes; a stage "
        "registry; dependency validation; topological execution; retry policy; checkpoint "
        "serialization; affected-work repair routing; librarian context selection; feedforward "
        "and feedback events; quality gates; and deterministic unit-test-friendly behavior. "
        "Every public class and function must have a docstring. Include real implementations, "
        "not TODOs, pass statements, ellipses, placeholders, or prose. Keep all code in one file "
        "and make the module importable using only the Python standard library."
    )
    return {
        "control_1k_short": {
            "prompt": _padded_prompt(short_instruction, 1_000),
            "max_tokens": 64,
            "purpose": "control",
        },
        "input_16k_short": {
            "prompt": _padded_prompt(short_instruction, 16_000),
            "max_tokens": 64,
            "purpose": "input_size",
        },
        "input_32763_short": {
            "prompt": _padded_prompt(short_instruction, 32_763),
            "max_tokens": 64,
            "purpose": "input_size",
        },
        "input_39k_short": {
            "prompt": _padded_prompt(short_instruction, 39_000),
            "max_tokens": 64,
            "purpose": "input_size",
        },
        "output_2k_short_input": {
            "prompt": _padded_prompt(medium_output, 4_000),
            "max_tokens": 2_000,
            "purpose": "output_size",
        },
        "complex_32763_8k": {
            "prompt": _padded_prompt(complex_output, 32_763),
            "max_tokens": 8_000,
            "purpose": "combined_complexity",
        },
        "complex_32763_4k": {
            "prompt": _padded_prompt(complex_output, 32_763),
            "max_tokens": 4_000,
            "purpose": "combined_complexity",
        },
        "complex_32763_6k": {
            "prompt": _padded_prompt(complex_output, 32_763),
            "max_tokens": 6_000,
            "purpose": "combined_complexity",
        },
        "complex_32763_7k": {
            "prompt": _padded_prompt(complex_output, 32_763),
            "max_tokens": 7_000,
            "purpose": "combined_complexity",
        },
        "concurrency_medium": {
            "prompt": _padded_prompt(
                "Return only a valid Python module containing 80 small, distinct, typed arithmetic functions.",
                4_000,
            ),
            "max_tokens": 1_024,
            "purpose": "concurrency",
        },
    }


def _usage_summary(doc: dict[str, Any]) -> dict[str, int]:
    raw = doc.get("usage")
    if not isinstance(raw, dict):
        return {}
    summary: dict[str, int] = {}
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
    ):
        value = raw.get(key)
        if isinstance(value, int):
            summary[key] = value
    return summary


def _run_once(
    *,
    name: str,
    case: dict[str, Any],
    model: str,
    timeout: int,
    endpoint: str,
    base_url: str,
    token: str,
    ordinal: int = 1,
) -> dict[str, Any]:
    prompt = str(case["prompt"])
    messages = [
        {"role": "system", "content": "Follow the output contract exactly. Do not reveal hidden context."},
        {"role": "user", "content": prompt},
    ]
    payload = check_connectivity._build_openai_compatible_payload(
        base_url,
        {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": int(case["max_tokens"]),
        },
        model=model,
    )
    started = time.monotonic()
    doc, error = provider_transport.post_json_once(endpoint, payload, token, timeout)
    elapsed = time.monotonic() - started
    result: dict[str, Any] = {
        "case": name,
        "ordinal": ordinal,
        "purpose": case["purpose"],
        "ok": doc is not None and not error,
        "prompt_chars": sum(len(item["content"]) for item in messages),
        "request_bytes": len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        "max_tokens": int(case["max_tokens"]),
        "elapsed_seconds": round(elapsed, 3),
        "error_type": "",
        "error": "",
        "response_chars": 0,
        "response_sha256": "",
        "usage": {},
    }
    if doc is None or error:
        result["error"] = provider_transport._redact(error, token)
        result["error_type"] = provider_transport.classify_provider_error(error)
        return result
    text = check_connectivity._extract_text(doc)
    result["response_chars"] = len(text)
    result["response_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    result["usage"] = _usage_summary(doc)
    result["request_id_present"] = bool(str(doc.get("id", "")).strip())
    choices = doc.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        result["finish_reason"] = str(choices[0].get("finish_reason", "")).strip()
    return result


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [item for item in results if not item["ok"]]
    successes = [item for item in results if item["ok"]]
    elapsed = [float(item["elapsed_seconds"]) for item in results]
    return {
        "request_count": len(results),
        "success_count": len(successes),
        "failure_count": len(failures),
        "success_rate": round(len(successes) / len(results), 3) if results else 0.0,
        "median_elapsed_seconds": round(statistics.median(elapsed), 3) if elapsed else 0.0,
        "max_elapsed_seconds": round(max(elapsed), 3) if elapsed else 0.0,
        "failure_types": sorted({str(item["error_type"]) for item in failures}),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    credentials = check_connectivity._resolve_api_credentials()
    token = str(credentials.get("api_key", "")).strip()
    base_url = str(credentials.get("base_url", "")).strip().rstrip("/")
    if not token or not base_url:
        raise RuntimeError("provider credentials are not configured")
    endpoint = check_connectivity._openai_compatible_endpoint(base_url, model=args.model)
    definitions = _case_definitions()
    selected_names = [item.strip() for item in args.cases.split(",") if item.strip()]
    unknown = sorted(set(selected_names) - set(definitions))
    if unknown:
        raise ValueError(f"unknown cases: {', '.join(unknown)}")

    results: list[dict[str, Any]] = []
    for name in selected_names:
        case = definitions[name]
        for ordinal in range(1, max(1, args.repeats) + 1):
            results.append(
                _run_once(
                    name=name,
                    case=case,
                    model=args.model,
                    timeout=args.timeout,
                    endpoint=endpoint,
                    base_url=base_url,
                    token=token,
                    ordinal=ordinal,
                )
            )

    if args.concurrency > 0:
        case = definitions["concurrency_medium"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = [
                executor.submit(
                    _run_once,
                    name="concurrency_medium",
                    case=case,
                    model=args.model,
                    timeout=args.timeout,
                    endpoint=endpoint,
                    base_url=base_url,
                    token=token,
                    ordinal=ordinal,
                )
                for ordinal in range(1, args.concurrency + 1)
            ]
            results.extend(future.result() for future in futures)

    return {
        "kind": "CGKNProviderFailureBoundaryResult",
        "schema_version": "1.0",
        "created_at": _utc_now(),
        "model": args.model,
        "base_url_domain": check_connectivity._base_url_domain(base_url),
        "api_method": check_connectivity._selected_provider_api_method(base_url, args.model),
        "timeout_seconds": args.timeout,
        "single_attempt_per_request": True,
        "secrets_recorded": False,
        "results": results,
        "summary": _aggregate(results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded live Provider failure-boundary probe without storing generated content."
    )
    parser.add_argument("--model", default="gpt-5.4-nano")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument(
        "--cases",
        default=(
            "control_1k_short,input_16k_short,input_32763_short,input_39k_short,"
            "output_2k_short_input,complex_32763_8k"
        ),
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=0)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    report = run(args)
    target = pathlib.Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["summary"]["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
