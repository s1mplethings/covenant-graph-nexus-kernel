from __future__ import annotations

import json
import pathlib
from types import MappingProxyType

import pytest

from cgkn.providers import ModelRoleConfig, ProviderCompletion
from experiments.release_060.contracts import ArchitectureBaseline, EvaluationPolicy
from experiments.release_060.evaluator import evaluate_family
from experiments.release_060.runner import _json_plain, file_bundle_schema, run_family
from experiments.release_060.specs import formal_families


def _family():
    return next(item for item in formal_families() if item.family_id == "PF-060-013")


def _files(package: str) -> dict[str, str]:
    return {
        f"{package}/__init__.py": "from .core import select_even\n",
        f"{package}/core.py": "def select_even(value):\n    return [item for item in value if isinstance(item, int) and item % 2 == 0]\n",
        f"{package}/__main__.py": (
            "import json, sys\nfrom pathlib import Path\nfrom .core import select_even\n"
            "def main():\n"
            "    try:\n"
            "        op, source, target = sys.argv[1:4]\n"
            "        if op != 'select_even': raise ValueError('operation')\n"
            "        result = select_even(json.loads(Path(source).read_text(encoding='utf-8')))\n"
            "        Path(target).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding='utf-8')\n"
            "    except Exception as exc:\n"
            "        print(f'error: {type(exc).__name__}', file=sys.stderr); return 2\n"
            "    return 0\n"
            "if __name__ == '__main__': raise SystemExit(main())\n"
        ),
        "README.md": "# Even export\n",
        "pyproject.toml": "[project]\nname='even-export'\nversion='0.1.0'\n",
    }


class FakeClient:
    def __init__(self): self.calls = 0
    def bind_run(self, *args, **kwargs): return self
    def complete(self, *, schema, **kwargs):
        self.calls += 1
        unit = schema["properties"]["unit_id"]["const"]
        allowed = schema["properties"]["files"]["items"]["properties"]["path"]["enum"]
        contents = _files(_family().package_name)
        value = {"schema_version": "2.0", "kind": "file_bundle", "unit_id": unit, "files": [{"path": path, "content": contents[path]} for path in allowed]}
        return ProviderCompletion(json.dumps(value), "deepseek-flash", f"req-{self.calls}", {"input_tokens": 10, "output_tokens": 20}, 1, {"final_status": "ACCEPTED"})


def test_evaluator_passes_and_private_failures_are_opaque(tmp_path: pathlib.Path) -> None:
    family = _family()
    for relative, content in _files(family.package_name).items():
        path = tmp_path / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
    assert evaluate_family(tmp_path, family, private=False).status == "PASS"
    assert evaluate_family(tmp_path, family, private=True).status == "PASS"
    (tmp_path / f"{family.package_name}/core.py").write_text("def select_even(value): return []\n", encoding="utf-8")
    hidden = evaluate_family(tmp_path, family, private=True)
    assert hidden.status == "FAIL"
    assert hidden.public_failure is None
    assert hidden.private_failure_hash.startswith("sha256:")
    public = evaluate_family(tmp_path, family, private=False)
    assert str(tmp_path) not in json.dumps(public.as_dict())


def test_forbidden_network_import_fails_static_gate(tmp_path: pathlib.Path) -> None:
    family = _family()
    for relative, content in _files(family.package_name).items():
        path = tmp_path / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
    path = tmp_path / f"{family.package_name}/core.py"
    path.write_text("import socket\ndef select_even(value): return []\n", encoding="utf-8")
    result = evaluate_family(tmp_path, family, private=False)
    assert result.status == "FAIL" and result.failure_class == "STATIC_GATE"


def test_dynamic_file_bundle_schema_is_exact() -> None:
    schema = file_bundle_schema("unit", ("a.py", "b.py"))
    assert schema["properties"]["files"]["maxItems"] == 2
    assert schema["properties"]["files"]["items"]["properties"]["path"]["enum"] == ["a.py", "b.py"]


def test_dag_dependency_results_are_thawed_for_json_prompt() -> None:
    frozen = MappingProxyType({"node": MappingProxyType({"paths": ("a.py", "b.py")})})
    assert _json_plain(frozen) == {"node": {"paths": ["a.py", "b.py"]}}
    json.dumps(_json_plain(frozen))


@pytest.mark.parametrize("baseline", [ArchitectureBaseline.DIRECT_CHEAP.value, ArchitectureBaseline.MINIMAL_CGNK.value, ArchitectureBaseline.FULL_CGNK.value])
def test_family_runner_and_private_corpus_packet(tmp_path: pathlib.Path, baseline: str) -> None:
    client = FakeClient(); policy = EvaluationPolicy()
    result = run_family(
        _family(), baseline, destination=tmp_path / "runs", corpus_root=tmp_path / "corpus",
        client=client, config=ModelRoleConfig("worker", "deepseek-flash", timeout_seconds=150, max_output_tokens=6000, temperature=0, task_class="release.project_frontier", operation="MATERIALIZE_EPISODE", outer_deadline_seconds=180, deadline_reserve_seconds=30, thinking_mode="disabled"),
        policy=policy, source_version="test-source",
    )
    assert result["status"] == "PASS", result
    assert result["provider_calls"] == 1
    assert result["corpus_capture"]["status"] == "PASS"
    manifest = json.loads(next((tmp_path / "corpus" / "manifests").glob("*.json")).read_text(encoding="utf-8"))
    assert manifest["private_evaluator_ref"]
    assert "private_cases" not in json.dumps(manifest["public_project_packet"], sort_keys=True)
    if baseline == ArchitectureBaseline.FULL_CGNK.value:
        assert result["architecture_receipt"]["summary"]["status"] == "SUCCEEDED"
