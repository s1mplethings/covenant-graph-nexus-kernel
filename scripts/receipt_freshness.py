from __future__ import annotations

import json
import pathlib
import hashlib
import xml.etree.ElementTree as ET
from typing import Any

from source_boundaries import ROOT, boundary_identity


RECEIPTS = {
    "kernel": "governance/kernel_test_receipt.json",
    "application": "governance/software_project_generation_receipt.json",
    "experiment": "governance/semantic_artifact_validation_receipt.json",
}

WORKTREE_RECEIPT = 'governance/current_worktree_test_receipt.json'


def junit_nodeid(case):
    parts=case.attrib['classname'].split('.')
    for index in range(len(parts),0,-1):
        filename='/'.join(parts[:index])+'.py'
        if (ROOT/filename).is_file():
            return filename+'::'+'::'.join([*parts[index:],case.attrib['name']])
    raise ValueError('JUnit case does not identify an existing test source')


def _affected_retest_passes(receipt, boundary, current):
    """Authenticate original batches and exact retests; never erase a failure.

    Only test source and this verifier may change between batches. Runtime,
    contracts, configuration and coverage mapping changes invalidate reuse.
    A changed test file must be re-executed at its current identity.
    """
    outcomes = {}
    test_files = set()
    failures_seen = set()
    for run in receipt['runs']:
        if boundary not in run.get('applicable_boundaries', (boundary,)):
            continue
        if run.get('source_unchanged') is not True or run.get('returncode') not in {0, 1}:
            raise ValueError('validation failed outside ordinary test assertions')
        snapshot = run['boundaries'][boundary]
        old, new = snapshot['files'], current['files']
        changed = {p for p in set(old) | set(new) if old.get(p) != new.get(p)}
        if any(not p.startswith('tests/') and p != 'scripts/receipt_freshness.py' for p in changed):
            raise ValueError('production source changed between validation batches')
        raw = pathlib.Path(run['junit_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != run['junit_sha256']:
            raise ValueError('validation output hash mismatch')
        cases = list(ET.fromstring(raw).iter('testcase'))
        if not cases:
            raise ValueError('empty validation batch')
        failed = any(c.find('failure') is not None or c.find('error') is not None for c in cases)
        if (run['returncode'] == 1) != failed:
            raise ValueError('test exit code and original JUnit disagree')
        for case in cases:
            node = junit_nodeid(case)
            filename = node.split('::')[0]
            test_files.add(filename)
            error = case.find('failure') is not None or case.find('error') is not None
            if error:
                failures_seen.add(node)
                outcomes[node] = False
            elif case.find('skipped') is not None:
                outcomes[node] = False
            elif filename in new and old.get(filename) != new[filename]:
                outcomes[node] = False
            else:
                outcomes[node] = True
    if any(not outcomes.get(node) for node in failures_seen):
        raise ValueError('original failed test has no passing current-source retest')
    # The schema extension itself requires its current negative controls.
    controls = set(receipt.get('retest_verifier_controls', ()))
    if not controls or not controls <= {n for n, ok in outcomes.items() if ok}:
        raise ValueError('affected-retest verifier controls missing')
    return {n for n, ok in outcomes.items() if ok}


def check_worktree_receipt(boundary: str) -> dict[str, Any]:
    """Verify an offline validation receipt against bytes and original JUnit.

    This supplements historical committed receipts; it never promotes their
    old product/readiness claims to the current working copy.
    """
    try:
        receipt=json.loads((ROOT/WORKTREE_RECEIPT).read_text(encoding='utf-8'))
        if receipt.get('kind')!='CGKNWorkingTreeTestReceipt' or receipt.get('status')!='PASS':
            raise ValueError('working tree validation did not pass')
        source=receipt['boundaries'][boundary]
        current=boundary_identity(boundary,'WORKTREE')
        if source!=current:raise ValueError('working tree source bytes changed')
        if receipt.get('schema_version') == '2':
            passed = _affected_retest_passes(receipt, boundary, current)
            controls = {
                'tests/architecture/test_affected_retest_receipts.py::test_original_failure_requires_exact_current_retest',
                'tests/architecture/test_affected_retest_receipts.py::test_retest_rejects_stale_runtime_and_test_identities',
            }
            if not controls <= passed:
                raise ValueError('current affected-retest verifier negative controls missing')
        else:
            passed=set()
            for run in receipt['runs']:
                if run['returncode']!=0 or run['source_unchanged'] is not True:
                    raise ValueError('validation command failed or source changed')
                path=pathlib.Path(run['junit_path'])
                raw=path.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=run['junit_sha256']:
                    raise ValueError('validation output hash mismatch')
                cases=list(ET.fromstring(raw).iter('testcase'))
                if not cases or any(c.find('failure') is not None or c.find('error') is not None for c in cases):
                    raise ValueError('validation output contains failures or no tests')
                for case in cases:
                    if case.find('skipped') is None:
                        passed.add(junit_nodeid(case))
        required=set(receipt['required_node_ids'][boundary])
        if not required or not required<=passed:raise ValueError('required boundary tests did not pass')
        if boundary=='kernel':
            manifest=json.loads((ROOT/'governance/test_coverage_manifest.json').read_text(encoding='utf-8'))
            mapped={c['nodeid'] for entry in manifest['sources'].values() for c in entry['test_cases']}
            if not mapped<=required:raise ValueError('mapped source tests absent from receipt')
        return {'boundary':boundary,'receipt':WORKTREE_RECEIPT,'status':'PASS',
            'current_boundary_hash':current['boundary_hash'],'test_node_ids':sorted(required),
            'scope':'offline source validation; historical product claims unchanged'}
    except (OSError,ValueError,KeyError,TypeError,RuntimeError,ET.ParseError) as exc:
        return {'boundary':boundary,'receipt':WORKTREE_RECEIPT,'status':'FAIL','reason':str(exc)}


def check_receipt(boundary: str, relative_path: str, *, current_commit: str = "WORKTREE") -> dict[str, Any]:
    if current_commit=='WORKTREE':
        return check_worktree_receipt(boundary)
    path = ROOT / relative_path
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        source_commit = str(receipt["source_commit"])
        source = boundary_identity(boundary, source_commit)
        current = boundary_identity(boundary, current_commit)
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        return {"boundary": boundary, "receipt": relative_path, "status": "FAIL", "reason": str(exc)}
    fresh = source["boundary_hash"] == current["boundary_hash"]
    return {
        "boundary": boundary,
        "receipt": relative_path,
        "status": "PASS" if fresh else "FAIL",
        "receipt_source_commit": source_commit,
        "receipt_boundary_hash": source["boundary_hash"],
        "current_boundary_hash": current["boundary_hash"],
    }


def check_all(*, current_commit: str = "WORKTREE") -> dict[str, Any]:
    results = [check_receipt(name, path, current_commit=current_commit) for name, path in RECEIPTS.items()]
    return {
        "kind": "CGKNReceiptFreshness",
        "schema_version": "1.0",
        "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
        "results": results,
    }


if __name__ == "__main__":
    value = check_all()
    print(json.dumps(value, indent=2))
    raise SystemExit(0 if value["status"] == "PASS" else 1)
