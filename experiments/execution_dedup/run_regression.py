"""Full offline regression with preserved exit status and credential redaction."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/substrate-replacement-v2'


def main():
    guard=OUT/'offline_guard';guard.mkdir(exist_ok=True)
    (guard/'sitecustomize.py').write_text('''import sys, os, json, ipaddress
from pathlib import Path
def guard(event,args):
    if event!='socket.connect':return
    address=args[1]
    if not isinstance(address,tuple):return
    host=address[0]
    try: allowed=ipaddress.ip_address(host).is_loopback
    except ValueError:allowed=host=='localhost'
    if not allowed:
        with (Path(os.environ['CGKN_OFFLINE_GUARD_LOG'])/('blocked-'+str(os.getpid())+'.jsonl')).open('a') as out:
            out.write(json.dumps({'host':host,'port':address[1]})+'\\n')
        raise OSError('OFFLINE_NETWORK_DENIED')
sys.addaudithook(guard)
''',encoding='utf-8')
    env=dict(os.environ,PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',CGKN_PYTEST_PROGRESS='0',
             CGKN_APPLICATION_PROFILE=str(OUT/'offline-profile.json'),
             CGKN_OFFLINE_GUARD_LOG=str(guard),PYTHONPATH=str(guard)+os.pathsep+str(ROOT))
    command=[sys.executable,'-m','pytest','-q','--junitxml='+str(OUT/'regression.xml')]
    start=time.time()
    with (OUT/'regression.log').open('w',encoding='utf-8') as output:
        proc=subprocess.Popen(command,cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT)
        (OUT/'regression-start.json').write_text(json.dumps({'started_epoch':start,'pid':proc.pid,'command':command,'profile':'explicit isolated legacy default; individual domestic fixtures retain their own mocks; external socket connects denied'},indent=2))
        code=proc.wait()
    (OUT/'regression-completion.json').write_text(json.dumps({'exit_code':code,'seconds':time.time()-start,'postprocessing':'pending'},indent=2))
    secrets=set();xml=OUT/'regression.xml'
    if xml.exists():
        for case in ET.parse(xml).findall('.//testcase'):
            if any(s in case.get('classname','') for s in ('test_provider_credentials','test_qwen_provider_alignment')):
                for n in list(case):secrets.update(re.findall(r'\+\s+([A-Za-z0-9_-]{24,})',n.get('message','')+(n.text or '')))
    receipts=[]
    for p in (xml,OUT/'regression.log'):
        if not p.exists():continue
        before=p.read_bytes();text=before.decode('utf-8', errors='replace')
        for secret in secrets:text=text.replace(secret,'[REDACTED_CREDENTIAL_ASSERTION]')
        p.write_text(text,encoding='utf-8')
        receipts.append({'file':p.name,'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    (OUT/'regression-completion.json').write_text(json.dumps({'exit_code':code,'seconds':time.time()-start,'redacted_values':len(secrets),'files':receipts},indent=2))
    print(json.dumps({'exit_code':code,'seconds':time.time()-start}))
    return code


if __name__=='__main__':raise SystemExit(main())
