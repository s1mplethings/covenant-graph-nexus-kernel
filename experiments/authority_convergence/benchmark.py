"""Alternating warmed controller trials, identical effects and persisted history."""
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/execution-authority-convergence'


def main():
    sys.path.insert(0,str(ROOT))
    spec=importlib.util.spec_from_file_location('trial',Path(__file__).with_name('test_loop_trial.py'))
    trial=importlib.util.module_from_spec(spec);spec.loader.exec_module(trial)
    # Exclude parsing/importing the archived source from all timing samples.
    old={(m.__name__,n):trial.old_function(m,n) for m,n in [(trial.conversation,'run_agent_loop'),(trial.dynamic,'_run_agent_turn')]}
    trial.old_function=lambda m,n:old[m.__name__,n]
    current=trial.candidate();trial.candidate=lambda:current
    transcript=[{'actions':[{'type':'write_file','fail':True}]},{'actions':[{'type':'write_file'}]}]
    rows=[]
    with tempfile.TemporaryDirectory(prefix='cgkn-authority-bench-') as tmp:
        for mode in ('conversation','step'):
            for repeat in range(12):
                for version in (('old','new') if repeat%2==0 else ('new','old')):
                    target=Path(tmp)/f'{mode}-{repeat}-{version}'
                    wall=time.perf_counter();cpu=time.process_time()
                    result=trial.invoke(version,mode,target,transcript)
                    rows.append({'mode':mode,'repeat':repeat,'version':version,'warmup':repeat<2,
                        'seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu,
                        'model_calls':len(result['agent_inputs']),'tool_calls':len(result['actions']),
                        'status':result['result']['status'],'paid_posts':0})
            for version in ('old','new'):
                tracemalloc.start()
                trial.invoke(version,mode,Path(tmp)/f'alloc-{mode}-{version}',transcript)
                _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
                rows.append({'mode':mode,'version':version,'peak_python_allocated_bytes':peak})
    summaries=[]
    for mode in ('conversation','step'):
        for version in ('old','new'):
            selected=[r for r in rows if r['mode']==mode and r['version']==version and r.get('warmup') is False]
            values=sorted(r['seconds'] for r in selected)
            summaries.append({'mode':mode,'version':version,'samples':len(values),
                'median_seconds':statistics.median(values),'p95_seconds':values[-1],
                'cpu_seconds_total':sum(r['cpu_seconds'] for r in selected)})
    (OUT/'controller-performance.json').write_text(json.dumps({'scope':'local persisted-history controller overhead, identical fixed-output executor; not a model quality or whole-project speed benchmark; two warmups then ten alternating samples; no significance claim','samples':rows,'summaries':summaries},indent=2))
    print(json.dumps(summaries))


if __name__=='__main__':main()
