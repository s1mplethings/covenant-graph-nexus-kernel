"""ITER-117 bounded acceptance operation over the existing canonical adapter.

No generation probes, retries, fallback, task scheduling or delivery authority.
The fixed, hashed three-case plan and explicit authorization live outside source.
"""
from __future__ import annotations
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / 'artifacts/streaming-live-acceptance-20261029/authorized-run'
LONG_RUN = ROOT / 'artifacts/streaming-long-request-plan-20261029/authorized-run'


def prepare(plan):
    if plan.get('total_max_posts') != 3 or plan.get('total_budget_cny') != 2:
        raise ValueError('ACCEPTANCE_LIMIT_MISMATCH')
    cases=[]
    expected=[('LIVE-01','qwen','qwen3.8-max',256),('LIVE-02','deepseek','deepseek-flash',256),('LIVE-03','qwen','qwen3.8-max',4096)]
    if len(plan['tests']) != 3:raise ValueError('ACCEPTANCE_CASE_COUNT')
    for row,(name,provider,model,maximum) in zip(plan['tests'],expected):
        if (row['test'],row['provider'],row['model'],row['max_output_tokens']) != (name,provider,model,maximum):
            raise ValueError('ACCEPTANCE_CASE_MISMATCH')
        if row['reasoning_effort']!='none' or row['max_post']!=1:raise ValueError('ACCEPTANCE_POLICY_MISMATCH')
        system='Follow the requested output exactly. Do not use tools or external search.'
        if name=='LIVE-03':system+=' Return only the canonical PlanningProposal JSON. Contract: '+json.dumps(row['prompt_contract'])
        messages=[dict(role='system',content=system),dict(role='user',content=row['prompt'])]
        # Count every byte of the serialized text/schema, with additional framing
        # allowance. Text-only BPE tokens cannot outnumber UTF-8 source bytes.
        framing=json.dumps(dict(messages=messages,response_format=row.get('response_format')),ensure_ascii=False).encode()
        upper_input=len(framing)+1024
        if upper_input>row['input_admission_cap_tokens']:raise ValueError('ACCEPTANCE_INPUT_TOO_LARGE')
        # Includes Qwen's documented <=10-token completion-limit tolerance.
        upper_cost=(upper_input*15+(maximum+10)*45)/1_000_000
        cases.append(dict(**row,messages=messages,upper_input_tokens=upper_input,upper_cost_cny=upper_cost))
    if sum(x['upper_cost_cny'] for x in cases)>2:raise ValueError('ACCEPTANCE_COST_EXCEEDED')
    return cases


def prepare_long(plan):
    wire=plan['wire_payload']
    raw=json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode()
    if (plan['case_id'],plan['provider'],plan['model'],plan['max_posts'],plan['budget_requested_cny']) != ('LIVE-LONG-01','qwen','qwen3.8-max',1,.75):
        raise ValueError('ACCEPTANCE_LONG_LIMIT_MISMATCH')
    if hashlib.sha256(raw).hexdigest()!=plan['payload_sha256']:raise ValueError('ACCEPTANCE_PAYLOAD_MISMATCH')
    if wire.get('model')!='qwen3.8-max' or wire.get('reasoning_effort')!='none' or wire.get('max_completion_tokens')!=7000:
        raise ValueError('ACCEPTANCE_LONG_CAP_MISMATCH')
    if plan['deadline_seconds']!=90 or plan['input_cap_tokens']!=16384 or plan['output_cap_tokens']!=7000:
        raise ValueError('ACCEPTANCE_LONG_CAP_MISMATCH')
    if set(wire)!={'model','messages','response_format','temperature','reasoning_effort','max_completion_tokens','stream','stream_options'}:
        raise ValueError('ACCEPTANCE_UNEXPECTED_FIELDS')
    from scripts.canonical_goal_spec_compiler import planning_proposal_response_format
    if wire['response_format']!=planning_proposal_response_format():raise ValueError('ACCEPTANCE_CONTRACT_CHANGED')
    if [m.get('role') for m in wire['messages']]!=['system','user']:raise ValueError('ACCEPTANCE_MESSAGES_INVALID')
    upper=len(raw)+1024
    cost=(upper*15+7010*45)/1_000_000
    if upper>16384 or cost>.75:raise ValueError('ACCEPTANCE_LONG_COST_EXCEEDED')
    return [dict(test='LIVE-LONG-01',provider='qwen',model='qwen3.8-max',messages=wire['messages'],
        response_format=wire['response_format'],total_seconds=90,max_output_tokens=7000,
        job_id=plan['job_id'],attempt_id=plan['attempt_id'],upper_input_tokens=upper,upper_cost_cny=cost)]


