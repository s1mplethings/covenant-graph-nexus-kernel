"""Retired bridge retry tests now exercise the canonical session adapter.

The old tests invoked run_provider_execute_with_retries / execute_validated_provider_round,
which owned a competing retry lifecycle. Transport retry controls remain covered in
tests/providers; these cases prove the bridge never repeats execution or delivers partial work.
"""
from pathlib import Path
import pytest
from scripts import codex_conversation as bridge
from cgkn.application.software_project.service import SoftwareProjectGenerationService

@pytest.mark.parametrize('unknown',[False,True])
def test_provider_exception_preserved_without_bridge_retry_or_delivery(tmp_path,monkeypatch,unknown):
    session={'project_session_profile':str(tmp_path/'profile.json'),'whiteboard':{'project_summary':'fixed goal'}}
    monkeypatch.setattr(bridge,'load_session',lambda *a:session)
    monkeypatch.setattr(bridge,'save_session',lambda *a:None)
    monkeypatch.setattr(SoftwareProjectGenerationService,'__init__',lambda *a,**k:None)
    class Failure(RuntimeError):pass
    error=Failure('retained provider failure');error.outcome_unknown=unknown
    calls=[]
    def run(*a,**k):calls.append(1);raise error
    monkeypatch.setattr(SoftwareProjectGenerationService,'run_profile',run)
    monkeypatch.setattr(bridge,'send_delivery_from_manifest',lambda *a,**k:pytest.fail('partial delivery'))
    with pytest.raises(Failure) as caught:
        bridge.run_provider_generation_job(None,'p',tmp_path,tmp_path,'ignored',10)
    assert caught.value is error and calls==[1]
    assert session['generation']['delivery_status']=='NOT_EVALUATED'
    assert session['generation']['status']==('outcome_unknown' if unknown else 'blocked')
    if unknown:
        with pytest.raises(ValueError,match='PRIOR_OUTCOME_UNKNOWN'):
            bridge.run_provider_generation_job(None,'p',tmp_path,tmp_path,'ignored',10)
        assert calls==[1]

def test_old_retry_and_simulator_cannot_start_a_new_run():
    for name in ('run_provider_execute_with_retries','execute_validated_provider_round','run_simulator_preflight'):
        assert not hasattr(bridge,name)
