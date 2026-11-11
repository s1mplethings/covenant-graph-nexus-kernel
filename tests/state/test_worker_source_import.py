"""Authorship import controls; current business acceptance stays independent."""
import copy,json,hashlib
from pathlib import Path
import pytest
from cgkn.state import FileRunStore
from cgkn.state.provenance import ProvenanceGate,ProvenanceError,reference
from cgkn.state.acceptance import identity


def setup(tmp_path,real=True):
 source=FileRunStore(tmp_path/'old');dest=FileRunStore(tmp_path/'new')
 old=ProvenanceGate(source,'p','old');new=ProvenanceGate(dest,'p','new')
 for gate in [old,new]:gate.store.immutable_json(gate.root/'provenance_contract.json',{'kind':'ProvenanceContract','logical_task_id':'p/'+gate.run_id,'requirements':{},'goals':{}})
 workspace=tmp_path/'workspace';workspace.mkdir();(workspace/'module.py').write_text('value = 7\n')
 staged=old.root/'candidates/worker/a/module.py';staged.parent.mkdir(parents=True);staged.write_bytes((workspace/'module.py').read_bytes());digest=hashlib.sha256(staged.read_bytes()).hexdigest()
 raw={'project_id':'p','run_id':'old','node_id':'worker','attempt_id':'a','executor_ref':'llm.cheap@1','status':'SUCCEEDED','error':None}
 rawpath=old.root/'execution_receipts/worker/a.json';source.immutable_json(rawpath,raw)
 receipt={**raw,'metadata':{'deliverable_verdict':'VERIFIED','raw_execution_receipt_ref':reference(source.root,rawpath),
  'deliverable_check':{'verdict':'VERIFIED','subjects':{'module.py':digest},'verified_artifacts':{'module.py':{'path':str(staged),'sha256':digest}}}},
  'usage':{'completion_calls':[{'request_id':'req'}]}}
 receiptpath=old.root/'attempts/worker/a.json';source.immutable_json(receiptpath,receipt)
 request={'identity':'call-identity','transport_kind':'recorded_gateway' if real else 'fake','config':{'role':'worker','model':'provider','model_id':'concrete'}}
 response={'identity':'call-identity','request_id':'req','model':'concrete','routing':{'identity_status':'MATCH','provider_id':'provider','actual_model':'concrete','requested_model':'concrete','bound_model':'concrete'}}
 call=old.root/'provider_calls/call';source.immutable_json(call/'request.json',request);source.immutable_json(call/'response.json',response)
 from cgkn.orchestration import CapabilityTree
 dest.immutable_json(new.root/'capability_tree.json',CapabilityTree('fixture',()).as_dict())
 return old,new,workspace,receiptpath,call,digest


def register(f):
 old,new,workspace,path,_,_=f
 return new.register_worker_import(old,reference(old.store.root,path),'module.py',workspace,reason='Explicit reuse of exact original Worker bytes')


def test_import_is_idempotent_read_only_and_not_a_new_call(tmp_path,monkeypatch):
 f=setup(tmp_path);old,new,workspace,_,_,digest=f
 before={p.relative_to(old.root).as_posix():p.read_bytes() for p in old.root.rglob('*') if p.is_file()}
 ref=register(f);assert register(f)==ref
 assert before=={p.relative_to(old.root).as_posix():p.read_bytes() for p in old.root.rglob('*') if p.is_file()}
 assert not (new.root/'provider_calls').exists()
 doc=json.loads(new.resolve(ref));origin=new._worker_import_origin(doc,workspace,digest)
 assert origin['source_run_id']=='old' and not origin['old_acceptance_imported']
 assert origin['provider_calls'][0]['real_provider_identity_bound']
 # Unit-test the source projection with current acceptance supplied separately.
 monkeypatch.setattr(new,'current',lambda a:{'acceptance':{'complete':True},'chains':['current-independent-check']})
 result=new.delivery_sources(None,workspace,{'module.py':digest})
 assert result['status']=='TRUSTED' and result['real_provider_backed']
 assert result['acceptance_chains']==['current-independent-check'] and not result['delivery_authorized']
 with pytest.raises(ProvenanceError,match='lacks bounded Worker origin'):
  new.delivery_sources(None,workspace,{'module.py':digest,'unowned.py':'x'})


