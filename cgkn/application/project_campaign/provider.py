from __future__ import annotations

from typing import Any

from cgkn.providers import CompletionClient, ProviderCompletion


class CampaignCompletionClient:
    """Transparent usage ledger around the one frozen campaign Provider route."""

    def __init__(self, inner: CompletionClient, *, provider_id: str = "grok"):
        self.inner = inner
        self.provider_id = provider_id
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_in_usd_ticks = 0

    def complete(self, **kwargs: Any) -> ProviderCompletion:
        config = kwargs.get("config")
        configured = str(getattr(config, "provider", getattr(config, "model", self.provider_id))).lower()
        if configured != self.provider_id:
            raise RuntimeError(f"CRITICAL_PROVIDER_ROUTE_CHANGED:{configured}")
        result = self.inner.complete(**kwargs)
        usage = dict(result.usage)
        self.calls += 1
        self.input_tokens += int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        self.output_tokens += int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
        self.cost_in_usd_ticks += int(usage.get("cost_in_usd_ticks", 0) or 0)
        return result

    def snapshot(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_in_usd_ticks": self.cost_in_usd_ticks,
        }
