"""Versioned SSE progress channel on the authenticated formal POST endpoint.

Only the final, identity-bound complete event carries an admissible response.
Progress has counts, never hidden reasoning or credentials. No retries here.
"""
import hashlib
import json
import threading
import time
import socket
import select
import math
from .network_transport import REQUEST_CONTEXT
from .streaming_sse import StreamError,StreamLimits,sse_events,iter_response_lines,MeaningfulProgressWatchdog

PROTOCOL='cgkn.model-stream.v1'


def serve(handler,payload,mode,gateway,session_id):
    identity='sha256:'+hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    sequence=0;lock=threading.Lock();closed=threading.Event()
    handler.connection.settimeout(5)  # independent bounded downstream write, not generation duration
    request_cancel=threading.Event()
    def watch_peer():
        while not closed.wait(.05):
            try:
                readable,_,_=select.select([handler.connection],[],[],0)
                if readable and handler.connection.recv(1,socket.MSG_PEEK)==b'':
                    request_cancel.set();return
            except (OSError,ValueError):
                if not closed.is_set():request_cancel.set()
                return
    peer=threading.Thread(target=watch_peer,name='cgkn-stream-peer',daemon=True)
    handler.send_response(200)
    handler.send_header('Content-Type','text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control','no-store')
    handler.send_header('Connection','close')
    handler.end_headers();handler.wfile.flush();handler.close_connection=True
    peer.start()
    def send(kind,body):
        nonlocal sequence
        with lock:
            if closed.is_set():raise StreamError('stream_client_disconnected')
            sequence+=1
            data=dict(protocol=PROTOCOL,request_identity=identity,session_id=session_id,sequence=sequence,emitted_at_unix=time.time(),**body)
            raw=('event: '+kind+'\ndata: '+json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n\n').encode()
            try:handler.wfile.write(raw);handler.wfile.flush()
            except OSError:
                closed.set();request_cancel.set();raise StreamError('stream_client_disconnected') from None
    token=REQUEST_CONTEXT.set({**REQUEST_CONTEXT.get(),'stream_progress':lambda row:send('cgkn.progress',dict(progress=row)), 'request_cancel':request_cancel})
    try:
        send('cgkn.started',{})
        status,body=gateway.application.invoke(payload,mode)
        send('cgkn.completed',dict(response=body,gateway_http_status=status))
        gateway.network.emit(dict(phase='local_response_write_completed',gateway_http_status=200))
    except Exception as exc:
        code=getattr(exc,'code','provider_outcome_unknown')
        # Only bounded error identifiers, never raw upstream text.
        if not isinstance(code,str) or not code.replace('_','').isalnum():code='provider_outcome_unknown'
        before_send=code in {'network_unavailable_before_send','provider_request_rejected_before_send','provider_queue_deadline','gateway_busy',
            'model_not_found','concrete_model_not_admitted','unsupported_tool_contract','unsupported_reasoning_contract','invalid_request','provider_credential_unavailable'}
        complete=getattr(exc,'completed_response',None)
        try:send('cgkn.error',dict(error_type=code,gateway_http_status=getattr(exc,'status',502),
            outcome_unknown=not before_send and complete is None,response=complete))
        except (OSError,StreamError):pass
    finally:
        closed.set();peer.join(timeout=.2);REQUEST_CONTEXT.reset(token)


def receive(response,identity,*,initial_seconds=180,idle_seconds=120,setup_seconds=60,
            expected_session=None,on_progress=None,cancel=None,on_started=None):
    """Consume indefinitely while real model progress continues; interrupt silent I/O.

    Setup is independently bounded until the authenticated Gateway reports the
    actual Provider submission. No generation elapsed-time limit exists.
    """
    if not isinstance(setup_seconds,(int,float)) or isinstance(setup_seconds,bool) or not math.isfinite(setup_seconds) or setup_seconds<=0:
        raise ValueError('INVALID_SETUP_TIMEOUT')
    sock=getattr(getattr(getattr(response,'fp',None),'raw',None),'_sock',None)
    state={'watchdog':MeaningfulProgressWatchdog(initial_seconds,idle_seconds,clock=time.perf_counter)}
    finished=threading.Event();failure=[];started_at=time.monotonic()
    def read_bound(watchdog):
        # urllib's buffered SocketIO cannot be reused after a socket timeout,
        # and Windows shutdown does not reliably wake its pending recv.
        # Use nonblocking reads with bounded select polls instead.
        if sock:sock.setblocking(False)
    read_bound(state['watchdog'])
    def check():
        if cancel is not None and cancel.is_set():raise StreamError('USER_CANCELLED')
        watchdog=state['watchdog']
        if not watchdog.snapshot()['submitted'] and time.monotonic()-started_at>=setup_seconds:
            raise StreamError('GATEWAY_SETUP_TIMEOUT')
        watchdog.check()
    def supervise():
        while not finished.wait(.025):
            try:check()
            except StreamError as exc:
                failure.append(exc)
                if sock:
                    try:sock.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                return
    monitor=threading.Thread(target=supervise,name='cgkn-stream-progress',daemon=True);monitor.start()
    def progress(row,*,observed_at=None):
        if not isinstance(row,dict):raise StreamError('gateway_progress_invalid')
        watchdog=state['watchdog']
        if row.get('phase')=='submitted':
            if watchdog.snapshot()['submitted']:raise StreamError('gateway_duplicate_submission')
            try:
                watchdog=MeaningfulProgressWatchdog(row.get('initial_timeout',initial_seconds),row.get('idle_timeout',idle_seconds),clock=time.perf_counter)
                watchdog.submitted(age=row.get('age',0) if observed_at is None else 0,observed_at=observed_at);state['watchdog']=watchdog
                read_bound(watchdog)
            except ValueError:raise StreamError('gateway_progress_invalid') from None
        elif row.get('meaningful_events',0):
            try:watchdog.progress(row['meaningful_events'],age=row.get('age',0) if observed_at is None else 0,observed_at=observed_at)
            except (ValueError,TypeError):raise StreamError('gateway_progress_invalid') from None
        check()
        if on_progress:on_progress(row)
    try:
        reader=_InterruptibleGatewayLines(response,sock,check) if sock else response
        result=_receive(reader,identity,expected_session=expected_session,on_progress=progress,check=check,on_started=on_started)
        if failure:raise failure[0]
        check()
        return result
    except Exception:
        if failure:raise failure[0] from None
        raise
    finally:
        finished.set();monitor.join(timeout=.2)


class _InterruptibleGatewayLines:
    """Bounded reader for our HTTP/1.x unchunked loopback SSE protocol.

    Drain urllib's already-buffered body bytes before polling the socket; never
    discard content coalesced with response headers. No timed-out file object is
    reused, and no read can hide the progress/cancellation checks.
    """
    def __init__(self,response,sock,check):
        if response.headers.get('Transfer-Encoding'):
            raise StreamError('gateway_stream_unsupported_transfer_encoding')
        self.fp=response.fp;self.sock=sock;self.check=check
        self.buffer=bytearray();self.eof=False
    def readline(self,limit):
        while True:
            self.check()
            end=self.buffer.find(b'\n')
            if end>=0 or len(self.buffer)>=limit or self.eof:
                n=min(end+1 if end>=0 else len(self.buffer),limit)
                value=bytes(self.buffer[:n]);del self.buffer[:n];return value
            chunk=self.fp.read1(min(65536,limit))
            if chunk:
                self.buffer.extend(chunk);continue
            readable,_,_=select.select([self.sock],[],[],.025)
            self.check()
            if readable:
                chunk=self.fp.read1(min(65536,limit))
                if chunk:self.buffer.extend(chunk)
                else:self.eof=True


def _receive(response,identity,*,expected_session=None,on_progress=None,check=lambda:None,on_started=None):
    """Read progress immediately; return only a complete terminal response."""
    limits=StreamLimits(max_line_bytes=4*1024*1024,max_event_bytes=4*1024*1024)
    # One local clock mapping per response. Repeated clock()-age conversions can
    # reorder rapid events on Windows' coarse monotonic ticks. Source wall time
    # is mapped once into our high-resolution local clock domain instead.
    local_anchor=time.perf_counter();wall_anchor=time.time()
    last_source_time=None;last_observed_at=None
    session=None;sequence=0;started=False
    for event in sse_events(iter_response_lines(response,limits),limits=limits):
        check()
        try:doc=json.loads(event.data)
        except ValueError:raise StreamError('gateway_stream_invalid_json') from None
        if not isinstance(doc,dict) or doc.get('protocol')!=PROTOCOL or doc.get('request_identity')!=identity:
            raise StreamError('gateway_stream_identity_mismatch')
        if doc.get('sequence')!=sequence+1:raise StreamError('gateway_stream_sequence_mismatch')
        sequence+=1
        if session is None:session=doc.get('session_id')
        if not session or session!=doc.get('session_id') or (expected_session and session!=expected_session):
            raise StreamError('gateway_stream_session_mismatch')
        if event.event=='cgkn.started':
            if started:raise StreamError('gateway_stream_duplicate_start')
            started=True
            if on_started:on_started({'phase':'gateway_started','session_id':session})
        elif not started:raise StreamError('gateway_stream_missing_start')
        elif event.event=='cgkn.progress':
            row=doc.get('progress')
            if not isinstance(row,dict):raise StreamError('gateway_progress_invalid')
            row=dict(row)
            if row.get('phase')!='submitted' and not row.get('meaningful_events',0):
                # Connection/status events carry no model progress and must not
                # participate in progress clock ordering or refresh its anchor.
                if on_progress:on_progress(row,observed_at=None)
                continue
            emitted=doc.get('emitted_at_unix');observed_at=None
            if emitted is not None:
                if isinstance(emitted,bool) or not isinstance(emitted,(int,float)) or not math.isfinite(emitted) or emitted<=0:
                    raise StreamError('gateway_progress_invalid_timestamp')
                age=row.get('age',0)
                if isinstance(age,bool) or not isinstance(age,(int,float)) or not math.isfinite(age) or age<0:
                    raise StreamError('gateway_progress_invalid_age')
                # Loopback Gateway and client share the host wall clock, unlike
                # process monotonic epochs. Preserve source age plus transit.
                transit=time.time()-emitted
                if transit < -.05:raise StreamError('gateway_progress_clock_mismatch_future')
                transit=max(0,transit)
                row['age']=age+transit
                source_time=emitted-age
                # One mapping and one nondecreasing anchor. Delayed/repeated
                # source times retain the old anchor, never reset to receipt.
                # Sequence/identity, not wall-clock ordering, authenticates order.
                if last_source_time is not None and source_time<=last_source_time:
                    observed_at=last_observed_at
                else:
                    observed_at=min(local_anchor+(source_time-wall_anchor),time.perf_counter())
                    if last_observed_at is not None:observed_at=max(last_observed_at,observed_at)
                    last_source_time=source_time;last_observed_at=observed_at
            if on_progress:on_progress(row,observed_at=observed_at)
        elif event.event=='cgkn.error':
            raise StreamError(str(doc.get('error_type','unknown'))[:100],outcome_unknown=doc.get('outcome_unknown') is not False,response=doc.get('response'))
        elif event.event=='cgkn.completed':
            result=doc.get('response')
            if doc.get('gateway_http_status')!=200 or not isinstance(result,dict):raise StreamError('gateway_stream_invalid_terminal')
            return result
        else:raise StreamError('gateway_stream_unknown_event')
    raise StreamError('gateway_stream_eof_without_complete')
