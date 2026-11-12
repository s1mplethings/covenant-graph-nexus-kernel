"""Exercise or host the existing Lab Gateway with domestic network isolation."""
import argparse
import json
from pathlib import Path
import time
import os
import getpass
import subprocess
import hashlib
import uuid
import logging
from cgkn.providers.evidence_journal import EvidenceJournal
from urllib.request import Request,build_opener,ProxyHandler
from cgkn.providers.domestic_gateway import DomesticGateway
from cgkn.providers.network_health import write_json


def check(lab_root,config,output):
    events=[];gateway=DomesticGateway(lab_root,config,log=events.append)
    try:
        info=gateway.start()
        req=Request(info.base_url+'/models',headers={'Authorization':'Bearer '+info.access_token})
        with build_opener(ProxyHandler({})).open(req,timeout=5) as response:
            data=json.loads(response.read());status=response.status
        probes=[gateway.probe(alias) for alias in ['qwen','deepseek']]
        write_json(output,dict(gateway_running=gateway.server.running,local_http_status=status,
            provider_ids=[p['id'] for p in data['data']],outbound_probes=probes,trace=events,
            authentication='NOT_TESTED',generation='BLOCKED_NO_CURRENT_PAID_AUTHORIZATION',model_calls=0))
        print(json.dumps(dict(gateway_http_status=status,outbound_probes=probes)))
    finally:gateway.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['check','serve','stop'])
    p.add_argument('--lab-root',type=Path,default=Path('D:/cgkn-provider-api-lab'))
    p.add_argument('--config',type=Path,default=Path('config/network_routes.json'));p.add_argument('--output',type=Path)
    p.add_argument('--state-dir',type=Path,default=Path('.cgkn/domestic-gateway'))
    p.add_argument('--provider-parallelism',type=int,choices=(1,2),default=1)
    p.add_argument('--route-diagnostics',action='store_true',help='Enable authenticated non-generation upstream models diagnostics')
    a=p.parse_args()
    if a.action=='check':
        if not a.output:p.error('--output is required for check')
        check(a.lab_root,a.config,a.output);return
    a.state_dir.mkdir(parents=True,exist_ok=True)
    stop=a.state_dir/'stop'
    if a.action=='stop':stop.touch();return
    if os.name=='nt':
        secured=subprocess.run(['icacls.exe',str(a.state_dir.resolve()),'/inheritance:r','/grant:r',
            getpass.getuser()+':(OI)(CI)F','SYSTEM:(OI)(CI)F'],capture_output=True)
        if secured.returncode:raise RuntimeError('PRIVATE_GATEWAY_STATE_ACL_REQUIRED')
    from scripts.network_watchdog import InstanceLock
    with InstanceLock(a.state_dir/'instance.lock'):
        stop.unlink(missing_ok=True)
        session_id=uuid.uuid4().hex
        config_sha=hashlib.sha256(a.config.read_bytes()).hexdigest()
        journal=EvidenceJournal(a.state_dir/'generation-events.jsonl')
        def audit(row):
            journal.emit(logging.LogRecord('cgkn.gateway',logging.INFO,'',0,json.dumps(dict(
                **row,gateway_pid=os.getpid(),gateway_session_id=session_id,network_sha256=config_sha,
                recorded_at=time.time())),(),None))
        gateway=DomesticGateway(a.lab_root,a.config,provider_parallelism=a.provider_parallelism,log=audit,
            response_dir=a.state_dir/'recovery-responses')
        from cgkn.providers.route_diagnostics import install
        install(gateway,read_only=a.route_diagnostics,audit_path=a.state_dir/'route-diagnostics.jsonl',
            identity=dict(gateway_session_id=session_id,
                network_sha256=hashlib.sha256(a.config.read_bytes()).hexdigest(),
                interface_guid=next(iter(gateway.network.routes.values())).interface_guid))
        from cgkn.providers import network_transport as network_module,domestic_gateway as gateway_module
        audit(dict(phase='gateway_start',runtime_source_sha256={str(Path(module.__file__).name):hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (network_module,gateway_module)}))
        info=gateway.start()
        # Only a local gateway token, never a vendor credential. Do not print it.
        from cgkn.providers.application_network import process_identity
        identity=process_identity(os.getpid())
        write_json(a.state_dir/'status.json',dict(pid=os.getpid(),base_url=info.base_url,
            providers=[p.provider_id for p in gateway.providers],grok='DISABLED',running=True,
            network_sha256=hashlib.sha256(a.config.read_bytes()).hexdigest(),
            interface_guid=next(iter(gateway.network.routes.values())).interface_guid,
            route_diagnostics_read_only=a.route_diagnostics,session_id=session_id,
            process_created_at=identity['created_at'],process_executable=identity['executable']))
        session=a.state_dir/'session.json'
        pending=session.with_name('session.'+str(os.getpid())+'.tmp')
        fd=os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as file:
            json.dump(dict(base_url=info.base_url,access_token=(info.access_token),session_id=session_id,
                           pid=os.getpid(),process_created_at=identity['created_at']),file)
        os.replace(pending,session)
        try:
            while not stop.exists():time.sleep(.2)
        finally:
            gateway.close();session.unlink(missing_ok=True)
            journal.close()
            write_json(a.state_dir/'status.json',dict(pid=os.getpid(),running=False))


if __name__=='__main__':main()
