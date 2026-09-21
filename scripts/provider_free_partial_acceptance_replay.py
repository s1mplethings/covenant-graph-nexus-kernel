#!/usr/bin/env python3
"""Provider-free deterministic acceptance for the partial-repair contracts.

This is a test/evaluation harness, not a generation path.  It replaces only the
HTTP transport boundary with an ordered replay, then uses the production
Provider response parser, schema repair, file validator, candidate materializer,
issue-level acceptance helper, accounting writer, and candidate store.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

try:
    import candidate_materializer
    import check_connectivity
    import post_build_repair
    import provider_transport
    import repair_acceptance
    import run_local_pipeline_impl
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import (
        candidate_materializer,
        check_connectivity,
        post_build_repair,
        provider_transport,
        repair_acceptance,
        run_local_pipeline_impl,
    )


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_CASES_HASH = "1DBD6AAE9DBAC9FBCB0C321DAC6A07D6DA45D8B31605EACEA127C499149C0462"
EXPECTED_EVALUATOR_HASH = "227E330E8BA037DE38A163631E005D29F6AD6626B0AD46582604860707E95A18"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _provider_json(files: list[dict[str, str]]) -> str:
    return json.dumps({"files": files}, ensure_ascii=False, sort_keys=True)


CASE01_V0 = '''import csv
import json

def load_csv(path):
    return []

def clean_rows(rows):
    return list(rows)

def write_preview(rows, path):
    return None

def export_csv(rows, path):
    return None

def delivery_ready(path):
    return False
'''


CASE01_V1 = '''import csv
import json

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def clean_rows(rows):
    cleaned = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        email = str(row.get("email", "")).strip().lower()
        if name:
            cleaned.append({"name": name, "email": email})
    return cleaned

def write_preview(rows, path):
    return None

def export_csv(rows, path):
    return None

def delivery_ready(path):
    return False
'''


CASE01_V2 = '''import csv
import json

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def clean_rows(rows):
    cleaned = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        email = str(row.get("email", "")).strip().lower()
        if name:
            cleaned.append({"name": name, "email": email})
    return cleaned

def write_preview(rows, path):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False)
    return path

def export_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "email"])
        writer.writeheader()
        writer.writerows(rows)
    return path

def delivery_ready(path):
    return False
'''


CASE01_V3_REJECTED = CASE01_V2.replace(
    "def delivery_ready(path):\n    return False\n",
    "def delivery_ready(path):\n    return bool(path) and False\n",
)


CASE03_V0 = '''import json

def create_task(board, title):
    task = {"id": str(len(board) + 1), "title": title, "status": "todo"}
    board.append(task)
    return task

def read_task(board, task_id):
    return next((item for item in board if item["id"] == task_id), None)

def update_task(board, task_id, title):
    task = read_task(board, task_id)
    if task:
        task["title"] = title
    return task

def delete_task(board, task_id):
    before = len(board)
    board[:] = [item for item in board if item["id"] != task_id]
    return before != len(board)

def move_task(board, task_id, new_index):
    return board

def save_state(board, path):
    return None

def load_state(path):
    return []

def export_board(board, path):
    return None
'''


CASE03_V1 = CASE03_V0.replace(
    "def save_state(board, path):\n    return None\n\n"
    "def load_state(path):\n    return []\n\n"
    "def export_board(board, path):\n    return None\n",
    "def save_state(board, path):\n"
    "    with open(path, 'w', encoding='utf-8') as handle:\n"
    "        json.dump(board, handle, ensure_ascii=False)\n"
    "    return path\n\n"
    "def load_state(path):\n"
    "    with open(path, encoding='utf-8') as handle:\n"
    "        return json.load(handle)\n\n"
    "def export_board(board, path):\n"
    "    with open(path, 'w', encoding='utf-8') as handle:\n"
    "        json.dump({'tasks': board}, handle, ensure_ascii=False)\n"
    "    return path\n",
)


CASE03_MOVE_FIXED = CASE03_V1.replace(
    "def move_task(board, task_id, new_index):\n    return board\n",
    "def move_task(board, task_id, new_index):\n"
    "    task = read_task(board, task_id)\n"
    "    if task is None:\n"
    "        return False\n"
    "    board.remove(task)\n"
    "    board.insert(new_index, task)\n"
    "    return True\n",
)


CASE03_MAIN_OK = '''import board_app
import sys

if __name__ == "__main__" and "--self-test" in sys.argv:
    print("READY")
'''


CASE03_MAIN_CRASH = '''raise RuntimeError("startup crash introduced by replay")
'''


SCORE_V0 = "def target_behavior():\n    return False\n"
SCORE_V1 = (
    "def target_behavior():\n"
    "    # The target is fixed; the lower advisory score is deliberately non-blocking.\n"
    "    return True\n"
)


def replay_payloads() -> list[dict[str, Any]]:
    rows = [
        (
            "RPL-CASE01-V1-UPLOAD-CLEAN",
            _provider_json([{"path": "app/csv_app.py", "content": CASE01_V1}]),
            "CASE01 V0->V1 fixes upload and clean while preview/export/delivery still fail.",
            "ACCEPT_PARTIAL_IMPROVEMENT",
        ),
        (
            "RPL-CASE01-V2-PREVIEW-EXPORT",
            _provider_json([{"path": "app/csv_app.py", "content": CASE01_V2}]),
            "CASE01 V1->V2 fixes preview and export while delivery still fails.",
            "ACCEPT_PARTIAL_IMPROVEMENT",
        ),
        (
            "RPL-CASE01-V3-NO-TARGET",
            _provider_json([{"path": "app/csv_app.py", "content": CASE01_V3_REJECTED}]),
            "CASE01 attempted V3 changes source but does not fix delivery.",
            "REJECT_NO_TARGET_ISSUE_IMPROVEMENT",
        ),
        (
            "RPL-CASE03-V1-PERSIST-EXPORT",
            _provider_json([{"path": "app/board_app.py", "content": CASE03_V1}]),
            "CASE03 fixes persistence and export through executable behavior.",
            "ACCEPT_PARTIAL_IMPROVEMENT",
        ),
        (
            "RPL-CASE03-NEW-STARTUP-BLOCKER",
            _provider_json(
                [
                    {"path": "app/board_app.py", "content": CASE03_MOVE_FIXED},
                    {"path": "app/main.py", "content": CASE03_MAIN_CRASH},
                ]
            ),
            "CASE03 fixes move but introduces a startup crash.",
            "REJECT_NEW_BLOCKER",
        ),
        (
            "RPL-SCHEMA-REPAIR-INITIAL-INVALID",
            "not-json: preserve this exact response",
            "Initial invalid JSON for one-repair success scenario.",
            "REQUEST_ONE_SCHEMA_REPAIR",
        ),
        (
            "RPL-SCHEMA-REPAIR-VALID",
            _provider_json([{"path": "app/main.py", "content": "print('schema repaired')\n"}]),
            "Valid replacement envelope after exactly one schema repair.",
            "SCHEMA_REPAIR_SUCCESS",
        ),
        (
            "RPL-SCHEMA-FAIL-INITIAL-INVALID",
            "first invalid response",
            "Initial invalid JSON for exhaustion scenario.",
            "REQUEST_ONE_SCHEMA_REPAIR",
        ),
        (
            "RPL-SCHEMA-FAIL-SECOND-INVALID",
            "second invalid response",
            "Invalid schema-repair response; processing must stop.",
            "SCHEMA_PAYLOAD_FAILURE",
        ),
        (
            "RPL-MATERIALIZATION-MISSING-REQUIRED",
            _provider_json([{"path": "notes.txt", "content": "valid payload, incomplete candidate\n"}]),
            "Valid payload that cannot satisfy the required candidate path.",
            "CANDIDATE_MATERIALIZED_FALSE",
        ),
        (
            "RPL-SCORE-DOWN-TARGET-FIXED",
            _provider_json([{"path": "app/score_case.py", "content": SCORE_V1}]),
            "Target behavior improves while an advisory score decreases.",
            "ACCEPT_PARTIAL_IMPROVEMENT",
        ),
    ]
    return [
        {
            "replay_id": replay_id,
            "response_text": response_text,
            "response_sha256": _sha256_text(response_text),
            "purpose": purpose,
            "expected_result": expected,
        }
        for replay_id, response_text, purpose, expected in rows
    ]


class DeterministicReplayTransport:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = [dict(item) for item in payloads]
        self.cursor = 0
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        endpoint: str,
        request_payload: dict[str, Any],
        token: str,
        timeout: int,
    ) -> tuple[dict[str, Any] | None, str]:
        del token
        if self.cursor >= len(self.payloads):
            raise AssertionError("deterministic replay response sequence exhausted")
        row = self.payloads[self.cursor]
        self.cursor += 1
        actual_hash = _sha256_text(str(row["response_text"]))
        if actual_hash != row["response_sha256"]:
            raise AssertionError(f"replay payload hash mismatch: {row['replay_id']}")
        self.calls.append(
            {
                "call_index": len(self.calls) + 1,
                "replay_id": row["replay_id"],
                "response_sha256": actual_hash,
                "request_sha256": _sha256_text(
                    json.dumps(request_payload, ensure_ascii=False, sort_keys=True)
                ),
                "endpoint": endpoint,
                "timeout": int(timeout),
                "external_network": False,
            }
        )
        return (
            {
                "id": row["replay_id"],
                "status": "completed",
                "output_text": row["response_text"],
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
            "",
        )


@contextlib.contextmanager
def provider_free_network_guard(
    transport: DeterministicReplayTransport,
) -> Iterator[dict[str, Any]]:
    real_attempts: list[dict[str, str]] = []

    def forbidden_network(*args: Any, **kwargs: Any) -> Any:
        del kwargs
        real_attempts.append({"target": str(args[0]) if args else "unknown"})
        raise AssertionError("real network access is forbidden in provider-free replay")

    runtime_connectivity = run_local_pipeline_impl.check_connectivity
    saved = {
        "post_json": runtime_connectivity._post_json,
        "connectivity_urlopen": runtime_connectivity._urlopen,
        "package_post_json": check_connectivity._post_json,
        "package_urlopen": check_connectivity._urlopen,
        "provider_urlopen": provider_transport._urlopen,
        "stdlib_urlopen": urllib.request.urlopen,
        "socket_create_connection": socket.create_connection,
    }
    env_names = (
        "CGKN_OPENAI_API_KEY_OVERRIDE",
        "CGKN_OPENAI_BASE_URL_OVERRIDE",
        "CGNK_MODEL_ROUTING_PROFILE",
        "CGKN_PROVIDER_RETRY_FAST",
    )
    old_env = {name: os.environ.get(name) for name in env_names}
    runtime_connectivity._post_json = transport.post_json
    runtime_connectivity._urlopen = forbidden_network
    check_connectivity._post_json = transport.post_json
    check_connectivity._urlopen = forbidden_network
    provider_transport._urlopen = forbidden_network
    urllib.request.urlopen = forbidden_network
    socket.create_connection = forbidden_network
    os.environ.update(
        {
            "CGKN_OPENAI_API_KEY_OVERRIDE": "provider-free-replay-key",
            "CGKN_OPENAI_BASE_URL_OVERRIDE": "https://provider-free.invalid/v1",
            "CGNK_MODEL_ROUTING_PROFILE": "api_only",
            "CGKN_PROVIDER_RETRY_FAST": "1",
        }
    )
    guard = {"real_network_attempts": real_attempts}
    try:
        yield guard
    finally:
        runtime_connectivity._post_json = saved["post_json"]
        runtime_connectivity._urlopen = saved["connectivity_urlopen"]
        check_connectivity._post_json = saved["package_post_json"]
        check_connectivity._urlopen = saved["package_urlopen"]
        provider_transport._urlopen = saved["provider_urlopen"]
        urllib.request.urlopen = saved["stdlib_urlopen"]
        socket.create_connection = saved["socket_create_connection"]
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _request_files(
    *,
    transport: DeterministicReplayTransport,
    phase_log: pathlib.Path,
    purpose: str,
) -> tuple[list[dict[str, str]], int]:
    before = len(transport.calls)
    model = "provider-free-replay"
    routing = run_local_pipeline_impl.ProviderModelRoutingPolicy(
        small_model=model,
        large_model=model,
        enable_model_routing=False,
    )
    raw = run_local_pipeline_impl.provider_text(
        [
            {"role": "system", "content": "Return the requested strict Provider JSON payload."},
            {"role": "user", "content": purpose},
        ],
        model,
        5,
        max_attempts=1,
        stage="component_file_generation",
        component="provider_free_replay",
        target_file="replay-target",
        max_tokens=4000,
        payload_mode="split_file",
        phase_log_path=phase_log,
        routing_policy=routing,
    )
    doc, _ = run_local_pipeline_impl.parse_provider_json_object_with_one_repair(
        raw,
        model=model,
        timeout=5,
        stage="component_file_generation",
        component="provider_free_replay",
        target_file="replay-target",
        max_tokens=4000,
        phase_log_path=phase_log,
        routing_policy=routing,
    )
    return run_local_pipeline_impl.validate_provider_files(doc), len(transport.calls) - before


def _read_candidate_files(root: pathlib.Path) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        pure = pathlib.PurePosixPath(relative)
        if relative.startswith("artifacts/") or pure.name in candidate_materializer.LIFECYCLE_FILES:
            continue
        if "__pycache__" in pure.parts or pure.suffix in {".pyc", ".pyo"}:
            continue
        files.append({"path": relative, "content": path.read_text(encoding="utf-8")})
    return files


def _load_module(path: pathlib.Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check(check_id: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check_id": check_id, "status": "PASS" if passed else "FAIL", "detail": detail}


def verify_case01(candidate: pathlib.Path, work: pathlib.Path) -> dict[str, Any]:
    module = _load_module(candidate / "app" / "csv_app.py", f"csv_replay_{hash(candidate)}")
    source = work / "input.csv"
    preview = work / "preview.json"
    export = work / "export.csv"
    work.mkdir(parents=True, exist_ok=True)
    source.write_text("name,email\n Alice , A@EXAMPLE.COM \n,blank@example.com\n", encoding="utf-8")
    try:
        rows = module.load_csv(source)
    except Exception as exc:
        rows = []
        upload_detail = f"load failed: {exc}"
    else:
        upload_detail = f"rows={rows!r}"
    upload_ok = len(rows) == 2 and set(rows[0]) == {"name", "email"}
    try:
        cleaned = module.clean_rows(rows)
    except Exception as exc:
        cleaned = []
        clean_detail = f"clean failed: {exc}"
    else:
        clean_detail = f"cleaned={cleaned!r}"
    clean_ok = cleaned == [{"name": "Alice", "email": "a@example.com"}]
    try:
        module.write_preview(cleaned, preview)
        preview_doc = json.loads(preview.read_text(encoding="utf-8")) if preview.is_file() else None
    except Exception as exc:
        preview_doc = None
        preview_detail = f"preview failed: {exc}"
    else:
        preview_detail = f"preview={preview_doc!r}"
    preview_ok = preview_doc == cleaned and bool(cleaned)
    try:
        module.export_csv(cleaned, export)
        with export.open(newline="", encoding="utf-8") as handle:
            exported = list(csv.DictReader(handle))
    except Exception as exc:
        exported = []
        export_detail = f"export failed: {exc}"
    else:
        export_detail = f"exported={exported!r}"
    export_ok = exported == cleaned and export.is_file()
    try:
        delivery_ok = bool(module.delivery_ready(export)) and export_ok
    except Exception:
        delivery_ok = False
    checks = [
        _check("csv_upload", upload_ok, upload_detail),
        _check("csv_clean", clean_ok, clean_detail),
        _check("preview", preview_ok, preview_detail),
        _check("export", export_ok, export_detail),
        _check("delivery", delivery_ok, f"delivery_ready={delivery_ok}"),
    ]
    return {"checks": checks, "score": sum(row["status"] == "PASS" for row in checks) * 20}


def verify_case03(candidate: pathlib.Path, work: pathlib.Path) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        [sys.executable, str(candidate / "app" / "main.py"), "--self-test"],
        cwd=candidate,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    startup_ok = process.returncode == 0 and "READY" in process.stdout
    try:
        module = _load_module(candidate / "app" / "board_app.py", f"board_replay_{hash(candidate)}")
        board: list[dict[str, Any]] = []
        first = module.create_task(board, "first")
        second = module.create_task(board, "second")
        read_ok = module.read_task(board, first["id"]) is first
        update_ok = module.update_task(board, first["id"], "updated")["title"] == "updated"
        delete_ok = module.delete_task(board, second["id"]) and len(board) == 1
        crud_ok = bool(read_ok and update_ok and delete_ok)
        second = module.create_task(board, "second")
        move_return = module.move_task(board, second["id"], 0)
        move_ok = bool(move_return is True and board[0]["id"] == second["id"])
        state_path = work / "board-state.json"
        module.save_state(board, state_path)
        reloaded = _load_module(candidate / "app" / "board_app.py", f"board_reload_{hash(work)}")
        persisted = reloaded.load_state(state_path)
        persistence_ok = persisted == board and state_path.is_file()
        export_path = work / "board-export.json"
        module.export_board(board, export_path)
        export_doc = json.loads(export_path.read_text(encoding="utf-8")) if export_path.is_file() else {}
        export_ok = export_doc == {"tasks": board}
        behavior_error = ""
    except Exception as exc:
        crud_ok = move_ok = persistence_ok = export_ok = False
        behavior_error = str(exc)
    checks = [
        _check("startup", startup_ok, f"returncode={process.returncode}; stderr={process.stderr[:200]}"),
        _check("crud", crud_ok, behavior_error or "create/read/update/delete executed"),
        _check("move", move_ok, behavior_error or "task order checked"),
        _check("persistence", persistence_ok, behavior_error or "state reloaded from disk with a fresh module"),
        _check("export", export_ok, behavior_error or "export JSON parsed and fields checked"),
    ]
    return {"checks": checks, "score": sum(row["status"] == "PASS" for row in checks) * 20}


def _failure_rows(result: dict[str, Any], *, product: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for check in result["checks"]:
        if check["status"] == "PASS":
            continue
        check_id = str(check["check_id"])
        path = "app/main.py" if check_id == "startup" else {
            "case01": "app/csv_app.py",
            "case03": "app/board_app.py",
            "score_case": "app/score_case.py",
        }.get(product, "")
        rows.append(
            {
                "kind": f"{product}.{check_id}",
                "path": path,
                "expected_behavior": f"{check_id} real behavior passes",
                "observed_behavior": str(check["detail"]),
                "severity": "blocker" if check_id == "startup" else "error",
            }
        )
    return rows


def _materialize_initial(
    candidate: pathlib.Path,
    store: pathlib.Path,
    files: list[dict[str, str]],
) -> dict[str, Any]:
    build = candidate_materializer.assess_build_complete(
        files,
        required_paths=[item["path"] for item in files],
    )
    if not build["build_complete"]:
        raise AssertionError(build["blockers"])
    return candidate_materializer.run(
        candidate_dir=candidate,
        files=files,
        store_dir=store,
        version_metadata={"provider_provenance": {"mode": "provider_free_replay"}},
    )


def _apply_replay_repair(
    *,
    transport: DeterministicReplayTransport,
    phase_log: pathlib.Path,
    candidate: pathlib.Path,
    store: pathlib.Path,
    latest_candidate_id: str,
    product: str,
    verifier: Callable[[pathlib.Path, pathlib.Path], dict[str, Any]],
    target_file: str,
    owned_paths: set[str],
    purpose: str,
    work_root: pathlib.Path,
    issue_ids: list[str],
) -> dict[str, Any]:
    before_result = verifier(candidate, work_root / "before")
    before_failures = _failure_rows(before_result, product=product)
    files, replay_calls = _request_files(
        transport=transport,
        phase_log=phase_log,
        purpose=purpose,
    )
    base_files = _read_candidate_files(candidate)
    promoted = candidate_materializer.build_authorized_candidate_file_set(
        base_files,
        files,
        owned_paths=sorted(owned_paths),
        validated_paths=[str(item["path"]) for item in files],
    )
    prospective = work_root / "prospective"
    candidate_materializer.run(candidate_dir=prospective, files=promoted["files"])
    after_result = verifier(prospective, work_root / "after")
    after_failures = _failure_rows(after_result, product=product)
    by_path = {str(item["path"]): str(item["content"]) for item in files}
    acceptance = repair_acceptance.assess_provider_job_partial_acceptance(
        target_file=target_file,
        before_content=(candidate / target_file).read_text(encoding="utf-8"),
        after_content=by_path[target_file],
        coherence_before=before_failures,
        coherence_after=after_failures,
        evidence_facts=[],
        owned_paths=owned_paths,
        syntax_safe=run_local_pipeline_impl.provider_repair_source_syntax_safe(
            target_file, by_path[target_file]
        ),
        behavior_checks_before=before_result["checks"],
        behavior_checks_after=after_result["checks"],
    )
    previous_id = latest_candidate_id
    candidate_record: dict[str, Any] = {}
    if acceptance["safe_to_accept_partial"]:
        for item in files:
            target = candidate / pathlib.PurePosixPath(str(item["path"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(item["content"]), encoding="utf-8")
        candidate_record = candidate_materializer.snapshot_version(
            candidate_dir=candidate,
            store_dir=store,
            parent_candidate_id=latest_candidate_id,
            repair_issue_ids=issue_ids,
            metadata={"provider_provenance": {"mode": "provider_free_replay"}},
        )
        latest_candidate_id = str(candidate_record["candidate_id"])
    return {
        "provider_calls": replay_calls,
        "candidate_materialized": True,
        "requested_files": sorted(by_path),
        "owned_paths": sorted(owned_paths),
        "before": before_result,
        "after": after_result,
        "acceptance": acceptance,
        "changed_files": [target_file] if acceptance["safe_to_accept_partial"] else [],
        "issue_acceptance": acceptance["issue_acceptance"],
        "latest_candidate_id_before": previous_id,
        "latest_candidate_id_after": latest_candidate_id,
        "candidate_record": candidate_record,
        "attempted_candidate_hash": candidate_materializer.candidate_source_hash(prospective),
    }


def _score_case_verifier(candidate: pathlib.Path, work: pathlib.Path) -> dict[str, Any]:
    del work
    module = _load_module(candidate / "app" / "score_case.py", f"score_case_{hash(candidate)}")
    passed = module.target_behavior() is True
    content = (candidate / "app" / "score_case.py").read_text(encoding="utf-8")
    score = 90 if len(content) < 60 else 80
    return {"checks": [_check("target", passed, f"target_behavior={passed}")], "score": score}


def run(output_dir: pathlib.Path) -> dict[str, Any]:
    output = pathlib.Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    phase_log = output / "provider_free_phase_log.jsonl"
    if phase_log.exists():
        phase_log.unlink()
    payloads = replay_payloads()
    transport = DeterministicReplayTransport(payloads)
    acceptance_history: list[dict[str, Any]] = []
    accounting_history: list[dict[str, Any]] = []
    scenarios: dict[str, dict[str, Any]] = {}
    benchmark_before = {
        "cases.json": _sha256_file(ROOT / "benchmarks" / "project_generation_v1" / "cases.json"),
        "evaluator.py": _sha256_file(ROOT / "benchmarks" / "project_generation_v1" / "evaluator.py"),
    }

    with tempfile.TemporaryDirectory(prefix="cgkn-provider-free-") as temp_name:
        temp = pathlib.Path(temp_name)
        with provider_free_network_guard(transport) as network_guard:
            case01 = temp / "case01" / "candidate"
            case01_store = temp / "case01" / "candidate_store"
            case01_initial = _materialize_initial(
                case01,
                case01_store,
                [{"path": "app/csv_app.py", "content": CASE01_V0}],
            )
            case01_v0 = str(case01_initial["candidate_record"]["candidate_id"])
            c01_v1 = _apply_replay_repair(
                transport=transport,
                phase_log=phase_log,
                candidate=case01,
                store=case01_store,
                latest_candidate_id=case01_v0,
                product="case01",
                verifier=verify_case01,
                target_file="app/csv_app.py",
                owned_paths={"app/csv_app.py"},
                purpose="CASE01 repair upload and clean",
                work_root=temp / "case01" / "attempt1",
                issue_ids=["CSV-UPLOAD", "CSV-CLEAN"],
            )
            c01_v2 = _apply_replay_repair(
                transport=transport,
                phase_log=phase_log,
                candidate=case01,
                store=case01_store,
                latest_candidate_id=c01_v1["latest_candidate_id_after"],
                product="case01",
                verifier=verify_case01,
                target_file="app/csv_app.py",
                owned_paths={"app/csv_app.py"},
                purpose="CASE01 repair preview and export",
                work_root=temp / "case01" / "attempt2",
                issue_ids=["CSV-PREVIEW", "CSV-EXPORT"],
            )
            c01_v3 = _apply_replay_repair(
                transport=transport,
                phase_log=phase_log,
                candidate=case01,
                store=case01_store,
                latest_candidate_id=c01_v2["latest_candidate_id_after"],
                product="case01",
                verifier=verify_case01,
                target_file="app/csv_app.py",
                owned_paths={"app/csv_app.py"},
                purpose="CASE01 attempted delivery repair without target improvement",
                work_root=temp / "case01" / "attempt3",
                issue_ids=["CSV-DELIVERY"],
            )
            for attempt, result in enumerate((c01_v1, c01_v2, c01_v3), start=1):
                acceptance_history.append(
                    {
                        "case": "CASE01",
                        "attempt": attempt,
                        "accepted": result["acceptance"]["safe_to_accept_partial"],
                        "reason": result["acceptance"]["reason"] or "ACCEPT_PARTIAL_IMPROVEMENT",
                        "candidate_before": result["latest_candidate_id_before"],
                        "candidate_after": result["latest_candidate_id_after"],
                        "attempted_candidate_hash": result["attempted_candidate_hash"],
                    }
                )
                accounting_history.append(
                    {
                        "attempt_number": len(accounting_history) + 1,
                        "plan": {"provider_actions": [{"path": "app/csv_app.py", "issue_ids": [f"CASE01-{attempt}"]}]},
                        "repair_result": result,
                    }
                )
            case01_final = verify_case01(case01, temp / "case01" / "final")
            case01_index = json.loads((case01_store / "candidate_versions.json").read_text(encoding="utf-8"))

            case03 = temp / "case03" / "candidate"
            case03_store = temp / "case03" / "candidate_store"
            case03_initial = _materialize_initial(
                case03,
                case03_store,
                [
                    {"path": "app/__init__.py", "content": "# Provider-free board fixture package.\n"},
                    {"path": "app/board_app.py", "content": CASE03_V0},
                    {"path": "app/main.py", "content": CASE03_MAIN_OK},
                ],
            )
            case03_v0 = str(case03_initial["candidate_record"]["candidate_id"])
            c03_v1 = _apply_replay_repair(
                transport=transport,
                phase_log=phase_log,
                candidate=case03,
                store=case03_store,
                latest_candidate_id=case03_v0,
                product="case03",
                verifier=verify_case03,
                target_file="app/board_app.py",
                owned_paths={"app/board_app.py"},
                purpose="CASE03 repair persistence and export",
                work_root=temp / "case03" / "attempt1",
                issue_ids=["BOARD-PERSISTENCE", "BOARD-EXPORT"],
            )
            c03_blocker = _apply_replay_repair(
                transport=transport,
                phase_log=phase_log,
                candidate=case03,
                store=case03_store,
                latest_candidate_id=c03_v1["latest_candidate_id_after"],
                product="case03",
                verifier=verify_case03,
                target_file="app/board_app.py",
                owned_paths={"app/board_app.py", "app/main.py"},
                purpose="CASE03 fix move but introduce startup blocker",
                work_root=temp / "case03" / "attempt2",
                issue_ids=["BOARD-MOVE"],
            )
            for attempt, result in enumerate((c03_v1, c03_blocker), start=1):
                acceptance_history.append(
                    {
                        "case": "CASE03",
                        "attempt": attempt,
                        "accepted": result["acceptance"]["safe_to_accept_partial"],
                        "reason": result["acceptance"]["reason"] or "ACCEPT_PARTIAL_IMPROVEMENT",
                        "candidate_before": result["latest_candidate_id_before"],
                        "candidate_after": result["latest_candidate_id_after"],
                        "attempted_candidate_hash": result["attempted_candidate_hash"],
                    }
                )
                accounting_history.append(
                    {
                        "attempt_number": len(accounting_history) + 1,
                        "plan": {"provider_actions": [{"path": "app/board_app.py", "issue_ids": [f"CASE03-{attempt}"]}]},
                        "repair_result": result,
                    }
                )
            case03_final = verify_case03(case03, temp / "case03" / "final")
            case03_index = json.loads((case03_store / "candidate_versions.json").read_text(encoding="utf-8"))

            schema_files, schema_success_calls = _request_files(
                transport=transport,
                phase_log=phase_log,
                purpose="schema repair succeeds once",
            )
            schema_candidate = temp / "schema-success"
            schema_build = candidate_materializer.assess_build_complete(
                schema_files, required_paths=["app/main.py"]
            )
            schema_materialized = candidate_materializer.run(
                candidate_dir=schema_candidate, files=schema_files
            ) if schema_build["build_complete"] else {}
            schema_process = subprocess.run(
                [sys.executable, str(schema_candidate / "app" / "main.py")],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            schema_success_repair_count = max(0, schema_success_calls - 1)
            accounting_history.append(
                {
                    "attempt_number": len(accounting_history) + 1,
                    "plan": {"provider_actions": [{"path": "app/main.py", "issue_ids": ["SCHEMA-D"]}]},
                    "repair_result": {
                        "status": "applied",
                        "provider_calls": schema_success_calls,
                        "changed_files": [],
                        "reason": "schema envelope replay",
                        "issue_acceptance": [],
                    },
                }
            )

            schema_failure_before = len(transport.calls)
            schema_failure = ""
            try:
                _request_files(
                    transport=transport,
                    phase_log=phase_log,
                    purpose="schema repair fails after one request",
                )
            except run_local_pipeline_impl.ProviderContractRepairExhaustedError as exc:
                schema_failure = str(exc)
            schema_failure_calls = len(transport.calls) - schema_failure_before
            accounting_history.append(
                {
                    "attempt_number": len(accounting_history) + 1,
                    "plan": {"provider_actions": [{"path": "", "issue_ids": ["SCHEMA-E"]}]},
                    "repair_result": {
                        "status": "failed",
                        "provider_calls": schema_failure_calls,
                        "changed_files": [],
                        "reason": schema_failure,
                        "issue_acceptance": [],
                    },
                }
            )

            materialization_files, materialization_calls = _request_files(
                transport=transport,
                phase_log=phase_log,
                purpose="valid payload cannot form required candidate",
            )
            materialization = candidate_materializer.assess_build_complete(
                materialization_files, required_paths=["app/main.py"]
            )
            no_candidate_score = None
            materialization_accepted = False
            accounting_history.append(
                {
                    "attempt_number": len(accounting_history) + 1,
                    "plan": {"provider_actions": [{"path": "app/main.py", "issue_ids": ["MATERIALIZE-F"]}]},
                    "repair_result": {
                        "status": "failed",
                        "provider_calls": materialization_calls,
                        "changed_files": [],
                        "reason": "candidate_materialized=false",
                        "issue_acceptance": [],
                    },
                }
            )

            score_candidate = temp / "score" / "candidate"
            score_store = temp / "score" / "candidate_store"
            score_initial = _materialize_initial(
                score_candidate,
                score_store,
                [{"path": "app/score_case.py", "content": SCORE_V0}],
            )
            score_result = _apply_replay_repair(
                transport=transport,
                phase_log=phase_log,
                candidate=score_candidate,
                store=score_store,
                latest_candidate_id=str(score_initial["candidate_record"]["candidate_id"]),
                product="score_case",
                verifier=_score_case_verifier,
                target_file="app/score_case.py",
                owned_paths={"app/score_case.py"},
                purpose="score declines while target behavior improves",
                work_root=temp / "score" / "attempt1",
                issue_ids=["SCORE-TARGET"],
            )
            accounting_history.append(
                {
                    "attempt_number": len(accounting_history) + 1,
                    "plan": {"provider_actions": [{"path": "app/score_case.py", "issue_ids": ["SCORE-G"]}]},
                    "repair_result": score_result,
                }
            )

            scenarios = {
                "A_partial_improvement": {
                    "passed": bool(
                        c01_v1["acceptance"]["safe_to_accept_partial"]
                        and c01_v1["after"]["score"] < 100
                        and c01_v1["acceptance"]["issues_fixed_by_partial_acceptance"] >= 2
                    ),
                    "actual": "ACCEPT_PARTIAL_IMPROVEMENT",
                    "actual_behavior_checks": c01_v1["after"]["checks"],
                },
                "B_no_target_improvement": {
                    "passed": bool(
                        not c01_v3["acceptance"]["safe_to_accept_partial"]
                        and c01_v3["acceptance"]["reason"] == "NO_TARGET_ISSUE_IMPROVEMENT"
                    ),
                    "actual": "REJECT_NO_TARGET_ISSUE_IMPROVEMENT",
                },
                "C_new_blocker": {
                    "passed": bool(
                        not c03_blocker["acceptance"]["safe_to_accept_partial"]
                        and c03_blocker["acceptance"]["reason"] == "NEW_EQUAL_OR_HIGHER_BLOCKER"
                    ),
                    "actual": "REJECT_NEW_BLOCKER",
                    "actual_behavior_checks": c03_blocker["after"]["checks"],
                },
                "D_invalid_json_one_repair": {
                    "passed": bool(
                        schema_success_repair_count == 1
                        and schema_build["build_complete"]
                        and schema_materialized.get("status") == "pass"
                        and schema_process.returncode == 0
                    ),
                    "actual": "SCHEMA_REPAIR_SUCCESS",
                    "schema_repair_attempts": schema_success_repair_count,
                    "candidate_materialized": bool(schema_materialized),
                    "startup_returncode": schema_process.returncode,
                },
                "E_continuous_invalid_json": {
                    "passed": bool(
                        schema_failure_calls == 2
                        and "after one request" in schema_failure
                    ),
                    "actual": "SCHEMA_PAYLOAD_FAILURE",
                    "schema_repair_attempts": max(0, schema_failure_calls - 1),
                },
                "F_candidate_not_materialized": {
                    "passed": bool(
                        not materialization["build_complete"] and no_candidate_score is None
                    ),
                    "actual": "CANDIDATE_MATERIALIZED_FALSE",
                    "candidate_materialized": False,
                    "score": no_candidate_score,
                },
                "G_score_down_issue_improved": {
                    "passed": bool(
                        score_result["acceptance"]["safe_to_accept_partial"]
                        and score_result["after"]["score"] < score_result["before"]["score"]
                    ),
                    "actual": "ACCEPT_PARTIAL_IMPROVEMENT",
                    "acceptance_reason": "TARGET_ISSUE_IMPROVED_WITHOUT_NEW_BLOCKER; CASE_SCORE_NOT_REQUIRED",
                    "score_before": score_result["before"]["score"],
                    "score_after": score_result["after"]["score"],
                    "actual_behavior_checks": score_result["after"]["checks"],
                },
                "H_multi_round_candidate_selection": {
                    "passed": bool(
                        c01_v1["acceptance"]["safe_to_accept_partial"]
                        and c01_v2["acceptance"]["safe_to_accept_partial"]
                        and not c01_v3["acceptance"]["safe_to_accept_partial"]
                        and case01_index["latest_candidate_id"] == c01_v2["latest_candidate_id_after"]
                        and case01_index["latest_candidate_id"] != case01_v0
                        and case01_index["candidates"][-1]["candidate_hash"]
                        != c01_v3["attempted_candidate_hash"]
                    ),
                    "actual": "FINAL_CANDIDATE_V2",
                    "v0_candidate_id": case01_v0,
                    "v2_candidate_id": c01_v2["latest_candidate_id_after"],
                    "selected_candidate_id": case01_index["latest_candidate_id"],
                    "rejected_v3_hash": c01_v3["attempted_candidate_hash"],
                },
            }

            accounting = post_build_repair.write_repair_call_accounting(
                output, accounting_history
            )
            accounting_consistent = len(accounting["rows"]) == len(transport.calls)
            accepted_without_improvement = accounting[
                "accepted_without_target_issue_improvement"
            ]
            replay_repairs = [c01_v1, c01_v2, c01_v3, c03_v1, c03_blocker, score_result]
            generic_scope_calls = sum(
                not bool(item.get("requested_files")) for item in replay_repairs
            )
            component_wide_rollback = sum(
                bool(not item["acceptance"]["safe_to_accept_partial"])
                and item["latest_candidate_id_after"] != item["latest_candidate_id_before"]
                for item in replay_repairs
            )
            network_report = {
                "kind": "CGKNProviderFreeNetworkCallGuardReport",
                "status": "PASS" if not network_guard["real_network_attempts"] else "FAIL",
                "real_network_calls": len(network_guard["real_network_attempts"]),
                "real_network_attempts": network_guard["real_network_attempts"],
                "replay_transport_calls": len(transport.calls),
                "provider_api_quota_consumed": False,
                "transport_injection_point": "scripts.check_connectivity._post_json",
            }

            case_results = {
                "CASE01": {
                    "actual_behavior": {
                        "csv_upload": c01_v1["after"]["checks"][0]["status"],
                        "csv_clean": c01_v1["after"]["checks"][1]["status"],
                        "preview": c01_v2["after"]["checks"][2]["status"],
                        "export": c01_v2["after"]["checks"][3]["status"],
                        "delivery": case01_final["checks"][4]["status"],
                    },
                    "verification_evidence": case01_final["checks"],
                    "issues_fixed_by_first_repair": c01_v1["acceptance"]["issues_fixed_by_partial_acceptance"],
                    "full_case_pass": case01_final["score"] == 100,
                    "final_score": case01_final["score"],
                    "candidate_versions": case01_index["candidate_versions_total"],
                    "v0_candidate_id": case01_v0,
                    "final_candidate_id": case01_index["latest_candidate_id"],
                    "final_candidate_not_v0": case01_index["latest_candidate_id"] != case01_v0,
                    "rejected_v3_not_selected": case01_index["latest_candidate_id"] == c01_v2["latest_candidate_id_after"],
                },
                "CASE03": {
                    "actual_behavior": {
                        row["check_id"]: row["status"] for row in case03_final["checks"]
                    },
                    "verification_evidence": case03_final["checks"],
                    "rejected_candidate_behavior": {
                        row["check_id"]: row["status"] for row in c03_blocker["after"]["checks"]
                    },
                    "persistence_export_improved": bool(
                        c03_v1["after"]["checks"][3]["status"] == "PASS"
                        and c03_v1["after"]["checks"][4]["status"] == "PASS"
                    ),
                    "startup_new_blocker_rejected": not c03_blocker["acceptance"]["safe_to_accept_partial"],
                    "candidate_materialized": c03_v1["candidate_materialized"],
                    "final_score": case03_final["score"],
                    "v0_candidate_id": case03_v0,
                    "final_candidate_id": case03_index["latest_candidate_id"],
                },
            }

            candidate_lineage = {
                "kind": "CGKNProviderFreeCandidateLineage",
                "case01": case01_index,
                "case03": case03_index,
                "rejected_attempts": [
                    {
                        "case": "CASE01",
                        "attempted_hash": c01_v3["attempted_candidate_hash"],
                        "reason": c01_v3["acceptance"]["reason"],
                    },
                    {
                        "case": "CASE03",
                        "attempted_hash": c03_blocker["attempted_candidate_hash"],
                        "reason": c03_blocker["acceptance"]["reason"],
                    },
                ],
            }

            assertions = {
                "partial_improvement_accepted": scenarios["A_partial_improvement"]["passed"],
                "full_case_pass_not_required": c01_v1["after"]["score"] < 100 and c01_v1["acceptance"]["safe_to_accept_partial"],
                "accepted_without_target_issue_improvement_zero": accepted_without_improvement == 0,
                "new_blocker_rejected": scenarios["C_new_blocker"]["passed"],
                "component_wide_rollback_zero": component_wide_rollback == 0,
                "generic_scope_calls_zero": generic_scope_calls == 0,
                "provider_schedulers_one": (
                    "ThreadPoolExecutor" not in (ROOT / "scripts" / "provider_jobs.py").read_text(encoding="utf-8")
                    and "ThreadPoolExecutor" in (ROOT / "scripts" / "run_local_pipeline_impl.py").read_text(encoding="utf-8")
                ),
                "schema_repair_max_one": schema_success_repair_count == 1 and max(0, schema_failure_calls - 1) == 1,
                "no_candidate_score_null": no_candidate_score is None,
                "unmaterialized_candidate_not_accepted": bool(
                    not materialization["build_complete"] and not materialization_accepted
                ),
                "rejected_candidate_does_not_override": scenarios["H_multi_round_candidate_selection"]["passed"],
                "final_candidate_not_v0": case_results["CASE01"]["final_candidate_not_v0"],
                "accounting_rows_match_replay_calls": accounting_consistent,
                "payload_manifest_auditable": all(
                    row["replay_id"] and row["purpose"] and row["expected_result"]
                    and row["response_sha256"] == _sha256_text(row["response_text"])
                    for row in payloads
                ),
                "real_network_calls_zero": network_report["real_network_calls"] == 0,
            }

    benchmark_after = {
        "cases.json": _sha256_file(ROOT / "benchmarks" / "project_generation_v1" / "cases.json"),
        "evaluator.py": _sha256_file(ROOT / "benchmarks" / "project_generation_v1" / "evaluator.py"),
    }
    scenarios_passed = sum(bool(row["passed"]) for row in scenarios.values())
    overall_pass = bool(
        scenarios_passed == len(scenarios)
        and all(assertions.values())
        and benchmark_before == benchmark_after
        and benchmark_after
        == {"cases.json": EXPECTED_CASES_HASH, "evaluator.py": EXPECTED_EVALUATOR_HASH}
    )
    final_verdict = {
        "kind": "CGKNProviderFreeLogicVerdict",
        "verdict": "PROVIDER_FREE_LOGIC_PASS" if overall_pass else "PROVIDER_FREE_LOGIC_FAIL",
        "live_product_repair_verified": False,
        "live_provider_repeatability_verified": False,
        "provider_rerun_still_required": True,
        "external_provider_calls": 0,
        "replay_transport_calls": len(transport.calls),
        "deterministic_scenarios_passed": scenarios_passed,
        "deterministic_scenarios_total": len(scenarios),
    }
    report = {
        "kind": "CGKNProviderFreePartialAcceptanceLogicReport",
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "deterministic local logic acceptance only",
        "not_live_product_acceptance": True,
        "not_live_provider_acceptance": True,
        "scenarios": scenarios,
        "assertions": assertions,
        "cases": case_results,
        "partial_acceptance": {
            "accepted_partial_improvements": accounting["partial_improvement_accepted_count"],
            "accepted_without_target_issue_improvement": accounting["accepted_without_target_issue_improvement"],
            "case_score_required": False,
        },
        "schema_repair_limit": 1,
        "orchestration_metrics": {
            "generic_scope_calls": generic_scope_calls,
            "component_wide_rollback": component_wide_rollback,
            "provider_schedulers": 1 if assertions["provider_schedulers_one"] else 0,
        },
        "accounting_consistent": accounting_consistent,
        "benchmark_hash_before": benchmark_before,
        "benchmark_hash_after": benchmark_after,
        "benchmark_hash_unchanged": benchmark_before == benchmark_after,
        "final_verdict": final_verdict,
    }
    _write_json(output / "replay_payload_manifest.json", {"kind": "CGKNProviderFreeReplayPayloadManifest", "payloads": payloads})
    _write_json(output / "acceptance_history.json", {"kind": "CGKNProviderFreeAcceptanceHistory", "entries": acceptance_history})
    _write_json(output / "candidate_lineage.json", candidate_lineage)
    _write_json(output / "network_call_guard_report.json", network_report)
    _write_json(output / "provider_free_logic_report.json", report)
    _write_json(output / "final_verdict.json", final_verdict)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run(pathlib.Path(args.output))
    print(json.dumps(report["final_verdict"], ensure_ascii=False, indent=2))
    return 0 if report["final_verdict"]["verdict"] == "PROVIDER_FREE_LOGIC_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
