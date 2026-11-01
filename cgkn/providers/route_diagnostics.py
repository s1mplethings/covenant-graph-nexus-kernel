"""Opt-in authenticated GET diagnostics on the existing domestic Gateway.

No generation, arbitrary URL, headers, credentials or response bodies are exposed.
The unchanged generation adapter and this diagnostic share NetworkClients/pools.
"""
import hashlib
import ctypes
import json
import os
import socket
import struct
import threading
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request


def tcp_connections(pid,port):
    """Read Windows TCP owner-PID table; no driver, capture or admin changes."""
    if os.name!='nt': return {'status':'NOT_CAPTURED'}
    size=ctypes.c_ulong(0)
    query=ctypes.WinDLL('iphlpapi').GetExtendedTcpTable
    query.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong),ctypes.c_bool,
                    ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong]
    query.restype=ctypes.c_ulong
    result=query(None,ctypes.byref(size),False,socket.AF_INET,5,0)
    if result!=122 or not 4<=size.value<=16*1024*1024:return {'status':'NOT_CAPTURED','code':int(result)}
    buffer=ctypes.create_string_buffer(size.value)
    result=query(buffer,ctypes.byref(size),False,socket.AF_INET,5,0)
    if result:return {'status':'NOT_CAPTURED','code':int(result)}
    raw=buffer.raw; count=struct.unpack_from('<I',raw)[0]; rows=[]
    if 4+24*count>len(raw):return {'status':'NOT_CAPTURED'}
    for index in range(count):
        state,local,local_port,remote,remote_port,owner=struct.unpack_from('<6I',raw,4+24*index)
        if owner==pid and socket.ntohs(local_port & 0xffff)==port:
            rows.append(dict(LocalAddress=socket.inet_ntoa(struct.pack('<I',local)),LocalPort=port,
                RemoteAddress=socket.inet_ntoa(struct.pack('<I',remote)),
                RemotePort=socket.ntohs(remote_port & 0xffff),OwningProcess=owner,State=state,
                source='WINDOWS_GET_EXTENDED_TCP_TABLE_OWNER_PID'))
    return rows


