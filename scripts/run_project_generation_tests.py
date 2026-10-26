from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILES = {"unit", "local", "hidden-harness", "live-single", "live-repeat", "live-multitype", "live-repair", "final"}


def run_command(argv: list[str]) -> dict:
    started = time.perf_counter()
    completed = subprocess.run(argv, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True)
    return {"argv": argv, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "duration_ms": int((time.perf_counter() - started) * 1000)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=sorted(PROFILES))
    parser.add_argument("--case")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.profile == "unit": commands = [[sys.executable, "-m", "pytest", "-q", "tests/application/software_project", "-m", "not local_functional"]]
    elif args.profile == "local": commands = [[sys.executable, "-m", "pytest", "-q", "tests/application/software_project", "-m", "local_functional"]]
    elif args.profile == "hidden-harness": commands = [[sys.executable, "-m", "pytest", "-q", "tests/application/software_project/test_acceptance.py"]]
    elif args.profile == "live-single": commands = [[sys.executable, "benchmarks/real_project_generation/run_case.py", "--case", args.case or "cli_csv_cleaner", "--json"]]
    elif args.profile == "live-repeat": commands = [[sys.executable, "benchmarks/real_project_generation/run_case.py", "--case", args.case or "cli_csv_cleaner", "--json"] for _ in range(args.count)]
    elif args.profile == "live-multitype": commands = [[sys.executable, "benchmarks/real_project_generation/run_suite.py", "--cases", "cli_csv_cleaner", "local_web_notes", "multi_module_job_api"]]
    elif args.profile == "live-repair": commands = [[sys.executable, "benchmarks/real_project_generation/run_case.py", "--case", args.case or "seeded_repair", "--json"]]
    else: commands = [[sys.executable, "benchmarks/real_project_generation/run_suite.py", "--cases", "cli_csv_cleaner", "cli_csv_cleaner", "cli_csv_cleaner", "local_web_notes", "multi_module_job_api", "seeded_repair"]]
    results = [run_command(command) for command in commands]
    report = {"kind": "CGKNProjectGenerationTestProfile", "schema_version": "1.0", "profile": args.profile, "commands": results, "status": "PASS" if all(row["returncode"] == 0 for row in results) else "FAIL"}
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json or True else report["status"])
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
