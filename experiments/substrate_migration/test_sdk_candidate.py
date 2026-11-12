"""Real loopback POST counting for the optional official SDK experiment."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import openai
import pytest


@pytest.fixture
def endpoint():
    class Handler(BaseHTTPRequestHandler):
        count = 0
        status = 200
        def log_message(self, *args):
            pass
        def do_POST(self):
            type(self).count += 1
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(type(self).status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('x-request-id', 'offline-request')
            self.end_headers()
            assert body['model'] == 'offline'
            self.wfile.write(json.dumps({'id': 'offline', 'object': 'chat.completion', 'created': 0,
                'model': 'offline', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': 3}}).encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('status', [200, 400, 401, 429, 500])
def test_sdk_one_post_without_retry(endpoint, status):
    url, handler = endpoint
    handler.status = status
    with openai.OpenAI(api_key='offline-fixture', base_url=url, max_retries=0,
                       http_client=httpx.Client(trust_env=False), timeout=2) as client:
        if status == 200:
            result = client.chat.completions.create(model='offline', messages=[{'role': 'user', 'content': 'fixture'}])
            assert result._request_id == 'offline-request'
            assert result.usage.total_tokens == 3
            assert json.loads(result.choices[0].message.content) == {'ok': True}
        else:
            with pytest.raises(openai.APIStatusError) as caught:
                client.chat.completions.create(model='offline', messages=[{'role': 'user', 'content': 'fixture'}])
            assert caught.value.status_code == status
    assert handler.count == 1


def test_sdk_decoder_does_not_replace_fail_closed_stream_contract():
    from openai._streaming import SSEDecoder
    from cgkn.providers.streaming_sse import StreamError, StreamLimits, sse_events

    incomplete = [b'data: {"delta":"partial"}\n']
    with pytest.raises(StreamError, match='stream_unterminated_event'):
        list(sse_events(incomplete, limits=StreamLimits()))
    # This is an intentionally measured incompatibility, not SDK qualification.
    assert list(SSEDecoder().iter_bytes(iter(incomplete))) == []


def test_sdk_and_current_parser_agree_on_complete_utf8_event():
    from openai._streaming import SSEDecoder
    from cgkn.providers.streaming_sse import StreamLimits, sse_events

    payload = json.dumps({'choices': [{'delta': {'content': '中文', 'tool_calls': [
        {'index': 0, 'function': {'arguments': '{"path":"文件"}'}}
    ]}}]}, ensure_ascii=False)
    wire = ('data: ' + payload + '\n\n').encode('utf-8')
    chunks = [wire[index:index + 1] for index in range(len(wire))]
    sdk = list(SSEDecoder().iter_bytes(iter(chunks)))
    current = list(sse_events(wire.splitlines(keepends=True), limits=StreamLimits()))
    assert len(sdk) == len(current) == 1
    assert sdk[0].data == current[0].data == payload
