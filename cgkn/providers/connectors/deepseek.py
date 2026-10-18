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


class DeepSeekConnector:
    provider_id = "deepseek"

    def __init__(self, profile: Mapping[str, Any], *, environment: Mapping[str, str] | None = None,
                 transport: SupervisedHttpTransport | None = None, policies: ProviderOperationPolicyRegistry | None = None) -> None:
        self.profile=dict(profile); self.environment=dict(os.environ if environment is None else environment)
        self.credential,self.credential_present=resolve_credential(self.environment,"CGKN_DEEPSEEK_API_KEY","DEEPSEEK_API_KEY")
        self.base_url=str(self.environment.get("CGKN_DEEPSEEK_BASE_URL") or self.profile.get("base_url") or "").rstrip("/")
        self.preferred_models=tuple(str(item) for item in self.profile.get("preferred_models",())); self.allowed_models=frozenset((*self.preferred_models,*(str(item) for item in self.profile.get("allowed_models",()))))
        legacy=self.profile.get("timeout"); explicit=self.profile.get("default_timeout_seconds")
        if legacy is not None and explicit is not None and int(legacy)!=int(explicit): raise ProviderConnectionError("CONFIG_CONFLICT","timeout and default_timeout_seconds differ")
        try:
            self.default_timeout_seconds=int(explicit if explicit is not None else (legacy if legacy is not None else 120)); self.max_timeout_seconds=int(self.profile.get("max_timeout_seconds",360))
        except (TypeError,ValueError) as exc: raise ProviderConnectionError("DEEPSEEK_TIMEOUT_CONFIG_INVALID","DeepSeek timeout values must be integers") from exc
        if not 0<self.default_timeout_seconds<=self.max_timeout_seconds<=600: raise ProviderConnectionError("DEEPSEEK_TIMEOUT_CONFIG_INVALID","DeepSeek timeouts must satisfy 0 < default <= max <= 600")
        self.timeout=self.default_timeout_seconds; self.max_output_tokens=int(self.profile.get("max_output_tokens",4096)); self.transport=transport or SupervisedHttpTransport(); self.policies=policies or ProviderOperationPolicyRegistry()
        self._auth_failures=0; self._models_cache:tuple[str,...]|None=None; self.catalog_status="NOT_EVALUATED"; self.data_plane_status="NOT_EVALUATED"; self.last_request_evidence={}; self.last_model_binding=None
        parsed=urlparse(self.base_url)
        if parsed.scheme!="https" or not parsed.hostname: raise ProviderConnectionError("DEEPSEEK_ENDPOINT_ERROR","DeepSeek endpoint must be HTTPS")

    def classify_error(self,*,http_status:int|None,vendor_code:str="",message:str="")->str:
        if http_status==401:return "DEEPSEEK_INVALID_API_KEY"
        if http_status==403:return "DEEPSEEK_FORBIDDEN"
        if http_status==404:return "DEEPSEEK_MODEL_NOT_VISIBLE"
        return "DEEPSEEK_ENDPOINT_ERROR" if http_status else "TRANSPORT_FAILURE"

    def _request_json(self,method:str,url:str,payload:Mapping[str,Any]|None=None,*,config:ModelRoleConfig|None=None,model:str="")->dict[str,Any]:
        if not self.credential: raise ProviderConnectionError("DEEPSEEK_MISSING_AUTH","DeepSeek credential is not configured")
        if self._auth_failures>=2: raise ProviderConnectionError("DEEPSEEK_CONNECTION_BLOCKED_CREDENTIAL","DeepSeek auth probe limit reached")
        task=config.task_class if config else "connection.probe"; operation=config.operation if config else "MODEL_CATALOG"; policy=self.policies.get(task,operation)
        if config is not None: policy=replace(policy,supervision_mode=SupervisionMode.DEADLINE_ONLY)
        encoded=None if payload is None else json.dumps(dict(payload),ensure_ascii=False).encode("utf-8")
        complexity=ProviderRequestComplexity(0,len(encoded or b""),0,0,0,0,config.max_output_tokens if config else 128,task,self.provider_id,model)
        try:
            response=self.transport.send(method=method,url=url,headers={"Authorization":f"Bearer {self.credential}","Content-Type":"application/json","Accept":"application/json"},body=encoded,provider_id=self.provider_id,model=model or self.provider_id,policy=policy,complexity=complexity)
            self.last_request_evidence=self.transport.usage(response.receipt); value=json.loads(response.body.decode("utf-8"))
            if not isinstance(value,dict): raise ProviderConnectionError("DEEPSEEK_INVALID_RESPONSE","DeepSeek response root is not an object")
            return value
        except error.HTTPError as exc:
            if int(exc.code)==401:self._auth_failures+=1
            message=sanitize_vendor_text(exc.read(65_536).decode("utf-8","replace"),(self.credential,))
            raise ProviderConnectionError(self.classify_error(http_status=int(exc.code),message=message),message,http_status=int(exc.code)) from None

    def list_models(self)->Sequence[str]:
        if self._models_cache is not None:return self._models_cache
        doc=self._request_json("GET",self.base_url+"/models"); self._models_cache=tuple(str(row.get("id")) for row in doc.get("data",[]) if isinstance(row,Mapping) and row.get("id")); self.catalog_status="PASS"; return self._models_cache

    def resolve_model(self,requested_model:str|None=None)->str:
        model=str(requested_model or (self.preferred_models[0] if self.preferred_models else "")).strip()
        if not model or model not in self.list_models(): raise ProviderConnectionError("DEEPSEEK_MODEL_NOT_VISIBLE","requested DeepSeek model is not visible")
        return model

    def resolve_pinned_model(self,requested_model:str|None=None)->ProviderModelBinding:
        requested=str(requested_model or self.provider_id).strip(); bound=self.preferred_models[0] if requested==self.provider_id else requested
        if not bound or bound not in self.allowed_models: raise ProviderConnectionError("DEEPSEEK_MODEL_NOT_ALLOWED","requested DeepSeek model is outside the profile allowlist")
        return ProviderModelBinding(self.provider_id,requested,bound,ModelBindingSource.PROFILE_PINNED,canonical_hash(self.profile),self.catalog_status,"NOT_EVALUATED")

    def supports_structured_output(self)->StructuredOutputMode:return StructuredOutputMode.PROMPT_JSON_LOCAL_VALIDATE

    def _complete_text(self,model:str,system:str,user:str,max_tokens:int,config:ModelRoleConfig)->ProviderCompletion:
        doc=self._request_json("POST",self.base_url+"/chat/completions",{"model":model,"messages":[{"role":"system","content":system},{"role":"user","content":user}],"temperature":0.0,"max_tokens":min(max_tokens,self.max_output_tokens),"response_format":{"type":"json_object"}},config=config,model=model)
        choices=doc.get("choices",[]); message=choices[0].get("message",{}) if choices and isinstance(choices[0],Mapping) else {}; actual=str(doc.get("model") or model)
        if actual!=model and actual not in self.allowed_models and not actual.startswith(model+"-"): raise ProviderConnectionError("MODEL_BINDING_MISMATCH","DeepSeek response model is outside the pinned allowlist",outcome_unknown=True)
        usage=dict(doc.get("usage") or {}); usage.update(self.last_request_evidence); usage.update({"requested_model":config.model,"bound_model":model,"actual_model":actual,"binding_source":ModelBindingSource.RESPONSE_CONFIRMED.value,"profile_hash":canonical_hash(self.profile),"model_binding_status":"PASS" if actual==model else "RESPONSE_MODEL_ALIAS"})
        return ProviderCompletion(str(message.get("content") or ""),actual,str(doc.get("id") or ""),usage,1)

    def complete_structured(self,*,system:str,user:str,schema_name:str,schema:Mapping[str,Any],config:ModelRoleConfig)->ProviderCompletion:
        binding=self.resolve_pinned_model(config.model); model=binding.bound_model; schema_text=json.dumps(dict(schema),ensure_ascii=False,sort_keys=True)
        completion=self._complete_text(model,system+"\nReturn only one JSON object matching this schema: "+schema_text,user,config.max_output_tokens,config)
        try: parse_and_validate(completion.text,schema); result=completion
        except ProviderConnectionError:
            try: original=json.loads(completion.text)
            except Exception: original=None
            repaired=self._complete_text(model,"Preserve the semantic answer; only transform it into the supplied schema. Return JSON only. Schema: "+schema_text,completion.text,config.max_output_tokens,config); value=parse_and_validate(repaired.text,schema)
            if isinstance(original,Mapping):
                for key,item in original.items():
                    if key in value and value[key]!=item: raise ProviderConnectionError("DEEPSEEK_FORMAT_REPAIR_CHANGED_SEMANTICS","format-only repair changed an existing semantic value")
            result=ProviderCompletion(repaired.text,repaired.model,repaired.request_id,repaired.usage,2)
        self.data_plane_status="PASS"; self.last_model_binding=ProviderModelBinding(self.provider_id,binding.requested_model,model,ModelBindingSource.RESPONSE_CONFIRMED,binding.profile_hash,self.catalog_status,"PASS",result.model); return result

    def probe_connection(self)->ProviderConnectionHealth:
        started=time.monotonic(); requested=self.preferred_models[0] if self.preferred_models else ""; steps=["static_config_pass"]
        try:
            models=self.list_models();steps.append("catalog_pass")
            if requested not in models:raise ProviderConnectionError("DEEPSEEK_MODEL_NOT_VISIBLE","preferred model is not visible")
            schema={"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}; completion=self.complete_structured(system="Return JSON.",user='Return {"ok": true}.',schema_name="connection_probe",schema=schema,config=ModelRoleConfig("worker",requested,self.default_timeout_seconds,32,task_class="connection.probe"))
            return ProviderConnectionHealth(self.provider_id,"deepseek","PASS","PASS",requested,completion.model,self.supports_structured_output(),"PASS",int((time.monotonic()-started)*1000),"",True,credential_present=self.credential_present,probe_steps=tuple(steps))
        except ProviderConnectionError as exc:return ProviderConnectionHealth(self.provider_id,"deepseek","BLOCKED" if "AUTH" in exc.error_class or "KEY" in exc.error_class else "NOT_EVALUATED",self.catalog_status,requested,"",self.supports_structured_output(),"BLOCKED",int((time.monotonic()-started)*1000),exc.error_class,False,credential_present=self.credential_present,probe_steps=tuple(steps))

    def connection_snapshot(self)->ProviderConnectionSnapshot:return ProviderConnectionSnapshot(self.provider_id,"deepseek-inference",self.preferred_models[0] if self.preferred_models else "",self.supports_structured_output(),canonical_hash(self.profile),self.credential_present,{"protocol":"openai-chat-completions","catalog_status":self.catalog_status,"data_plane_status":self.data_plane_status})
