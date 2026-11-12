"""Probe only newly created harmless canaries through the existing executor."""
import json
import pathlib
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
from cgkn.execution.contracts import BlockExecutionRequest, TaskContext
from cgkn.executors.local import CommandExecutor

out=pathlib.Path(sys.argv[1]).resolve()
work=out/'route-canary-workspace'
work.mkdir(exist_ok=False)
private=out/'route-canary-private.txt'
private.write_text('SYNTHETIC-NOT-A-SECRET',encoding='utf-8')
code='from pathlib import Path; print(Path('+repr(str(private))+').read_text())'
request=BlockExecutionRequest(project_id='iter076-preflight',run_id='route-canary',attempt_id='1',node_id='canary',component_ref='canary@1',executor_ref='local.command@1',task_context=TaskContext(node_goal='Read only the evaluator-created synthetic canary',node_config={'command':[sys.executable,'-c',code]}))
result=CommandExecutor(work).execute(request)
doc={'request':request.as_dict(),'result':result.as_dict(),'isolation_status':'FAIL' if 'SYNTHETIC-NOT-A-SECRET' in str(result.outputs) else 'UNVERIFIED','scope':'existing CommandExecutor; no real private data accessed; not a model run'}
(out/'route-canary.json').write_text(json.dumps(doc,indent=2),encoding='utf-8')
print(json.dumps(doc))
