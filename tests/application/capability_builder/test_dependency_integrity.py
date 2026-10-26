from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cgkn.application.capability_builder import CapabilityRisk, CapabilitySpec, CapabilityStore, StoredCapabilityRuntime


def _spec(ref: str, *, risk: CapabilityRisk = CapabilityRisk.PURE, dependencies: tuple[str, ...] = ()) -> CapabilitySpec:
    capability_id, version = ref.rsplit("@", 1)
    return CapabilitySpec(capability_id, version, "bounded capability", {}, {}, ({"input":"x","output":"x","runtime":{"dependency_results":{item:"x" for item in dependencies}}},), ("bounded",), risk, dependencies)


def _install(store: CapabilityStore, spec: CapabilitySpec, *, code: str | None = None, manifest: list[dict] | None = None) -> Path:
    root = store.path_for(spec.ref); (root / "tests").mkdir(parents=True)
    code = code or ("def execute(value, ctx):\n    return ctx.capabilities.invoke(%r, value)\n" % spec.allowed_dependencies[0] if spec.allowed_dependencies else "def execute(value):\n    return value\n")
    (root / "executor.py").write_bytes(code.encode("utf-8"))
    (root / "capability.json").write_text(json.dumps(spec.as_dict()), encoding="utf-8")
    (root / "tests/test_capability.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    source_hash = "sha256:" + hashlib.sha256(code.encode()).hexdigest()
    (root / "admission.json").write_text(json.dumps({"kind":"CapabilityAdmission","schema_version":"1.1","capability_ref":spec.ref,"status":"ADMITTED","source_hash":source_hash,"dependency_manifest":manifest or []}), encoding="utf-8")
    return root


def test_declared_dependency_resolves_with_hash_and_contract_pin(tmp_path: Path):
    store=CapabilityStore(tmp_path / "store"); _install(store,_spec("base.echo@1"))
    composite=_spec("composite.echo@1",dependencies=("base.echo@1",))
    manifest=store.resolve_dependency_manifest(composite)
    assert manifest[0]["capability_ref"]=="base.echo@1" and manifest[0]["package_hash"].startswith("sha256:") and manifest[0]["contract_hash"].startswith("sha256:")


def test_missing_dependency_is_blocked(tmp_path: Path):
    store=CapabilityStore(tmp_path / "store")
    with pytest.raises(ValueError,match="CAPABILITY_DEPENDENCY_MISSING"):
        store.resolve_dependency_manifest(_spec("composite.echo@1",dependencies=("missing.echo@1",)))


def test_dependency_cycle_is_blocked(tmp_path: Path):
    store=CapabilityStore(tmp_path / "store")
    _install(store,_spec("cycle.a@1",dependencies=("cycle.b@1",)))
    _install(store,_spec("cycle.b@1",dependencies=("cycle.a@1",)))
    with pytest.raises(ValueError,match="DEPENDENCY_CYCLE"):
        store.validate_dependency_graph(_spec("top.echo@1",dependencies=("cycle.a@1",)))


def test_composite_risk_cannot_understate_transitive_network_risk(tmp_path: Path):
    store=CapabilityStore(tmp_path / "store"); _install(store,_spec("web.fetch@1",risk=CapabilityRisk.READ_ONLY_PUBLIC_NETWORK),code="def execute(value, ctx):\n    return value\n")
    with pytest.raises(ValueError,match="INVALID_COMPOSITE_RISK"):
        store.resolve_dependency_manifest(_spec("brief.make@1",dependencies=("web.fetch@1",)))


def test_composite_risk_accepts_bounded_dependency_execution(tmp_path: Path):
    store=CapabilityStore(tmp_path / "store"); _install(store,_spec("web.fetch@1",risk=CapabilityRisk.READ_ONLY_PUBLIC_NETWORK),code="def execute(value, ctx):\n    return value\n")
    spec=_spec("brief.make@1",risk=CapabilityRisk.READ_ONLY_PUBLIC_NETWORK_COMPOSITE,dependencies=("web.fetch@1",))
    assert store.resolve_dependency_manifest(spec)[0]["capability_ref"]=="web.fetch@1"


def test_dependency_hash_drift_blocks_execution(tmp_path: Path):
    store=CapabilityStore(tmp_path / "store"); base_root=_install(store,_spec("base.echo@1")); composite=_spec("composite.echo@1",dependencies=("base.echo@1",)); manifest=store.resolve_dependency_manifest(composite); _install(store,composite,manifest=manifest)
    (base_root / "executor.py").write_text("def execute(value): return 'drift'\n",encoding="utf-8")
    with pytest.raises(ValueError,match="BLOCK_REVALIDATION_REQUIRED|DEPENDENCY_HASH_DRIFT"):
        StoredCapabilityRuntime(store,provider_id="grok").invoke("composite.echo@1","x")


def test_undeclared_dependency_call_is_rejected_by_bound_context(tmp_path: Path):
    store=CapabilityStore(tmp_path / "store"); runtime=StoredCapabilityRuntime(store,provider_id="grok")
    context=runtime.context_for(_spec("top.echo@1",dependencies=("declared.echo@1",)))
    with pytest.raises(PermissionError,match="undeclared"):
        context.capabilities.invoke("other.echo@1","x")


def test_composite_has_no_raw_network_authority(tmp_path: Path):
    store=CapabilityStore(tmp_path / "store"); runtime=StoredCapabilityRuntime(store,provider_id="grok")
    context=runtime.context_for(_spec("top.echo@1",dependencies=("declared.echo@1",)))
    assert not hasattr(context.capabilities,"network_public")