def install(gateway, *, read_only=True, identity=None, audit_path=None):
    from cgkn_provider_lab.gateway import _GatewayHandler
    from pathlib import Path
    from . import network_transport,direct_transport,domestic_gateway,streaming_sse,gateway_stream,progress_io
    sources={Path(module.__file__).name:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
             for module in (network_transport,direct_transport,domestic_gateway,streaming_sse,gateway_stream,progress_io)}
    sources[Path(__file__).name]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    active={};lock=threading.Lock();prior_log=gateway.network.log
    audit=None
    if audit_path:
        import logging
        from .evidence_journal import EvidenceJournal
        audit=EvidenceJournal(audit_path)

    def stage(record,name):
        record['stages'].append(name)
        record['last_completed_stage']=name

    def observe(row):
        prior_log(row)
        identity=row.get('logical_id')
        with lock:
            record=active.get(identity)
            if record is not None:
                record['trace'].append(dict(row))
                if row.get('phase') in ('direct_interface_validated','direct_dns','direct_socket') or row.get('phase','').endswith('.complete'):
                    stage(record,row['phase'])
        if record is not None and row.get('phase')=='direct_socket' and os.name=='nt':
            try:connections=tcp_connections(os.getpid(),int(row['local_port']))
            except Exception:connections={'status':'NOT_CAPTURED'}
            with lock:record['os_connections'].append(connections)
    gateway.network.log=observe

    class Handler(_GatewayHandler):
        def _send(self,status,payload):
            if self.path.startswith('/v1/network/models/') and 'request_id' in payload:
                phases={row.get('phase') for row in payload.get('trace',[])}
                stages=payload.get('stages',[])
                payload['observed_progress']={
                    'credential_resolved':'credential_resolved' in stages,
                    'route_initialized':'route_initialized' in stages,
                    'dns_started':'direct_dns_started' in phases,'dns_completed':'direct_dns' in phases,
                    **{label:any(name and name.endswith(suffix) for name in phases) for label,suffix in (
                        ('tcp_started','connect_tcp.started'),('tcp_completed','connect_tcp.complete'),
                        ('tls_started','start_tls.started'),('tls_completed','start_tls.complete'),
                        ('http_send_started','send_request_headers.started'),('http_send_completed','send_request_headers.complete'))}}
                if audit:
                    import logging
                    audit.emit(logging.LogRecord('cgkn.route',logging.INFO,'',0,json.dumps(payload),(),None))
            if self.command=='POST':
                gateway.network.emit(dict(phase='local_response_write_started',gateway_http_status=status))
                try:result=super()._send(status,payload)
                except OSError as exc:
                    gateway.network.emit(dict(phase='local_response_write_failed',exception_type=type(exc).__name__))
                    raise
                gateway.network.emit(dict(phase='local_response_write_completed',gateway_http_status=status))
                return result
            return super()._send(status,payload)

        def do_POST(self):
            if not read_only:
                safe=lambda text:text if text and len(text)<=128 and all(c.isalnum() or c in '-_.' for c in text) else None
                token=network_transport.REQUEST_CONTEXT.set(dict(inbound_http=True,
                    client_run_id=safe(self.headers.get('X-CGKN-Run-ID')),
                    client_job_id=safe(self.headers.get('X-CGKN-Job-ID')),
                    client_attempt_id=safe(self.headers.get('X-CGKN-Attempt-ID')),
                    client_call_id=safe(self.headers.get('X-CGKN-Call-ID')),
                    input_token_ceiling=self.headers.get('X-CGKN-Input-Token-Ceiling')))
                try:
                    if 'text/event-stream' not in self.headers.get('Accept',''):return super().do_POST()
                    if not self._authorized():return
                    from .gateway_stream import serve
                    from cgkn_provider_lab.gateway import MAX_BODY_BYTES
                    mode='chat' if self.path=='/v1/chat/completions' else 'responses' if self.path=='/v1/responses' else None
                    if mode is None:return self._send(404,{'error':{'type':'not_found'}})
                    try:
                        length=int(self.headers.get('Content-Length','0'))
                        if not 0<length<=MAX_BODY_BYTES:raise ValueError()
                        payload=json.loads(self.rfile.read(length))
                        if not isinstance(payload,dict) or payload.get('stream') is not True:raise ValueError()
                    except (ValueError,UnicodeDecodeError):return self._send(400,{'error':{'type':'invalid_request'}})
                    return serve(self,payload,mode,gateway,(identity or {}).get('gateway_session_id') or gateway.stream_session_id)
                finally:network_transport.REQUEST_CONTEXT.reset(token)
            if self._authorized():self._send(403,{'error':{'type':'route_diagnostics_read_only'}})

        def do_GET(self):
            prefix='/v1/network/models/'
            if not self.path.startswith(prefix):return super().do_GET()
            if not self._authorized():return
            provider=self.path[len(prefix):]
            if provider not in ('qwen','deepseek'):
                self._send(404,{'error':{'type':'diagnostic_provider_not_allowed'}});return
            request_id=uuid.uuid4().hex;record={'trace':[],'os_connections':[],'stages':[],'last_completed_stage':'accepted'};start=time.time();outcome={}
            with lock:active[request_id]=record
            base=dict(request_id=request_id,provider=provider,gateway_pid=os.getpid(),generation_calls=0,
                **(identity or {}),
                inbound={'client_address':self.client_address[0],'client_port':self.client_address[1],
                         'gateway_port':self.server.server_port},runtime_source_sha256=sources,
                scope='SAME_GATEWAY_AND_OUTBOUND_POOL; GENERATION_ADAPTER_INVOKE_NOT_EXECUTED')
            try:
                with gateway.provider_slot(provider):
                    stage(record,'provider_slot_acquired')
                    entry=next(p for p in gateway.providers if p.provider_id==provider)
                    credential=gateway.application.secrets.resolve(entry)
                    stage(record,'credential_resolved')
                    req=Request(entry.base_url.rstrip('/')+'/models',headers={'Authorization':'Bearer '+credential})
                    opener=gateway.network.opener(provider,logical_id=request_id,attempt_id=request_id+'-models',outcome=outcome)
                    stage(record,'route_initialized')
                    try:
                        with opener(req) as response:
                            raw=response.read();status=int(response.status)
                    except HTTPError as exc:
                        raw=exc.read();status=int(exc.code);exc.close()
                    stage(record,'upstream_http_response_received')
                parsed=True
                try:
                    doc=json.loads(raw)
                    data=doc['data']
                    if not isinstance(doc,dict) or not isinstance(data,list) or any(not isinstance(item,dict) or not isinstance(item.get('id'),str) for item in data):raise ValueError()
                except (ValueError,KeyError,TypeError):parsed=False;data=[]
                if status==200 and parsed:
                    gateway.available_models[provider]={item["id"] for item in data}
                listed=any(item.get('id')==entry.model for item in data)
                reason=('UNEXPECTED_UPSTREAM_STATUS' if status!=200 else
                        'INVALID_MODEL_LIST_RESPONSE' if not parsed else 'CONFIGURED_MODEL_MISSING' if not listed else 'OK')
                result=dict(**base,gateway_http_status=200,upstream_http_status=status,
                    route_id=gateway.network.bindings[provider],upstream_method='GET',upstream_path='/models',
                    configured_model_listed=listed,model_list_parse_valid=parsed,ok=reason=='OK',reason=reason,
                    response_sha256=hashlib.sha256(raw).hexdigest(),response_bytes=len(raw),model_count=len(data),
                    model_ids=sorted(item["id"] for item in data),
                    model_ids_sha256=hashlib.sha256(json.dumps(sorted(item['id'] for item in data)).encode()).hexdigest(),
                    started=start,ended=time.time(),**record)
                self._send(200,result)
            except Exception as exc:
                self._send(503,dict(**base,gateway_http_status=503,upstream_http_status=None,ok=False,
                    reason=getattr(exc,'code',None) or getattr(exc,'kind',None) or type(exc).__name__,
                    exception_type=type(exc).__name__,route_id=gateway.network.bindings[provider],
                    started=start,ended=time.time(),
                    outcome={k:v for k,v in outcome.items() if isinstance(v,(str,bool,int,float))},**record))
            finally:
                with lock:active.pop(request_id,None)
    gateway.server._server.RequestHandlerClass=Handler
