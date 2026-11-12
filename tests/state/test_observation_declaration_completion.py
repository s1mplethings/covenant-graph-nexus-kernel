from copy import deepcopy
from types import SimpleNamespace
import pytest
from cgkn.state.acceptance import GoalAcceptance

def fixture():
    owner={'id':'owner','phase_id':'p','requirement_refs':['R'],'acceptance':'Full original predicate',
           'checker':'check','subject_refs':['app.py'],'milestone_contract':{'design':{'artifacts':[{'path':'app.py'}]},'registry':{'exact':'unchanged'}}}
    observation={**owner,'id':'observe','acceptance':'Additional scoped observation','milestone_contract':{'scope':'Observe existing port'}}
    obj=object.__new__(GoalAcceptance);obj.requirements={'R':{}};obj.checkers={'check':'registered'}
    obj.data={'plans':[{'phases':[{'id':'p'}],'goals':[owner,observation]}],'subjects':{'app.py':'hash'}}
    plan=deepcopy(obj.data['plans'][-1]);plan['goals'][1]['milestone_contract']={**owner['milestone_contract'],**observation['milestone_contract']}
    return obj,plan,SimpleNamespace(by_id={})

def test_completion_is_additive_and_preserves_history():
    obj,plan,tree=fixture();before=deepcopy(obj.data)
    assert obj.propose(plan,tree)==plan
    assert obj.data==before

@pytest.mark.parametrize('field,value',[('acceptance','weaker'),('subject_refs',[]),('checker','producer'),('requirement_refs',[])])
def test_completion_never_changes_predicate_bindings(field,value):
    obj,plan,tree=fixture();plan['goals'][1][field]=value
    with pytest.raises(ValueError,match='weakened'):obj.propose(plan,tree)

@pytest.mark.parametrize('mutation',['scope','design','owner'])
def test_completion_rejects_semantic_and_layout_changes(mutation):
    obj,plan,tree=fixture()
    if mutation=='scope':plan['goals'][1]['milestone_contract']['scope']='different'
    if mutation=='design':plan['goals'][1]['milestone_contract']['design']['artifacts'].append({'path':'foreign.py'})
    if mutation=='owner':plan['goals'][0]['milestone_contract']['registry']={'different':True}
    with pytest.raises(ValueError,match='weakened'):obj.propose(plan,tree)
