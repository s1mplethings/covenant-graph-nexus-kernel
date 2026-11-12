"""Freeze generated tests and sources; diagnostic only, no acceptance writes."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

R=Path(r'F:\CGKN-ITER-132\production-core-convergence-v1\promotion\run-05')
S=R/'state/iter132-promotion-studio/promotion-05'
H=Path(__file__).parent
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
tag,label=sys.argv[1:3]
selection=sys.argv[3] if len(sys.argv)==4 else None
assert len(sys.argv) in (3,4)
assert tag in {'M'+str(i) for i in range(1,13)}
assert label and set(label)<=set('abcdefghijklmnopqrstuvwxyz0123456789-')
goal=next(g for g in read(S/'goal_acceptance.json')['plans'][-1]['goals'] if g['requirement_refs']==[tag])
test=goal['milestone_contract']['compilation']['artifact_layout']['test']
tree={n['id']:n for n in read(S/'capability_tree.json')['nodes']}
for node,state in read(S/'run_state.json')['nodes'].items():
    if state['status']=='RUNNING':
        assert tree[node]['config']['leaf_contract']['task_kind'] not in {'IMPLEMENTATION','REPAIR','INTEGRATION','DELIVERY'}, 'Wait for active source writer'
out=H/label;out.mkdir(exist_ok=False);snapshot=out/'snapshot';snapshot.mkdir()
identities={}
for p in (R/'candidate').rglob('*'):
    if not p.is_file():continue
    rel=p.relative_to(R/'candidate')
    if set(rel.parts)&{'__pycache__','.pytest_cache','.cgnk_test_env'}:continue
    identities[rel.as_posix()]=sha(p)
    target=snapshot/rel;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(p,target);assert sha(target)==identities[rel.as_posix()]
assert all(sha(R/'candidate'/rel)==value for rel,value in identities.items())
config=out/'pytest.ini';config.write_text('[pytest]\n',encoding='utf8')
scratch=H/'scratch';scratch.mkdir(exist_ok=True)
system_temp=scratch/(label+'-system-temp');system_temp.mkdir(exist_ok=False)
argv=[sys.executable,'-I','-X','utf8','-m','pytest',test,'-q','-p','no:cacheprovider',
      '-c',str(config),'--rootdir',str(snapshot),'-o','pythonpath='+snapshot.as_posix(),
      '--basetemp='+str(scratch/label),'--junitxml='+str(out/'junit.xml')]
if selection: argv.extend(['-k',selection])
start=time.monotonic()
with (out/'output.log').open('wb') as log:
    result=subprocess.run(argv,cwd=snapshot,stdout=log,stderr=subprocess.STDOUT,timeout=180,
                          env={**os.environ,'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1',
                               'TEMP':str(system_temp),'TMP':str(system_temp)})
cases=list(ET.parse(out/'junit.xml').iter('testcase')) if (out/'junit.xml').exists() else []
receipt={'kind':'FrozenGeneratedTestsDiagnostic','milestone':tag,'argv':argv,'exit_code':result.returncode,
         'selection':selection,'scope':'Selected local Block/Edge cases only' if selection else 'Generated milestone tests',
         'cwd':str(snapshot),'system_temp':str(system_temp),'diagnostic_script_sha256':sha(Path(__file__)),
         'seconds':time.monotonic()-start,'collected':len(cases),
         'failures':[{'id':c.get('classname','')+'::'+c.get('name',''),'message':e.get('message','')[:1200]} for c in cases for e in c if e.tag in ('failure','error')],
         'source_identities':identities,'acceptance_authority':False,'host_business_patches':0,
         'output_sha256':sha(out/'output.log'),'junit_sha256':sha(out/'junit.xml') if (out/'junit.xml').exists() else None}
(out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in receipt.items() if k!='source_identities'}))
