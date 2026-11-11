"""Bounded checking executor on a disposable, isolated candidate snapshot."""
import hashlib
import json
import subprocess
import zipfile
import itertools
from dataclasses import replace
from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.providers import parse_json_object
from cgkn.execution.check_evidence import evaluate
from experiments.product_dev_089.isolation import ContainerBoundary
from experiments.product_eval_076_v8.freeze_candidate import INSPECT

SCHEMA = {'type':'object','required':['done','action','report'],'additionalProperties':False,
          'properties':{'done':{'type':'boolean'},'action':{'type':'object'},'report':{'type':'array','items':{'type':'object'}}}}
CLAIM_FIELDS=('requirement_ref','requirement_version','artifact_hash','checker','check_version','environment_hash','expected','observed','evidence_ref','check_execution','verdict')
SCHEMA['properties']['report']['items']={'type':'object','additionalProperties':False,'required':list(CLAIM_FIELDS),
    'properties':{**{k:{'type':'string'} for k in CLAIM_FIELDS},
        'evidence_ref':{'anyOf':[{'type':'integer','minimum':0},{'type':'array','minItems':1,'items':{'type':'integer','minimum':0}}]},
        'check_execution':{'enum':['VALID','INVALID','NOT_RUN']},
        'verdict':{'enum':['VERIFIED','FAILED','INSUFFICIENT_EVIDENCE']}}}


def valid_history_reference(reference, history):
    refs=reference if isinstance(reference,list) else [reference]
    return bool(refs) and all(type(i) is int and 0<=i<len(history)
        and history[i].get('result',{}).get('status') in {'COMPLETED','FAILED'}
        and type(history[i].get('result',{}).get('exit_code')) is int for i in refs)

def source_identity(root):
    """Track pre-existing executable sources, not legitimate runtime data writes."""
    suffixes={'.py','.js','.ts','.html','.css','.sql','.sh'}
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and not p.is_symlink() and p.suffix in suffixes and not any(x in p.parts for x in ('.git','__pycache__','node_modules'))}

def altered_sources(before, root):
    after=source_identity(root)
    return [name for name,digest in before.items() if after.get(name)!=digest]

