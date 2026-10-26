#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from cgkn.application.learning import FileLessonStore, LessonRecord, LessonScope, LessonStatus, canonical_hash


CREATED_AT = "2026-10-18T00:00:00+00:00"


def _definitions() -> tuple[dict[str, Any], ...]:
    return (
        {
            "key": "cli-exact-interface", "status": LessonStatus.VALIDATED,
            "scope": LessonScope(task_class="project.codegen", operation="GENERATION"),
            "trigger": "CLI_INTERFACE_DRIFT", "guidance": "Implement the exact declared CLI positional and optional argument shapes.",
            "avoid": "Do not turn positional arguments into options or invent aliases.",
            "evidence": ("governance/baselines/receipts/BASELINE-INTERFACE-001.json", "governance/interface_contract_status.json"),
        },
        {
            "key": "dependency-domains", "status": LessonStatus.VALIDATED,
            "scope": LessonScope(task_class="project.codegen", operation="GENERATION"),
            "trigger": "DEPENDENCY_DOMAIN_CONFUSION", "guidance": "Keep runtime and test dependency domains distinct; stdlib-only runtime still permits declared pytest test usage.",
            "avoid": "Do not import test dependencies in runtime source or reject allowed test-only pytest usage.",
            "evidence": ("governance/baselines/receipts/BASELINE-OBLIGATION-004.json", "governance/obligation_compiler_status.json"),
        },
        {
            "key": "composite-bounded-dependencies", "status": LessonStatus.VALIDATED,
            "scope": LessonScope(task_class="capability.build", operation="GENERATION"),
            "trigger": "RAW_NETWORK_IN_COMPOSITE", "guidance": "Composite capabilities must invoke only declared dependencies through ctx.capabilities.",
            "avoid": "Do not import network clients or request raw network access from a composite capability.",
            "evidence": ("governance/capability_dependency_graph.json", "governance/baselines/receipts/BASELINE-SELF-GROWN-LEAVES-001.json"),
        },
        {
            "key": "candidate-dependency-completeness", "status": LessonStatus.VALIDATED,
            "scope": LessonScope(task_class="capability.build", operation="GENERATION"),
            "trigger": "CAPABILITY_DEPENDENCY_MISMATCH", "guidance": "Invoke every required capability dependency and only those declared by the CapabilitySpec.",
            "avoid": "Do not omit required dependencies or invoke undeclared dependencies.",
            "evidence": ("governance/candidate_lifecycle_status.json", "governance/capability_dependency_graph.json"),
        },
        {
            "key": "framework-revalidate", "status": LessonStatus.PROMOTED_TO_POLICY,
            "scope": LessonScope(), "trigger": "FRAMEWORK_VALIDATOR_DEFECT", "guidance": "Revalidate the unchanged candidate after a framework or validator correction.",
            "avoid": "Do not spend a Provider repair call on an unchanged candidate.",
            "evidence": ("governance/candidate_lifecycle_status.json", "governance/validation_action_policy_status.json"),
        },
        {
            "key": "external-wait", "status": LessonStatus.PROMOTED_TO_POLICY,
            "scope": LessonScope(), "trigger": "EXTERNAL_DEPENDENCY_FAILURE", "guidance": "Preserve the candidate and wait for external availability evidence.",
            "avoid": "Do not rewrite candidate source in response to an external outage.",
            "evidence": ("governance/external_dependency_health_status.json", "governance/validation_action_policy_status.json"),
        },
        {
            "key": "immutable-repair", "status": LessonStatus.PROMOTED_TO_POLICY,
            "scope": LessonScope(), "trigger": "CANDIDATE_REPAIR", "guidance": "An authorized repair creates an immutable child CandidateRevision.",
            "avoid": "Do not mutate the parent CandidateRevision.",
            "evidence": ("governance/candidate_lifecycle_status.json", "governance/candidate_revision_index.json"),
        },
        {
            "key": "catalog-data-plane", "status": LessonStatus.PROMOTED_TO_POLICY,
            "scope": LessonScope(provider_id="grok"), "trigger": "CATALOG_FAILURE", "guidance": "A degraded catalog does not block an already pinned and validated Provider data-plane route.",
            "avoid": "Do not refetch the catalog during a frozen production run.",
            "evidence": ("governance/grok_data_plane_status.json", "governance/grok_timeout_authority_status.json"),
        },
    )


def import_lessons(repository: pathlib.Path, artifact_root: pathlib.Path, receipt_path: pathlib.Path) -> dict[str, Any]:
    store = FileLessonStore(artifact_root)
    existing = {item.lesson_id: item for item in store.current_lessons()}
    imported: list[str] = []
    reused: list[str] = []
    records: list[LessonRecord] = []
    for definition in _definitions():
        evidence = tuple(str(item) for item in definition["evidence"])
        missing = [ref for ref in evidence if not (repository / ref).is_file()]
        if missing:
            raise FileNotFoundError("structured lesson evidence missing: " + ",".join(missing))
        scope = definition["scope"]
        lesson_id = LessonRecord.stable_id(scope, definition["trigger"], definition["key"], definition["key"])
        record = LessonRecord(
            lesson_id, 1, definition["status"], scope, definition["trigger"], definition["guidance"],
            definition["avoid"], evidence, 1, 0, CREATED_AT, CREATED_AT,
        )
        records.append(record)
        if lesson_id in existing:
            current = existing[lesson_id]
            semantic = (current.status, current.scope, current.trigger, current.guidance, current.avoid, current.evidence_refs)
            expected = (record.status, record.scope, record.trigger, record.guidance, record.avoid, record.evidence_refs)
            if semantic != expected:
                raise ValueError(f"historical lesson identity collision: {lesson_id}")
            reused.append(lesson_id)
        else:
            store.append_revision(record); imported.append(lesson_id)
    catalog = [item.as_dict() for item in sorted(records, key=lambda item: item.lesson_id)]
    receipt = {
        "kind": "LessonImportReceipt", "schema_version": "1.0", "importer": "deterministic-v0",
        "source_policy": "STRUCTURED_GOVERNANCE_ONLY", "imported_lesson_ids": imported,
        "reused_lesson_ids": reused, "validated_count": sum(item.status is LessonStatus.VALIDATED for item in records),
        "policy_count": sum(item.status is LessonStatus.PROMOTED_TO_POLICY for item in records),
        "catalog_hash": canonical_hash(catalog), "idempotent": True, "contains_credentials": False,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--artifact-root", type=pathlib.Path, required=True)
    parser.add_argument("--receipt", type=pathlib.Path, required=True)
    args = parser.parse_args()
    print(json.dumps(import_lessons(args.repository.resolve(), args.artifact_root.resolve(), args.receipt.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

