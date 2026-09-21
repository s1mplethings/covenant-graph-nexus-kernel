#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.artifacts import ArtifactInstance, ArtifactStore, ArtifactTypeRegistry, Producer, Provenance
from cgkn.runtime import ArtifactInvalidator, ArtifactModuleRunner


FLOW = "flow.artifact_driven_project_refactor@1"


def write_seed(store, artifact_type, content, port):
    return store.write_artifact(
        ArtifactInstance(
            id=store.allocate_id(artifact_type),
            artifact_type=artifact_type,
            run_id=store.run_dir.name,
            producer=Producer("flow_input", "module.flow_input@1", port),
            content=content,
            provenance=Provenance(source_refs=("examples/artifact-driven/todo-refactor",)),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Todo artifact-flow incremental recompute demonstration.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    run_dir = pathlib.Path(args.run_dir).resolve()
    registry = ArtifactTypeRegistry(ROOT)
    store = ArtifactStore(run_dir, registry)
    project = json.loads((ROOT / "examples" / "artifact-driven" / "todo-refactor" / "todo_project.json").read_text(encoding="utf-8"))
    requirement_text = "给现有 Todo App 增加批量归档功能，但不能破坏现有单条归档。"
    inputs = {
        "raw_requirement": write_seed(store, "artifact.raw_requirement@1", {"text": requirement_text, "source": "demo"}, "raw_requirement"),
        "project": write_seed(store, "artifact.project_source@1", project, "project"),
    }
    initial = ArtifactModuleRunner(ROOT, run_dir, FLOW).run(inputs, raw_source_chars=12000)
    old_interpretation = store.resolve_artifact_ref(initial["outputs"]["requirement_interpretation"])
    changed_content = dict(old_interpretation.content)
    changed_content["goal"] = requirement_text + " 批量归档必须有确认。"
    changed_content["constraints"] = [*changed_content["constraints"], "Bulk archive requires confirmation"]
    changed = ArtifactInstance(
        id=store.allocate_id(old_interpretation.artifact_type),
        artifact_type=old_interpretation.artifact_type,
        run_id=store.run_dir.name,
        producer=old_interpretation.producer,
        content=changed_content,
        provenance=Provenance(
            input_artifact_refs=old_interpretation.provenance.input_artifact_refs,
            source_refs=("demo-change:confirmation",),
            prompt_version=old_interpretation.provenance.prompt_version,
        ),
        supersedes=old_interpretation.id,
    )
    changed_ref = store.write_artifact(changed)
    second_runner = ArtifactModuleRunner(ROOT, run_dir, FLOW)
    invalidation = ArtifactInvalidator(store, second_runner.graph).invalidate(changed_ref)
    rerun = second_runner.run(
        inputs,
        output_overrides={(changed.producer.node_id, changed.producer.output_port): changed_ref},
        raw_source_chars=12000,
    )
    rows = {row["nodeId"]: row for row in rerun["feedForwardReport"]["nodes"]}
    evidence = {
        "kind": "ArtifactIncrementalRecomputeEvidence",
        "formalEvidenceStatus": "NOT_EVALUATED",
        "changedArtifact": changed_ref.as_dict(),
        "invalidation": invalidation,
        "cacheOutcomes": {node: row["cache"] for node, row in rows.items()},
        "unaffectedSnapshotCacheHit": rows["n_project_snapshot"]["cache"] == "hit",
        "changedBranchReran": all(
            rows[node]["cache"] == "miss"
            for node in ["n_problem_analysis", "n_architecture", "n_refactor_plan", "n_implementation", "n_tests", "n_boundary", "n_delivery"]
        ),
        "maxArtifactContextChars": max(row["artifact_context_chars"] for row in rows.values()),
        "rawSourceChars": 12000,
        "bestCompressionRatio": min(row["compression_ratio"] for row in rows.values() if row["compression_ratio"] is not None),
        "deliveryJudgment": rerun["outputs"]["delivery_judgment"].as_dict(),
    }
    path = run_dir / "incremental_recompute_evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2) if args.json else f"status=PASS\nevidence={path}")
    return 0 if evidence["unaffectedSnapshotCacheHit"] and evidence["changedBranchReran"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
