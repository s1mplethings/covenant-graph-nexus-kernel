import json
import pytest
from cgkn.providers import ModelRoleConfig,ProviderCompletion
from cgkn.protocol.compiler import TableSnapshot,compile_worker
from cgkn.protocol.exchange import exchange,SchemaRepairFailed
from cgkn.protocol.normalization import ContractError
from cgkn.agent.composer import AgentComposer,AgentDecisionContext
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.executors.llm import LLMExecutor
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.execution import BlockExecutionRequest,TaskContext,BlockStatus

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

class Fake:
 def __init__(self,packets):self.packets=list(packets);self.requests=[]
 def complete(self,**kwargs):
  self.requests.append(kwargs)
  value=self.packets.pop(0)
  if isinstance(value,Exception):raise value
  return ProviderCompletion(json.dumps(value),'actual-model',str(len(self.requests)),{'input_tokens':5,'output_tokens':7},routing={'actual_model':'actual-model'})

def table():return TableSnapshot({'paths':[{'path':'module.py','readable':True,'writable':True}]})

def run(client,trace):
 t=table()
 return exchange(client,ModelRoleConfig('worker','fixture'),system='bounded',context={'goal':'original'},snapshot=t,semantic_attempt_id='run:one',
  compiler=lambda p,h:compile_worker(p,t,bound_hash=h,node_id='n'),normalization={'integer_fields':['op','path']},trace=trace)

def test_correction_is_same_semantic_attempt_and_accounts_all_calls():
 client=Fake([{'op':2,'path':0},{'op':2,'path':0,'payload':'x=1'}]);events=[]
 result,final,stats=run(client,events.append)
 assert stats['semantic_decision_attempts']==1 and stats['schema_repair_attempts']==1
 assert len(stats['calls'])==2 and sum(x['usage']['output_tokens'] for x in stats['calls'])==14
 prompt=json.loads(client.requests[1]['user'])
 assert 'context' not in prompt and prompt['previous_packet']=={'op':2,'path':0}
 assert prompt['immutable_fields']==['op','path'] and events[-1]['semantic_diff']['changed_fields']==['payload']
 assert result['actions'][0]['content']=='x=1'

def test_two_corrections_max_then_replan():
 client=Fake([{'op':2,'path':0}]*3);events=[]
 with pytest.raises(SchemaRepairFailed) as e:run(client,events.append)
 assert len(client.requests)==3 and len(e.value.semantic_calls)==3 and e.value.repair_class=='R6'

def test_correction_cannot_change_valid_action():
 client=Fake([{'op':2,'path':0},{'op':0,'path':0}])
 with pytest.raises(ContractError,match='IMMUTABLE'):run(client,lambda e:None)
 assert len(client.requests)==2

def test_unknown_transport_never_corrected():
 from cgkn.providers.gateway_client import GatewayCompletionError
 client=Fake([GatewayCompletionError('outcome_unknown','unknown',outcome_unknown=True)])
 with pytest.raises(GatewayCompletionError):run(client,lambda e:None)
 assert len(client.requests)==1

def planner_table():
 return TableSnapshot({'nodes':[{'node_id':'n','parent_id':''}],'scopes':[{'path':'module.py'}],
  'capabilities':[{'capability_ref':'code@1','executor_ref':'llm.cheap@1','checker_ref':'source','task_kinds':[2],
  'acceptance_refs':['public_contract'],'effect_domains':['source_code']}],'sources':[]})

def test_existing_composer_returns_canonical_decision():
 packet={'action':1,'target':0,'task_kind':2,'scope':[0],'goal':'bounded','expected':['source'],'accept':['caller predicate'],'deps':[]}
 client=Fake([packet]);events=[]
 composer=AgentComposer(client,ModelRoleConfig('agent','fixture'),semantic_tables=lambda ctx:planner_table(),protocol_trace=events.append)
 ctx=AgentDecisionContext('p','r','goal',1,CapabilityTree('goal',()),('code@1',),{},{},{})
 result=composer.decide(ctx)
 assert result.edits[0].operation=='add_node' and result.edits[0].node_id=='n'
 assert result.provider['usage']['semantic_decision_attempts']==1
 assert events[0]['canonical_output']['edits'][0]['payload']['config']['leaf_contract']['checker_ref']=='source'

