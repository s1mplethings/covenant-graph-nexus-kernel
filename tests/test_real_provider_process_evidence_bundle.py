from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.provider, pytest.mark.e2e]


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = ROOT / "generated" / "real_provider_large_project_delivery_eval" / "process_evidence_bundle"
BUNDLE_ZIP = ROOT / "generated" / "real_provider_large_project_delivery_eval" / "process_evidence_bundle.zip"


def test_process_evidence_bundle_zip_contains_required_entrypoints() -> None:
    assert BUNDLE_ZIP.exists()
    assert BUNDLE_ZIP.stat().st_size > 50_000

    with zipfile.ZipFile(BUNDLE_ZIP) as zf:
        names = set(zf.namelist())

    assert "00_INDEX.md" in names
    assert "process_evidence_manifest.json" in names
    assert "08_failure_analysis/root_cause_analysis.md" in names
    assert "06_contract_checks/public_delivery_gate.json" in names


def test_process_evidence_manifest_is_inspectable() -> None:
    manifest_path = BUNDLE_DIR / "process_evidence_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["kind"] == "RealProviderProcessEvidenceBundle"
    assert manifest["provider_ready"] is True
    assert manifest["generation_status"] == "rework_blocked"
    assert manifest["classification"] == "real_provider_generated_but_not_runnable"
    assert manifest["final_verdict"] == "NEEDS_REWORK"
    assert manifest["redaction"]["api_key_redacted"] is True
    assert manifest["included_files"]


def test_missing_evidence_docs_explain_reason_and_gate_impact() -> None:
    missing_docs = sorted(path for path in BUNDLE_DIR.rglob("*.md") if path.name.startswith("MISSING_"))
    assert missing_docs

    required_phrases = ["期望文件是什么", "应该由哪个阶段生成", "当前为什么没有", "对最终 gate 的影响"]
    for path in missing_docs:
        text = path.read_text(encoding="utf-8")
        for phrase in required_phrases:
            assert phrase in text, f"{path} missing {phrase}"


def test_bundle_does_not_contain_obvious_secret_values() -> None:
    secret_value_patterns = [
        re.compile(r"(?i)authorization\s*[:=]\s*(?!\[REDACTED_SECRET\])\S+"),
        re.compile(r"(?i)api[_-]?key\s*[:=]\s*(?!\[REDACTED_SECRET\])\S+"),
        re.compile(r"(?i)secret\s*[:=]\s*(?!\[REDACTED_SECRET\])\S+"),
        re.compile(r"(?i)password\s*[:=]\s*(?!\[REDACTED_SECRET\])\S+"),
        re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    ]

    for path in BUNDLE_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".zip", ".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in secret_value_patterns:
            assert not pattern.search(text), f"possible secret leaked in {path}"
