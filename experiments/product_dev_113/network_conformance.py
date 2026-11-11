"""Zero-paid-call real CGNK runner/Coordinator/Worker transport wiring check."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

import httpx

from cgkn.providers.network_transport import NetworkClients, Route
from .conformance import act, worker, IMAGE
from .network_client import NetworkClient
from .runner import run_route
from experiments.product_dev_089.isolation import verify_audit


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    root=parser.parse_args().output;root.mkdir(exist_ok=False)
    auth=root/'auth.json';auth.write_text(json.dumps(dict(stage='ITER-113-ACV-MULTI-API',
        approved=True,user_authorization_reference='HARNESS_CONFORMANCE_ONLY',cumulative_cap_cny=100,
        route_cap_cny=100,max_requests=20,max_tokens=6000000)))
    config=root/'routes.json';config.write_text(json.dumps({'version':'offline','trust_env':False,
        'verify_tls':True,'provider_bindings':{'deepseek':'coordinator','grok':'worker'},
        'transport_profiles':{'coordinator':{'proxy_url':None},'worker':{'proxy_url':None}}}))
    client=NetworkClient('D:/cgkn-provider-api-lab',root/'offline-ledger.json',root/'provider',
        'net114-conformance',run_cap_cny=100,authorization=auth,transport_config=config)
    client.network.close()
    rows=[act('invalid'),act('workspace.file@1',{'action':'read_file','path':'/input/probe.txt'}),
        act('workspace.code@1',{'goal':'Copy synthetic probe text to probe.txt. Transport test only.',
            'acceptance':['probe.txt contains PROBE']},['n0002']),
        worker([{'action':'read_file','path':'/input/probe.txt'}]),
        worker([{'action':'write_file','path':'probe.txt','content':'PROBE'}]),
        act('workspace.command@1',{'command':['python','-c',"from pathlib import Path;assert Path('probe.txt').read_text()=='PROBE';print('PASS')"]}),
        act(op='finish')]
    seen=[]
    def handler(route):
        def send(req):
            index=len(seen);seen.append({'route':route,'host':req.url.host,'index':index})
            assert route==('worker' if index in (3,4) else 'coordinator')
            return httpx.Response(200,json={'model':req.url.host,'id':str(index),
                'choices':[{'message':{'content':json.dumps(rows[index])},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}})
        return send
    client.network=NetworkClients({k:Route(k,None) for k in ['coordinator','worker']},
        {'deepseek':'coordinator','grok':'worker'},version='offline',
        transports={k:httpx.MockTransport(handler(k)) for k in ['coordinator','worker']},log=client._trace)
    try:
        with patch.object(type(client.service.secret_manager),'resolve',lambda self,p:'synthetic-only'):
            boundary,receipt=run_route(root=root/'run',run_id='net114-conformance',route='R_CGNK',
                image=IMAGE,client=client,goal='HARNESS_CONFORMANCE_ONLY',
                public_files={'probe.txt':'PROBE'},mode='HARNESS_CONFORMANCE_ONLY')
        assert receipt['result']['status']=='SUCCEEDED',receipt
        assert len(seen)==len(rows)
        result={'status':'PASS','mode':'HARNESS_CONFORMANCE_ONLY','paid_calls':0,'routes':seen,
                'receipt':receipt,'audit':verify_audit(boundary.audit_path)}
        (root/'result.json').write_text(json.dumps(result,indent=2));print('PASS real runner and worker injection; no network/paid generation')
    finally:client.close()

if __name__=='__main__':main()
