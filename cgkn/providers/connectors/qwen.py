from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping, Sequence
from urllib import error, request
from urllib.parse import urlparse

from ..client import ModelRoleConfig, ProviderCompletion
from ..connection_contracts import (
    ProviderConnectionError, ProviderConnectionHealth, ProviderConnectionSnapshot,
    StructuredOutputMode, canonical_hash,
)
from ..structured_output import parse_and_validate, resolve_credential, sanitize_vendor_text


_REGIONS = frozenset({"cn-beijing", "ap-southeast-1", "ap-northeast-1", "us-east-1", "eu-central-1", "cn-hongkong"})


class QwenConnector:
    provider_id = "qwen"

    def __init__(self, profile: Mapping[str, Any], *, environment: Mapping[str, str] | None = None) -> None:
        self.profile = dict(profile)
        self.environment = dict(os.environ if environment is None else environment)
        self.credential, self.credential_present = resolve_credential(self.environment, "CGKN_QWEN_API_KEY", "DASHSCOPE_API_KEY")
        self.region = str(self.environment.get("CGKN_QWEN_REGION") or self.profile.get("region") or "").strip()
        self.workspace_id = str(self.environment.get("CGKN_QWEN_WORKSPACE_ID") or self.profile.get("workspace_id") or "").strip()
        configured_url = str(self.environment.get("CGKN_QWEN_BASE_URL") or self.profile.get("base_url") or "").strip()
        self.base_url = configured_url.replace("{workspace_id}", self.workspace_id)
        self.catalog_base_url = str(self.profile.get("catalog_base_url") or self.base_url).replace("{workspace_id}", self.workspace_id)
        self.preferred_models = tuple(str(item) for item in self.profile.get("preferred_models", ()))
        self.timeout = int(self.profile.get("timeout", 120))
        self.max_output_tokens = int(self.profile.get("max_output_tokens", 4096))
        self._auth_failures = 0
        self._models_cache: tuple[str, ...] | None = None
        self._validate_static()

    def _validate_static(self) -> None:
        if self.region not in _REGIONS:
            raise ProviderConnectionError("QWEN_REGION_KEY_MISMATCH", "unsupported Qwen region")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith("maas.aliyuncs.com"):
            raise ProviderConnectionError("QWEN_PLAN_ENDPOINT_MISMATCH", "Qwen inference endpoint is not a Model Studio HTTPS host")
        if self.region not in parsed.hostname:
            raise ProviderConnectionError("QWEN_REGION_KEY_MISMATCH", "Qwen region and endpoint host do not match")
        if not self.workspace_id or parsed.hostname.split(".", 1)[0] != self.workspace_id:
            raise ProviderConnectionError("QWEN_WORKSPACE_NOT_FOUND", "Qwen workspace is not configured in the endpoint")
        if parsed.path.rstrip("/") != "/compatible-mode/v1":
            raise ProviderConnectionError("QWEN_PLAN_ENDPOINT_MISMATCH", "Qwen endpoint must use compatible-mode/v1")

    def classify_error(self, *, http_status: int | None, vendor_code: str = "", message: str = "") -> str:
        code = vendor_code.lower()
        text = message.lower()
        if http_status == 401:
            if "region" in code or "region" in text:
                return "QWEN_REGION_KEY_MISMATCH"
            if "workspace" in code or "workspace" in text:
                return "QWEN_WORKSPACE_UNAUTHORIZED"
            if any(item in code + text for item in ("invalid", "unauthorized", "authentication")):
                return "QWEN_INVALID_KEY"
            return "QWEN_AUTH_UNKNOWN"
        if http_status == 403:
            return "QWEN_WORKSPACE_UNAUTHORIZED"
        if http_status == 404:
            return "QWEN_WORKSPACE_NOT_FOUND"
        return "QWEN_AUTH_UNKNOWN" if http_status in {400, 401, 403} else "TRANSPORT_FAILURE"

    def _request_json(self, method: str, url: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.credential:
            raise ProviderConnectionError("QWEN_MISSING_AUTH", "Qwen credential is not configured")
        if self._auth_failures >= 2:
            raise ProviderConnectionError("QWEN_CONNECTION_BLOCKED_CREDENTIAL", "Qwen auth probe limit reached")
        encoded = None if payload is None else json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=encoded, headers={"Authorization": f"Bearer {self.credential}", "Content-Type": "application/json", "Accept": "application/json"}, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read(2_097_153)
            if len(raw) > 2_097_152:
                raise ProviderConnectionError("QWEN_RESPONSE_TOO_LARGE", "Qwen response exceeded the bounded size")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ProviderConnectionError("QWEN_INVALID_RESPONSE", "Qwen response root is not an object")
            return value
        except error.HTTPError as exc:
            body = exc.read(65_536)
            try:
                value = json.loads(body.decode("utf-8"))
            except Exception:
                value = {}
            raw_error = value.get("error", value) if isinstance(value, dict) else {}
            code = str(raw_error.get("code", "")) if isinstance(raw_error, Mapping) else ""
            message = sanitize_vendor_text(raw_error.get("message", f"Qwen HTTP {exc.code}") if isinstance(raw_error, Mapping) else f"Qwen HTTP {exc.code}", (self.credential,))
            category = self.classify_error(http_status=int(exc.code), vendor_code=code, message=message)
            if int(exc.code) == 401:
                self._auth_failures += 1
            raise ProviderConnectionError(category, message, http_status=int(exc.code)) from None
        except (TimeoutError, error.URLError, OSError) as exc:
            raise ProviderConnectionError("TIMEOUT" if isinstance(exc, TimeoutError) else "TRANSPORT_FAILURE", sanitize_vendor_text(getattr(exc, "reason", exc), (self.credential,))) from None

    def list_models(self) -> Sequence[str]:
        if self._models_cache is not None:
            return self._models_cache
        doc = self._request_json("GET", self.catalog_base_url.rstrip("/") + "/models")
        rows = doc.get("data", [])
        self._models_cache = tuple(str(row.get("id")) for row in rows if isinstance(row, Mapping) and row.get("id"))
        return self._models_cache

    def resolve_model(self, requested_model: str | None = None) -> str:
        model = str(requested_model or (self.preferred_models[0] if self.preferred_models else "")).strip()
        if not model:
            raise ProviderConnectionError("QWEN_MODEL_NOT_VISIBLE", "no Qwen model requested")
        if model not in self.list_models():
            raise ProviderConnectionError("QWEN_MODEL_NOT_VISIBLE", "requested Qwen model is not visible")
        return model

    def supports_structured_output(self) -> StructuredOutputMode:
        return StructuredOutputMode.NATIVE_JSON_SCHEMA

    def _completion(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", self.base_url.rstrip("/") + "/chat/completions", payload)

    def complete_structured(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        model = self.resolve_model(config.model if config.model != self.provider_id else None)
        doc = self._completion({"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": config.temperature, "max_tokens": min(config.max_output_tokens, self.max_output_tokens), "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": dict(schema)}}})
        choices = doc.get("choices", [])
        message = choices[0].get("message", {}) if choices and isinstance(choices[0], Mapping) else {}
        text = str(message.get("content", "")) if isinstance(message, Mapping) else ""
        parse_and_validate(text, schema)
        return ProviderCompletion(text, str(doc.get("model") or model), str(doc.get("id") or ""), dict(doc.get("usage") or {}), 1)

    def probe_connection(self) -> ProviderConnectionHealth:
        started = time.monotonic()
        steps: list[str] = ["static_config_pass"]
        requested = self.preferred_models[0] if self.preferred_models else ""
        try:
            models = self.list_models(); steps.append("catalog_pass")
            if requested not in models:
                raise ProviderConnectionError("QWEN_MODEL_NOT_VISIBLE", "preferred Qwen model is not visible")
            schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
            config = ModelRoleConfig("worker", requested, min(self.timeout, 120), 32, 0.0, "none")
            completion = self.complete_structured(system="Return JSON.", user="Return {\"ok\": true}.", schema_name="connection_probe", schema=schema, config=config)
            steps.extend(("text_pass", "json_object_pass", "json_schema_pass", "local_schema_pass"))
            return ProviderConnectionHealth(self.provider_id, self.region, "PASS", "PASS", requested, completion.model, self.supports_structured_output(), "PASS", int((time.monotonic() - started) * 1000), "", True, credential_present=self.credential_present, workspace_configured=bool(self.workspace_id), probe_steps=tuple(steps))
        except ProviderConnectionError as exc:
            return ProviderConnectionHealth(self.provider_id, self.region, "BLOCKED" if "AUTH" in exc.error_class or "KEY" in exc.error_class else "NOT_EVALUATED", "BLOCKED", requested, "", self.supports_structured_output(), "BLOCKED", int((time.monotonic() - started) * 1000), exc.error_class, False, credential_present=self.credential_present, workspace_configured=bool(self.workspace_id), probe_steps=tuple(steps))

    def connection_snapshot(self) -> ProviderConnectionSnapshot:
        safe = {"region": self.region, "workspace_configured": bool(self.workspace_id), "protocol": "openai-chat-completions"}
        return ProviderConnectionSnapshot(self.provider_id, self.region, self.preferred_models[0] if self.preferred_models else "", self.supports_structured_output(), canonical_hash({**self.profile, "workspace_id": bool(self.workspace_id)}), self.credential_present, safe)

