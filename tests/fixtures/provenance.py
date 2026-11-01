"""Host-authored evidence calibration; never production capability samples."""
from pathlib import Path
import json
from cgkn.state import FileRunStore
from cgkn.state.acceptance import GoalAcceptance,identity
from cgkn.state.provenance import put_evidence,reference,file_hash
from cgkn.executors.measurement import FileMeasurementExecutor,EvidenceBoundExecutor
from cgkn.execution import BlockExecutionRequest,TaskContext,BlockExecutionResult,BlockStatus
from cgkn.orchestration.capability_tree import CapabilityTree

CONFIG={'actual_model':'fixture-model','model_version':'fixture-v1','task_family':'fixture','difficulty':'tiny','tools':'local','context':'public','repair_protocol':'bounded'}
def setup(root,value=7,production=False,continuation=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    artifact=root/'candidate.json';artifact.write_text(json.dumps({'value':value}),encoding='utf-8')
    store=FileRunStore(root/'state');run=store.run_dir('p','r')
    requirements={'R':{'must':True,'version':'1','source':'public','scope':'object','weight':1}}
    source=Path(__file__).resolve().parents[2]/'cgkn/executors/measurement.py'
    input_ref=put_evidence(store,'p','r',{'kind':'PublicInput','text':'value must equal 7','version':'1'})
    environment_ref=put_evidence(store,'p','r',{'kind':'ToolEnvironment','python':'fixture','protocol':'1'})
    binding={'kind':'ProvenanceContract','logical_task_id':'task','requirements':requirements,'input_ref':input_ref,'environment_ref':environment_ref,'configuration':CONFIG,'provider_id':'fixture','checker_bindings':{'c':'measure.file@1'},'pricing':{'currency':'CNY','version':'fixture','input_per_million':20,'output_per_million':60},'metrics':{'time_reference':10,'cost_reference':1,'quantile':.05},'goals':{'g':{'requirement_refs':['R'],'checker_ref':'measure.file@1','checker_hash':file_hash(source),'checker_version':'1.0','predicate':{'operator':'equal','expected':7},'condition_hash':identity({'operator':'equal','expected':7})}}}
    if production:binding.update(require_artifact_lineage=True,current_artifacts={'object':str(artifact)})
    if continuation:binding['continuation']=continuation
    store.immutable_json(run/'provenance_contract.json',binding)
    a=GoalAcceptance(store,'p','r',requirements,{'c':'measure.file@1'});a.bind_subjects({'object':file_hash(artifact)})
    goal={'id':'g','requirement_refs':['R'],'phase_id':'p','subject_refs':['object'],'checker':'c','checker_version':'1.0','acceptance':{'operator':'equal','expected':7},'task_refs':[]}
    a.commit(a.propose({'phases':[{'id':'p','depends_on':[]}],'goals':[goal]},CapabilityTree('fixture',())))
    ctx={'root':root,'store':store,'acceptance':a,'artifact':artifact,'source':source,'goal':goal,'binding':binding}
    return ctx

def check(f,value=None,attempt='attempt-0001',node='checker'):
    if value is not None:f['artifact'].write_text(json.dumps({'value':value}),encoding='utf-8')
    h=file_hash(f['artifact']);a=f['acceptance'];a.bind_subjects({'object':h})
    contracts={'c':{'goal_id':'g','version':'1','path':'candidate.json','field':'value','subject':'object','artifact_sha256':h,'predicate':{'operator':'equal','expected':7}}}
    executor=EvidenceBoundExecutor(FileMeasurementExecutor(f['root'],contracts),f['store'],f['source'],{'object':f['artifact']},'candidate',attempt)
    req=BlockExecutionRequest(project_id='p',run_id='r',node_id=node,attempt_id=attempt,component_ref='measure.file@1',executor_ref='measure.file@1',input_values={'contract_id':'c'},task_context=TaskContext(node_goal='controlled measurement'))
    result=executor.execute(req);f['store'].save_result(result);a.record('g',result,executor_ref='measure.file@1');return result

def sample(f,revision=1,provider=True,unknown=False):
    store=f['store'];a=f['acceptance'];a._reload();run=store.run_dir('p','r')
    snapshot=put_evidence(store,'p','r',{'kind':'AcceptanceSnapshot','state':a.data})
    time_ref=put_evidence(store,'p','r',{'kind':'TaskTiming','logical_task_id':'task','ready_unix':0,'finished_unix':10,'measurement':{'ready':0,'ended':10,'now':10,'clock_id':'fixture','intervals':[{'start':0,'end':8,'clock_id':'fixture','category':'provider_wait_time'},{'start':8,'end':10,'clock_id':'fixture','category':'acceptance_time'}]}})
    refs=[]
    if provider:
        call='fixture-call'
        req=run/'provider_calls'/call/'request.json';resp=req.with_name('response.json')
        store.immutable_json(req,{'identity':call,'started_at':0,'config':{'model':'fixture','model_id':'fixture-model'},'request':{'fixture':True}})
        store.immutable_json(resp,{'identity':call,'ended_at':8,'request_id':'upstream-fixture','model':'fixture-model','text':'{"fixture":true}','usage':{} if unknown else {'input_tokens':100,'output_tokens':100},'routing':{'actual_model':'fixture-model','requested_model':'fixture-model','identity_status':'MATCH'}})
        result=BlockExecutionResult(project_id='p',run_id='r',node_id='worker',attempt_id='attempt-0001',executor_ref='llm.cheap@1',status=BlockStatus.SUCCEEDED,usage={'model':'fixture-model','request_id':'upstream-fixture'},metadata={'proposal':{'fixture':True},'artifact_hashes':{'object':file_hash(f['artifact'])}})
        path=run/'attempts/worker/attempt-0001.json'
        if not path.exists():store.save_result(result)
        refs=[put_evidence(store,'p','r',{'kind':'ProviderWitness','logical_task_id':'task','call_id':call,'request_ref':reference(store.root,req),'response_ref':reference(store.root,resp),'execution_ref':reference(store.root,path)})]
    y=1 if a.view()['complete'] else 0
    row={'kind':'MetricRevision','task_id':'task','configuration':CONFIG,'revision':revision,'supersedes':revision-1 if revision>1 else None,'acceptance_ref':snapshot,'time_ref':time_ref,'provider_refs':refs,'business':y,'delivery':y,'first_pass':revision==1 and y==1,'repair_count':revision-1}
    return put_evidence(store,'p','r',row)
