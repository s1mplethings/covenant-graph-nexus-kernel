import json
from dataclasses import asdict

import pytest

from cgkn.agent.planning_scope import assemble_execution_authorities
from cgkn.agent.project_agent import AdmissionPolicy
from cgkn.runtime.node_authority import ExecutionAuthority
from cgkn.state import FileRunStore
from tests.session_authority_support import authorization


@pytest.mark.boundary
@pytest.mark.happy_path
def test_json_authorization_roundtrip_and_immutable_resume(tmp_path):
    store=FileRunStore(tmp_path)
    raw=authorization('p',('observe@1',),'observe current object')
    policy,planning=assemble_execution_authorities('p','r',store,raw)
    path=store.run_dir('p','r')/'execution_authorization.json'
    original=path.read_bytes()
    restored=json.loads(json.dumps(raw))
    policy2,planning2=assemble_execution_authorities('p','r',store,restored)
    assert policy.as_dict()==policy2.as_dict()
    assert policy.allowed_effect_domains==frozenset(raw['admission_policy']['allowed_effect_domains'])
    assert planning.contract.fingerprint==planning2.contract.fingerprint
    assert path.read_bytes()==original
    restored['admission_policy']['execution_budget']['calls']+=1
    with pytest.raises(ValueError,match='conflicting immutable record'):
        assemble_execution_authorities('p','r',store,restored)
    assert path.read_bytes()==original
    assert ExecutionAuthority(store,'p','r').events()==[]


@pytest.mark.parametrize('bad',[None,{}, {'admission_policy':{}}, 'old-business-budget'])
def test_missing_authorization_cannot_create_permit(tmp_path,bad):
    store=FileRunStore(tmp_path)
    with pytest.raises(ValueError,match='EXPLICIT_EXECUTION_AUTHORIZATION_REQUIRED'):
        assemble_execution_authorities('p','r',store,bad)
    assert ExecutionAuthority(store,'p','r').events()==[]


@pytest.mark.parametrize('domains',['filesystem',[1],[''],None])
def test_malformed_effect_domain_scope_is_rejected(domains):
    with pytest.raises(ValueError,match='allowed_effect_domains'):
        AdmissionPolicy(allowed_effect_domains=domains)


@pytest.mark.boundary
@pytest.mark.negative
def test_other_project_authorization_is_not_inherited(tmp_path):
    store=FileRunStore(tmp_path)
    with pytest.raises(ValueError,match='PROJECT_SCOPE_REJECT'):
        assemble_execution_authorities('p','r',store,authorization('other',('observe@1',),'g'))
    assert ExecutionAuthority(store,'p','r').events()==[]
