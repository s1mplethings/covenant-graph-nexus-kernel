"""Bounded ITER-118 acceptance, reusing canonical adapters and Agent/DAG authority.

No authorization is inferred. Each sealed slot can be attempted once; UNKNOWN
stops the batch. This operation is launched by the installed MCP managed worker.
"""
from __future__ import annotations
import dataclasses,hashlib,json,os,threading,time
from pathlib import Path
from cgkn.providers.gateway_client import GatewayCompletionClient
from cgkn.providers.streaming_sse import save_immutable_json
from scripts import provider_api_budget as budget
ROOT=Path(__file__).resolve().parents[3]
RUN=ROOT/'artifacts/api-final-live-20261029'
DURATION_RUN=ROOT/'artifacts/api-duration100-20261029'
EFFICIENT_RUN=ROOT/'artifacts/api-efficient-stream-20261029'
DUAL_RUN=ROOT/'artifacts/api-live-dual-long-20261029'
EXPECTED=[('qwen','qwen3.8-max',2048,64),('deepseek','deepseek-flash',2048,64),('qwen','qwen3.8-max',16384,7000),('qwen','qwen3.8-max',32768,4096),('deepseek','deepseek-flash',32768,4096),('qwen','qwen3.8-max',32768,2048)]


def admitted(run):
    if run.resolve().is_relative_to(ROOT.resolve()):raise RuntimeError('ARCHIVED_ACCEPTANCE_LIVE_DISABLED')
    raw=(run/'paid-plan.json').read_bytes();plan=json.loads(raw)
    auth=json.loads((run/'authorization.json').read_text(encoding='utf-8')) if (run/'authorization.json').exists() else {}
    duration=plan.get('kind')=='CGKN_ITER118_DURATION100_PLAN'
    efficient=plan.get('kind')=='CGKN_ITER118_EFFICIENT_STREAM_PLAN'
    dual=plan.get('kind')=='CGKN_ITER118_DUAL_LONG_PLAN'
    count,ceiling=(2,10) if dual or efficient or duration else (6,3)
    expected_rows=[('qwen','qwen3.8-max',16384,7000),('deepseek','deepseek-flash',16384,7000)] if dual else EXPECTED
    if efficient:expected_rows=[('qwen','qwen3.8-max',2048,512),('deepseek','deepseek-flash',2048,512)]
    if duration:
        expected_rows=[('qwen','qwen3.8-max',4096,10000),('deepseek','deepseek-flash',4096,28000)]
        if plan.get('prior_conservative_ceiling_cny')!=1.23084 or sum(r['upper_cny'] for r in plan['calls'])+1.23084>10:raise ValueError('CUMULATIVE_BUDGET_REFUSED')
    if not (auth.get('authorized') is True and auth.get('plan_sha256')==hashlib.sha256(raw).hexdigest() and auth.get('max_posts')==count and auth.get('max_cny')==ceiling):
        raise ValueError('ITER118_EXPLICIT_AUTHORIZATION_REQUIRED')
    rows=plan['calls']
    if len(rows)!=count or plan['max_posts']!=count or plan['max_cny']!=ceiling:raise ValueError('ITER118_LIMIT_MISMATCH')
    for row,expected in zip(rows,expected_rows):
        if tuple(row[k] for k in ('provider','model','input_cap','output_cap'))!=expected:raise ValueError('ITER118_SLOT_MISMATCH')
        if row['upper_cny']!=round((row['input_cap']*15+(row['output_cap']+10)*45)/1e6,6):raise ValueError('ITER118_PRICE_MISMATCH')
    if sum(row['upper_cny'] for row in rows)>ceiling:raise ValueError('ITER118_PRICE_EXCEEDS_AUTHORIZATION')
    return plan


def independent_resume_allowed(run,index):
    # Explicitly authorized, unused DeepSeek slot only. Never replay Qwen.
    if index!=1:return False
    path=run/'resume-unused-deepseek.json'
    previous=run/'call-01-result.json'
    if not path.exists() or not previous.exists():return False
    doc=json.loads(path.read_text(encoding="utf-8"))
    return (doc.get('authorized') is True and doc.get('case_id')=='ITER118-LONG-02'
        and doc.get('plan_sha256')==hashlib.sha256((run/'paid-plan.json').read_bytes()).hexdigest()
        and doc.get('preserved_unknown_sha256')==hashlib.sha256(previous.read_bytes()).hexdigest()
        and json.loads(previous.read_text()).get('status')=='UNKNOWN'
        and admitted(run).get('kind')=='CGKN_ITER118_DUAL_LONG_PLAN')


