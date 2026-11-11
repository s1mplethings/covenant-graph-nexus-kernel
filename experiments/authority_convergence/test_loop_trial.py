"""Same transcripts, effects, exceptions and business oracle on old/new controllers."""
import ast
import copy
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT.parent / 'execution-dedup-20261101'
sys.path.insert(0, str(ROOT / 'scripts'))
import agent_conversation_loop as conversation
import dynamic_pipeline_runner as dynamic


def old_function(module, name):
    path = OLD / 'scripts' / Path(module.__file__).name
    node = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = dict(module.__dict__)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
    return scope[name]


def candidate():
    scope = dict(conversation.__dict__)
    exec((Path(__file__).with_name('candidate_loop.py')).read_text(encoding='utf-8'), scope)
    return scope['_run_action_loop']


def normalize(value, root):
    if isinstance(value, dict):
        return {k: normalize(v, root) for k, v in value.items() if k != 'created_at'}
    if isinstance(value, list):
        return [normalize(v, root) for v in value]
    if isinstance(value, str):
        return value.replace(str(root), '<ROOT>')
    return value


def invoke(version, mode, folder, responses, limit=2, executor=None):
    session = folder / 'session.jsonl'
    project = folder / 'project'
    project.mkdir(parents=True, exist_ok=True)
    conversation.append_event(session, {'kind':'user','role':'user','text':'Build a bounded calculator; tests must prove arithmetic.'})
    calls = []
    actions = []
    class Executor:
        project_dir = project
        def execute(self, action):
            actions.append(copy.deepcopy(action))
            if executor:
                return executor(action)
            if action.get('type') == 'raise':
                raise ValueError('executor failed')
            if action.get('type') == 'package_project':
                return {'ok':True, 'manifest':{'status':'needs_review'}}
            return {'ok':not action.get('fail'), 'error':'tool failure' if action.get('fail') else '', 'type':action.get('type')}
    impl = Executor()
    def agent(events, model, timeout):
        calls.append(copy.deepcopy(events))
        response = responses[min(len(calls)-1, len(responses)-1)]
        if isinstance(response, BaseException):
            raise type(response)(str(response))
        return copy.deepcopy(response)
    manifest = {'roles':[{'id':'worker','name':'Worker'}]}
    step = {'id':'build','role':'worker','allowed_actions':['write_file','read_file','run_command','package_project','raise'], 'goal':'bounded calculator'}
    allowed = set(step['allowed_actions'])
    def prepare(action):
        if str(action.get('type') or action.get('action') or '') == 'package_project':
            audit = dynamic.pre_package_audit(session, project, manifest)
            limits = list(action.get('known_limits', []) if isinstance(action.get('known_limits'),list) else [])
            limits.extend(audit.get('known_limits',[]))
            return {**action,'known_limits':limits}
        return action
    try:
        if version == 'old':
            if mode == 'step':
                result = old_function(dynamic, '_run_agent_turn')(session_file=session,executor=impl,manifest=manifest,step=step,model='fixture',timeout=1,max_turns=limit,agent=agent)
            else:
                # Bind only the effect boundary; the original complete loop is unchanged.
                fn = old_function(conversation,'run_agent_loop')
                from types import SimpleNamespace
                fn.__globals__['local_agent_actions'] = SimpleNamespace(LocalAgentActionExecutor=lambda p:impl)
                result = fn(session_path=session,project_dir=project,model='fixture',timeout=1,max_turns=limit,agent=agent)
        else:
            kwargs = {} if mode == 'conversation' else {
                'event_context':{'role':'worker','step_id':'build'},
                'read_events':lambda:dynamic._history_for_step(session,dynamic._system_prompt(manifest['roles'][0],step,manifest)),
                'prepare_action':prepare,
            }
            result = candidate()(session_file=session,project=project,model='fixture',timeout=1,max_turns=limit,agent=agent,
                                 execute=impl.execute if mode=='conversation' else lambda a:dynamic._execute_manifest_action(impl,a,allowed),**kwargs)
    except BaseException as exc:
        result = {'raised':type(exc).__name__,'error':str(exc)}
    return normalize({'result':result,'events':conversation.read_session(session),'agent_inputs':calls,'actions':actions},folder)


TRANSCRIPTS = [
    [{'actions':[{'type':'write_file','path':'a.py','content':'x'}]}],
    [{'actions':[]}], ['not JSON'],
    [TimeoutError('provider timeout'), {'actions':[{'type':'write_file'}]}],
    [RuntimeError('UNKNOWN request; do not resubmit')],
    [KeyboardInterrupt('cancelled')],
    [{'actions':[{'type':'write_file','fail':True}]},{'actions':[{'type':'write_file'}]}],
    [{'actions':[{'type':'write_file','fail':True}]}],
    [{'actions':[{'type':'package_project'},{'type':'write_file','fail':True}]}],
    [{'actions':[{'type':'write_file','fail':True},{'type':'package_project'}]}],
    [{'actions':[{'type':'final_message','text':'done'}]}],
    [{'actions':[{'type':'unknown'}]}],
    [{'actions':[{'type':'raise'}]}],
    ['{"actions":[{"type":"write_file","path":"a.py","content":"ok"},{"type":"write_file"'],
    [{'actions':[{'action':'write_file'}],'message':'ok'}],
    [{'actions':[{'type':' write_file '}] }],
]


