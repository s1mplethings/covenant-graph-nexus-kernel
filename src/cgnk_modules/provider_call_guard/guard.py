from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import (
    CGNK_PROVIDER_GUARD_BUDGET_EXCEEDED,
    CGNK_PROVIDER_GUARD_DENIED,
    CGNK_PROVIDER_GUARD_INVALID_REQUEST,
    Diagnostic,
)

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF


def evaluate_provider_call_request(request: Any, policy: dict[str, Any] | None = None, budget: dict[str, Any] | None = None) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    denied_reasons: list[str] = []
    if not isinstance(request, dict):
        diagnostics.append(Diagnostic(CGNK_PROVIDER_GUARD_INVALID_REQUEST, "error", "$.request", "Provider call request must be a dictionary", expected="dict", actual=type(request).__name__, involved_ref=MODULE_REF))
        request = {}
        denied_reasons.append("invalid_request")
    policy = policy if isinstance(policy, dict) else {}
    budget = budget if isinstance(budget, dict) else {}
    provider_allowed = policy.get("allow_provider_call") is True or policy.get("provider_call") is True
    if not provider_allowed:
        denied_reasons.append("policy_denies_provider_call")
    budget_summary = _budget_summary(request, budget)
    if budget_summary["exceeded"]:
        denied_reasons.append("budget_exceeded")
        diagnostics.append(Diagnostic(CGNK_PROVIDER_GUARD_BUDGET_EXCEEDED, "error", "$.budget", "Provider request exceeds declared budget", expected=budget_summary["limits"], actual=budget_summary["requested"], involved_ref=MODULE_REF))
    allowed = not denied_reasons
    if not allowed:
        diagnostics.append(Diagnostic(CGNK_PROVIDER_GUARD_DENIED, "warning", "$.request", "Provider request is denied by policy or budget", expected="allowed request", actual=sorted(denied_reasons), involved_ref=MODULE_REF))
    report = {
        "kind": "ProviderGuardReport",
        "schema_version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "allowed": allowed,
        "denied_reasons": sorted(dict.fromkeys(denied_reasons)),
        "budget_summary": budget_summary,
    }
    return {"ok": allowed, "allowed": allowed, "denied_reasons": report["denied_reasons"], "budget_summary": budget_summary, "report": report, "diagnostics": [d.as_dict() for d in diagnostics]}


def _budget_summary(request: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
    requested_tokens = _number(request.get("max_tokens") or request.get("tokens"), 0)
    requested_calls = _number(request.get("calls"), 1)
    max_tokens = _number(budget.get("max_tokens"), requested_tokens if requested_tokens else 0)
    max_calls = _number(budget.get("max_calls"), requested_calls)
    exceeded = (max_tokens > 0 and requested_tokens > max_tokens) or (max_calls > 0 and requested_calls > max_calls)
    return {
        "requested": {"tokens": requested_tokens, "calls": requested_calls},
        "limits": {"max_tokens": max_tokens, "max_calls": max_calls},
        "exceeded": exceeded,
    }


def _number(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return default
