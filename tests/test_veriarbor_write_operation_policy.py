"""An explicit repair strategy can narrow, never expand, writable operations."""
import json
import pytest
from cgkn.protocol.adapters import SemanticWorkerClient
from cgkn.protocol.compiler import TableSnapshot,compile_worker
from cgkn.protocol.normalization import ContractError
from cgkn.providers import ModelRoleConfig,ProviderCompletion

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def test_full_file_policy_rejects_partial_patch_but_allows_read_and_full_write():
    table=TableSnapshot({'paths':[{'path':'module.py','readable':True,'writable':True}],
                         'allowed_write_operations':[2]})
    with pytest.raises(ContractError,match='WRITE_OPERATION_POLICY_VIOLATION'):
        compile_worker({'op':3,'path':0,'payload':{'find':'old','replace':'new'}},table,bound_hash=table.hash,node_id='n')
    for packet in ({'op':0,'path':0},{'op':2,'path':0,'payload':'value = 2\n'}):
        assert compile_worker(packet,table,bound_hash=table.hash,node_id='n')['actions']

def test_default_patch_permission_and_read_only_scope_remain_unchanged():
    table=TableSnapshot({'paths':[{'path':'module.py','readable':True,'writable':True}]})
    assert compile_worker({'op':3,'path':0,'payload':{'find':'old','replace':'new'}},table,bound_hash=table.hash,node_id='n')['actions']
    table=TableSnapshot({'paths':[{'path':'dependency.py','readable':True,'writable':False}],
                         'allowed_write_operations':[2]})
    with pytest.raises(ContractError,match='UNAUTHORIZED_WRITE'):
        compile_worker({'op':2,'path':0,'payload':'value = 2\n'},table,bound_hash=table.hash,node_id='n')

@pytest.mark.parametrize('flag',[True,False,None,'true'])
def test_explicit_boolean_strategy_reaches_real_worker_table(flag):
    seen=[]
    class Client:
        def complete(self,**kwargs):
            request=json.loads(kwargs['user']);seen.append(request)
            operations=request['tables'].get('allowed_write_operations',[2,3])
            assert operations==([2] if flag is True else [2,3])
            return ProviderCompletion(json.dumps({'op':2,'path':0,'payload':'value = 2\n'}),'fake','fake',{})
    raw={'node_id':'n','goal':'Complete every required caller in one source write','observations':[],
         'config':{'leaf_contract':{'target_scope':['module.py'],'read_scope':[],
                                   'expected_delta':'Complete all caller paths'},
                   'repair_contract':{'strategy_semantics':{'full_file_write':flag}}}}
    result=SemanticWorkerClient(Client(),lambda event:None).complete(user=json.dumps(raw),config=ModelRoleConfig('worker','fake'))
    assert seen and json.loads(result.text)['actions'][0]['action']=='write_file'
