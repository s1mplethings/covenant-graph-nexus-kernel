from __future__ import annotations

import importlib.util
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_compliance_audit", ROOT / "scripts" / "release_compliance_audit.py"
)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def test_secret_scan_never_returns_secret_value() -> None:
    secret = b"sk-proj-abcdefghijklmnopqrstuvwx"
    findings = AUDIT.scan_bytes(b"token=" + secret, "fixture.txt", history=False)
    assert findings
    rendered = repr(findings)
    assert secret.decode() not in rendered
    assert findings[0].severity == "P0"
    assert findings[0].detail == "openai_token; unreviewed secret candidate"


def test_placeholder_is_not_an_assigned_secret() -> None:
    findings = AUDIT.scan_bytes(
        b'api_key = "placeholder"\npassword = "example"\n', "fixture.txt", history=False
    )
    assert findings == []


def test_user_home_path_is_privacy_finding() -> None:
    findings = AUDIT.scan_bytes(
        b'path = "C:/Users/alice/private/run.json"\n', "fixture.txt", history=False
    )
    assert len(findings) == 1
    assert findings[0].gate == "privacy_current"
    assert findings[0].severity == "P1"
    assert "alice" not in repr(findings)


def test_release_metadata_and_provenance_are_complete() -> None:
    paths = AUDIT.tracked_paths()
    for rel in (pathlib.Path("LICENSE"), AUDIT.PROVENANCE, pathlib.Path("pyproject.toml"), pathlib.Path("CITATION.cff")):
        if rel not in paths:
            paths.append(rel)
    findings = AUDIT.metadata_findings() + AUDIT.postiz_findings(paths)
    provenance, inventory = AUDIT.provenance_findings(paths)
    assert findings + provenance == []
    assert inventory["binary_assets"] == [
        "evidence/architecture-reduction-v1/e2e/math_training_screenshot.png",
        "evidence/candidate-canonicalization-v1/math_training_screenshot.png",
    ]


def test_history_scope_commit_is_resolved_explicitly() -> None:
    resolved = AUDIT.resolve_commit("HEAD")
    assert len(resolved) == 40
    assert resolved == AUDIT.run_git("rev-parse", "HEAD").decode().strip()


def test_canonical_hash_is_order_independent() -> None:
    assert AUDIT.canonical_hash({"a": 1, "b": 2}) == AUDIT.canonical_hash({"b": 2, "a": 1})
