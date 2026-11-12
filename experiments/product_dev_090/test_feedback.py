import json
from pathlib import Path
from cgkn.executors.llm import LLMExecutor
from cgkn.execution import BlockExecutionRequest,TaskContext
from cgkn.providers import ModelRoleConfig,ProviderCompletion

def test_worker_read_only_completion_keeps_observations(tmp_path):
 (tmp_path/'probe.txt').write_text('RAW PROBE')
 class Client:
  def __init__(self):self.n=0
  def complete(self,**kw):
   self.n+=1
   if self.n==2:assert 'RAW PROBE' in kw['user']
   value=dict(schema_version='1.0',node_id='probe',summary='read complete',actions=[{'action':'read_file','path':'probe.txt'}] if self.n==1 else [],expected_outputs=[],confidence=1,needs_escalation=False,escalation_reason='')
   return ProviderCompletion(json.dumps(value),'stub','test',{})
 worker=LLMExecutor(tmp_path,Client(),ModelRoleConfig('worker','stub'),max_rounds=80)
 req=BlockExecutionRequest(project_id='p',run_id='r',attempt_id='a',node_id='probe',component_ref='code@1',executor_ref='llm.cheap@1',task_context=TaskContext(node_goal='Read synthetic text'))
 result=worker.execute(req)
 assert result.outputs['action_results'][0]['content']=='RAW PROBE'
 assert not result.outputs['modified_files']

