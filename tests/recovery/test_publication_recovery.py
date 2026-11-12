"""Real controller death around publication, never automatic worker replay."""
import json
import pathlib
import subprocess
import sys
import pytest
from cgkn.executors import ExecutorRegistry
from cgkn.executors.llm import LLMExecutor
from cgkn.providers import ModelRoleConfig
from cgkn.execution.deliverables import FileDeliverableChecker
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from tests.runtime.test_execution_continuity import Client,node,write,works,run


CHILD=r'''
import os,sys,pathlib
from tests.runtime.test_execution_continuity import setup,Client,node,write,run
base=pathlib.Path(sys.argv[1]);mode=sys.argv[2]
root,store,runner=setup(base,Client([write('a.py'),write('b.py')]))
if mode=='before':
 original=store.immutable_json
 def save(path,value):
  original(path,value)
  if path.parent.parent.name=='publication_intents':os._exit(71)
 store.immutable_json=save
elif mode=='after':
 original=store.save_result
 def save(result):
  if result.succeeded:os._exit(72)
  return original(result)
 store.save_result=save
else:
 original=pathlib.Path.replace
 def publish(path,target):
  if pathlib.Path(target)==root/'b.py':os._exit(73)
  return original(path,target)
 pathlib.Path.replace=publish
run(runner,[node(files=('a.py','b.py'))])
'''


@pytest.mark.parametrize('mode,exitcode,expected',[('before',71,'NOT_APPLIED'),('after',72,'COMPLETED'),('mixed',73,'UNKNOWN')])
def test_real_process_death_publication_reconciled_without_replay(tmp_path,mode,exitcode,expected):
    completed=subprocess.run([sys.executable,'-X','utf8','-c',CHILD,str(tmp_path),mode],capture_output=True,text=True,timeout=25)
    assert completed.returncode==exitcode,completed.stderr
    client=Client([write('a.py'),write('b.py')]);store=FileRunStore(tmp_path/'state');registry=ExecutorRegistry()
    registry.register(LLMExecutor(tmp_path/'project',client,ModelRoleConfig('worker','fake')))
    registry.register(FileDeliverableChecker(tmp_path/'project',{'works':works}))
    runner=DAGRunner(registry,store,deliverable_checkers={'check':'deliverable.files@1'})
    before={p.name:p.read_bytes() for p in (tmp_path/'project').glob('*.py')}
    summary=run(runner,[node(files=('a.py','b.py'))],resume=True)
    receipt=store.load_result('p','r','n')
    assert receipt.metadata['publication_recovery']['disposition']==expected
    assert not client.calls
    assert before=={p.name:p.read_bytes() for p in (tmp_path/'project').glob('*.py')}
    assert (summary.status=='SUCCEEDED') is (expected=='COMPLETED')
    if expected=='UNKNOWN':assert receipt.error.details['outcome_unknown']
    if expected=='NOT_APPLIED':assert receipt.error.details['outcome_unknown'] is False
    if expected=='COMPLETED':
        assert receipt.metadata['deliverable_verdict']=='VERIFIED'
        assert not run(runner,[node(files=('a.py','b.py'))],resume=True).actual_executions