def request():
 contract=build_leaf_contract(goal='bounded source',kind='IMPLEMENTATION',scope=['module.py'],acceptance=['source'],checker='source',output_identity='source',effect_domains=['source'],executor='llm.cheap@1',expected_delta='source file')
 return BlockExecutionRequest(project_id='p',run_id='r',attempt_id='a',node_id='n',component_ref='code@1',executor_ref='llm.cheap@1',task_context=TaskContext('bounded source',{'leaf_contract':contract}))

def test_existing_worker_writes_real_file_and_sums_correction_usage(tmp_path):
 client=Fake([{'op':2,'path':0},{'op':2,'path':0,'payload':'value=7\n'}]);events=[]
 result=LLMExecutor(tmp_path,client,ModelRoleConfig('worker','fixture'),semantic_protocol=True,protocol_trace=events.append).execute(request())
 assert result.status is BlockStatus.SUCCEEDED and (tmp_path/'module.py').read_text()=='value=7\n'
 assert result.usage['input_tokens']==10 and result.usage['output_tokens']==14
 assert len(events)==2 and all(x['semantic_attempt_id']==events[0]['semantic_attempt_id'] for x in events)

def test_worker_exhaustion_preserves_actual_calls_and_no_artifact(tmp_path):
 client=Fake([{'op':2,'path':0}]*3);events=[]
 result=LLMExecutor(tmp_path,client,ModelRoleConfig('worker','fixture'),semantic_protocol=True,protocol_trace=events.append).execute(request())
 assert result.status is BlockStatus.FAILED and result.error.message=='SCHEMA_REPAIR_FAILED'
 assert result.usage['schema_repair_attempts']==2 and result.usage['output_tokens']==21
 assert not (tmp_path/'module.py').exists()

def test_safe_numeric_normalization_needs_no_provider_correction():
 client=Fake([{'op':'2','path':'0','payload':'x=1'}]);events=[]
 _,_,stats=run(client,events.append)
 assert stats['schema_repair_attempts']==0 and len(client.requests)==1


def test_tables_derive_only_from_model_design_and_existing_catalog():
 from cgkn.protocol.tables import planner_snapshot
 catalog={'code@1':{'executor_ref':'llm.cheap@1','checker_ref':'source','acceptance':['public_contract'],'effect_domains':['source'],'semantic_task_kinds':[2]}}
 ctx=AgentDecisionContext('p','r','goal',1,CapabilityTree('goal',()),('code@1',),catalog,{},{})
 design=[{'path':'model_chosen.py','purpose':'provider-chosen responsibility','interfaces':{'entry':'provider-defined'}}]
 snap=planner_snapshot(ctx,design)
 assert snap.document['scopes']==design and len(snap.document['nodes'])==8
 assert planner_snapshot(ctx,design).hash==snap.hash
 for path in ['../escape.py','C:/escape.py','/absolute.py','*.py']:
  with pytest.raises(ContractError):planner_snapshot(ctx,[{'path':path,'purpose':'same'}])

def test_unknown_extra_intent_never_normalized_to_authorization():
 client=Fake([{'op':2,'path':0,'payload':'x=1','publish':True}])
 with pytest.raises(ContractError):run(client,lambda e:None)
 assert len(client.requests)==1

def test_planner_schema_correction_does_not_consume_second_loop_decision(tmp_path):
 from cgkn.agent import AgentProjectLoop
 from cgkn.runtime import DAGRunner
 from cgkn.state import FileRunStore
 from cgkn.executors import ExecutorRegistry
 # Missing escalation reason is semantic, corrected within one Agent turn.
 client=Fake([{'action':8},{'action':8,'goal':'user decision required'}]);events=[]
 composer=AgentComposer(client,ModelRoleConfig('agent','fixture'),semantic_tables=lambda ctx:planner_table(),protocol_trace=events.append)
 store=FileRunStore(tmp_path)
 result=AgentProjectLoop(composer,DAGRunner(ExecutorRegistry(),store),store,known_capabilities={'code@1'},worker_model='fixture',max_decisions=1).run(project_id='p',run_id='r',goal='goal')
 assert result.decision_count==1 and len(client.requests)==2
 assert result.status=='BLOCKED' and result.escalation_reason=='user decision required'
 assert events[-1]['schema_repair_attempt']==1


