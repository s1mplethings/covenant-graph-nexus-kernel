from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import kernel_gate_common as common


def test_inventory_includes_nested_adapters_protocol_and_package_entries(tmp_path, monkeypatch):
    paths = {'cgkn/adapters/vendor/deep/entry.py', 'cgkn/protocol/new_role.py',
             'cgkn/providers/__init__.py'}
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('', encoding='utf-8')
    monkeypatch.setattr(common, 'ROOT', tmp_path)
    assert common.source_files() == paths


def test_relative_import_cannot_hide_reverse_dependency(tmp_path):
    path = tmp_path / 'cgkn/component/entry.py'
    path.parent.mkdir(parents=True)
    path.write_text('from ..agent import project_loop\nfrom . import spec\n', encoding='utf-8')
    assert common.imported_modules(path) == {
        'cgkn.agent', 'cgkn.agent.project_loop', 'cgkn.component', 'cgkn.component.spec'}


def test_package_entry_relative_import_is_resolved_from_package(tmp_path):
    path = tmp_path / 'cgkn/adapters/vendor/__init__.py'
    path.parent.mkdir(parents=True)
    path.write_text('from ...runtime.node_authority import ExecutionAuthority\n', encoding='utf-8')
    assert 'cgkn.runtime.node_authority' in common.imported_modules(path)
