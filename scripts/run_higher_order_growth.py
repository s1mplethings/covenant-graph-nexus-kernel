from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.capability_builder import (  # noqa: E402
    CapabilityBuilderService,
    CapabilityRisk,
    CapabilitySpec,
    CapabilityStore,
    PublicNetworkClient,
    StoredCapabilityRuntime,
    inspect_capability_health,
)
from cgkn.application.self_growth import SelfGrowthService  # noqa: E402
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree  # noqa: E402
from cgkn.providers import ConnectorCompletionClient, GrokConnector, ModelRoleConfig, ProviderConnectorRegistry  # noqa: E402


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _brief(metadata: dict[str, Any], question: str, readme_status: int = 200) -> dict[str, Any]:
    full_name = metadata["full_name"]
    github_id = f"github:{full_name}"
    readme_id = f"readme:{full_name}"
    available = readme_status == 200
    sources = [{"source_id": github_id, "url": metadata["html_url"], "kind": "github.repository"}]
    claims = [{"claim_id": "default-branch", "text": f"{full_name} uses {metadata['default_branch']} as its default branch.", "evidence_refs": [github_id]}]
    if available:
        sources.append({"source_id": readme_id, "url": f"https://raw.githubusercontent.com/{full_name}/{metadata['default_branch']}/README.md", "kind": "github.readme"})
        claims.append({"claim_id": "readme-available", "text": f"README content was retrieved for {full_name}.", "evidence_refs": [readme_id]})
    return {
        "repository": {**metadata, "readme_available": available},
        "question": question,
        "summary": metadata.get("description") or f"{full_name} is a public GitHub repository.",
        "claims": claims,
        "sources": sources,
        "limitations": [] if available else ["README unavailable; brief is based on repository metadata only."],
    }


def repo_brief_spec() -> CapabilitySpec:
    metadata = {"full_name":"octo/alpha","default_branch":"main","description":"Alpha toolkit","html_url":"https://github.com/octo/alpha","language":"Python","stars":10,"forks":2,"open_issues":1}
    readme = {"status_code":200,"final_url":"https://raw.githubusercontent.com/octo/alpha/main/README.md","content_type":"text/plain","text":"# Alpha\n[Docs](https://example.test/docs)","truncated":False}
    unavailable = dict(readme, status_code=404, text="Not Found")
    deps_ok = {"github.repo.inspect.public@1":metadata,"web.fetch.public@1":readme,"markdown.links.extract@1":[{"text":"Docs","url":"https://example.test/docs"}]}
    deps_partial = {"github.repo.inspect.public@1":metadata,"web.fetch.public@1":unavailable,"markdown.links.extract@1":[]}
    return CapabilitySpec(
        "research.repo.brief", "1",
        "Produce a deterministic, source-bound repository brief. Invoke each declared dependency exactly once. Fetch the raw README for the resolved default branch, pass at most its first 65536 characters to the Markdown link extractor, and never use raw network APIs. A README is available only when status_code is 200. Use the exact stable source IDs and sentence formats demonstrated by the examples.",
        {"type":"object","required":["owner","repo","question"]},
        {"type":"object","required":["repository","question","summary","claims","sources","limitations"]},
        (
            {"input":{"owner":"octo","repo":"alpha","question":"What is it?"},"output":_brief(metadata,"What is it?"),"runtime":{"dependency_results":deps_ok}},
            {"input":{"owner":"octo","repo":"alpha","question":"What is available?"},"output":_brief(metadata,"What is available?",404),"runtime":{"dependency_results":deps_partial}},
        ),
        (
            "invoke github.repo.inspect.public@1, web.fetch.public@1, and markdown.links.extract@1 exactly once",
            "every claim has a nonempty evidence_refs list resolving to a unique source_id",
            "README input to markdown.links.extract@1 is bounded to 65536 characters",
            "return only deterministic data derived from the input and dependency results",
            "do not import or call any network library and do not use ctx.network_public",
        ),
        CapabilityRisk.READ_ONLY_PUBLIC_NETWORK_COMPOSITE,
        ("github.repo.inspect.public@1", "web.fetch.public@1", "markdown.links.extract@1"),
    )


