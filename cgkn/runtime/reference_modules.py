from __future__ import annotations

from typing import Any


def interpret_requirement(inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    text = inputs["requirement"]["text"].strip()
    constraints = []
    if "不能" in text or "must not" in text.lower():
        constraints.append("Preserve existing single-item archive behavior")
    if "确认" in text or "confirm" in text.lower():
        constraints.append("Bulk archive requires confirmation")
    return {
        "interpretation": {
            "goal": text,
            "explicitRequirements": ["Add bulk archive to the existing Todo application"],
            "constraints": constraints,
            "nonGoals": ["Replace the existing single-item archive path"],
            "ambiguities": [],
            "assumptions": ["Bulk selection uses existing todo identifiers"],
        }
    }


def snapshot_project(inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {"snapshot": dict(inputs["project"])}


def analyze_problem(inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    requirement = inputs["requirement"]
    snapshot = inputs["snapshot"]
    confirmation = any("confirmation" in item.lower() for item in requirement["constraints"])
    capabilities = ["archive a selected batch atomically", "preserve single archive"]
    if confirmation:
        capabilities.append("confirm before bulk archive")
    return {
        "analysis": {
            "observedProblems": ["Only one todo can be archived per action"],
            "rootCauses": ["The service and UI expose only a single-item archive interface"],
            "affectedAreas": snapshot["modules"],
            "requiredCapabilities": capabilities,
            "invariants": ["Existing single-item archive remains behaviorally unchanged"],
            "risks": ["Partial batch updates", "Accidental bulk action without confirmation"] if confirmation else ["Partial batch updates"],
        }
    }


def decide_architecture(inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    capabilities = inputs["analysis"]["requiredCapabilities"]
    confirmation = any("confirm" in item.lower() for item in capabilities)
    decisions = ["Add archive_many(ids) beside archive_one(id)", "Reuse the existing persistence boundary"]
    if confirmation:
        decisions.append("Require explicit UI confirmation before archive_many")
    return {
        "architecture": {
            "decisions": decisions,
            "newConcepts": ["BulkArchiveRequest"],
            "modifiedConcepts": ["TodoService", "TodoListUI"],
            "interfaces": ["archive_many(todo_ids) -> archived_count"],
            "tradeoffs": ["A separate batch API duplicates a small amount of orchestration but protects the single-item contract"],
            "rejectedAlternatives": ["Loop over the public single-item UI action"],
        }
    }


def plan_refactor(inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    decisions = inputs["architecture"]["decisions"]
    needs_confirmation = any("confirmation" in item.lower() for item in decisions)
    steps = ["Add service-level archive_many", "Add selection and bulk archive control", "Cover both single and bulk archive"]
    if needs_confirmation:
        steps.insert(2, "Add confirmation before dispatching the bulk request")
    return {
        "plan": {
            "steps": steps,
            "filesToModify": ["todo/service.py", "todo/ui.py", "tests/test_archive.py"],
            "filesToCreate": [],
            "migrations": [],
            "testRequirements": ["single archive regression", "bulk archive", "empty selection", "confirmation cancellation"] if needs_confirmation else ["single archive regression", "bulk archive", "empty selection"],
            "boundaryRequirements": inputs["snapshot"]["boundaries"],
        }
    }


def apply_code(inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "patch": {
            "changedFiles": list(inputs["plan"]["filesToModify"]),
            "createdFiles": list(inputs["plan"]["filesToCreate"]),
            "deletedFiles": [],
            "commit": None,
        }
    }


def run_tests(inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence": {
            "status": "PASS",
            "testsRun": ["single archive regression", "bulk archive behavior", "empty selection behavior"],
            "passed": 3,
            "failed": 0,
            "evidenceRefs": ["reference-demo:deterministic-tests"],
        }
    }


def validate_boundaries(inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "report": {
            "status": "PASS" if inputs["evidence"]["failed"] == 0 else "FAIL",
            "checks": ["single archive preserved", "writes remain inside declared project paths"],
            "violations": [],
        }
    }


def judge_delivery(inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    passed = inputs["evidence"]["status"] == "PASS" and inputs["boundary"]["status"] == "PASS"
    return {
        "judgment": {
            "evidenceStatus": "PASS" if passed else "NEEDS_REWORK",
            "requiredArtifactsPresent": True,
            "lineageComplete": True,
            "gatesPassed": passed,
            "staleArtifacts": [],
            "diagnostics": [],
        }
    }
