from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping, Sequence
from urllib import error, request
from urllib.parse import urlparse

from ..client import ModelRoleConfig, ProviderCompletion
from ..connection_contracts import ProviderConnectionError, ProviderConnectionHealth, ProviderConnectionSnapshot, StructuredOutputMode, canonical_hash
from ..structured_output import parse_and_validate, resolve_credential, sanitize_vendor_text


class GrokConnector:
    provider_id = "grok"

    def __init__(self, profile: Mapping[str, Any], *, environment: Mapping[str, str] | None = None) -> None:
        self.profile = dict(profile); self.environment = dict(os.environ if environment is None else environment)
        self.credential, self.credential_present = resolve_credential(self.environment, "CGKN_GROK_API_KEY", "XAI_API_KEY")
        self.base_url = str(self.environment.get("CGKN_GROK_BASE_URL") or self.profile.get("base_url") or "").rstrip("/")
        self.preferred_models = tuple(str(item) for item in self.profile.get("preferred_models", ()))
        self.reasoning_effort = str(self.profile.get("reasoning_effort", "medium"))
        self.timeout = int(self.profile.get("timeout", 120)); self.max_output_tokens = int(self.profile.get("max_output_tokens", 4096))
        self._auth_failures = 0; self._models_cache: tuple[str, ...] | None = None; self._validate_static()

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
        if http_status == 403: return "GROK_FORBIDDEN"
        if http_status == 404: return "GROK_MODEL_NOT_VISIBLE" if "model" in text else "GROK_ENDPOINT_ERROR"
        return "GROK_ENDPOINT_ERROR" if http_status else "TRANSPORT_FAILURE"

    def _request_json(self, method: str, url: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.credential: raise ProviderConnectionError("GROK_MISSING_AUTH", "Grok inference credential is not configured")
        if self._auth_failures >= 2: raise ProviderConnectionError("GROK_CONNECTION_BLOCKED_CREDENTIAL", "Grok auth probe limit reached")
        encoded = None if payload is None else json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=encoded, headers={"Authorization": f"Bearer {self.credential}", "Content-Type": "application/json", "Accept": "application/json"}, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout) as response: raw = response.read(2_097_153)
            if len(raw) > 2_097_152: raise ProviderConnectionError("GROK_RESPONSE_TOO_LARGE", "Grok response exceeded the bounded size")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict): raise ProviderConnectionError("GROK_INVALID_RESPONSE", "Grok response root is not an object")
            return value
        except error.HTTPError as exc:
            try: value = json.loads(exc.read(65_536).decode("utf-8"))
            except Exception: value = {}
            raw_error = value.get("error", value) if isinstance(value, dict) else {}
            code = str(raw_error.get("code", raw_error.get("type", ""))) if isinstance(raw_error, Mapping) else ""
            message = sanitize_vendor_text(raw_error.get("message", f"Grok HTTP {exc.code}") if isinstance(raw_error, Mapping) else f"Grok HTTP {exc.code}", (self.credential,))
            category = self.classify_error(http_status=int(exc.code), vendor_code=code, message=message)
            if int(exc.code) == 401: self._auth_failures += 1
            raise ProviderConnectionError(category, message, http_status=int(exc.code)) from None
        except (TimeoutError, error.URLError, OSError) as exc:
            raise ProviderConnectionError("TIMEOUT" if isinstance(exc, TimeoutError) else "TRANSPORT_FAILURE", sanitize_vendor_text(getattr(exc, "reason", exc), (self.credential,))) from None

    def list_models(self) -> Sequence[str]:
        if self._models_cache is not None: return self._models_cache
        doc = self._request_json("GET", self.base_url + "/models")
        self._models_cache = tuple(str(row.get("id")) for row in doc.get("data", []) if isinstance(row, Mapping) and row.get("id"))
        return self._models_cache

    def resolve_model(self, requested_model: str | None = None) -> str:
        model = str(requested_model or (self.preferred_models[0] if self.preferred_models else "")).strip()
        if not model or model not in self.list_models(): raise ProviderConnectionError("GROK_MODEL_NOT_VISIBLE", "requested Grok model is not visible")
        return model

    def supports_structured_output(self) -> StructuredOutputMode: return StructuredOutputMode.NATIVE_JSON_SCHEMA

    def complete_structured(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        model = self.resolve_model(config.model if config.model != self.provider_id else None)
        payload = {"model": model, "input": [{"role": "system", "content": system}, {"role": "user", "content": user}], "max_output_tokens": min(config.max_output_tokens, self.max_output_tokens), "reasoning": {"effort": config.reasoning_effort if config.reasoning_effort != "none" else self.reasoning_effort}, "store": False, "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": dict(schema)}}}
        doc = self._request_json("POST", self.base_url + "/responses", payload)
        text = str(doc.get("output_text") or "")
        if not text:
            for item in doc.get("output", []):
                if isinstance(item, Mapping):
                    for content in item.get("content", []):
                        if isinstance(content, Mapping) and content.get("type") == "output_text": text += str(content.get("text") or "")
        parse_and_validate(text, schema)
        usage = dict(doc.get("usage") or {}); details = usage.get("input_tokens_details") or {}
        if isinstance(details, Mapping): usage["cache_read_tokens"] = details.get("cached_tokens", 0)
        return ProviderCompletion(text, str(doc.get("model") or model), str(doc.get("id") or ""), usage, 1)

    def probe_connection(self) -> ProviderConnectionHealth:
        started = time.monotonic(); steps = ["static_config_pass"]; requested = self.preferred_models[0] if self.preferred_models else ""
        try:
            models = self.list_models(); steps.append("catalog_pass")
            if requested not in models: raise ProviderConnectionError("GROK_MODEL_NOT_VISIBLE", "preferred Grok model is not visible")
            schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
            completion = self.complete_structured(system="Return JSON.", user="Return {\"ok\": true}.", schema_name="connection_probe", schema=schema, config=ModelRoleConfig("worker", requested, min(self.timeout, 120), 32, 0.0, self.reasoning_effort))
            steps.extend(("responses_text_pass", "json_schema_pass", "local_schema_pass"))
            return ProviderConnectionHealth(self.provider_id, "xai-inference", "PASS", "PASS", requested, completion.model, self.supports_structured_output(), "PASS", int((time.monotonic()-started)*1000), "", True, credential_present=self.credential_present, probe_steps=tuple(steps))
        except ProviderConnectionError as exc:
            return ProviderConnectionHealth(self.provider_id, "xai-inference", "BLOCKED" if "AUTH" in exc.error_class or "KEY" in exc.error_class else "NOT_EVALUATED", "BLOCKED", requested, "", self.supports_structured_output(), "BLOCKED", int((time.monotonic()-started)*1000), exc.error_class, False, credential_present=self.credential_present, probe_steps=tuple(steps))

    def connection_snapshot(self) -> ProviderConnectionSnapshot:
        return ProviderConnectionSnapshot(self.provider_id, "xai-inference", self.preferred_models[0] if self.preferred_models else "", self.supports_structured_output(), canonical_hash(self.profile), self.credential_present, {"api_backend": "RESPONSES", "reasoning_effort": self.reasoning_effort, "prompt_cache_policy": self.profile.get("prompt_cache_policy", "disabled_for_benchmark")})

