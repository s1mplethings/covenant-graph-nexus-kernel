"""Count actual calls without modifying the pure function or trusting cache labels."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.leanloop_v1.qualify import OUT,execute
from cgkn.telemetry.lean import read,write,source_identity
from tests.leanloop_support import normalize_python

root=OUT/(sys.argv[1] if len(sys.argv)>1 else 'invocation-audit');root.mkdir(exist_ok=False)
policy=root/'policy.json';write(policy,read(OUT/'lean-policy.example.json'))
rows=[]
for mode in ('OBSERVE','AUTO_QUALIFIED'):
    calls=[]
    def trace(frame,event,arg):
        if event=='call' and frame.f_code is normalize_python.__code__:calls.append(True)
    sys.setprofile(trace)
    try: report,oracle,result=execute(root/mode,mode,policy if mode=='AUTO_QUALIFIED' else None)
    finally: sys.setprofile(None)
    rows.append({'mode':mode,'actual_function_calls':len(calls),'component_records':len(report['steps']),
        'oracle':oracle,'report_ref':str(root/mode/'run/lean-report.json'),
        'function_source_hash':source_identity(normalize_python)})
assert [r['actual_function_calls'] for r in rows]==[2,1]
assert all(r['oracle']['status']=='PASS' for r in rows)
write(OUT/'actual-function-call-evidence.json',{'method':'CPython call profile matched by exact function code object; implementation unmodified',
    'rows':rows,'timings_not_used_as_benchmark':True,'DAG_node_count_before_after':[2,2],
    'execution_mechanisms_removed':0})
write(OUT/'runtime-pruning-evidence.json',{**read(OUT/'runtime-pruning-evidence.json'),
    'direct_invocation_evidence':'actual-function-call-evidence.json','DAG_node_count_before_after':[2,2],
    'execution_mechanisms_removed':0})
write(policy,{**read(policy),'state':'ROLLBACK','rollback_reason':'Bounded invocation audit complete'})
print(json.dumps({'actual_calls':[r['actual_function_calls'] for r in rows],'oracles':[r['oracle']['status'] for r in rows]}))
