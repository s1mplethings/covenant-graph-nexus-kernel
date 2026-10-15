from __future__ import annotations

from scripts import product_direction_gate


def test_product_direction_gate_passes() -> None:
    assert product_direction_gate.check() == []


def test_mvp_authorities_are_explicit() -> None:
    product = product_direction_gate._read("PRODUCT_GOAL.md")
    scope = product_direction_gate._read("MVP_SCOPE.md")
    assert "Capability Tree" in product
    assert "Tree-to-DAG" in product
    assert "Roles are capability bundles/views" in product
    assert "Provider-owned project planning" in scope
    assert "Fixed10 as a product-readiness gate" in scope
