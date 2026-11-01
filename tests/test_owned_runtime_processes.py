"""Real process-tree regression, with an unrelated sibling as a negative control."""
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

from scripts.customer_runtime_runner import _stop_owned_process


def test_stops_descendant_but_preserves_unrelated_process(tmp_path):
    pid_file = tmp_path / 'child.pid'
    sleeper = 'import time; time.sleep(60)'
    code = (
        'import pathlib, subprocess, sys; '
        f'child = subprocess.Popen([sys.executable, "-c", {sleeper!r}]); '
        f'pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); '
        'child.wait()'
    )
    unrelated = subprocess.Popen([sys.executable, '-c', sleeper])
    parent = subprocess.Popen([sys.executable, '-c', code], cwd=tmp_path)
    child = None
    try:
        deadline = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert pid_file.exists()
        child = psutil.Process(int(pid_file.read_text()))
        _stop_owned_process(parent)
        assert parent.poll() is not None
        assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
        assert unrelated.poll() is None
        _stop_owned_process(parent)  # Already-reaped handles are safe/idempotent.
    finally:
        _stop_owned_process(parent)
        _stop_owned_process(unrelated)
        if child is not None and child.is_running():
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass


@pytest.mark.parametrize('survives_kill', [False, True])
def test_termination_timeout_escalates_and_never_hides_survivors(monkeypatch, survives_kill):
    calls = []
    child = SimpleNamespace(terminate=lambda: calls.append('terminate_child'),
                            kill=lambda: calls.append('kill_child'))
    parent = SimpleNamespace(children=lambda **kwargs: [child],
                             terminate=lambda: calls.append('terminate_parent'))
    proc = SimpleNamespace(pid=123, poll=lambda: None, wait=lambda **kwargs: 0)
    monkeypatch.setattr(psutil, 'Process', lambda pid: parent)
    waits = iter([([], [child]), ([], [child]) if survives_kill else ([child], [])])
    monkeypatch.setattr(psutil, 'wait_procs', lambda *args, **kwargs: next(waits))
    if survives_kill:
        with pytest.raises(RuntimeError, match='descendants did not stop'):
            _stop_owned_process(proc)
    else:
        _stop_owned_process(proc)
    assert calls == ['terminate_child', 'terminate_parent', 'kill_child']


def test_reaped_parent_never_resolves_a_recycled_pid(monkeypatch):
    def unexpected_lookup(pid):
        raise AssertionError('must not attach to a reaped process PID')
    monkeypatch.setattr(psutil, 'Process', unexpected_lookup)
    _stop_owned_process(SimpleNamespace(pid=123, poll=lambda: 0))


def test_parent_wait_timeout_uses_identity_checked_kill(monkeypatch):
    calls = []
    parent = SimpleNamespace(children=lambda **kwargs: [],
                             terminate=lambda: calls.append('terminate'),
                             kill=lambda: calls.append('kill'))
    def wait(**kwargs):
        calls.append('wait')
        if calls.count('wait') == 1:
            raise subprocess.TimeoutExpired('owned-fixture', 3)
        return -9
    monkeypatch.setattr(psutil, 'Process', lambda pid: parent)
    monkeypatch.setattr(psutil, 'wait_procs', lambda *args, **kwargs: ([], []))
    _stop_owned_process(SimpleNamespace(pid=123, poll=lambda: None, wait=wait))
    assert calls == ['terminate', 'wait', 'kill', 'wait']
