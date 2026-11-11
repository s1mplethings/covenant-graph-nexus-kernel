"""Read-only baselines and controlled local budget-lock reproduction."""
import hashlib,json,sys,time,threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/provider-parallel-final-20261029'
OLD=ROOT/'artifacts/api-progress-clock-20261029/live-authorized-01'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding='utf-8')

def baseline():
    OUT.mkdir(exist_ok=False)
    files={Path(c['path']) for c in json.loads((OLD/'protected-files-check.json').read_text())['checks']}
    files.update(p for p in OLD.rglob('*') if p.is_file())
    files.update(p for p in Path('F:/CGKN-ITER-116/real-dev-01').rglob('*') if p.is_file())
    save(OUT/'protected-before.json',{str(p):sha(p) for p in files if p.is_file()})
    for folder in ('cgkn','scripts','experiments/api_acceptance','plugins/cgkn/scripts','tests/providers','tests/runtime'):
        for p in (ROOT/folder).rglob('*.py'):
            dest=OUT/'baseline'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())

def lock_probe(label):
    from scripts.provider_api_budget import _locked
    p=OUT/(label+'-probe.json');values=[]
    for i in range(3):
        held=threading.Event()
        def holder():
            with _locked(p):held.set();time.sleep(.06)
        t=threading.Thread(target=holder);t.start();held.wait()
        start=time.perf_counter()
        with _locked(p):wait=time.perf_counter()-start
        t.join();values.append(wait)
    save(OUT/(label+'-lock.json'),dict(hold_seconds=.06,wait_seconds=values,lock_file_bytes=p.with_suffix('.json.lock').stat().st_size))

if __name__=='__main__':
    if sys.argv[1]=='baseline':baseline()
    else:lock_probe(sys.argv[1])