@pytest.mark.parametrize('mode',['conversation','step'])
@pytest.mark.parametrize('responses',TRANSCRIPTS)
def test_exact_controller_transcripts(tmp_path, monkeypatch, mode, responses):
    monkeypatch.setattr(dynamic,'pre_package_audit',lambda *a:{'known_limits':['independent acceptance required']})
    before=invoke('old',mode,tmp_path/'old',responses)
    after=invoke('new',mode,tmp_path/'new',responses)
    assert after == before


@pytest.mark.parametrize('mode',['conversation','step'])
def test_final_budget_failure_has_identical_repair_allowance(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(dynamic,'pre_package_audit',lambda *a:{})
    transcript=[{'actions':[{'type':'write_file','fail':True}]},{'actions':[{'type':'write_file'}]}]
    assert invoke('old',mode,tmp_path/'old',transcript,limit=1)==invoke('new',mode,tmp_path/'new',transcript,limit=1)


@pytest.mark.parametrize('mode',['conversation','step'])
def test_real_multifile_pytest_failure_then_repair(tmp_path, mode):
    import subprocess
    import time
    outcomes=[]
    for version in ('old','new'):
        started=time.perf_counter()
        folder=tmp_path/version;project=folder/'project'
        actual=conversation.local_agent_actions.LocalAgentActionExecutor(project)
        command=f'"{sys.executable}" -m pytest -q -p no:cacheprovider test_calc.py'
        responses=[{'actions':[
            {'type':'write_file','path':'calc.py','content':'def add(a,b): return a-b\n'},
            {'type':'write_file','path':'test_calc.py','content':'from calc import add\ndef test_add(): assert add(2,3)==5\n'},
            {'type':'run_command','command':command},
        ]},{'actions':[
            {'type':'write_file','path':'calc.py','content':'def add(a,b): return a+b\n'},
            {'type':'run_command','command':command},
        ]}]
        result=invoke(version,mode,folder,responses,executor=actual.execute)
        oracle_dir=folder/'independent-oracle';oracle_dir.mkdir()
        oracle_file=oracle_dir/'test_business.py'
        oracle_file.write_text('import pytest\nfrom calc import add\n@pytest.mark.parametrize("a,b,expected",[(2,3,5),(-2,3,1),(0,0,0),(19,-7,12)])\ndef test_business_addition(a,b,expected): assert add(a,b)==expected\n',encoding='utf-8')
        wrong=folder/'false-pass-control';wrong.mkdir()
        (wrong/'calc.py').write_text('def add(a,b): return 5\n',encoding='utf-8')
        (wrong/'test_calc.py').write_text((project/'test_calc.py').read_text(),encoding='utf-8')
        worker_false_pass=subprocess.run([sys.executable,'-m','pytest','-q','-p','no:cacheprovider','test_calc.py'],cwd=wrong,capture_output=True,timeout=30)
        def independent(workspace):
            return subprocess.run([sys.executable,'-m','pytest','-q','-p','no:cacheprovider',
                '--override-ini','pythonpath='+workspace.as_posix(),str(oracle_file)],cwd=oracle_dir,capture_output=True,timeout=30)
        rejected=independent(wrong)
        oracle=independent(project)
        tool_results=[e['result'] for e in result['events'] if e['kind']=='tool_result' and 'result' in e]
        assert any(not r['ok'] for r in tool_results)
        assert oracle.returncode==0
        assert worker_false_pass.returncode==0 and rejected.returncode==1
        assert result['result']['status'] not in ('PASS','DELIVERED','SUCCEEDED','ready')
        outcomes.append({'status':result['result']['status'],'calls':len(result['agent_inputs']),
                         'effects':[a['type'] for a in result['actions']],
                         'files':{p.name:p.read_text() for p in project.glob('*.py')},
                         'oracle_exit':oracle.returncode,'worker_false_pass_exit':worker_false_pass.returncode,
                         'independent_rejects_false_pass_exit':rejected.returncode})
        if os.environ.get('CGKN_TRIAL_EVIDENCE'):
            evidence=Path(os.environ['CGKN_TRIAL_EVIDENCE'])/'real-projects'/f'{mode}-{version}'
            evidence.mkdir(parents=True,exist_ok=True)
            for path in project.glob('*.py'):
                (evidence/path.name).write_bytes(path.read_bytes())
            (evidence/'oracle.stdout').write_bytes(oracle.stdout)
            (evidence/'oracle.stderr').write_bytes(oracle.stderr)
            (evidence/'test_business.py').write_bytes(oracle_file.read_bytes())
            (evidence/'false-pass-worker.stdout').write_bytes(worker_false_pass.stdout)
            (evidence/'false-pass-oracle.stdout').write_bytes(rejected.stdout)
            (evidence/'receipt.json').write_text(json.dumps({'result':outcomes[-1],'seconds':time.perf_counter()-started,'transcript':result},indent=2),encoding='utf-8')
    assert outcomes[0]==outcomes[1]
