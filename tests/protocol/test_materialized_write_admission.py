import pytest
from cgkn.protocol.compiler import TableSnapshot
from cgkn.protocol.normalization import ContractError
from cgkn.orchestration import CapabilityTree
from tests.protocol.test_repair_path import snapshot,packet,run,initial,failed_snapshot,repair_packet

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def materialized(s):
 d=s.document;d['artifact_readiness']=[{'path':'module.py','materialized':True,'current_identity':'a'*64}]
 return TableSnapshot(d)

@pytest.mark.parametrize('kind',[2,3,6,7])
def test_new_writer_cannot_replace_materialized_milestone(kind):
 d=materialized(snapshot()).document;d['capabilities'][0]['task_kinds']=[2,3,4,5,6,7];s=TableSnapshot(d);tree=CapabilityTree('goal',())
 with pytest.raises(ContractError,match='MATERIALIZED_SCOPE_REQUIRES_EXPLICIT_CHANGE') as exc:
  run({**packet(),'task_kind':kind},s,tree)
 assert exc.value.details['materialized_paths']==['module.py']
 assert not tree.nodes

@pytest.mark.parametrize('kind',[4,5])
def test_measurement_of_materialized_scope_remains_available(kind):
 result=run({**packet(),'task_kind':kind},materialized(snapshot()),CapabilityTree('goal',()))
 assert result['admission_status']=='ADMISSIBLE'

def test_new_artifact_can_be_implemented_with_materialized_sibling():
 result=run({**packet(),'scope':[1]},materialized(snapshot()),CapabilityTree('goal',()))
 assert result['admission_status']=='ADMISSIBLE'

def test_observed_repair_preserves_explicit_change_authority():
 s,t=initial();result=run(repair_packet(),materialized(failed_snapshot(s)),t)
 config=next(e.payload['config'] for e in result['edits'] if e.operation=='update_config')
 assert config['repair_contract']['state']=='REPAIR_ADMITTED'

@pytest.mark.parametrize('action',[5,8])
def test_explicit_strategy_can_change_existing_writer(action):
 s,t=initial();result=run({**packet(),'action':action},materialized(s),t)
 config=next(e.payload['config'] for e in result['edits'] if e.operation=='update_config')
 assert config['verified_artifact_change_reason'].startswith('Explicit Agent strategy')

def test_repair_still_requires_observed_failure():
 s,t=initial()
 with pytest.raises(ContractError,match='REPAIR_REQUIRES_OBSERVED_FAILURE'):
  run(repair_packet(),materialized(s),t)
