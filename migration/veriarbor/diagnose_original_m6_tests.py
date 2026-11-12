"""Run unchanged historical M6 assertions against frozen current source only."""
from pathlib import Path
import json,hashlib,shutil,subprocess,sys,os,time,xml.etree.ElementTree as ET
M=Path(__file__).parent
prior=M/'m11-generated-tests-e4737c44/snapshot/tests/test_milestone_33270fed0c9054f5ae04.py'
current=M/'m6-generated-tests-db223502/snapshot'
out=M/'m6-original-tests-db223502';out.mkdir(exist_ok=False)
snapshot=out/'snapshot';shutil.copytree(current,snapshot,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache'))
target=snapshot/'tests/test_milestone_33270fed0c9054f5ae04.py';target.write_bytes(prior.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(target)==sha(prior)=='20df669dcf4fbf7b30cbd249f991f75d9889321e427818ce2f86649abfd0d311'
config=out/'pytest.ini';config.write_text('[pytest]\n')
temp=M/'scratch/m6-original-tests-db223502-system-temp';temp.mkdir(exist_ok=False)
argv=[sys.executable,'-I','-X','utf8','-m','pytest',str(target),'-q','-p','no:cacheprovider','-c',str(config),'--rootdir',str(snapshot),'-o','pythonpath='+snapshot.as_posix(),'--basetemp='+str(M/'scratch/m6-original-tests-db223502'),'--junitxml='+str(out/'junit.xml')]
start=time.monotonic()
with (out/'output.log').open('wb') as log:
 result=subprocess.run(argv,cwd=snapshot,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'TEMP':str(temp),'TMP':str(temp),'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'})
cases=ET.parse(out/'junit.xml').getroot().findall('.//testcase')
receipt={'kind':'HistoricalAssertionsOnCurrentSourceDiagnostic','argv':argv,'cwd':str(snapshot),'exit_code':result.returncode,
 'source_snapshot_ref':str(M/'m6-generated-tests-db223502/receipt.json'),
 'original_test_ref':str(prior),'original_test_sha256':sha(prior),
 'tests':len(cases),'failed':sum(c.find('failure') is not None or c.find('error') is not None for c in cases),
 'skipped':sum(c.find('skipped') is not None for c in cases),'seconds':time.monotonic()-start,
 'coverage_delta':'Current regenerated suite omitted original distinct STALE rejection assertion; original unchanged suite retained and run here. Restore coverage through original Provider-owned test task before final delivery.',
 'acceptance_authority':False,'candidate_modified':False,'host_business_patches':0}
(out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(json.dumps(receipt))
