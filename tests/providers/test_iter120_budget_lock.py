"""Windows ledger contention must stay atomic without one-second backoff."""
import json,os,subprocess,sys,time,threading
from pathlib import Path
import pytest
from scripts.provider_api_budget import _locked


def test_invalid_existing_ledger_is_never_reset(tmp_path):
    from scripts import provider_api_budget as b
    p=tmp_path/'ledger.json';p.write_text('{malformed historical ledger')
    with pytest.raises(RuntimeError,match='never reset'):b._read(p,{})
    assert p.read_text()=='{malformed historical ledger'


@pytest.mark.skipif(os.name!='nt',reason='Windows sharing violation')
def test_atomic_ledger_replace_retries_reader_sharing_only(tmp_path,monkeypatch):
    from scripts import provider_api_budget as b
    original=Path.replace;calls=[]
    def transient(path,target):
        calls.append(str(path))
        if len(calls)==1:
            error=PermissionError('controlled reader sharing');error.winerror=32
            raise error
        return original(path,target)
    monkeypatch.setattr(Path,'replace',transient)
    b._write(tmp_path/'ledger.json',{'calls':[{'call_id':'kept'}]})
    assert len(calls)==2 and calls[0]==calls[1]
    assert json.loads((tmp_path/'ledger.json').read_text())['calls']==[{'call_id':'kept'}]

def test_short_lock_contention_and_stable_file_size(tmp_path):
    p=tmp_path/'budget.json';held=threading.Event()
    def holder():
        with _locked(p):held.set();time.sleep(.06)
    t=threading.Thread(target=holder);t.start();held.wait();start=time.monotonic()
    with _locked(p):elapsed=time.monotonic()-start
    t.join()
    assert .035<elapsed<.5
    for _ in range(30):
        with _locked(p):pass
    assert p.with_suffix('.json.lock').stat().st_size==1

def test_windows_processes_do_not_overreserve(tmp_path):
    code='''import os,pathlib,time
from scripts import provider_api_budget as b
root=pathlib.Path(os.environ['TEST_LOCK_ROOT'])
while not (root/'go').exists():time.sleep(.005)
try:
 r=b.reserve_call(case_id='offline',purpose='GENERATION',model='fixture',request_identity=str(os.getpid()),estimated_input_tokens=1,requested_output_tokens=1,retry_count=0)
 b.mark_request_started(r)
 status='accepted'
except b.ProviderBudgetExhausted:status='blocked'
(root/str(os.getpid())).write_text(status)
'''
    env={k:v for k,v in os.environ.items() if not k.startswith('CGKN_PROVIDER_')}
    env.update(TEST_LOCK_ROOT=str(tmp_path),CGKN_PROVIDER_BUDGET_LEDGER=str(tmp_path/'budget.json'),CGKN_PROVIDER_MAX_API_CALLS='2',
        CGKN_PROVIDER_MAX_INPUT_TOKENS='20',CGKN_PROVIDER_MAX_OUTPUT_TOKENS='20',CGKN_PROVIDER_MAX_ESTIMATED_COST='1',
        CGKN_PROVIDER_INPUT_COST_PER_MILLION='4',CGKN_PROVIDER_OUTPUT_COST_PER_MILLION='16')
    children=[subprocess.Popen([sys.executable,'-c',code],env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) for _ in range(8)]
    (tmp_path/'go').touch()
    for p in children:assert p.wait(20)==0
    assert [p.read_text() for p in tmp_path.iterdir() if p.name.isdigit()].count('accepted')==2
    ledger=json.loads((tmp_path/'budget.json').read_text());assert len(ledger['calls'])==2
    assert len({c['request_identity'] for c in ledger['calls']})==2
