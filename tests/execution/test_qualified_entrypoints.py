import json
import pathlib
import subprocess
import sys
import pytest
from cgkn.orchestration.leaf_contract import build_leaf_contract

ROOT=pathlib.Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('correct',[True,False])
def test_runtime_cli_requires_real_declared_file_predicate(tmp_path,correct):
    c=build_leaf_contract(goal='Persist the public fixture object',kind='IMPLEMENTATION',scope=['object.json'],
        acceptance=['object-value'],checker='files',output_identity='object',effect_domains=['object'],
        executor='local.file@1',expected_delta='new object value')
    tree={'goal':'persist object','run_id':'r','project_root':'workspace','nodes':[{'id':'write',
        'capability_ref':'file.write@1','config':{'executor_ref':'local.file@1','leaf_contract':c,
        'action':'write_file','path':'object.json','content':'{"value":7}'}}]}
    source=tmp_path/'tree.json';source.write_text(json.dumps(tree),encoding='utf-8')
    binding=tmp_path/'bindings.json';binding.write_text(json.dumps({'kind':'CGKNFileCheckerBindings',
        'schema_version':'1.0','checks':{'object-value':{'kind':'json_schema','path':'object.json',
        'schema':{'type':'object','required':['value'],'properties':{'value':{'const':7 if correct else 8}}}}}}),encoding='utf-8')
    args=[sys.executable,'-X','utf8',str(ROOT/'scripts/run_mvp_runtime.py'),'--project-id','p',
        '--tree',str(source),'--run-root',str(tmp_path/'runs'),'--executor-config',str(binding),'--json']
    result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert result.returncode==(0 if correct else 1),result.stderr
    receipt=json.loads((tmp_path/'runs/p/r/node_results/write.json').read_text(encoding='utf-8'))
    assert receipt['metadata']['execution_status']=='EXECUTION_SUCCESS'
    assert receipt['metadata']['deliverable_verdict']==('VERIFIED' if correct else 'FAILED')
    assert receipt['metadata']['goal_acceptance']=='NOT_EVALUATED'


def test_self_growth_cli_checks_parsed_object_and_reuses_capability(tmp_path):
    result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_self_growth_v0.py'),
        '--run-root',str(tmp_path/'growth'),'--json'],cwd=ROOT,capture_output=True,text=True,timeout=35)
    assert result.returncode==0,result.stdout+result.stderr
    report=json.loads(result.stdout)
    assert report['status']=='PASS' and report['second_run_reused_registry']
    assert report['provider_calls']==0 and report['kernel_files_modified_by_growth']==0
    for run in ('growth-run-1','growth-run-2'):
        receipt=json.loads((tmp_path/'growth/runs/growth-project'/run/'node_results/parse.json').read_text(encoding='utf-8'))
        assert receipt['metadata']['deliverable_verdict']=='VERIFIED'
        assert receipt['outputs']['object']=={'answer':42}
