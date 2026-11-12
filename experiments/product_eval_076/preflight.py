"""Read-only environment checks and synthetic isolation evidence; no model calls.

This is NOT a product benchmark runner. Never promotes a preflight to formal.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
IMAGE = 'python@sha256:37ed081dbe77115b843b3d139801105e110f43005a2df4e80af94777cfd807f5'

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def run(argv, timeout=60):
    started = datetime.now(timezone.utc).isoformat()
    try:
        p = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        return dict(argv=argv, started=started, exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except subprocess.TimeoutExpired as e:
        return dict(argv=argv, started=started, status='TIMEOUT', stdout=str(e.stdout or ''), stderr=str(e.stderr or ''))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=pathlib.Path, required=True)
    args=p.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    checks={}
    for name, argv in {
        'head':['git','rev-parse','HEAD'], 'branch':['git','branch','--show-current'],
        'worktree':['git','status','--short'],
        'history':['git','show','-s','--format=%H %s','56cba0c','feaf6c1','v0.2.0-rc.6'],
        'merge_base':['git','merge-base','HEAD','feaf6c1'],
        'docker':['docker','info','--format','{{.ServerVersion}}'],
        'image':['docker','image','inspect',IMAGE,'--format','{{.Id}}'],
        'media':['ffmpeg','-version'],
    }.items():
        checks[name]=run(argv)
    public=out/'public'; public.mkdir()
    (public/'canary.txt').write_text('public-canary',encoding='utf-8')
    for name in ('private','sibling','audit'):
        (out/name).mkdir()
        (out/name/'canary.txt').write_text(name+'-canary',encoding='utf-8')
    code='''import pathlib,json,socket,os
r={'public_read':pathlib.Path('/input/canary.txt').read_text()=='public-canary'}
try:
 pathlib.Path('/input/canary.txt').write_text('changed');r['input_write_denied']=False
except OSError:r['input_write_denied']=True
for name in ('private','sibling','audit'):
 r[name+'_not_mounted']=not pathlib.Path('/'+name+'/canary.txt').exists()
r['docker_socket_absent']=not pathlib.Path('/var/run/docker.sock').exists()
r['host_mount_absent']=not pathlib.Path('/mnt/host').exists()
r['credential_environment_absent']=not any(k.startswith(('CGKN_','OPENAI_','AWS_')) for k in os.environ)
try:
 socket.create_connection(('1.1.1.1',443),timeout=2).close();r['egress_denied']=False
except OSError:r['egress_denied']=True
print(json.dumps(r));raise SystemExit(0 if all(r.values()) else 2)
'''
    checks['container_canary']=run(['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','32','--memory','128m','--cpus','1','--mount',f'type=bind,source={public},target=/input,readonly',IMAGE,'python','-c',code])
    checks['related_regression']=run([sys.executable,'-m','pytest','-q','tests/agent/test_agent_mvp_gateway_cli.py','tests/application/software_project/test_gateway_e2e.py','tests/providers/test_gateway_client.py','tests/test_provider_api_budget.py'],180)
    write(out/'checks.json',checks)
    matrix=[]
    for group,levels in [('TAKEOVER',['B-1','B0','B+1','B-2','B+2']),('CREATE',['B0']),('REPEAT',['B0']),('SELF_EVOLVE',['B0'])]:
        for level in levels:
            for domain in ['video','promotion']:
                order=['R_DIRECT','R_CGNK'] if len(matrix)//2%2==0 else ['R_CGNK','R_DIRECT']
                for route in order:
                    matrix.append(dict(order=len(matrix)+1,task_id=f'{group}-{domain}-{level}',route=route,status='NOT_RUN',formal_status='UNVERIFIED',engineering=[None]*24,domain_quality=[None]*4,gates={f'G{i}':'UNTESTED' for i in range(1,7)},confirmed_score=0,evaluated_weight=0,pending_weight=100,possible_score_interval=[0,100],host_semantic_assistance_count=None))
    assert len(matrix)==32
    write(out/'matrix.json',dict(frozen=False,seed_proposed=7601,rows=matrix))
    write(out/'status.json',dict(iteration='ITER-076',phase='PREFLIGHT_ONLY',formal_freeze=False,development_runs=0,formal_runs=0,formal_planned=32,provider_requests=0,provider_tokens=0,new_api_cost_cny=0,budget_cny=100,acceptance_reserve_cny=20,actual_bill='NOT_QUERIED',container_canary_scope='synthetic shell only; not integrated into either development route',browser_isolation='UNTESTED',mcp_isolation='UNTESTED',connector_isolation='UNTESTED',product_gui='UNTESTED',real_media='UNTESTED',actual_model_identity='UNVERIFIED',human_review='PENDING_HUMAN',product_failures=0,protocol_contaminations=0))
    hashes={str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest() for f in out.rglob('*') if f.is_file()}
    hashes['preflight_source']=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
    write(out/'hashes.json',hashes)
    print(json.dumps({'output':str(out),'formal_ready':False,'canary_exit':checks['container_canary'].get('exit_code'),'regression_exit':checks['related_regression'].get('exit_code')}))

if __name__=='__main__':main()
