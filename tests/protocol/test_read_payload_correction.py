import pytest
from cgkn.protocol.compiler import compile_worker
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.exchange import SchemaRepairFailed
from tests.protocol.test_semantic_integration import Fake,run,table

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

@pytest.mark.parametrize('payload',[None,'',{'find':'x','replace':'y'}])
def test_read_payload_is_rejected_then_model_can_remove_only_invalid_field(payload):
    t=table();bad={'op':0,'path':0,'payload':payload}
    with pytest.raises(ContractError,match='READ_WITH_UNRELATED_PAYLOAD') as caught:
        compile_worker(bad,t,bound_hash=t.hash,node_id='n')
    assert caught.value.repair_class=='R5'
    fake=Fake([bad,{'op':0,'path':0}]);events=[]
    result,_,stats=run(fake,events.append)
    assert len(fake.requests)==2 and stats['schema_repair_attempts']==1
    assert result['actions'][0]['action']=='read_file'
    assert events[-1]['semantic_diff']['changed_fields']==['payload']


def test_read_correction_cannot_turn_into_write():
    fake=Fake([{'op':0,'path':0,'payload':None},{'op':2,'path':0,'payload':'overwrite'}])
    with pytest.raises(ContractError,match='IMMUTABLE'):run(fake,lambda event:None)


def test_read_correction_repeats_are_bounded():
    fake=Fake([{'op':0,'path':0,'payload':None}]*3)
    with pytest.raises(SchemaRepairFailed):run(fake,lambda event:None)
    assert len(fake.requests)==3
