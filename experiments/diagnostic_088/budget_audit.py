"""Offline reconstruction of UNSENT requests, never a Provider client."""
import json
from decimal import Decimal
from .capture import ROOT,OLD,save,sha
from .offline import no_provider

def main():
    with no_provider(ROOT/'forbidden-provider.jsonl'):
        ledger=json.loads((OLD/'global-provider-budget.json').read_text());calls=ledger['calls']
        out=ROOT/'budget-audit-v3';out.mkdir(exist_ok=False)
        def cost(c):
            i=c.get('input_tokens');o=c.get('output_tokens')
            return ((i if isinstance(i,int) else c['reserved_input_tokens'])*20+(o if isinstance(o,int) else c['reserved_output_tokens'])*60)/1e6
        rows=[]
        for d in sorted((OLD/'formal-v8').glob('*direct')):
            requests=sorted((d/'provider').glob('*.request.json'))
            requests=[p for p in requests if '.transport-' not in p.name]
            last=json.loads(requests[-1].read_text(encoding='utf-8'))
            events=[json.loads(x) for x in (d/'run/audit.jsonl').read_text(encoding='utf-8').splitlines()]
            actions=[x['data'] for x in events if x['kind']=='provider_action']
            tool=[x['data'] for x in events if x['kind']=='tool']
            context=json.loads(last['user']);history=context['history']
            # Every earlier raw tool return must equal the corresponding next
            # transmitted request history; this validates reconstruction format.
            validated=0
            for p in requests:
                r=json.loads(p.read_text(encoding='utf-8'));h=json.loads(r['user'])['history']
                for i,item in enumerate(h):
                    assert item['response']==actions[i]['response']
                    if item['tool_result'].get('status')!='INVALID_RESPONSE':
                        assert any(t['result']==item['tool_result'] for t in tool)
                validated+=1
            action=actions[-1]
            tail=next(x for x in reversed(events) if x['kind']=='tool')['data']['result']
            # Confirm the final tool immediately follows final Provider action.
            final_index=max(i for i,x in enumerate(events) if x['kind']=='provider_action')
            assert any(x['kind']=='tool' for x in events[final_index+1:])
            history.append({'response':action['response'],'tool_result':tail})
            user=json.dumps(context,ensure_ascii=False)
            estimate=len((last['system']+user+json.dumps(last['schema'])).encode())+4096
            output=last['max_output_tokens'];input_cost=estimate*20/1e6;output_cost=output*60/1e6
            own=[c for c in calls if c['run_id']==d.name]
            lastidx=max(i for i,c in enumerate(calls) if c['run_id']==d.name)
            prior=calls[:lastidx+1]
            used=round(sum(cost(c) for c in own),8)
            globalused=round(sum(cost(c) for c in prior),8)
            cap=json.loads((d/'provider/billing-policy.json').read_text())['run_cap']
            remaining=round(cap-used,8)
            affordable=int((Decimal(str(remaining))-Decimal(estimate)*20/1000000)*1000000/60)
            transport_checks=[]
            for p in requests:
                r=json.loads(p.read_text());t=json.loads(p.with_name(p.name.replace('.request.json','.transport-request.json')).read_text())
                transport_checks.append(t.get('max_tokens',t.get('max_completion_tokens'))==r['max_output_tokens'])
            assert all(transport_checks)
            text_bytes=len(tail.get('stdout','').encode())+len(tail.get('stderr','').encode())
            reason='INPUT_BOUND_EXCEEDS_BALANCE' if affordable<1024 else 'SMALLER_OUTPUT_FEASIBLE'
            if text_bytes>10000:reason+=';CONTEXT_GROWTH_RAW_TOOL_OUTPUT'
            row={'run_id':d.name,'kind':'RECONSTRUCTED_UNSENT_REQUEST','request_history_checks':validated,'run_cap':cap,'run_used':used,'run_remaining':remaining,'global_cap':50,'global_used_at_stop':globalused,'global_remaining_at_stop':round(50-globalused,8),'outstanding_reservations':[c['call_id'] for c in prior if c['status'] not in ['SUCCEEDED','FAILED','CANCELLED']],'input_upper_tokens':estimate,'input_upper_cny':input_cost,'output_limit':output,'output_upper_cny':output_cost,'next_upper_cny':input_cost+output_cost,'input_padding_tokens':4096,'input_padding_cny':.08192,'last_tool_output_bytes':text_bytes,'affordable_output_tokens':max(0,affordable),'minimum_viable_output':1024,'reason':reason,'run_reject':used+input_cost+output_cost>cap,'transport_max_matches':all(transport_checks),'untransmitted_reservation_created':False}
            assert row['run_reject']
            save(out/(d.name+'.unsent.json'),{'reconstructed':True,'not_transmitted':True,**last,'user':user})
            rows.append(row)
        unknown=[c for c in calls if not isinstance(c.get('input_tokens'),int) or not isinstance(c.get('output_tokens'),int)]
        save(out/'audit.json',{'ledger_sha256':sha(OLD/'global-provider-budget.json'),'ledger_totals':ledger.get('totals'),'rows':rows,'unknown_usage_calls':unknown,'duplicate_call_ids':len(calls)-len(set(c['call_id'] for c in calls)),'duplicate_request_identities':len(calls)-len(set(c['request_identity'] for c in calls)),'paid_calls':0})
        print(json.dumps(rows,indent=2))
if __name__=='__main__':main()
