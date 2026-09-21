#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.artifacts import ArtifactInstance, ArtifactRef, ArtifactStore, ArtifactTypeRegistry, Producer, Provenance
from cgkn.runtime import ArtifactInvalidator, ArtifactModuleRunner


FLOW_REF = "flow.artifact_driven_project_refactor@1"


def _seed(store: ArtifactStore, artifact_type: str, content: dict, port: str) -> ArtifactRef:
    instance = ArtifactInstance(
        id=store.allocate_id(artifact_type),
        artifact_type=artifact_type,
        run_id=store.run_dir.name,
        producer=Producer("flow_input", "module.flow_input@1", port),
        content=content,
        provenance=Provenance(source_refs=("cli",)),
    )
    return store.write_artifact(instance)


def _manifest_inputs(store: ArtifactStore) -> dict[str, ArtifactRef]:
    path = store.run_dir / "run_manifest.json"
    if not path.is_file():
        return {}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    refs = [ArtifactRef.from_dict(item) for item in manifest.get("inputArtifacts", [])]
    result = {}
    for ref in refs:
        if ref.artifact_type == "artifact.raw_requirement@1":
            result["raw_requirement"] = ref
        elif ref.artifact_type == "artifact.project_source@1":
            result["project"] = ref
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or partially recompute a local typed artifact flow.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--flow", default=FLOW_REF)
    parser.add_argument("--requirement", default="")
    parser.add_argument("--project-json", default="")
    parser.add_argument("--raw-source-chars", type=int, default=0)
    parser.add_argument("--from-artifact", default="")
    parser.add_argument("--invalidate", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    run_dir = pathlib.Path(args.run_dir).resolve()
    registry = ArtifactTypeRegistry(ROOT)
    store = ArtifactStore(run_dir, registry)
    inputs = _manifest_inputs(store)
    if not inputs:
        if not args.requirement or not args.project_json:
            parser.error("a new run requires --requirement and --project-json")
        project = json.loads(pathlib.Path(args.project_json).read_text(encoding="utf-8"))
        inputs = {
            "raw_requirement": _seed(store, "artifact.raw_requirement@1", {"text": args.requirement, "source": "cli"}, "raw_requirement"),
            "project": _seed(store, "artifact.project_source@1", project, "project"),
        }

    runner = ArtifactModuleRunner(ROOT, run_dir, args.flow)
    target = args.from_artifact or args.invalidate
    invalidation = None
    overrides = None
    if target:
        artifact = store.resolve_artifact_ref(target)
        invalidator = ArtifactInvalidator(store, runner.graph)
        invalidation = invalidator.invalidate(artifact.ref, dry_run=args.dry_run)
        if args.dry_run:
            print(json.dumps(invalidation, ensure_ascii=False, indent=2))
            return 0
        overrides = {(artifact.producer.node_id, artifact.producer.output_port): artifact.ref}
    result = runner.run(inputs, output_overrides=overrides, raw_source_chars=args.raw_source_chars or len(args.requirement))
    payload = {
        "status": "PASS",
        "runDir": str(run_dir),
        "outputs": {key: value.as_dict() for key, value in result["outputs"].items()},
        "invalidation": invalidation,
        "feedForwardReport": result["feedForwardReport"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else f"status=PASS\nrun_dir={run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
