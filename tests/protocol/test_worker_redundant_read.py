import json
import pytest
from cgkn.protocol.adapters import SemanticWorkerClient
from cgkn.protocol.compiler import TableSnapshot,compile_worker
from cgkn.protocol.normalization import ContractError,digest
from cgkn.providers import ProviderCompletion,ModelRoleConfig


def test_duplicate_read_corrects_with_full_context_without_reexecuting_read():
    class Client:
        def __init__(self):self.requests=[]
        def complete(self,**kw):
            self.requests.append(kw)
            packet={'op':0,'path':0} if len(self.requests)==1 else {'op':3,'path':0,'payload':{'find':'old','replace':'new'}}
            return ProviderCompletion(json.dumps(packet),'fixture-model',str(len(self.requests)),{'input_tokens':1,'output_tokens':1})
    client=Client();trace=[]
    raw={'node_id':'n','goal':'fixture update','config':{'leaf_contract':{'target_scope':['module.py'],'read_scope':[]}},
         'observations':[{'action':'read_file','path':'module.py','content':'old'}]}
    result=SemanticWorkerClient(client,trace.append).complete(config=ModelRoleConfig('worker','fixture-model'),system='',user=json.dumps(raw),schema={},schema_name='fixture')
    assert len(client.requests)==2
    assert 'READ_ALREADY_IN_CONTEXT' in client.requests[1]['user']
    assert json.loads(result.text)['actions']==[{'action':'patch_file','path':'module.py','find':'old','replace':'new'}]
    assert any(e.get('status')!='COMPILED' for e in trace)


@pytest.mark.parametrize('op',[0,1,2,3])
def test_read_guard_does_not_restrict_unseen_read_list_or_write(op):
    snap=TableSnapshot({'paths':[{'path':'module.py','readable':True,'writable':True}]})
    packet={'op':op,'path':0}
    if op==2:packet['payload']='new'
    if op==3:packet['payload']={'find':'old','replace':'new'}
    assert compile_worker(packet,snap,bound_hash=snap.hash,node_id='n')['actions']


def test_observed_hash_rejects_duplicate_not_escalation():
    snap=TableSnapshot({'paths':[{'path':'module.py','readable':True,'writable':True,'observed_content_sha256':digest(b'old')}]})
    with pytest.raises(ContractError,match='READ_ALREADY_IN_CONTEXT'):
        compile_worker({'op':0,'path':0},snap,bound_hash=snap.hash,node_id='n')
    result=compile_worker({'escalation':True,'expected_local_effect':'Need a missing public requirement'},snap,bound_hash=snap.hash,node_id='n')
    assert result['needs_escalation'] and result['actions']==[]
