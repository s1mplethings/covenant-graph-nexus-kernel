"""Shared representation must preserve isolation across public contract boundaries."""
import importlib
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('name', ['cgkn.component.spec', 'cgkn.execution.contracts',
                                 'cgkn.orchestration.capability_tree', 'cgkn.orchestration.execution_dag'])
def test_nested_contract_snapshots_remain_detached(name):
    module = importlib.import_module(name)
    source = {'scope': [{'file': '中文.py', 'ports': [1, 2]}], 7: ('value',)}
    frozen = module._freeze(source)
    source['scope'][0]['ports'].append(3)
    assert module._thaw(frozen) == {'scope': [{'file': '中文.py', 'ports': [1, 2]}], '7': ['value']}
    with pytest.raises(TypeError):
        frozen['scope'][0]['file'] = 'changed.py'
    exported = module._thaw(frozen)
    exported['scope'][0]['ports'].append(4)
    assert frozen['scope'][0]['ports'] == (1, 2)


@pytest.mark.parametrize('first', ['cgkn.execution.contracts', 'cgkn.orchestration.capability_tree',
                                  'cgkn.orchestration.execution_dag'])
def test_cold_imports_do_not_create_component_cycles(first):
    code = ('import importlib; '
            f'm=importlib.import_module({first!r}); '
            'from cgkn.component import ComponentSpec; '
            'from cgkn.execution import BlockExecutionRequest; '
            'assert m._thaw(m._freeze({"x":[1]})) == {"x":[1]}')
    result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('domestic', [False, True])
def test_compatibility_post_failure_never_uses_other_route(monkeypatch, domestic):
    from scripts import check_connectivity
    from cgkn.providers import application_network, canonical_gateway_adapter, legacy_transport
    monkeypatch.setattr(application_network, 'settings', lambda: {'enabled': True} if domestic else None)
    calls = []
    def blocked(*args, **kwargs):
        calls.append('selected')
        raise RuntimeError('admission blocked')
    def forbidden(*args, **kwargs):
        pytest.fail('failed request must not fall through to the other transport')
    monkeypatch.setattr(canonical_gateway_adapter, 'post_payload', blocked if domestic else forbidden)
    monkeypatch.setattr(legacy_transport, 'post_json_once', forbidden if domestic else blocked)
    with pytest.raises(RuntimeError, match='admission blocked'):
        check_connectivity._post_json('http://127.0.0.1:1/v1/responses', {'model': 'qwen'}, 'fake', 1)
    assert calls == ['selected']


@pytest.mark.parametrize('argv', [
    ['rm', '-rf', '/'], ['rmdir', '/s', 'C:\\Windows'], ['del', 'file'], ['format', 'C:'],
    ['shutdown', '/s'], ['reboot'], ['diskpart'], ['git', 'clean', '-fd'], ['git', 'reset', '--hard'],
    ['cmd', '/c', 'del file'], ['powershell', '-Command', 'shutdown /s'], ['/bin/rm', 'file'],
])
def test_denied_command_tokens_never_reach_process_runner(tmp_path, monkeypatch, argv):
    from cgkn.execution import BlockExecutionRequest, TaskContext
    from cgkn.executors import local
    def forbidden(*args, **kwargs):
        pytest.fail('dangerous fixture must never execute')
    monkeypatch.setattr(local.subprocess, 'run', forbidden)
    request = BlockExecutionRequest(project_id='p', run_id='r', attempt_id='a', node_id='n',
        component_ref='c@1', executor_ref='local.command@1', task_context=TaskContext('check', {'command': argv}))
    result = local.CommandExecutor(tmp_path).execute(request)
    assert result.error.code.value == 'POLICY_BLOCKED'


def test_real_pytest_survives_blocked_substring_in_temporary_path(tmp_path, monkeypatch):
    from cgkn.execution import BlockExecutionRequest, TaskContext
    from cgkn.executors import local
    original = local.tempfile.TemporaryDirectory
    monkeypatch.setattr(local.tempfile, 'TemporaryDirectory',
                        lambda **kwargs: original(prefix='cgkn-pycache-xo_lurm4-', dir=tmp_path.parent))
    (tmp_path / 'test_model.py').write_text('def test_sum(): assert 2 + 3 == 5\n', encoding='utf-8')
    request = BlockExecutionRequest(project_id='p', run_id='r', attempt_id='a', node_id='n',
        component_ref='c@1', executor_ref='local.python-test@1',
        task_context=TaskContext('check', {'pytest_args': ['-q', 'test_model.py']}), timeout_seconds=20)
    from tests.executor_authority_support import invoke_bound_executor
    result = invoke_bound_executor(local.PythonTestExecutor(tmp_path),request)
    assert result.succeeded
    assert result.outputs['test_observation']['status'] == 'PASS'
    assert result.outputs['test_observation']['executed'] == 1
    assert result.outputs['test_observation']['files'][0]['path'] == 'test_model.py'


@pytest.mark.parametrize('boundary', ['compatibility', 'transport'])
def test_historical_sender_delegates_to_current_gateway_after_import(monkeypatch,boundary):
    # Replaces retired raw-opener semantics: neither old import location may
    # bypass the current Gateway or create another transport/retry owner.
    from cgkn.providers import canonical_gateway_adapter,application_network
    from scripts import check_connectivity,provider_transport
    import urllib.request
    monkeypatch.setattr(application_network,'settings',lambda:None)
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:pytest.fail('raw transport bypass'))
    calls=[]
    def gateway(payload,timeout,*,endpoint):
        calls.append((payload,timeout,endpoint));return {'output_text':'offline'}
    monkeypatch.setattr(canonical_gateway_adapter,'post_payload',gateway)
    entry=check_connectivity._post_json if boundary=='compatibility' else provider_transport.post_json_once
    result,error=entry('http://127.0.0.1:1',{'model':'fixture'},'not-authority',1)
    assert result=={'output_text':'offline'} and error==''
    assert calls==[({'model':'fixture'},1,'http://127.0.0.1:1')]
