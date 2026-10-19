from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, replace
from typing import Any, Mapping
from urllib import error, request
from urllib.parse import urlparse

from scripts import provider_api_budget

from .client import ModelRoleConfig, OpenAICompatibleClient, ProviderCompletion
from .structured_output import StructuredAnswerSelector, StructuredSelectionError


MAX_RESPONSE_BYTES = 2_097_152
MAX_REQUEST_BYTES = 1_048_576
API_LAB_REPOSITORY = "https://github.com/s1mplethings/cgkn-provider-api-lab.git"
API_LAB_BRANCH = "codex/deepseek-thinking-control-20261019"
API_LAB_COMMIT = "999dff096afe45f058fe67016aee28a73912d5d4"
API_LAB_RAW_DEFER_CONTRACT_VERSION = "1.1"


class GatewayCompletionError(RuntimeError):
    def __init__(self, category: str, message: str, *, http_status: int | None = None, outcome_unknown: bool = False, evidence: Mapping[str, Any] | None = None) -> None:
        self.category = category
        self.http_status = http_status
        self.outcome_unknown = outcome_unknown
        self.evidence = dict(evidence or {})
        super().__init__(f"{category}: {message}")


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _loopback_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Provider gateway must be an explicit http://127.0.0.1 loopback URL")
    path = parsed.path.rstrip("/")
    if path not in {"", "/v1"}:
        raise ValueError("Provider gateway URL path must be empty or /v1")
    return f"http://127.0.0.1:{parsed.port or 80}"


def _safe_gateway_error(doc: Mapping[str, Any], token: str, fallback: str) -> tuple[str, str]:
    raw = doc.get("error")
    if not isinstance(raw, Mapping):
        return "gateway_error", fallback
    category = str(raw.get("type") or "gateway_error")[:80]
    message = str(raw.get("message") or fallback).replace(token, "[REDACTED]")[:1000]
    return category, message


def _schema_validator(schema: Mapping[str, Any]):
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # the legacy client remains importable without this gateway dependency
        raise GatewayCompletionError("gateway_dependency_unavailable", "jsonschema is required for structured gateway output") from exc
    Draft202012Validator.check_schema(dict(schema))
    return Draft202012Validator(dict(schema))


