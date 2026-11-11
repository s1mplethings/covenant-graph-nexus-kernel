"""Long queue configuration must not delay cancellation or controlled shutdown."""
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request

import httpx
import pytest

from cgkn.providers.network_transport import NetworkClients,Route,RouteFailure,REQUEST_CONTEXT


@pytest.mark.parametrize('shutdown',[False,True])
def test_transport_queue_cancel_is_prompt_without_submission(shutdown):
    sent=[]
    transport=httpx.MockTransport(lambda req:sent.append(req) or httpx.Response(200,json={}))
    clients=NetworkClients({'direct':Route('direct',None,queue=600)}, {'qwen':'direct'},version='offline',transports={'direct':transport})
    cancel=threading.Event()
    clients.execution_slots['qwen'].acquire()
    outcome={}
    timer=threading.Timer(.05,clients.shutdown_event.set if shutdown else cancel.set)
    timer.start();started=time.monotonic()
    try:
        with pytest.raises(RouteFailure) as caught:
            clients.opener('qwen',logical_id='offline',attempt_id='offline',cancel=cancel,outcome=outcome)(Request('https://fixture.invalid/models'))
        assert caught.value.kind==('GATEWAY_SHUTDOWN' if shutdown else 'USER_CANCELLED')
        assert time.monotonic()-started<.5
        assert outcome['submitted'] is False and sent==[]
    finally:
        timer.join();clients.execution_slots['qwen'].release();clients.close()


@pytest.mark.parametrize('shutdown',[False,True])
def test_gateway_provider_queue_cancel_is_prompt(shutdown):
    from cgkn.providers.domestic_gateway import DomesticGateway
    sys.path.insert(0,str(Path('D:/cgkn-provider-api-lab/src')))
    from cgkn_provider_lab.gateway import GatewayError
    gateway=object.__new__(DomesticGateway)
    gateway.provider_slots={'qwen':threading.BoundedSemaphore(1)}
    gateway.provider_slots['qwen'].acquire()
    events=[]
    gateway.network=SimpleNamespace(shutdown_event=threading.Event(),emit=events.append)
    cancel=threading.Event();token=REQUEST_CONTEXT.set({'request_cancel':cancel})
    timer=threading.Timer(.05,gateway.network.shutdown_event.set if shutdown else cancel.set)
    timer.start();started=time.monotonic()
    try:
        with pytest.raises(GatewayError) as caught:
            with gateway.provider_slot('qwen',timeout=600):pytest.fail('slot must not be entered')
        assert caught.value.code=='provider_request_rejected_before_send'
        assert time.monotonic()-started<.5
        assert events[-1]['reason']==('GATEWAY_SHUTDOWN' if shutdown else 'USER_CANCELLED')
        assert events[-1]['submitted'] is False
    finally:
        timer.join();REQUEST_CONTEXT.reset(token);gateway.provider_slots['qwen'].release()
