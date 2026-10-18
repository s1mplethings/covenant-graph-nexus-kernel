from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def imports(relative: str) -> set[str]:
    tree = ast.parse(source(relative)); result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): result.update(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom): result.add(node.module or "")
    return result


def test_connectors_do_not_call_urlopen_directly():
    for name in ("qwen.py", "deepseek.py", "grok.py"):
        tree = ast.parse(source(f"cgkn/providers/connectors/{name}"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "urlopen"]
        assert calls == []


def test_production_packages_do_not_import_benchmark_budget():
    for relative in ("cgkn/application/learning/integration.py", "cgkn/application/software_project/greenfield/service.py", "cgkn/application/repository_codegen/service.py"):
        assert "BenchmarkBudget" not in source(relative)


def test_supervisor_does_not_import_selector_or_action_policy():
    values = imports("cgkn/providers/supervision/supervisor.py")
    assert not any("selector" in value or "action_policy" in value for value in values)


def test_cli_compiler_does_not_import_provider():
    assert not any("provider" in value for value in imports("cgkn/application/software_project/greenfield/cli.py"))


def test_learning_does_not_mutate_operation_policy():
    assert "ProviderOperationPolicy" not in source("cgkn/application/learning/integration.py")


def test_shared_transport_is_only_provider_urlopen_caller():
    assert "request.urlopen" in source("cgkn/providers/supervision/transport.py")
