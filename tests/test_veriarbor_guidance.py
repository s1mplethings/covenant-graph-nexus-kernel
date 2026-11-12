from copy import deepcopy
import pytest
from cgkn.adapters.veriarbor.guidance_adapter import project_continuation
from cgkn.protocol.context_pack import failure_context


def fixture():
    guidance={'milestone_completion_request':'Complete all product requirements',
              'cost_policy':'cheap only', 'fresh_runtime_diagnosis':{
                  'applicability':{'artifact_hashes':{'module.py':'a'},'goal_receipts':{'g':None}},
                  'next_step':'Measure current materialized artifact once'}}
    state={'subject_identities':{'module.py':'a'},'goals':[{'id':'g','evidence':None,'acceptance':'works','requirement_refs':['R']}],
           'obligations':{},'complete':False}
    return guidance,state


def test_exact_binding_retains_guidance_without_mutating_history():
    g,s=fixture();before=deepcopy(g);out=project_continuation(g,s)
    assert out['fresh_runtime_diagnosis']['status']=='GUIDANCE_APPLICABLE'
    assert out['fresh_runtime_diagnosis']['next_step']==g['fresh_runtime_diagnosis']['next_step']
    assert g==before


@pytest.mark.parametrize('delta',['artifact','observation','missing_goal','malformed'])
def test_new_state_retires_only_bounded_guidance(delta):
    g,s=fixture()
    if delta=='artifact':s['subject_identities']['module.py']='b'
    elif delta=='observation':s['goals'][0]['evidence']={'receipt_hash':'new-failure'}
    elif delta=='missing_goal':s['goals']=[]
    else:g['fresh_runtime_diagnosis']['applicability']='invalid'
    before=deepcopy(g);out=project_continuation(g,s)
    assert out['fresh_runtime_diagnosis']['status']=='GUIDANCE_NOT_APPLICABLE'
    assert 'next_step' not in out['fresh_runtime_diagnosis']
    assert out['milestone_completion_request']==g['milestone_completion_request']
    assert out['cost_policy']==g['cost_policy'] and g==before


def test_legacy_unbound_guidance_is_not_silently_dropped():
    g,s=fixture();del g['fresh_runtime_diagnosis']['applicability']
    assert project_continuation(g,s)==g


def test_real_context_projection_retires_step_after_new_receipt():
    g,s=fixture();s['goals'][0]['evidence']={'receipt_hash':'measured'}
    source={'goal':'finish','goal_acceptance':s,'failure_details':{'continuation_requirements':g}}
    pack=failure_context(source,evidence_ref={'path':'raw.json','sha256':'x'})
    assert pack['continuation_requirements']['fresh_runtime_diagnosis']['status']=='GUIDANCE_NOT_APPLICABLE'
    assert 'Measure current' not in str(pack['continuation_requirements'])
    assert source['failure_details']['continuation_requirements']==g
