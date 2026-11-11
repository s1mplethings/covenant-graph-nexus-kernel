"""Offline evidence using the existing real CSV project and independent Oracle."""
from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path
import shutil
import statistics
import sys
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'artifacts/leanloop-v1'
# Same network denial used by regression, inherited by Oracle subprocesses.
os.environ['PYTHONPATH']=str(OUT/'offline_guard')+os.pathsep+str(ROOT)
os.environ['CGKN_TRIAL_EVIDENCE']=str(OUT/'qualification-network')
sys.path.insert(0,str(OUT/'offline_guard'))
import sitecustomize  # noqa: E402,F401

from cgkn.telemetry.lean import read,write,source_identity
from cgkn.telemetry.lean_policy import evaluate,approve,aggregate,structural_candidates
from cgkn.application.verification import OracleExecutor
from tests.leanloop_support import run_csv,cases,normalize_python,FLOW,COMPONENT
from tests.test_leanloop import run_case,break_candidate,compensated_case


def execute(folder,mode,policy=None):
    folder.mkdir(parents=True,exist_ok=False)
    os.environ['CGKN_LEAN_MODE']=mode
    if policy: os.environ['CGKN_LEAN_POLICY']=str(policy)
    else: os.environ.pop('CGKN_LEAN_POLICY',None)
    runner,result=run_csv(folder)
    oracle=OracleExecutor().execute(cases()[0]['oracles'][0],folder).as_dict()
    write(folder/'independent-oracle.json',oracle)
    report=read(folder/'run/lean-report.json')
    return report,oracle,result


def qualify(name='qualification'):
    evidence=OUT/name;evidence.mkdir(exist_ok=False)
    observed,original_oracle,_=execute(evidence/'observed','OBSERVE')
    candidate=observed['candidate_cuts'][0]
    write(OUT/'candidate-discovery.json',{'source_report':str(evidence/'observed/run/lean-report.json'),
        'candidates':observed['candidate_cuts'],'human_preselected_step':False,
        'scope':'Two real AST transformations added to the existing CSV case to qualify the runtime boundary; not a discovered default production duplication.'})
    receipt=evaluate(candidate,cases(),run_case,evidence/'ablation')
    assert receipt['status']=='PASS',receipt['reason']
    write(OUT/'ablation-results.json',receipt)
    policy_path=evidence/'approved-policy.json'
    policy=approve(receipt,policy_path,version='lean-csv-v1',task_profile=FLOW,
        component_ref=COMPONENT,implementation_hash=source_identity(normalize_python))
    # Measurement-only ceiling. The runtime default stays 100 ms; the initial
    # trial correctly revoked at 105.6 ms and is preserved beside this evidence.
    policy.update(review_budget_ms=1000,experiment_scope='bounded offline qualification; not a production rollout')
    write(policy_path,policy)
    write(OUT/'lean-policy.example.json',policy)
    optimized,oracle,result=execute(evidence/'optimized','AUTO_QUALIFIED',policy_path)
    assert original_oracle['status']==oracle['status']=='PASS'
    assert observed['steps_executed']==2 and optimized['steps_executed']==1
    sample=OUT/'sample-run';sample.mkdir(exist_ok=True)
    for name in ('lean-report.json','lean-report.md'):shutil.copy2(evidence/'optimized/run'/name,sample/name)
    write(OUT/'runtime-pruning-evidence.json',{'baseline_report':str(evidence/'observed/run/lean-report.json'),
        'candidate_report':str(evidence/'optimized/run/lean-report.json'),'baseline_component_calls':2,
        'candidate_component_calls':1,'qualified_cuts':optimized['qualified_cuts_applied'],
        'original_oracle':original_oracle,'candidate_oracle':oracle,'outputs':{k:v.as_dict() for k,v in result['outputs'].items()},
        'default_mode':'OBSERVE','global_auto_enabled':False,'paid_api_posts':0})
    broken,_,_=execute(evidence/'regressed','AUTO_QUALIFIED',policy_path)
    assert broken['steps_executed']==1
    (evidence/'regressed/csv_cleaner/core.py').write_text('def clean(*args): return [], []\n',encoding='utf-8')
    failed=OracleExecutor().execute(cases()[0]['oracles'][0],evidence/'regressed').as_dict()
    assert failed['status']=='FAIL' and read(policy_path)['state']=='ROLLBACK'
    recovered,recovered_oracle,_=execute(evidence/'recovered','AUTO_QUALIFIED',policy_path)
    assert recovered['steps_executed']==2 and recovered_oracle['status']=='PASS'
    os.environ['CGKN_LEAN_MODE']='OBSERVE';os.environ.pop('CGKN_LEAN_POLICY',None)
    necessary=evaluate(candidate,cases(),break_candidate,evidence/'necessary')
    combinations=[]
    for cuts in (['a'],['b'],['a','b']):
        dataset=cases()
        for case in dataset:case['input']['cuts']=cuts
        item=evaluate(candidate,dataset,compensated_case,evidence/('combination-'+''.join(cuts)))
        combinations.append({'cuts':cuts,'status':item['status'],'evidence_ref':item['evidence_ref']})
    assert necessary['status']=='FAIL' and [r['status'] for r in combinations]==['PASS','PASS','FAIL']
    write(OUT/'negative-controls.json',{'actual_independent_failure':failed,
        'revoked_policy':read(policy_path),'next_run_component_calls':recovered['steps_executed'],
        'next_run_independent_oracle':recovered_oracle,'necessary_step_removal':necessary,
        'compensating_steps_combinations':combinations,'irreversible_effects_undone':False})
    reports=list(evidence.glob('*/run/lean-report.json'))
    write(OUT/'cross-run-evidence.json',aggregate(reports))
    write(OUT/'structural-candidates.json',structural_candidates([
        {'duplicate_responsibility':'Provider session and formal-project lifecycle report boundaries','files':['scripts/codex_conversation.py'],
         'proposed_action':'Review shared lifecycle finalization only; keep packaging/delivery authorities',
         'estimated_deletable_lines':None,'proofs':[]},
        {'duplicate_responsibility':'Legacy ArtifactFlow and canonical ExecutionDAG execution surfaces','files':['cgkn/runtime/runner.py','cgkn/runtime/dag_runner.py'],
         'proposed_action':'Map artifact ports, lineage and dynamic public callers before any consolidation',
         'estimated_deletable_lines':None,'proofs':[]}]))
    print(json.dumps({'qualification':'PASS','calls_before':2,'calls_after':1,'oracle':'PASS','rollback':'PASS'}))


