from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import pathlib
import re
import subprocess
import tempfile
import zipfile
from typing import Iterable


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_RESULT = ROOT / "cgkn-function-stress-pass" / "pass2-functional-closure"
RUNTIME = ROOT / "artifacts" / "function_stress_pass" / "20261010-pass2"
UNTRACKED_IMPLEMENTATION = (
    "benchmarks/project_generation_v1/audit_failure_to_repair.py",
    "benchmarks/project_generation_v1/run_trimmed_case_debug.py",
    "scripts/build_pass2_evidence_bundle.py",
    "scripts/build_pass2_test_inventory.py",
    "scripts/capture_pass2_recovery_evidence.py",
    "scripts/run_function_stress_pass.py",
    "scripts/run_pass2_operational_closure.py",
    "tests/test_function_stress_runner.py",
    "tests/test_pass2_operational_closure.py",
    "project_management/summaries/ITER-099-function-stress-first-pass.md",
    "project_management/summaries/ITER-100-pass2-functional-closure.md",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run_git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, timeout=60
    ).stdout


def redact(value: str) -> str:
    value = re.sub(r"(?i)(api[_-]?key|authorization|bearer|token|secret)(\s*[:=]\s*)[^\s,;\"']+", r"\1\2***REDACTED***", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_.-]{8,}", "sk-***REDACTED***", value)
    value = re.sub(r"(?i)C:\\Users\\[^\\\s\"]+", "%USERPROFILE%", value)
    return value


def text_diff_for_untracked(paths: Iterable[str]) -> str:
    chunks: list[str] = []
    for relative in paths:
        path = ROOT / relative
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        chunks.extend(difflib.unified_diff([], lines, fromfile="/dev/null", tofile=f"b/{relative}"))
    return "".join(chunks)


def source_identity() -> dict[str, object]:
    tracked = run_git("ls-files", "-z").decode("utf-8", errors="replace").split("\0")
    untracked = run_git("ls-files", "--others", "--exclude-standard", "-z").decode("utf-8", errors="replace").split("\0")
    excluded_prefixes = (".cgkn/", "artifacts/", "cgkn-function-stress-pass/pass2-functional-closure/")
    excluded_names = {"CODEX_PASS2_FUNCTIONAL_CLOSURE.md"}
    paths = sorted(
        path
        for path in [*tracked, *untracked]
        if path
        and path not in excluded_names
        and not path.startswith(excluded_prefixes)
        and "/__pycache__/" not in path
        and not path.endswith((".pyc", ".log"))
        and (ROOT / path).is_file()
    )
    manifest = [
        {
            "path": path,
            "size": (ROOT / path).stat().st_size,
            "sha256": sha256_bytes((ROOT / path).read_bytes()),
        }
        for path in paths
    ]
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    freeze = subprocess.run(
        ["python", "-m", "pip", "freeze"], cwd=ROOT, capture_output=True, text=True, timeout=60
    ).stdout
    return {
        "kind": "CGKNPass2SourceTreeIdentity",
        "head": run_git("rev-parse", "HEAD").decode().strip(),
        "branch": run_git("branch", "--show-current").decode().strip(),
        "source_file_count": len(manifest),
        "source_manifest_sha256": sha256_bytes(manifest_bytes),
        "pytest_config_sha256": sha256_bytes((ROOT / "pytest.ini").read_bytes()),
        "dependency_freeze_sha256": sha256_bytes(freeze.encode("utf-8")),
        "working_diff_sha256": sha256_bytes(run_git("diff", "--no-ext-diff", "--binary")),
        "included_untracked_implementation": [path for path in UNTRACKED_IMPLEMENTATION if (ROOT / path).is_file()],
        "exclusions": ["runtime/artifacts", "local .cgkn state", "pass2 output directory", "user task prompt", "cache/log files"],
    }


def selected_runtime_files() -> list[pathlib.Path]:
    relative = (
        "stress/summary.json",
        "stress/source_identity.json",
        "stress/scheduler_scale.log",
        "stress/recovery_faults.log",
        "stress/surrogate_contract.log",
        "stress/delivery_contract.log",
        "stress/holdout.log",
        "stress/arrival_load/arrival_events.jsonl",
        "stress/arrival_load/arrival_load_summary.json",
        "load-final/arrival_events.jsonl",
        "load-final/arrival_load_summary.json",
        "operational/operational_closure.json",
        "recovery/recovery_isolation_report.json",
        "timeout_skips_explicit.log",
        "pass2_targeted_regression.log",
        "agent_kit_recovery.log",
        "full_suite_last_failed_isolated.log",
    )
    return [RUNTIME / item for item in relative if (RUNTIME / item).is_file()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a redacted pass-2 engineering evidence ZIP")
    parser.add_argument("--result-dir", type=pathlib.Path, default=DEFAULT_RESULT)
    args = parser.parse_args()
    result_dir = args.result_dir.resolve()
    result_dir.mkdir(parents=True, exist_ok=True)
    required = result_dir / "TEST_INVENTORY.json"
    if not required.is_file():
        raise SystemExit("TEST_INVENTORY.json must be finalized before packaging")

    tracked_diff = run_git("diff", "--no-ext-diff", "--binary").decode("utf-8", errors="replace")
    current_diff = redact(tracked_diff + text_diff_for_untracked(UNTRACKED_IMPLEMENTATION))
    (result_dir / "CURRENT_DIFF.patch").write_text(current_diff, encoding="utf-8")
    (result_dir / "SOURCE_TREE_IDENTITY.json").write_text(
        json.dumps(source_identity(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    zip_path = result_dir / "CGKN_PASS2_REDACTED_EVIDENCE.zip"
    candidates = [
        path for path in sorted(result_dir.iterdir())
        if path.is_file() and path != zip_path and path.name != "CONTENT_HASHES.json"
    ]
    hashes: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="cgkn-pass2-evidence-") as temporary:
        stage = pathlib.Path(temporary)
        for source in [*candidates, *selected_runtime_files()]:
            archive_name = source.name if source.parent == result_dir else "raw/" + source.relative_to(RUNTIME).as_posix()
            data = source.read_bytes()
            try:
                sanitized = redact(data.decode("utf-8")).encode("utf-8")
            except UnicodeDecodeError:
                continue
            target = stage / archive_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(sanitized)
            hashes.append({"path": archive_name, "size": len(sanitized), "sha256": sha256_bytes(sanitized)})
        hashes.sort(key=lambda item: str(item["path"]))
        hash_bytes = (json.dumps({"kind": "CGKNPass2EvidenceHashes", "files": hashes}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (stage / "CONTENT_HASHES.json").write_bytes(hash_bytes)
        (result_dir / "CONTENT_HASHES.json").write_bytes(hash_bytes)

        suspicious = []
        for path in stage.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"\bsk-[A-Za-z0-9_.-]{8,}|(api[_-]?key|authorization|bearer|secret)\s*[:=]\s*(?!\*\*\*REDACTED)", text, flags=re.IGNORECASE):
                suspicious.append(path.relative_to(stage).as_posix())
        if suspicious:
            raise SystemExit(f"secret-like content remains after redaction: {suspicious}")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in sorted(item for item in stage.rglob("*") if item.is_file()):
                bundle.write(path, path.relative_to(stage).as_posix())
    print(json.dumps({"zip": str(zip_path), "files": len(hashes) + 1, "sha256": sha256_bytes(zip_path.read_bytes())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
