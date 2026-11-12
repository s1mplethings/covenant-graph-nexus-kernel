"""Repeat the original/current runtime on identical loopback-only static inputs."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import customer_runtime_runner as current


def run_trial(module, project):
    children = []
    processes = []
    original_start, original_health = module._start_process, module._wait_for_health
    def start(*args, **kwargs):
        proc = original_start(*args, **kwargs)
        processes.append(proc)
        return proc
    def health(*args, **kwargs):
        result = original_health(*args, **kwargs)
        # Observe owned descendants before the old implementation reaps its parent.
        children.extend(psutil.Process(processes[-1].pid).children(recursive=True))
        return result
    module._start_process, module._wait_for_health = start, health
    started = time.perf_counter()
    try:
        result = module.run(project, run_id='offline-comparison', candidate_id='fixed', commit_sha='offline')
        return {'status': result['status'], 'health': result['health_probe']['status_code'],
                'cleanup_removed': result['cleanup_result']['removed'],
                'candidate_hash': result['candidate_hash'],
                'seconds': time.perf_counter() - started}
    finally:
        module._start_process, module._wait_for_health = original_start, original_health
        for child in children:
            try:
                if child.is_running():
                    child.terminate()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(children, timeout=5)


if __name__ == '__main__':
    baseline = Path('D:/CGKN/scripts/customer_runtime_runner.py')
    spec = importlib.util.spec_from_file_location('substrate_original_runtime', baseline)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    results = []
    with tempfile.TemporaryDirectory() as directory:
        for index in range(3):
            pair = {}
            for name, module in [('original', old), ('current', current)]:
                project = Path(directory) / f'{index}-{name}'
                project.mkdir()
                (project / 'index.html').write_text('<h1>fixed offline fixture</h1>', encoding='utf-8')
                pair[name] = run_trial(module, project)
                assert pair[name]['health'] == 200
            assert pair['current']['status'] == 'PASS' and pair['current']['cleanup_removed']
            assert pair['original']['candidate_hash'] == pair['current']['candidate_hash']
            results.append(pair)
    (ROOT / 'artifacts/substrate-migration/process-differential.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results))
