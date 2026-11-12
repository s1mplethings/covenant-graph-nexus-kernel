"""Offline matched-load experiment; imports source read-only, writes only evidence."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

import psutil

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/execution-dedup/watchdog'


def child(source, target, loaded):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source))
    spec = importlib.util.spec_from_file_location('matched_test', source / 'tests/providers/test_network_reliability.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stop = threading.Event()
    loads, load_results = [], []
    if loaded:
        # Same bounded local runtime workload in each source variant.
        from scripts import customer_runtime_runner
        def workload():
            for i in range(8):
                if stop.is_set(): break
                project = target / f'runtime-{i}'
                project.mkdir()
                (project / 'index.html').write_text('<h1>matched offline workload</h1>')
                started = time.monotonic()
                try:
                    result = customer_runtime_runner.run(project, run_id=f'load-{i}', commit_sha='offline')
                    load_results.append({'status': result['status'], 'seconds': time.monotonic()-started,
                                         'cleanup': result['cleanup_result']})
                except Exception as exc:
                    load_results.append({'error': type(exc).__name__})
                stop.wait(.1)
        loads.append(threading.Thread(target=workload))
        for thread in loads: thread.start()
    began = time.monotonic()
    result = {'status': 'PASS', 'source': str(source), 'loaded': loaded}
    try:
        case = target / 'case'; case.mkdir()
        module.test_real_mihomo_crash_recovery_duplicate_and_normal_stop(case, 'crash')
    except Exception as exc:
        result.update(status='FAIL', error=type(exc).__name__, detail=str(exc), frames=traceback.format_tb(exc.__traceback__))
    finally:
        stop.set()
        for thread in loads: thread.join(30)
        result.update(seconds=time.monotonic()-began, load_results=load_results,
                      surviving_load_threads=sum(t.is_alive() for t in loads))
        (target / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['status']=='PASS' else 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--child', type=Path); p.add_argument('--target', type=Path)
    p.add_argument('--loaded', action='store_true'); p.add_argument('--repeats', type=int, default=3)
    a = p.parse_args()
    if a.child: return child(a.child, a.target, a.loaded)
    OUT.mkdir(parents=True, exist_ok=True)
    instrument = OUT / 'instrument'; instrument.mkdir(exist_ok=True)
    (instrument / 'sitecustomize.py').write_text('''import os, sys, threading, time, json
from pathlib import Path
if '--config' in sys.argv and 'run' in sys.argv:
    def sample():
        target=Path(os.environ['CGKN_DIAGNOSTIC_DIR'])/('stack-'+str(os.getpid())+'.jsonl')
        with target.open('a') as output:
            while True:
                rows={}
                for ident, frame in sys._current_frames().items():
                    frames=[]
                    while frame and len(frames)<14:
                        frames.append([frame.f_code.co_filename,frame.f_code.co_name,frame.f_lineno]);frame=frame.f_back
                    rows[str(ident)]=frames
                output.write(json.dumps({'at':time.time(),'frames':rows})+'\\n');output.flush();time.sleep(.2)
    threading.Thread(target=sample,daemon=True).start()
''', encoding='utf-8')
    variants = [('pre_round1', Path('D:/CGKN')), ('limited_change', ROOT)]
    summary = []
    for loaded in (False, True):
        for repeat in range(a.repeats):
            for label, source in (variants if repeat % 2 == 0 else variants[::-1]):
                target = OUT / f'{label}-{int(loaded)}-{repeat}'; target.mkdir()
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', CGKN_PYTEST_PROGRESS='0',
                           PYTHONPATH=str(instrument)+os.pathsep+str(source), CGKN_DIAGNOSTIC_DIR=str(target))
                command = [sys.executable, str(Path(__file__).resolve()), '--child', str(source), '--target', str(target)]
                if loaded: command.append('--loaded')
                observed, samples = {}, []
                with (target/'console.log').open('w') as output:
                    proc = subprocess.Popen(command, cwd=target, env=env, stdout=output, stderr=subprocess.STDOUT)
                    parent = psutil.Process(proc.pid); deadline=time.monotonic()+90
                    while proc.poll() is None and time.monotonic()<deadline:
                        rows=[]
                        for item in [parent]+parent.children(recursive=True):
                            try:
                                observed[(item.pid,item.create_time())]=item
                                rows.append({'pid':item.pid,'name':item.name(),'threads':item.num_threads(),
                                             'handles':item.num_handles(),'cpu':sum(item.cpu_times()[:2]),
                                             'rss':item.memory_info().rss})
                            except psutil.Error: pass
                        samples.append({'at':time.time(),'processes':rows});time.sleep(.1)
                    timed_out=proc.poll() is None
                    survivors=[]
                    for key,item in observed.items():
                        try:
                            if item.is_running(): survivors.append(item)
                        except psutil.Error: pass
                    residual=[{'pid':x.pid,'name':x.name()} for x in survivors]
                    # Only processes captured as descendants of this exact fixture.
                    for item in reversed(survivors):
                        try:item.terminate()
                        except psutil.NoSuchProcess:pass
                    _,alive=psutil.wait_procs(survivors,timeout=5)
                    for item in alive:
                        try:item.kill()
                        except psutil.NoSuchProcess:pass
                    proc.wait(timeout=5)
                (target/'resources.json').write_text(json.dumps(samples))
                result=json.loads((target/'result.json').read_text()) if (target/'result.json').exists() else {'status':'TIMEOUT'}
                result.update(label=label,repeat=repeat,timeout=timed_out,exit_code=proc.returncode,residual_processes=residual)
                summary.append(result);(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
                print(label,loaded,repeat,result['status'],len(residual),flush=True)
    return 0


if __name__=='__main__': raise SystemExit(main())
