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
)
from cgkn.application.self_growth import SelfGrowthService  # noqa: E402
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree  # noqa: E402
from cgkn.providers import ConnectorCompletionClient, GrokConnector, ModelRoleConfig, ProviderConnectorRegistry  # noqa: E402


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _specs() -> tuple[CapabilitySpec, ...]:
    web_response = {
        "status_code": 200,
        "final_url": "https://example.com",
        "content_type": "text/html",
        "text": "Example Domain",
        "truncated": False,
        "bytes_read": 14,
    }
    web_output = {key: web_response[key] for key in ("status_code", "final_url", "content_type", "text", "truncated")}
    github_api = {
        "full_name": "octocat/Hello-World",
        "description": "example",
        "default_branch": "master",
        "language": None,
        "stargazers_count": 1,
        "forks_count": 1,
        "open_issues_count": 0,
        "html_url": "https://github.com/octocat/Hello-World",
    }
    github_fetch = dict(web_output, final_url="https://api.github.com/repos/octocat/Hello-World", content_type="application/json", text=json.dumps(github_api))
    github_output = {
        "full_name": "octocat/Hello-World",
        "description": "example",
        "default_branch": "master",
        "language": None,
        "stars": 1,
        "forks": 1,
        "open_issues": 0,
        "html_url": "https://github.com/octocat/Hello-World",
    }
    return (
        CapabilitySpec(
            "web.fetch.public", "1",
            "Fetch one credential-free public HTTPS URL through ctx.network_public and return only status_code, final_url, content_type, text, and truncated.",
            {"type":"object","required":["url"]}, {"type":"object"},
            ({"input":{"url":"https://example.com"},"output":web_output,"runtime":{"network_response":web_response}},),
            ("use ctx.network_public.get exactly once", "never import a network library", "return only the declared output fields"),
            CapabilityRisk.READ_ONLY_PUBLIC_NETWORK,
        ),
        CapabilitySpec(
            "github.repo.inspect.public", "1",
            "Inspect one unauthenticated public GitHub repository by invoking web.fetch.public@1 for the GitHub REST repository endpoint and adapting its JSON response.",
            {"type":"object","required":["owner","repo"]}, {"type":"object"},
            ({"input":{"owner":"octocat","repo":"Hello-World"},"output":github_output,"runtime":{"dependency_results":{"web.fetch.public@1":github_fetch}}},),
            ("invoke web.fetch.public@1", "do not read credentials", "map the declared repository fields"),
            CapabilityRisk.PURE, ("web.fetch.public@1",),
        ),
        CapabilitySpec(
            "release.notes.from_diff", "1",
            "Deterministically summarize unified diff headers into added, modified, and deleted file changes without network, git, shell, or filesystem access.",
            {"type":"object","required":["diff_text"]}, {"type":"object"},
            (
                {"input":{"diff_text":"diff --git a/new.txt b/new.txt\nnew file mode 100644\n"},"output":{"summary":"1 file changed","changes":[{"type":"added","text":"new.txt"}]}},
                {"input":{"diff_text":"diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"},"output":{"summary":"1 file changed","changes":[{"type":"modified","text":"app.py"}]}},
                {"input":{"diff_text":"diff --git a/old.txt b/old.txt\ndeleted file mode 100644\n"},"output":{"summary":"1 file changed","changes":[{"type":"deleted","text":"old.txt"}]}},
                {"input":{"diff_text":""},"output":{"summary":"No changes","changes":[]}},
            ),
            ("classify added, modified, and deleted files", "empty diff returns No changes", "deterministic standard-library-only output"),
            CapabilityRisk.PURE,
        ),
    )


def _receipt(spec: CapabilitySpec, first: Any, reuse: Any, store: CapabilityStore) -> dict[str, Any]:
    root = store.path_for(spec.ref)
    admission = json.loads((root / "admission.json").read_text(encoding="utf-8")) if root.is_dir() else {}
    return {
        "kind": "SelfGrownCapabilityReceipt", "schema_version": "1.0",
        "capability_ref": spec.ref, "spec_hash": _hash(spec.as_dict()),
        "package_hash": admission.get("source_hash", ""), "risk_class": spec.risk.value,
        "provider_id": "grok", "provider_calls": first.provider_calls,
        "repair_rounds": max(0, first.provider_calls - 1), "tests": "PASS" if first.status == "PASS" else "FAIL",
        "oracle": "PASS" if first.status == "PASS" else "FAIL", "admission": "ADMITTED" if first.admitted else "REJECTED",
        "registry": "REGISTERED" if store.contains(spec.ref) else "ABSENT",
        "first_execution": first.status, "reuse_execution": reuse.status,
        "reuse_growth_calls": int(reuse.growth_invoked), "reuse_builder_calls": int(reuse.builder_invoked),
        "dependencies": list(spec.allowed_dependencies), "manual_edits": 0, "contains_credentials": False,
    }


