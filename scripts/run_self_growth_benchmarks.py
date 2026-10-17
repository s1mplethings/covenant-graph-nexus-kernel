from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from cgkn.application.capability_builder import CapabilityBuilderService, CapabilitySpec, CapabilityStore  # noqa: E402
from cgkn.application.self_growth import SelfGrowthService  # noqa: E402
from cgkn.providers import ConnectorCompletionClient, GrokConnector, ModelRoleConfig, ProviderConnectorRegistry  # noqa: E402


CASES = (
    (CapabilitySpec("text.slugify", "1", "Convert Unicode text into a stable lowercase ASCII URL slug; collapse separators and trim hyphens.", {"type":"string"}, {"type":"string"}, ({"input":"Hello, World!","output":"hello-world"},{"input":"Café déjà vu","output":"cafe-deja-vu"}), ("standard library only","stable string output")), "Growth Reuse", "growth-reuse"),
    (CapabilitySpec("markdown.links.extract", "1", "Extract Markdown inline links in source order as dictionaries with text and url; ignore images.", {"type":"string"}, {"type":"array"}, ({"input":"[A](a) and [B](b)","output":[{"text":"A","url":"a"},{"text":"B","url":"b"}]},{"input":"![x](image.png) [home](/)","output":[{"text":"home","url":"/"}]}), ("standard library only","ignore images")), "[next](page.md)", [{"text":"next","url":"page.md"}]),
)


def run(output_root: pathlib.Path) -> dict:
    profile = json.loads((ROOT / "config/provider_connections/grok.json").read_text(encoding="utf-8")); connector = GrokConnector(profile)
    selection = json.loads((ROOT / "governance/provider_connections/selection_status.json").read_text(encoding="utf-8"))
    if selection.get("routing_provider") != "grok" or selection.get("repository_codegen_mode") != "SINGLE_PROVIDER_MODE": raise RuntimeError("frozen SINGLE_PROVIDER_MODE selection is unavailable")
    output_root.mkdir(parents=True, exist_ok=False); store = CapabilityStore(output_root / "store")
    builder = CapabilityBuilderService(ConnectorCompletionClient(ProviderConnectorRegistry((connector,)), enforce_budget=True, budget_purpose="CAPABILITY_BUILD", run_id="self-growth", case_id="growth-build"), ModelRoleConfig("worker","grok",120,3000,0.0,"low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=store)
    growth = SelfGrowthService(builder, store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=output_root / "provider_capability_history.json")
    rows = []
    for spec, reuse_input, expected in CASES:
        first = growth.ensure_and_resume(output_root / "candidates", spec, dict(spec.examples[0])["input"])
        second = growth.ensure_and_resume(output_root / "unused", spec, reuse_input)
        passed = first.status == "PASS" and first.growth_invoked and first.builder_invoked and first.resumed and second.status == "PASS" and second.reused and not second.growth_invoked and not second.builder_invoked and second.provider_calls == 0 and second.output == expected
        rows.append({"capability_ref":spec.ref,"first_run":first.as_dict(),"second_run":second.as_dict(),"full_lifecycle_passed":passed,"manual_edits":0})
    passed = sum(row["full_lifecycle_passed"] for row in rows)
    result = {"kind":"SelfGrowthBenchmarkStatus","schema_version":"1.0","mode":"SINGLE_PROVIDER_MODE","provider_id":"grok","routing_frozen":True,"fallback":"deny","cases":rows,"passed":passed,"required":2,"status":"COMPLETE" if passed == 2 else "SELF_GROWTH_NEEDS_REWORK","contains_credentials":False}
    (output_root / "self_growth_status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2)); return result


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--output-root",type=pathlib.Path,required=True); args=parser.parse_args()
    if args.output_root.exists(): raise SystemExit("output root already exists")
    return 0 if run(args.output_root.resolve())["status"] == "COMPLETE" else 2


if __name__ == "__main__": raise SystemExit(main())
