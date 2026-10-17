from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from cgkn.application.capability_builder import CapabilityBuilderService, CapabilitySpec, CapabilityStore  # noqa: E402
from cgkn.providers import ConnectorCompletionClient, GrokConnector, ModelRoleConfig, ProviderConnectorRegistry  # noqa: E402


CASES = (
    CapabilitySpec("text.slugify", "1", "Convert Unicode text into a stable lowercase ASCII URL slug; collapse separators and trim hyphens.", {"type": "string"}, {"type": "string"}, (
        {"input": "Hello, World!", "output": "hello-world"}, {"input": "  Café déjà vu  ", "output": "cafe-deja-vu"}, {"input": "A___B", "output": "a-b"}), ("use only Python standard library", "support Unicode transliteration", "return a string")),
    CapabilitySpec("markdown.links.extract", "1", "Extract Markdown inline links in source order as dictionaries with text and url; ignore images.", {"type": "string"}, {"type": "array"}, (
        {"input": "See [OpenAI](https://openai.com) and [Docs](docs/readme.md).", "output": [{"text": "OpenAI", "url": "https://openai.com"}, {"text": "Docs", "url": "docs/readme.md"}]},
        {"input": "![logo](logo.png) [home](/)", "output": [{"text": "home", "url": "/"}]}, {"input": "plain text", "output": []}), ("use only Python standard library", "ignore image syntax", "preserve source order")),
    CapabilitySpec("json.path.get", "1", "Read nested dictionaries and lists with a dot path; numeric segments index lists and missing paths return None.", {"type": "object"}, {}, (
        {"input": {"document": {"a": {"b": 3}}, "path": "a.b"}, "output": 3}, {"input": {"document": {"items": [{"name": "x"}]}, "path": "items.0.name"}, "output": "x"}, {"input": {"document": {}, "path": "missing"}, "output": None}), ("use only Python standard library", "return None for missing or invalid paths", "do not mutate input")),
)


def run(output_root: pathlib.Path) -> dict:
    profile = json.loads((ROOT / "config/provider_connections/grok.json").read_text(encoding="utf-8"))
    connector = GrokConnector(profile)
    if not connector.probe_connection().eligible:
        raise RuntimeError("SINGLE_PROVIDER_MODE requires the frozen Grok connection to remain eligible")
    output_root.mkdir(parents=True, exist_ok=False)
    service = CapabilityBuilderService(ConnectorCompletionClient(ProviderConnectorRegistry((connector,))), ModelRoleConfig("worker", "grok", 120, 3000, 0.0, "low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=CapabilityStore(output_root / "store"))
    receipts = []
    for spec in CASES:
        receipt = service.build(output_root / "candidates", spec).as_dict()
        (output_root / (_filename(spec.ref) + "_receipt.json")).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        receipts.append(receipt)
    passed = sum(item["status"] == "PASS" for item in receipts)
    result = {"kind": "CapabilityBuilderBenchmarkStatus", "schema_version": "1.0", "mode": "SINGLE_PROVIDER_MODE", "provider_id": "grok", "eligible_provider_count": 1, "routing_frozen": True, "fallback": "deny", "cases": receipts, "passed": passed, "required": 2, "manual_edits": 0, "status": "COMPLETE" if passed >= 2 else "CAPABILITY_BUILDER_NEEDS_REWORK", "contains_credentials": False}
    (output_root / "capability_builder_status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _filename(value: str) -> str:
    return value.replace("@", "-").replace(".", "-")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-root", type=pathlib.Path, required=True); args = parser.parse_args()
    if args.output_root.exists(): raise SystemExit("output root already exists")
    result = run(args.output_root.resolve()); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__": raise SystemExit(main())
