"""Explicit Host permits for reviewed offline transport fixtures.

Only the named pre-authority transport suites receive this fixture. Their
budget/schema/UNKNOWN assertions remain unchanged. No production guard is
patched, no LEGACY execution is selected, and unrelated tests receive no permit.
"""
import pytest
from tests.providers.authority_fixtures import authorized_transport

TRANSPORT_FIXTURES=frozenset({
    'test_domestic_mode.py','test_domestic_repair.py','test_iter117_thinking_mode.py',
    'test_iter119_pair.py','test_progress_clock.py','test_readonly_recovery.py',
    'test_streaming_independent.py','test_streaming_runtime.py',
    'test_progress_transport.py',
    'test_iter117_bounded_acceptance.py','test_iter117_long_acceptance.py','test_iter118_acceptance.py',
})


@pytest.fixture(autouse=True)
def explicit_transport_host_admission(request,tmp_path_factory):
    if request.path.name not in TRANSPORT_FIXTURES:
        yield
        return
    with authorized_transport(tmp_path_factory.mktemp('transport-host-authority'),calls=32):
        yield
