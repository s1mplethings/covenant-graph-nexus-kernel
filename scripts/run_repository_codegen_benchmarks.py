from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from cgkn.application.repository_codegen import ChangeKind, ChangeRequest, RepositoryCodegenService  # noqa: E402
from cgkn.providers import ConnectorCompletionClient, GrokConnector, ModelRoleConfig, ProviderConnectorRegistry  # noqa: E402


CASES = (
    ("BUG_FIX", "def add(a, b):\n    return a - b\n", "from app import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", ChangeRequest("repo-bug-fix", "Fix add so it returns the arithmetic sum.", ChangeKind.BUG_FIX, ("add(2,3) returns 5",), ("keep function add(a,b)",), ("do not edit tests",), ("pytest passes",), ("app.py",))),
    ("MULTI_FILE_FEATURE", "def base_value():\n    return 3\n", "from app import base_value\nfrom feature import doubled\n\ndef test_feature():\n    assert doubled(base_value()) == 6\n", ChangeRequest("repo-feature", "Add feature.py with doubled(value) while preserving base_value.", ChangeKind.FEATURE, ("doubled returns value times two",), ("keep base_value",), ("do not edit tests",), ("pytest passes",), ("app.py", "feature.py"))),
    ("REFACTOR", "def normalize(text):\n    return text.strip().lower()\n", "from app import normalize\n\ndef test_normalize():\n    assert normalize(' A ') == 'a'\n", ChangeRequest("repo-refactor", "Refactor normalize to use a named intermediate and casefold without changing its public interface.", ChangeKind.REFACTOR, ("same observable result",), ("keep normalize(text)",), ("do not edit tests",), ("pytest passes",), ("app.py",))),
)


def run(output_root: pathlib.Path) -> dict:
    profile = json.loads((ROOT / "config/provider_connections/grok.json").read_text(encoding="utf-8"))
    connector = GrokConnector(profile)
    health = connector.probe_connection()
    if not health.eligible: raise RuntimeError("SINGLE_PROVIDER_MODE requires the frozen Grok connection to remain eligible")
    client = ConnectorCompletionClient(ProviderConnectorRegistry((connector,)))
    service = RepositoryCodegenService(client, ModelRoleConfig("worker", "grok", 120, 3000, 0.0, "low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE")
    output_root.mkdir(parents=True, exist_ok=False); receipts = []
    for name, source, test, change in CASES:
        workspace = output_root / name.lower(); (workspace / "tests").mkdir(parents=True)
        (workspace / "app.py").write_text(source, encoding="utf-8"); (workspace / "tests/test_app.py").write_text(test, encoding="utf-8")
        try: receipt = service.run(workspace, change).as_dict()
        except Exception as exc:
            receipt = {"kind": "RepositoryCodegenReceipt", "schema_version": "1.0", "change_id": change.change_id, "change_kind": name, "provider_id": "grok", "mode": "SINGLE_PROVIDER_MODE", "routing_frozen": True, "fallback": "deny", "calls": "UNKNOWN", "repairs": "UNKNOWN", "modified_files": [], "unrelated_edits": [], "interface_breaks": [], "tests_passed": False, "status": "FAIL", "error_class": type(exc).__name__, "error": str(exc)[:1000], "contains_credentials": False}
        (output_root / f"{name.lower()}_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); receipts.append(receipt)
    passed = sum(item["status"] == "PASS" for item in receipts)
    result = {"kind": "RepositoryCodegenBenchmarkStatus", "schema_version": "1.0", "mode": "SINGLE_PROVIDER_MODE", "provider_id": "grok", "eligible_provider_count": 1, "routing_frozen": True, "fallback": "deny", "cases": receipts, "passed": passed, "required": 2, "manual_edits": 0, "whole_replans": 0, "status": "COMPLETE" if passed >= 2 else "REPOSITORY_CODEGEN_NEEDS_REWORK", "contains_credentials": False}
    (output_root / "repository_codegen_status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-root", type=pathlib.Path, required=True); args = parser.parse_args()
    if args.output_root.exists(): raise SystemExit("output root already exists")
    result = run(args.output_root.resolve()); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__": raise SystemExit(main())
