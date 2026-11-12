import json
from pathlib import Path
import pytest
from scripts import provider_api_budget as budget


def reservation(tmp_path,monkeypatch):
    monkeypatch.setenv('CGKN_PROVIDER_BUDGET_LEDGER',str(tmp_path/'ledger.json'))
    r=budget.reserve_call(case_id='fixture',purpose='GENERATION',model='fixture',request_identity='identity',
        estimated_input_tokens=1,requested_output_tokens=1,retry_count=0,
        execution_policy='accounting_only',authorization_reference='local-test',durable_response_required=True)
    budget.mark_request_started(r)
    return r


def test_success_requires_durable_response_even_when_cache_disabled(tmp_path,monkeypatch):
    r=reservation(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='SUCCEEDED_REQUIRES_DURABLE_RESPONSE'):
        budget.finalize_call(r,usage={},http_status=200,status='SUCCEEDED')
    response={'model':'actual-fixture','id':'response','usage':{'input_tokens':2,'output_tokens':3},'output':'complete'}
    budget.mark_response_received(r,response=response,http_status=200)
    row=json.loads(Path(r['path']).read_text())['calls'][0]
    assert row['status']=='RESPONSE_RECEIVED'
    assert row['terminal_commit_state']=='RESPONSE_PENDING_COMMIT'
    assert json.loads(Path(row['authoritative_response_ref']).read_text())['response']==response
    ledger_before=Path(r['path']).read_bytes()
    assert budget.load_authoritative_response('identity')==response
    assert Path(r['path']).read_bytes()==ledger_before
    budget.finalize_call(r,usage=response['usage'],http_status=200,status='SUCCEEDED')
    row=json.loads(Path(r['path']).read_text())['calls'][0]
    assert row['status']=='SUCCEEDED' and row['actual_model']=='actual-fixture'


@pytest.mark.parametrize('mode',['missing','tampered'])
def test_archive_loss_before_commit_cannot_succeed(tmp_path,monkeypatch,mode):
    r=reservation(tmp_path,monkeypatch)
    budget.mark_response_received(r,response={'model':'actual','usage':{}},http_status=200)
    row=json.loads(Path(r['path']).read_text())['calls'][0]
    path=Path(row['authoritative_response_ref'])
    if mode=='missing':path.unlink()
    else:path.write_text('{}')
    with pytest.raises(ValueError,match='SUCCEEDED_REQUIRES_DURABLE_RESPONSE'):
        budget.finalize_call(r,usage={},http_status=200,status='SUCCEEDED')
    assert json.loads(Path(r['path']).read_text())['calls'][0]['status']=='RESPONSE_RECEIVED'


def test_failed_archive_write_never_publishes_response_received(tmp_path,monkeypatch):
    r=reservation(tmp_path,monkeypatch);write=budget._write
    def fail(path,value):
        if value.get('kind')=='ProviderTerminalResponse':raise OSError('disk failure')
        return write(path,value)
    monkeypatch.setattr(budget,'_write',fail)
    with pytest.raises(OSError,match='disk failure'):
        budget.mark_response_received(r,response={'model':'actual'},http_status=200)
    assert json.loads(Path(r['path']).read_text())['calls'][0]['status']=='REQUEST_STARTED'
