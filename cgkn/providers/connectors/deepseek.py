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


class DeepSeekConnector:
    provider_id = "deepseek"

    def __init__(self, profile: Mapping[str, Any], *, environment: Mapping[str, str] | None = None) -> None:
        self.profile = dict(profile); self.environment = dict(os.environ if environment is None else environment)
        self.credential, self.credential_present = resolve_credential(self.environment, "CGKN_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY")
        self.base_url = str(self.environment.get("CGKN_DEEPSEEK_BASE_URL") or self.profile.get("base_url") or "").rstrip("/")
        self.preferred_models = tuple(str(item) for item in self.profile.get("preferred_models", ()))
        self.timeout = int(self.profile.get("timeout", 120)); self.max_output_tokens = int(self.profile.get("max_output_tokens", 4096)); self._auth_failures = 0
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname: raise ProviderConnectionError("DEEPSEEK_ENDPOINT_ERROR", "DeepSeek endpoint must be HTTPS")

    def classify_error(self, *, http_status: int | None, vendor_code: str = "", message: str = "") -> str:
        if http_status == 401: return "DEEPSEEK_INVALID_API_KEY"
        if http_status == 403: return "DEEPSEEK_FORBIDDEN"
        if http_status == 404: return "DEEPSEEK_MODEL_NOT_VISIBLE"
        return "DEEPSEEK_ENDPOINT_ERROR" if http_status else "TRANSPORT_FAILURE"

    def _request_json(self, method: str, url: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.credential: raise ProviderConnectionError("DEEPSEEK_MISSING_AUTH", "DeepSeek credential is not configured")
        if self._auth_failures >= 2: raise ProviderConnectionError("DEEPSEEK_CONNECTION_BLOCKED_CREDENTIAL", "DeepSeek auth probe limit reached")
        encoded = None if payload is None else json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=encoded, headers={"Authorization": f"Bearer {self.credential}", "Content-Type": "application/json", "Accept": "application/json"}, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout) as response: raw = response.read(2_097_153)
            if len(raw) > 2_097_152: raise ProviderConnectionError("DEEPSEEK_RESPONSE_TOO_LARGE", "DeepSeek response exceeded the bounded size")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict): raise ProviderConnectionError("DEEPSEEK_INVALID_RESPONSE", "DeepSeek response root is not an object")
            return value
        except error.HTTPError as exc:
            if int(exc.code) == 401: self._auth_failures += 1
            message = sanitize_vendor_text(exc.read(65_536).decode("utf-8", "replace"), (self.credential,))
            raise ProviderConnectionError(self.classify_error(http_status=int(exc.code), message=message), message, http_status=int(exc.code)) from None
        except (TimeoutError, error.URLError, OSError) as exc:
            raise ProviderConnectionError("TIMEOUT" if isinstance(exc, TimeoutError) else "TRANSPORT_FAILURE", sanitize_vendor_text(getattr(exc, "reason", exc), (self.credential,))) from None

    def list_models(self) -> Sequence[str]:
        doc = self._request_json("GET", self.base_url + "/models")
        return tuple(str(row.get("id")) for row in doc.get("data", []) if isinstance(row, Mapping) and row.get("id"))

    def resolve_model(self, requested_model: str | None = None) -> str:
        model = str(requested_model or (self.preferred_models[0] if self.preferred_models else "")).strip()
        if not model or model not in self.list_models(): raise ProviderConnectionError("DEEPSEEK_MODEL_NOT_VISIBLE", "requested DeepSeek model is not visible")
        return model

    def supports_structured_output(self) -> StructuredOutputMode: return StructuredOutputMode.PROMPT_JSON_LOCAL_VALIDATE

    def _complete_text(self, model: str, system: str, user: str, max_tokens: int) -> ProviderCompletion:
        doc = self._request_json("POST", self.base_url + "/chat/completions", {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0.0, "max_tokens": min(max_tokens, self.max_output_tokens), "response_format": {"type": "json_object"}})
        choices = doc.get("choices", []); message = choices[0].get("message", {}) if choices and isinstance(choices[0], Mapping) else {}
        return ProviderCompletion(str(message.get("content") or ""), str(doc.get("model") or model), str(doc.get("id") or ""), dict(doc.get("usage") or {}), 1)

    def complete_structured(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        model = self.resolve_model(config.model if config.model != self.provider_id else None)
        schema_text = json.dumps(dict(schema), ensure_ascii=False, sort_keys=True)
        completion = self._complete_text(model, system + "\nReturn only one JSON object matching this schema: " + schema_text, user, config.max_output_tokens)
        try:
            parse_and_validate(completion.text, schema); return completion
        except ProviderConnectionError:
            try:
                original = json.loads(completion.text)
            except Exception:
                original = None
            repaired = self._complete_text(model, "Preserve the semantic answer; only transform it into the supplied schema. Return JSON only. Schema: " + schema_text, completion.text, config.max_output_tokens)
            value = parse_and_validate(repaired.text, schema)
            if isinstance(original, Mapping):
                for key, item in original.items():
                    if key in value and value[key] != item:
                        raise ProviderConnectionError("DEEPSEEK_FORMAT_REPAIR_CHANGED_SEMANTICS", "format-only repair changed an existing semantic value")
            return ProviderCompletion(repaired.text, repaired.model, repaired.request_id, repaired.usage, 2)

    def probe_connection(self) -> ProviderConnectionHealth:
        started = time.monotonic(); steps = ["static_config_pass"]; requested = self.preferred_models[0] if self.preferred_models else ""
        try:
            models = self.list_models(); steps.append("catalog_pass")
            if requested not in models: raise ProviderConnectionError("DEEPSEEK_MODEL_NOT_VISIBLE", "preferred DeepSeek model is not visible")
            schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
            completion = self.complete_structured(system="Return JSON.", user="Return {\"ok\": true}.", schema_name="connection_probe", schema=schema, config=ModelRoleConfig("worker", requested, min(self.timeout, 120), 32, 0.0, "none"))
            steps.extend(("json_object_pass", "local_schema_pass"))
            return ProviderConnectionHealth(self.provider_id, "deepseek-inference", "PASS", "PASS", requested, completion.model, self.supports_structured_output(), "PASS", int((time.monotonic()-started)*1000), "", True, credential_present=self.credential_present, probe_steps=tuple(steps))
        except ProviderConnectionError as exc:
            return ProviderConnectionHealth(self.provider_id, "deepseek-inference", "BLOCKED" if "AUTH" in exc.error_class or "KEY" in exc.error_class else "NOT_EVALUATED", "BLOCKED", requested, "", self.supports_structured_output(), "BLOCKED", int((time.monotonic()-started)*1000), exc.error_class, False, credential_present=self.credential_present, probe_steps=tuple(steps))

    def connection_snapshot(self) -> ProviderConnectionSnapshot:
        return ProviderConnectionSnapshot(self.provider_id, "deepseek-inference", self.preferred_models[0] if self.preferred_models else "", self.supports_structured_output(), canonical_hash(self.profile), self.credential_present, {"format_repairs_max": 1, "protocol": "openai-chat-completions"})

