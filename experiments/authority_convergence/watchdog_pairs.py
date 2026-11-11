"""New paired evidence with working -m stack sampling; reuse original fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/execution-authority-convergence/watchdog-pairs'


def main():
    # Reuse the prior experiment's real crash fixture, loads and result recorder.
    sys.path.insert(0,str(ROOT))
    from experiments.execution_dedup.watchdog_compare import child
    if len(sys.argv)>1 and sys.argv[1]=='child':
        return child(Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4]=='1')
    OUT.mkdir(parents=True,exist_ok=True)
    instrument=OUT/'instrument';instrument.mkdir(exist_ok=True)
    (instrument/'sitecustomize.py').write_text('''import sys,os,threading,time,json
from pathlib import Path
if '--config' in sys.argv and 'run' in sys.argv:
    def sample():
        with (Path(os.environ['CGKN_DIAGNOSTIC_DIR'])/('stack-'+str(os.getpid())+'.jsonl')).open('a') as out:
            while True:
                rows={}
                for ident,frame in sys._current_frames().items():
                    frames=[]
                    while frame and len(frames)<18:
                        frames.append([frame.f_code.co_filename,frame.f_code.co_name,frame.f_lineno]);frame=frame.f_back
                    rows[str(ident)]=frames
                out.write(json.dumps({'epoch':time.time(),'frames':rows})+'\\n');out.flush();time.sleep(.2)
    threading.Thread(target=sample,daemon=True).start()
''',encoding='utf-8')
    variants=[('baseline',ROOT.parent/'execution-dedup-20261101'),('candidate',ROOT)]
    summary=[]
    for loaded in (False,True):
        for repeat in range(2):
            for label,source in (variants if repeat%2==0 else variants[::-1]):
                target=OUT/f'{label}-{int(loaded)}-{repeat}';target.mkdir()
                env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',CGKN_PYTEST_PROGRESS='0',
                         CGKN_APPLICATION_PROFILE=str(OUT.parent/'offline-profile.json'),
                         PYTHONPATH=str(instrument)+os.pathsep+str(source),CGKN_DIAGNOSTIC_DIR=str(target))
                with (target/'console.log').open('wb') as log:
                    process=subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'child',str(source),str(target),str(int(loaded))],cwd=target,env=env,stdout=log,stderr=subprocess.STDOUT)
                    parent=psutil.Process(process.pid);seen={};samples=[];deadline=time.monotonic()+90
                    while process.poll() is None and time.monotonic()<deadline:
                        rows=[]
                        try:family=[parent]+parent.children(recursive=True)
                        except psutil.Error:family=[]
                        for p in family:
                            try:
                                seen[p.pid,p.create_time()]=p
                                rows.append({'pid':p.pid,'name':p.name(),'threads':p.num_threads(),'handles':p.num_handles(),'rss':p.memory_info().rss,'cpu':sum(p.cpu_times()[:2])})
                            except psutil.Error:pass
                        samples.append({'epoch':time.time(),'processes':rows});time.sleep(.1)
                    timeout=process.poll() is None
                    alive=[]
                    for (pid,created),p in seen.items():
                        try:
                            if p.is_running() and p.create_time()==created:alive.append(p)
                        except psutil.Error:pass
                    residual=[{'pid':p.pid,'name':p.name()} for p in alive]
                    for p in reversed(alive):
                        try:p.terminate()
                        except psutil.NoSuchProcess:pass
                    _,left=psutil.wait_procs(alive,timeout=5)
                    for p in left:
                        try:p.kill()
                        except psutil.NoSuchProcess:pass
                    process.wait(timeout=5)
                (target/'resources.json').write_text(json.dumps(samples))
                result=json.loads((target/'result.json').read_text()) if (target/'result.json').exists() else {'status':'TIMEOUT'}
                result.update(label=label,repeat=repeat,timeout=timeout,exit_code=process.returncode,residual_before_owned_cleanup=residual,
                              stack_samples=sum(sum(1 for _ in p.open()) for p in target.glob('stack-*.jsonl')))
                summary.append(result);(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
                print(label,loaded,repeat,result['status'],result['stack_samples'],flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
