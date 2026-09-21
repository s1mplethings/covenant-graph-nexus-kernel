"""Non-live fixtures used only to prove the benchmark harness itself."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from typing import Any

from .evaluator import candidate_tree_hash, inspect_delivery, make_observation, run_process_probe, utc_now, write_json


CSV_APP = r'''#!/usr/bin/env python3
import argparse
import csv
import json
import pathlib

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args()
    source, target = pathlib.Path(args.input), pathlib.Path(args.output)
    if not source.is_file():
        print(json.dumps({"error": "input_missing"}))
        return 2
    with source.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        print(json.dumps({"error": "empty_csv"}))
        return 2
    header = [cell.strip() for cell in rows[0]]
    seen, clean, malformed, missing_values = set(), [], 0, 0
    for row in rows[1:]:
        if len(row) != len(header):
            malformed += 1
            continue
        normalized = tuple(cell.strip() for cell in row)
        missing_values += sum(not cell for cell in normalized)
        if normalized not in seen:
            seen.add(normalized)
            clean.append(normalized)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(clean)
    print(json.dumps({"input_rows": len(rows)-1, "output_rows": len(clean), "duplicates_removed": len(rows)-1-malformed-len(clean), "malformed_rows": malformed, "missing_values": missing_values, "before_preview": rows[1:3], "after_preview": clean[:2]}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


BOARD_CLI = r'''#!/usr/bin/env python3
import argparse
import json
import pathlib

COLUMNS = {"todo", "doing", "done"}

def load(path):
    if not path.exists():
        return {"cards": []}
    return json.loads(path.read_text(encoding="utf-8"))

def save(path, board):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("add"); add.add_argument("--title", required=True); add.add_argument("--column", default="todo")
    edit = sub.add_parser("edit"); edit.add_argument("--id", required=True); edit.add_argument("--title", required=True)
    move = sub.add_parser("move"); move.add_argument("--id", required=True); move.add_argument("--column", required=True)
    delete = sub.add_parser("delete"); delete.add_argument("--id", required=True)
    sub.add_parser("list")
    export = sub.add_parser("export"); export.add_argument("--output", required=True)
    args = parser.parse_args()
    state = pathlib.Path(args.state); board = load(state)
    if args.action == "add":
        if args.column not in COLUMNS: return 2
        next_id = str(max([int(card["id"]) for card in board["cards"]] + [0]) + 1)
        board["cards"].append({"id": next_id, "title": args.title, "column": args.column}); save(state, board)
        print(next_id)
    elif args.action in {"edit", "move", "delete"}:
        card = next((item for item in board["cards"] if item["id"] == args.id), None)
        if not card: return 3
        if args.action == "edit": card["title"] = args.title
        elif args.action == "move":
            if args.column not in COLUMNS: return 2
            card["column"] = args.column
        else: board["cards"].remove(card)
        save(state, board)
    elif args.action == "export":
        pathlib.Path(args.output).write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(board, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


BOARD_HTML = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Local Project Board</title><link rel="stylesheet" href="styles.css"></head>
<body><header><h1>Project Board</h1><button id="add">Add task</button><button id="export">Export</button></header>
<main id="board"><section><h2>TODO</h2></section><section><h2>DOING</h2></section><section><h2>DONE</h2></section></main>
<script src="app.js"></script></body></html>
'''


BOARD_JS = '''const KEY="project-board";
const load=()=>JSON.parse(localStorage.getItem(KEY)||"[]");
const save=(cards)=>localStorage.setItem(KEY,JSON.stringify(cards));
document.querySelector("#add").addEventListener("click",()=>{const cards=load();cards.push({id:crypto.randomUUID(),title:"New task",column:"todo"});save(cards);});
document.querySelector("#export").addEventListener("click",()=>{const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(load(),null,2)],{type:"application/json"}));a.download="board.json";a.click();});
'''


BOARD_CSS = '''body{font:16px system-ui;margin:0;background:#f4f6fb;color:#172033}header{display:flex;gap:12px;align-items:center;padding:20px}h1{margin-right:auto}#board{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;padding:20px}section{min-height:320px;background:white;border-radius:14px;padding:16px;box-shadow:0 8px 24px #18223b18}button{border:0;border-radius:8px;padding:10px 14px;background:#315efb;color:white}@media(max-width:700px){#board{grid-template-columns:1fr}}
'''


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _package(candidate: pathlib.Path, case_dir: pathlib.Path) -> None:
    package = case_dir / "final_project_bundle.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(candidate.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(candidate).as_posix())
    write_json(case_dir / "delivery_receipt.json", {
        "kind": "BenchmarkDryRunDeliveryReceipt",
        "created_at": utc_now(),
        "package": package.name,
        "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "non_live_fixture": True,
    })


def create_fake_candidate(case: dict[str, Any], case_dir: pathlib.Path, public_context: dict[str, Any]) -> pathlib.Path:
    """Create a fixture candidate. Only the goal is accepted as simulated production context."""
    if set(public_context) != {"user_goal"} or public_context["user_goal"] != case["user_goal"]:
        raise ValueError("hidden benchmark data crossed the production-context boundary")
    candidate = case_dir / "candidate"
    candidate.mkdir(parents=True, exist_ok=False)
    case_id = str(case["case_id"])
    if case_id == "CASE_01_CSV_DATA_CLEANER":
        _write(candidate / "app.py", CSV_APP)
        _write(candidate / "README.md", "# CSV Data Cleaner\n\nRun `python app.py input.csv output.csv`.\n")
        _write(candidate / "TEST_PLAN.md", "Run the command against duplicate and malformed rows.\n")
    elif case_id == "CASE_03_LOCAL_PROJECT_BOARD":
        _write(candidate / "board_cli.py", BOARD_CLI)
        _write(candidate / "index.html", BOARD_HTML)
        _write(candidate / "app.js", BOARD_JS)
        _write(candidate / "styles.css", BOARD_CSS)
        _write(candidate / "README.md", "# Local Project Board\n\nRun `python -m http.server 8000`.\n")
        _write(candidate / "TEST_PLAN.md", "Exercise CRUD, movement, restart persistence, export, and the browser UI.\n")
    else:
        raise ValueError("dry-run fixtures exist only for CASE_01 and CASE_03")
    write_json(candidate / "delivery_manifest.json", {
        "kind": "DeliveryManifest",
        "schema_version": "1.0",
        "entrypoint": "app.py" if case_id.startswith("CASE_01") else "index.html",
        "non_live_fixture": True,
    })
    write_json(case_dir / "production_context_receipt.json", {
        "visible_keys": sorted(public_context),
        "user_goal_sha256": hashlib.sha256(public_context["user_goal"].encode("utf-8")).hexdigest(),
        "hidden_acceptance_visible": False,
        "non_live_fixture": True,
    })
    _package(candidate, case_dir)
    return candidate


def _observation(case: dict[str, Any], run_id: str, candidate: pathlib.Path, criterion: str, ok: bool, producer: str, details: str, requirement_ids: list[str], elapsed: int = 0) -> dict[str, Any]:
    return make_observation(
        case_id=str(case["case_id"]), run_id=run_id, candidate_sha256=candidate_tree_hash(candidate),
        criterion_id=criterion, status="PASS" if ok else "FAIL", producer=producer, details=details,
        requirement_ids=requirement_ids, elapsed_ms=elapsed,
    )


def _probe_csv(case: dict[str, Any], run_id: str, candidate: pathlib.Path, work: pathlib.Path) -> list[dict[str, Any]]:
    source, output = work / "mixed.csv", work / "clean.csv"
    _write(source, "name,email\n Alice , a@example.test \nAlice,a@example.test\nBob,b@example.test,EXTRA\nCarol,c@example.test\nDave,\n")
    ok, process_output, elapsed = run_process_probe([sys.executable, "app.py", str(source), str(output)], cwd=candidate)
    rows = list(csv.reader(output.open(newline="", encoding="utf-8"))) if output.is_file() else []
    cleaned = rows == [["name", "email"], ["Alice", "a@example.test"], ["Carol", "c@example.test"], ["Dave", ""]]
    try:
        summary = json.loads(process_output.splitlines()[-1])
    except (ValueError, IndexError):
        summary = {}
    malformed = summary.get("malformed_rows") == 1
    missing = summary.get("missing_values") == 1
    preview = bool(summary.get("before_preview")) and bool(summary.get("after_preview"))
    integrated = summary.get("output_rows") == max(0, len(rows) - 1) and summary.get("duplicates_removed") == 1
    persisted = output.is_file() and output.read_text(encoding="utf-8").startswith("name,email")
    return [
        _observation(case, run_id, candidate, "csv.runtime", ok, "benchmark_process_probe", process_output, ["R1"], elapsed),
        _observation(case, run_id, candidate, "csv.clean", ok and cleaned, "benchmark_process_probe", f"rows={rows}", ["R1","R2","R3"]),
        _observation(case, run_id, candidate, "csv.missing", missing, "benchmark_process_probe", f"summary={summary}", ["R3"]),
        _observation(case, run_id, candidate, "csv.preview", preview, "benchmark_process_probe", f"summary={summary}", ["R4"]),
        _observation(case, run_id, candidate, "csv.malformed", malformed, "benchmark_process_probe", f"summary={summary}", ["R6"]),
        _observation(case, run_id, candidate, "csv.persist", persisted, "benchmark_persistence_probe", f"output_exists_after_exit={output.is_file()}", ["R5"]),
        _observation(case, run_id, candidate, "csv.integration", integrated, "benchmark_file_probe", f"summary={summary}; rows={len(rows)-1}", ["R2","R4","R5","R6"]),
    ]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _probe_board(case: dict[str, Any], run_id: str, candidate: pathlib.Path, work: pathlib.Path) -> list[dict[str, Any]]:
    state, exported = work / "board.json", work / "export.json"
    base = [sys.executable, "board_cli.py", "--state", str(state)]
    commands = [base + ["add", "--title", "First"], base + ["edit", "--id", "1", "--title", "Revised"], base + ["move", "--id", "1", "--column", "doing"], base + ["move", "--id", "1", "--column", "done"]]
    command_results = [run_process_probe(command, cwd=candidate) for command in commands]
    listed = run_process_probe(base + ["list"], cwd=candidate)
    exported_result = run_process_probe(base + ["export", "--output", str(exported)], cwd=candidate)
    try:
        persisted = json.loads(listed[1].splitlines()[-1])
        exported_doc = json.loads(exported.read_text(encoding="utf-8"))
    except (OSError, ValueError, IndexError):
        persisted, exported_doc = {}, {}
    cards = persisted.get("cards", []) if isinstance(persisted, dict) else []
    crud_ok = all(item[0] for item in command_results) and cards and cards[0].get("title") == "Revised"
    move_ok = bool(cards) and cards[0].get("column") == "done"
    persist_ok = listed[0] and bool(cards)
    export_ok = exported_result[0] and exported_doc == persisted
    port = _free_port()
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], cwd=candidate, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started = time.perf_counter(); http_ok = False; details = "server did not respond"
    try:
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html", timeout=1) as response:
                    body = response.read().decode("utf-8", errors="replace")
                    http_ok = response.status == 200 and all(label in body for label in ("TODO", "DOING", "DONE"))
                    details = f"HTTP {response.status}; columns={http_ok}"
                    break
            except Exception:
                time.sleep(0.05)
    finally:
        server.terminate()
        try: server.wait(timeout=3)
        except subprocess.TimeoutExpired: server.kill()
    elapsed = round((time.perf_counter() - started) * 1000)
    delete_ok = run_process_probe(base + ["delete", "--id", "1"], cwd=candidate)[0]
    return [
        _observation(case, run_id, candidate, "board.crud", bool(crud_ok and delete_ok), "benchmark_process_probe", f"cards_before_delete={cards}", ["R1"]),
        _observation(case, run_id, candidate, "board.move", move_ok, "benchmark_process_probe", f"cards={cards}", ["R2"]),
        _observation(case, run_id, candidate, "board.runtime", http_ok, "benchmark_http_probe", details, ["R1"], elapsed),
        _observation(case, run_id, candidate, "board.persist", persist_ok, "benchmark_persistence_probe", f"fresh_process_cards={cards}", ["R3"]),
        _observation(case, run_id, candidate, "board.export", export_ok, "benchmark_file_probe", f"export_matches={export_ok}", ["R4"]),
    ]


def run_dry_case_probes(case: dict[str, Any], run_id: str, candidate: pathlib.Path, case_dir: pathlib.Path) -> list[dict[str, Any]]:
    work = case_dir / "external_probe_workspace"
    work.mkdir(parents=True, exist_ok=True)
    if case["case_id"] == "CASE_01_CSV_DATA_CLEANER":
        observations = _probe_csv(case, run_id, candidate, work)
    elif case["case_id"] == "CASE_03_LOCAL_PROJECT_BOARD":
        observations = _probe_board(case, run_id, candidate, work)
    else:
        raise ValueError("dry-run probes exist only for CASE_01 and CASE_03")
    observations.append(inspect_delivery(candidate, case_dir, case_id=str(case["case_id"]), run_id=run_id))
    write_json(case_dir / "evidence" / "external_observations.json", {"observations": observations})
    return observations
