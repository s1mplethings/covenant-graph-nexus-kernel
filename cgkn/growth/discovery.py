from __future__ import annotations

import importlib.util
import sys
from typing import Protocol

from cgkn.capabilities import CapabilityDescriptor

from .candidate import CapabilityCandidate
from .gap import CapabilityGap


class DiscoverySource(Protocol):
    def discover(self, gap: CapabilityGap) -> list[CapabilityCandidate]: ...


class LocalDiscoverySource:
    """Offline-only discovery over explicitly allowlisted local identities."""

    def discover(self, gap: CapabilityGap) -> list[CapabilityCandidate]:
        if gap.requested_capability != "json.parse" or importlib.util.find_spec("json") is None:
            return []
        descriptor = CapabilityDescriptor(
            capability_id="json.parse", version="1", component_ref="json.parse@1",
            executor_ref="python.stdlib.json@1", allowed_executor_kinds=("python_stdlib",),
            input_ports=("text",), output_ports=("object",), declared_effects=(),
            timeout_seconds=5.0, cost_hint="zero", risk_level="LOW", source="python_stdlib",
            provenance={"module": "json", "callable": "json.loads", "python_version": sys.version.split()[0]},
            test_refs=("sandbox.valid_json", "sandbox.invalid_json", "sandbox.no_write", "sandbox.no_network"),
        )
        return [CapabilityCandidate(
            candidate_id="candidate.python-stdlib-json-loads.v1", proposed_descriptor=descriptor,
            implementation_kind="python_callable", source="python_stdlib", identity="json.loads",
            version=sys.version.split()[0], required_environment={"python": sys.version.split()[0]},
            declared_effects=(), generated_adapter_path="cgkn.growth.loop:StdlibJsonExecutor",
            trial_plan=("valid JSON parses", "invalid JSON is controlled", "no file writes", "no network"),
            provenance={"discovery": "allowlisted_local_stdlib", "network_used": False},
        )]
