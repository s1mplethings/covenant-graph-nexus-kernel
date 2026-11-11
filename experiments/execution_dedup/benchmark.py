"""Warmed repeated primitive measurements; no model or network traffic."""
import json
from pathlib import Path
import statistics
import time
import tracemalloc
from types import SimpleNamespace

from experiments.execution_dedup.candidates import freeze, ordered_nodes
from experiments.execution_dedup.test_candidates import original

OUT=Path(__file__).resolve().parents[2]/'artifacts/substrate-replacement-v2'


def measure(call):
    for _ in range(10): call()
    samples=[];cpu=time.process_time()
    for _ in range(15):
        start=time.perf_counter()
        for _ in range(30):call()
        samples.append((time.perf_counter()-start)/30)
    cpu=time.process_time()-cpu
    tracemalloc.start();call();_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return {'median_seconds':statistics.median(samples),'p95_seconds':sorted(samples)[-1],
            'cpu_seconds_450_calls':cpu,'peak_allocated_bytes_single_call':peak,'samples':samples}


def main():
    old_freeze=original('cgkn/component/spec.py',{'_freeze'})['_freeze']
    old_graph=original('cgkn/orchestration/execution_dag.py',{'topological_order'})['topological_order']
    value={'conditions':['must preserve data']*10,'sources':{str(i):{'inputs':[1,2,3]} for i in range(20)}}
    rows={'freeze':{'old':measure(lambda:old_freeze(value)),'candidate':measure(lambda:freeze(value))}}
    for size in (20,200,1000):
        deps={f'n{i}':tuple(f'n{j}' for j in range(max(0,i-3),i)) for i in range(size)}
        obj=SimpleNamespace(by_id=deps,nodes=[SimpleNamespace(id=n,depends_on=d) for n,d in deps.items()])
        rows[f'graph-{size}']={'old':measure(lambda:old_graph(obj)),
                               'candidate':measure(lambda:ordered_nodes(deps))}
    (OUT/'primitive-benchmarks.json').write_text(json.dumps(rows,indent=2))
    print(json.dumps({k:{side:round(data['median_seconds']*1000,3) for side,data in v.items()} for k,v in rows.items()}))


if __name__=='__main__':main()
