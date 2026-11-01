"""Independent process controls for structured public-route test evidence."""
import pytest
from scripts.real_test_execution import run_tests

pytestmark=[pytest.mark.boundary,pytest.mark.negative]


@pytest.mark.parametrize('source',['# no collected test\n','def test_failure(): assert False\n'])
def test_public_route_rejects_fake_pass_text_and_overridden_exit(tmp_path,source):
    (tmp_path/'tests').mkdir();(tmp_path/'tests/test_probe.py').write_text(source)
    (tmp_path/'conftest.py').write_text("def pytest_sessionfinish(session,exitstatus):\n print('999 passed')\n session.exitstatus=0\n")
    result=run_tests(tmp_path)
    assert result['exit_code']==0 and result['status']=='FAIL'
    assert result['test_observation']['status']!='PASS'
    assert result['passed']==0


def test_public_route_does_not_count_console_numbers_as_tests(tmp_path):
    (tmp_path/'tests').mkdir();(tmp_path/'tests/test_probe.py').write_text('def test_probe(): assert True\n')
    (tmp_path/'conftest.py').write_text("def pytest_sessionfinish(session,exitstatus):\n print('999 passed')\n")
    result=run_tests(tmp_path)
    assert result['status']=='PASS' and result['collected']==result['passed']==1
    assert result['test_observation']['files'][0]['path']=='tests/test_probe.py'


def test_fresh_execution_cannot_reuse_old_passing_test_receipt(tmp_path):
    (tmp_path/'tests').mkdir();test=tmp_path/'tests/test_probe.py';test.write_text('def test_probe(): assert True\n')
    first=run_tests(tmp_path);assert first['status']=='PASS'
    test.write_text('# current version contains no executable tests\n')
    second=run_tests(tmp_path)
    assert second['status']=='FAIL' and second['passed']==0
    assert first['candidate_hash']!=second['candidate_hash']
