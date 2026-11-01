"""Bounded, fail-closed SSE aggregation for Qwen/DeepSeek model responses.

No network route, credentials, retries, budget writes or business approval here.
The caller MUST use CGKN's authenticated, interface-bound Gateway transport.
The caller MUST NOT commit/cache an incomplete stream or automatically replay POST.

This module is stdlib-only and intentionally small enough to test independently.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import threading
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


class StreamError(RuntimeError):
    """A stream is unusable. Once POST may have been sent, preserve UNKNOWN outcome."""
    def __init__(self, code: str, *, outcome_unknown=True, response=None) -> None:
        self.code = code
        self.outcome_unknown=outcome_unknown
        self.response=response
        from cgkn.providers.finish_reason import classify_finish
        self.finish_reason = classify_finish(code)
        super().__init__(code)


class MeaningfulProgressWatchdog:
    """Per-attempt idle policy; elapsed generation duration is never a deadline.

    Only parsed meaningful model deltas may advance ``sequence``. Remote callers
    translate event ages to their local clock; raw monotonic timestamps never
    cross process boundaries. Call check from the I/O supervisor as well as the
    parser so a silent socket cannot prevent cancellation.
    """
    def __init__(self, initial_timeout=180.0, idle_timeout=120.0, *, clock=time.monotonic):
        for value in (initial_timeout, idle_timeout):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("INVALID_PROGRESS_TIMEOUT")
        self.initial_timeout = float(initial_timeout)
        self.idle_timeout = float(idle_timeout)
        self.clock = clock
        self._lock = threading.RLock()
        self._submitted = self._first = self._last = None
        self._events = 0
        self._reason = None

    @staticmethod
    def _age(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("INVALID_PROGRESS_AGE")
        return float(value)

    def _observed(self, age, observed_at):
        age = self._age(age)
        now = self.clock()
        if observed_at is None:
            return now - age
        if age != 0 or isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)) or not math.isfinite(observed_at) or observed_at > now:
            raise ValueError("INVALID_PROGRESS_OBSERVATION")
        return float(observed_at)

    def submitted(self, *, age=0, observed_at=None):
        when = self._observed(age, observed_at)
        with self._lock:
            if self._submitted is None:
                self._submitted = when
            self.check()

    def progress(self, sequence, *, age=0, observed_at=None):
        when = self._observed(age, observed_at)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("INVALID_PROGRESS_SEQUENCE")
        with self._lock:
            if self._submitted is None:
                raise ValueError("PROGRESS_BEFORE_SUBMISSION")
            self.check()
            if sequence <= self._events:
                return False
            if when < self._submitted or (self._last is not None and when < self._last):
                raise ValueError("INVALID_PROGRESS_ORDER")
            self._events = sequence
            if self._first is None:
                self._first = when
            self._last = when
            self.check()
            return True

    def check(self):
        with self._lock:
            if self._reason:
                raise StreamError(self._reason)
            if self._submitted is None:
                return
            now = self.clock()
            if self._last is None and now - self._submitted >= self.initial_timeout:
                self._reason = "NO_INITIAL_MEANINGFUL_PROGRESS"
            elif self._last is not None and now - self._last >= self.idle_timeout:
                self._reason = "NO_MEANINGFUL_PROGRESS"
            if self._reason:
                raise StreamError(self._reason)

    def snapshot(self):
        with self._lock:
            now = self.clock()
            return dict(submitted=self._submitted is not None, started=self._first is not None,
                        meaningful_events=self._events,
                        submitted_age=None if self._submitted is None else max(0, now-self._submitted),
                        first_progress_age=None if self._first is None else max(0, now-self._first),
                        last_progress_age=None if self._last is None else max(0, now-self._last),
                        stall_reason=self._reason)


@dataclass(frozen=True)
class StreamLimits:
    max_wire_bytes: int = 10 * 1024 * 1024
    max_line_bytes: int = 256 * 1024
    max_event_bytes: int = 512 * 1024
    max_events: int = 120_000
    max_text_bytes: int = 4 * 1024 * 1024


@dataclass(frozen=True)
class SSEEvent:
    data: str
    event: str = "message"
    event_id: str = ""


def sse_events(lines: Iterable[bytes], *, limits: StreamLimits, on_heartbeat=None):
    """Parse complete SSE lines, including comments, CRLF and multiline data.

    `lines` should yield lines from a response.readline(limit + 1) loop;
    enforce socket/read-idle timeout in the network layer as well.
    """
    data: list[bytes] = []
    size = 0
    event_type = "message"
    event_id = ""
    wire = 0
    event_count = 0
    seen_ids = {}
    for raw in lines:
        if not isinstance(raw, bytes):
            raise StreamError("stream_invalid_transport_chunk")
        if len(raw) > limits.max_line_bytes:
            raise StreamError("stream_line_too_large")
        wire += len(raw)
        if wire > limits.max_wire_bytes:
            raise StreamError("stream_wire_too_large")
        line = raw.rstrip(b"\r\n")
        if not line:
            if data:
                event_count += 1
                if event_count > limits.max_events:
                    raise StreamError("stream_too_many_events")
                try:
                    payload = b"\n".join(data).decode("utf-8", "strict")
                except UnicodeDecodeError:
                    raise StreamError("stream_invalid_utf8") from None
                fingerprint = hashlib.sha256((event_type+'\0'+payload).encode()).hexdigest()
                if event_id and event_id in seen_ids:
                    if seen_ids[event_id] != fingerprint:
                        raise StreamError('stream_conflicting_event_id')
                else:
                    if event_id:seen_ids[event_id] = fingerprint
                    yield SSEEvent(payload, event_type, event_id)
            data, size, event_type, event_id = [], 0, "message", ""
            continue
        if line.startswith(b":"):
            if on_heartbeat:on_heartbeat()
            continue  # keepalive, never counted as generated content
        key, sep, value = line.partition(b":")
        if sep and value.startswith(b" "):
            value = value[1:]
        if key == b"data":
            size += len(value)
            if size > limits.max_event_bytes:
                raise StreamError("stream_event_too_large")
            data.append(value)
        elif key == b"event":
            try:
                event_type = value.decode("utf-8", "strict")
            except UnicodeDecodeError:
                raise StreamError("stream_invalid_utf8") from None
        elif key == b"id":
            # Don't allow control characters or gigantic opaque IDs in logs/metadata.
            if len(value) <= 256 and b"\x00" not in value:
                event_id = value.decode("utf-8", "replace")
    if data:
        # A trailing non-dispatched event is not a complete SSE event.
        raise StreamError("stream_unterminated_event")


def iter_response_lines(response: Any, limits: StreamLimits):
    """Read streaming lines without buffering an entire HTTP body."""
    while True:
        line = response.readline(limits.max_line_bytes + 1)
        if not line:
            break
        yield line


def _object(payload: str) -> Mapping[str, Any]:
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise StreamError("stream_invalid_json") from None
    if not isinstance(data, dict):
        raise StreamError("stream_json_not_object")
    return data


def _usage(data: Any) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        return {}
    # Keep provider-compatible usage fields; fail on negative or malformed known counts.
    for key in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens", "total_tokens"):
        if key in data and data[key] is not None:
            value = data[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise StreamError("stream_invalid_usage")
    return dict(data)


@dataclass(frozen=True)
class StreamedCompletion:
    text: str
    model: str
    request_id: str
    usage: Mapping[str, Any] = field(default_factory=dict)
    finish_reason: str = "stop"
    event_count: int = 0
    reasoning_chars: int = 0

    def as_chat_completion(self, model_alias: str | None = None) -> dict[str, Any]:
        return {
            "id": self.request_id,
            "object": "chat.completion",
            "model": model_alias or self.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": self.text}, "finish_reason": self.finish_reason}],
            "usage": dict(self.usage),
            "cgkn_stream": {"completed": True, "event_count": self.event_count, "reasoning_chars": self.reasoning_chars},
        }

    def as_responses(self, model_alias: str | None = None) -> dict[str, Any]:
        usage = dict(self.usage)
        if "input_tokens" not in usage and "prompt_tokens" in usage:
            usage["input_tokens"] = usage["prompt_tokens"]
        if "output_tokens" not in usage and "completion_tokens" in usage:
            usage["output_tokens"] = usage["completion_tokens"]
        return {
            "id": self.request_id,
            "object": "response",
            "status": "completed",
            "model": model_alias or self.model,
            "output_text": self.text,
            "usage": usage,
            "cgkn_stream": {"completed": True, "event_count": self.event_count, "reasoning_chars": self.reasoning_chars},
        }


def collect_chat_completions(
    events: Iterable[SSEEvent], *, limits: StreamLimits | None = None,
    on_progress: Callable[[Mapping[str, Any]], None] | None = None,
) -> StreamedCompletion:
    """Only [DONE] + stop + nonempty content constitutes a completed Chat stream."""
    limits = limits or StreamLimits()
    parts: list[str] = []
    size = 0
    model = ""
    request_id = ""
    usage: dict[str, Any] = {}
    finish: str | None = None
    reason_chars = 0
    event_count = 0
    done = False
    meaningful_events = 0
    for evt in events:
        event_count += 1
        if event_count > limits.max_events:
            raise StreamError("stream_too_many_events")
        if done:
            raise StreamError("stream_data_after_done")
        if evt.data.strip() == "[DONE]":
            done = True
            break
        doc = _object(evt.data)
        if "error" in doc and doc["error"] is not None:
            raise StreamError("stream_upstream_error")
        if doc.get("id"):
            current_id = str(doc["id"])
            if request_id and request_id != current_id:
                raise StreamError("stream_mixed_request_ids")
            request_id = current_id
        if doc.get("model"):
            current_model = str(doc["model"])
            if model and model != current_model:
                raise StreamError("stream_mixed_models")
            model = current_model
        if doc.get("usage") is not None:
            usage = _usage(doc["usage"])
        meaningful = False
        choices = doc.get("choices", [])
        if not isinstance(choices, list):
            raise StreamError("stream_invalid_choices")
        for choice in choices:
            if not isinstance(choice, Mapping):
                raise StreamError("stream_invalid_choice")
            if choice.get("index", 0) != 0:
                raise StreamError("stream_multiple_choices_not_supported")
            delta = choice.get("delta") or {}
            if not isinstance(delta, Mapping):
                raise StreamError("stream_invalid_delta")
            if delta.get("tool_calls") or delta.get("function_call"):
                raise StreamError("stream_tool_calls_require_explicit_contract")
            if delta.get('refusal'):
                raise StreamError('stream_refused')
            fragment = delta.get("content")
            if fragment is not None:
                if not isinstance(fragment, str):
                    raise StreamError("stream_nontext_content_unsupported")
                if finish is not None and fragment:raise StreamError('stream_content_after_finish')
                size += len(fragment.encode("utf-8"))
                if size > limits.max_text_bytes:
                    raise StreamError("stream_text_too_large")
                parts.append(fragment)
                meaningful = meaningful or bool(fragment.strip())
            reason = delta.get("reasoning_content") or delta.get("reasoning")
            if reason is not None:
                if not isinstance(reason, str):
                    raise StreamError("stream_invalid_reasoning")
                meaningful = meaningful or bool(reason.strip())
                reason_chars += len(reason)
                if reason_chars>limits.max_text_bytes:raise StreamError('stream_reasoning_too_large')
            if choice.get("finish_reason") is not None:
                next_finish = str(choice["finish_reason"])
                if finish is not None and finish != next_finish:
                    raise StreamError("stream_conflicting_finish")
                finish = next_finish
        if meaningful:
            meaningful_events += 1
        if on_progress:
            on_progress({"phase": "receiving", "events": event_count, "meaningful_events": meaningful_events, "text_bytes": size, "reasoning_chars": reason_chars})
    if not done:
        raise StreamError("stream_eof_without_done")
    if finish != "stop":
        code = {'length':'stream_output_token_limit','tool_calls':'stream_tool_finished',
                'function_call':'stream_tool_finished'}.get(finish,'stream_unknown_finish')
        raise StreamError(code, response={'partial_text':''.join(parts), 'model':model,
                                         'usage':usage,'finish_reason':finish})
    if not "".join(parts).strip():
        raise StreamError("stream_empty_content")
    return StreamedCompletion("".join(parts), model, request_id, usage, finish, event_count, reason_chars)


def collect_responses(
    events: Iterable[SSEEvent], *, limits: StreamLimits | None = None,
    on_progress: Callable[[Mapping[str, Any]], None] | None = None,
) -> StreamedCompletion:
    """Handle Responses SSE using the explicit response.completed event as commit fence."""
    limits = limits or StreamLimits()
    parts: list[str] = []
    size = 0
    event_count = 0
    completed: Mapping[str, Any] | None = None
    response_id = ""
    meaningful_events = 0
    reason_chars = 0
    for evt in events:
        event_count += 1
        if event_count > limits.max_events:
            raise StreamError("stream_too_many_events")
        # Responses events usually specify type inside JSON (event name may vary).
        doc = _object(evt.data)
        typ = str(doc.get("type") or evt.event)
        meaningful = False
        if doc.get('response_id'):
            if response_id and response_id!=doc['response_id']:raise StreamError('stream_mixed_request_ids')
            response_id=doc['response_id']
        if 'refusal' in typ:raise StreamError('stream_refused')
        if typ in {"response.failed", "response.incomplete", "error"}:
            raise StreamError("stream_response_not_completed")
        if typ == "response.output_text.delta":
            text = doc.get("delta")
            if not isinstance(text, str):
                raise StreamError("stream_invalid_delta")
            size += len(text.encode("utf-8"))
            if size > limits.max_text_bytes:
                raise StreamError("stream_text_too_large")
            parts.append(text)
            meaningful = bool(text.strip())
        elif typ in {"response.reasoning_text.delta", "response.reasoning_summary_text.delta"}:
            reason = doc.get("delta")
            if not isinstance(reason, str):
                raise StreamError("stream_invalid_reasoning")
            reason_chars += len(reason)
            if reason_chars > limits.max_text_bytes:
                raise StreamError("stream_reasoning_too_large")
            meaningful = bool(reason.strip())
        elif typ == "response.completed":
            if completed is not None:
                raise StreamError("stream_duplicate_complete")
            completed = doc.get("response")
            if not isinstance(completed, Mapping):
                raise StreamError("stream_missing_completed_response")
            if completed.get("status") != "completed":
                raise StreamError("stream_response_not_completed")
        if typ in {"response.created", "response.in_progress"}:
            obj = doc.get("response")
            if isinstance(obj, Mapping) and obj.get("id"):
                if response_id and response_id != str(obj["id"]):
                    raise StreamError("stream_mixed_request_ids")
                response_id = str(obj["id"])
        if meaningful:
            meaningful_events += 1
        if on_progress:
            on_progress({"phase": "receiving", "events": event_count, "meaningful_events": meaningful_events, "text_bytes": size, "reasoning_chars": reason_chars})
        if completed is not None:
            break
    if completed is None:
        raise StreamError("stream_eof_without_complete")
    final_id = str(completed.get("id") or "")
    if response_id and final_id and response_id != final_id:
        raise StreamError("stream_mixed_request_ids")
    # Reject mixed function-call outputs: the plain-text result contract
    # cannot prove those tools actually ran, even if text is also present.
    output = completed.get("output")
    if isinstance(output, list) and any(isinstance(item, Mapping) and item.get("type") not in {"message", "reasoning"} for item in output):
        raise StreamError("stream_tool_calls_require_explicit_contract")
    final_text = completed.get("output_text")
    if isinstance(final_text,str) and parts and final_text!=''.join(parts):
        raise StreamError('stream_final_text_mismatch')
    if not isinstance(final_text, str):
        final_text = "".join(parts)
    if not final_text:
        # Some Responses implementations only return the final output[] tree.
        blocks = completed.get("output")
        if isinstance(blocks, list):
            output_parts: list[str] = []
            for block in blocks:
                if isinstance(block, Mapping) and block.get("type") == "message":
                    for unit in block.get("content", []):
                        if isinstance(unit, Mapping) and unit.get("type") == "output_text" and isinstance(unit.get("text"), str):
                            output_parts.append(unit["text"])
            final_text = "".join(output_parts)
    if len(final_text.encode("utf-8")) > limits.max_text_bytes:
        raise StreamError("stream_text_too_large")
    if not final_text.strip():
        raise StreamError("stream_empty_content")
    return StreamedCompletion(final_text, str(completed.get("model") or ""), final_id or response_id,
                              _usage(completed.get("usage")), "stop", event_count, reason_chars)


def read_sse_response(response: Any, *, kind: str = "chat", limits: StreamLimits | None = None,
                      on_progress: Callable[[Mapping[str, Any]], None] | None = None) -> StreamedCompletion:
    """Consume an already-open, bound upstream or loopback HTTP response.

    IMPORTANT: pass the provider network binding's HTTP response, not a fresh
    urllib.request.urlopen() or environmental-proxy client. The outer layer
    must set connect/read-idle timeouts and classify any transport exception
    after POST start as an unknown outcome, not retryable failure.
    """
    limits = limits or StreamLimits()
    code = getattr(response, "status", None)
    if code is not None and int(code) != 200:
        raise StreamError("stream_http_non_200")
    headers = getattr(response, "headers", {})
    content_type = str(headers.get("Content-Type", "")).lower() if hasattr(headers, "get") else ""
    if "text/event-stream" not in content_type:
        raise StreamError("stream_not_sse")
    heartbeat_count = 0
    def heartbeat():
        nonlocal heartbeat_count
        heartbeat_count += 1
        if on_progress:on_progress({'phase':'heartbeat','heartbeat_count':heartbeat_count,'meaningful_events':0})
    event_iter = sse_events(iter_response_lines(response, limits), limits=limits, on_heartbeat=heartbeat)
    if kind == "chat":
        return collect_chat_completions(event_iter, limits=limits, on_progress=on_progress)
    if kind == "responses":
        return collect_responses(event_iter, limits=limits, on_progress=on_progress)
    raise ValueError("Unknown stream kind")


def configure_streamed_chat_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the model-specific payload intact while asking for Chat SSE+usage."""
    if payload.get("stream") is False:
        raise StreamError("stream_explicitly_disabled")
    result = dict(payload)
    result["stream"] = True
    opts = result.get("stream_options") or {}
    if not isinstance(opts, Mapping):
        raise StreamError("stream_options_invalid")
    result["stream_options"] = {**dict(opts), "include_usage": True}
    return result


