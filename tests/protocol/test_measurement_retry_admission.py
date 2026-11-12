import pytest
from cgkn.orchestration import CapabilityTree
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.protocol.normalization import ContractError
from tests.protocol.test_repair_path import snapshot,packet,run,failed_snapshot

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

@pytest.mark.parametrize('kind',[4,5])
def test_measurement_retry_feedback_retains_measurement_authority(kind):
 s=snapshot();tree=CapabilityTree('goal',());tree=apply_tree_edits(tree,run({**packet(),'task_kind':kind},s,tree)['edits'],known_capabilities={'code'})
 before=tree.as_dict()
 with pytest.raises(ContractError,match='RETRY_CHANGES_SEMANTICS') as exc:
  run({**packet(),'action':3,'task_kind':kind},failed_snapshot(s),tree)
 assert exc.value.details['allowed_action_ids']==[3]
 assert exc.value.details['allowed_fields']==['action','target','confidence','needs_user']
 assert 'Omit task_kind' in exc.value.details['instruction']
 assert tree.as_dict()==before
 result=run({'action':3,'target':0},failed_snapshot(s),tree)
 assert [e.operation for e in result['edits']]==['retry_node']
 assert apply_tree_edits(tree,result['edits'],known_capabilities={'code'}).as_dict()==before