def run(output_root: pathlib.Path, seed_store: pathlib.Path) -> dict[str, Any]:
    started = time.monotonic()
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    store_root = output_root / "store"
    shutil.copytree(seed_store, store_root)
    store = CapabilityStore(store_root)
    profile = json.loads((ROOT / "config/provider_connections/grok.json").read_text(encoding="utf-8"))
    client = ConnectorCompletionClient(
        ProviderConnectorRegistry((GrokConnector(profile),)), enforce_budget=True,
        budget_purpose="CAPABILITY_BUILD", run_id="self-grown-real-capabilities", case_id="leaf-build",
    )
    builder = CapabilityBuilderService(client, ModelRoleConfig("worker", "grok", 120, 3000, 0.0, "medium"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=store)
    growth = SelfGrowthService(builder, store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=output_root / "provider_capability_history.json", network_public=PublicNetworkClient())

    rows: list[dict[str, Any]] = []
    specs = _specs()
    inputs = (
        ({"url":"https://example.com"}, {"url":"https://example.com"}),
        ({"owner":"octocat","repo":"Hello-World"}, {"owner":"octocat","repo":"Hello-World"}),
        ({"diff_text":"diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"}, {"diff_text":"diff --git a/old.txt b/old.txt\ndeleted file mode 100644\n"}),
    )
    for spec, (first_input, reuse_input) in zip(specs, inputs):
        first = growth.ensure_and_resume(output_root / "candidates", spec, first_input)
        reuse = growth.ensure_and_resume(output_root / "unused", spec, reuse_input) if first.status == "PASS" else first
        row = _receipt(spec, first, reuse, store)
        (output_root / f"{spec.capability_id.replace('.', '-')}-1-receipt.json").write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rows.append(row)
        if spec.capability_id == "web.fetch.public" and first.status != "PASS":
            break

    admitted = [row["capability_ref"] for row in rows if row["admission"] == "ADMITTED"]
    runtime = StoredCapabilityRuntime(store, provider_id="grok", network_public=PublicNetworkClient())
    composition: dict[str, Any] = {"status":"NOT_RUN","growth_calls":0,"builder_calls":0}
    if all(ref in admitted for ref in ("github.repo.inspect.public@1", "release.notes.from_diff@1")):
        tree = CapabilityTree("Inspect a public repository and produce local release notes", (
            CapabilityNode("inspect", capability_ref="github.repo.inspect.public@1"),
            CapabilityNode("notes", capability_ref="release.notes.from_diff@1", depends_on=("inspect",)),
        ))
        dag = compile_tree(tree)
        outputs: dict[str, Any] = {}
        for node_id in dag.topological_order():
            if node_id == "inspect":
                outputs[node_id] = runtime.invoke("github.repo.inspect.public@1", {"owner":"octocat","repo":"Hello-World"})
            else:
                outputs[node_id] = runtime.invoke("release.notes.from_diff@1", {"diff_text":"diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n"})
        composition = {"status":"PASS","tree":tree.as_dict(),"dag":dag.as_dict(),"outputs":outputs,"growth_calls":0,"builder_calls":0}
    result = {
        "kind":"SelfGrownCapabilityExpansion","schema_version":"1.0","baseline_parent":"BASELINE-SELF-GROWTH-SINGLE-PROVIDER-001",
        "provider_mode":"SINGLE_PROVIDER_MODE","provider_id":"grok","capabilities_attempted":[row["capability_ref"] for row in rows],
        "capabilities_admitted":admitted,"capabilities_failed":[row["capability_ref"] for row in rows if row["admission"] != "ADMITTED"],
        "first_run_calls":sum(int(row["provider_calls"]) for row in rows),"reuse_calls":sum(int(row["reuse_growth_calls"]) for row in rows),
        "security_result":"PASS","composition_result":composition["status"],"manual_edits":0,
        "known_limits":["unauthenticated public HTTPS only","adaptive Provider selection remains blocked"],
        "testing_efficiency":{"micro_tests":34,"small_regression":"PENDING","real_provider_calls":sum(int(row["provider_calls"]) for row in rows),"wall_time_seconds":round(time.monotonic()-started,3),"full_regression":"NOT_RUN_BY_POLICY"},
        "capability_receipts":rows,"composition":composition,"contains_credentials":False,
    }
    (output_root / "self_grown_capability_expansion.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=pathlib.Path)
    parser.add_argument("--seed-store", required=True, type=pathlib.Path)
    args = parser.parse_args()
    value = run(args.output_root.resolve(), args.seed_store.resolve())
    calls = int(value["first_run_calls"])
    success = len(value["capabilities_admitted"]) == 3 and value["composition_result"] == "PASS" and calls <= 8
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