def save_completed_response(path: str | Path, completion: StreamedCompletion, *, model_alias: str, kind: str = "responses") -> str:
    """Persist a completely assembled output atomically; caller validates schema beforehand.

    Does not write budget, clear UNKNOWN outcomes, or change task state.
    """
    data = completion.as_responses(model_alias) if kind == "responses" else completion.as_chat_completion(model_alias)
    return save_immutable_json(path,data)


def save_immutable_json(path,data):
    """Durable, atomic create; a late result cannot replace an existing result."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    # Stream the encoder into a bounded buffer: metadata must not bypass the
    # model text bounds and allocate an unbounded second result in memory.
    chunks = []
    size = 0
    for piece in json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).iterencode(data):
        raw_piece = piece.encode("utf-8")
        size += len(raw_piece)
        if size > 16 * 1024 * 1024:
            raise StreamError("completed_response_too_large")
        chunks.append(raw_piece)
    raw = b"".join(chunks)
    if shutil.disk_usage(path.parent).free < len(raw) + 1024 * 1024:
        raise StreamError("completed_response_disk_space_low")
    fd, tmp = tempfile.mkstemp(prefix=".cgkn-stream-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        # Atomic create-if-absent using a hard link. os.replace would overwrite
        # another completed attempt between the existence check and rename.
        # If the filesystem cannot support this, fail closed rather than overwrite.
        os.link(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return "sha256:" + hashlib.sha256(raw).hexdigest()
