from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectCase:
    case_id: str
    public_goal: str
    public_acceptance: tuple[str, ...]
    entrypoint: str
    runtime_command: tuple[str, ...]
    seeded_fixture: str = ""


CASES: dict[str, ProjectCase] = {
    "cli_csv_cleaner": ProjectCase(
        "cli_csv_cleaner",
        "Build a local Python CSV-cleaning CLI. The public command contract is: python -m csv_cleaner INPUT OUTPUT [--dedupe-column COLUMN] [--fill VALUE] [--preview N]. It must read and write CSV, preserve headers and row order, deduplicate by the selected column or whole row, fill every empty field when --fill is supplied, print the first N cleaned data rows as CSV preview without suppressing output-file creation, provide --help and clear non-zero errors, include README and pytest tests, use only the standard library, and never use the network.",
        ("whole-row and selected-column stable deduplication", "missing-value fill and preview", "valid output and clear invalid-input errors", "README and internal tests", "stdlib-only and offline"),
        "csv_cleaner/__main__.py",
        ("python", "-m", "csv_cleaner", "--help"),
    ),
    "local_web_notes": ProjectCase(
        "local_web_notes",
        "Build a local Notes web application with a Python standard-library backend and vanilla HTML/CSS/JS. The public API contract is GET /, GET /api/notes, POST /api/notes with JSON {\"text\": string}, and DELETE /api/notes/<id>; JSON responses must expose notes as objects with id and text. It must persist across restarts, bind only to 127.0.0.1, support --host --port --data-dir including --port 0, print LISTENING 127.0.0.1:<port> with flush enabled, include README and pytest tests, and make no outbound network requests or external-package imports. The supported entrypoint is python -m notes_app.",
        ("real loopback HTTP process", "create/list/delete JSON API", "persistence across restart", "reasonable request errors", "README, tests, stdlib-only and offline"),
        "notes_app/__main__.py",
        ("python", "-m", "notes_app", "--help"),
    ),
    "multi_module_job_api": ProjectCase(
        "multi_module_job_api",
        "Build a local multi-module Python Job API with separated domain, repository, service, HTTP/API, application entrypoint, and tests. The public API contract is POST /api/jobs with JSON {\"title\": string}, GET /api/jobs, GET /api/jobs/<id>, and POST /api/jobs/<id>/complete. Job JSON exposes id, title, and status; completing an already completed job is rejected. The CLI supports --host --port --data-dir including port 0 and prints LISTENING 127.0.0.1:<port> with flush enabled. It must persist across restart, bind only to loopback, include README and pytest tests, use only the standard library, and make no outbound network requests. The supported entrypoint is python -m job_api.",
        ("domain does not depend on HTTP", "repository and service are testable", "create/list/get/complete HTTP API", "invalid IDs and transitions rejected", "persistence, restart, README, tests and offline stdlib-only operation"),
        "job_api/__main__.py",
        ("python", "-m", "job_api", "--help"),
    ),
    "seeded_repair": ProjectCase(
        "seeded_repair",
        "Repair the existing small Python project so its arithmetic behavior and all tests pass. Inspect the existing files, make the smallest bounded patch, run pytest, and do not replace unrelated files.",
        ("initial public test fails", "bounded Provider-authored patch", "pytest passes", "external arithmetic acceptance passes"),
        "math_utils.py",
        ("python", "-m", "pytest", "-q"),
        "benchmarks/real_project_generation/fixtures/seeded_repair",
    ),
}


def get_case(case_id: str) -> ProjectCase:
    try:
        return CASES[case_id]
    except KeyError as exc:
        raise ValueError(f"unknown software-project case: {case_id}") from exc


def list_cases() -> tuple[ProjectCase, ...]:
    return tuple(CASES[key] for key in sorted(CASES))
