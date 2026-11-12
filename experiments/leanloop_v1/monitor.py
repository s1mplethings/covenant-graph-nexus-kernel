"""Read-only owned process/thread/handle sampling; no command lines or secrets."""
import json
from pathlib import Path
import sys
import time

import psutil

OUT=Path(__file__).resolve().parents[2]/'artifacts/leanloop-v1'
run=OUT/sys.argv[1]
start=json.loads((run/'start.json').read_text())
root=psutil.Process(start['pid'])
identity=root.create_time()
seen={}
with (run/'resources.jsonl').open('w',encoding='utf-8') as log:
    while root.is_running() and root.create_time()==identity:
        rows=[]
        try:
            current=root.environ().get('PYTEST_CURRENT_TEST','')
            family=[root]+root.children(recursive=True)
        except psutil.Error:
            break
        for process in family:
            try:
                row={'pid':process.pid,'created':process.create_time(),'name':process.name(),
                     'threads':process.num_threads(),'handles':process.num_handles(),
                     'rss':process.memory_info().rss,'cpu_seconds':sum(process.cpu_times()[:2])}
                rows.append(row);seen[process.pid]=row
            except psutil.Error:
                pass
        log.write(json.dumps({'epoch':time.time(),'test':current,'processes':rows})+'\n');log.flush()
        time.sleep(1)
surviving=[]
for row in seen.values():
    try:
        process=psutil.Process(row['pid'])
        if process.create_time()==row['created'] and process.is_running():surviving.append(row)
    except psutil.Error:
        pass
(run/'resource-completion.json').write_text(json.dumps({'scope':'owned descendants observed once per second; short-lived processes may be missed; baseline monitor starts after suite launch','observed_processes':len(seen),'surviving_observed_identities':surviving},indent=2))
