"""Explicit immutable HTTP routes for the trusted Provider side, never tool sandboxes.

No transport retries. The existing budget-owning caller decides new attempts.
Only phase names, host names and counts enter trace records, never headers/body.
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import io
import json
import threading
import time
import ssl
import socket
from .streaming_sse import MeaningfulProgressWatchdog, StreamError
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import httpx
import contextvars
REQUEST_CONTEXT=contextvars.ContextVar('cgkn_network_request',default={})
from .network_health import Circuits
from .progress_io import install as install_progress_io, READ_CHECK


@dataclasses.dataclass(frozen=True)
class Route:
    route_id: str
    proxy_url: str | None
    connect: float = 15
    read: float = 90
    write: float = 30
    pool: float = 10
    deadline: float = 120  # bounded non-streaming GET/legacy operation only
    fallback: str | None = None
    node: str | None = None
    fault_domain: str | None = None
    interface_index: int | None = None
    local_address: str | None = None
    dns_servers: tuple[str,...] = ()
    allowed_hosts: tuple[str,...] = ()
    interface_guid: str | None = None
    first_response: float = 180
    progress: float = 120
    queue: float = 1

    def __post_init__(self):
        if not self.route_id or min(self.connect, self.read, self.write, self.pool, self.deadline) <= 0:
            raise ValueError('INVALID_ROUTE')
        if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not 0<v<=600 for v in (self.queue,self.first_response,self.progress)):
            raise ValueError('INVALID_STREAM_TIMEOUT')
        if self.proxy_url and urlsplit(self.proxy_url).scheme not in ('http', 'https'):
            raise ValueError('UNSUPPORTED_PROXY_PROTOCOL')
        if self.interface_index and (self.proxy_url or not self.local_address or not self.dns_servers or not self.allowed_hosts):
            raise ValueError('INVALID_PHYSICAL_DIRECT_ROUTE')


class Response(io.BytesIO):
    def __init__(self, content, headers, status=200):
        super().__init__(content)
        self.headers = headers
        self.status = status

    def getcode(self):return self.status


class StreamingResponse:
    """Bounded line reader over the already selected httpx response/pool."""
    def __init__(self,response,check):
        self.response=response
        self.status=response.status_code;self.headers=response.headers
        self.chunks=iter(response.iter_bytes());self.buffer=bytearray();self.check=check
    def readline(self,limit):
        while True:
            self.check()
            end=self.buffer.find(b'\n')
            if end>=0 or len(self.buffer)>=limit:
                n=min(end+1 if end>=0 else len(self.buffer),limit)
                value=bytes(self.buffer[:n]);del self.buffer[:n];return value
            try:chunk=next(self.chunks)
            except StopIteration:
                value=bytes(self.buffer);self.buffer.clear();return value
            self.check()
            if len(chunk)>16*1024*1024:raise RouteFailure('RESPONSE_TOO_LARGE',submitted=True,partial=True,retryable=False)
            self.buffer.extend(chunk)
    def __enter__(self):return self
    def __exit__(self,*args):pass  # enclosing httpx context owns the connection
    def close(self):
        # A terminal SSE event can consume the last Content-Length bytes before
        # httpx's iterator observes EOF. Finish that already-buffered boundary so
        # the provider's keep-alive connection is returned to its own pool.
        # Never drain an unbounded/chunked body after DONE or wait for more data.
        length=self.headers.get('content-length','')
        if length.isdigit() and self.response.num_bytes_downloaded == int(length):
            next(self.chunks,None)
        close=getattr(self.chunks,'close',None)
        if close:close()


class RouteFailure(URLError):
    def __init__(self, kind, *, submitted, partial, retryable):
        super().__init__(kind)
        self.kind, self.submitted, self.partial, self.retryable = kind, submitted, partial, retryable


def classify_failure(exc, phase):
    """Return bounded diagnostics, never exception text (which can contain secrets)."""
    direct_reasons={'DIRECT_DNS_FAILED','DIRECT_ADAPTER_REVALIDATION_FAILED',
        'DIRECT_BINDING_CHANGED_RESTART_GATEWAY','DIRECT_ENDPOINT_NOT_ALLOWED','DIRECT_INTERFACE_MISMATCH'}
    if isinstance(exc,httpx.ConnectError) and str(exc) in direct_reasons:return str(exc)
    cause = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return 'TLS_CERTIFICATE_FAILED'
        cause = cause.__cause__
    if 'start_tls' in phase:
        return 'TLS_TIMEOUT' if isinstance(exc, httpx.TimeoutException) else 'TLS_HANDSHAKE_FAILED'
    if isinstance(exc, httpx.ProxyError): return 'PROXY_TUNNEL_FAILED'
    if 'connect_tcp' in phase or isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return 'TCP_TIMEOUT' if isinstance(exc, httpx.ConnectTimeout) else 'TCP_CONNECT_FAILED'
    if isinstance(exc, httpx.PoolTimeout): return 'LOCAL_POOL_TIMEOUT'
    if isinstance(exc, httpx.TimeoutException): return 'REQUEST_TIMEOUT'
    if isinstance(exc, httpx.RemoteProtocolError): return 'REMOTE_PROTOCOL_FAILED'
    return type(exc).__name__


class NetworkClients:
    def __init__(self, routes, bindings, *, version, transports=None, log=None, health=None, disabled_providers=(), provider_parallelism=1):
        if provider_parallelism not in (1,2): raise ValueError("provider parallelism must be 1 or 2")
        self.routes = dict(routes)
        self.bindings = dict(bindings)
        self.version = version
        self.disabled_providers=frozenset(disabled_providers)
        self.health = health or Circuits()
        self.log = log or (lambda event: None)
        self.lock = threading.Lock()
        self.shutdown_event = threading.Event()
        self.active_abort = set()
        self.executors = {provider:concurrent.futures.ThreadPoolExecutor(max_workers=provider_parallelism,thread_name_prefix='cgkn-'+provider)
                          for provider in bindings}
        self.execution_slots = {p:threading.BoundedSemaphore(provider_parallelism) for p in bindings}
        self.clients = {}
        for provider, route_id in self.bindings.items():
            if route_id not in self.routes:
                raise ValueError('UNKNOWN_PROVIDER_ROUTE: ' + provider)
        for route in self.routes.values():
            if route.fallback and route.fallback not in self.routes:
                raise ValueError('UNKNOWN_FALLBACK_ROUTE')
            transport = (transports or {}).get(route.route_id)
            if transport is None:
                if route.interface_index:
                    from .direct_transport import PhysicalDirectTransport
                    transport=PhysicalDirectTransport(interface_index=route.interface_index,local_address=route.local_address,
                        dns_servers=route.dns_servers,allowed_hosts=route.allowed_hosts,
                        log=lambda row,r=route:self.emit({'route_id':r.route_id,**row}),interface_guid=route.interface_guid)
                else:transport = httpx.HTTPTransport(proxy=route.proxy_url, retries=0, verify=True, trust_env=False)
            install_progress_io(transport)
            self.clients[route.route_id] = httpx.Client(transport=transport, trust_env=False, follow_redirects=False)

    @classmethod
    def load(cls, path, **kwargs):
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        if doc.get('trust_env') is not False or doc.get('verify_tls') is not True:
            raise ValueError('EXPLICIT_ENV_AND_TLS_POLICY_REQUIRED')
        routes = {key: Route(route_id=key, **value) for key, value in doc['transport_profiles'].items()}
        for key,route in tuple(routes.items()):
            if route.interface_guid:
                from .windows_interface import resolve_interface
                current=resolve_interface(route.interface_guid)
                routes[key]=dataclasses.replace(route,interface_index=current['index'],local_address=current['source'])
        if doc.get('network_policy')=='domestic':
            domestic=[doc['provider_bindings'].get(p) for p in ('qwen','deepseek')]
            if len(set(domestic))!=2 or any(key not in routes for key in domestic):
                raise ValueError('DOMESTIC_POOLS_MUST_BE_INDEPENDENT')
            if any(routes[key].proxy_url or routes[key].fallback or not routes[key].interface_index for key in domestic):
                raise ValueError('DOMESTIC_REQUIRES_PHYSICAL_DIRECT_NO_PROXY_FALLBACK')
            if doc['provider_bindings'].get('grok') in domestic:
                raise ValueError('GROK_POOL_MUST_BE_ISOLATED')
        if 'health' not in kwargs: kwargs['health']=Circuits(**doc.get('health_policy',{}))
        return cls(routes, doc['provider_bindings'], version=doc['version'],disabled_providers=doc.get('disabled_providers',()), **kwargs)

    def emit(self, row):
        self.log({**{k:v for k,v in REQUEST_CONTEXT.get().items() if not callable(v) and k != 'request_cancel'},**row,
                  'at':time.time(), 'monotonic_ns':time.monotonic_ns(), 'clock_pid':__import__('os').getpid()})

    def opener(self, provider, *, logical_id, attempt_id, deadline=None, cancel=None,
               route_id=None, late_usage=None, outcome=None, consume=None, watchdog=None):
        if provider in self.disabled_providers:
            def disabled(req,timeout=None):
                if outcome is not None:outcome.update(kind='ProviderDisabled',submitted=False,retryable=False)
                raise RouteFailure('ProviderDisabled',submitted=False,partial=False,retryable=False)
            return disabled
        route_id = route_id or self.bindings[provider]
        visited = set()
        while not self.health.available(provider,route_id):
            visited.add(route_id)
            fallback = self.routes[route_id].fallback
            if not fallback or fallback in visited:
                def unavailable(req,timeout=None):
                    if outcome is not None: outcome.update(kind='NetworkUnavailable',submitted=False,retryable=False)
                    raise RouteFailure('NetworkUnavailable',submitted=False,partial=False,retryable=False)
                return unavailable
            route_id = fallback
        route = self.routes[route_id]  # no implicit direct/system route
        deadline = None if consume else (deadline if deadline is not None else time.monotonic() + route.deadline)
        watchdog = watchdog or (MeaningfulProgressWatchdog(initial_timeout=route.first_response,idle_timeout=route.progress) if consume else None)
        progress_callback = REQUEST_CONTEXT.get().get('stream_progress')
        cancel = cancel or threading.Event()
        outcome = outcome if outcome is not None else {}

        def open_request(req, timeout=None):
            outcome.update(route_id=route_id,node=route.node,fault_domain=route.fault_domain)
            host = urlsplit(req.full_url).hostname
            context = dict(**{k:v for k,v in REQUEST_CONTEXT.get().items() if k in ('client_request_identity','client_attempt_id','client_call_key','client_run_id','client_job_id','client_call_id')},
                           provider=provider, endpoint_host=host, route_id=route_id,
                           config_version=self.version, logical_id=logical_id, attempt_id=attempt_id)
            state = {'submitted': False, 'partial': False, 'phase': 'queued', 'tunnel': False}
            expired = threading.Event()
            started = time.monotonic()

            sockets = []
            failure = [None]
            def abort_io():
                for sock in tuple(sockets):
                    try:sock.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
            def check():
                kind = failure[0]
                if self.shutdown_event.is_set():kind = 'GATEWAY_SHUTDOWN'
                elif cancel.is_set():kind = 'USER_CANCELLED'
                elif deadline is not None and time.monotonic() >= deadline:kind = 'NON_GENERATION_DEADLINE'
                if kind is None and watchdog:
                    try:watchdog.check()
                    except StreamError as exc:kind = exc.code
                if kind:
                    failure[0]=kind
                    raise RouteFailure(kind,submitted=state['submitted'],partial=state['partial'],retryable=False)

            def trace(name, info):
                # Never throw from failure/close callbacks during iterator cleanup.
                if name.endswith('.started') and 'response_closed' not in name:check()
                state['phase'] = name
                value=info.get('return_value')
                if hasattr(value,'get_extra_info'):
                    sock=value.get_extra_info('socket')
                    if sock and sock not in sockets:sockets.append(sock)
                traced_request = info.get('request')
                if 'send_request_headers.started' in name:
                    state['tunnel'] = getattr(traced_request, 'method', None) == b'CONNECT'
                if ('send_request_headers.started' in name or 'send_request_body' in name) and not state['tunnel']:
                    state['submitted'] = True
                    if watchdog and not watchdog.snapshot()['submitted']:
                        watchdog.submitted()
                        self.emit({**context,'phase':'provider_submitted','meaningful_events':0})
                        if progress_callback:progress_callback(dict(phase='submitted',meaningful_events=0,age=0,initial_timeout=route.first_response,idle_timeout=route.progress))
                if 'start_tls.complete' in name:
                    state['tunnel'] = False
                self.emit({**context, 'phase': name, 'elapsed': time.monotonic()-started})

            def perform():
                token=REQUEST_CONTEXT.set(context)
                read_token=READ_CHECK.set(check if consume else None)
                try:
                    check()
                    remaining = max(.001, deadline-time.monotonic()) if deadline is not None else float('inf')
                    limits = httpx.Timeout(connect=min(route.connect, remaining), read=(max(route.first_response,route.progress)+5 if consume else min(route.read, remaining)),
                                           write=min(route.write, remaining), pool=min(route.pool, remaining))
                    self.emit({**context,'phase':'transport_begin','remaining_deadline':remaining if deadline is not None else None,
                        'timeouts':dict(connect=limits.connect,read=limits.read,write=limits.write,pool=limits.pool,
                            first_response=route.first_response or route.read,progress=route.progress or route.read,
                            queue=route.queue,total_remaining=remaining if deadline is not None else None)})
                    with self.clients[route_id].stream(req.get_method(), req.full_url, content=req.data,
                            headers=dict(req.header_items()), timeout=limits, extensions={'trace': trace}) as response:
                        stream_socket=response.extensions.get('network_stream')
                        sock=stream_socket.get_extra_info('socket') if stream_socket else None
                        if sock and sock not in sockets:sockets.append(sock)
                        state['submitted'] = True
                        state['upstream_http_status']=response.status_code
                        if progress_callback:progress_callback(dict(phase='upstream_headers',upstream_http_status=response.status_code))
                        upstream_id=response.headers.get('x-request-id') or response.headers.get('request-id') or ''
                        # Identifiers only, never arbitrary headers or exception text.
                        safe_id=''.join(c for c in upstream_id[:200] if c.isalnum() or c in '-_.:')
                        self.emit({**context,'phase':'upstream_headers','upstream_http_status':response.status_code,
                            'upstream_request_id':safe_id})
                        if consume and response.status_code==200:
                            state['partial']=True
                            stream=StreamingResponse(response,check)
                            try:result=consume(stream)
                            finally:stream.close()
                            check()
                            self.health.record(provider,route_id,True)
                            return result
                        chunks = []
                        size = 0
                        for chunk in response.iter_bytes():
                            if not chunks:self.emit({**context,'phase':'first_response_content','bytes':len(chunk)})
                            state['partial'] = True
                            chunks.append(chunk)
                            size += len(chunk)
                            if size > 16*1024*1024:
                                raise RouteFailure('RESPONSE_TOO_LARGE', submitted=True, partial=True, retryable=False)
                            if expired.is_set() or cancel.is_set() or (deadline is not None and time.monotonic() >= deadline):
                                callback = late_usage or outcome.get('late_usage_callback')
                                if callback and str(size) == response.headers.get('content-length'):
                                    try: callback(json.loads(b''.join(chunks)).get('usage'))
                                    except (ValueError, AttributeError): pass
                            check()
                        raw = b''.join(chunks)
                        self.emit({**context,'phase':'response_body_complete','bytes':len(raw)})
                        self.health.record(provider,route_id,True)
                        if expired.is_set() or cancel.is_set() or (deadline is not None and time.monotonic() >= deadline):
                            callback = late_usage or outcome.get("late_usage_callback")
                            if callback:
                                try: callback(json.loads(raw).get('usage'))
                                except (ValueError, AttributeError): pass
                            check()
                        if response.status_code >= 400:
                            outcome.update(kind='HTTP_'+str(response.status_code), retryable=False, submitted=True)
                            raise HTTPError(req.full_url, response.status_code, 'HTTP status', response.headers, io.BytesIO(raw))
                        if 300 <= response.status_code < 400:
                            raise RouteFailure('REDIRECT_REFUSED', submitted=True, partial=True, retryable=False)
                        return Response(raw, response.headers,response.status_code)
                except httpx.HTTPError as exc:
                    check()
                    if not isinstance(exc,httpx.PoolTimeout): self.health.record(provider,route_id,False)
                    if not state['tunnel'] and isinstance(exc,(httpx.ReadError,httpx.ReadTimeout,httpx.WriteError,httpx.WriteTimeout,httpx.RemoteProtocolError)):
                        state["submitted"]=True
                    kind = classify_failure(exc, state['phase'])
                    chain=[];cause=exc
                    while cause is not None and len(chain)<8:
                        chain.append(type(cause).__name__);cause=cause.__cause__ or cause.__context__
                    self.emit({**context,'phase':'transport_failure','kind':kind,'exception_types':chain,
                        'last_transport_phase':state['phase'],'submitted':state['submitted'],'partial':state['partial']})
                    retryable = not state['submitted'] and not state['partial'] and kind not in ('TLS_CERTIFICATE_FAILED','LOCAL_POOL_TIMEOUT')
                    raise RouteFailure(kind, submitted=state['submitted'], partial=state['partial'], retryable=retryable) from None
                finally:
                    with self.lock:self.active_abort.discard(abort_io)
                    self.health.release(provider,route_id)
                    self.execution_slots[provider].release()
                    if watchdog:self.emit({**context,'phase':'progress_final',**watchdog.snapshot()})
                    self.emit({**context, **state, 'last_transport_phase':state['phase'], 'phase': 'attempt_end', 'elapsed': time.monotonic()-started,
                               'expired': expired.is_set(), 'cancelled': cancel.is_set()})
                    READ_CHECK.reset(read_token)
                    REQUEST_CONTEXT.reset(token)

            check()
            queue_until=time.monotonic()+route.queue
            try:
                while True:
                    check()
                    remaining_queue=queue_until-time.monotonic()
                    if remaining_queue<=0:
                        raise RouteFailure('PROVIDER_QUEUE_TIMEOUT',submitted=False,partial=False,retryable=False)
                    if self.execution_slots[provider].acquire(timeout=min(.025,remaining_queue)):
                        try:check()
                        except BaseException:
                            self.execution_slots[provider].release()
                            raise
                        break
            except RouteFailure as exc:
                outcome.update(kind=exc.kind,submitted=False,partial=False,retryable=False)
                raise
            if not self.health.reserve(provider,route_id):
                self.execution_slots[provider].release()
                outcome.update(kind='NetworkUnavailable',submitted=False,retryable=False)
                raise RouteFailure('NetworkUnavailable',submitted=False,partial=False,retryable=False)
            with self.lock:self.active_abort.add(abort_io)
            try:future = self.executors[provider].submit(perform)
            except RuntimeError:
                self.health.release(provider,route_id)
                self.execution_slots[provider].release()
                with self.lock:self.active_abort.discard(abort_io)
                raise RouteFailure('GATEWAY_SHUTDOWN',submitted=False,partial=False,retryable=False) from None
            try:
                while True:
                    check()
                    try:
                        result = future.result(timeout=.05)
                        check()
                        return result
                    except concurrent.futures.TimeoutError:
                        if future.done(): raise
            except RouteFailure as exc:
                expired.set()
                abort_io()
                if future.cancel():
                    self.health.release(provider,route_id)
                    self.execution_slots[provider].release()
                    with self.lock:self.active_abort.discard(abort_io)
                outcome.update(kind=exc.kind, retryable=exc.retryable, submitted=exc.submitted, partial=exc.partial)
                raise
        return open_request

    def close(self):
        self.shutdown_event.set()
        with self.lock:aborts=tuple(self.active_abort)
        for abort in aborts:abort()
        for executor in self.executors.values():executor.shutdown(wait=True, cancel_futures=True)
        for client in self.clients.values():
            client.close()