class ObserverExecutor:
    descriptor = ExecutorDescriptor('isolated.observer@1','bounded_observer',('*',),('container.execute',))
    def __init__(self, boundary, client, configs):
        self.boundary,self.client,self.configs=boundary,client,configs

    def execute(self, request):
        source=self.boundary; cfg=request.task_context.as_dict()['node_config']
        root=source.root.parent/('observer-'+request.node_id+'-'+request.attempt_id[-8:])
        root.mkdir(exist_ok=False); out=root/'snapshot';out.mkdir()
        b=None
        try:
            selected=cfg.get('provider','grok')
            if selected not in self.configs:raise ValueError('Unregistered observer provider')
            cmd=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--mount',f'type=bind,source={source.work},target=/candidate,readonly','--mount',f'type=bind,source={out},target=/evidence',source.policy.image,'python','-c',INSPECT]
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
            source.record('observer_snapshot',{'node':request.node_id,'command':cmd,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
            if p.returncode:raise RuntimeError('Observer snapshot failed')
            artifact=hashlib.sha256((out/'manifest.json').read_bytes()).hexdigest()
            b=ContainerBoundary(root/'run',(source.run_id+'-o'+request.node_id)[-55:],'R_CGNK',source.policy)
            with zipfile.ZipFile(out/'candidate.zip') as z:
                for n in z.namelist():
                    from .paths import safe_member
                    path=safe_member(n)
                    dest=b.work/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(n))
            for f in source.public.iterdir():
                if f.is_file() and not f.is_symlink():(b.public/f.name).write_bytes(f.read_bytes())
            b.start();original_sources=source_identity(b.work);history=[];repetitions={};alternative_used=False;report_rejections=0
            continuous=getattr(self.client,'accounting_only',False)
            for turn in itertools.count() if continuous else range(8):
                payload={'task':cfg.get('goal',''),'requirements':cfg.get('requirement_ref',[]),'requirement_version':cfg.get('requirement_version','public-v1'),'artifact_hash':artifact,'environment_hash':source.policy.image,'history':history,'input':'/input','workspace':'/workspace','dependency_results':request.task_context.as_dict()['dependency_results']}
                from .routes import TOOL_DOC, TOOL_POLICY
                payload['tools']=TOOL_DOC
                payload['tool_policy']=TOOL_POLICY
                feedback=source.public/'exposed-feedback.json'
                payload['public_feedback']=feedback.read_text(encoding='utf-8') if feedback.is_file() else None
                payload['action_contract']={'discriminator':'action','command_example':{'action':'command','argv':['pwd']},'file_example':{'action':'read_file','path':'/workspace/README.md'},'browser_example':{'action':'browser','url':'http://127.0.0.1:5000'},'no_wrappers':['name','tool','parameters']}
                if continuous and turn and turn%8==0:
                    (root/f'checkpoint-{turn:04d}.json').write_text(json.dumps({'history':history,'selected_provider':selected,'repetitions':repetitions}),encoding='utf-8')
                    payload['checkpoint']='Continue the same assigned check and existing environment. Return measured report when sufficient; do not restart the project or repeat completed effects.'
                c=self.client.complete(system='You are a bounded independent checker, not the project planner. Check the assigned requirements on this disposable candidate copy. First inspect public requirements and actual behavior; if reading source later, disclose it. You may run shell, file and browser tools and write temporary checks here; nothing is merged to the candidate. Do not repair the product. Report only observed issues, never guessed defects. Each report includes requirement_ref, requirement_version, artifact_hash, checker, check_version, environment_hash, expected, observed, evidence_ref (history index), check_execution VALID/INVALID/NOT_RUN, verdict VERIFIED/FAILED/INSUFFICIENT_EVIDENCE. VERIFIED only covers the exact observation. Return done=false with one action using action tool name and argv/path/etc, report=[]; done=true action={} and report. Command timeout_seconds <=120, services must be backgrounded with logs. No bash installed. Budget is shared.',user=json.dumps(payload,ensure_ascii=False),schema_name='cgkn_observer',schema=SCHEMA,config=replace(self.configs[selected],max_output_tokens=4096))
                v=None
                try:
                    v=parse_json_object(c.text)
                    if set(v)!=set(SCHEMA['required']) or not isinstance(v['done'],bool):raise ValueError('Invalid observer envelope')
                    if v['done']:
                        changed=altered_sources(original_sources,b.work)
                        if changed:
                            return self.result(request,{'artifact_hash':artifact,'history':history,'check_execution':'INVALID','verdict':'INSUFFICIENT_EVIDENCE','changed_original_sources':changed,'reason':'Checker modified original executable source; its result cannot attest the supplied candidate','modifications_merged':False})
                        records=[]
                        for claim in v['report']:
                            valid_ref=valid_history_reference(claim.get('evidence_ref'),history)
                            verdict=evaluate(claim,artifact_hash=artifact,requirement_version=payload['requirement_version'],environment_hash=source.policy.image) if valid_ref else {'verdict':'INSUFFICIENT_EVIDENCE','next_action':'ADD_EVIDENCE','reason':'missing actual tool reference'}
                            records.append({'claim':claim,'assessment':verdict,'review_type':'DOMAIN_PROXY_REVIEW'})
                        invalid=[r['assessment'] for r in records if r['claim'].get('verdict') in {'VERIFIED','FAILED'} and r['assessment']['verdict']=='INSUFFICIENT_EVIDENCE']
                        if invalid and report_rejections<2:
                            report_rejections+=1
                            history.append({'model':c.model,'request_id':c.request_id,'raw':c.text,'report_validation':invalid,'instruction':'Correct your own evidence references/record fields, or honestly report INSUFFICIENT_EVIDENCE. Original observations are unchanged.'})
                            continue
                        return self.result(request,{'artifact_hash':artifact,'checks':records,'history':history,'snapshot_ref':str(out),'modifications_merged':False})
                    result=b.execute(v['action'],120)
                except (ValueError,TypeError,KeyError) as exc:result={'status':'INVALID_RESPONSE','error':str(exc)}
                history.append({'model':c.model,'request_id':c.request_id,'raw':c.text,'result':result})
                signature=hashlib.sha256(json.dumps({'action':v.get('action') if isinstance(v,dict) else c.text,'status':result.get('status'),'stdout':result.get('stdout_hash',result.get('stdout')),'stderr':result.get('stderr_hash',result.get('stderr')),'error':result.get('error')},sort_keys=True).encode()).hexdigest()
                repetitions[signature]=repetitions.get(signature,0)+1
                if continuous and repetitions[signature]>=3:
                    alternatives=[m for m in self.configs if m!=selected]
                    if alternatives and not alternative_used:
                        selected=alternatives[0];alternative_used=True
                        history.append({'framework_feedback':'Repeated identical action and evidence; change observation strategy. Provider changed; original goal, environment and history retained.'})
                    else:
                        return self.result(request,{'artifact_hash':artifact,'history':history,'check_execution':'NOT_RUN','verdict':'INSUFFICIENT_EVIDENCE','reason':'Repeated identical evidence after alternate observation opportunity; no business pass inferred'})
            return self.result(request,{'artifact_hash':artifact,'history':history,'check_execution':'NOT_RUN','verdict':'INSUFFICIENT_EVIDENCE','reason':'bounded observer exhausted'})
        except Exception as exc:
            return self.result(request,{},str(exc))
        finally:
            if b:b.close()

    @staticmethod
    def result(r,outputs,error=None):
        return BlockExecutionResult(project_id=r.project_id,run_id=r.run_id,attempt_id=r.attempt_id,node_id=r.node_id,executor_ref=r.executor_ref,status=BlockStatus.FAILED if error else BlockStatus.SUCCEEDED,outputs=outputs,error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,error) if error else None)
