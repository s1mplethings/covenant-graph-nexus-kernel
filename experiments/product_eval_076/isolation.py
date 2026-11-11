"""ITER-076 v2: trusted control plane, untrusted payloads inside one container.

No host execution fallback. All model tools, including file and browser tools,
are subprocesses of the same container. The Docker CLI is never a model tool.
"""
from __future__ import annotations
import hashlib
import json
import pathlib
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone

VERSION='iter076-isolation-v2'
def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

@dataclass(frozen=True)
class Policy:
    image: str
    network: str='none'
    memory: str='1536m'
    cpus: str='2'
    user: str='65534:65534'
    def __post_init__(self):
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',self.image):raise ValueError('Immutable local image ID required')
        if (self.network,self.memory,self.cpus,self.user)!=('none','1536m','2','65534:65534'):raise ValueError('Unvalidated policy')

PAYLOAD='''import json,sys,subprocess,os
p=json.load(sys.stdin)
r=subprocess.run(p['argv'],cwd='/workspace',input=p.get('stdin',''),text=True)
raise SystemExit(r.returncode)
'''
FILE_TOOL='''import json,pathlib,sys
p=json.load(sys.stdin);a=p['action'];f=pathlib.Path(p.get('path','.'))
if a=='read_file':r={'action':a,'path':str(f),'content':f.read_text()}
elif a=='list_files':r={'action':a,'files':sorted(str(x) for x in f.rglob('*') if x.is_file())}
elif a=='write_file':
 f.parent.mkdir(parents=True,exist_ok=True);r={'action':a,'path':str(f),'bytes':f.write_text(p['content'])}
elif a=='patch_file':
 s=f.read_text();assert p['find'] and s.count(p['find'])==1,'patch find text must occur exactly once';f.write_text(s.replace(p['find'],p['replace'],1));r={'action':a,'path':str(f)}
else:raise ValueError('Unknown file action')
print(json.dumps(r))
'''

