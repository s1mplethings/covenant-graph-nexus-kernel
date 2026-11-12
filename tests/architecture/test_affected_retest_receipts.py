import copy
import hashlib
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import receipt_freshness as receipts


def batch(tmp_path, name, failed, snapshot, case='test_fixture'):
    child='<failure>original failure</failure>' if failed else ''
    raw=('<testsuite><testcase classname="tests.fixture" name="'+case+'">'+child+'</testcase></testsuite>').encode()
    p=tmp_path/(name+'.xml');p.write_bytes(raw)
    return {'returncode':int(failed),'source_unchanged':True,'boundaries':{'kernel':snapshot},
            'junit_path':str(p),'junit_sha256':hashlib.sha256(raw).hexdigest()}


def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(receipts,'ROOT',tmp_path)
    (tmp_path/'tests').mkdir();(tmp_path/'tests/fixture.py').write_text('# fixture')
    current={'files':{'cgkn/runtime/core.py':'runtime','tests/fixture.py':'new'}}
    old={'files':{'cgkn/runtime/core.py':'runtime','tests/fixture.py':'old'}}
    node='tests/fixture.py::test_fixture'
    doc={'runs':[batch(tmp_path,'red',True,old),batch(tmp_path,'green',False,current)],
         'retest_verifier_controls':[node]}
    return doc,current,node


def test_original_failure_requires_exact_current_retest(tmp_path,monkeypatch):
    doc,current,node=fixture(tmp_path,monkeypatch)
    assert receipts._affected_retest_passes(doc,'kernel',current)=={node}
    assert '<failure>' in Path(doc['runs'][0]['junit_path']).read_text()
    for mutation in ('missing','other_case','tampered','non_test_exit','skip'):
        bad=copy.deepcopy(doc)
        if mutation=='missing':bad['runs'].pop()
        elif mutation=='other_case':bad['runs'][-1]=batch(tmp_path,'other',False,current,'different')
        elif mutation=='tampered':bad['runs'][-1]['junit_sha256']='fake'
        elif mutation=='non_test_exit':bad['runs'][-1]['returncode']=2
        else:
            p=tmp_path/'skip.xml';p.write_text('<testsuite><testcase classname="tests.fixture" name="test_fixture"><skipped/></testcase></testsuite>')
            bad['runs'][-1].update(junit_path=str(p),junit_sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        with pytest.raises(ValueError):receipts._affected_retest_passes(bad,'kernel',current)


def test_retest_rejects_stale_runtime_and_test_identities(tmp_path,monkeypatch):
    doc,current,node=fixture(tmp_path,monkeypatch)
    for mutation in ('runtime','test','changed_during_run','no_controls','exit_mismatch'):
        bad=copy.deepcopy(doc)
        if mutation=='runtime':bad['runs'][0]['boundaries']['kernel']['files']['cgkn/runtime/core.py']='stale'
        elif mutation=='test':bad['runs'][-1]['boundaries']['kernel']['files']['tests/fixture.py']='stale'
        elif mutation=='changed_during_run':bad['runs'][-1]['source_unchanged']=False
        elif mutation=='no_controls':bad['retest_verifier_controls']=[]
        else:bad['runs'][0]['returncode']=0
        with pytest.raises(ValueError):receipts._affected_retest_passes(bad,'kernel',current)
