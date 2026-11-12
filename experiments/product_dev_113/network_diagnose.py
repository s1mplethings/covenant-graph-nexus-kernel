"""Display explicit routes; optional two non-generation HTTPS probes. No API keys."""
import argparse
import json
import time
from pathlib import Path
from urllib.request import Request
from urllib.parse import urlsplit

from cgkn.providers.network_transport import NetworkClients


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True)
    p.add_argument('--check',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.output and a.output.exists():raise RuntimeError('OUTPUT_EXISTS')
    events=[];client=NetworkClients.load(a.config,log=events.append)
    rows=[]
    try:
        for alias,host in [('deepseek','api.deepseek.com'),('grok','api.x.ai')]:
            route_id=client.bindings[alias];route=client.routes[route_id]
            proxy=urlsplit(route.proxy_url) if route.proxy_url else None
            row={'provider':alias,'endpoint_host':host,'route_id':route_id,
                'proxy_host':proxy.hostname if proxy else None,'proxy_port':proxy.port if proxy else None,
                'trust_env':False,'verify_tls':True,'config_version':client.version}
            if a.check:
                try:
                    response=client.opener(alias,logical_id='diagnostic',attempt_id=alias,
                        deadline=time.monotonic()+25)(Request('https://'+host+'/v1/models'))
                    row['http_status']=200;row['bytes']=len(response.read())
                except Exception as exc:
                    row['http_status']=getattr(exc,'code',None);row['error_type']=type(exc).__name__
            rows.append(row)
    finally:client.close()
    result={'routes':rows,'non_generation_probes':2 if a.check else 0,'model_calls':0,'trace':events}
    if a.output:a.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
