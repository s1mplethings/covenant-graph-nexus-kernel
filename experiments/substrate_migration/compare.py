"""Compare completed full-suite JUnit results without hiding missing tests."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parents[2] / 'artifacts/substrate-migration'


def read(name):
    rows = {}
    for case in ET.parse(OUT / name).findall('.//testcase'):
        key = f"{case.get('classname')}::{case.get('name')}"
        error = case.find('error')
        failure = case.find('failure')
        if error is not None or failure is not None:
            node = error if error is not None else failure
            status, detail = 'FAIL', node.get('message', '')
        elif case.find('skipped') is not None:
            status, detail = 'SKIP', case.find('skipped').get('message', '')
        else:
            status, detail = 'PASS', ''
        if key in rows:
            raise ValueError('duplicate test identity: ' + key)
        rows[key] = {'status': status, 'detail': detail}
    return rows


if __name__ == '__main__':
    before, after = read('baseline/pytest.xml'), read('regression.xml')
    old_fail = {key for key, value in before.items() if value['status'] == 'FAIL'}
    new_fail = {key for key, value in after.items() if value['status'] == 'FAIL'}
    result = {
        'baseline_cases': len(before), 'regression_cases': len(after),
        'baseline_failures': sorted(old_fail),
        'reproduced_baseline_failures': sorted(new_fail & old_fail),
        'new_failures': {key: after[key] for key in sorted(new_fail - old_fail)},
        'no_longer_failing': sorted(old_fail - new_fail),
        'missing_tests': sorted(before.keys() - after.keys()),
        'added_tests': sorted(after.keys() - before.keys()),
        'new_skips': sorted(key for key in before.keys() & after.keys()
                            if before[key]['status'] != 'SKIP' and after[key]['status'] == 'SKIP'),
    }
    (OUT / 'regression-comparison.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key: len(value) if isinstance(value, (list, dict)) else value
                      for key, value in result.items()}, indent=2))
