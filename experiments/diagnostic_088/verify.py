"""Finite offline regressions and original-record checks, retained outputs."""
import contextlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
import pytest
from .capture import ROOT,OLD,sha,save
from .offline import no_provider

def main():
    base=json.loads((ROOT/'baseline.json').read_text())
    unchanged={p:sha(OLD/p)==h for p,h in base['original_records'].items()}
    old_code={p:sha(Path(p))==h for p,h in base['source_files'].items() if p.startswith(('experiments/product_eval_076/','experiments/product_eval_076_v8/'))}
    assert all(unchanged.values()) and all(old_code.values())
    out=ROOT/'verification-v2';out.mkdir(exist_ok=False)
    argv=['tests/runtime/test_graph_commit.py','tests/runtime/test_dag_runner.py','tests/runtime/test_invalidation_and_edits.py','tests/agent','tests/state','tests/test_provider_api_budget.py','experiments/diagnostic_088/test_budget_policy.py','experiments/product_eval_076_v8/test_feedback.py','--run-profile-marked','-q','-rs']
    log=io.StringIO()
    with no_provider(ROOT/'forbidden-provider.jsonl'),contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        result=pytest.main(argv)
    save(out/'regression.json',{'command':['python','-m','pytest',*argv],'exit':int(result),'output':log.getvalue(),'production_provider':'DISABLED','paid_calls':0,'scope':'Affected runtime/agent/state, canonical budget and new output policy; not full pytest'})
    print(log.getvalue())
    export=out/'source-export';export.mkdir()
    files=[Path(p) for p in subprocess.check_output(['git','ls-files'],text=True).splitlines() if Path(p).is_file()]
    files+=list(Path('experiments/diagnostic_088').glob('*.*'))+[Path('tests/runtime/test_graph_commit.py')]
    for p in files:
        dst=export/p;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
    gate=subprocess.run([sys.executable,str(export/'scripts/product_direction_gate.py')],capture_output=True,text=True,encoding='utf-8',timeout=120)
    save(out/'product-direction-gate.json',{'command':[sys.executable,str(export/'scripts/product_direction_gate.py')],'exit':gate.returncode,'stdout':gate.stdout,'stderr':gate.stderr,'scope':'Current tracked source + new diagnostic/test; user ignored directories excluded without reading/removing them'})
    print(gate.stdout)
    records=[]
    for p in sorted((ROOT/'replay-before').glob('*/replay.json')):
        raw=json.loads(p.read_text());source=Path(raw['source']);original=list((source/'run/cgkn-state').glob('*/*/run_state.json'))
        if not original:continue
        state=json.loads(original[0].read_text());failure=next((t for t in raw['transitions'] if 'persisted run state does not match DAG' in t.get('stack','')),None)
        records.append({'run_id':source.name,'original_state_path':str(original[0]),'original_state_sha256':sha(original[0]),'original_node_records':state['nodes'],'replayed_first_mismatch_same_saved_node_ids':set(state['nodes'])==set(failure['before']['nodes']) if failure else None,'new_nodes_at_failure':[n['id'] for n in failure['dag']['nodes']] if failure else None,'original_definition_sha256':sha(original[0].with_name('execution_dag.json'))})
    assert all(r['replayed_first_mismatch_same_saved_node_ids'] for r in records if r['new_nodes_at_failure'])
    save(out/'historical-state-comparison.json',records)
    ledger=json.loads((OLD/'global-provider-budget.json').read_text())
    groups={}
    for c in ledger['calls']:
        name=c['run_id'];stage='PROTOCOL' if name.startswith('protocol-') else 'PRODUCT_DEV' if name.startswith('dev-') else 'FORMAL_v7' if int(name.split('-')[1])<=4 else 'FORMAL_v8'
        g=groups.setdefault(stage,{'runs':set(),'calls':0,'cost':0})
        g['runs'].add(name);g['calls']+=1
        i=c['input_tokens'];o=c['output_tokens']
        g['cost']+=((i if isinstance(i,int) else c['reserved_input_tokens'])*20+(o if isinstance(o,int) else c['reserved_output_tokens'])*60)/1e6
    for g in groups.values():g['runs']=sorted(g['runs']);g['run_count']=len(g['runs']);g['cost']=round(g['cost'],8)
    save(out/'stage-ledger.json',{'groups':groups,'authorization_8_to_12':json.loads((OLD/'authorization-amendment-v5.json').read_text(encoding='utf-8')),'later_cap':json.loads((OLD/'budget-authorization-v8.json').read_text(encoding='utf-8')),'new_stage':'Local diagnosis only; zero paid authorization','clarifications':{'D1':'No effective target-workflow candidate tests demonstrated; reuse is permitted, unrelated copied CGKN tests do not cover absent video/promotion workflows. This supplements rationale, not a regrade.','domain':'UNTESTED/NO_CANDIDATE_DOMAIN_OUTPUT; human pending separate','old_self_evolve':'All four actual runs retained; runnable parent baseline did not establish maintenance of self-built workflow','future_self_evolve':'Require a new real dependent workflow plus necessary data/interfaces or BLOCKED_BY_PREDECESSOR'}})
    save(out/'old-records-unchanged.json',{'original_records':unchanged,'old_experiment_sources':old_code,'ledger_calls':ledger['totals']['api_calls'],'ledger_cost':ledger['totals']['estimated_cost'],'new_paid_calls':0,'forbidden_provider_events':(ROOT/'forbidden-provider.jsonl').read_text() if (ROOT/'forbidden-provider.jsonl').exists() else ''})
    assert result==0 and gate.returncode==0
if __name__=='__main__':main()
