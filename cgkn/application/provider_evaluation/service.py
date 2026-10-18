from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from scripts import provider_api_budget
from jsonschema import Draft202012Validator

from cgkn.providers import (
    CompletionClient,
    GatewayCompletionClient,
    GatewayCompletionError,
    ModelRoleConfig,
    ProviderConnectionError,
    parse_json_object,
)

from .contracts import ProviderBenchmarkCase, ProviderBenchmarkReceipt, canonical_hash
from .suite import BenchmarkValidation, benchmark_cases, evaluate, system_prompt


@dataclass(frozen=True)
class ProviderPrice:
    input_per_million: float
    output_per_million: float

    def __post_init__(self) -> None:
        if self.input_per_million < 0 or self.output_per_million < 0:
            raise ValueError("Provider prices cannot be negative")


def _token(usage: Mapping[str, Any], *names: str) -> int | str:
    for name in names:
        value = usage.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return "TOKEN_USAGE_UNAVAILABLE"


def _failure_class(exc: Exception) -> str:
    if isinstance(exc, provider_api_budget.ProviderBudgetExhausted):
        return "BUDGET_BLOCKED"
    if isinstance(exc, GatewayCompletionError):
        category = exc.category.lower()
        if "timeout" in category:
            return "TIMEOUT"
        if category in {"schema_validation_failed", "invalid_response", "empty_response", "truncated_response"}:
            return "SCHEMA_FAILURE"
        return "TRANSPORT_FAILURE"
    if isinstance(exc, ProviderConnectionError):
        category = exc.error_class.upper()
        if "TIMEOUT" in category:
            return "TIMEOUT"
        if "SCHEMA" in category or "INVALID_RESPONSE" in category:
            return "SCHEMA_FAILURE"
        if "BUDGET" in category:
            return "BUDGET_BLOCKED"
        return "TRANSPORT_FAILURE"
    if isinstance(exc, TimeoutError):
        return "TIMEOUT"
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return "SCHEMA_FAILURE"
    return "TRANSPORT_FAILURE"


class ProviderEvaluationService:
    def __init__(
        self,
        client: CompletionClient,
        *,
        gateway_config_hash: str,
        source_commit: str,
        prices: Mapping[str, ProviderPrice] | None = None,
        structured_output_modes: Mapping[str, str] | None = None,
    ) -> None:
        self.client = client
        self.gateway_config_hash = gateway_config_hash
        self.source_commit = source_commit
        self.prices = dict(prices or {})
        self.structured_output_modes = dict(structured_output_modes or {})

    def run_case(
        self,
        provider_id: str,
        case: ProviderBenchmarkCase,
        *,
        run_id: str,
        actual_model_hint: str = "UNAVAILABLE",
    ) -> ProviderBenchmarkReceipt:
        system = system_prompt(case.task_class)
        user = json.dumps({
            "case_id": case.case_id,
            "task_class": case.task_class,
            "prompt_facts": list(case.prompt_facts),
            "output_contract": dict(case.expected_output_contract),
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        prompt_hash = canonical_hash({"system": system, "user": user})
        config = ModelRoleConfig(
            role=case.role,
            model=provider_id,
            timeout_seconds=case.timeout,
            max_output_tokens=case.budget.max_output_tokens,
            temperature=0.0,
            reasoning_effort="none",
        )
        client: CompletionClient = self.client
        if isinstance(client, GatewayCompletionClient):
            client = client.bind_run(run_id, case.case_id, budget_purpose="BENCHMARK")
        started = time.perf_counter()
        actual_model = actual_model_hint
        request_ids: tuple[str, ...] = ()
        usage: Mapping[str, Any] = {}
        validation = BenchmarkValidation(False)
        error_class = "NONE"
        schema_valid = False
        try:
            completion = client.complete(
                system=system,
                user=user,
                schema_name="cgkn_provider_benchmark",
                schema=case.expected_output_contract,
                config=config,
            )
            actual_model = (
                actual_model_hint
                if completion.model == provider_id and actual_model_hint != "UNAVAILABLE"
                else (completion.model or actual_model_hint)
            )
            request_ids = (completion.request_id,) if completion.request_id else ()
            usage = completion.usage
            value = parse_json_object(completion.text)
            errors = sorted(Draft202012Validator(dict(case.expected_output_contract)).iter_errors(value), key=lambda item: list(item.path))
            if errors:
                raise ValueError(errors[0].message)
            schema_valid = True
            validation = evaluate(case.case_id, value)
            if not validation.scope_valid:
                error_class = "SCOPE_FAILURE"
            elif not validation.interface_valid:
                error_class = "INTERFACE_FAILURE"
            elif not validation.functional_valid:
                error_class = "REPAIR_FAILURE" if validation.repair_required else "TASK_FAILURE"
        except Exception as exc:
            error_class = _failure_class(exc)
            # A transport or budget failure is not evidence of a schema, scope,
            # interface, or secret violation; it remains a functional failure.
            schema_valid = error_class not in {"SCHEMA_FAILURE"}
            validation = BenchmarkValidation(
                False,
                interface_valid=error_class != "INTERFACE_FAILURE",
                scope_valid=error_class != "SCOPE_FAILURE",
                repair_required=case.task_class == "worker.repair",
            )
        input_tokens = _token(usage, "input_tokens", "prompt_tokens")
        output_tokens = _token(usage, "output_tokens", "completion_tokens")
        total_tokens: int | str = (
            input_tokens + output_tokens
            if isinstance(input_tokens, int) and isinstance(output_tokens, int)
            else "TOKEN_USAGE_UNAVAILABLE"
        )
        price = self.prices.get(provider_id)
        cost: float | str = "UNAVAILABLE"
        if price and isinstance(input_tokens, int) and isinstance(output_tokens, int):
            cost = round((input_tokens * price.input_per_million + output_tokens * price.output_per_million) / 1_000_000, 8)
        success = bool(schema_valid and validation.functional_valid and validation.interface_valid and validation.scope_valid)
        return ProviderBenchmarkReceipt(
            provider_id=provider_id,
            actual_model=actual_model,
            task_class=case.task_class,
            benchmark_id=case.case_id,
            benchmark_version=case.benchmark_version,
            prompt_hash=prompt_hash,
            contract_hash=case.contract_hash,
            success=success,
            schema_valid=schema_valid,
            functional_valid=validation.functional_valid,
            interface_valid=validation.interface_valid,
            scope_valid=validation.scope_valid,
            repair_required=validation.repair_required,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_estimate=cost,
            wall_time_ms=int((time.perf_counter() - started) * 1000),
            error_class=error_class,
            request_ids=request_ids,
            source_commit=self.source_commit,
            gateway_config_hash=self.gateway_config_hash,
            secret_safe=True,
            structured_output_mode=self.structured_output_modes.get(provider_id, "UNAVAILABLE"),
        )

    def run_provider(
        self,
        provider_id: str,
        *,
        run_id: str,
        actual_model_hint: str = "UNAVAILABLE",
        cases: Sequence[ProviderBenchmarkCase] | None = None,
    ) -> tuple[ProviderBenchmarkReceipt, ...]:
        selected = tuple(benchmark_cases() if cases is None else cases)
        return tuple(
            self.run_case(provider_id, case, run_id=run_id, actual_model_hint=actual_model_hint)
            for case in selected
        )

    @staticmethod
    def write_receipt_once(receipt: ProviderBenchmarkReceipt, path: pathlib.Path | str) -> pathlib.Path:
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            json.dump(receipt.as_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return target
