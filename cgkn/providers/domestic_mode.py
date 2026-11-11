"""Domestic readiness and explicitly admitted failover; no capability scoring."""
from __future__ import annotations
import dataclasses
import uuid
from .gateway_client import GatewayCompletionError


def domestic_state(rows):
    available={r['provider'] for r in rows if r.get('http_reached') and r['provider'] in ('qwen','deepseek')}
    return 'DOMESTIC_READY' if len(available)==2 else ('DOMESTIC_DEGRADED' if available else 'DOMESTIC_UNAVAILABLE')


@dataclasses.dataclass(frozen=True)
class SubstitutionAdmission:
    role: str
    schema_name: str
    primary: str
    backup: str
    required_capabilities: frozenset[str]
    proven_capabilities: frozenset[str]
    evidence_ref: str

    def __post_init__(self):
        if self.role not in ('agent','worker') or {self.primary,self.backup}!={'qwen','deepseek'}:
            raise ValueError('DOMESTIC_SUBSTITUTION_REQUIRED')
        if not self.schema_name or not self.required_capabilities or not self.evidence_ref:
            raise ValueError('EXPLICIT_TASK_CAPABILITY_ADMISSION_REQUIRED')
        if not self.required_capabilities<=self.proven_capabilities:raise ValueError('BACKUP_CAPABILITY_GATE_FAILED')


class DomesticFailoverClient:
    """Opt-in wrapper. An empty admission list preserves existing fallback=deny."""
    def __init__(self,client,admissions=(),log=None):
        self.client,self.admissions=client,tuple(admissions);self.log=log or (lambda row:None)

    def complete(self,**kwargs):
        config=kwargs['config'];logical_id=uuid.uuid4().hex
        try:
            self.log(dict(logical_id=logical_id,attempt_id=logical_id+'-1',provider=config.model))
            return self.client.complete(**kwargs)
        except GatewayCompletionError as exc:
            if exc.category!='network_unavailable_before_send' or exc.outcome_unknown:raise
            admission=next((a for a in self.admissions if a.role==config.role and a.schema_name==kwargs['schema_name'] and a.primary==config.model),None)
            if admission is None:raise
            self.log(dict(logical_id=logical_id,attempt_id=logical_id+'-2',provider=admission.backup,
                admission_ref=admission.evidence_ref,reason=exc.category))
            return self.client.complete(**{**kwargs,'config':dataclasses.replace(config,model=admission.backup)})
