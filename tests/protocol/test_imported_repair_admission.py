import pytest
from cgkn.orchestration import CapabilityTree
from cgkn.protocol.compiler import TableSnapshot
from cgkn.protocol.normalization import ContractError
from tests.protocol.test_repair_path import snapshot,packet,run,initial,plain
from tests.protocol.test_materialized_write_admission import materialized

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def failed(s,**changes):
 d=materialized(s).document
 d['repair_context']={'failures':[{'acceptance_id':'G','failure_domain':'business','artifact_paths':['module.py'],'evidence_refs':[{'path':'observations/failure.json','sha256':'a'*64}],**changes}]}
 return TableSnapshot(d)

def test_imported_artifact_first_repair_requires_real_failure_and_preserves_public_contract():
 s=failed(snapshot());result=run({**packet(),'task_kind':3},s,CapabilityTree('goal',()))
 config=plain(result['edits'][0].payload['config'])
 assert config['imported_artifact_repair_evidence']==s.document['repair_context']['failures']
 assert config['verified_artifact_change_reason'].startswith('Explicit evidence-bound initial repair')
 assert config['public_contracts']['entries'][0]['definition']==s.document['public_contract_registry']['entries'][0]['definition']

@pytest.mark.parametrize('changes',[{'failure_domain':'harness'},{'failure_domain':'transport'},{'evidence_refs':[]},{'acceptance_id':''},{'artifact_paths':['other.py']}])
def test_unqualified_failure_cannot_authorize_import_repair(changes):
 with pytest.raises(ContractError,match='MATERIALIZED_SCOPE_REQUIRES_EXPLICIT_CHANGE'):
  run({**packet(),'task_kind':3},failed(snapshot(),**changes),CapabilityTree('goal',()))

def test_existing_canonical_writer_cannot_be_bypassed_even_with_incomplete_table_metadata():
 s,tree=initial()
 with pytest.raises(ContractError,match='MATERIALIZED_SCOPE_REQUIRES_EXPLICIT_CHANGE'):
  run({**packet(),'task_kind':3,'target':1},failed(s),tree)

def test_import_failure_does_not_authorize_plain_implementation():
 with pytest.raises(ContractError,match='MATERIALIZED_SCOPE_REQUIRES_EXPLICIT_CHANGE'):
  run(packet(),failed(snapshot()),CapabilityTree('goal',()))

def test_partial_failure_coverage_does_not_authorize_other_existing_file():
 s=failed(snapshot());d=s.document;d['artifact_readiness'].append({'path':'tests.py','materialized':True})
 with pytest.raises(ContractError,match='MATERIALIZED_SCOPE_REQUIRES_EXPLICIT_CHANGE'):
  run({**packet(),'task_kind':3,'scope':[0,1]},TableSnapshot(d),CapabilityTree('goal',()))
