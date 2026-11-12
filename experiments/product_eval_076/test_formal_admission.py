import json
import pathlib
import pytest
from experiments.product_eval_076.formal_contract import validate,sha,REQUIRED
from experiments.product_eval_076.runner import run_route

def seal(tmp_path):
 artifact=tmp_path/'public.txt';artifact.write_text('public input')
 receipt=tmp_path/'check.json';receipt.write_text('{"status":"PASS"}')
 value={'status':'FROZEN','evidence':{k:{'status':'PASS','path':str(receipt),'sha256':sha(receipt)} for k in REQUIRED},'source_hashes':{},'artifact_hashes':{str(artifact):sha(artifact)},'matrix':[{'run_id':'r','route':'R_DIRECT'}]}
 p=tmp_path/'seal.json';p.write_text(json.dumps(value));return p,artifact,receipt

def test_changed_public_input_refused(tmp_path):
 p,a,_=seal(tmp_path);validate(p,'r','R_DIRECT');a.write_text('changed')
 with pytest.raises(RuntimeError,match='ARTIFACT_CHANGED'):validate(p,'r','R_DIRECT')

def test_changed_gate_receipt_refused(tmp_path):
 p,_,r=seal(tmp_path);r.write_text('{"status":"FAIL"}')
 with pytest.raises(RuntimeError,match='EVIDENCE_CHANGED'):validate(p,'r','R_DIRECT')

def test_unregistered_route_refused(tmp_path):
 p,_,_=seal(tmp_path)
 with pytest.raises(RuntimeError,match='NOT_REGISTERED'):validate(p,'r','R_CGNK')

def test_formal_replay_refused_before_environment_creation(tmp_path):
 class Replay:is_replay=True
 with pytest.raises(RuntimeError,match='LIVE_PROVIDER_REQUIRED'):
  run_route(root=tmp_path/'must-not-exist',run_id='r',route='R_DIRECT',image='unavailable',client=Replay(),goal='irrelevant',mode='FORMAL')
 assert not (tmp_path/'must-not-exist').exists()
