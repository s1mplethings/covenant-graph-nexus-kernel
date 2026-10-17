from __future__ import annotations

import json

from cgkn.application.repository_codegen import ChangeKind, ChangeRequest, RepositoryCodegenService, compile_change_contract, snapshot_repository
from cgkn.providers import ModelRoleConfig, ProviderCompletion


class FakeClient:
    def __init__(self, proposals): self.proposals = iter(proposals); self.calls = 0
    def complete(self, **_kwargs):
        self.calls += 1
        return ProviderCompletion(json.dumps(next(self.proposals)), "grok-4.7", f"r{self.calls}", {"total_tokens": 10})


def proposal(node_id, actions):
    return {"schema_version": "1.0", "node_id": node_id, "summary": "bounded patch", "actions": actions, "expected_outputs": ["pytest passes"], "confidence": 1.0, "needs_escalation": False, "escalation_reason": ""}


def write_fixture(root, source, test):
    (root / "tests").mkdir(); (root / "app.py").write_text(source, encoding="utf-8"); (root / "tests/test_app.py").write_text(test, encoding="utf-8")


def service(client):
    return RepositoryCodegenService(client, ModelRoleConfig("worker", "grok", 30, 1000), provider_id="grok", mode="SINGLE_PROVIDER_MODE")


def test_bug_fix_patch_first_passes(tmp_path) -> None:
    write_fixture(tmp_path, "def add(a, b):\n    return a - b\n", "from app import add\n\ndef test_add(): assert add(2, 3) == 5\n")
    client = FakeClient([proposal("bug", [{"action": "patch_file", "path": "app.py", "find": "return a - b", "replace": "return a + b"}])])
    receipt = service(client).run(tmp_path, ChangeRequest("bug", "fix addition", ChangeKind.BUG_FIX, ("addition works",), ("add interface",), ("tests",), ("pytest",), ("app.py",)))
    assert receipt.status == "PASS" and receipt.modified_files == ("app.py",) and receipt.repairs == 0


def test_multifile_feature_passes_without_unrelated_edits(tmp_path) -> None:
    write_fixture(tmp_path, "def value():\n    return 2\n", "from app import value\nfrom feature import doubled\n\ndef test_feature(): assert doubled(value()) == 4\n")
    client = FakeClient([proposal("feature", [
        {"action": "patch_file", "path": "app.py", "find": "return 2", "replace": "return 2"},
        {"action": "write_file", "path": "feature.py", "content": "def doubled(value):\n    return value * 2\n"},
    ])])
    receipt = service(client).run(tmp_path, ChangeRequest("feature", "add doubled", ChangeKind.FEATURE, ("doubled",), ("value",), ("tests",), ("pytest",), ("app.py", "feature.py")))
    assert receipt.status == "PASS" and receipt.unrelated_edits == ()


def test_refactor_preserves_public_interface(tmp_path) -> None:
    write_fixture(tmp_path, "def normalize(text):\n    return text.strip().lower()\n", "from app import normalize\n\ndef test_normalize(): assert normalize(' A ') == 'a'\n")
    client = FakeClient([proposal("refactor", [{"action": "patch_file", "path": "app.py", "find": "return text.strip().lower()", "replace": "clean = text.strip()\n    return clean.casefold()"}])])
    receipt = service(client).run(tmp_path, ChangeRequest("refactor", "refactor normalize", ChangeKind.REFACTOR, ("same behavior",), ("normalize",), ("tests",), ("pytest",), ("app.py",)))
    assert receipt.status == "PASS" and receipt.interface_breaks == ()


def test_change_contract_rejects_protected_scope(tmp_path) -> None:
    (tmp_path / "governance").mkdir(); (tmp_path / "governance/x.py").write_text("x=1", encoding="utf-8")
    snapshot = snapshot_repository(tmp_path)
    request = ChangeRequest("bad", "bad", ChangeKind.REFACTOR, (), (), (), (), ("governance/x.py",))
    import pytest
    with pytest.raises(ValueError, match="protected"):
        compile_change_contract(snapshot, request)


def test_existing_file_full_rewrite_is_rejected(tmp_path) -> None:
    write_fixture(tmp_path, "def add(a,b): return a-b\n", "from app import add\n\ndef test_add(): assert add(2,3)==5\n")
    client = FakeClient([proposal("bad", [{"action": "write_file", "path": "app.py", "content": "def add(a,b): return a+b\n"}])])
    import pytest
    with pytest.raises(ValueError, match="patch-first"):
        service(client).run(tmp_path, ChangeRequest("bad", "fix", ChangeKind.BUG_FIX, (), (), (), (), ("app.py",)))

