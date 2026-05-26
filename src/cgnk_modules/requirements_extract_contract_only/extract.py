from __future__ import annotations

import re
from typing import Any

from cgnk_core.diagnostics import (
    CGNK_REQUIREMENTS_EXTRACT_INSUFFICIENT_CONTEXT,
    CGNK_REQUIREMENTS_EXTRACT_INVALID_INPUT,
    Diagnostic,
)

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF

CONSTRAINT_MARKERS = ("must", "must not", "do not", "without", "avoid", "no ", "forbidden", "only")
UNSUPPORTED_KEYWORDS = {
    "provider": "provider_call",
    "llm": "provider_call",
    "openai": "provider_call",
    "network": "network",
    "http": "network",
    "execute": "runtime_execution",
    "run tests": "runtime_execution",
    "shell": "runtime_execution",
    "sqlite": "database",
    "database": "database",
    "zip": "archive_output",
    "final_output": "generated_output",
    "project_output": "generated_output",
    "telegram": "legacy_bot",
    "support bot": "legacy_bot",
}


def extract_requirements_contract_only(goal: Any, context: dict[str, Any] | None = None) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    if not isinstance(goal, str) or not goal.strip():
        diagnostics.append(Diagnostic(CGNK_REQUIREMENTS_EXTRACT_INVALID_INPUT, "error", "$.goal", "Goal must be a non-empty string", expected="non-empty string", actual=type(goal).__name__, involved_ref=MODULE_REF))
        return _result(False, "", [], [], [], [], diagnostics)

    normalized_goal = " ".join(goal.strip().split())
    context = context if isinstance(context, dict) else {}
    chunks = _goal_chunks(normalized_goal)
    requirements = [
        {"id": f"req.{index:03d}", "text": chunk, "source": "goal", "priority": "medium"}
        for index, chunk in enumerate(chunks, start=1)
    ]
    constraints = _constraints(normalized_goal, context)
    unsupported = _unsupported(normalized_goal, context)
    assumptions = _assumptions(normalized_goal, context, requirements, constraints)
    if not requirements:
        diagnostics.append(Diagnostic(CGNK_REQUIREMENTS_EXTRACT_INSUFFICIENT_CONTEXT, "warning", "$.goal", "No concrete requirement clauses were extracted", expected="actionable requirement text", actual=normalized_goal, involved_ref=MODULE_REF))
    return _result(not any(d.severity == "error" for d in diagnostics), normalized_goal, requirements, constraints, assumptions, unsupported, diagnostics)


def _result(ok: bool, normalized_goal: str, requirements: list[dict[str, Any]], constraints: list[dict[str, Any]], assumptions: list[str], unsupported_items: list[dict[str, str]], diagnostics: list[Diagnostic]) -> dict[str, Any]:
    artifact = {
        "kind": "Requirements",
        "schema_version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "normalized_goal": normalized_goal,
        "requirements": requirements,
        "constraints": constraints,
        "assumptions": assumptions,
        "unsupported_items": unsupported_items,
    }
    return {"ok": ok, "requirements": artifact, "diagnostics": [d.as_dict() for d in diagnostics]}


def _goal_chunks(goal: str) -> list[str]:
    raw = re.split(r"(?:[.;\n]+|\s+\band\b\s+)", goal)
    chunks = []
    for item in raw:
        chunk = item.strip(" -:")
        if len(chunk) >= 3 and chunk.lower() not in {"and", "the", "it"}:
            chunks.append(chunk)
    return sorted(dict.fromkeys(chunks))


def _constraints(goal: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[str] = []
    lowered = goal.lower()
    for marker in CONSTRAINT_MARKERS:
        if marker in lowered:
            found.append(goal)
            break
    extra = context.get("constraints", [])
    if isinstance(extra, dict):
        extra = [f"{key}: {value}" for key, value in sorted(extra.items())]
    if isinstance(extra, list):
        found.extend(str(item) for item in extra if str(item).strip())
    return [{"id": f"constraint.{index:03d}", "text": text, "source": "goal_or_context"} for index, text in enumerate(sorted(dict.fromkeys(found)), start=1)]


def _unsupported(goal: str, context: dict[str, Any]) -> list[dict[str, str]]:
    haystack = f"{goal} {context}".lower()
    rows = [{"keyword": keyword, "reason": reason} for keyword, reason in sorted(UNSUPPORTED_KEYWORDS.items()) if keyword in haystack]
    return rows


def _assumptions(goal: str, context: dict[str, Any], requirements: list[dict[str, Any]], constraints: list[dict[str, Any]]) -> list[str]:
    assumptions: list[str] = []
    if requirements and not context.get("snapshot"):
        assumptions.append("Project snapshot context may be required before planning file changes.")
    if not constraints:
        assumptions.append("No additional execution, provider, or workspace-write permission is implied.")
    if len(goal.split()) < 4:
        assumptions.append("Goal is terse and may require clarification before implementation planning.")
    return assumptions
