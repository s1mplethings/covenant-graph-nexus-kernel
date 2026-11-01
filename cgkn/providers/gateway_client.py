from __future__ import annotations

import hashlib
import json
import os
import re
import time
import math
from dataclasses import dataclass, field, replace
from typing import Any, Mapping
from pathlib import Path
from urllib import error, request
from urllib.parse import urlparse

from scripts import provider_api_budget

from .client import CompletionClient, ModelRoleConfig, ProviderCompletion, parse_json_object


MAX_RESPONSE_BYTES = 2_097_152
MAX_REQUEST_BYTES = 1_048_576


def _raw_finish_reason(doc):
    choices=doc.get('choices')
    if isinstance(choices,list) and choices and isinstance(choices[0],dict):
        return choices[0].get('finish_reason')
    return doc.get('status')


def _open_loopback(req,timeout):
    return request.build_opener(request.ProxyHandler({})).open(req,timeout=timeout)


class GatewayCompletionError(RuntimeError):
    def __init__(self, category: str, message: str, *, http_status: int | None = None, outcome_unknown: bool = False) -> None:
        self.category = category
        self.http_status = http_status
        self.outcome_unknown = outcome_unknown
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


def _validate_terminal(doc,method,config):
    if not isinstance(doc,dict) or not isinstance(doc.get('cgkn_stream'),dict) or doc['cgkn_stream'].get('completed') is not True:
        raise GatewayCompletionError('stream_terminal_missing','No validated upstream stream terminal',outcome_unknown=True)
    if method=='responses' and doc.get('status')!='completed':
        raise GatewayCompletionError('truncated_response','Explicit completed state required',outcome_unknown=True)
    if method=='chat_completions':
        choices=doc.get('choices') or []
        if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict) or choices[0].get('finish_reason')!='stop':
            raise GatewayCompletionError('truncated_response','Text completion must stop normally',outcome_unknown=True)
    usage=doc.get('usage') or {}
    if not isinstance(usage,dict):raise GatewayCompletionError('usage_unknown','Invalid usage object',outcome_unknown=True)
    counts=[usage.get('prompt_tokens',usage.get('input_tokens')),usage.get('completion_tokens',usage.get('output_tokens'))]
    if any(not isinstance(v,int) or isinstance(v,bool) or v<0 for v in counts):
        raise GatewayCompletionError('usage_unknown','Complete token usage required for admission',outcome_unknown=True)
    route=doc.get('cgkn_model_identity') or {}
    if (not isinstance(route,dict) or route.get('provider_id')!=config.model or route.get('identity_status')!='MATCH' or
        not doc.get('model') or doc['model']!=route.get('actual_model') or doc['model']!=route.get('requested_model') or
        (config.model_id and doc['model']!=config.model_id) or not doc.get('id')):
        raise GatewayCompletionError('model_identity_mismatch','Completed response does not match admitted model route',outcome_unknown=True)
    if route.get('bound_model',route.get('requested_model')) != route.get('requested_model'):
        raise GatewayCompletionError('model_identity_mismatch','Bound model differs from pinned request',outcome_unknown=True)
    # Backward-compatible exact binding for old gateways. Never infer an alias.
    route.setdefault('bound_model',route['requested_model'])
    route.setdefault('binding_policy',{'kind':'exact','aliases':[]})


