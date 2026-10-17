from __future__ import annotations

import json
import time
from typing import Any, Mapping, Protocol
from urllib import error, request

from .models import ComparisonOptions, ProviderConfig, ProviderResult
from .redaction import redact_text


class Adapter(Protocol):
    def invoke(
        self,
        provider: ProviderConfig,
        credential: str,
        prompt: str,
        options: ComparisonOptions,
    ) -> ProviderResult: ...


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                candidate = item.get("text") or item.get("output_text")
                if isinstance(candidate, str):
                    parts.append(candidate)
        return "\n".join(part for part in parts if part)
    return ""


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class OpenAIChatAdapter:
    def invoke(
        self,
        provider: ProviderConfig,
        credential: str,
        prompt: str,
        options: ComparisonOptions,
    ) -> ProviderResult:
        messages: list[dict[str, str]] = []
        if options.system_prompt:
            messages.append({"role": "system", "content": options.system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": provider.model,
            "messages": messages,
            "temperature": options.temperature,
            "max_tokens": options.max_tokens,
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "cgkn-provider-api-lab/0.1",
        }
        if provider.secret_backend != "none":
            headers[provider.auth_header] = f"{provider.auth_prefix}{credential}"
        endpoint = f"{provider.base_url}/chat/completions"
        started = time.perf_counter()
        try:
            req = request.Request(endpoint, data=body, headers=headers, method="POST")
            with request.urlopen(req, timeout=provider.timeout_seconds) as response:
                raw = response.read()
                request_id = (
                    response.headers.get("x-request-id")
                    or response.headers.get("request-id")
                    or ""
                )
            latency_ms = int(round((time.perf_counter() - started) * 1000))
            decoded = json.loads(raw.decode("utf-8"))
            if not isinstance(decoded, Mapping):
                raise ValueError("response root is not an object")
            choices = decoded.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError("response has no choices")
            first = choices[0]
            if not isinstance(first, Mapping):
                raise ValueError("response choice is not an object")
            message = first.get("message")
            if not isinstance(message, Mapping):
                raise ValueError("response choice has no message")
            text = _content_to_text(message.get("content"))
            reasoning = _content_to_text(
                message.get("reasoning_content") or message.get("reasoning")
            )
            if not text and not reasoning:
                raise ValueError("response message contains no text")
            usage = decoded.get("usage")
            if not isinstance(usage, Mapping):
                usage = {}
            return ProviderResult(
                provider_id=provider.provider_id,
                display_name=provider.display_name,
                model=provider.model,
                status="ok",
                text=text,
                reasoning=reasoning,
                latency_ms=latency_ms,
                prompt_tokens=_optional_int(usage.get("prompt_tokens")),
                completion_tokens=_optional_int(usage.get("completion_tokens")),
                total_tokens=_optional_int(usage.get("total_tokens")),
                request_id=request_id,
                metadata={"finish_reason": first.get("finish_reason")},
            )
        except error.HTTPError as exc:
            latency_ms = int(round((time.perf_counter() - started) * 1000))
            try:
                response_body = exc.read(16_384).decode("utf-8", errors="replace")
            except Exception:
                response_body = ""
            message = f"HTTP {exc.code}: {response_body or exc.reason}"
            return self._error_result(provider, message, latency_ms, credential)
        except (error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            latency_ms = int(round((time.perf_counter() - started) * 1000))
            return self._error_result(provider, str(exc), latency_ms, credential)

    @staticmethod
    def _error_result(
        provider: ProviderConfig,
        message: str,
        latency_ms: int,
        credential: str,
    ) -> ProviderResult:
        return ProviderResult(
            provider_id=provider.provider_id,
            display_name=provider.display_name,
            model=provider.model,
            status="error",
            error=redact_text(message, [credential]),
            latency_ms=latency_ms,
        )


ADAPTERS: dict[str, Adapter] = {"openai_chat": OpenAIChatAdapter()}
