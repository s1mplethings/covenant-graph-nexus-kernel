"""Synthetic plan documents for isolated loopback regression tests only.

These contain no authorization or credentials and are never saved to the
historical artifacts directories. Numeric limits are frozen test inputs, not
current Provider prices or permission to perform paid calls.
"""
import hashlib
import json
from scripts.canonical_goal_spec_compiler import planning_proposal_response_format

def offline_pair_plan():
    from pathlib import Path
    from tests.session_authority_support import authorization
    root=Path(__file__).resolve().parents[2]
    return dict(kind='ITER119AuthorizedPair',max_posts=2,max_cny=.5,input_rate=4,output_rate=16,
        network_sha256=hashlib.sha256((root/'config/network_routes.json').read_bytes()).hexdigest(),
        execution_authorization=authorization('iter119',('bounded-api-witness@1',),
            'Observe two bounded structured responses',calls=1),
        requests=[dict(provider=p,model=m,role=r,input_ceiling=8192,output_limit=n,
            system='Return the declared offline response schema.',user='Plan a local calculator.' if p=='qwen' else 'Calculate 19+23.',
            schema=planning_proposal_response_format()['json_schema']['schema'] if p=='qwen' else {'type':'object'})
            for p,m,r,n in [('qwen','qwen3.8-flash','agent',2048),('deepseek','deepseek-flash','worker',256)]])


def offline_plan(name):
    response=planning_proposal_response_format()
    if name=='bounded':
        rows=[]
        for i,(provider,model,maximum) in enumerate([('qwen','qwen3.8-max',256),('deepseek','deepseek-flash',256),('qwen','qwen3.8-max',4096)],1):
            row=dict(test=f'LIVE-{i:02}',provider=provider,model=model,max_output_tokens=maximum,
                reasoning_effort='none',max_post=1,input_admission_cap_tokens=16384 if i==3 else 2048,
                prompt='Plan an offline task tracker' if i==3 else ('CGKN_QWEN_STREAM_OK' if i==1 else 'CGKN_DEEPSEEK_STREAM_OK'),
                job_id='ISOLATED_TEST_ONLY',attempt_id=f'offline-{i}',total_seconds=90)
            if i==3:row.update(prompt_contract=response['json_schema']['schema'],response_format=response)
            rows.append(row)
        doc=dict(total_max_posts=3,total_budget_cny=2,tests=rows)
    elif name=='long':
        wire=dict(model='qwen3.8-max',messages=[{'role':'system','content':'Return the declared planning schema.'},
            {'role':'user','content':'Plan an offline data import application.'}],response_format=response,
            temperature=0,reasoning_effort='none',max_completion_tokens=7000,stream=True,stream_options={'include_usage':True})
        encode=lambda:json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode()
        # Keep the historical exact-byte calibration while using domain-neutral
        # synthetic input. No old plan or billing authorization is inherited.
        padding=7631-1024-len(encode());assert padding>=0
        wire['messages'][1]['content']+=' '*padding
        doc=dict(case_id='LIVE-LONG-01',provider='qwen',model='qwen3.8-max',max_posts=1,budget_requested_cny=.75,
            wire_payload=wire,payload_sha256=hashlib.sha256(encode()).hexdigest(),deadline_seconds=90,
            input_cap_tokens=16384,output_cap_tokens=7000,job_id='ISOLATED_TEST_ONLY',attempt_id='offline-long')
    else:
        definitions={
            'final':[(2048,64),(2048,64),(16384,7000),(32768,4096),(32768,4096),(32768,2048)],
            'dual':[(16384,7000),(16384,7000)],'efficient':[(2048,512),(2048,512)],
            'duration':[(4096,10000),(4096,28000)]}
        rows=[]
        for i,(input_cap,output_cap) in enumerate(definitions[name]):
            provider='deepseek' if i==1 or (name=='final' and i==4) else 'qwen'
            row=dict(id=f'offline-{name}-{i}',attempt_id=f'offline-{name}-{i}',provider=provider,
                model='deepseek-flash' if provider=='deepseek' else 'qwen3.8-max',input_cap=input_cap,output_cap=output_cap,
                upper_cny=round((input_cap*15+(output_cap+10)*45)/1e6,6),
                messages=[{'role':'system','content':'Follow the declared offline output contract.'},
                          {'role':'user','content':'Return an offline planning proposal.'}])
            if name=='final' and i<2:
                row['expected_marker']='CGKN_QWEN_STREAM_OK' if i==0 else 'CGKN_DEEPSEEK_STREAM_OK'
                row['messages'][1]['content']=row['expected_marker']
            if name=='dual' or (name=='final' and i==2):row['response_format']=response
            if name=='duration':row['expected_count']=40 if i==0 else 120
            rows.append(row)
        doc=dict(max_posts=len(rows),max_cny=3 if name=='final' else 10,calls=rows,job_id='ISOLATED_TEST_ONLY')
        if name=='final':
            # The domain-neutral arithmetic handoff uses the ordinary model
            # tier. It does not manufacture a Max escalation for a simple task.
            doc['kind']='CGKN_GENERIC_OFFLINE_HANDOFF'
            for index in (3,5):rows[index]['model']='qwen3.8-flash'
        if name!='final':doc['kind']={'dual':'CGKN_ITER118_DUAL_LONG_PLAN','efficient':'CGKN_ITER118_EFFICIENT_STREAM_PLAN','duration':'CGKN_ITER118_DURATION100_PLAN'}[name]
        if name=='duration':doc['prior_conservative_ceiling_cny']=1.23084
    return json.dumps(doc,ensure_ascii=False).encode()
