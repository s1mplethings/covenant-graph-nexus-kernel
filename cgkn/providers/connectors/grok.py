from __future__ import annotations

import json
import os
import socket
import time
from typing import Any, Mapping, Sequence
from urllib import error, request
from urllib.parse import urlparse

from ..client import ModelRoleConfig, ProviderCompletion
from ..connection_contracts import ModelBindingSource, ProviderConnectionError, ProviderConnectionHealth, ProviderConnectionSnapshot, ProviderModelBinding, StructuredOutputMode, canonical_hash
from ..structured_output import parse_and_validate, resolve_credential, sanitize_vendor_text


MAX_PROVIDER_TIMEOUT_SECONDS = 600


def resolve_effective_timeout(requested_timeout_seconds: Any, default_timeout_seconds: int, max_timeout_seconds: int) -> int:
    try:
        requested = int(requested_timeout_seconds)
    except (TypeError, ValueError):
        requested = 0
    return min(requested, max_timeout_seconds) if requested > 0 else default_timeout_seconds


class GrokConnector:
    provider_id = "grok"

    def __init__(self, profile: Mapping[str, Any], *, environment: Mapping[str, str] | None = None) -> None:
        self.profile = dict(profile); self.environment = dict(os.environ if environment is None else environment)
        self.credential, self.credential_present = resolve_credential(self.environment, "CGKN_GROK_API_KEY", "XAI_API_KEY")
        self.base_url = str(self.environment.get("CGKN_GROK_BASE_URL") or self.profile.get("base_url") or "").rstrip("/")
        self.preferred_models = tuple(str(item) for item in self.profile.get("preferred_models", ()))
        self.allowed_models = frozenset((*self.preferred_models, *(str(item) for item in self.profile.get("allowed_models", ()))))
        self.reasoning_effort = str(self.profile.get("reasoning_effort", "medium"))
        legacy_timeout = self.profile.get("timeout")
        explicit_default = self.profile.get("default_timeout_seconds")
        try:
            if legacy_timeout is not None and explicit_default is not None and int(legacy_timeout) != int(explicit_default):
                raise ProviderConnectionError("CONFIG_CONFLICT", "timeout and default_timeout_seconds differ")
            self.default_timeout_seconds = int(explicit_default if explicit_default is not None else (legacy_timeout if legacy_timeout is not None else 120))
            self.max_timeout_seconds = int(self.profile.get("max_timeout_seconds", self.default_timeout_seconds))
        except ProviderConnectionError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderConnectionError("GROK_TIMEOUT_CONFIG_INVALID", "Grok timeout values must be integers") from exc
        if not (0 < self.default_timeout_seconds <= self.max_timeout_seconds <= MAX_PROVIDER_TIMEOUT_SECONDS):
            raise ProviderConnectionError("GROK_TIMEOUT_CONFIG_INVALID", "Grok timeouts must satisfy 0 < default <= max <= 600")
        self.timeout = self.default_timeout_seconds
        self.max_output_tokens = int(self.profile.get("max_output_tokens", 4096))
        self._auth_failures = 0; self._models_cache: tuple[str, ...] | None = None
        self.catalog_status = "NOT_EVALUATED"; self.data_plane_status = "NOT_EVALUATED"
        self.last_model_binding: ProviderModelBinding | None = None
        self._validate_static()

    def _validate_static(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or parsed.hostname != "api.x.ai" or parsed.path.rstrip("/") != "/v1":
            raise ProviderConnectionError("GROK_ENDPOINT_ERROR", "Grok inference endpoint must be https://api.x.ai/v1")
        if str(self.profile.get("api_backend", "RESPONSES")) != "RESPONSES":
            raise ProviderConnectionError("GROK_ENDPOINT_ERROR", "Grok connector requires the Responses backend")

    def classify_error(self, *, http_status: int | None, vendor_code: str = "", message: str = "") -> str:
        text = (vendor_code + " " + message).lower()
        if http_status == 401:
            if "management" in text:
                return "GROK_WRONG_KEY_TYPE"
            return "GROK_INVALID_API_KEY" if any(item in text for item in ("invalid", "incorrect", "token")) else "GROK_AUTH_UNKNOWN"
        if http_status == 403: return "GROK_MODEL_FORBIDDEN" if "model" in text else "GROK_FORBIDDEN"
        if http_status == 400 and "model" in text: return "GROK_MODEL_INVALID"
        if http_status == 404: return "GROK_MODEL_NOT_VISIBLE" if "model" in text else "GROK_ENDPOINT_ERROR"
        return "GROK_ENDPOINT_ERROR" if http_status else "TRANSPORT_FAILURE"

    @staticmethod
    def _is_timeout(exc: BaseException) -> bool:
        return isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout))

    def _request_json(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: int | None = None,
        requested_timeout_seconds: Any = None,
        operation: str,
        endpoint_class: str,
        requested_model: str = "",
        bound_model: str = "",
    ) -> dict[str, Any]:
        if not self.credential: raise ProviderConnectionError("GROK_MISSING_AUTH", "Grok inference credential is not configured")
        if self._auth_failures >= 2: raise ProviderConnectionError("GROK_CONNECTION_BLOCKED_CREDENTIAL", "Grok auth probe limit reached")
        effective_timeout = int(timeout_seconds or self.default_timeout_seconds)
        started = time.monotonic()
        evidence = {
            "requested_timeout_seconds": requested_timeout_seconds,
            "effective_timeout_seconds": effective_timeout,
            "provider_default_timeout_seconds": self.default_timeout_seconds,
            "provider_max_timeout_seconds": self.max_timeout_seconds,
            "operation": operation,
            "endpoint_class": endpoint_class,
            "requested_model": requested_model,
            "bound_model": bound_model,
        }
        encoded = None if payload is None else json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=encoded, headers={"Authorization": f"Bearer {self.credential}", "Content-Type": "application/json", "Accept": "application/json"}, method=method)
        try:
            try:
                response_context = request.urlopen(req, timeout=effective_timeout)
            except error.HTTPError:
                raise
            except (TimeoutError, error.URLError, OSError) as exc:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                if self._is_timeout(exc):
                    raise ProviderConnectionError("PROVIDER_CONNECT_OR_HEADER_TIMEOUT", "Grok request timed out before response headers", outcome_unknown=True, timeout_phase="CONNECT_OR_HEADER_TIMEOUT", evidence={**evidence, "elapsed_ms": elapsed_ms}) from None
                raise ProviderConnectionError("PROVIDER_TRANSPORT_FAILURE", sanitize_vendor_text(getattr(exc, "reason", exc), (self.credential,)), outcome_unknown=True, evidence={**evidence, "elapsed_ms": elapsed_ms}) from None
            with response_context as response:
                try:
                    raw = response.read(2_097_153)
                except (TimeoutError, error.URLError, OSError) as exc:
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    if self._is_timeout(exc):
                        raise ProviderConnectionError("PROVIDER_RESPONSE_READ_TIMEOUT", "Grok response body timed out", outcome_unknown=True, timeout_phase="RESPONSE_READ_TIMEOUT", evidence={**evidence, "elapsed_ms": elapsed_ms}) from None
                    raise ProviderConnectionError("PROVIDER_TRANSPORT_FAILURE", sanitize_vendor_text(getattr(exc, "reason", exc), (self.credential,)), outcome_unknown=True, evidence={**evidence, "elapsed_ms": elapsed_ms}) from None
            if len(raw) > 2_097_152: raise ProviderConnectionError("PROVIDER_TRUNCATED_RESPONSE", "Grok response exceeded the bounded size", outcome_unknown=True, evidence={**evidence, "elapsed_ms": int((time.monotonic()-started)*1000)})
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderConnectionError("PROVIDER_SCHEMA_FAILURE", "Grok response was not valid JSON", outcome_unknown=True, evidence={**evidence, "elapsed_ms": int((time.monotonic()-started)*1000)}) from exc
            if not isinstance(value, dict): raise ProviderConnectionError("PROVIDER_SCHEMA_FAILURE", "Grok response root is not an object", outcome_unknown=True, evidence={**evidence, "elapsed_ms": int((time.monotonic()-started)*1000)})
            self.last_request_evidence = {**evidence, "elapsed_ms": int((time.monotonic() - started) * 1000), "timeout_phase": "NONE", "outcome_unknown": False}
            return value
        except error.HTTPError as exc:
            try: value = json.loads(exc.read(65_536).decode("utf-8"))
            except Exception: value = {}
            raw_error = value.get("error", value) if isinstance(value, dict) else {}
            code = str(raw_error.get("code", raw_error.get("type", ""))) if isinstance(raw_error, Mapping) else ""
            message = sanitize_vendor_text(raw_error.get("message", f"Grok HTTP {exc.code}") if isinstance(raw_error, Mapping) else f"Grok HTTP {exc.code}", (self.credential,))
            category = self.classify_error(http_status=int(exc.code), vendor_code=code, message=message)
            if int(exc.code) == 401: self._auth_failures += 1
            raise ProviderConnectionError(category, message, http_status=int(exc.code), outcome_unknown=True, evidence={**evidence, "elapsed_ms": int((time.monotonic()-started)*1000)}) from None
        except ProviderConnectionError:
            raise

    def list_models(self) -> Sequence[str]:
        if self._models_cache is not None: return self._models_cache
        try:
            doc = self._request_json(
                "GET", self.base_url + "/models", timeout_seconds=self.default_timeout_seconds,
                operation="MODEL_CATALOG", endpoint_class="CONTROL_PLANE",
            )
        except ProviderConnectionError as exc:
            if "AUTH" in exc.error_class or "KEY" in exc.error_class:
                category = "PROVIDER_CATALOG_AUTH_FAILURE"
            elif "TIMEOUT" in exc.error_class:
                category = "PROVIDER_CATALOG_TIMEOUT"
            elif "SCHEMA" in exc.error_class or "RESPONSE" in exc.error_class:
                category = "PROVIDER_CATALOG_RESPONSE_INVALID"
            else:
                category = "PROVIDER_CATALOG_TRANSPORT_FAILURE"
            self.catalog_status = "DEGRADED_TRANSPORT" if category in {"PROVIDER_CATALOG_TIMEOUT", "PROVIDER_CATALOG_TRANSPORT_FAILURE"} else "BLOCKED"
            raise ProviderConnectionError(category, str(exc), http_status=exc.http_status, outcome_unknown=exc.outcome_unknown, timeout_phase=exc.timeout_phase, evidence=dict(exc.evidence)) from None
        self._models_cache = tuple(str(row.get("id")) for row in doc.get("data", []) if isinstance(row, Mapping) and row.get("id"))
        self.catalog_status = "PASS"
        return self._models_cache

    def resolve_model(self, requested_model: str | None = None) -> str:
        model = str(requested_model or (self.preferred_models[0] if self.preferred_models else "")).strip()
        if not model or model not in self.list_models(): raise ProviderConnectionError("PROVIDER_CATALOG_MODEL_NOT_VISIBLE", "requested Grok model is not visible")
        return model

    def resolve_pinned_model(self, requested_model: str | None = None) -> ProviderModelBinding:
        requested = str(requested_model or self.provider_id).strip()
        if requested == self.provider_id:
            bound = self.preferred_models[0] if self.preferred_models else ""
        else:
            bound = requested
        if not bound or bound not in self.allowed_models:
            raise ProviderConnectionError("GROK_MODEL_NOT_ALLOWED", "requested Grok model is outside the profile allowlist")
        binding = ProviderModelBinding(
            self.provider_id, requested, bound, ModelBindingSource.PROFILE_PINNED,
            canonical_hash(self.profile), self.catalog_status, "NOT_EVALUATED",
        )
        self.last_model_binding = binding
        return binding

    def supports_structured_output(self) -> StructuredOutputMode: return StructuredOutputMode.NATIVE_JSON_SCHEMA

    def complete_structured(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        binding = self.resolve_pinned_model(config.model)
        model = binding.bound_model
        effective_timeout = resolve_effective_timeout(config.timeout_seconds, self.default_timeout_seconds, self.max_timeout_seconds)
        payload = {"model": model, "input": [{"role": "system", "content": system}, {"role": "user", "content": user}], "max_output_tokens": min(config.max_output_tokens, self.max_output_tokens), "reasoning": {"effort": config.reasoning_effort if config.reasoning_effort != "none" else self.reasoning_effort}, "store": False, "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": dict(schema)}}}
        try:
            doc = self._request_json(
                "POST", self.base_url + "/responses", payload,
                timeout_seconds=effective_timeout, requested_timeout_seconds=config.timeout_seconds,
                operation="STRUCTURED_COMPLETION", endpoint_class="DATA_PLANE",
                requested_model=binding.requested_model, bound_model=binding.bound_model,
            )
        except ProviderConnectionError:
            self.data_plane_status = "BLOCKED"
            raise
        text = str(doc.get("output_text") or "")
        if not text:
            for item in doc.get("output", []):
                if isinstance(item, Mapping):
                    for content in item.get("content", []):
                        if isinstance(content, Mapping) and content.get("type") == "output_text": text += str(content.get("text") or "")
        if not text:
            raise ProviderConnectionError("PROVIDER_EMPTY_RESPONSE", "Grok returned no output text", outcome_unknown=True, evidence=dict(self.last_request_evidence))
        try:
            parse_and_validate(text, schema)
        except ProviderConnectionError as exc:
            raise ProviderConnectionError("PROVIDER_SCHEMA_FAILURE", str(exc), outcome_unknown=True, evidence=dict(self.last_request_evidence)) from None
        actual_model = str(doc.get("model") or model)
        alias = actual_model != model
        alias_allowed = actual_model in self.allowed_models or actual_model.startswith(model + "-")
        if alias and not alias_allowed:
            self.data_plane_status = "BLOCKED_MODEL_BINDING"
            raise ProviderConnectionError("MODEL_BINDING_MISMATCH", "Grok response model is outside the pinned allowlist", outcome_unknown=True, evidence={**dict(self.last_request_evidence), "actual_model": actual_model})
        self.data_plane_status = "PASS"
        self.last_model_binding = ProviderModelBinding(
            self.provider_id, binding.requested_model, model, ModelBindingSource.RESPONSE_CONFIRMED,
            binding.profile_hash, self.catalog_status, "PASS", actual_model,
        )
        usage = dict(doc.get("usage") or {}); details = usage.get("input_tokens_details") or {}
        if isinstance(details, Mapping): usage["cache_read_tokens"] = details.get("cached_tokens", 0)
        usage.update(self.last_request_evidence)
        usage.update({
            "actual_model": actual_model, "binding_source": ModelBindingSource.RESPONSE_CONFIRMED.value,
            "catalog_status": self.catalog_status, "data_plane_status": self.data_plane_status,
            "model_binding_status": "RESPONSE_MODEL_ALIAS" if alias else "PASS",
        })
        return ProviderCompletion(text, actual_model, str(doc.get("id") or ""), usage, 1)

    def probe_connection(self) -> ProviderConnectionHealth:
        started = time.monotonic(); steps = ["static_config_pass"]; requested = self.preferred_models[0] if self.preferred_models else ""
        catalog_error = ""
        try:
            models = self.list_models(); steps.append("catalog_pass")
            if requested not in models: raise ProviderConnectionError("PROVIDER_CATALOG_MODEL_NOT_VISIBLE", "preferred Grok model is not visible")
        except ProviderConnectionError as exc:
            catalog_error = exc.error_class; steps.append("catalog_degraded")
            if exc.error_class == "PROVIDER_CATALOG_AUTH_FAILURE":
                return ProviderConnectionHealth(self.provider_id, "xai-control-and-data", "BLOCKED", "BLOCKED", requested, "", self.supports_structured_output(), "NOT_EVALUATED", int((time.monotonic()-started)*1000), exc.error_class, False, credential_present=self.credential_present, probe_steps=tuple(steps))
        try:
            schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
            completion = self.complete_structured(system="Return JSON.", user="Return {\"ok\": true}.", schema_name="connection_probe", schema=schema, config=ModelRoleConfig("worker", self.provider_id, self.default_timeout_seconds, 32, 0.0, self.reasoning_effort))
            steps.extend(("responses_text_pass", "json_schema_pass", "local_schema_pass"))
            return ProviderConnectionHealth(self.provider_id, "xai-control-and-data", "PASS", self.catalog_status, requested, completion.model, self.supports_structured_output(), "PASS", int((time.monotonic()-started)*1000), catalog_error, True, credential_present=self.credential_present, probe_steps=tuple(steps))
        except ProviderConnectionError as exc:
            return ProviderConnectionHealth(self.provider_id, "xai-control-and-data", "BLOCKED" if "AUTH" in exc.error_class or "KEY" in exc.error_class else "NOT_EVALUATED", self.catalog_status, requested, "", self.supports_structured_output(), "BLOCKED", int((time.monotonic()-started)*1000), exc.error_class, False, credential_present=self.credential_present, probe_steps=tuple(steps))

    def probe_data_plane_only(self) -> ProviderConnectionHealth:
        started = time.monotonic(); requested = self.preferred_models[0] if self.preferred_models else ""
        schema = {"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}
        try:
            completion = self.complete_structured(system="Return JSON.", user="Return {\"ok\": true}.", schema_name="data_plane_probe", schema=schema, config=ModelRoleConfig("worker", self.provider_id, self.default_timeout_seconds, 32, 0.0, self.reasoning_effort))
            return ProviderConnectionHealth(self.provider_id,"xai-data-plane","PASS",self.catalog_status,requested,completion.model,self.supports_structured_output(),"PASS",int((time.monotonic()-started)*1000),"",True,credential_present=self.credential_present,probe_steps=("profile_binding_pass","responses_text_pass","json_schema_pass"))
        except ProviderConnectionError as exc:
            return ProviderConnectionHealth(self.provider_id,"xai-data-plane","BLOCKED" if "AUTH" in exc.error_class else "NOT_EVALUATED",self.catalog_status,requested,"",self.supports_structured_output(),"BLOCKED",int((time.monotonic()-started)*1000),exc.error_class,False,credential_present=self.credential_present,probe_steps=("profile_binding_pass",))

    def connection_snapshot(self) -> ProviderConnectionSnapshot:
        return ProviderConnectionSnapshot(self.provider_id, "xai-inference", self.preferred_models[0] if self.preferred_models else "", self.supports_structured_output(), canonical_hash(self.profile), self.credential_present, {"api_backend": "RESPONSES", "reasoning_effort": self.reasoning_effort, "prompt_cache_policy": self.profile.get("prompt_cache_policy", "disabled_for_benchmark"), "catalog_status":self.catalog_status,"data_plane_status":self.data_plane_status,"last_model_binding":self.last_model_binding.as_dict() if self.last_model_binding else None})