def _comparison(first: dict[str, Any], second: dict[str, Any], question: str) -> dict[str, Any]:
    a, b = first["repository"], second["repository"]
    evidence = [first["sources"][0]["source_id"], second["sources"][0]["source_id"]]
    dimensions = []
    for name, key in (("description","description"),("primary language","language"),("stars","stars"),("forks","forks"),("open issues","open_issues"),("default branch","default_branch"),("README availability","readme_available")):
        dimensions.append({"name":name,"repo_a":str(a.get(key)),"repo_b":str(b.get(key)),"evidence_refs":evidence})
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in first["sources"] + second["sources"]:
        if source["source_id"] not in seen:
            seen.add(source["source_id"]); sources.append(source)
    return {
        "question": question,
        "repositories": [{"full_name":a["full_name"],"brief_ref":f"brief:{a['full_name']}"},{"full_name":b["full_name"],"brief_ref":f"brief:{b['full_name']}"}],
        "dimensions": dimensions,
        "summary": f"Compared {a['full_name']} and {b['full_name']} across seven factual repository dimensions.",
        "sources": sources,
        "limitations": list(dict.fromkeys(first["limitations"] + second["limitations"])),
    }


def compare_spec() -> CapabilitySpec:
    alpha_meta = {"full_name":"octo/alpha","default_branch":"main","description":"Alpha toolkit","html_url":"https://github.com/octo/alpha","language":"Python","stars":10,"forks":2,"open_issues":1}
    beta_meta = {"full_name":"octo/beta","default_branch":"master","description":None,"html_url":"https://github.com/octo/beta","language":None,"stars":3,"forks":1,"open_issues":0}
    first = _brief(alpha_meta, "Compare them")
    second = _brief(beta_meta, "Compare them", 404)
    value = {"repositories":[{"owner":"octo","repo":"alpha"},{"owner":"octo","repo":"beta"}],"question":"Compare them"}
    return CapabilitySpec(
        "research.compare.repos", "1",
        "Compare exactly two repositories by invoking research.repo.brief@1 once per repository. Preserve and deduplicate source evidence, compare only description, primary language, stars, forks, open issues, default branch, and README availability, and use the exact stable formatting demonstrated by the example.",
        {"type":"object","required":["repositories","question"],"properties":{"repositories":{"type":"array","minItems":2,"maxItems":2}}},
        {"type":"object","required":["question","repositories","dimensions","summary","sources","limitations"]},
        ({"input":value,"output":_comparison(first,second,"Compare them"),"runtime":{"dependency_results":{"research.repo.brief@1":[first,second]}}},),
        (
            "reject inputs that do not contain exactly two repositories",
            "invoke research.repo.brief@1 exactly twice and no other capability",
            "produce seven factual dimensions with evidence_refs",
            "preserve and deduplicate sources by source_id",
            "make no unsupported recommendation or quality ranking",
        ),
        CapabilityRisk.READ_ONLY_PUBLIC_NETWORK_COMPOSITE,
        ("research.repo.brief@1",),
    )


def _capability_receipt(spec: CapabilitySpec, first: Any, reuse: Any, store: CapabilityStore) -> dict[str, Any]:
    admission = json.loads((store.path_for(spec.ref) / "admission.json").read_text(encoding="utf-8")) if store.contains(spec.ref) else {}
    return {
        "kind":"HigherOrderCapabilityReceipt","schema_version":"1.0","capability_ref":spec.ref,
        "spec_hash":_hash(spec.as_dict()),"package_hash":admission.get("source_hash","") ,
        "provider":"grok","routing_mode":"SINGLE_PROVIDER_MODE","fallback":"deny",
        "provider_calls":first.provider_calls,"repair_rounds":max(0,first.provider_calls-1),
        "dependencies":admission.get("dependency_manifest",[]),"build":first.status,
        "admission":"ADMITTED" if store.contains(spec.ref) else "REJECTED","reuse":reuse.status,
        "reuse_growth_calls":int(reuse.growth_invoked),"reuse_builder_calls":int(reuse.builder_invoked),
        "manual_candidate_edits":0,"contains_credentials":False,
    }


