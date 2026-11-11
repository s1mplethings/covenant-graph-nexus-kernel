"""Isolated candidate Python must not discard its UTF-8 evidence policy."""
import sys
from scripts import real_test_execution


def test_isolated_candidate_preserves_unicode_output_and_utf8_mode(tmp_path):
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_encoding.py').write_text(
        "import sys\n"
        "def test_encoding():\n"
        "    print('审批状态 ✓')\n"
        "    assert sys.flags.isolated == 1\n"
        "    assert sys.flags.utf8_mode == 1\n", encoding='utf8')
    result = real_test_execution.run_tests(tmp_path, python_executable=sys.executable,
        run_id='utf8-regression', candidate_id='unicode-candidate', commit_sha='test-fixture')
    assert result['status'] == 'PASS', result['test_observation']['failure_details']
    assert result['collected'] == result['passed'] == 1
    assert real_test_execution.inspect_test_report(tmp_path)['status'] == 'PASS'
