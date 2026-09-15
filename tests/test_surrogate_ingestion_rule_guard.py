from __future__ import annotations

import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_surrogate_is_transport_under_the_existing_scheduler() -> None:
    adapter = (ROOT / "scripts/surrogate_provider_adapter.py").read_text(encoding="utf-8")
    runner = (ROOT / "scripts/run_local_pipeline_impl.py").read_text(encoding="utf-8")
    assert "ThreadPoolExecutor" not in adapter
    assert runner.count("with ThreadPoolExecutor(") == 1
    assert "surrogate_provider_adapter.provider_text(" in runner


def test_nonlive_transport_precedes_every_live_transport() -> None:
    runner = (ROOT / "scripts/run_local_pipeline_impl.py").read_text(encoding="utf-8")
    start = runner.index("def provider_text(")
    end = runner.index("def parse_provider_json_object_with_one_repair(", start)
    body = runner[start:end]
    branch = body.index("surrogate_provider_adapter.provider_text(")
    assert branch < body.index("try_local_provider_text(")
    assert branch < body.index("_resolve_api_credentials()")


def test_frozen_acceptance_and_product_governance_modules_are_not_surrogate_dependencies() -> None:
    adapter = (ROOT / "scripts/surrogate_provider_adapter.py").read_text(encoding="utf-8")
    assert "repair_acceptance" not in adapter
    assert "product_design_depth_governance" not in adapter
    assert "candidate_materializer" not in adapter
    assert "local_packager" not in adapter


def test_formal_modes_are_registered_once_at_the_transport_boundary() -> None:
    adapter = (ROOT / "scripts/surrogate_provider_adapter.py").read_text(encoding="utf-8")
    assert 'PROVIDER_MODES = ("live", "codex_surrogate", "deterministic_replay")' in adapter
    assert "WAITING_SURROGATE_RESPONSE" in adapter
