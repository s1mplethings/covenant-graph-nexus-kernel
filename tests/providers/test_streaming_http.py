"""Purely local HTTP fixture: checks SSE handling over real socket, no vendor calls."""
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, ProxyHandler, build_opener
import threading
import time
import unittest

MODULE_PATH = Path(__file__).resolve().parents[2] / "cgkn/providers/streaming_sse.py"
spec = importlib.util.spec_from_file_location("cgkn_sse_http", MODULE_PATH)
sse = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = sse
spec.loader.exec_module(sse)


def send_event(h, data):
    h.wfile.write(b"data: " + json.dumps(data).encode() + b"\n\n")
    h.wfile.flush()


class MockChatStream(BaseHTTPRequestHandler):
    qwen_started = threading.Event()
    qwen_release = threading.Event()
    received = []

    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        doc = json.loads(self.rfile.read(length).decode())
        type(self).received.append(doc)
        if not doc.get("stream") or not doc.get("stream_options", {}).get("include_usage"):
            self.send_error(400)
            return
        model = doc.get("model")
        if model == "qwen":
            type(self).qwen_started.set()
            type(self).qwen_release.wait(timeout=2)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        send_event(self, {"id": f"id-{model}", "model": model, "choices": [{"index": 0, "delta": {"content": '{"ok":true}'}, "finish_reason": None}]})
        send_event(self, {"id": f"id-{model}", "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 3}})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class TestHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockChatStream)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(2)

    def send(self, model):
        payload=sse.configure_streamed_chat_request({"model":model,"messages":[{"role":"user", "content":"offline fixture"}]})
        req=Request(f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions",
                    data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"},method="POST")
        with build_opener(ProxyHandler({})).open(req,timeout=3) as response:
            return sse.read_sse_response(response)

    def test_parallel_provider_streams_do_not_block_one_another(self):
        MockChatStream.received.clear();MockChatStream.qwen_release.clear();MockChatStream.qwen_started.clear()
        qwen=[]
        worker=threading.Thread(target=lambda: qwen.append(self.send("qwen")))
        worker.start()
        self.assertTrue(MockChatStream.qwen_started.wait(1))
        before=time.monotonic()
        deepseek=self.send("deepseek")
        self.assertLess(time.monotonic()-before, 1)
        self.assertEqual(deepseek.text, '{"ok":true}')
        MockChatStream.qwen_release.set()
        worker.join(2)
        self.assertEqual(len(qwen),1)
        self.assertEqual(qwen[0].request_id,"id-qwen")
        self.assertEqual(len(MockChatStream.received),2)
        self.assertTrue(all(row['stream_options']['include_usage'] for row in MockChatStream.received))


if __name__ == "__main__":
    unittest.main()
