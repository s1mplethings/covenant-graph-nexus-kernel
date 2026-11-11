import json
import pytest
from cgkn.adapters.veriarbor.provider_novelty_adapter import request_novelty, novelty_disposition

def declaration(milestone='M11', decision=1):
    return {'schema_name':'milestone_declaration', 'system':'same Planner declaration',
            'user':json.dumps({'context':{'goal':'complete product',
                'current_requirements':{milestone:{'description':milestone+' public contract'}},
                'dependency_contracts':[], 'verified_state':[], 'unresolved_acceptance':[]},
                'tables':{'mode':'MILESTONE_MODE'}, 'semantic_attempt_id':str(decision)})}

def test_distinct_registered_milestones_have_new_contracts():
    old=request_novelty(declaration(),'agent')
    new=request_novelty(declaration('M12'),'agent')
    assert old['contracts'] != new['contracts']
    assert novelty_disposition([old],new)=='EXECUTE'
    assert novelty_disposition([new],request_novelty(declaration('M12',99),'agent'))=='NO_NOVEL_DELTA'

def test_recorded_declarations_dispatch_once_per_contract(tmp_path):
    from cgkn.providers import ModelRoleConfig, ProviderCompletion
    from cgkn.providers.recording import RecordedCompletionClient
    from cgkn.providers.gateway_client import GatewayCompletionError
    from cgkn.state import FileRunStore
    class Client:
        calls=0
        def complete(self,**kwargs):
            self.calls+=1
            return ProviderCompletion('{}','fixture','response',{})
    client=Client()
    recorded=RecordedCompletionClient(client,FileRunStore(tmp_path),'p','r')
    config=ModelRoleConfig('agent','fixture')
    recorded.complete(**declaration(),config=config)
    recorded.complete(**declaration('M12'),config=config)
    with pytest.raises(GatewayCompletionError,match='NO_NOVEL_DELTA'):
        recorded.complete(**declaration('M12',99),config=config)
    assert client.calls==2
