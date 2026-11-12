"""Domestic non-generation network evidence. No credential resolver is used."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import hashlib
import shutil
import time
from urllib.error import HTTPError
from urllib.request import Request
from cgkn.providers.direct_transport import IP_UNICAST_IF
from cgkn.providers.network_health import write_json
from cgkn.providers.network_transport import NetworkClients
from cgkn.providers.domestic_mode import domestic_state


def rollback(manifest,apply=False,workspace=None):
    workspace=Path(workspace or Path(__file__).resolve().parents[1]).resolve()
    rows=json.loads(Path(manifest).read_text(encoding='utf-8'))['files']
    checked=[]
    for row in rows:
        target=(workspace/row['path']).resolve();backup=(workspace/row['backup']).resolve()
        if workspace not in target.parents or workspace not in backup.parents:raise ValueError('ROLLBACK_PATH_OUTSIDE_WORKSPACE')
        if hashlib.sha256(target.read_bytes()).hexdigest()!=row['after_sha256']:raise ValueError('ROLLBACK_CURRENT_HASH_MISMATCH')
        if hashlib.sha256(backup.read_bytes()).hexdigest()!=row['before_sha256']:raise ValueError('ROLLBACK_BACKUP_HASH_MISMATCH')
        checked.append((target,backup))
    if apply:
        for target,backup in checked:shutil.copy2(backup,target)
    return dict(state='APPLIED' if apply else 'HASHES_VALID_DRY_RUN',files=len(checked))


@contextlib.contextmanager
def process_isolation(config,events):
    """Child-process-only deny rules; never change host VPN, firewall or routes."""
    original=socket.socket.connect
    dns={s for r in config['transport_profiles'].values() for s in r.get('dns_servers',[])}
    interfaces={r['interface_index'] for r in config['transport_profiles'].values() if r.get('interface_index')}
    def connect(sock,address):
        host,port=address[:2]
        try: selected=sock.getsockopt(socket.IPPROTO_IP,IP_UNICAST_IF)
        except OSError:selected=0
        allowed=selected in interfaces and ((port==53 and host in dns) or (port==443 and ipaddress.ip_address(host).is_global))
        events.append(dict(destination=host,port=port,selected_interface=selected,allowed=allowed))
        if not allowed:raise OSError('ISOLATED_NETWORK_DESTINATION_DENIED')
        return original(sock,address)
    old={k:os.environ.get(k) for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY']}
    for k in old:os.environ[k]='' if k=='NO_PROXY' else 'http://127.0.0.1:1'
    socket.socket.connect=connect
    try:yield
    finally:
        socket.socket.connect=original
        for k,v in old.items():
            if v is None:os.environ.pop(k,None)
            else:os.environ[k]=v


def sample(config_path,isolate=False):
    config=json.loads(Path(config_path).read_text(encoding='utf-8'));events=[];connects=[];rows=[]
    scope=process_isolation(config,connects) if isolate else contextlib.nullcontext()
    with scope:
        clients=NetworkClients.load(config_path,log=events.append)
        def check(provider):
            start=time.monotonic();row=dict(provider=provider,dns=False,tcp=False,tls=False,http_status=None,
                authentication='NOT_TESTED',model_calls=0,application_proxy=None)
            try:
                response=clients.opener(provider,logical_id='non-generation-'+provider,attempt_id=str(time.time_ns()),
                    deadline=start+15)(Request(config['probe_endpoints'][provider]))
                row['http_status']=200;response.close()
            except HTTPError as exc:row['http_status']=exc.code;exc.close()
            except Exception as exc:row.update(category=getattr(exc,'kind',type(exc).__name__))
            row['elapsed_seconds']=time.monotonic()-start
            return row
        try:
            with ThreadPoolExecutor(2) as pool:rows=list(pool.map(check,['qwen','deepseek']))
        finally:clients.close()
    for row in rows:
        host=config['probe_endpoints'][row['provider']].split('/')[2]
        trace=[e for e in events if e.get('endpoint_host')==host]
        sockets=[e for e in trace if e['phase']=='direct_socket']
        row['dns']=any(e['phase']=='direct_dns' for e in trace)
        row['tcp']=bool(sockets);row['tls']=any(e['phase'].endswith('start_tls.complete') for e in trace)
        row['socket_evidence']=sockets;row['http_reached']=row['http_status'] is not None
        row['route_id']=clients.bindings[row['provider']]
        row['route_proof']='WINDOWS_OUTGOING_INTERFACE_READBACK' if sockets else 'NOT_VERIFIED'
        row['no_system_tun_interception']='NOT_VERIFIED_WITHOUT_PHYSICAL_CAPTURE_OR_VPN_UPSTREAM_OUTAGE'
        row.setdefault('category','HTTP_'+str(row['http_status']))
    return dict(at=time.time(),isolation=isolate,rows=rows,trace=events,process_connects=connects,
        domestic_network_mode=domestic_state(rows),readiness_scope='HTTP_REACHABILITY_ONLY',
        grok_state='GROK_UNAVAILABLE' if 'grok' in config.get('disabled_providers',[]) else 'NOT_TESTED')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['probe','soak','rollback'])
    p.add_argument('--config',type=Path,default=Path('config/network_routes.json'));p.add_argument('--output',type=Path)
    p.add_argument('--manifest',type=Path);p.add_argument('--apply',action='store_true')
    p.add_argument('--duration',type=float,default=600);p.add_argument('--interval',type=float,default=10);p.add_argument('--isolate',action='store_true')
    a=p.parse_args()
    if a.action=='rollback':
        if not a.manifest:p.error('--manifest is required')
        print(json.dumps(rollback(a.manifest,a.apply)));return
    if not a.output:p.error('--output is required')
    if a.action=='probe':result=sample(a.config,a.isolate);write_json(a.output,result);print(json.dumps(result['rows'],indent=2));return
    start=time.monotonic();samples=[]
    while time.monotonic()-start<a.duration:
        cycle=time.monotonic();samples.append(sample(a.config,a.isolate))
        write_json(a.output,dict(state='RUNNING',elapsed=time.monotonic()-start,samples=samples,model_calls=0))
        end=min(start+a.duration,cycle+a.interval)
        while time.monotonic()<end:time.sleep(min(.5,end-time.monotonic()))
    summary={}
    for provider in ['qwen','deepseek']:
        rows=[r for s in samples for r in s['rows'] if r['provider']==provider];elapsed=sorted(r['elapsed_seconds'] for r in rows)
        summary[provider]=dict(probes=len(rows),http_reached=sum(r['http_reached'] for r in rows),
            success_rate=sum(r['http_reached'] for r in rows)/len(rows),failures=[r for r in rows if not r['http_reached']],
            p50=elapsed[len(elapsed)//2],p95=elapsed[min(len(elapsed)-1,int(len(elapsed)*.95))])
    write_json(a.output,dict(state='COMPLETE',elapsed=time.monotonic()-start,samples=samples,summary=summary,model_calls=0))


if __name__=='__main__':main()
