from scripts.run_higher_order_growth import compare_spec, repo_brief_spec
from cgkn.application.capability_builder import CapabilityRisk
from cgkn.application.capability_builder.service import _ExampleDependencies


def test_repo_brief_is_bounded_composite_with_required_leaf_dependencies():
    spec = repo_brief_spec()
    assert spec.risk is CapabilityRisk.READ_ONLY_PUBLIC_NETWORK_COMPOSITE
    assert spec.allowed_dependencies == ("github.repo.inspect.public@1", "web.fetch.public@1", "markdown.links.extract@1")
    assert all(claim["evidence_refs"] for example in spec.examples for claim in example["output"]["claims"])


def test_compare_depends_only_on_repo_brief_and_preserves_evidence():
    spec = compare_spec()
    assert spec.allowed_dependencies == ("research.repo.brief@1",)
    output = spec.examples[0]["output"]
    source_ids = {source["source_id"] for source in output["sources"]}
    assert len(output["repositories"]) == 2 and len(output["dimensions"]) == 7
    assert all(set(row["evidence_refs"]) <= source_ids for row in output["dimensions"])


def test_empty_list_dependency_output_is_not_treated_as_call_sequence():
    dependencies = _ExampleDependencies({"markdown.links.extract@1": []})
    assert dependencies.invoke("markdown.links.extract@1", "no links") == []