class ContainerBoundary:
    def __init__(self,root:pathlib.Path,run_id:str,route:str,policy:Policy):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,55}',run_id):raise ValueError('Invalid control-plane run ID')
        if route not in ('R_DIRECT','R_CGNK'):raise ValueError('Invalid route')
        self.root=root.resolve();self.run_id=run_id;self.route=route;self.policy=policy
        self.name='eval076-'+run_id
        self.root.mkdir(parents=True,exist_ok=False)
        self.work=self.root/'workspace';self.work.mkdir()
        self.public=self.root/'public';self.public.mkdir()
        self.chain='0'*64;self.active=False
        self.audit_path=self.root/'audit.jsonl'
        self.record('policy',{'policy':policy.__dict__,'version':VERSION,'source_sha':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),'registered_tools':['command','read_file','list_files','write_file','patch_file','browser'],'external_network':'disabled; frozen dependencies only','unregistered':['host_shell','host_browser','MCP','personal_connectors','Docker_control']})
    def record(self,kind,data):
        row={'at':datetime.now(timezone.utc).isoformat(),'run_id':self.run_id,'route':self.route,'backend':self.name,'version':VERSION,'policy_hash':digest(self.policy.__dict__),'previous':self.chain,'kind':kind,'data':data}
        self.chain=digest(row);row['hash']=self.chain
        with self.audit_path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    def control(self,args,timeout=30):
        p=subprocess.run(['docker',*args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,shell=False)
        self.record('control',{'argv':['docker',*args],'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        if p.returncode:raise RuntimeError('ISOLATION_BACKEND_FAILED: '+p.stderr[:1000])
        return p.stdout
    def start(self):
        self.control(['image','inspect',self.policy.image,'--format','{{.Id}}'])
        self.control(['run','-d','--name',self.name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user',self.policy.user,'--pids-limit','256','--memory',self.policy.memory,'--cpus',self.policy.cpus,'--init','--tmpfs','/tmp:rw,nosuid,nodev,size=536870912','--mount',f'type=bind,source={self.public},target=/input,readonly','--mount',f'type=bind,source={self.work},target=/workspace',self.policy.image])
        self.active=True
        doc=json.loads(self.control(['inspect',self.name]))[0]
        mounts={(m['Destination'],bool(m['RW'])) for m in doc['Mounts']}
        if mounts!={('/input',False),('/workspace',True)} or doc['HostConfig']['NetworkMode']!='none' or doc['Image']!=self.policy.image:
            self.close();raise RuntimeError('ISOLATION_POLICY_MISMATCH')
        self.record('binding_verified',{'container_id':doc['Id'],'image':doc['Image'],'mounts':doc['Mounts'],'host_config':doc['HostConfig']})
    def execute(self,action:dict,timeout=30):
        started=time.monotonic()
        original_action=action
        if not self.active:
            result={'exit_code':None,'stdout':'','stderr':'ISOLATION_BACKEND_UNAVAILABLE','status':'BLOCKED_ENV'}
            self.record('tool',{'action':action,'result':result});return result
        try:
            if not isinstance(action,dict):raise ValueError('action must be object')
            action=dict(action)
            timeout=action.pop('timeout_seconds',timeout)
            kind=action.get('action')
            if kind=='command':
                if set(action)-{'action','argv','stdin'}:raise ValueError('Unknown command parameter')
                argv=action['argv'];stdin=action.get('stdin','')
                if not isinstance(argv,list) or not argv or not all(isinstance(s,str) and '\x00' not in s for s in argv):raise ValueError('argv must be strings')
            elif kind in {'read_file','list_files','write_file','patch_file'}:
                if set(action)-{'action','path','content','find','replace'}:raise ValueError('Unknown file parameter')
                argv=['python','-c',FILE_TOOL];stdin=json.dumps(action)
            elif kind=='browser':
                if set(action)-{'action','url','javascript','screenshot','wait_seconds'}:raise ValueError('Unknown browser parameter')
                argv=['python','/opt/evaltools/browser.py'];stdin=json.dumps(action)
            else:raise ValueError('Unregistered tool')
            payload=json.dumps({'argv':argv,'stdin':stdin})
            if len(payload.encode())>1_000_000:raise ValueError('Tool payload exceeds 1 MB')
            timeout=max(.1,min(float(timeout),120))
            # Untrusted strings travel only over stdin, never a host shell or Docker flags.
            with tempfile.TemporaryFile() as stdout,tempfile.TemporaryFile() as stderr:
                proc=subprocess.Popen(['docker','exec','-i','--user',self.policy.user,'--workdir','/workspace',self.name,'python','-c',PAYLOAD],stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,shell=False)
                try:proc.communicate(payload.encode(),timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill();proc.wait();self.close()
                    result={'exit_code':None,'status':'TIMEOUT_CONTAINER_TERMINATED'}
                else:result={'exit_code':proc.returncode,'status':'COMPLETED' if proc.returncode==0 else 'FAILED'}
                for name,stream in [('stdout',stdout),('stderr',stderr)]:
                    stream.seek(0);raw=stream.read();h=hashlib.sha256(raw).hexdigest()
                    blob=self.root/('output-'+h);blob.write_bytes(raw)
                    result[name]=raw[:60000].decode('utf-8',errors='replace')
                    result[name+'_hash']=h;result[name+'_bytes']=len(raw)
                    result[name+'_truncated']=len(raw)>60000
            result['elapsed_seconds']=time.monotonic()-started
        except (ValueError,KeyError,TypeError) as e:
            result={'exit_code':None,'status':'INVALID_TOOL_ARGUMENTS','stdout':'','stderr':str(e)}
        except Exception as e:
            # No fallback; losing the control plane makes the run unusable.
            self.active=False
            result={'exit_code':None,'status':'BLOCKED_ENV','stdout':'','stderr':type(e).__name__+': '+str(e)}
        self.record('tool',{'action':original_action,'timeout':timeout,'result':result})
        return result
    def close(self):
        if self.active:
            try:self.control(['rm','-f',self.name])
            finally:self.active=False

def verify_audit(path):
    previous='0'*64;count=0
    for line in pathlib.Path(path).read_text(encoding='utf-8').splitlines():
        row=json.loads(line);h=row.pop('hash')
        assert row['previous']==previous and digest(row)==h
        previous=h;count+=1
    return {'records':count,'last_hash':previous}