def run_case(case_id,confirmation):
    if confirmation!='RUN_AUTHORIZED_STREAMING_CASE':raise ValueError('ACCEPTANCE_CONFIRMATION_REQUIRED')
    from scripts import provider_api_budget as budget
    from cgkn.providers.streaming_sse import save_immutable_json
    long_case=case_id=='LIVE-LONG-01'
    run=LONG_RUN if long_case else RUN
    if run.resolve().is_relative_to(ROOT.resolve()):raise RuntimeError('ARCHIVED_ACCEPTANCE_LIVE_DISABLED')
    max_posts,max_cny=(1,.75) if long_case else (3,2)
    raw=(run/'plan.json').read_bytes();auth=json.loads((run/'authorization.json').read_text())
    if not (auth.get('authorized') is True and auth.get('max_posts')==max_posts and auth.get('max_cny')==max_cny and auth.get('plan_sha256')==hashlib.sha256(raw).hexdigest()):
        raise ValueError('ACCEPTANCE_AUTHORIZATION_REQUIRED')
    cases=(prepare_long if long_case else prepare)(json.loads(raw));index=[x['test'] for x in cases].index(case_id);case=cases[index]
    with budget._locked(run/'admission'):
        if (run/(case_id+'-started.json')).exists():raise ValueError('ACCEPTANCE_ALREADY_ATTEMPTED_NO_REPLAY')
        for previous in cases[:index]:
            file=run/(previous['test']+'-result.json')
            if not file.exists() or json.loads(file.read_text()).get('status')!='PASS':raise ValueError('ACCEPTANCE_PREVIOUS_NOT_PASS')
        ledger=run/'budget.json'
        if ledger.exists():
            calls=json.loads(ledger.read_text()).get('calls',[])
            if len(calls)!=index or any(x.get('status')!='SUCCEEDED' or x.get('submission_outcome_unknown') for x in calls):
                raise ValueError('ACCEPTANCE_LEDGER_NOT_RECONCILED')
        # Read metadata only; never expose credential references or values.
        import sys
        sys.path.insert(0,'D:/cgkn-provider-api-lab/src')
        from cgkn_provider_lab.storage import ProviderConfigStore
        models={x.provider_id:x.model for x in ProviderConfigStore().load()}
        if models.get(case['provider'])!=case['model']:raise ValueError('ACCEPTANCE_MODEL_CHANGED')
        os.environ.update(CGKN_PROVIDER_BUDGET_LEDGER=str(ledger),CGKN_PROVIDER_MAX_API_CALLS=str(max_posts),
            CGKN_PROVIDER_MAX_INPUT_TOKENS='16384' if long_case else '40000',CGKN_PROVIDER_MAX_OUTPUT_TOKENS='7010' if long_case else '5000',
            CGKN_PROVIDER_MAX_ESTIMATED_COST=str(max_cny),CGKN_PROVIDER_INPUT_COST_PER_MILLION='15',
            CGKN_PROVIDER_OUTPUT_COST_PER_MILLION='45',CGKN_PROVIDER_MAX_PLANNING_CALLS='1' if long_case else '2',
            CGKN_PROVIDER_MAX_GENERATION_CALLS='0' if long_case else '1',CGKN_PROVIDER_MAX_REPAIR_CALLS='0',
            CGKN_PROVIDER_CACHE_MODE='off',CGKN_MODEL_JOB_ID=case['job_id'],
            CGKN_MODEL_ATTEMPT_ID=case['attempt_id'],CGKN_BENCHMARK_RUN_ID='ITER-117-LONG' if long_case else 'ITER-117-LIVE',CGKN_BENCHMARK_CASE_ID=case_id)
        started=time.time()
        save_immutable_json(run/(case_id+'-started.json'),dict(case_id=case_id,job_id=case['job_id'],attempt_id=case['attempt_id'],
            started_at=started,upper_cost_cny=case['upper_cost_cny'],batch_upper_cost_cny=sum(x['upper_cost_cny'] for x in cases)))
        events=[]
        def progress(row):
            events.append(dict(received_at=time.time(),**row))
            with (run/(case_id+'-progress.jsonl')).open('a',encoding='utf-8') as f:f.write(json.dumps(events[-1])+'\n');f.flush()
        try:
            from cgkn.providers.canonical_gateway_adapter import provider_text
            result=provider_text(case['messages'],case['provider'],case['total_seconds'],max_tokens=case['max_output_tokens'],
                stage='requirements_planning' if case['provider']=='qwen' else 'generation',
                response_format=case.get('response_format'),temperature=0,on_progress=progress)
            contract_errors=[]
            if case_id in ('LIVE-03','LIVE-LONG-01'):
                from scripts.canonical_goal_spec_compiler import validate_planning_proposal
                contract_errors=validate_planning_proposal(json.loads(result.text))
            elif result.text.strip()!=('CGKN_QWEN_STREAM_OK' if case_id=='LIVE-01' else 'CGKN_DEEPSEEK_STREAM_OK'):
                contract_errors=['unexpected_marker']
            calls=json.loads(ledger.read_text())['calls']
            if len(calls)!=index+1:raise RuntimeError('ACCEPTANCE_POST_ACCOUNTING_MISMATCH')
            doc=dict(status='PASS' if not contract_errors else 'FAIL',api_complete=True,contract_errors=contract_errors,
                started_at=started,completed_at=time.time(),elapsed_seconds=time.time()-started,case_id=case_id,
                result=dataclasses.asdict(result),progress_events=len(events),first_progress_at=events[0]['received_at'] if events else None,
                meaningful_progress_at=next((e['received_at'] for e in events if e.get('text_bytes',0)+e.get('reasoning_chars',0)>0),None))
        except Exception as exc:
            calls=json.loads(ledger.read_text()).get('calls',[]) if ledger.exists() else []
            unknown=any(x.get('submission_outcome_unknown') or x.get('status') in ('INTERRUPTED_UNKNOWN','REQUEST_STARTED') for x in calls)
            doc=dict(status='UNKNOWN' if unknown else 'FAIL',exception_type=type(exc).__name__,
                error_code=str(getattr(exc,'code',getattr(exc,'category',''))),case_id=case_id,started_at=started,ended_at=time.time())
        save_immutable_json(run/(case_id+'-result.json'),doc)
        return {k:v for k,v in doc.items() if k!='result'}


if __name__=='__main__':
    import sys
    print(json.dumps(run_case(sys.argv[1],sys.argv[2])))
