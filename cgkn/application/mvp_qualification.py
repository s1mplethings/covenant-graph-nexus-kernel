"""Qualification bindings for the public arithmetic demo, outside the kernel."""
import hashlib
import json
import subprocess
import sys
from dataclasses import replace

from cgkn.execution.deliverables import FileDeliverableChecker, SubjectDeliverableChecker
from cgkn.executors import PythonTestExecutor
from cgkn.orchestration import CapabilityTree
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.state.acceptance import GoalAcceptance, identity

CONDITION = 'add returns the arithmetic sum for positive, negative and zero operands'


def leaf_contract(node, executor, dependencies=()):
    if node not in {'inspect','fix','test'}:
        raise ValueError('unknown arithmetic demo node')
    writing=node=='fix'
    return build_leaf_contract(goal=CONDITION if writing else 'Measure '+node+' for the public arithmetic demo',
        kind='IMPLEMENTATION' if writing else 'INSPECTION' if node=='inspect' else 'TEST',
        scope=['math_utils.py'] if writing else ['observations/'+node],
        acceptance=['arithmetic'] if writing else ['demo-observation'],
        checker='demo-files' if writing else 'demo-observation',output_identity='demo/'+node,
        effect_domains=['filesystem','external_network'] if executor=='llm.cheap@1' else
            ['local_process'] if executor=='local.python-test@1' else ['filesystem'],executor=executor,dependencies=dependencies,
        **({'expected_delta':'correct the arithmetic implementation'} if writing else
           {'subject':'math_utils.py','expected_observation':'source read' if node=='inspect' else CONDITION,
            'pass_fail_rule':'independent observation with current subject and raw receipt'}))


def arithmetic(root):
    # Run candidate code in a disposable process, not inside the host evaluator.
    code="import runpy,json;f=runpy.run_path('math_utils.py')['add'];print(json.dumps([f(2,3),f(-7,2),f(0,0)]))"
    completed=subprocess.run([sys.executable,'-I','-c',code],cwd=root,capture_output=True,text=True,timeout=10)
    try:values=json.loads(completed.stdout)
    except ValueError:values=None
    return {'passed':completed.returncode==0 and values==[5,-5,0],
            'observed':{'values':values,'stderr':completed.stderr,'returncode':completed.returncode},
            'artifacts':['math_utils.py']}


def install(registry,store,root,project_id,run_id):
    acceptance=GoalAcceptance(store,project_id,run_id,{'R-add':{'must':True}}, {'arithmetic':'local.python-test@1'})
    acceptance.bind_subjects({'math_utils.py':hashlib.sha256((root/'math_utils.py').read_bytes()).hexdigest()})
    acceptance.commit(acceptance.propose({'phases':[{'id':'usable','depends_on':[]}],
        'goals':[{'id':'add','phase_id':'usable','requirement_refs':['R-add'],'acceptance':CONDITION,
                  'subject_refs':['math_utils.py'],'checker':'arithmetic','task_refs':[]}]},CapabilityTree('public arithmetic demo',())))

    class CheckedTests(PythonTestExecutor):
        def execute(self,request):
            result=super().execute(request)
            if not result.succeeded:return result
            measured=arithmetic(self.root)
            subjects={'math_utils.py':hashlib.sha256((self.root/'math_utils.py').read_bytes()).hexdigest()}
            acceptance.bind_subjects(subjects)
            return replace(result,outputs={**dict(result.outputs),'goal_check':{
                'goal_id':'add','condition_hash':identity(CONDITION),'subjects':subjects,'execution':'VALID',
                'verdict':'VERIFIED' if measured['passed'] else 'FAILED','observed':measured['observed'],
                'evidence_refs':['math_utils.py','process:arithmetic-independent-measurement']}})

    registry.unregister('local.python-test@1')
    registry.register(CheckedTests(root))
    registry.register(FileDeliverableChecker(root,{'arithmetic':lambda r,c:arithmetic(r)}))
    def observation(request,c):
        out=request.as_dict()['input_values']['execution_receipt']['outputs']
        if request.node_id=='inspect':
            passed=out.get('path')=='math_utils.py' and isinstance(out.get('content'),str) and 'def add' in out['content']
        else:
            check=out.get('goal_check',{})
            passed=(check.get('condition_hash')==identity(CONDITION) and check.get('subjects')==acceptance.data['subjects']
                    and check.get('observed',{}).get('values')==[5,-5,0])
        return {'passed':passed,'observed':out,'evidence_refs':[dict(request.input_values['execution_receipt_ref'])]}
    registry.register(SubjectDeliverableChecker(lambda c:{name:identity(name) for name in c['target_scope']},
        {'demo-observation':observation}))
    return acceptance,{'demo-files':'deliverable.files@1','demo-observation':'deliverable.subjects@1'}