@dataclasses.dataclass(frozen=True)
class AcceptanceClient(GatewayCompletionClient):
    admission_dir: str = ''

    def complete(self,**kwargs):
        run=Path(self.admission_dir);plan=admitted(run)
        with budget._locked(run/'slot-admission'):
            starts=sorted(run.glob('call-*-started.json'));index=len(starts)
            if index>=plan['max_posts']:raise ValueError('ITER118_POST_LIMIT')
            for i in range(index):
                result=run/f'call-{i+1:02}-result.json'
                if (not result.exists() or json.loads(result.read_text())['status']!='PASS') and not independent_resume_allowed(run,index):raise ValueError('ITER118_PREVIOUS_NOT_CONFIRMED_NO_REPLAY')
            row=plan['calls'][index];cfg=kwargs['config']
            if cfg.model!=row['provider']:raise ValueError('ITER118_PROVIDER_SEQUENCE_REFUSED')
            if cfg.reasoning_effort!='none':raise ValueError('ITER118_REASONING_REFUSED')
            # This is only an early lower-bound check. The final exact upstream
            # serialized bytes + framing are enforced in Windows Gateway too.
            if len((kwargs['system']+kwargs['user']).encode())+1024>row['input_cap']:raise ValueError('ITER118_INPUT_CAP')
            cfg=dataclasses.replace(cfg,max_output_tokens=min(cfg.max_output_tokens,row['output_cap']),model_id=row['model'])
            inner=GatewayCompletionClient(self.base_url,self.access_token,self.api_method,run_id=self.run_id,case_id=row['id'],input_token_ceiling=row['input_cap'])
            os.environ['CGKN_MODEL_ATTEMPT_ID']=row['attempt_id']
            save_immutable_json(run/f'call-{index+1:02}-started.json',dict(**row,started_at=time.time(),job_id=plan['job_id'],run_id=self.run_id))
            def progress(event):
                with (run/f'call-{index+1:02}-progress.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(received_at=time.time(),**event))+'\n')
                if kwargs.get('on_progress'):kwargs['on_progress'](event)
            request={**kwargs,'config':cfg,'on_progress':progress}
            try:
                result=inner.complete(**request)
                save_immutable_json(run/f'call-{index+1:02}-response.json',dataclasses.asdict(result))
                record=dict(status='PASS',api_complete=True,result_committed=True,request_id=result.request_id,model=result.model,usage=dict(result.usage),completed_at=time.time())
            except Exception as exc:
                ledger=budget.configured_ledger_path();calls=json.loads(ledger.read_text()).get('calls',[]) if ledger and ledger.exists() else []
                unknown=any(c.get('submission_outcome_unknown') or c.get('status') in ('REQUEST_STARTED','INTERRUPTED_UNKNOWN') for c in calls if c.get('attempt_id')==row['attempt_id'])
                record=dict(status='UNKNOWN' if unknown else 'FAIL',error_type=type(exc).__name__,error_code=getattr(exc,'category',''),ended_at=time.time())
                save_immutable_json(run/f'call-{index+1:02}-result.json',record)
                raise
            save_immutable_json(run/f'call-{index+1:02}-result.json',record)
            return result


def run_case(case_id,confirmation):
    if confirmation!='RUN_AUTHORIZED_STREAMING_CASE':raise ValueError('ITER118_CONFIRMATION_REQUIRED')
    duration=case_id in ('ITER118-DURATION-01','ITER118-DURATION-02')
    efficient=case_id in ('ITER118-SAVE-01','ITER118-SAVE-02')
    dual=case_id in ('ITER118-LONG-01','ITER118-LONG-02')
    if not (dual or efficient or duration) and case_id not in ('ITER118-01','ITER118-02','ITER118-03','ITER118-04'):raise ValueError('ITER118_CASE_INVALID')
    run=DURATION_RUN if duration else EFFICIENT_RUN if efficient else DUAL_RUN if dual else RUN;plan=admitted(run)
    required=int(case_id[-2:])-1 if dual or efficient or duration else {'ITER118-01':0,'ITER118-02':1,'ITER118-03':2,'ITER118-04':3}[case_id]
    with budget._locked(run/'case-admission'):
        if len(list(run.glob('call-*-started.json')))!=required:raise ValueError('ITER118_CASE_ALREADY_USED_OR_OUT_OF_ORDER')
        for prior in range(1,int(case_id[-2:])):
            p=run/((f'ITER118-LONG-{prior:02}' if dual else f'ITER118-{prior:02}')+'-result.json')
            if dual or efficient or duration:p=run/f'call-{prior:02}-result.json'
            if (not p.exists() or json.loads(p.read_text())['status']!='PASS') and not (dual and independent_resume_allowed(run,required)):raise ValueError('ITER118_PREVIOUS_CASE_NOT_PASS')
        os.environ.update(CGKN_PROVIDER_BUDGET_LEDGER=str(run/'budget.json'),CGKN_PROVIDER_MAX_API_CALLS=str(plan['max_posts']),CGKN_PROVIDER_MAX_INPUT_TOKENS=str(sum(r['input_cap'] for r in plan['calls'])),CGKN_PROVIDER_MAX_OUTPUT_TOKENS=str(sum(r['output_cap']+10 for r in plan['calls'])),CGKN_PROVIDER_MAX_ESTIMATED_COST=str(plan['max_cny']),CGKN_PROVIDER_INPUT_COST_PER_MILLION='15',CGKN_PROVIDER_OUTPUT_COST_PER_MILLION='45',CGKN_PROVIDER_MAX_PLANNING_CALLS='4',CGKN_PROVIDER_MAX_GENERATION_CALLS='2',CGKN_PROVIDER_MAX_REPAIR_CALLS='0',CGKN_PROVIDER_CACHE_MODE='off',CGKN_MODEL_JOB_ID=plan['job_id'],CGKN_BENCHMARK_RUN_ID=plan['job_id'])
        from cgkn.providers.gateway_client import completion_client_from_environment
        base=completion_client_from_environment()
        if not isinstance(base,GatewayCompletionClient):raise ValueError('ITER118_SAVED_GATEWAY_REQUIRED')
        client=AcceptanceClient(base.base_url,base.access_token,run_id=plan['job_id'],admission_dir=str(run))
        try:
            if required<3:
                from cgkn.providers.canonical_gateway_adapter import provider_text
                row=plan['calls'][required]
                result=provider_text(row['messages'],row['provider'],90,max_tokens=row['output_cap'],stage='requirements_planning' if row['provider']=='qwen' else 'generation',response_format=row.get('response_format'),temperature=0,client=client)
                if duration:
                    value=json.loads(result.text);cases=value.get('cases') if isinstance(value,dict) else None
                    errors=[]
                    if not isinstance(cases,list) or len(cases)!=row['expected_count']:errors.append('case_count')
                    else:
                        if [v.get('id') for v in cases]!=list(range(1,row['expected_count']+1)):errors.append('case_ids')
                        for v in cases:
                            if not all(isinstance(v.get(k),str) and v[k].strip() for k in ('area','scenario','expected','recovery_check')) or not isinstance(v.get('steps'),list) or len(v['steps'])!=3 or not all(isinstance(x,str) and x.strip() for x in v['steps']):errors.append('case_shape');break
                elif efficient:
                    value=json.loads(result.text);cases=value.get('cases') if isinstance(value,dict) else None
                    errors=[] if isinstance(cases,list) and len(cases)==12 and all(isinstance(v,str) and 0<len(v)<=60 for v in cases) and len(set(cases))==12 else ['compact_cases_contract_failed']
                elif dual or required==2:
                    from scripts.canonical_goal_spec_compiler import validate_planning_proposal
                    errors=validate_planning_proposal(json.loads(result.text))
                else:errors=[] if result.text.strip()==row['expected_marker'] else ['marker_mismatch']
                doc=dict(status='FAIL' if errors else 'PASS',api_complete=True,business_contract_passed=not errors,contract_errors=errors)
            else:
                from cgkn.application.software_project.service import SoftwareProjectGenerationService
                result=SoftwareProjectGenerationService(ROOT,run/'task',client=client,config={'max_agent_decisions':2}).run_case('seeded_repair',max_repair_rounds=0)
                if result.status.value=='PASS' and len(list(run.glob('call-*-started.json')))!=6:raise ValueError('ITER118_HANDOFF_CALL_COUNT_MISMATCH')
                doc=dict(status=result.status.value,receipt=result.receipt,run_dir=str(result.run_dir),scope='CANONICAL_AGENT_DAG_EXISTING_SEEDED_REPAIR_CASE')
        except Exception as exc:
            latest=sorted(run.glob('call-*-result.json'))
            unknown=bool(latest and json.loads(latest[-1].read_text()).get('status')=='UNKNOWN')
            doc=dict(status='UNKNOWN' if unknown else 'FAIL',error_type=type(exc).__name__,error_code=getattr(exc,'category',''))
        doc.update(job_id=plan['job_id'],case_id=case_id)
        save_immutable_json(run/(case_id+'-result.json'),doc)
        return doc
