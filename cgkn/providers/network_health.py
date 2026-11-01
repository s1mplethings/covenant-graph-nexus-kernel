"""Credential-free, bounded HTTPS probes and provider/route circuit state.

Infrastructure support only; does not plan work, submit completions or own budgets.
"""
from __future__ import annotations

import dataclasses
import json
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit


@dataclasses.dataclass
class Health:
    failures: int = 0
    successes: int = 0
    opened: float = 0
    state: str = 'HEALTHY'
    recovering_request: bool = False


class Circuits:
    def __init__(self, threshold=2, cooldown=30, recovery_successes=2, clock=time.monotonic):
        self.threshold, self.cooldown = threshold, cooldown
        self.recovery_successes, self.clock = recovery_successes, clock
        self.rows = {}
        self.lock = threading.Lock()

    def available(self, provider, route):
        with self.lock:
            h = self.rows.setdefault((provider,route), Health())
            return not h.recovering_request and (h.state != 'OPEN_CIRCUIT' or self.clock()-h.opened >= self.cooldown)

    def reserve(self, provider, route):
        """At most one trial in flight while an open route is recovering."""
        with self.lock:
            h=self.rows.setdefault((provider,route),Health())
            if h.recovering_request or (h.state=='OPEN_CIRCUIT' and self.clock()-h.opened<self.cooldown): return False
            if h.state in ('OPEN_CIRCUIT','RECOVERING'): h.recovering_request=True
            return True

    def release(self, provider, route):
        with self.lock:
            self.rows.setdefault((provider,route),Health()).recovering_request=False

    def record(self, provider, route, ok):
        with self.lock:
            h = self.rows.setdefault((provider,route), Health())
            h.recovering_request = False
            if ok:
                h.failures = 0
                h.successes += 1
                h.state = 'HEALTHY' if h.state=='HEALTHY' or h.successes >= self.recovery_successes else 'RECOVERING'
            else:
                h.successes = 0
                h.failures += 1
                if h.failures >= self.threshold:
                    h.state, h.opened = 'OPEN_CIRCUIT', self.clock()
                else: h.state = 'DEGRADED'
            return h.state


def probe(provider, route_id, proxy_url, endpoint, timeout=5, observer=None):
    """Fresh TCP -> CONNECT -> verified TLS -> HTTP GET. No credentials/body.

    HTTP status proves communication, never authentication or model capability.
    A total deadline bounds all socket operations, including trickling headers.
    """
    target, proxy = urlsplit(endpoint), urlsplit(proxy_url)
    if target.scheme != 'https' or target.username or target.password or target.query:
        raise ValueError('PROBE_REQUIRES_CREDENTIAL_FREE_HTTPS')
    if proxy.scheme != 'http' or proxy.username or proxy.password:
        raise ValueError('PROBE_REQUIRES_HTTP_PROXY')
    start = time.monotonic()
    end = start+timeout
    row = dict(provider=provider,route_id=route_id,host=target.hostname,
               tcp=False,connect=False,tls=False,http_status=None,layer='L1',
               category='TCP_CONNECT_FAILED', model_calls=0)
    sock = None
    def remaining():
        value = end-time.monotonic()
        if value <= 0: raise TimeoutError()
        return value
    def headers():
        data = b''
        while b'\r\n\r\n' not in data:
            sock.settimeout(remaining())
            chunk = sock.recv(1)
            if not chunk: raise EOFError()
            data += chunk
            if len(data)>32768: raise ValueError('HEADER_LIMIT')
        return int(data.split(b' ',2)[1])
    try:
        sock = socket.create_connection((proxy.hostname,proxy.port),timeout=remaining())
        row['local_source_port']=sock.getsockname()[1]
        row.update(tcp=True,layer='L2',category='PROXY_TUNNEL_FAILED')
        authority = f'{target.hostname}:{target.port or 443}'
        sock.sendall(f'CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n'.encode('ascii'))
        row['connect_status'] = headers()
        if row['connect_status'] != 200: return row
        if observer:
            try: row['node_observation']=observer(row['local_source_port'])
            except Exception:
                row['node_observation']={'evidence':'OBSERVER_UNAVAILABLE','chains':[]}
        row.update(connect=True,layer='L3',category='TLS_HANDSHAKE_FAILED')
        sock.settimeout(remaining())
        sock = ssl.create_default_context().wrap_socket(sock,server_hostname=target.hostname)
        row.update(tls=True,category='HTTP_RESPONSE_FAILED')
        sock.settimeout(remaining())
        sock.sendall(f'GET {target.path or "/"} HTTP/1.1\r\nHost: {target.hostname}\r\nConnection: close\r\nUser-Agent: CGKN-network-health/1\r\n\r\n'.encode('ascii'))
        row['http_status'] = headers()
        row['category'] = 'HTTP_'+str(row['http_status'])
    except ssl.SSLCertVerificationError: row['category']='TLS_CERTIFICATE_FAILED'
    except (TimeoutError,socket.timeout): row['category'] = {'L1':'TCP_TIMEOUT','L2':'PROXY_TUNNEL_TIMEOUT','L3':'TLS_TIMEOUT' if not row['tls'] else 'HTTP_TIMEOUT'}[row['layer']]
    except ConnectionRefusedError: row['category']='TCP_REFUSED'
    except EOFError: row['category']='TUNNEL_EOF' if row['layer']=='L2' else 'TLS_OR_HTTP_EOF'
    except (OSError,ValueError): pass
    finally:
        if sock: sock.close()
        row['elapsed_seconds'] = round(time.monotonic()-start,4)
        row['http_reached'] = row['http_status'] is not None
        row['authentication'] = 'NOT_TESTED'
    return row


def matrix(config,observer=None):
    from concurrent.futures import ThreadPoolExecutor
    jobs = [(p,r,v['proxy_url'],endpoint) for p,endpoint in config['probe_endpoints'].items()
            for r,v in config['transport_profiles'].items()]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(probe,*job,timeout=config.get('probe_timeout',8),observer=observer) for job in jobs]
        return [f.result() for f in futures]


def write_json(path, value):
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)
