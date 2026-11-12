"""Compact read-only observations; never substitutes for authenticated acceptance."""
import json
import time
from pathlib import Path

R=Path(r'F:\CGKN-ITER-132\production-core-convergence-v1\promotion\run-05')
S=R/'state/iter132-promotion-studio/promotion-05'
def read(p):return json.loads(p.read_text(encoding='utf8'))
start=max((R/'continuations').glob('veriarbor-*/started.json'), key=lambda p:p.stat().st_mtime)
request=max((S/'provider_calls').glob('*/request.json'),key=lambda p:p.stat().st_mtime)
data=read(request); response=request.with_name('response.json'); error=request.with_name('error.json')
provider={'id':request.parent.name,'role':data['config']['role'],
    'execution_identity':data.get('execution_identity'),
    'in_current_continuation':request.stat().st_mtime>=start.stat().st_mtime,
    'age_seconds':round(time.time()-request.stat().st_mtime),
    'status':'COMPLETE' if response.exists() else 'ERROR' if error.exists() else 'IN_FLIGHT'}
if error.exists():provider['error']={k:v for k,v in read(error).items() if k in ('category','outcome_unknown')}
if response.exists():provider['response_prefix']=read(response).get('text','')[:500]
check=read(S/'goal_acceptance.json')['checks'][-1]
nodes=read(S/'run_state.json')['nodes']
result={'continuation':start.parent.name,'controller_result_exists':(start.parent/'result.json').exists(),
    'controller_error_exists':(start.parent/'execution-error.json').exists(),
    'provider':provider,'latest_raw_check':{'node':check['node_id'],'observed':check['observation']['observed']},
    'last_nodes':[(n,nodes[n]['status']) for n in sorted(nodes)[-5:]],
    'running_nodes':[n for n in nodes if nodes[n]['status']=='RUNNING']}
print(json.dumps(result,ensure_ascii=False))
