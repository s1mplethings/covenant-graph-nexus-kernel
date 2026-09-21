#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any


ALLOWED_STATUS = {
    "PASS", "PASS_WITH_LIMITS", "NOT_EVALUATED", "BLOCKED", "BLOCKED_PROVIDER",
    "BLOCKED_LOCAL_MODEL", "BLOCKED_ENVIRONMENT", "NEEDS_REWORK", "FAIL",
}
SUMMARY_NAMES = ("run_summary.json", "verification_summary.json", "test_result.json", "known_limits.json", "run_manifest.json")
DROP_KEYS = {"cache", "artifacts", "checkpoints", "raw_provider_response", "provider_response", "generated_files", "raw_logs"}


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items() if key not in DROP_KEYS}
    if isinstance(value, list):
        return [compact(item) for item in value[:100]]
    return value


def promote(run_dir: pathlib.Path, output_dir: pathlib.Path, claim: str, status: str, reproduction: str) -> dict[str, Any]:
    if status not in ALLOWED_STATUS:
        raise ValueError(f"unsupported formal status: {status}")
    if not run_dir.is_dir():
        raise FileNotFoundError(run_dir)
    selected: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    limitations: list[str] = []
    for name in SUMMARY_NAMES:
        path = run_dir / name
        if not path.is_file():
            continue
        selected.append({"source": name, "sha256": sha256(path), "bytes": path.stat().st_size})
        try:
            data = compact(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if name in {"run_summary.json", "verification_summary.json", "test_result.json"}:
            metrics[name.removesuffix(".json")] = data
        if name == "known_limits.json":
            values = data.get("known_limits", data) if isinstance(data, dict) else data
            if isinstance(values, list):
                limitations.extend(str(item) for item in values)
    bundle = {
        "kind": "CGKNCuratedEvidenceBundle",
        "schemaVersion": "1",
        "claim": claim,
        "evidenceStatus": status,
        "sourceRun": run_dir.name,
        "sourceHashes": selected,
        "metrics": metrics,
        "testResult": metrics.get("test_result", {}),
        "knownLimitations": limitations,
        "reproductionCommand": reproduction,
        "excluded": ["cache", "complete artifacts", "checkpoints", "raw provider responses", "generated project copies", "raw logs"],
        "note": "Curated support evidence does not replace canonical evidence producers or delivery authority.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "verification_summary.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote a local run into a small curated evidence bundle.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--claim", required=True)
    parser.add_argument("--status", required=True, choices=sorted(ALLOWED_STATUS))
    parser.add_argument("--reproduction-command", required=True)
    args = parser.parse_args(argv)
    bundle = promote(pathlib.Path(args.run_dir).resolve(), pathlib.Path(args.output).resolve(), args.claim, args.status, args.reproduction_command)
    print(json.dumps({"output": str(pathlib.Path(args.output).resolve()), "sourceFiles": len(bundle["sourceHashes"]), "status": bundle["evidenceStatus"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