@dataclass(frozen=True)
class GatewayCompletionClient:
    base_url: str
    access_token: str = field(repr=False)
    api_method: str = "responses"
    run_id: str = ""
    case_id: str = ""
    enforce_budget: bool = True
    budget_purpose: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _loopback_base_url(self.base_url))
        if not self.access_token.strip():
            raise ValueError("Provider gateway token is required")
        if self.api_method not in {"responses", "chat_completions"}:
            raise ValueError("gateway API method must be responses or chat_completions")

    @classmethod
    def from_environment(cls) -> "GatewayCompletionClient":
        base_url = str(os.environ.get("CGKN_PROVIDER_GATEWAY_BASE_URL", "")).strip()
        token = str(os.environ.get("CGKN_PROVIDER_GATEWAY_TOKEN", "")).strip()
        method = str(os.environ.get("CGKN_PROVIDER_GATEWAY_API_METHOD", "responses")).strip().lower()
        return cls(base_url, token, method)

    def bind_run(self, run_id: str, case_id: str, *, budget_purpose: str = "") -> "GatewayCompletionClient":
        purpose = str(budget_purpose).strip().upper()
        if purpose and purpose not in {"PLANNING", "GENERATION", "REPAIR", "BENCHMARK", "AUTH_PROBE", "CAPABILITY_BUILD"}:
            raise ValueError("unsupported Provider budget purpose")
        return replace(self, run_id=str(run_id), case_id=str(case_id), budget_purpose=purpose)

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        logical_started = time.monotonic()
        if config.model not in {"qwen", "deepseek", "grok"}:
            raise GatewayCompletionError("invalid_model", "model must be an allowed Provider ID")
        schema_doc = dict(schema)
        _schema_validator(schema_doc)
        if self.api_method == "chat_completions":
            path = "/v1/chat/completions"
            payload: dict[str, Any] = {
                "model": config.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": config.temperature,
                "max_tokens": config.max_output_tokens,
                "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema_doc}},
            }
        else:
            path = "/v1/responses"
            payload = {
                "model": config.model,
                "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": config.temperature,
                "max_output_tokens": config.max_output_tokens,
                "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema_doc}},
            }
        if config.thinking_mode != "default":
            payload["thinking"] = {"type": config.thinking_mode}
        if config.reasoning_effort != "none" and config.thinking_mode != "disabled":
            payload["reasoning"] = {"effort": config.reasoning_effort}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise GatewayCompletionError("request_too_large", "gateway request exceeded the bounded request size")
        identity = "sha256:" + hashlib.sha256(encoded).hexdigest()
        outer_seconds = config.outer_deadline_seconds or (config.timeout_seconds + config.deadline_reserve_seconds)
        remaining_outer = max(0.0, outer_seconds - (time.monotonic() - logical_started))
        available_transport_seconds = remaining_outer - config.deadline_reserve_seconds
        if available_transport_seconds <= 0:
            raise GatewayCompletionError("outer_deadline_exhausted", "insufficient time remains to start Provider transport")
        # Do not let sub-second bookkeeping elapsed before transport turn a valid
        # one-second request into a zero-second deadline.
        effective_timeout = min(config.timeout_seconds, max(1, int(available_transport_seconds)))
        limits = provider_api_budget.configured_limits()
        if self.enforce_budget and (
            provider_api_budget.configured_ledger_path() is None
            or not provider_api_budget.budget_configured()
            or limits.get("input_cost_per_million") is None
            or limits.get("output_cost_per_million") is None
        ):
            raise provider_api_budget.ProviderBudgetExhausted(
                "PROVIDER_BUDGET_EXHAUSTED: gateway calls require a ledger, complete limits, and operator-supplied price estimates"
            )
        reservation = provider_api_budget.reserve_call(
            case_id=self.case_id or str(os.environ.get("CGKN_BENCHMARK_CASE_ID", "gateway-runtime")),
            purpose=self.budget_purpose or ("PLANNING" if config.role == "agent" else "GENERATION"),
            model=config.model,
            request_identity=identity,
            estimated_input_tokens=max(1, (len(system) + len(user) + 3) // 4),
            requested_output_tokens=config.max_output_tokens,
            retry_count=0,
            run_id=self.run_id or None,
            provider=config.model,
        ) if self.enforce_budget else None
        response_doc: dict[str, Any] | None = None
        http_status: int | None = None
        started = False
        try:
            req = request.Request(
                self.base_url + path,
                data=encoded,
                headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "cgkn-kernel/gateway-v1"},
                method="POST",
            )
            provider_api_budget.mark_request_started(reservation)
            started = True
            with request.urlopen(req, timeout=effective_timeout) as response:
                http_status = int(response.status)
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise GatewayCompletionError("invalid_response", "gateway response exceeded the bounded response size", http_status=http_status)
            decoded = json.loads(raw.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise GatewayCompletionError("invalid_response", "gateway response root is not an object", http_status=http_status)
            response_doc = decoded
            provider_api_budget.mark_response_received(reservation, response=response_doc, http_status=http_status)
            raw_defer = decoded.get("cgkn_raw_defer")
            if raw_defer is not None and not isinstance(raw_defer, Mapping):
                raise GatewayCompletionError("invalid_response", "raw-defer metadata must be an object", http_status=http_status)
            transport_metadata = dict(raw_defer or {})
            if transport_metadata and str(transport_metadata.get("contract_version")) != API_LAB_RAW_DEFER_CONTRACT_VERSION:
                raise GatewayCompletionError("invalid_response", "unsupported API Lab raw-defer contract", http_status=http_status)
            status = str(decoded.get("status", "completed"))
            finish_reason = str(transport_metadata.get("finish_reason") or "")
            text = str(transport_metadata.get("raw_text") or "") if transport_metadata else self._extract_text(decoded)
            usage_source = transport_metadata.get("usage") if transport_metadata else decoded.get("usage")
            usage = dict(usage_source) if isinstance(usage_source, Mapping) else {}
            if "prompt_tokens" not in usage and "input_tokens" in usage:
                usage["prompt_tokens"] = usage.get("input_tokens")
            if "completion_tokens" not in usage and "output_tokens" in usage:
                usage["completion_tokens"] = usage.get("output_tokens")
            prompt_hash = "sha256:" + hashlib.sha256(
                json.dumps({"system": system, "user": user}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            attempts = transport_metadata.get("transport_attempts")
            attempt_count = len(attempts) if isinstance(attempts, list) and attempts else 1
            selector_kwargs = {
                "schema_name": schema_name,
                "provider_id": str(transport_metadata.get("provider_id") or config.model),
                "model": str(transport_metadata.get("model") or decoded.get("model") or config.model),
                "task_class": config.task_class,
                "operation": config.operation,
                "prompt_hash": prompt_hash,
                "transport_attempts": attempt_count,
                "elapsed_ms": int(transport_metadata.get("elapsed_ms") or (time.monotonic() - logical_started) * 1000),
                "usage_status": "REPORTED" if usage else "UNREPORTED",
                "configured_timeout_seconds": config.timeout_seconds,
                "effective_request_timeout_seconds": effective_timeout,
                "remaining_outer_seconds": max(0, int(remaining_outer)),
                "max_output_tokens": config.max_output_tokens,
                "logical_call_number": 1,
                "response_headers_received": bool(transport_metadata.get("response_headers_received", True)),
                "finish_reason": finish_reason,
                "transport_status": str(transport_metadata.get("transport_status") or "COMPLETED"),
                "usage": usage,
                "api_lab_commit": API_LAB_COMMIT,
                "api_lab_contract_version": API_LAB_RAW_DEFER_CONTRACT_VERSION,
                "route_mode": "raw_defer",
                "request_id": str(transport_metadata.get("request_id") or decoded.get("id") or ""),
                "thinking_mode": str(transport_metadata.get("thinking_mode_requested") or config.thinking_mode),
                "reasoning_effort": str(transport_metadata.get("reasoning_effort_requested") or config.reasoning_effort),
                "reasoning_tokens": transport_metadata.get("reasoning_tokens"),
                "reasoning_text_present": bool(transport_metadata.get("reasoning_text_present")),
                "reasoning_text_length": int(transport_metadata.get("reasoning_text_length") or 0),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cached_tokens": transport_metadata.get("cached_tokens"),
            }
            selection_error: StructuredSelectionError | None = None
            selected: dict[str, Any] | None = None
            try:
                selected, selection = StructuredAnswerSelector().select(
                    text, schema_doc, **selector_kwargs,
                )
            except StructuredSelectionError as exc:
                selection_error = exc
                selection = exc.receipt
            truncated = status not in {"completed", ""} or finish_reason.lower() in {"length", "max_tokens"}
            if truncated:
                evidence = selection.as_dict()
                evidence.update({
                    "thinking_mode_requested": config.thinking_mode,
                    "thinking_mode_forwarded": transport_metadata.get("thinking_mode_forwarded"),
                    "transport_attempts_detail": list(attempts) if isinstance(attempts, list) else [],
                })
                evidence["final_status"] = "PROVIDER_OUTPUT_TRUNCATED"
                raise GatewayCompletionError(
                    "PROVIDER_OUTPUT_TRUNCATED", "Provider output reached its configured limit",
                    http_status=http_status, evidence=evidence,
                )
            if not text.strip():
                raise GatewayCompletionError("empty_response", "gateway returned no completion text", http_status=http_status)
            if selection_error is not None:
                failed_evidence = selection_error.receipt.as_dict()
                failed_evidence.update({
                    "thinking_mode_requested": config.thinking_mode,
                    "thinking_mode_forwarded": transport_metadata.get("thinking_mode_forwarded"),
                    "transport_attempts_detail": list(attempts) if isinstance(attempts, list) else [],
                })
                raise GatewayCompletionError(
                    selection_error.status, selection_error.status,
                    http_status=http_status, evidence=failed_evidence,
                ) from None
            provider_api_budget.finalize_call(reservation, usage=usage, http_status=http_status, status="SUCCEEDED")
            assert selected is not None
            transport_metadata.update({
                "api_lab_repository": API_LAB_REPOSITORY,
                "api_lab_branch": API_LAB_BRANCH,
                "api_lab_commit": API_LAB_COMMIT,
                "api_lab_contract_version": API_LAB_RAW_DEFER_CONTRACT_VERSION,
                "route_mode": "raw_defer",
            })
            return ProviderCompletion(
                json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                str(transport_metadata.get("model") or decoded.get("model") or config.model),
                str(transport_metadata.get("request_id") or decoded.get("id") or ""),
                usage, attempt_count, selection.as_dict(), transport_metadata,
            )
        except error.HTTPError as exc:
            http_status = int(exc.code)
            try:
                body = exc.read(65_536)
                decoded = json.loads(body.decode("utf-8"))
                response_doc = decoded if isinstance(decoded, dict) else {}
            except Exception:
                response_doc = {}
            category, message = _safe_gateway_error(response_doc, self.access_token, f"gateway HTTP {http_status}")
            provider_api_budget.finalize_call(reservation, usage=None, http_status=http_status, status="FAILED")
            evidence = response_doc.get("cgkn_raw_defer") if isinstance(response_doc.get("cgkn_raw_defer"), Mapping) else {}
            raise GatewayCompletionError(category, message, http_status=http_status, evidence=evidence) from None
        except GatewayCompletionError:
            provider_api_budget.finalize_call(reservation, usage=(response_doc or {}).get("usage") if response_doc else None, http_status=http_status, status="FAILED")
            raise
        except (TimeoutError, error.URLError, OSError) as exc:
            provider_api_budget.finalize_call(reservation, usage=None, http_status=http_status, status="FAILED")
            category = "outcome_unknown" if started else "gateway_unavailable"
            safe = str(getattr(exc, "reason", exc)).replace(self.access_token, "[REDACTED]")[:500]
            raise GatewayCompletionError(category, safe, http_status=http_status, outcome_unknown=started) from None
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            provider_api_budget.finalize_call(reservation, usage=None, http_status=http_status, status="FAILED")
            safe = str(exc).replace(self.access_token, "[REDACTED]")[:500]
            raise GatewayCompletionError("invalid_response", safe, http_status=http_status) from None

    def _extract_text(self, doc: Mapping[str, Any]) -> str:
        if self.api_method == "chat_completions":
            choices = doc.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
                return ""
            if str(choices[0].get("finish_reason", "stop")) in {"length", "max_tokens"}:
                raise GatewayCompletionError("truncated_response", "provider stopped at the output limit")
            message = choices[0].get("message")
            return str(message.get("content") or "") if isinstance(message, Mapping) else ""
        return str(doc.get("output_text") or "")


def completion_client_from_environment() -> OpenAICompatibleClient | GatewayCompletionClient:
    if _enabled(os.environ.get("CGKN_PROVIDER_GATEWAY_ENABLED")):
        return GatewayCompletionClient.from_environment()
    return OpenAICompatibleClient()
