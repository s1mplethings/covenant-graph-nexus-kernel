from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from cgkn_provider_lab.adapters import OpenAIChatAdapter
from cgkn_provider_lab.models import ComparisonOptions, ProviderConfig


class Handler(BaseHTTPRequestHandler):
    request_payload = None
    authorization = None

    def do_POST(self):  # noqa: N802
        length = int(self.headers["Content-Length"])
        type(self).request_payload = json.loads(self.rfile.read(length))
        type(self).authorization = self.headers.get("Authorization")
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": "answer",
                            "reasoning_content": "reasoning",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-request-id", "request-1")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def test_openai_adapter_calls_compatible_endpoint() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = ProviderConfig(
            provider_id="local",
            display_name="Local",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            model="model-a",
            secret_backend="session",
            secret_ref="local",
        )
        result = OpenAIChatAdapter().invoke(
            provider,
            "test-secret",
            "hello",
            ComparisonOptions(temperature=0.1, max_tokens=9),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result.status == "ok"
    assert result.text == "answer"
    assert result.reasoning == "reasoning"
    assert result.total_tokens == 5
    assert result.request_id == "request-1"
    assert Handler.authorization == "Bearer test-secret"
    assert Handler.request_payload["model"] == "model-a"
    assert Handler.request_payload["messages"][-1]["content"] == "hello"