def run(output_root: pathlib.Path, seed_store: pathlib.Path) -> dict[str, Any]:
    started = time.monotonic()
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    shutil.copytree(seed_store, output_root / "store")
    store = CapabilityStore(output_root / "store")
    baseline_refs = ("web.fetch.public@1","github.repo.inspect.public@1","markdown.links.extract@1","release.notes.from_diff@1")
    local_health = [inspect_capability_health(store, ref).as_dict() for ref in baseline_refs]
    if not all(row["local_healthy"] for row in local_health):
        result = {"status":"LOCAL_INTEGRITY_BLOCKER","local_health":local_health,"provider_calls":0}
        (output_root / "higher_order_growth.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
        return result
    profile = json.loads((ROOT / "config/provider_connections/grok.json").read_text(encoding="utf-8"))
    client = ConnectorCompletionClient(ProviderConnectorRegistry((GrokConnector(profile),)), enforce_budget=True, budget_purpose="CAPABILITY_BUILD", run_id="higher-order-growth", case_id="research-capabilities")
    builder = CapabilityBuilderService(client, ModelRoleConfig("worker","grok",120,3000,0.0,"medium"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=store)
    growth = SelfGrowthService(builder, store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=output_root / "provider_capability_history.json", network_public=PublicNetworkClient())
    specs = (repo_brief_spec(), compare_spec())
    smoke_inputs = ({"owner":"octocat","repo":"Hello-World","question":"What does this repository expose?"},{"repositories":[{"owner":"octocat","repo":"Hello-World"},{"owner":"octocat","repo":"Spoon-Knife"}],"question":"Compare these repositories"})
    receipts: list[dict[str, Any]] = []
    for spec, smoke_input in zip(specs, smoke_inputs):
        first = growth.ensure_and_resume(output_root / "candidates", spec, smoke_input)
        if first.status != "PASS":
            receipts.append(_capability_receipt(spec, first, first, store)); break
        reuse = growth.ensure_and_resume(output_root / "reuse-unused", spec, smoke_input)
        receipts.append(_capability_receipt(spec, first, reuse, store))
    runtime = StoredCapabilityRuntime(store, provider_id="grok", network_public=PublicNetworkClient())
    composition: dict[str, Any] = {"status":"NOT_RUN","growth_calls":0,"builder_calls":0,"admission_calls":0}
    if store.contains("research.compare.repos@1"):
        tree = CapabilityTree("Compose repository comparison with deterministic release notes",(
            CapabilityNode("research",capability_ref="research.compare.repos@1"),
            CapabilityNode("release",capability_ref="release.notes.from_diff@1"),
            CapabilityNode("compose",capability_ref="compose.research_release_summary@local",depends_on=("research","release")),
        ))
        dag = compile_tree(tree)
        comparison = runtime.invoke("research.compare.repos@1", smoke_inputs[1])
        release = runtime.invoke("release.notes.from_diff@1", {"diff_text":"diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n"})
        composition = {"status":"PASS","tree":tree.as_dict(),"dag":dag.as_dict(),"artifacts":{"research":comparison,"release":release,"compose":{"research_summary":comparison["summary"],"release_summary":release["summary"]}},"growth_calls":0,"builder_calls":0,"admission_calls":0}
    total_calls = sum(int(row["provider_calls"]) for row in receipts)
    success = len(receipts) == 2 and all(row["build"] == row["reuse"] == "PASS" and row["reuse_growth_calls"] == row["reuse_builder_calls"] == 0 for row in receipts) and composition["status"] == "PASS" and total_calls <= 4
    result = {
        "kind":"HigherOrderGrowthRun","schema_version":"1.0","status":"PASS" if success else "HIGHER_ORDER_GROWTH_PARTIAL",
        "api_role_snapshot":{"task_class":"capability.build","selected_provider":"grok","reason":"only READY provider; SINGLE_PROVIDER_MODE","provider_status":"READY","routing_mode":"SINGLE_PROVIDER_MODE","fallback":"deny"},
        "local_health":local_health,"capabilities":receipts,"provider_calls":total_calls,"composition":composition,
        "manual_candidate_edits":0,"unsafe_admissions":0,"full":"NOT_RUN_BY_POLICY","wall_time_seconds":round(time.monotonic()-started,3),"contains_credentials":False,
    }
    (output_root / "higher_order_growth.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root",required=True,type=pathlib.Path)
    parser.add_argument("--seed-store",required=True,type=pathlib.Path)
    args = parser.parse_args()
    return 0 if run(args.output_root.resolve(),args.seed_store.resolve())["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
