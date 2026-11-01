import json
import pytest
from cgkn.protocol.normalization import normalize,ContractError,preserve_valid_fields
from cgkn.protocol.compiler import TableSnapshot,compile_worker,compile_planner
from cgkn.orchestration.capability_tree import CapabilityTree

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def tables():
 return TableSnapshot({'paths':[{'path':'module.py','readable':True,'writable':True},{'path':'dependency.py','readable':True,'writable':False}],
  'nodes':[{'node_id':'node-1','parent_id':''},{'node_id':'node-2','parent_id':''}],
  'scopes':[{'path':'module.py'}],
  'capabilities':[{'capability_ref':'code@1','executor_ref':'llm.cheap@1','checker_ref':'source','task_kinds':[2,3],
    'acceptance_refs':['public_contract'],'effect_domains':['source_code']}], 'sources':[]})

def valid():return {'action':1,'task_kind':2,'target':0,'goal':'Produce specified function','scope':[0],'expected':['Function source exists'],'accept':['Function preserves caller input'],'deps':[]}

def compile(p,t=None):
 t=t or tables();return compile_planner(p,t,bound_hash=t.hash,tree=CapabilityTree('goal',()),context_identity='run:decision1')

@pytest.mark.parametrize('text', ['{ "action": 2 }','```json\n{"action":2}\n```','{"action":2,}','{"action":"2"}'])
def test_safe_form_normalization(text):
 value,receipt=normalize(text,integer_fields=['action']);assert value=={'action':2};assert receipt['semantics_changed'] is False

@pytest.mark.parametrize('text', ['[,]','{"a":1,"a":2}','{"a":','```json\n{}','NaN','[]','{"a":Infinity}'])
def test_unsafe_syntax_closed(text):
 with pytest.raises(ContractError):normalize(text)

def test_code_payload_not_normalized():
 raw='  x = "a,}"\r\n  '
 value,_=normalize(json.dumps({'payload':raw})[:-1]+',}')
 assert value['payload']==raw

@pytest.mark.parametrize('ids,expected',[(0,[0]),(['2','1',1],[1,2]),([0],[0]),([] ,[])])
def test_declared_id_sets(ids,expected):
 value,_=normalize(json.dumps({'scope':ids}),list_fields=['scope']);assert value['scope']==expected

def test_alias_collision_closed():
 with pytest.raises(ContractError):normalize('{"operation":1,"action":1}',aliases={'operation':'action'})

def test_missing_semantics_not_filled():
 value,_=normalize('{}');assert value=={}
 for field in ['goal','expected','accept']:
  p=valid();p.pop(field)
  with pytest.raises(ContractError) as e:compile(p)
  assert e.value.repair_class=='R5'

def test_worker_compiles_only_authorized_paths():
 t=tables();p=compile_worker({'op':2,'path':0,'payload':'x=1'},t,bound_hash=t.hash,node_id='n')
 assert p['actions']==[{'action':'write_file','path':'module.py','content':'x=1'}]
 for index in [1,2,-1,True,'0']:
  with pytest.raises(ContractError):compile_worker({'op':2,'path':index,'payload':'x=1'},t,bound_hash=t.hash,node_id='n')

@pytest.mark.parametrize('op',[0,1,2,3])
def test_stale_table_always_closed(op):
 t=tables()
 with pytest.raises(ContractError,match='STALE_TABLE'):compile_worker({'op':op,'path':0},t,bound_hash='stale',node_id='n')

@pytest.mark.parametrize('payload',[None,{},42,True,[],{'content':'x'}])
def test_no_payload_inference(payload):
 t=tables()
 with pytest.raises(ContractError):compile_worker({'op':2,'path':0,'payload':payload},t,bound_hash=t.hash,node_id='n')

def test_compile_deterministic_and_canonical():
 a=compile(valid());b=compile(valid());assert a==b
 c=a['edits'][0].payload['config'];assert tuple(c['semantic_acceptance'])==tuple(valid()['accept']);assert c['leaf_contract']['schema_version']=='1.0'

@pytest.mark.parametrize('key,value',[('target',9),('target',True),('scope',[99]),('scope',[True]),('task_kind',99),('task_kind',False),('action',99),('action',True),('deps',[99]),('capability',99),('confidence',True),('confidence',2),('needs_user','false')])
def test_invalid_ids_and_types_closed(key,value):
 p=valid();p[key]=value
 with pytest.raises(ContractError):compile(p)

def test_cycle_not_repaired():
 p=valid();p['deps']=[0]
 with pytest.raises(ContractError) as e:compile(p)
 assert e.value.repair_class=='R6'

def test_unauthorized_side_effect_closed():
 d=tables().document;d['capabilities'][0]['external_effect']=True
 with pytest.raises(ContractError,match='UNAUTHORIZED'):compile(valid(),TableSnapshot(d))

def test_correction_immutable_semantics():
 before=valid();after={**before,'goal':'different goal'}
 with pytest.raises(ContractError) as e:preserve_valid_fields(before,after,['scope'])
 assert e.value.repair_class=='R6'
 assert preserve_valid_fields(before,{**before,'scope':[1]},['scope'])['unrelated_fields_changed']==0

def test_snapshot_immutable():
 t=tables();d=t.document;d['paths'][0]['path']='other.py';assert t.row('paths',0)['path']=='module.py'

def test_oversized_closed():
 with pytest.raises(ContractError):normalize('x'*262145)


def test_mutated_snapshot_cannot_keep_old_hash():
 t=tables();t._json=json.dumps({'paths':[{'path':'other','writable':True}]})
 with pytest.raises(ContractError,match='STALE_TABLE'):compile_worker({'op':2,'path':0,'payload':'x'},t,bound_hash=t.hash,node_id='n')

@pytest.mark.parametrize('path',['../x','/tmp/x','C:/x','.git/config','*','x\\y'])
def test_compiler_rejects_unsafe_registry_path(path):
 t=TableSnapshot({'paths':[{'path':path,'readable':True,'writable':True}]})
 with pytest.raises(ContractError):compile_worker({'op':2,'path':0,'payload':'x'},t,bound_hash=t.hash,node_id='n')