def test_recorded_semantic_calls_keep_finish_reason_and_classification(tmp_path):
 from cgkn.providers.recording import RecordedCompletionClient
 from cgkn.state import FileRunStore
 class Complete:
  def complete(self,**kwargs):return ProviderCompletion('{"op":2,"path":0,"payload":"x=1"}','model','request',{'input_tokens':2,'output_tokens':3},raw_finish_reason='stop')
 store=FileRunStore(tmp_path);client=RecordedCompletionClient(Complete(),store,'p','r')
 run(client,lambda e:None)
 root=store.run_dir('p','r')/'provider_calls';response=json.loads(next(root.glob('*/response.json')).read_text())
 request=json.loads(next(root.glob('*/request.json')).read_text())
 assert response['raw_finish_reason']=='stop'
 assert json.loads(request['request']['user'])['call_kind']=='semantic_decision_attempt'

def test_planner_protocol_trace_serializes_real_nested_canonical_lists(tmp_path):
 from cgkn.state import FileRunStore
 packet={'action':1,'target':0,'task_kind':2,'scope':[0],'goal':'bounded','expected':['source'],'accept':['caller predicate'],'deps':[]}
 store=FileRunStore(tmp_path);events=[]
 def trace(event):
  store.immutable_json(tmp_path/'trace.json',event);events.append(event)
 composer=AgentComposer(Fake([packet]),ModelRoleConfig('agent','fixture'),semantic_tables=lambda ctx:planner_table(),protocol_trace=trace)
 ctx=AgentDecisionContext('p','r','goal',1,CapabilityTree('goal',()),('code@1',),{},{'status':'EMPTY'},{})
 composer.decide(ctx)
 saved=json.loads((tmp_path/'trace.json').read_text())
 assert saved['canonical_output']['edits'][0]['payload']['config']['leaf_contract']['task_kind']=='IMPLEMENTATION'


def test_invalid_dependency_correction_cannot_change_target():
 from cgkn.protocol.compiler import compile_planner
 table=planner_table();tree=CapabilityTree('goal',())
 packet={'action':1,'target':0,'task_kind':2,'scope':[0],'goal':'bounded','expected':['source'],'accept':['caller predicate'],'deps':[999]}
 with pytest.raises(ContractError) as e:compile_planner(packet,table,bound_hash=table.hash,tree=tree,context_identity='one')
 assert e.value.fields==('deps',) and e.value.repair_class=='R5'
 client=Fake([packet,{**packet,'deps':[]}]);events=[]
 _,_,stats=exchange(client,ModelRoleConfig('agent','fixture'),system='bounded',context={},snapshot=table,semantic_attempt_id='one',compiler=lambda p,h:compile_planner(p,table,bound_hash=h,tree=tree,context_identity='one'),normalization={},trace=events.append)
 prompt=json.loads(client.requests[-1]['user'])
 assert prompt['invalid_fields']==['deps'] and 'target' in prompt['immutable_fields']
 assert stats['schema_repair_attempts']==1

def test_public_tables_hide_canonical_encoding_but_keep_numeric_rows():
 table=planner_table();public=table.public_document
 assert public['nodes'][0]=={'id':0,'label':'node'}
 assert public['capabilities'][0]=={'id':0,'task_kinds':[2],'label':'capability'}
 assert table.document['nodes'][0]['node_id']=='n'
 assert public['scopes'][0]=={'id':0,'path':'module.py','label':'module.py'}
 assert public['compatibility']==[{'capability_id':0,'allowed_scope_ids':[0]}]
 assert 'capability_ref' not in json.dumps(public)
 public['nodes'][0]['id']=99
 assert table.public_document['nodes'][0]['id']==0


def test_real_exchange_initial_and_correction_only_expose_public_table():
 client=Fake([{'op':2,'path':99},{'op':2,'path':0,'payload':'x=1'}])
 # First correction may only fix path; trying to add unrelated payload is R6.
 with pytest.raises(ContractError,match='IMMUTABLE'):run(client,lambda e:None)
 for req in client.requests:
  prompt=json.loads(req['user']);assert prompt['tables']['paths'][0]['id']==0
 assert json.loads(client.requests[1]['user'])['exact_error']['fields']==['path']
