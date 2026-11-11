import json
import pytest
from cgkn.state.provenance import ProvenanceGate, ProvenanceError
from tests.fixtures.provenance import setup, check


def test_view_loads_binding_twice_and_revalidates_next_view(tmp_path, monkeypatch):
    f=setup(tmp_path,production=True);check(f);calls=[];original=ProvenanceGate._load_binding
    def counted(self):
        calls.append(self.run_id);return original(self)
    monkeypatch.setattr(ProvenanceGate,'_load_binding',counted)
    assert f['acceptance'].view()['complete'];assert len(calls)==2
    f['artifact'].write_text('{"value":8}')
    assert not f['acceptance'].view()['complete'];assert len(calls)==4


def test_mid_view_binding_change_never_returns_verified(tmp_path, monkeypatch):
    f=setup(tmp_path);check(f);original=ProvenanceGate.verify_check
    path=f['store'].run_dir('p','r')/'provenance_contract.json';before=path.read_bytes()
    def changed(self,*args):
        result=original(self,*args);body=json.loads(path.read_text());body['logical_task_id']='changed';path.write_text(json.dumps(body));return result
    monkeypatch.setattr(ProvenanceGate,'verify_check',changed)
    view=f['acceptance'].view();assert not view['complete'];assert view['goals'][0]['verdict']=='INSUFFICIENT_EVIDENCE'
    monkeypatch.setattr(ProvenanceGate,'verify_check',original);path.write_bytes(before)
    assert f['acceptance'].view()['complete']


def test_snapshot_does_not_cache_or_trust_changed_receipts(tmp_path):
    f=setup(tmp_path);r=check(f);gate=ProvenanceGate(f['store'],'p','r')
    with gate.read_binding_snapshot():
        b=gate.binding();b['logical_task_id']='forged'
        assert gate.binding()['logical_task_id']=='task'
        assert gate.verify_check(r,f['goal'],f['acceptance'].data['subjects'])['status']=='TRUSTED'
        path=gate.root/'attempts/checker/attempt-0001.json';body=json.loads(path.read_text());body['outputs']['goal_check']['verdict']='FAILED';path.write_text(json.dumps(body))
        assert gate.verify_check(r,f['goal'],f['acceptance'].data['subjects'])['status']!='TRUSTED'
    assert gate._binding_snapshot is None


def test_snapshot_cleans_up_on_exception_and_rejects_nesting(tmp_path):
    f=setup(tmp_path);gate=ProvenanceGate(f['store'],'p','r')
    with pytest.raises(RuntimeError):
        with gate.read_binding_snapshot():raise RuntimeError('control')
    assert gate._binding_snapshot is None
    with gate.read_binding_snapshot():
        with pytest.raises(ProvenanceError,match='nested'):
            with gate.read_binding_snapshot():pass
    with gate.read_binding_snapshot():assert gate.binding()['logical_task_id']=='task'
