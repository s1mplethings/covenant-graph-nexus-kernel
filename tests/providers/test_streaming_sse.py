"""Offline protocol tests; no network, credentials, Gateway or paid generation."""
import io
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "cgkn/providers/streaming_sse.py"
spec = importlib.util.spec_from_file_location("cgkn_streaming_sse", MODULE_PATH)
sse = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = sse
spec.loader.exec_module(sse)


def event(doc, *, name=None):
    body = json.dumps(doc, ensure_ascii=False)
    return ((f"event: {name}\n" if name else "") + "data: " + body + "\n\n").encode("utf-8")


def chunk(text="{}", *, req="cmpl-1", model="qwen3.8-max", finish=None, usage=None):
    value = {"id": req, "model": model, "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]}
    if usage is not None:
        value["usage"] = usage
    return value


def complete_stream(*, parts=None, with_done=True, finish="stop", usage=None):
    if parts is None:
        parts = ['{"ok":', 'true}']
    value = b": keep-alive\n\n"
    for part in parts:
        value += event(chunk(part))
    value += event(chunk("", finish=finish, usage=usage or {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}))
    if with_done:
        value += b"data: [DONE]\n\n"
    return value


class FakeResponse(io.BytesIO):
    def __init__(self, data, *, content_type="text/event-stream; charset=utf-8", status=200):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Type": content_type}


class TestSSE(unittest.TestCase):
    def collect(self, data, **kw):
        return sse.read_sse_response(FakeResponse(data), **kw)

    def error_code(self, data, code, **kw):
        with self.assertRaises(sse.StreamError) as ctx:
            self.collect(data, **kw)
        self.assertEqual(ctx.exception.code, code)

    def test_qwen_success_with_usage_and_heartbeat(self):
        item = self.collect(complete_stream())
        self.assertEqual(item.text, '{"ok":true}')
        self.assertEqual(item.request_id, "cmpl-1")
        self.assertEqual(item.usage["total_tokens"], 13)
        self.assertEqual(item.as_responses("qwen")["status"], "completed")

    def test_deepseek_reasoning_is_not_part_of_business_text(self):
        data = event({"id": "r1", "model": "deepseek-chat", "choices": [{"index": 0, "delta": {"reasoning_content": "internal detail", "content": None}, "finish_reason": None}]})
        data += event({"id": "r1", "model": "deepseek-chat", "choices": [{"index": 0, "delta": {"content": '{"ok":true}'}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
        data += b"data: [DONE]\n\n"
        item = self.collect(data)
        self.assertEqual(item.text, '{"ok":true}')
        self.assertEqual(item.reasoning_chars, len("internal detail"))
        self.assertNotIn("internal detail", json.dumps(item.as_responses()))

    def test_multiline_event_and_crlf(self):
        first = json.dumps(chunk('"ok"')).encode()
        left, right = first.find(b'"choices"'), 0
        # splitting one JSON string across SSE data fields inserts newline;
        # valid JSON with a newline between fields still parses.
        row = first.replace(b', "choices"', b',\n "choices"')
        pivot = row.index(b'\n')
        data = b'data: ' + row[:pivot] + b'\r\ndata: ' + row[pivot+1:] + b'\r\n\r\n'
        data += event(chunk("", finish="stop")) + b'data: [DONE]\n\n'
        self.assertEqual(self.collect(data).text, '"ok"')

    def test_missing_done_is_unknown(self):
        self.error_code(complete_stream(with_done=False), "stream_eof_without_done")

    def test_missing_finish_is_unknown(self):
        data = event(chunk("{}")) + b"data: [DONE]\n\n"
        self.error_code(data, "stream_unknown_finish")

    def test_length_finish_is_not_success(self):
        self.error_code(complete_stream(finish="length"), "stream_output_token_limit")

    def test_tool_calls_require_separate_contract(self):
        val=chunk("{}");val["choices"][0]["delta"]["tool_calls"]=[{"index":0,"id":"a"}]
        self.error_code(event(val)+b"data: [DONE]\n\n", "stream_tool_calls_require_explicit_contract")

    def test_error_event(self):
        self.error_code(event({"error":{"message":"bad","type":"rate_limit"}}), "stream_upstream_error")

    def test_invalid_json(self):
        self.error_code(b"data: {bad}\n\n", "stream_invalid_json")

    def test_missing_event_terminator(self):
        self.error_code(b"data: [DONE]", "stream_unterminated_event")

    def test_inconsistent_ids(self):
        data=event(chunk("{"))+event(chunk("}",req="other"))
        self.error_code(data, "stream_mixed_request_ids")

    def test_non_sse_is_rejected(self):
        with self.assertRaisesRegex(sse.StreamError, "stream_not_sse"):
            sse.read_sse_response(FakeResponse(b"{}",content_type="application/json"))

    def test_bounded_text(self):
        self.error_code(complete_stream(parts=["abcdefgh"]), "stream_text_too_large", limits=sse.StreamLimits(max_text_bytes=5))

    def test_bounded_event(self):
        self.error_code(complete_stream(), "stream_event_too_large", limits=sse.StreamLimits(max_event_bytes=5))

    def test_upstream_response_201_is_not_sse_success(self):
        with self.assertRaisesRegex(sse.StreamError, "stream_http_non_200"):
            sse.read_sse_response(FakeResponse(complete_stream(),status=201))

    def test_no_usage_never_fabricates_usage(self):
        data=event(chunk('{"ok":true}', finish="stop"))+b"data: [DONE]\n\n"
        self.assertEqual(self.collect(data).usage, {})

    def test_usage_nonnegative(self):
        self.error_code(complete_stream(usage={"prompt_tokens": -2}), "stream_invalid_usage")

    def test_prompt_flags(self):
        src = {"model":"qwen", "messages":[{"role":"user","content":"hello"}]}
        out = sse.configure_streamed_chat_request(src)
        self.assertIs(out is src, False)
        self.assertTrue(out["stream"])
        self.assertTrue(out["stream_options"]["include_usage"])
        with self.assertRaisesRegex(sse.StreamError, "stream_explicitly_disabled"):
            sse.configure_streamed_chat_request({"stream":False})

    def test_responses_completed(self):
        data=event({"type":"response.created", "response":{"id":"resp1"}})
        data+=event({"type":"response.output_text.delta", "delta":"{\"ok\":"})
        data+=event({"type":"response.output_text.delta", "delta":"true}"})
        data+=event({"type":"response.completed", "response":{"id":"resp1","model":"qwen", "status":"completed","usage":{"input_tokens":9,"output_tokens":4}}})
        item=self.collect(data, kind="responses")
        self.assertEqual(item.text, '{"ok":true}')
        self.assertEqual(item.usage["input_tokens"],9)

    def test_responses_incomplete_is_unknown(self):
        data=event({"type":"response.output_text.delta", "delta":"{}"})+event({"type":"response.incomplete"})
        self.error_code(data, "stream_response_not_completed", kind="responses")

    def test_responses_missing_terminal(self):
        data=event({"type":"response.output_text.delta", "delta":"{}"})
        self.error_code(data, "stream_eof_without_complete", kind="responses")

    def test_completed_response_saved_atomically_and_not_overwritten(self):
        item=self.collect(complete_stream())
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"results"/"done.json"
            digest=sse.save_completed_response(path, item, model_alias="qwen")
            self.assertTrue(digest.startswith("sha256:"))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["output_text"], item.text)
            with self.assertRaises(FileExistsError):
                sse.save_completed_response(path,item,model_alias="deepseek")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["model"],"qwen")

    def test_progress_metadata_contains_no_text(self):
        progress=[]
        item=self.collect(complete_stream(),on_progress=progress.append)
        self.assertTrue(progress)
        self.assertFalse(any(item.text in str(x) for x in progress))


if __name__ == "__main__":
    unittest.main()