def test_import_never_supplies_missing_current_acceptance(tmp_path):
 f=setup(tmp_path);register(f);_,new,workspace,_,_,digest=f
 class Unchecked:
  requirements={}
  def view(self):return {'complete':False,'goals':[]}
 with pytest.raises(ProvenanceError,match='no current checks'):
  new.delivery_sources(Unchecked(),workspace,{'module.py':digest})


def test_fake_provider_origin_cannot_become_real(tmp_path):
 f=setup(tmp_path,real=False);ref=register(f);_,new,workspace,_,_,digest=f
 origin=new._worker_import_origin(json.loads(new.resolve(ref)),workspace,digest)
 assert not origin['provider_calls'][0]['real_provider_identity_bound']


@pytest.mark.parametrize('attack',['failed','unknown','unverified','wrong_subject','wrong_staged_hash','raw_failure','raw_identity','agent_role','model_mismatch','call_identity','missing_response','duplicate_response','escaped_staging'])
def test_invalid_source_cannot_register(tmp_path,attack):
 f=setup(tmp_path);old,new,workspace,path,call,digest=f
 receipt=json.loads(path.read_text());rawpath=old.root/'execution_receipts/worker/a.json'
 if attack=='failed':receipt['status']='FAILED'
 if attack=='unknown':receipt['error']={'details':{'outcome_unknown':True}}
 if attack=='unverified':receipt['metadata']['deliverable_verdict']='UNRESOLVED'
 if attack=='wrong_subject':receipt['metadata']['deliverable_check']['subjects']['module.py']='b'*64
 if attack=='wrong_staged_hash':receipt['metadata']['deliverable_check']['verified_artifacts']['module.py']['sha256']='b'*64
 if attack=='escaped_staging':receipt['metadata']['deliverable_check']['verified_artifacts']['module.py']['path']=str(workspace/'module.py')
 if attack in {'raw_failure','raw_identity'}:
  raw=json.loads(rawpath.read_text());raw['status' if attack=='raw_failure' else 'node_id']='FAILED' if attack=='raw_failure' else 'different'
  rawpath.write_text(json.dumps(raw));receipt['metadata']['raw_execution_receipt_ref']=reference(old.store.root,rawpath)
 path.write_text(json.dumps(receipt))
 if attack=='agent_role':
  r=json.loads((call/'request.json').read_text());r['config']['role']='agent';(call/'request.json').write_text(json.dumps(r))
 if attack in {'model_mismatch','call_identity'}:
  r=json.loads((call/'response.json').read_text());r['model' if attack=='model_mismatch' else 'identity']='wrong';(call/'response.json').write_text(json.dumps(r))
 if attack=='missing_response':(call/'response.json').unlink()
 if attack=='duplicate_response':old.store.immutable_json(old.root/'provider_calls/duplicate/response.json',json.loads((call/'response.json').read_text()))
 with pytest.raises(ProvenanceError):register(f)
 assert not list((new.root/'source_imports').glob('*.json'))
 assert hashlib.sha256((workspace/'module.py').read_bytes()).hexdigest()==digest


@pytest.mark.parametrize('field',['receipt_ref','raw_execution_ref','candidate_ref','request_ref','response_ref'])
def test_copied_evidence_tamper_is_rejected(tmp_path,field):
 f=setup(tmp_path);ref=register(f);_,new,workspace,_,_,digest=f;doc=json.loads(new.resolve(ref))
 item=doc[field] if field in doc else doc['provider_calls'][0][field]
 path=new.store.root/item['path'];path.write_bytes(path.read_bytes()+b' ')
 with pytest.raises(ProvenanceError,match='hash mismatch'):
  new._worker_import_origin(doc,workspace,digest)


def test_current_bytes_and_manifest_tamper_fail_closed(tmp_path,monkeypatch):
 f=setup(tmp_path);ref=register(f);_,new,workspace,_,_,digest=f;doc=json.loads(new.resolve(ref))
 (workspace/'module.py').write_text('value=99\n')
 with pytest.raises(ProvenanceError,match='current artifact mismatch'):
  new._worker_import_origin(doc,workspace,digest)
 monkeypatch.setattr(new,'current',lambda a:{'acceptance':{'complete':True},'chains':[]})
 doc['reason']='changed';(new.store.root/ref['path']).write_text(json.dumps(doc))
 with pytest.raises(ProvenanceError,match='manifest changed'):
  new.delivery_sources(None,workspace,{'module.py':digest})
