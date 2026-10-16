from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from cgkn.application.requirements import ObligationDAGService
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from tests.application.requirements.test_work_unit_dag import CORE, MAIN, TESTS


README = "# CSV Cleaner\n\nUse `python -m csv_cleaner INPUT OUTPUT [--dedupe-column COLUMN] [--fill VALUE] [--preview N]`.\n"
BROKEN_TESTS = "def test_generated_but_incorrect():\n    assert False, 'generated test defect'\n"
WEAK_TESTS = "def test_smoke_only():\n    assert True\n"
BROKEN_FILL_CORE = CORE.replace(
    'row = {name: fill if raw.get(name, "") == "" and fill else raw.get(name, "") for name in fields}',
    'row = {name: raw.get(name, "") for name in fields}',
)


class SeededOracleProvider:
    def __init__(self, defect: str):
        self.defect = defect
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: Any) -> ProviderCompletion:
        payload = json.loads(user)
        node = payload["node_id"]
        self.calls.append(payload)
        repairing = bool(payload.get("failure_evidence"))
        if node == "WU-CORE":
            core = CORE if repairing or self.defect != "core" else BROKEN_FILL_CORE
            actions = [
                {"action": "write_file", "path": "csv_cleaner/__init__.py", "content": "from .core import clean_csv\n__all__ = ['clean_csv']\n"},
                {"action": "write_file", "path": "csv_cleaner/__main__.py", "content": MAIN},
                {"action": "write_file", "path": "csv_cleaner/core.py", "content": core},
            ]
        elif node == "WU-TESTS":
            if self.defect == "tests":
                content = TESTS if repairing else BROKEN_TESTS
            else:
                content = WEAK_TESTS
            actions = [{"action": "write_file", "path": "tests/test_csv_cleaner.py", "content": content}]
        else:
            actions = [{"action": "write_file", "path": "README.md", "content": README}]
        value = {
            "schema_version": "1.0", "node_id": node, "summary": "seeded fake response",
            "actions": actions, "expected_outputs": ["contract satisfied"], "confidence": 1.0,
            "needs_escalation": False, "escalation_reason": "",
        }
        return ProviderCompletion(json.dumps(value), config.model, f"fake-{len(self.calls)}", {"total_tokens": 20})


def count(provider: SeededOracleProvider, node: str) -> int:
    return sum(item["node_id"] == node for item in provider.calls)


def test_oracle_pass_public_test_fail_repairs_only_tests_and_reuses_core(tmp_path: Path) -> None:
    provider = SeededOracleProvider("tests")
    result = ObligationDAGService(Path.cwd(), provider, ModelRoleConfig("worker", "fake-worker")).run_csv(
        tmp_path / "workspace", tmp_path / "run"
    )
    assert result.status == "PASS"
    assert result.public_pytest == result.oracle_status == result.hidden_acceptance == "PASS"
    assert result.repair_owners == ("WU-TESTS",)
    assert count(provider, "WU-CORE") == 1
    assert count(provider, "WU-TESTS") == 2
    assert "WU-CORE" in result.reused_work_units


def test_oracle_fail_weak_public_test_repairs_core(tmp_path: Path) -> None:
    provider = SeededOracleProvider("core")
    result = ObligationDAGService(Path.cwd(), provider, ModelRoleConfig("worker", "fake-worker")).run_csv(
        tmp_path / "workspace", tmp_path / "run"
    )
    assert result.status == "PASS"
    assert result.public_pytest == result.oracle_status == result.hidden_acceptance == "PASS"
    assert result.repair_owners[0] == "WU-CORE"
    assert count(provider, "WU-CORE") == 2
    assert any(item["status"] == "PASS" for item in result.oracle_evidence)
