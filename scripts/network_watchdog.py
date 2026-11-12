"""Independent dedicated-proxy supervisor and zero-generation network diagnostics.

Run with python -m scripts.network_watchdog. Never changes OS networking.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import psutil
import yaml

from cgkn.providers.network_health import Circuits, matrix, write_json


class InstanceLock:
    def __init__(self,path): self.path,self.handle=Path(path),None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.handle=self.path.open('a+b')
        self.handle.seek(0); self.handle.write(b'0'); self.handle.flush(); self.handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.handle.close(); raise RuntimeError('WATCHDOG_ALREADY_RUNNING') from None
        return self
    def __exit__(self,*args): self.handle.close()


def process(config):
    expected=Path(config['proxy_config']).resolve()
    executable=Path(config['executable']).resolve()
    matches=[]
    for p in psutil.process_iter(['name','pid']):
        try:
            if (p.info['name'] or '').casefold()!=executable.name.casefold(): continue
            if Path(p.exe()).resolve()!=executable: continue
            args=p.cmdline() or []
            if '-f' in args and Path(args[args.index('-f')+1]).resolve()==expected: matches.append(p)
        except (psutil.Error,OSError,IndexError): continue
    if len(matches)>1: raise RuntimeError('DUPLICATE_DEDICATED_PROXY')
    return matches[0] if matches else None


def listeners(config):
    result={}
    for port in config['ports']:
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=.5): result[str(port)]=True
        except OSError: result[str(port)]=False
    return result


def controller(config,path='/version',method='GET',body=None,timeout=4):
    private=yaml.safe_load(Path(config['proxy_config']).read_text(encoding='utf-8'))
    address=private.get('external-controller')
    if not isinstance(address,str): raise ValueError('MISSING_CONTROLLER_CONFIGURATION')
    if not address.startswith('127.0.0.1:'): raise ValueError('CONTROLLER_MUST_BE_LOOPBACK')
    headers={'Authorization':'Bearer '+private['secret']} if private.get('secret') else {}
    with httpx.Client(trust_env=False,timeout=timeout,follow_redirects=False) as client:
        r=client.request(method,'http://'+address+path,headers=headers,json=body)
        r.raise_for_status()
        result=r.json() if r.content else {}
        if not isinstance(result,dict): raise ValueError('INVALID_CONTROLLER_RESPONSE')
        return result


def node_status(config):
    data=controller(config,'/proxies').get('proxies') or {}
    names=config.get('node_names',[])+config.get('group_names',[])
    return {n:{k:data.get(n,{}).get(k) for k in ('type','alive','now')} for n in names}


def observe_node(config,source_port):
    try:
        rows=controller(config,'/connections',timeout=.5).get('connections') or []
        allowed=set(config.get('node_names',[])+config.get('group_names',[]))
        for row in rows:
            if str(row.get('metadata',{}).get('sourcePort'))==str(source_port):
                return dict(evidence='CONTROLLER_SOURCE_PORT_MATCH',chains=[n for n in row.get('chains',[]) if n in allowed])
    except (httpx.HTTPError,OSError,ValueError,TypeError,AttributeError): pass
    return dict(evidence='NOT_CAPTURED',chains=[])


def l1(config):
    p=process(config)
    ports=listeners(config)
    api=False
    if p and all(ports.values()):
        try: api=bool(controller(config).get('version'))
        except (httpx.HTTPError,OSError,ValueError): pass
    return dict(pid=p.pid if p else None,ports=ports,controller=api,
                ok=bool(p) and all(ports.values()) and api)


def start_proxy(config):
    if process(config): return 'ALREADY_RUNNING'
    if any(listeners(config).values()): return 'PORT_CONFLICT'
    root=Path(config['state_dir']); root.mkdir(parents=True,exist_ok=True)
    output=root/'proxy-process.log'
    if output.exists() and output.stat().st_size>2*1024*1024:
        output.replace(root/'proxy-process.previous.log')
    with output.open('ab') as log:
        subprocess.Popen([config['executable'],'-d',str(Path(config['proxy_config']).parent),'-f',config['proxy_config']],
            stdin=subprocess.DEVNULL,stdout=log,stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    return 'STARTED'


def event_logger(root):
    logger=logging.getLogger('cgkn.network.'+str(root)); logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler=RotatingFileHandler(root/'watchdog.jsonl',maxBytes=2*1024*1024,backupCount=3,encoding='utf-8')
        logger.addHandler(handler)
    return lambda **row: logger.info(json.dumps({'at':time.time(),**row},ensure_ascii=False))


def run(config,duration=None):
    root=Path(config['state_dir']); root.mkdir(parents=True,exist_ok=True)
    with InstanceLock(root/'instance.lock'):
        stop=root/'stop'; stop.unlink(missing_ok=True)
        emit=event_logger(root)
        circuits=Circuits(config.get('failure_threshold',2),config.get('cooldown',30))
        started=time.monotonic(); restart_times=collections.deque(); next_restart=0; failures=0; restarts=0; cycle=0
        network_state='RECOVERING'; last_rows=[]; last_nodes={}
        emit(event='watchdog_started',pid=os.getpid())
        try:
            while not stop.exists() and (duration is None or time.monotonic()-started<duration):
                cycle_start=time.monotonic(); cycle+=1
                proxy_log=root/'proxy-process.log'
                if proxy_log.exists() and proxy_log.stat().st_size>2*1024*1024:
                    with proxy_log.open('rb') as source:
                        source.seek(-2*1024*1024,2)
                        (root/'proxy-process.previous.log').write_bytes(source.read())
                    with proxy_log.open('r+b') as target: target.truncate(0)
                local=l1(config)
                state=network_state if local['ok'] else 'FAILING'
                if local['ok']: failures=0
                else:
                    failures+=1
                    if failures>=config.get('failure_threshold',2) and cycle_start>=next_restart:
                        while restart_times and cycle_start-restart_times[0]>3600: restart_times.popleft()
                        if len(restart_times)>=config.get('max_restarts_per_hour',5): state='OPEN_CIRCUIT'
                        else:
                            p=process(config)
                            # Restart only the verified dedicated instance. L3 failures never restart it.
                            if p:
                                p.terminate()
                                try: p.wait(5)
                                except psutil.TimeoutExpired: state='UNAVAILABLE'
                            result=start_proxy(config)
                            restart_times.append(cycle_start); restarts+=1
                            next_restart=cycle_start+min(300,5*2**min(restarts,6))
                            emit(event='restart',reason='PROCESS_UNRESPONSIVE' if p else 'PROCESS_EXIT_OR_MISSING',result=result,count=restarts)
                            state='RECOVERING'
                rows=[]; nodes={}
                if local['ok'] and cycle%config.get('probe_every',2)==0:
                    rows=matrix(config,lambda port:observe_node(config,port))
                    for row in rows:
                        row['health']=circuits.record(row['provider'],row['route_id'],row['http_reached'])
                    try: nodes=node_status(config)
                    except (httpx.HTTPError,OSError,ValueError): pass
                    reached=sum(r['http_reached'] for r in rows)
                    state='UNAVAILABLE' if not reached else ('HEALTHY' if reached==len(rows) else 'DEGRADED')
                    network_state=state;last_rows=rows;last_nodes=nodes
                snapshot=dict(at=time.time(),watchdog_pid=os.getpid(),cycle=cycle,state=state,local=local,
                              probes=last_rows,nodes=last_nodes,restarts=restarts,uptime_seconds=round(time.monotonic()-started,2))
                write_json(root/'status.json',snapshot); emit(event='sample',**snapshot)
                end=cycle_start+config.get('interval',15)
                while time.monotonic()<end and not stop.exists() and (duration is None or time.monotonic()-started<duration): time.sleep(.2)
        finally:
            emit(event='watchdog_stopped',reason='requested' if stop.exists() else 'duration_or_exception')
            write_json(root/'status.json',dict(at=time.time(),watchdog_pid=os.getpid(),state='STOPPED',restarts=restarts))


def soak(config,duration,output):
    """Standalone bounded experiment. Does not require a supervising chat."""
    started=time.monotonic(); samples=[]
    while time.monotonic()-started<duration:
        local=l1(config); rows=matrix(config,lambda port:observe_node(config,port))
        try: nodes=node_status(config)
        except (httpx.HTTPError,OSError,ValueError): nodes={}
        samples.append(dict(at=time.time(),elapsed=time.monotonic()-started,local=local,probes=rows,nodes=nodes))
        write_json(output,dict(status='RUNNING',requested_seconds=duration,samples=samples,model_calls=0))
        end=min(started+duration,time.monotonic()+config.get('soak_interval',30))
        while time.monotonic()<end: time.sleep(min(.5,end-time.monotonic()))
    flat=[r for s in samples for r in s['probes']]
    latency=sorted(r['elapsed_seconds'] for r in flat)
    write_json(output,dict(status='COMPLETE',requested_seconds=duration,elapsed_seconds=time.monotonic()-started,
        samples=samples,model_calls=0,summary=dict(probes=len(flat),http_reached=sum(r['http_reached'] for r in flat),
        failed=sum(not r['http_reached'] for r in flat),l1_failures=sum(not s['local']['ok'] for s in samples),
        latency_p50=latency[len(latency)//2],latency_p95=latency[min(len(latency)-1,int(len(latency)*.95))])))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['configure','run','start','stop','status','probe','soak','start-proxy','stop-proxy'])
    p.add_argument('--config',type=Path,required=True); p.add_argument('--duration',type=float,default=None)
    p.add_argument('--output',type=Path)
    p.add_argument('--proxy-config',type=Path);p.add_argument('--executable',type=Path);p.add_argument('--state-dir',type=Path)
    p.add_argument('--routes',type=Path,default=Path(__file__).resolve().parents[1]/'config/network_routes.json')
    a=p.parse_args()
    if a.action=='configure':
        if not a.proxy_config or not a.executable or not a.state_dir: p.error('--proxy-config, --executable and --state-dir are required')
        if a.config.exists(): p.error('configuration already exists; back up before editing')
        config=json.loads(a.routes.read_text(encoding='utf-8'))
        config.update(proxy_config=str(a.proxy_config.resolve(strict=True)),executable=str(a.executable.resolve(strict=True)),
            state_dir=str(a.state_dir.resolve()),ports=[17890,17891,17892],node_names=['api-primary-node','api-backup-node'],
            group_names=['api-primary-fallback','api-backup-fallback'],interval=15,probe_every=2,soak_interval=30)
        write_json(a.config,config);print('CONFIGURED_WITH_CANONICAL_PATHS');return
    config=json.loads(a.config.read_text(encoding='utf-8'))
    root=Path(config['state_dir']); root.mkdir(parents=True,exist_ok=True)
    if a.action=='run':
        private_path=Path(config['proxy_config'])
        private_doc=yaml.safe_load(private_path.read_text(encoding='utf-8'))
        write_json(root/'startup.json',dict(proxy_config=str(private_path.resolve()),
            config_sha256=hashlib.sha256(private_path.read_bytes()).hexdigest(),
            controller_present='external-controller' in private_doc,python=sys.executable))
        try: run(config,a.duration)
        except RuntimeError as exc:
            if str(exc)!='WATCHDOG_ALREADY_RUNNING': raise
            print('ALREADY_RUNNING')
        except Exception as exc:
            import traceback
            write_json(root/'fatal.json',{'at':time.time(),'type':type(exc).__name__,'frames':traceback.format_tb(exc.__traceback__)})
            raise
    elif a.action=='soak':
        if not a.output: p.error('--output is required')
        soak(config,a.duration or 600,a.output)
    elif a.action=='probe':
        result=matrix(config,lambda port:observe_node(config,port))
        if a.output: write_json(a.output,result)
        print(json.dumps(result,indent=2))
    elif a.action=='status':
        last=json.loads((root/'status.json').read_text()) if (root/'status.json').exists() else None
        alive=False
        if last:
            try: alive='scripts.network_watchdog' in psutil.Process(last['watchdog_pid']).cmdline()
            except psutil.Error: pass
        print(json.dumps(dict(current=l1(config),watchdog_alive=alive,last=last),indent=2))
    elif a.action=='stop': (root/'stop').touch()
    elif a.action=='start-proxy': print(start_proxy(config))
    elif a.action=='stop-proxy':
        (root/'stop').touch()
        # Allow in-progress bounded probes to observe stop before terminating proxy.
        deadline=time.monotonic()+30
        while True:
            try:
                with InstanceLock(root/'instance.lock'):
                    proc=process(config)
                    if proc: proc.terminate(); proc.wait(5)
                    print('STOPPED');break
            except RuntimeError:
                if time.monotonic()>=deadline: raise
                time.sleep(.2)
    elif a.action=='start':
        try:
            with InstanceLock(root/'instance.lock'): pass
        except RuntimeError: print('ALREADY_RUNNING'); return
        subprocess.Popen([sys.executable,'-X','utf8','-m','scripts.network_watchdog','run','--config',str(a.config.resolve())],
            cwd=Path(__file__).resolve().parents[1],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        print('START_REQUESTED')


if __name__=='__main__': main()
