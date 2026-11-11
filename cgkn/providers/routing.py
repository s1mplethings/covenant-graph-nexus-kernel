from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from .client import ModelRoleConfig


ALLOWED_PROVIDER_IDS = frozenset({"qwen", "deepseek", "grok"})

MAX_ESCALATION_REASONS = frozenset({
    'HIGH_IMPACT_ARCHITECTURE_CONFLICT',
    'MULTI_MILESTONE_REPLAN_WITH_CONFLICTING_CONSTRAINTS',
    'REPEATED_CHEAP_SEMANTIC_FAILURE_WITH_VALID_CONTEXT',
    'CRITICAL_IRREVERSIBLE_DECISION', 'COMPLEX_CROSS_DOMAIN_TRADEOFF',
})
ESCALATION_CHECKS = frozenset({'context_complete','evidence_complete','contract_complete',
                             'deterministic_correction_exhausted','cheap_semantic_failure'})


class ModelEscalationDenied(ValueError):
    category = 'model_escalation_denied'
    outcome_unknown = False
    provider_dispatched = False


def admit_recorded_model(store, root, config, public_request, *, evidence_producers=()):
    """Admit Max only against an exact request and protected checked evidence.

    This consumes existing run-store evidence, not a separate routing ledger.
    Evidence producers are controller registrations; model output cannot add
    producers, choose another purpose, or authorize its own escalation.
    """
    import dataclasses
    import re
    if config.model in ALLOWED_PROVIDER_IDS and config.model_id is None:
        raise ModelEscalationDenied('CONCRETE_MODEL_BINDING_REQUIRED: provider alias cannot establish cheap or escalation route')
    model = config.model_id or config.model
    if not re.search(r'(^|[.\-_])max($|[.\-_])', model.lower()):
        return {'policy':'MAX_ESCALATION_ONLY','escalated':False,'requested_model':model}
    key = hashlib.sha256(_canonical({'config':dataclasses.asdict(config),'request':public_request}).encode()).hexdigest()
    path = root / 'model_escalations' / (key + '.json')
    try:
        path.resolve().relative_to(root.resolve())
        receipt_raw = path.read_bytes()
        receipt = json.loads(receipt_raw)
        if (config.role != 'agent' or receipt['request_hash'] != key
                or receipt['reason'] not in MAX_ESCALATION_REASONS
                or receipt['operation'] != 'project_semantic_decision'
                or set(receipt['checks']) != ESCALATION_CHECKS):
            raise ValueError('scope, reason or checks do not authorize this operation')
        # A schema/declaration correction remains forbidden even if somebody
        # reuses a valid semantic escalation reason in its surrounding prompt.
        request_kind = json.loads(public_request['user']).get('call_kind','')
        if request_kind and request_kind != 'semantic_decision_attempt':
            raise ValueError('correction and routine operations cannot escalate')
        for name, reference in receipt['checks'].items():
            evidence = (root / reference['path']).resolve()
            evidence.relative_to(root.resolve())
            raw = evidence.read_bytes()
            if hashlib.sha256(raw).hexdigest() != reference['sha256']:
                raise ValueError('changed escalation evidence')
            check = json.loads(raw)
            if (check.get('producer') not in evidence_producers
                    or check.get('request_hash') != key or check.get('check') != name
                    or check.get('passed') is not True or not check.get('source_refs')):
                raise ValueError('unregistered, incomplete or wrong-object escalation evidence')
            if check.get('failure_domain') != 'SEMANTIC':
                raise ValueError('parser/schema/evidence/transport/contract/harness/unknown cannot escalate')
            for source in check['source_refs']:
                source_path = (root / source['path']).resolve()
                source_path.relative_to(root.resolve())
                if hashlib.sha256(source_path.read_bytes()).hexdigest() != source['sha256']:
                    raise ValueError('changed source evidence')
        # Exactly one dispatch per grant. Even an interrupted use is preserved;
        # a fresh model attempt requires a new explicit, evidence-bound grant.
        with store.exclusive_file(root/'model_escalations'/'admission.lock',wait_seconds=10):
            used = path.with_suffix('.used.json')
            if used.exists(): raise ValueError('escalation grant already consumed; reconcile original call')
            if path.read_bytes() != receipt_raw: raise ValueError('escalation receipt changed during admission')
            store.immutable_json(used, {'request_hash':key,'receipt_hash':hashlib.sha256(receipt_raw).hexdigest()})
        return {'policy':'MAX_ESCALATION_ONLY','escalated':True,'requested_model':model,
                'reason':receipt['reason'],'receipt_ref':str(path.relative_to(root)), 'request_hash':key}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ModelEscalationDenied('MAX_ESCALATION_NOT_ADMITTED: '+str(exc)) from exc


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class CGKNModelRouting:
    agent: ModelRoleConfig
    worker: ModelRoleConfig
    allowed_providers: frozenset[str]
    fallback: str = "deny"
    schema_version: str = "1.0"

    @classmethod
    def load(cls, path: pathlib.Path | str) -> "CGKNModelRouting":
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("kind") != "CGKNModelRouting" or raw.get("schema_version") != "1.0":
            raise ValueError("unsupported CGKN model routing configuration")
        if set(raw) != {"kind", "schema_version", "roles", "allowed_providers", "fallback"}:
            raise ValueError("model routing configuration has unknown or missing fields")
        roles = raw.get("roles")
        if not isinstance(roles, dict) or set(roles) != {"agent", "worker"}:
            raise ValueError("model routing must define exactly agent and worker roles")
        allowed = frozenset(str(item).strip().lower() for item in raw.get("allowed_providers", ()))
        if not allowed or not allowed <= ALLOWED_PROVIDER_IDS:
            raise ValueError("model routing contains an unsupported Provider ID")
        fallback = str(raw.get("fallback", "")).strip().lower()
        if fallback != "deny":
            raise ValueError("automatic Provider fallback is forbidden")
        configs: dict[str, ModelRoleConfig] = {}
        for role in ("agent", "worker"):
            value = roles[role]
            if not isinstance(value, dict) or set(value) - {"provider_id", "model_id", "timeout_seconds", "max_output_tokens", "temperature", "reasoning_effort"}:
                raise ValueError(f"invalid {role} routing fields")
            provider_id = str(value.get("provider_id", "")).strip().lower()
            if provider_id not in allowed:
                raise ValueError(f"{role} Provider ID is not allowed")
            configs[role] = ModelRoleConfig(
                role,
                provider_id,
                int(value.get("timeout_seconds", 90)),
                int(value.get("max_output_tokens", 6000)),
                float(value.get("temperature", 0.0)),
                str(value.get("reasoning_effort", "none")),
                value.get("model_id"),
            )
        return cls(configs["agent"], configs["worker"], allowed, fallback)

    def as_dict(self) -> dict[str, Any]:
        def role(config: ModelRoleConfig) -> dict[str, Any]:
            return {
                "provider_id": config.model,
                **({"model_id": config.model_id} if config.model_id else {}),
                "timeout_seconds": config.timeout_seconds,
                "max_output_tokens": config.max_output_tokens,
                "temperature": config.temperature,
                "reasoning_effort": config.reasoning_effort,
            }

        return {
            "kind": "CGKNModelRouting",
            "schema_version": self.schema_version,
            "roles": {"agent": role(self.agent), "worker": role(self.worker)},
            "allowed_providers": sorted(self.allowed_providers),
            "fallback": self.fallback,
        }

    @property
    def config_hash(self) -> str:
        return "sha256:" + hashlib.sha256(_canonical(self.as_dict()).encode("utf-8")).hexdigest()

    def snapshot(self, run_id: str, *, gateway_protocol: str = "openai-compatible-local-v1") -> "ModelRoutingSnapshot":
        roles = MappingProxyType({"agent": self.agent.model, "worker": self.worker.model})
        limits = MappingProxyType({
            "agent": MappingProxyType({"max_output_tokens": self.agent.max_output_tokens, "timeout_seconds": self.agent.timeout_seconds}),
            "worker": MappingProxyType({"max_output_tokens": self.worker.max_output_tokens, "timeout_seconds": self.worker.timeout_seconds}),
        })
        return ModelRoutingSnapshot(
            run_id=str(run_id),
            roles=roles,
            actual_models=MappingProxyType({"agent": "", "worker": ""}),
            requested_models=MappingProxyType({"agent": self.agent.model_id or "DEFAULT_BINDING", "worker": self.worker.model_id or "DEFAULT_BINDING"}),
            gateway_protocol=gateway_protocol,
            routing_config_hash=self.config_hash,
            limits=limits,
            fallback="deny",
            created_at=datetime.now(timezone.utc).isoformat(),
        )


@dataclass(frozen=True)
class ModelRoutingSnapshot:
    run_id: str
    roles: Mapping[str, str]
    actual_models: Mapping[str, str]
    gateway_protocol: str
    routing_config_hash: str
    limits: Mapping[str, Mapping[str, int]]
    fallback: str
    created_at: str
    requested_models: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "ModelRoutingSnapshot",
            "schema_version": "1.0",
            "run_id": self.run_id,
            "roles": dict(self.roles),
            "actual_models": dict(self.actual_models),
            "requested_models": dict(self.requested_models),
            "bound_models": {k:(v if v!='DEFAULT_BINDING' else 'UNRESOLVED') for k,v in self.requested_models.items()},
            "binding_policy": {"kind":"exact","aliases":[]},
            "gateway_protocol": self.gateway_protocol,
            "routing_config_hash": self.routing_config_hash,
            "limits": {key: dict(value) for key, value in self.limits.items()},
            "fallback": self.fallback,
            "created_at": self.created_at,
            "contains_credentials": False,
        }

    def write_once(self, path: pathlib.Path | str) -> pathlib.Path:
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            json.dump(self.as_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return target
