"""Real loopback Gateway and real budget ledger through both old/new controllers."""
import json
import os
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).parent))
from test_loop_trial import conversation, dynamic, old_function
from tests.providers.test_domestic_repair import isolated, fake_gateway, admit


@pytest.mark.parametrize('version',['old','new'])
@pytest.mark.parametrize('mode',['conversation','step'])
@pytest.mark.parametrize('fault',['unknown','exhausted'])
def test_no_automatic_paid_resubmission(fake_gateway,isolated,monkeypatch,tmp_path,version,mode,fault):
    state,_=isolated
    base=json.loads((state/'session.json').read_text())['base_url']
    monkeypatch.setattr(conversation.check_connectivity,'_resolve_api_credentials',lambda:{'api_key':'offline-token','base_url':base})
    admit(monkeypatch,tmp_path,CGKN_PROVIDER_MAX_OUTPUT_TOKENS='100000',CGKN_PROVIDER_MAX_INPUT_TOKENS='1000000',
          **({'CGKN_PROVIDER_MAX_API_CALLS':'0'} if fault=='exhausted' else {}))
    fake_gateway[1]['mode']='unknown'
    session=tmp_path/'session.jsonl';project=tmp_path/'project'
    conversation.append_event(session,{'kind':'user','role':'user','text':'Do one bounded task; never repeat an unknown submission.'})
    if mode=='step':
        fn=old_function(dynamic,'_run_agent_turn') if version=='old' else dynamic._run_agent_turn
        result=fn(session_file=session,executor=conversation.local_agent_actions.LocalAgentActionExecutor(project),
            manifest={'roles':[{'id':'worker'}]},step={'id':'work','role':'worker','allowed_actions':['write_file']},
            model='qwen',timeout=2,max_turns=2,agent=None)
    else:
        fn=old_function(conversation,'run_agent_loop') if version=='old' else conversation.run_agent_loop
        result=fn(session_path=session,project_dir=project,model='qwen',timeout=2,max_turns=2)
    evidence={'version':version,'mode':mode,'fault':fault,'posts':len(fake_gateway[0]),'result':result,
              'ledger':json.loads((tmp_path/'budget.json').read_text()) if (tmp_path/'budget.json').exists() else {}}
    output=Path(os.environ['CGKN_TRIAL_EVIDENCE'])/'provider-boundary'
    output.mkdir(exist_ok=True);(output/f'{version}-{mode}-{fault}.json').write_text(json.dumps(evidence,indent=2))
    assert len(fake_gateway[0])==(1 if fault=='unknown' else 0)
    assert result['status'] not in ('PASS','DELIVERED','SUCCEEDED','ready','ok')
