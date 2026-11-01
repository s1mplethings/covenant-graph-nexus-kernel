"""Real loopback sockets: no model calls, isolated progress-only downstream."""
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import build_opener, ProxyHandler

import pytest

from cgkn.providers.gateway_stream import PROTOCOL, receive
from cgkn.providers.streaming_sse import StreamError


@contextmanager
def channel(script):
    done=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','text/event-stream')
            self.end_headers();sequence=0
            def send(event,**body):
                nonlocal sequence
                sequence+=1
                row=dict(protocol=PROTOCOL,request_identity='request',session_id='session',sequence=sequence,**body)
                self.wfile.write(('event: '+event+'\ndata: '+json.dumps(row)+'\n\n').encode());self.wfile.flush()
            try:
                send('cgkn.started');script(send,done)
            except (OSError,ValueError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with build_opener(ProxyHandler({})).open('http://127.0.0.1:'+str(server.server_port),timeout=1) as response:
            yield response
    finally:
        done.set();server.shutdown();server.server_close();thread.join(1)


def submitted(send):
    send('cgkn.progress',progress=dict(phase='submitted',initial_timeout=.16,idle_timeout=.12,age=0,meaningful_events=0))


def test_silent_socket_initial_watchdog_interrupts_blocking_read():
    def script(send,done):submitted(send);done.wait(2)
    with channel(script) as response:
        start=time.monotonic()
        with pytest.raises(StreamError,match='NO_INITIAL_MEANINGFUL_PROGRESS'):
            receive(response,'request',setup_seconds=1)
        assert time.monotonic()-start<.8


def test_silent_socket_idle_watchdog_interrupts_blocking_read():
    def script(send,done):
        submitted(send);send('cgkn.progress',progress=dict(meaningful_events=1));done.wait(2)
    with channel(script) as response:
        with pytest.raises(StreamError,match='NO_MEANINGFUL_PROGRESS'):receive(response,'request',setup_seconds=1)


def test_sustained_progress_outlives_each_idle_period():
    def script(send,done):
        submitted(send)
        for i in range(1,10):
            send('cgkn.progress',progress=dict(meaningful_events=i));time.sleep(.04)
        send('cgkn.completed',response={'complete':True},gateway_http_status=200)
    with channel(script) as response:
        start=time.monotonic()
        assert receive(response,'request',setup_seconds=.2)=={'complete':True}
        assert time.monotonic()-start>.3


def test_duplicate_progress_does_not_refresh_watchdog():
    def script(send,done):
        submitted(send)
        for _ in range(20):
            send('cgkn.progress',progress=dict(meaningful_events=1));time.sleep(.03)
    with channel(script) as response:
        with pytest.raises(StreamError,match='NO_MEANINGFUL_PROGRESS'):receive(response,'request',setup_seconds=1)


def test_connection_status_does_not_start_or_refresh_model_progress():
    def script(send,done):
        submitted(send)
        for _ in range(20):
            send('cgkn.progress',progress=dict(phase='receiving',meaningful_events=0));time.sleep(.03)
    with channel(script) as response:
        with pytest.raises(StreamError,match='NO_INITIAL_MEANINGFUL_PROGRESS'):receive(response,'request',setup_seconds=1)


def test_cancel_interrupts_silent_socket():
    cancellation=threading.Event()
    def script(send,done):
        send('cgkn.progress',progress=dict(phase='submitted',meaningful_events=0))
        time.sleep(.05);cancellation.set();done.wait(2)
    with channel(script) as response:
        with pytest.raises(StreamError,match='USER_CANCELLED'):receive(response,'request',cancel=cancellation)


def test_presubmit_setup_is_independently_bounded():
    def script(send,done):done.wait(2)
    with channel(script) as response:
        with pytest.raises(StreamError,match='GATEWAY_SETUP_TIMEOUT'):receive(response,'request',setup_seconds=.1)


@pytest.mark.parametrize('stamp',[-1,float('nan'),float('inf'),'not-time',True,lambda:time.time()+10])
def test_invalid_or_future_event_time_cannot_extend_progress(stamp):
    import io
    def event(kind,seq,**body):
        row=dict(protocol=PROTOCOL,request_identity='request',session_id='session',sequence=seq,**body)
        return ('event: '+kind+'\ndata: '+json.dumps(row)+'\n\n').encode()
    raw=event('cgkn.started',1)+event('cgkn.progress',2,
        emitted_at_unix=stamp() if callable(stamp) else stamp,
        progress=dict(phase='submitted',meaningful_events=0))
    with pytest.raises(StreamError,match='gateway_progress_(invalid_timestamp|clock_mismatch)'):
        receive(io.BytesIO(raw),'request')


def test_original_submission_age_survives_delayed_delivery():
    import io
    rows=[('cgkn.started',{}),('cgkn.progress',dict(emitted_at_unix=time.time()-1,
        progress=dict(phase='submitted',initial_timeout=.1,idle_timeout=.1,age=0,meaningful_events=0)))]
    raw=b''.join(('event: '+kind+'\ndata: '+json.dumps(dict(protocol=PROTOCOL,request_identity='request',
        session_id='session',sequence=i+1,**body))+'\n\n').encode() for i,(kind,body) in enumerate(rows))
    with pytest.raises(StreamError,match='NO_INITIAL_MEANINGFUL_PROGRESS'):receive(io.BytesIO(raw),'request')


def test_rapid_equal_source_times_keep_order_without_receipt_time_refresh():
    import io
    stamp=time.time()
    rows=[('cgkn.started',{}),('cgkn.progress',dict(emitted_at_unix=stamp,
        progress=dict(phase='submitted',meaningful_events=0)))]
    rows += [('cgkn.progress',dict(emitted_at_unix=stamp,progress=dict(meaningful_events=i))) for i in range(1,100)]
    rows += [('cgkn.completed',dict(response={'ok':True},gateway_http_status=200))]
    raw=b''.join(('event: '+kind+'\ndata: '+json.dumps(dict(protocol=PROTOCOL,request_identity='request',
        session_id='session',sequence=i+1,**body))+'\n\n').encode() for i,(kind,body) in enumerate(rows))
    assert receive(io.BytesIO(raw),'request')=={'ok':True}


def test_explicit_local_observation_retains_original_time_and_expiry():
    from cgkn.providers.streaming_sse import MeaningfulProgressWatchdog
    clock=[10.0]
    dog=MeaningfulProgressWatchdog(initial_timeout=180,idle_timeout=120,clock=lambda:clock[0])
    dog.submitted(observed_at=5.0)
    dog.progress(1,observed_at=5.0)
    clock[0]=15.0
    dog.progress(2,observed_at=5.0)
    assert dog.snapshot()['last_progress_age']==10.0
    with pytest.raises(ValueError,match='INVALID_PROGRESS_ORDER'):dog.progress(3,observed_at=4.0)
    with pytest.raises(ValueError,match='INVALID_PROGRESS_OBSERVATION'):dog.progress(3,observed_at=16.0)
    clock[0]=125.0
    with pytest.raises(StreamError,match='NO_MEANINGFUL_PROGRESS'):dog.progress(3,observed_at=125.0)


def test_wall_clock_quantization_clamps_back_without_reaging_same_source(monkeypatch):
    import io
    from cgkn.providers import gateway_stream
    perf=iter([100.0,100.0005,100.001])
    monkeypatch.setattr(gateway_stream.time,'perf_counter',lambda:next(perf))
    observed=[]
    # Anchor wall call must be 1000.0, subsequent wall calls can advance faster
    # than performance-clock ticks, as observed on the Windows host.
    wall_calls=[0]
    def wall():
        wall_calls[0]+=1
        return 1000.0 if wall_calls[0]==1 else 1000.01
    monkeypatch.setattr(gateway_stream.time,'time',wall)
    rows=[('cgkn.started',{}),('cgkn.progress',dict(emitted_at_unix=1000.001,
        progress=dict(phase='submitted',meaningful_events=0))),
        ('cgkn.progress',dict(emitted_at_unix=1000.001,progress=dict(meaningful_events=1))),
        ('cgkn.progress',dict(emitted_at_unix=1000.002,progress=dict(meaningful_events=2))),
        ('cgkn.completed',dict(response={'ok':True},gateway_http_status=200))]
    raw=b''.join(('event: '+kind+'\ndata: '+json.dumps(dict(protocol=PROTOCOL,request_identity='request',
        session_id='session',sequence=i+1,**body))+'\n\n').encode() for i,(kind,body) in enumerate(rows))
    assert gateway_stream._receive(io.BytesIO(raw),'request',
        on_progress=lambda row,observed_at:observed.append(observed_at))=={'ok':True}
    assert observed==[100.0005,100.0005,100.001]


def test_source_time_regression_never_refreshes_anchor():
    import io
    stamp=time.time()-1
    rows=[('cgkn.started',{}),('cgkn.progress',dict(emitted_at_unix=stamp,
        progress=dict(phase='submitted',meaningful_events=0))),
        ('cgkn.progress',dict(emitted_at_unix=stamp-.1,progress=dict(meaningful_events=1)))]
    raw=b''.join(('event: '+kind+'\ndata: '+json.dumps(dict(protocol=PROTOCOL,request_identity='request',
        session_id='session',sequence=i+1,**body))+'\n\n').encode() for i,(kind,body) in enumerate(rows))
    observed=[]
    from cgkn.providers import gateway_stream
    with pytest.raises(StreamError,match='gateway_stream_eof_without_complete'):
        gateway_stream._receive(io.BytesIO(raw),'request',on_progress=lambda row,observed_at:observed.append(observed_at))
    assert len(observed)==2 and observed[0]==observed[1]


@pytest.mark.parametrize('offset',[.001,.015,-.015])
def test_bounded_cross_process_clock_quantization(offset,monkeypatch):
    import io
    from cgkn.providers import gateway_stream
    monkeypatch.setattr(gateway_stream.time,'time',lambda:1000.0)
    monkeypatch.setattr(gateway_stream.time,'perf_counter',lambda:100.0)
    observed=[]
    rows=[('cgkn.started',{}),('cgkn.progress',dict(emitted_at_unix=1000.0,progress=dict(phase='submitted',meaningful_events=0))),
          ('cgkn.progress',dict(emitted_at_unix=1000.0+offset,progress=dict(meaningful_events=1))),
          ('cgkn.completed',dict(response={'ok':True},gateway_http_status=200))]
    raw=b''.join(('event: '+kind+'\ndata: '+json.dumps(dict(protocol=PROTOCOL,request_identity='request',session_id='session',sequence=i+1,**body))+'\n\n').encode() for i,(kind,body) in enumerate(rows))
    assert gateway_stream._receive(io.BytesIO(raw),'request',on_progress=lambda row,observed_at:observed.append(observed_at))=={'ok':True}
    assert observed==[100.0,100.0]  # no artificial idle-time extension


def test_nonmeaningful_status_does_not_change_source_order():
    import io
    from cgkn.providers import gateway_stream
    stamp=time.time()-.01;observed=[]
    rows=[('cgkn.started',{}),('cgkn.progress',dict(emitted_at_unix=stamp,progress=dict(phase='submitted',meaningful_events=0))),
          ('cgkn.progress',dict(emitted_at_unix=stamp-1,progress=dict(phase='progress',meaningful_events=0,age=1))),
          ('cgkn.progress',dict(emitted_at_unix=stamp,progress=dict(meaningful_events=1))),
          ('cgkn.completed',dict(response={'ok':True},gateway_http_status=200))]
    raw=b''.join(('event: '+kind+'\ndata: '+json.dumps(dict(protocol=PROTOCOL,request_identity='request',session_id='session',sequence=i+1,**body))+'\n\n').encode() for i,(kind,body) in enumerate(rows))
    assert gateway_stream._receive(io.BytesIO(raw),'request',on_progress=lambda row,observed_at:observed.append(observed_at))=={'ok':True}
    assert observed[1] is None and observed[0]==observed[2]