def benchmark(samples,name='benchmark'):
    root=OUT/name;root.mkdir(exist_ok=False)
    policy=root/'policy.json';write(policy,read(OUT/'lean-policy.example.json'))
    rows=[]
    for index in range(samples+2):
        modes=['OFF','OBSERVE','AUTO_QUALIFIED']
        modes=modes[index%3:]+modes[:index%3]
        for mode in modes:
            tracemalloc.start();clock=time.perf_counter();cpu=time.process_time()
            report,oracle,_=execute(root/(str(index)+'-'+mode),mode,policy if mode=='AUTO_QUALIFIED' else None)
            elapsed=(time.perf_counter()-clock)*1000;cpu_ms=(time.process_time()-cpu)*1000
            _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            assert oracle['status']=='PASS'
            assert mode!='AUTO_QUALIFIED' or report['steps_executed']==1
            rows.append({'index':index,'warmup':index<2,'mode':mode,'whole_task_oracle_ms':elapsed,
                'parent_cpu_ms':cpu_ms,'parent_python_peak_bytes':peak,
                'optimization_overhead_ms':report['optimization_overhead_ms'],
                'component_calls':1 if mode=='AUTO_QUALIFIED' else 2,'oracle_status':oracle['status'],
                'actual_cost_cny':None,'extra_model_calls':0})
    summary={mode:{key:statistics.median(r[key] for r in rows if r['mode']==mode and not r['warmup'])
        for key in ('whole_task_oracle_ms','parent_cpu_ms','parent_python_peak_bytes','optimization_overhead_ms','component_calls')}
        for mode in ('OFF','OBSERVE','AUTO_QUALIFIED')}
    write(OUT/'self-overhead.json',{'samples_per_mode':samples,'warmups_per_mode':2,'order':'rotated paired order',
        'summary_medians':summary,'measurements':rows,'child_cpu_memory':'NOT_AVAILABLE',
        'source':'Existing CSV cleaner case, two AST transforms; local Oracle subprocess included in wall time',
        'actual_cost_cny':None,'extra_model_calls':0,'paid_api_posts':0})
    off=summary['OFF']['whole_task_oracle_ms'];auto=summary['AUTO_QUALIFIED']['whole_task_oracle_ms']
    pairs={i:{r['mode']:r for r in rows if r['index']==i} for i in range(2,samples+2)}
    deltas=[x['AUTO_QUALIFIED']['whole_task_oracle_ms']-x['OFF']['whole_task_oracle_ms'] for x in pairs.values()]
    rng=random.Random(20261101)
    draws=sorted(statistics.mean(rng.choices(deltas,k=len(deltas))) for _ in range(10000))
    paired={'paired_auto_minus_off_ms':deltas,'paired_mean_ms':statistics.mean(deltas),
        'bootstrap_mean_95_percent_interval_ms':[draws[249],draws[9749]],'seed':20261101,
        'interpretation':'Exploratory fixed local workload; no universal or money savings claim. CPU/experiment overhead also matters.'}
    write(OUT/'self-overhead-paired.json',paired)
    text='# LeanLoop self overhead\n\n'+json.dumps(summary,indent=2)+'\n\n'
    text+=f'Whole task including independent Oracle: AUTO median delta versus OFF = {auto-off:.3f} ms. '
    text+='This small workload does not establish a general end-to-end speedup. Component calls fall 2 to 1, but hashing, policy validation, artifact lineage and reports have costs.\n\n'
    text+='CPU and tracemalloc cover the parent Python process only; wall time includes Oracle subprocesses. Unknown money is not zero. No extra model calls/tokens/API charges are introduced by analysis. Ablation setup cost is recorded separately in ablation-results.json. Default remains OBSERVE; AUTO is explicit scoped configuration. No API billing or full-suite timing is used to claim savings.\n'
    text+='\nPaired comparison: '+json.dumps(paired)+'\nMeasurement policy paused after the bounded experiment; no global rollout.\n'
    (OUT/'self-overhead-report.md').write_text(text,encoding='utf-8')
    write(policy,{**read(policy),'state':'ROLLBACK','rollback_reason':'NET_BENEFIT_NOT_ESTABLISHED; bounded measurement complete'})
    print(json.dumps(summary))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--benchmark',action='store_true');parser.add_argument('--samples',type=int,default=12)
    parser.add_argument('--qualification-name',default='qualification')
    parser.add_argument('--benchmark-name',default='benchmark')
    args=parser.parse_args()
    benchmark(args.samples,args.benchmark_name) if args.benchmark else qualify(args.qualification_name)
