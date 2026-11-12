"""Frozen read-only diagnostics with the unchanged qualified consumer."""
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

R=Path(r'F:\CGKN-ITER-132\production-core-convergence-v1\promotion\run-05')
S=R/'state/iter132-promotion-studio/promotion-05'
H=Path(__file__).parent
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
tag=sys.argv[1]
assert tag in {'M'+str(i) for i in range(1,13)}
assert len(sys.argv) in (2,3)
suffix=sys.argv[2] if len(sys.argv)==3 else ''
assert not suffix or set(suffix)<=set('abcdefghijklmnopqrstuvwxyz0123456789-')
goal=next(g for g in read(S/'goal_acceptance.json')['plans'][-1]['goals'] if g['requirement_refs']==[tag])
layout=goal['milestone_contract']['compilation']['artifact_layout']
excluded=layout['test'];source=R/'candidate';identity=sha(source/layout['source'])
tree={n['id']:n for n in read(S/'capability_tree.json')['nodes']}
for key,value in read(S/'run_state.json')['nodes'].items():
    if value['status']!='RUNNING':continue
    leaf=tree[key]['config']['leaf_contract']
    if leaf['task_kind'] in {'IMPLEMENTATION','REPAIR','INTEGRATION','DELIVERY'}:
        assert set(leaf['target_scope']) <= {excluded}, 'Cannot snapshot an active source writer'
out=H/(tag.lower()+'-diagnostic-'+identity[:8]+('-'+suffix if suffix else ''));out.mkdir(exist_ok=False)
snapshot=out/'snapshot';snapshot.mkdir();identities={}
for path in source.rglob('*'):
    if not path.is_file():continue
    relative=path.relative_to(source)
    if set(relative.parts)&{'__pycache__','.pytest_cache','.cgnk_test_env'} or relative.as_posix()==excluded:continue
    identities[relative.as_posix()]=sha(path)
    target=snapshot/relative;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(path,target);assert sha(target)==identities[relative.as_posix()]
assert all(sha(source/name)==value for name,value in identities.items())
checker=R/'consumer-revisions/gui-locators-v3.py'
assert sha(checker)=='5201a3c5aa6c9e829890787e3a5d6b8f60d3de104b301fb9df5eeb28faeb1007'
request=out/'request.json'
request.write_text(json.dumps({'workspace':str(snapshot),'requirements':{tag:{}}}),encoding='utf8')
argv=[sys.executable,'-X','utf8',str(checker),'--request',str(request)]
start=time.monotonic()
with (out/'output.log').open('wb') as log:
    result=subprocess.run(argv,cwd=snapshot,stdout=log,stderr=subprocess.STDOUT,timeout=180)
receipt={'kind':'FrozenMilestoneDiagnostic','milestone':tag,'argv':argv,'exit_code':result.returncode,
    'cwd':str(snapshot),'diagnostic_script_sha256':sha(Path(__file__)),
    'seconds':time.monotonic()-start,'source_identities':identities,
    'excluded_active_writer_scope':excluded,'acceptance_authority':False,
    'host_business_patches':0,'output_sha256':sha(out/'output.log')}
(out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
print(out)
print((out/'output.log').read_text(encoding='utf8'))
