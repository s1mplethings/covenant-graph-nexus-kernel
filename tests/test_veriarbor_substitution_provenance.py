import json
from cgkn.state.provenance import ProvenanceGate
from tests.fixtures.provenance import setup, check


def test_mutable_cached_label_cannot_upgrade_raw_failure(tmp_path):
    f=setup(tmp_path,value=8,production=True)
    check(f)
    a=f['acceptance']
    assert a.view()['goals'][0]['verdict']=='FAILED'
    path=a.root/'goal_acceptance.json'
    raw=json.loads(path.read_text(encoding='utf-8'))
    raw['checks'][-1]['verdict']='VERIFIED'
    f['store'].atomic_json(path,raw)
    assert a.view()['goals'][0]['verdict']=='FAILED'
    assert not a.view()['complete']


def test_native_provenance_still_binds_current_artifacts(tmp_path):
    f=setup(tmp_path,value=7,production=True)
    check(f)
    gate=ProvenanceGate(f['store'],'p','r')
    assert gate.current(f['acceptance'])['status']=='TRUSTED'
    f['artifact'].write_text('{"value":8}',encoding='utf-8')
    assert not f['acceptance'].view()['complete']
