from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from typing import Any, Mapping, Sequence
from urllib import error, request
from urllib.parse import urlparse

from ..client import ModelRoleConfig, ProviderCompletion
from ..connection_contracts import (ModelBindingSource, ProviderConnectionError, ProviderConnectionHealth,
                                    ProviderConnectionSnapshot, ProviderModelBinding, StructuredOutputMode, canonical_hash)
from ..structured_output import parse_and_validate, resolve_credential, sanitize_vendor_text
from ..supervision import ProviderOperationPolicyRegistry, ProviderRequestComplexity, SupervisedHttpTransport, SupervisionMode

_REGIONS = frozenset({"cn-beijing", "ap-southeast-1", "ap-northeast-1", "us-east-1", "eu-central-1", "cn-hongkong"})


class QwenConnector:
    provider_id = "qwen"

    def __init__(self, profile: Mapping[str, Any], *, environment: Mapping[str, str] | None = None,
                 transport: SupervisedHttpTransport | None = None, policies: ProviderOperationPolicyRegistry | None = None) -> None:
        self.profile = dict(profile); self.environment = dict(os.environ if environment is None else environment)
        self.credential, self.credential_present = resolve_credential(self.environment, "CGKN_QWEN_API_KEY", "DASHSCOPE_API_KEY")
        self.region = str(self.environment.get("CGKN_QWEN_REGION") or self.profile.get("region") or "").strip()
        self.workspace_id = str(self.environment.get("CGKN_QWEN_WORKSPACE_ID") or self.profile.get("workspace_id") or "").strip()
        configured_url = str(self.environment.get("CGKN_QWEN_BASE_URL") or self.profile.get("base_url") or "").strip()
        self.base_url = configured_url.replace("{workspace_id}", self.workspace_id)
        self.catalog_base_url = str(self.profile.get("catalog_base_url") or self.base_url).replace("{workspace_id}", self.workspace_id)
        self.preferred_models = tuple(str(item) for item in self.profile.get("preferred_models", ()))
        self.allowed_models = frozenset((*self.preferred_models, *(str(item) for item in self.profile.get("allowed_models", ()))))
        legacy = self.profile.get("timeout"); explicit = self.profile.get("default_timeout_seconds")
        if legacy is not None and explicit is not None and int(legacy) != int(explicit):
            raise ProviderConnectionError("CONFIG_CONFLICT", "timeout and default_timeout_seconds differ")
        try:
            self.default_timeout_seconds = int(explicit if explicit is not None else (legacy if legacy is not None else 120))
            self.max_timeout_seconds = int(self.profile.get("max_timeout_seconds", 360))
        except (TypeError, ValueError) as exc:
            raise ProviderConnectionError("QWEN_TIMEOUT_CONFIG_INVALID", "Qwen timeout values must be integers") from exc
        if not 0 < self.default_timeout_seconds <= self.max_timeout_seconds <= 600:
            raise ProviderConnectionError("QWEN_TIMEOUT_CONFIG_INVALID", "Qwen timeouts must satisfy 0 < default <= max <= 600")
        self.timeout = self.default_timeout_seconds; self.max_output_tokens = int(self.profile.get("max_output_tokens", 4096))
        self.transport = transport or SupervisedHttpTransport(); self.policies = policies or ProviderOperationPolicyRegistry()
        self._auth_failures = 0; self._models_cache: tuple[str, ...] | None = None
        self.catalog_status = "NOT_EVALUATED"; self.data_plane_status = "NOT_EVALUATED"; self.last_model_binding = None
        self.last_request_evidence: dict[str, Any] = {}; self._validate_static()

    def _validate_static(self) -> None:
        if self.region not in _REGIONS: raise ProviderConnectionError("QWEN_REGION_KEY_MISMATCH", "unsupported Qwen region")
        parsed = urlparse(self.base_url)
        is_public = parsed.hostname == "dashscope.aliyuncs.com"
        is_workspace = bool(parsed.hostname and parsed.hostname.endswith("maas.aliyuncs.com"))
        if parsed.scheme != "https" or not parsed.hostname or not (is_public or is_workspace):
            raise ProviderConnectionError("QWEN_PLAN_ENDPOINT_MISMATCH", "Qwen inference endpoint is not a Model Studio HTTPS host")
        if is_workspace and self.region not in parsed.hostname: raise ProviderConnectionError("QWEN_REGION_KEY_MISMATCH", "Qwen region and endpoint host do not match")
        if is_workspace and (not self.workspace_id or parsed.hostname.split(".", 1)[0] != self.workspace_id): raise ProviderConnectionError("QWEN_WORKSPACE_NOT_FOUND", "Qwen workspace is not configured in the endpoint")
        if parsed.path.rstrip("/") != "/compatible-mode/v1": raise ProviderConnectionError("QWEN_PLAN_ENDPOINT_MISMATCH", "Qwen endpoint must use compatible-mode/v1")

    def classify_error(self, *, http_status: int | None, vendor_code: str = "", message: str = "") -> str:
        code = vendor_code.lower(); text = message.lower()
        if http_status == 401:
            if "region" in code or "region" in text: return "QWEN_REGION_KEY_MISMATCH"
            if "workspace" in code or "workspace" in text: return "QWEN_WORKSPACE_UNAUTHORIZED"
            return "QWEN_INVALID_KEY" if any(x in code + text for x in ("invalid", "unauthorized", "authentication")) else "QWEN_AUTH_UNKNOWN"
        if http_status == 403: return "QWEN_WORKSPACE_UNAUTHORIZED"
        if http_status == 404: return "QWEN_WORKSPACE_NOT_FOUND"
        return "QWEN_AUTH_UNKNOWN" if http_status in {400, 401, 403} else "TRANSPORT_FAILURE"

    def _request_json(self, method: str, url: str, payload: Mapping[str, Any] | None = None, *, config: ModelRoleConfig | None = None, model: str = "") -> dict[str, Any]:
        if not self.credential: raise ProviderConnectionError("QWEN_MISSING_AUTH", "Qwen credential is not configured")
        if self._auth_failures >= 2: raise ProviderConnectionError("QWEN_CONNECTION_BLOCKED_CREDENTIAL", "Qwen auth probe limit reached")
        task_class = config.task_class if config else "connection.probe"; operation = config.operation if config else "MODEL_CATALOG"
        policy = self.policies.get(task_class, operation)
        if config is not None: policy = replace(policy, supervision_mode=SupervisionMode.DEADLINE_ONLY)
        encoded = None if payload is None else json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        complexity = ProviderRequestComplexity(0, len(encoded or b""), 0, 0, 0, 0, config.max_output_tokens if config else 128, task_class, self.provider_id, model)
        try:
            response = self.transport.send(method=method, url=url, headers={"Authorization": f"Bearer {self.credential}", "Content-Type": "application/json", "Accept": "application/json"}, body=encoded, provider_id=self.provider_id, model=model or self.provider_id, policy=policy, complexity=complexity)
            self.last_request_evidence = self.transport.usage(response.receipt); value = json.loads(response.body.decode("utf-8"))
            if not isinstance(value, dict): raise ProviderConnectionError("QWEN_INVALID_RESPONSE", "Qwen response root is not an object")
            return value
        except error.HTTPError as exc:
            body = exc.read(65_536)
            try: value = json.loads(body.decode("utf-8"))
            except Exception: value = {}
            raw_error = value.get("error", value) if isinstance(value, dict) else {}; code = str(raw_error.get("code", "")) if isinstance(raw_error, Mapping) else ""
            message = sanitize_vendor_text(raw_error.get("message", f"Qwen HTTP {exc.code}") if isinstance(raw_error, Mapping) else f"Qwen HTTP {exc.code}", (self.credential,))
            if int(exc.code) == 401: self._auth_failures += 1
            raise ProviderConnectionError(self.classify_error(http_status=int(exc.code), vendor_code=code, message=message), message, http_status=int(exc.code)) from None

    def list_models(self) -> Sequence[str]:
        if self._models_cache is not None: return self._models_cache
        doc = self._request_json("GET", self.catalog_base_url.rstrip("/") + "/models"); self._models_cache = tuple(str(row.get("id")) for row in doc.get("data", []) if isinstance(row, Mapping) and row.get("id")); self.catalog_status = "PASS"; return self._models_cache

    def resolve_model(self, requested_model: str | None = None) -> str:
        model = str(requested_model or (self.preferred_models[0] if self.preferred_models else "")).strip()
        if not model or model not in self.list_models(): raise ProviderConnectionError("QWEN_MODEL_NOT_VISIBLE", "requested Qwen model is not visible")
        return model

    def resolve_pinned_model(self, requested_model: str | None = None) -> ProviderModelBinding:
        requested = str(requested_model or self.provider_id).strip(); bound = self.preferred_models[0] if requested == self.provider_id else requested
        if not bound or bound not in self.allowed_models: raise ProviderConnectionError("QWEN_MODEL_NOT_ALLOWED", "requested Qwen model is outside the profile allowlist")
        return ProviderModelBinding(self.provider_id, requested, bound, ModelBindingSource.PROFILE_PINNED, canonical_hash(self.profile), self.catalog_status, "NOT_EVALUATED")

    def supports_structured_output(self) -> StructuredOutputMode: return StructuredOutputMode.NATIVE_JSON_SCHEMA

    def complete_structured(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        binding = self.resolve_pinned_model(config.model); model = binding.bound_model
        payload = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": config.temperature, "max_tokens": min(config.max_output_tokens, self.max_output_tokens), "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": dict(schema)}}}
        doc = self._request_json("POST", self.base_url.rstrip("/") + "/chat/completions", payload, config=config, model=model)
        choices = doc.get("choices", []); message = choices[0].get("message", {}) if choices and isinstance(choices[0], Mapping) else {}; text = str(message.get("content", "")) if isinstance(message, Mapping) else ""; parse_and_validate(text, schema)
        actual = str(doc.get("model") or model)
        if actual != model and actual not in self.allowed_models and not actual.startswith(model + "-"): raise ProviderConnectionError("MODEL_BINDING_MISMATCH", "Qwen response model is outside the pinned allowlist", outcome_unknown=True)
        self.data_plane_status = "PASS"; self.last_model_binding = ProviderModelBinding(self.provider_id, binding.requested_model, model, ModelBindingSource.RESPONSE_CONFIRMED, binding.profile_hash, self.catalog_status, "PASS", actual)
        usage = dict(doc.get("usage") or {}); usage.update(self.last_request_evidence); usage.update({"requested_model":binding.requested_model,"bound_model":model,"actual_model":actual,"binding_source":ModelBindingSource.RESPONSE_CONFIRMED.value,"profile_hash":binding.profile_hash,"model_binding_status":"PASS" if actual == model else "RESPONSE_MODEL_ALIAS"})
        return ProviderCompletion(text, actual, str(doc.get("id") or ""), usage, 1)

    def probe_connection(self) -> ProviderConnectionHealth:
        started=time.monotonic(); requested=self.preferred_models[0] if self.preferred_models else ""; steps=["static_config_pass"]
        try:
            models=self.list_models(); steps.append("catalog_pass")
            if requested not in models: raise ProviderConnectionError("QWEN_MODEL_NOT_VISIBLE", "preferred Qwen model is not visible")
            schema={"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}
            completion=self.complete_structured(system="Return JSON.",user='Return {"ok": true}.',schema_name="connection_probe",schema=schema,config=ModelRoleConfig("worker",requested,self.default_timeout_seconds,32,task_class="connection.probe"))
            return ProviderConnectionHealth(self.provider_id,self.region,"PASS","PASS",requested,completion.model,self.supports_structured_output(),"PASS",int((time.monotonic()-started)*1000),"",True,credential_present=self.credential_present,workspace_configured=bool(self.workspace_id),probe_steps=tuple(steps))
        except ProviderConnectionError as exc:
            return ProviderConnectionHealth(self.provider_id,self.region,"BLOCKED" if "AUTH" in exc.error_class or "KEY" in exc.error_class else "NOT_EVALUATED",self.catalog_status,requested,"",self.supports_structured_output(),"BLOCKED",int((time.monotonic()-started)*1000),exc.error_class,False,credential_present=self.credential_present,workspace_configured=bool(self.workspace_id),probe_steps=tuple(steps))

    def connection_snapshot(self) -> ProviderConnectionSnapshot:
        return ProviderConnectionSnapshot(self.provider_id,self.region,self.preferred_models[0] if self.preferred_models else "",self.supports_structured_output(),canonical_hash({**self.profile,"workspace_id":bool(self.workspace_id)}),self.credential_present,{"region":self.region,"workspace_configured":bool(self.workspace_id),"protocol":"openai-chat-completions","catalog_status":self.catalog_status,"data_plane_status":self.data_plane_status})
