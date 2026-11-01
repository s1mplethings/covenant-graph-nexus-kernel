"""Local real-file/process witness through production DAG and bounded Worker."""
import hashlib,json,subprocess,sys
import pytest
from tests.protocol.test_repair_path import snapshot,registry,packet,repair_packet,run,failed_snapshot,plain
from cgkn.protocol.compiler import TableSnapshot
from cgkn.orchestration import CapabilityTree,compile_tree
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.providers import ModelRoleConfig,ProviderCompletion
from cgkn.executors import ExecutorRegistry
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.executors.llm import LLMExecutor
from cgkn.execution import BlockExecutionResult,BlockStatus
from cgkn.execution.deliverables import FileDeliverableChecker,SubjectDeliverableChecker
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.state.repair import TargetedRepairVerification,record_repair_phase

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def test_real_dag_worker_repair_targeted_recheck_sibling_reuse_and_recovery(tmp_path):
    work=tmp_path/'work';work.mkdir();store=FileRunStore(tmp_path/'state');calls=[];checks=[]
    class Client:
        def complete(self,**kw):
            prompt=json.loads(kw['user']);pack=prompt['context'];path=pack['allowed_write_paths'][0]
            calls.append((path,pack));is_repair=bool(pack['failed_acceptance_ids'])
            value=4 if is_repair or path=='tests.py' else 1
            table=prompt['tables']['paths'];key=next(x['id'] for x in table if x['path']==path)
            return ProviderCompletion(json.dumps({'op':2,'path':key,'payload':f'value = {value}\n'}),'fake-model',str(len(calls)),{'input_tokens':1,'output_tokens':1})
    def subject():return {'project':hashlib.sha256(b''.join(p.read_bytes() for p in sorted(work.glob('*.py')))).hexdigest()}
    def probe(ids):
        process=subprocess.run([sys.executable,'-c','import runpy,json; print(json.dumps({"A-field":runpy.run_path("module.py")["value"]==4,"sibling":runpy.run_path("tests.py")["value"]==4}))'],cwd=work,capture_output=True,text=True)
        assert process.returncode==0
        values=json.loads(process.stdout);checks.append(list(ids));path=store.run_dir('p','r')/'observations'/f'{len(checks)}.json'
        store.immutable_json(path,{'stdout':process.stdout,'stderr':process.stderr,'exit_code':process.returncode})
        return {'passed':all(values[k] for k in ids),'checks':{k:values[k] for k in ids},'evidence_refs':[str(path)]}
    class Consumer:
        descriptor=ExecutorDescriptor('verify@1','deterministic',('verify',),())
        def execute(self,request):
            if len(calls)>2:
                observed=TargetedRepairVerification(probe,lambda:probe(['A-field','sibling'])).execute(['A-field'],
                    record=lambda phase,data:record_repair_phase(store,'p','r','n',phase,data))
            else:observed=probe(['A-field','sibling'])
            return BlockExecutionResult(project_id='p',run_id='r',node_id=request.node_id,attempt_id=request.attempt_id,
                executor_ref=request.executor_ref,status=BlockStatus.SUCCEEDED,outputs={'observation':observed})
    traces=[]
    def trace(event):
        store.immutable_json(store.run_dir('p','r')/'protocol'/f'{len(traces)}.json',plain(event));traces.append(event)
    reg=ExecutorRegistry();reg.register(LLMExecutor(work,Client(),ModelRoleConfig('worker','fake'),semantic_protocol=True,protocol_trace=trace));reg.register(Consumer())
    reg.register(FileDeliverableChecker(work,{'public':lambda root,c:{'passed':all((root/p).is_file() for p in c['target_scope']),
        'observed':{p:(root/p).is_file() for p in c['target_scope']}}}))
    reg.register(SubjectDeliverableChecker(lambda c:subject(),{'public':lambda request,c:{
        'passed':request.input_values['execution_receipt']['outputs']['observation']['passed'],
        'observed':plain(request.input_values['execution_receipt']['outputs']['observation']),
        'evidence_refs':[plain(request.input_values['execution_receipt_ref'])]}}))
    runner=DAGRunner(reg,store,deliverable_checkers={'source':'deliverable.files@1','acceptance':'deliverable.subjects@1'})
    doc=snapshot().document
    doc['capabilities']=[{'capability_ref':'code','task_kinds':[2,3],'executor_ref':'llm.cheap@1','checker_ref':'source','acceptance_refs':['public'],'effect_domains':['source']},
        {'capability_ref':'verify','task_kinds':[4,5],'executor_ref':'verify@1','checker_ref':'acceptance','acceptance_refs':['public'],'effect_domains':['measurement']}]
    s=TableSnapshot(doc);tree=CapabilityTree('original user goal',())
    for p in [packet(),{**packet(),'target':1,'scope':[1]},
              {**packet(),'target':2,'scope':[2],'task_kind':4,'deps':[0,1],'goal':'independent full acceptance'}]:
        tree=apply_tree_edits(tree,run(p,s,tree)['edits'],known_capabilities={'code','verify'})
    first=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
    assert first.status=='FAILED' and len(calls)==2 and checks==[['A-field','sibling']]
    s=failed_snapshot(s);repair=run(repair_packet(),s,tree)
    repaired=apply_tree_edits(tree,repair['edits'],known_capabilities={'code','verify'})
    second=runner.run(project_id='p',run_id='r',tree=repaired,dag=compile_tree(repaired),resume=True,retry_node='n',accept_edits=True)
    assert second.status=='SUCCEEDED' and 'sibling' in second.reused_nodes
    assert [x[0] for x in calls].count('tests.py')==1 and len(calls)==3
    assert checks==[['A-field','sibling'],['A-field'],['A-field','sibling']]
    repair_pack=calls[-1][1]
    assert repair_pack['public_contracts']['entries'][0]['definition']['fields']=={'value':'int'}
    assert repair_pack['failed_acceptance_ids']==['A-field']
    before=(len(calls),len(checks));again=runner.run(project_id='p',run_id='r',tree=repaired,dag=compile_tree(repaired),resume=True)
    assert again.status=='SUCCEEDED' and (len(calls),len(checks))==before
    phases=[e.event_type for e in store.load_events('p','r')]
    assert 'TARGETED_RETEST' in phases and 'ACCEPTANCE_RECHECK' in phases and 'REPAIR_VERIFIED' in phases
