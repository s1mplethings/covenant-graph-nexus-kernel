from types import SimpleNamespace
import pytest
from cgkn.agent.project_loop import ProjectSession

class Acceptance:
    def __init__(self): self.data={'subjects':{}}
    def _reload(self): pass
    def bind_subjects(self,value): self.data['subjects']=value

def plans(subject='app.py',requirement='R1'):
    return {'goals':[
        {'id':'implementation','requirement_refs':['R1'],'subject_refs':['app.py','dep.py'],
         'milestone_contract':{'design':{'artifacts':[{'path':'app.py'}]},'dependency_artifacts':['dep.py']}},
        {'id':'dependency','requirement_refs':['R0'],'subject_refs':['dep.py'],
         'milestone_contract':{'design':{'artifacts':[{'path':'dep.py'}]}}},
        {'id':'observation','requirement_refs':[requirement],'subject_refs':[subject],
         'milestone_contract':{'scope':'Read-only observation of existing compiled boundary'}}]}

def session():
    return SimpleNamespace(acceptance=Acceptance(),subject_snapshot=lambda paths:{p:'hash:'+p for p in paths})

def test_additive_observation_reuses_compiled_artifacts_and_dependency():
    for path in ('app.py','dep.py'):
        s=session();ProjectSession._refresh_milestone_subjects(s,plans(path))
        assert s.acceptance.data['subjects']=={'app.py':'hash:app.py','dep.py':'hash:dep.py'}

@pytest.mark.parametrize('path,requirement',[('unregistered.py','R1'),('app.py','R0'),('../secret','R1')])
def test_observation_cannot_escape_compiled_scope(path,requirement):
    with pytest.raises(ValueError,match='observation must bind'):
        ProjectSession._refresh_milestone_subjects(session(),plans(path,requirement))

def test_existing_implementation_contract_still_rejects_unknown_subject():
    p=plans();p['goals'][0]['subject_refs'].append('unregistered.py')
    with pytest.raises(ValueError,match='milestone subject'):
        ProjectSession._refresh_milestone_subjects(session(),p)

def test_observation_cannot_add_uncompiled_dependency():
    p=plans();p['goals'][2]['milestone_contract']['dependency_artifacts']=['unregistered.py']
    with pytest.raises(ValueError,match='milestone dependency'):
        ProjectSession._refresh_milestone_subjects(session(),p)
