"""Read-only diagnostic: execute existing assertions with isolated platform storage.

Does not modify the original tests, candidate, checker, or acceptance authority.
"""
import hashlib
import importlib.util
import json
import tempfile
import time
from pathlib import Path

R = Path(r'F:\CGKN-ITER-132\production-core-convergence-v1\promotion\run-05')
source = R / 'DOGFOOD_MVP/application'
out = Path(__file__).parent / 'publish-fixture-diagnostic'
out.mkdir(exist_ok=False)
test_path = source / 'tests/test_publish.py'
spec = importlib.util.spec_from_file_location('original_publish_tests', test_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rows = []
for name in ('test_reconcile_records_absence_on_404', 'test_retry_resends_failed_branch'):
    with tempfile.TemporaryDirectory(prefix='veriarbor-fixture-') as directory:
        root = Path(directory)
        client = root / 'client'
        client.mkdir()
        platform = module._Platform(str(root / 'platform'))
        start = time.monotonic()
        try:
            getattr(module, name)(str(client), platform)
            status, error = 'PASS', None
        except Exception as exc:
            status, error = 'FAIL', repr(exc)
        rows.append({'test': name, 'status': status, 'error': error,
                     'elapsed_seconds': time.monotonic() - start})
receipt = {
    'kind': 'ReadOnlyFixtureIsolationDiagnostic',
    'source': str(test_path),
    'source_sha256': hashlib.sha256(test_path.read_bytes()).hexdigest(),
    'application_sha256': hashlib.sha256((source / 'promotion_publish.py').read_bytes()).hexdigest(),
    'changed_variable': 'Separate client and simulated remote platform storage directories',
    'assertions': 'Unmodified original test functions',
    'results': rows,
    'authority': 'Diagnostic only; original failures and GoalAcceptance remain unchanged',
    'host_business_patches': 0,
}
(out / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf8')
print(json.dumps(receipt, indent=2))