@dataclass(frozen=True)
class GatewayCompletionClient:
    base_url: str
    access_token: str = field(repr=False)
    api_method: str = "responses"
    run_id: str = ""
    case_id: str = ""
    enforce_budget: bool = True
    execution_policy: str = "limited"
    authorization_reference: str | None = None
    input_token_ceiling: int | None = None
    setup_seconds: float = 60
    initial_progress_seconds: float = 180
    progress_idle_seconds: float = 120

    def __post_init__(self) -> None:
        if self.input_token_ceiling is not None and (type(self.input_token_ceiling) is not int or self.input_token_ceiling<1):raise ValueError("INVALID_INPUT_CEILING")
        from .streaming_sse import MeaningfulProgressWatchdog
        MeaningfulProgressWatchdog(self.initial_progress_seconds,self.progress_idle_seconds)
        if isinstance(self.setup_seconds,bool) or not isinstance(self.setup_seconds,(int,float)) or not math.isfinite(self.setup_seconds) or self.setup_seconds<=0:
            raise ValueError('INVALID_SETUP_TIMEOUT')
        if self.execution_policy not in {"limited", "accounting_only"}:
            raise ValueError("invalid execution policy")
        if self.execution_policy == "accounting_only" and not self.authorization_reference:
            raise ValueError("accounting-only policy requires authorization reference")
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

    def reconnect(self) -> "GatewayCompletionClient":
        """Rebuild transport only; caller chooses whether a NEW request is permitted."""
        from .application_network import settings,session
        application=settings()
        if not application:raise GatewayCompletionError('not_domestic','No saved domestic profile')
        info,_=session(application)
        return replace(self,base_url=info['base_url'],access_token=info['access_token'])

    def bind_run(self, run_id: str, case_id: str) -> "GatewayCompletionClient":
        return replace(self, run_id=str(run_id), case_id=str(case_id))

    def models(self, provider: str) -> dict[str, Any]:
        if provider not in {'qwen','deepseek'}:
            raise ValueError('DOMESTIC_PROVIDER_NOT_ALLOWED')
        from .application_network import settings,session
        config=settings()
        if config:
            info,_=session(config,autostart=False)
            if _loopback_base_url(info['base_url'])!=self.base_url or info['access_token']!=self.access_token:
                raise GatewayCompletionError('domestic_gateway_changed','Use client.reconnect() for new requests; unknown submissions must not be replayed')
        req=request.Request(self.base_url+'/v1/network/models/'+provider,
                            headers={'Authorization':'Bearer '+self.access_token})
        try:
            with _open_loopback(req,timeout=35) as response:
                return json.load(response)
        except error.HTTPError as exc:
            # The authenticated diagnostic envelope is evidence even on local 503.
            # Never replace it with HTTPError or expose arbitrary response text.
            try: doc=json.loads(exc.read(256*1024))
            except (ValueError,TypeError): doc={}
            finally: exc.close()
            allowed={'request_id','provider','gateway_pid','gateway_session_id','network_sha256',
                'interface_guid','inbound','runtime_source_sha256','generation_calls','scope',
                'route_id','reason','exception_type','last_completed_stage','stages','trace','observed_progress',
                'os_connections','outcome','upstream_http_status','started','ended'}
            row={key:value for key,value in doc.items() if key in allowed} if isinstance(doc,dict) else {}
            row.update(provider=provider,ok=False,gateway_http_status=exc.code,generation_calls=0)
            row.setdefault('upstream_http_status',None)
            row.setdefault('reason','GATEWAY_DIAGNOSTIC_HTTP_ERROR')
            return row

    def recover_cached(self, *, request_identity: str, schema: Mapping[str, Any] | None,
                       cache_dir: Path | None = None) -> ProviderCompletion | None:
        """Read-only recovery: no session startup, reservation, POST or ledger edit.

        The caller must match the identity to the original recorded request, then
        pass the result through the original Agent/Worker admission contract.
        A miss returns None; it never falls through to complete().
        """
        identity=request_identity.removeprefix('sha256:')
        if not re.fullmatch('[0-9a-f]{64}',identity):raise ValueError('Invalid recovery identity')
        if cache_dir is None:
            doc=provider_api_budget.load_cached_response(identity)
        else:
            path=Path(cache_dir)/identity[:2]/(identity+'.json')
            if not path.is_file():return None
            if path.stat().st_size>MAX_RESPONSE_BYTES*4:
                raise GatewayCompletionError('invalid_cached_response','Recovery file exceeds bound')
            try:envelope=json.loads(path.read_text(encoding='utf-8'))
            except (ValueError,OSError):raise GatewayCompletionError('invalid_cached_response','Unreadable recovery file') from None
            if not isinstance(envelope,dict) or envelope.get('request_identity')!=identity or envelope.get('call_mode')!='CACHE_REPLAY':
                raise GatewayCompletionError('invalid_cached_response','Recovery identity mismatch')
            doc=envelope.get('response')
        if doc is None:return None
        if not isinstance(doc,dict) or (self.api_method=='responses' and doc.get('status')!='completed'):
            raise GatewayCompletionError('invalid_cached_response','Recovery response incomplete')
        if len(json.dumps(doc,ensure_ascii=False).encode('utf-8'))>MAX_RESPONSE_BYTES:
            raise GatewayCompletionError('invalid_cached_response','Recovery response exceeds original response bound')
        text=self._extract_text(doc)
        if not text.strip():raise GatewayCompletionError('invalid_cached_response','No complete recovery text')
        if schema is not None:
            validator=_schema_validator(schema)
            try:value=parse_json_object(text)
            except ValueError:raise GatewayCompletionError('invalid_cached_response','Recovery text is not JSON') from None
            if list(validator.iter_errors(value)):
                raise GatewayCompletionError('invalid_cached_response','Recovery schema failed')
        usage=dict(doc.get('usage') or {})
        if 'input_tokens' in usage:usage.setdefault('prompt_tokens',usage['input_tokens'])
        if 'output_tokens' in usage:usage.setdefault('completion_tokens',usage['output_tokens'])
        return ProviderCompletion(text,str(doc.get('model') or 'UNKNOWN'),str(doc.get('id') or ''),usage,0,
                                  dict(doc.get('cgkn_model_identity') or {}),raw_finish_reason=_raw_finish_reason(doc))

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any] | None, config: ModelRoleConfig, purpose: str | None = None, transport_scope=None, call_identity: str | None = None, on_progress=None, cancel=None) -> ProviderCompletion:
        from .application_network import settings,session
        if cancel is not None and cancel.is_set():
            raise GatewayCompletionError('USER_CANCELLED','Request cancelled before submission')
        application=settings();expected_session=None
        if application:
            current,_=session(application,autostart=False)
            expected_session=current.get('session_id')
            if _loopback_base_url(current['base_url'])!=self.base_url or current['access_token']!=self.access_token:
                raise GatewayCompletionError('domestic_gateway_changed','Use client.reconnect() for new requests; unknown submissions must not be replayed')
        if config.model not in {"qwen", "deepseek", "grok"}:
            raise GatewayCompletionError("invalid_model", "model must be an allowed Provider ID")
        schema_doc = dict(schema) if schema is not None else None
        validator = _schema_validator(schema_doc) if schema_doc is not None else None
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
        if schema_doc is None:
            payload.pop("response_format",None);payload.pop("text",None)
        if call_identity is not None:
            if not isinstance(call_identity, str) or not call_identity or len(call_identity)>128:
                raise ValueError("invalid call identity")
            payload["cgkn_attempt_id"] = call_identity
        if config.model_id:
            payload["cgkn_model_id"] = config.model_id
        if config.reasoning_effort != "none":
            payload["reasoning"] = {"effort": config.reasoning_effort}
        legacy_identity='sha256:'+hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        payload['stream']=True
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        def stamp():return dict(utc_unix=time.time(),monotonic=time.monotonic(),pid=os.getpid())
        stages = {'payload_ready':stamp()}
        if len(encoded) > MAX_REQUEST_BYTES:
            raise GatewayCompletionError("request_too_large", "gateway request exceeded the bounded request size")
        identity = "sha256:" + hashlib.sha256(encoded).hexdigest()
        cached=provider_api_budget.load_cached_response(identity.removeprefix('sha256:'))
        if cached is None and provider_api_budget.configured_cache_mode()=='replay_only':
            raise GatewayCompletionError('cache_miss','Replay-only cache miss; no request submitted')
        if cached is not None:
            _validate_terminal(cached,self.api_method,config)
            # Reconstruct only an identity-bound prior response, never a new call.
            if str(cached.get('status','completed')) not in ('completed',''):
                raise GatewayCompletionError('invalid_cached_response','Cached completion was not complete')
            text=self._extract_text(cached)
            if not text.strip():raise GatewayCompletionError('invalid_cached_response','Cached response has no completion text')
            value=parse_json_object(text) if validator else None
            if validator and list(validator.iter_errors(value)):
                raise GatewayCompletionError('invalid_cached_response','Cached completion failed schema validation')
            usage=dict(cached.get('usage') or {})
            if 'input_tokens' in usage:usage.setdefault('prompt_tokens',usage['input_tokens'])
            if 'output_tokens' in usage:usage.setdefault('completion_tokens',usage['output_tokens'])
            return ProviderCompletion(text,str(cached.get('model') or config.model),str(cached.get('id') or ''),usage,0,dict(cached.get("cgkn_model_identity") or {}),raw_finish_reason=_raw_finish_reason(cached))
        limits = provider_api_budget.configured_limits()
        if self.enforce_budget and (
            provider_api_budget.configured_ledger_path() is None
            or (self.execution_policy == "limited" and not provider_api_budget.budget_configured())
            or limits.get("input_cost_per_million") is None
            or limits.get("output_cost_per_million") is None
        ):
            raise provider_api_budget.ProviderBudgetExhausted(
                "PROVIDER_BUDGET_EXHAUSTED: gateway calls require a ledger, complete limits, and operator-supplied price estimates"
            )
        stages['budget_reserve_begin'] = stamp()
        reservation = provider_api_budget.reserve_call(
            case_id=self.case_id or str(os.environ.get("CGKN_BENCHMARK_CASE_ID", "gateway-runtime")),
            purpose=purpose or ("PLANNING" if config.role == "agent" else "GENERATION"),
            model=config.model_id or config.model,
            request_identity=identity,
            estimated_input_tokens=self.input_token_ceiling or max(1, (len(system) + len(user) + 3) // 4),
            requested_output_tokens=config.max_output_tokens,
            retry_count=0,
            run_id=self.run_id or None,
            provider=config.model,
            execution_policy=self.execution_policy,
            authorization_reference=self.authorization_reference,
            prior_request_identities=(legacy_identity,),
        ) if self.enforce_budget else None
        stages['budget_reserve_end'] = stamp()
        response_doc: dict[str, Any] | None = None
        http_status: int | None = None
        started = False;known_failure=False
        scope=None
        from .progress_clock import ProgressClock
        progress_root = os.environ.get('CGKN_PROGRESS_ROOT')
        ledger_path = provider_api_budget.configured_ledger_path()
        if not progress_root and ledger_path:
            progress_root = str(Path(ledger_path).parent / 'api-progress')
        clock = None
        final_clock_status = 'UNKNOWN'
        clock_error = None
        def observe_progress(row):
            if clock:clock.observe(row)
            if on_progress:on_progress(row)
        try:
            if progress_root:
                clock = ProgressClock(progress_root, identity=identity,
                    stages=stages,
                    call_id=(reservation or {}).get('call_id') or call_identity or identity,
                    job_id=(reservation or {}).get('job_id') or os.environ.get('CGKN_MODEL_JOB_ID') or self.run_id or identity,
                    attempt_id=(reservation or {}).get('attempt_id') or call_identity or identity,
                    provider=config.model, model=config.model_id or 'DEFAULT_BINDING',
                    phase=purpose or ('PLANNING' if config.role == 'agent' else 'GENERATION'),
                    gateway_state=application.get('gateway_state_dir') if application else None,
                    initial=self.initial_progress_seconds, idle=self.progress_idle_seconds)
            if transport_scope is not None:
                scope=transport_scope();scope.__enter__()
            req = request.Request(
                self.base_url + path,
                data=encoded,
                headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json", "Accept": "text/event-stream", "User-Agent": "cgkn-kernel/gateway-v1",
                    "X-CGKN-Run-ID":str((reservation or {}).get("run_id",self.run_id)),
                    "X-CGKN-Job-ID":str((reservation or {}).get("job_id","")),
                    "X-CGKN-Attempt-ID":str((reservation or {}).get("attempt_id","")),"X-CGKN-Call-ID":str((reservation or {}).get('call_id',''))},
                method="POST",
            )
            if self.input_token_ceiling is not None:req.add_header("X-CGKN-Input-Token-Ceiling",str(self.input_token_ceiling))
            provider_api_budget.mark_request_started(reservation)
            started = True
            # This bound covers only local connection / response headers. The
            # streaming reader replaces it with progress-based supervision.
            with _open_loopback(req, timeout=self.setup_seconds) as response:
                http_status = int(response.status)
                if 'text/event-stream' not in response.headers.get('Content-Type',''):
                    raise GatewayCompletionError('stream_required','Formal generation requires streaming Gateway; no JSON fallback',outcome_unknown=True)
                from .gateway_stream import receive
                from .streaming_sse import StreamError
                try:decoded=receive(response,identity,initial_seconds=self.initial_progress_seconds,idle_seconds=self.progress_idle_seconds,setup_seconds=self.setup_seconds,expected_session=expected_session,on_progress=observe_progress,cancel=cancel,on_started=observe_progress)
                except StreamError as exc:
                    known_failure=not exc.outcome_unknown
                    if isinstance(exc.response,dict):
                        response_doc=exc.response
                        provider_api_budget.mark_response_received(reservation,response=response_doc,http_status=http_status)
                    raise GatewayCompletionError(exc.code,'Streaming request failed; no automatic replay',http_status=http_status,outcome_unknown=exc.outcome_unknown) from None
            if len(json.dumps(decoded,ensure_ascii=False).encode())>MAX_RESPONSE_BYTES:
                raise GatewayCompletionError('invalid_response','Completed response exceeds bound',outcome_unknown=True)
            if not isinstance(decoded, dict):
                raise GatewayCompletionError("invalid_response", "gateway response root is not an object", http_status=http_status)
            response_doc = decoded
            if clock:clock.observe({'phase':'completing'})
            provider_api_budget.mark_response_received(reservation, response=response_doc, http_status=http_status)
            _validate_terminal(decoded,self.api_method,config)
            status = str(decoded.get("status", "completed"))
            if status not in {"completed", ""}:
                raise GatewayCompletionError("truncated_response", "gateway response did not complete", http_status=http_status)
            text = self._extract_text(decoded)
            if not text.strip():
                raise GatewayCompletionError("empty_response", "gateway returned no completion text", http_status=http_status)
            value = parse_json_object(text) if validator else None
            errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path)) if validator else []
            if errors:
                raise GatewayCompletionError("schema_validation_failed", errors[0].message, http_status=http_status)
            usage = dict(decoded.get("usage")) if isinstance(decoded.get("usage"), dict) else {}
            if "prompt_tokens" not in usage and "input_tokens" in usage:
                usage["prompt_tokens"] = usage.get("input_tokens")
            if "completion_tokens" not in usage and "output_tokens" in usage:
                usage["completion_tokens"] = usage.get("output_tokens")
            provider_api_budget.store_cached_response(identity.removeprefix('sha256:'),decoded)
            provider_api_budget.finalize_call(reservation, usage=usage, http_status=http_status, status="SUCCEEDED")
            if clock:clock.observe({'phase':'result_saved'})
            final_clock_status = 'COMPLETED'
            return ProviderCompletion(text, str(decoded.get("model") or "UNKNOWN"), str(decoded.get("id") or ""), usage, 1, dict(decoded.get("cgkn_model_identity") or {}),raw_finish_reason=_raw_finish_reason(decoded))
        except error.HTTPError as exc:
            http_status = int(exc.code)
            try:
                body = exc.read(65_536)
                decoded = json.loads(body.decode("utf-8"))
                response_doc = decoded if isinstance(decoded, dict) else {}
            except Exception:
                response_doc = {}
            category, message = _safe_gateway_error(response_doc, self.access_token, f"gateway HTTP {http_status}")
            known_before_send={'network_unavailable_before_send','provider_queue_deadline','gateway_busy',
                               'provider_credential_unavailable','provider_authentication_failed','model_not_found',
                               'invalid_request','provider_protocol_unsupported','provider_rate_limited'}
            unknown=(category in {'provider_outcome_unknown','outcome_unknown'} or
                     (http_status>=500 and category not in known_before_send) or http_status==408)
            final_clock_status = 'UNKNOWN' if unknown else 'FAILED'
            clock_error = category
            provider_api_budget.finalize_call(reservation, usage=None, http_status=http_status, status='INTERRUPTED_UNKNOWN' if unknown else 'FAILED')
            raise GatewayCompletionError(category, message, http_status=http_status,
                outcome_unknown=unknown) from None
        except GatewayCompletionError as exc:
            if exc.category=='schema_validation_failed' and response_doc is not None:
                exc.completed_response=dict(response_doc)
            unknown=exc.outcome_unknown or (started and response_doc is None and not known_failure)
            clock_error = exc.category
            final_clock_status = ('STALLED' if exc.category in {'NO_INITIAL_MEANINGFUL_PROGRESS','NO_MEANINGFUL_PROGRESS'}
                else 'UNKNOWN' if unknown else 'CANCELLED' if exc.category=='USER_CANCELLED' else 'BLOCKED' if known_failure else 'FAILED')
            provider_api_budget.finalize_call(reservation, usage=(response_doc or {}).get("usage") if response_doc else None,
                http_status=http_status,status='INTERRUPTED_UNKNOWN' if unknown else 'FAILED')
            if unknown and not exc.outcome_unknown:
                raise GatewayCompletionError(exc.category,str(exc),http_status=http_status,outcome_unknown=True) from None
            raise
        except (TimeoutError, error.URLError, OSError) as exc:
            final_clock_status = 'UNKNOWN' if started else 'BLOCKED'
            clock_error = 'transport_error'
            provider_api_budget.finalize_call(reservation, usage=None, http_status=http_status,status='INTERRUPTED_UNKNOWN' if started else 'FAILED')
            category = "outcome_unknown" if started else "gateway_unavailable"
            safe = str(getattr(exc, "reason", exc)).replace(self.access_token, "[REDACTED]")[:500]
            raise GatewayCompletionError(category, safe, http_status=http_status, outcome_unknown=started) from None
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            final_clock_status = 'UNKNOWN' if started else 'BLOCKED'
            clock_error = 'invalid_response'
            provider_api_budget.finalize_call(reservation, usage=None, http_status=http_status, status='INTERRUPTED_UNKNOWN' if started else 'FAILED')
            safe = str(exc).replace(self.access_token, "[REDACTED]")[:500]
            raise GatewayCompletionError("invalid_response", safe, http_status=http_status,outcome_unknown=started) from None
        except Exception as exc:
            final_clock_status = 'UNKNOWN' if started else 'BLOCKED'
            clock_error = 'unexpected_transport_failure'
            # An unexpected decoder/adapter exception must not reopen an already
            # submitted recorded attempt through a missing UNKNOWN annotation.
            provider_api_budget.finalize_call(reservation,usage=None,http_status=http_status,
                status='INTERRUPTED_UNKNOWN' if started else 'FAILED')
            raise GatewayCompletionError('unexpected_transport_failure',type(exc).__name__,http_status=http_status,outcome_unknown=started) from None
        finally:
            if clock:clock.finish(final_clock_status, error=clock_error, response=response_doc)
            if scope is not None:scope.__exit__(None,None,None)

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


def completion_client_from_environment() -> CompletionClient:
    from .application_network import settings,session,record_selection
    config=settings()
    if config:
        info,status= session(config)
        record_selection(config,info,status)
        return GatewayCompletionClient(info['base_url'],info['access_token'])
    if _enabled(os.environ.get("CGKN_PROVIDER_GATEWAY_ENABLED")):
        return GatewayCompletionClient.from_environment()
    from .legacy_client import OpenAICompatibleClient
    return OpenAICompatibleClient()
