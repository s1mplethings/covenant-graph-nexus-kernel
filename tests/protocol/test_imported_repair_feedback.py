import pytest
from cgkn.orchestration import CapabilityTree
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.protocol.normalization import ContractError
from tests.protocol.test_repair_path import snapshot,packet,run,plain
from tests.protocol.test_imported_repair_admission import failed


def test_wrong_measurement_target_explains_initial_repair_without_admitting_it():
 s=snapshot();t=CapabilityTree('goal',())
 t=apply_tree_edits(t,run({**packet(),'task_kind':4,'scope':[1]},s,t)['edits'],known_capabilities={'code'})
 s=failed(s)
 with pytest.raises(ContractError) as error:
  run({**packet(),'action':4,'task_kind':3},s,t)
 d=error.value.details
 assert d['allowed_action_ids']==[1] and d['allowed_values']==[1,2]
 assert d['required_task_kind']==3
 original=t.as_dict()
 repair=run({**packet(),'task_kind':3,'target':1},s,t)
 assert t.as_dict()==original
 assert repair['edits'][0].node_id=='sibling'
 assert plain(repair['edits'][0].payload['config'])['imported_artifact_repair_evidence']


def test_feedback_does_not_grant_missing_failure_authority():
 s=snapshot();t=CapabilityTree('goal',())
 from tests.protocol.test_materialized_write_admission import materialized
 with pytest.raises(ContractError,match='MATERIALIZED_SCOPE_REQUIRES_EXPLICIT_CHANGE'):
  run({**packet(),'task_kind':3,'target':1},materialized(s),t)
