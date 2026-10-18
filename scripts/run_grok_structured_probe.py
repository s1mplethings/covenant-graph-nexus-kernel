from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.providers import (  # noqa: E402
    ConnectorCompletionClient,
    GrokConnector,
    ModelRoleConfig,
    ProviderConnectorRegistry,
    parse_json_object,
)


PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok"]},
        "files": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string", "enum": ["executor.py"]}, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["status", "files"],
    "additionalProperties": False,
}


def run(output: pathlib.Path) -> dict[str, object]:
    profile = json.loads((ROOT / "config/provider_connections/grok.json").read_text(encoding="utf-8"))
    connector = GrokConnector(profile)
    client = ConnectorCompletionClient(
        ProviderConnectorRegistry((connector,)),
        enforce_budget=True,
        budget_purpose="CAPABILITY_BUILD",
        run_id="grok-timeout-authority-probe",
        case_id="builder-compatible-structured-probe",
    )
    started = time.monotonic()
    try:
        completion = client.complete(
            system="Return one tiny strict JSON object. Do not use markdown.",
            user="Return status ok and one executor.py file whose content defines execute(value) and returns value.",
            schema_name="builder_compatible_probe",
            schema=PROBE_SCHEMA,
            config=ModelRoleConfig("worker", "grok", 180, 768, 0.0, "medium"),
        )
        parsed = parse_json_object(completion.text)
        usage = dict(completion.usage)
        passed = parsed.get("status") == "ok" and len(parsed.get("files", [])) == 1 and usage.get("effective_timeout_seconds") == 180
        result: dict[str, object] = {
            "kind":"GrokStructuredProbe","schema_version":"1.0","status":"PASS" if passed else "FAIL",
            "provider":"grok","requested_timeout_seconds":usage.get("requested_timeout_seconds"),
            "effective_timeout_seconds":usage.get("effective_timeout_seconds"),
            "provider_default_timeout_seconds":usage.get("provider_default_timeout_seconds"),
            "provider_max_timeout_seconds":usage.get("provider_max_timeout_seconds"),
            "elapsed_ms":usage.get("elapsed_ms",int((time.monotonic()-started)*1000)),
            "reasoning_effort":"medium","schema_valid":passed,"request_id":completion.request_id,
            "actual_model":completion.model,"usage":usage,"response_content_saved":False,"contains_credentials":False,
        }
    except Exception as exc:
        result = {
            "kind":"GrokStructuredProbe","schema_version":"1.0","status":"FAIL",
            "provider":"grok","requested_timeout_seconds":180,"effective_timeout_seconds":getattr(exc,"evidence",{}).get("effective_timeout_seconds"),
            "elapsed_ms":getattr(exc,"evidence",{}).get("elapsed_ms",int((time.monotonic()-started)*1000)),
            "error_class":getattr(exc,"error_class",type(exc).__name__),"timeout_phase":getattr(exc,"timeout_phase",""),
            "outcome_unknown":getattr(exc,"outcome_unknown",False),"response_content_saved":False,"contains_credentials":False,
        }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True,type=pathlib.Path)
    args=parser.parse_args()
    return 0 if run(args.output.resolve())["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
