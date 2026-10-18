from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Mapping

from scripts import provider_api_budget

from .client import ModelRoleConfig, ProviderCompletion
from .connector_registry import ProviderConnectorRegistry


class ConnectorCompletionClient:
    """Canonical CompletionClient adapter over an explicit connector registry."""

    def __init__(self, registry: ProviderConnectorRegistry, *, enforce_budget: bool = False, budget_purpose: str = "GENERATION", run_id: str = "", case_id: str = "connector-runtime") -> None:
        self.registry = registry
        self.enforce_budget = enforce_budget
        self.budget_purpose = budget_purpose
        self.run_id = run_id
        self.case_id = case_id
        self._call_count = 0

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        self._call_count += 1
        identity_source = json.dumps({"provider": config.model, "system": system, "user": user, "schema_name": schema_name, "schema": schema}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        identity = hashlib.sha256(identity_source.encode("utf-8")).hexdigest()
        if self.enforce_budget:
            limits = provider_api_budget.configured_limits()
            if provider_api_budget.configured_ledger_path() is None or not provider_api_budget.budget_configured() or limits.get("input_cost_per_million") is None or limits.get("output_cost_per_million") is None:
                raise provider_api_budget.ProviderBudgetExhausted("PROVIDER_BUDGET_EXHAUSTED: connector calls require a ledger, complete limits, and operator-supplied price estimates")
        reservation = provider_api_budget.reserve_call(
            case_id=f"{self.case_id}-{self._call_count}", purpose=self.budget_purpose,
            model=config.model, request_identity=identity,
            estimated_input_tokens=max(1, (len(system) + len(user) + len(identity_source) // 4) // 4),
            requested_output_tokens=config.max_output_tokens, retry_count=0,
            run_id=self.run_id or str(os.environ.get("CGKN_BENCHMARK_RUN_ID", "")), provider=config.model,
        ) if self.enforce_budget else None
        try:
            provider_api_budget.mark_request_started(reservation)
            completion = self.registry.get(config.model).complete_structured(system=system, user=user, schema_name=schema_name, schema=schema, config=config)
            response = {"id": completion.request_id, "usage": dict(completion.usage)}
            provider_api_budget.mark_response_received(reservation, response=response, http_status=200)
            provider_api_budget.finalize_call(reservation, usage=dict(completion.usage), http_status=200, status="SUCCEEDED")
            return completion
        except Exception as exc:
            provider_api_budget.finalize_call(reservation, usage=None, http_status=provider_api_budget.http_status_from_error(str(exc)), status="FAILED")
            raise
