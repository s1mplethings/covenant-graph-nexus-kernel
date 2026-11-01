"""Route-preserving streaming transport adapter for the existing CGKN Gateway.

This does NOT open a network route. Supply the existing provider-bound opener
from gateway.network.opener(provider_id, ...); never urllib.request.urlopen.
Budget reservation and UNKNOWN outcome handling belong to the enclosing caller.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.request import Request
from urllib.parse import urlparse

from .streaming_sse import (
    StreamedCompletion,
    StreamLimits,
    configure_streamed_chat_request,
    read_sse_response,
)

# This is the existing CGKN text contract, not a statement that vendors lack
# tools/vision. Those require their own already-admitted executor contracts.
PROVIDER_CAPABILITIES={
    'qwen':{'upstream_protocol':'chat_sse','include_usage':True,'structured_output':'json_schema',
            'reasoning_delta':'count_only','tool_execution_contract':False,'live_stream_verified':False},
    'deepseek':{'upstream_protocol':'chat_sse','include_usage':True,'structured_output':'json_object_with_local_schema',
                'reasoning_delta':'count_only','tool_execution_contract':False,'live_stream_verified':False},
}


@dataclass(frozen=True)
class BoundProviderRoute:
    provider_id: str
    base_url: str
    model: str
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "

    def __post_init__(self):
        if self.provider_id not in PROVIDER_CAPABILITIES:
            raise ValueError("provider is outside domestic allowlist")
        url = urlparse(self.base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("bound upstream provider URL must be an HTTPS base URL")
        if self.auth_header not in {"Authorization", "api-key", "x-api-key"}:
            raise ValueError("auth header not allowed")
        if self.auth_prefix not in {"Bearer ", ""}:
            raise ValueError("auth prefix not allowed")
        if not self.model.strip():
            raise ValueError("upstream model is required")


def invoke_stream_via_bound_opener(
    *, route: BoundProviderRoute, token: str,
    bound_open: Callable[[Request], Any] | None = None, upstream_chat_payload: Mapping[str, Any],
    bound_consume: Callable | None = None,
    limits: StreamLimits | None = None,
    on_progress: Callable[[Mapping[str, Any]], None] | None = None,
) -> StreamedCompletion:
    """Make exactly one POST using an already selected interface-bound transport.

    Does not contain retries, fallbacks, environment proxy selection, storage,
    cost accounting or task state mutations. The caller must reserve and mark
    request-started before invocation; exceptions after start mean UNKNOWN until
    independently reconciled. This function may throw on malformed/partial SSE.
    """
    if not token.strip():
        raise ValueError("provider credential unavailable")
    if upstream_chat_payload.get("model") != route.model:
        raise ValueError("upstream model does not match saved route")
    body = json.dumps(configure_streamed_chat_request(upstream_chat_payload),
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > 1_048_576:
        raise ValueError("upstream request exceeds gateway request limit")
    req = Request(
        route.base_url.rstrip("/") + "/chat/completions", data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            route.auth_header: route.auth_prefix + token,
        }, method="POST",
    )
    # Network binding and TLS verification are owned by bound_open.
    # No fallback attempt is performed here if it raises.
    def consume(response):
        return read_sse_response(response, kind="chat", limits=limits, on_progress=on_progress)
    if bound_consume is not None:
        completion=bound_consume(req,consume)
    else:
        with bound_open(req) as response:completion=consume(response)
    if completion.model != route.model:
        raise ValueError("upstream model mismatches saved route")
    return completion
