import json,copy
import pytest
from cgkn.protocol.compiler import TableSnapshot,compile_planner
from cgkn.protocol.admission import strip_proven_mechanical
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.exchange import exchange
from cgkn.orchestration import CapabilityTree
from cgkn.providers import ProviderCompletion,ModelRoleConfig
from tests.protocol.test_repair_path import snapshot,packet

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def split():return {'action':2,'target':2,'goal_ref':0,'children':[packet(),{**packet(),'target':1,'scope':[1]}]}
def table():
 d=snapshot().document;d['goals']=[{'goal_id':'G','covered_artifact_paths':['module.py','tests.py']}];return TableSnapshot(d)

def test_v2_split_semantics_survive_correction_preflight_unchanged():
 p=split();before=copy.deepcopy(p);normalized,receipts=strip_proven_mechanical(p,table())
 assert normalized==before==p and receipts==[]

def test_real_exchange_missing_target_can_correct_without_losing_children():
 final=split();first={k:v for k,v in final.items() if k!='target'};calls=[];events=[];s=table();t=CapabilityTree('goal',())
 class Client:
  def complete(self,**kwargs):
   calls.append(kwargs);return ProviderCompletion(json.dumps(first if len(calls)==1 else final),'fake','r'+str(len(calls)),{'input_tokens':10,'output_tokens':10},raw_finish_reason='stop')
 def compiler(p,h):
  result=compile_planner(p,s,bound_hash=h,tree=t,context_identity='correction')
  return {'nodes':[e.node_id for e in result['edits']]}
 result,_,stats=exchange(Client(),ModelRoleConfig('agent','fake'),system='bounded split',context={'tables':s.public_document},snapshot=s,semantic_attempt_id='split-correction',compiler=compiler,normalization={},trace=events.append)
 assert len(calls)==2 and stats['schema_repair_attempts']==1
 assert set(result['nodes'])=={'n','sibling','inspect'}
 assert not t.nodes

def test_legacy_fields_are_not_silently_expanded():
 d=table().document;d['action_version']=1
 with pytest.raises(ContractError,match='UNEXPECTED_PLANNER_FIELDS'):strip_proven_mechanical(split(),TableSnapshot(d))

def test_unknown_field_still_rejected_without_dropping_it():
 p={**split(),'override_acceptance':True}
 with pytest.raises(ContractError,match='UNEXPECTED_PLANNER_FIELDS'):strip_proven_mechanical(p,table())
 assert p['override_acceptance'] is True

def test_v2_failed_acceptance_ids_are_preserved_as_semantics():
 p={**packet(),'action':4,'task_kind':3,'failed_acceptance_ids':['G']}
 assert strip_proven_mechanical(p,table())[0]==p
