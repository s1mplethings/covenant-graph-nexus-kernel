#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from cgkn.application.learning import FileLessonStore, ProductionGenerationClient, StoreLessonReader
from cgkn.application.project_production import AutonomousProjectProductionService
from cgkn.providers import ConnectorCompletionClient, GrokConnector, ModelRoleConfig, ProviderConnectorRegistry, completion_client_from_environment
from scripts.import_historical_lessons import import_lessons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=pathlib.Path, required=True)
    parser.add_argument("--model", default="grok")
    args = parser.parse_args()
    repository = REPOSITORY
    artifact_root = args.artifact_root.resolve(); artifact_root.mkdir(parents=True, exist_ok=True)
    learning_root = artifact_root / "learning"
    import_lessons(repository, learning_root, artifact_root / "lesson_import_receipt.json")
    os.environ["CGKN_LEARNING_ARTIFACT_ROOT"] = str(learning_root)
    store = FileLessonStore(learning_root)
    if args.model == "grok":
        profile = json.loads((repository / "config/provider_connections/grok.json").read_text(encoding="utf-8"))
        provider_client = ConnectorCompletionClient(ProviderConnectorRegistry((GrokConnector(profile),)))
    else:
        provider_client = completion_client_from_environment()
    generation = ProductionGenerationClient(provider_client, StoreLessonReader(store), store=store, max_provider_calls=5)
    service = AutonomousProjectProductionService(
        repository, artifact_root / "project_runs", generation,
        ModelRoleConfig("worker", args.model, timeout_seconds=180, max_output_tokens=8000, temperature=0.0, reasoning_effort="low"),
    )
    result = service.run_folder_manifest()
    output = {"status": result.status, "workspace": result.workspace, "package_path": result.package_path, "receipt": dict(result.receipt)}
    (artifact_root / "latest_result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

