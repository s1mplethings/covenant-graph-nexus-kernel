#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

import requirement_blueprint


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "examples" / "test_results" / "context_prompt_pack.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def clip_text(text: Any, limit: int = 320) -> str:
    value = clean_text(text)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def rough_token_count(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_\u4e00-\u9fff]", text))
    return cjk + latin


def assess_prompt_quality(
    *,
    prompt_text: str,
    budget: dict[str, Any],
    key_points: list[dict[str, Any]],
    required_types: list[str],
) -> dict[str, Any]:
    issues: list[str] = []
    prompt_chars = len(prompt_text)
    max_chars = int(budget.get("max_chars", 0))
    if max_chars and prompt_chars > max_chars:
        issues.append(f"prompt exceeds max_chars: {prompt_chars}>{max_chars}")
    if "CGNK_CONTEXT_PROMPT" not in prompt_text:
        issues.append("prompt marker missing")
    if "Context JSON:" not in prompt_text:
        issues.append("context json marker missing")
    available_types = {
        str(point.get("type", "")).strip()
        for point in key_points
        if isinstance(point, dict) and str(point.get("type", "")).strip()
    }
    missing = [item for item in required_types if item not in available_types]
    if missing:
        issues.append("missing key point types: " + ", ".join(missing))
    return {
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "required_key_types": required_types,
        "preserved_key_types": sorted(available_types),
        "prompt_chars": prompt_chars,
        "max_chars": max_chars,
    }


def source_value(row: Any, default: Any = "") -> Any:
    if isinstance(row, dict) and "value" in row:
        return row.get("value", default)
    return row if row not in (None, "") else default


def source_meta(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return {
            "source_type": row.get("source_type", "unknown"),
            "confidence": row.get("confidence", 0),
        }
    return {"source_type": "unknown", "confidence": 0}


def compact_source(row: Any, default: Any = "") -> dict[str, Any]:
    return {"value": source_value(row, default), **source_meta(row)}


def priority_rank(value: str) -> int:
    return {"Must": 0, "Should": 1, "Could": 2, "Won't": 3}.get(str(value), 9)


def compact_feature(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id", ""),
        "name": row.get("name", ""),
        "priority": row.get("priority", ""),
        "description": clip_text(row.get("description", ""), 240),
        "inputs": row.get("inputs", []),
        "outputs": row.get("outputs", []),
        "source_type": row.get("source_type", "unknown"),
    }


def compact_gap(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "field": row.get("field", ""),
        "status": row.get("status", ""),
        "severity": row.get("severity", ""),
        "question": clip_text(row.get("question", ""), 180),
        "impact": clip_text(row.get("impact", ""), 220),
        "default_assumption": clip_text(row.get("default_assumption", ""), 220),
    }


def compact_tech_decision(row: dict[str, Any]) -> dict[str, Any]:
    selected = row.get("selected", {}) if isinstance(row.get("selected"), dict) else {}
    return {
        "feature_id": row.get("feature_id", ""),
        "capability": row.get("capability", ""),
        "selected": selected.get("name", ""),
        "ecosystem": selected.get("ecosystem", ""),
        "fit_reason": clip_text(selected.get("fit_reason", ""), 200),
        "decision_type": row.get("decision_type", ""),
        "score": row.get("score", ""),
    }


def summarize_blueprint(
    blueprint: dict[str, Any],
    *,
    max_features: int = 10,
    max_gaps: int = 8,
    max_tech_decisions: int = 12,
) -> dict[str, Any]:
    requirement_spec = blueprint.get("requirement_spec", {})
    io_contract = blueprint.get("io_contract", {})
    output_contract = io_contract.get("output_contract", {})
    input_contract = io_contract.get("input_contract", {})
    features = blueprint.get("feature_spec", {}).get("features", [])
    gaps = blueprint.get("gap_analysis", {}).get("gap_items", [])
    tech_decisions = blueprint.get("tech_decisions", {}).get("tech_decisions", [])
    review_report = blueprint.get("review_report", {})

    sorted_features = sorted(
        [row for row in features if isinstance(row, dict)],
        key=lambda row: (priority_rank(str(row.get("priority", ""))), str(row.get("id", ""))),
    )
    open_gaps = [row for row in gaps if isinstance(row, dict) and row.get("status") != "resolved"]
    blocking_gaps = [row for row in open_gaps if str(row.get("severity", "")).lower() in {"level 3", "level3"}]
    blocking_fields = {str(row.get("field", "")) for row in blocking_gaps}
    non_blocking_open_gaps = [row for row in open_gaps if str(row.get("field", "")) not in blocking_fields]

    return {
        "kind": "CompressedRequirementContext",
        "status": blueprint.get("status", "unknown"),
        "raw_requirement": clip_text(blueprint.get("raw_requirement", ""), 1200),
        "requirement": {
            "project_type": compact_source(requirement_spec.get("project_type", {})),
            "domain": compact_source(requirement_spec.get("domain", {})),
            "required_features": compact_source(requirement_spec.get("required_features", {}), []),
            "non_goals": compact_source(requirement_spec.get("non_goals", {}), []),
            "business_goal": compact_source(requirement_spec.get("business_goal", {})),
            "target_users": compact_source(requirement_spec.get("target_users", {}), []),
            "scope_boundary": [
                compact_source(row)
                for row in requirement_spec.get("scope_boundary", [])
                if isinstance(row, dict)
            ][:4],
        },
        "io": {
            "input_types": input_contract.get("input_types", []),
            "required_fields": input_contract.get("required_fields", []),
            "optional_fields": input_contract.get("optional_fields", []),
            "input_unknowns": input_contract.get("unknowns", []),
            "output_types": output_contract.get("output_types", []),
            "output_formats": output_contract.get("output_formats", []),
            "storage": compact_source(output_contract.get("storage", {})),
            "output_unknowns": output_contract.get("unknowns", []),
        },
        "gaps": {
            "blocking": [compact_gap(row) for row in blocking_gaps[:max_gaps]],
            "open": [compact_gap(row) for row in non_blocking_open_gaps[:max_gaps]],
        },
        "features": [compact_feature(row) for row in sorted_features[:max_features]],
        "tech_decisions": [compact_tech_decision(row) for row in tech_decisions[:max_tech_decisions] if isinstance(row, dict)],
        "risk_summary": [clip_text(row, 240) for row in review_report.get("risk_summary", [])],
    }


def extract_key_points(requirement: str, answers: list[dict[str, str]], blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    summary = summarize_blueprint(blueprint)
    points: list[dict[str, Any]] = []
    raw_requirement = clean_text(requirement or blueprint.get("raw_requirement", ""))
    if raw_requirement:
        points.append({"type": "explicit_requirement", "text": clip_text(raw_requirement, 800), "source_type": "explicit", "confidence": 1.0})
    for answer in answers or []:
        field = str(answer.get("field", "")).strip()
        value = str(answer.get("answer", "")).strip()
        if field and value:
            points.append({"type": "explicit_answer", "field": field, "text": clip_text(value, 360), "source_type": "explicit", "confidence": 1.0})
    req = summary["requirement"]
    for key in ("project_type", "business_goal", "target_users"):
        item = req.get(key, {})
        points.append({"type": key, "text": item.get("value"), "source_type": item.get("source_type"), "confidence": item.get("confidence")})
    for key in ("domain", "required_features", "non_goals"):
        item = req.get(key, {})
        points.append({"type": key, "text": item.get("value"), "source_type": item.get("source_type"), "confidence": item.get("confidence")})
    for gap in summary["gaps"]["blocking"] + summary["gaps"]["open"]:
        points.append({"type": "gap", "field": gap["field"], "severity": gap["severity"], "text": gap["question"], "impact": gap["impact"]})
    for feature in summary["features"]:
        points.append({"type": "feature", "id": feature["id"], "priority": feature["priority"], "text": f"{feature['name']}: {feature['description']}"})
    for decision in summary["tech_decisions"]:
        points.append({"type": "tech_decision", "capability": decision["capability"], "text": f"{decision['selected']} for {decision['capability']}"})
    for risk in summary["risk_summary"]:
        points.append({"type": "risk", "text": risk})
    return points


def prompt_instructions(purpose: str) -> str:
    if purpose == "project_generation":
        return (
            "Use the raw explicit user requirement inside the context as the product source of truth. "
            "Treat CGNK blueprint/module/artifact fields as supporting planning evidence, not as the product to build. "
            "Preserve explicit/inferred/assumed provenance, implement only the accepted user-facing scope, "
            "keep open gaps visible as assumptions or risks, and emit project files, generation trace, test graph, "
            "effect report, and runtime result."
        )
    if purpose == "route_planning":
        return (
            "Use the compressed context to choose the smallest complete local route. Prefer deterministic local modules. "
            "Provider/network routes are optional and must remain explicit."
        )
    return "Use the compressed context as the source of truth. Preserve provenance and do not invent missing details."


def serialize_context(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def compact_prompt_context(summary: dict[str, Any]) -> dict[str, Any]:
    req = summary.get("requirement", {})
    io_doc = summary.get("io", {})
    gaps = summary.get("gaps", {})
    return {
        "status": summary.get("status", "unknown"),
        "raw": summary.get("raw_requirement", ""),
        "project_type": req.get("project_type", {}),
        "domain": req.get("domain", {}),
        "required_features": req.get("required_features", {}),
        "non_goals": req.get("non_goals", {}),
        "goal": req.get("business_goal", {}),
        "users": req.get("target_users", {}),
        "scope": req.get("scope_boundary", []),
        "io": {
            "inputs": io_doc.get("input_types", []),
            "required": io_doc.get("required_fields", []),
            "outputs": io_doc.get("output_types", [])[:10],
            "formats": io_doc.get("output_formats", []),
            "unknowns": (io_doc.get("input_unknowns", []) + io_doc.get("output_unknowns", []))[:6],
            "storage": io_doc.get("storage", {}),
        },
        "blocking_gaps": gaps.get("blocking", []),
        "open_gaps": gaps.get("open", []),
        "features": [
            {
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "priority": row.get("priority", ""),
                "description": row.get("description", ""),
                "inputs": row.get("inputs", []),
                "outputs": row.get("outputs", []),
                "source_type": row.get("source_type", "unknown"),
            }
            for row in summary.get("features", [])
        ],
        "tech": summary.get("tech_decisions", []),
        "risks": summary.get("risk_summary", []),
    }


def render_prompt(purpose: str, context: dict[str, Any]) -> str:
    context_json = serialize_context({"purpose": purpose, "context": context})
    return (
        "CGNK_CONTEXT_PROMPT\n"
        f"Purpose: {purpose}\n"
        f"Instructions: {prompt_instructions(purpose)}\n"
        "Context JSON:\n"
        f"{context_json}\n"
    )


def compact_turn(turn: dict[str, Any], limit: int = 220) -> dict[str, Any]:
    return {
        "turn_id": turn.get("turn_id", ""),
        "role": turn.get("role", ""),
        "content": clip_text(turn.get("content", ""), limit),
        "artifact_refs": turn.get("artifact_refs", {}),
    }


def state_key_points(state: dict[str, Any], checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    current_intent = clean_text(state.get("current_intent", ""))
    if current_intent:
        points.append({"type": "current_intent", "text": clip_text(current_intent, 360)})
    for value in state.get("stable_facts", [])[:12]:
        points.append({"type": "stable_fact", "text": clip_text(value, 260)})
    for value in state.get("confirmed_constraints", [])[:10]:
        points.append({"type": "constraint", "text": clip_text(value, 260)})
    for value in state.get("user_preferences", [])[:8]:
        points.append({"type": "preference", "text": clip_text(value, 220)})
    for value in state.get("rejected_options", [])[:8]:
        points.append({"type": "rejected_option", "text": clip_text(value, 220)})
    for value in state.get("open_questions", [])[:8]:
        points.append({"type": "open_question", "text": clip_text(value, 220)})
    if checkpoint:
        points.append(
            {
                "type": "checkpoint",
                "stage": checkpoint.get("stage", ""),
                "status": checkpoint.get("status", ""),
                "completed_steps": checkpoint.get("completed_steps", []),
                "pending_steps": checkpoint.get("pending_steps", []),
            }
        )
    return points


def compact_state_context(
    state: dict[str, Any],
    checkpoint: dict[str, Any],
    *,
    active_module: str,
    flow_ref: str,
    recent_turns: int = 6,
) -> dict[str, Any]:
    return {
        "active_module": active_module,
        "flow_ref": flow_ref,
        "summary": clip_text(state.get("summary", ""), 1600),
        "current_intent": clip_text(state.get("current_intent", ""), 500),
        "stable_facts": [clip_text(value, 260) for value in state.get("stable_facts", [])[:16]],
        "constraints": [clip_text(value, 260) for value in state.get("confirmed_constraints", [])[:12]],
        "preferences": [clip_text(value, 220) for value in state.get("user_preferences", [])[:8]],
        "rejected_options": [clip_text(value, 220) for value in state.get("rejected_options", [])[:8]],
        "open_questions": [clip_text(value, 220) for value in state.get("open_questions", [])[:10]],
        "recent_turns": [compact_turn(turn) for turn in state.get("recent_turns", [])[-recent_turns:]],
        "artifact_refs": state.get("artifact_refs", {}),
        "resume": {
            "checkpoint_id": checkpoint.get("checkpoint_id", ""),
            "stage": checkpoint.get("stage", ""),
            "status": checkpoint.get("status", ""),
            "completed_steps": checkpoint.get("completed_steps", []),
            "pending_steps": checkpoint.get("pending_steps", []),
            "artifact_refs": checkpoint.get("artifact_refs", {}),
            "resume_command": checkpoint.get("resume_command", ""),
            "failure": checkpoint.get("failure"),
        } if checkpoint else {},
    }


def shrink_state_context(context: dict[str, Any], stage: int) -> dict[str, Any]:
    doc = json.loads(json.dumps(context, ensure_ascii=False))
    if stage >= 1:
        doc["summary"] = clip_text(doc.get("summary", ""), 900)
        doc["stable_facts"] = doc.get("stable_facts", [])[:10]
        doc["constraints"] = doc.get("constraints", [])[:8]
        doc["open_questions"] = doc.get("open_questions", [])[:6]
        doc["recent_turns"] = doc.get("recent_turns", [])[-4:]
    if stage >= 2:
        doc["summary"] = clip_text(doc.get("summary", ""), 520)
        doc["preferences"] = doc.get("preferences", [])[:4]
        doc["rejected_options"] = doc.get("rejected_options", [])[:4]
        for turn in doc.get("recent_turns", []):
            turn["content"] = clip_text(turn.get("content", ""), 140)
    if stage >= 3:
        doc["recent_turns"] = doc.get("recent_turns", [])[-2:]
        doc.get("resume", {}).pop("artifact_refs", None)
        doc.get("resume", {}).pop("failure", None)
    if stage >= 4:
        doc.pop("preferences", None)
        doc.pop("rejected_options", None)
        doc["stable_facts"] = doc.get("stable_facts", [])[:6]
        doc["constraints"] = doc.get("constraints", [])[:5]
        doc["open_questions"] = doc.get("open_questions", [])[:3]
        doc["artifact_refs"] = {key: doc.get("artifact_refs", {})[key] for key in list(doc.get("artifact_refs", {}))[:8]}
    if stage >= 5:
        doc["summary"] = clip_text(doc.get("summary", ""), 240)
        doc["current_intent"] = clip_text(doc.get("current_intent", ""), 240)
        doc.pop("recent_turns", None)
    return doc


def build_state_prompt_pack(
    state: dict[str, Any],
    checkpoint: dict[str, Any] | None = None,
    *,
    active_module: str,
    flow_ref: str,
    purpose: str = "general",
    max_chars: int = 6000,
    recent_turns: int = 6,
) -> dict[str, Any]:
    checkpoint_doc = checkpoint or {}
    key_points = state_key_points(state, checkpoint_doc)
    base_context = compact_state_context(
        state,
        checkpoint_doc,
        active_module=active_module,
        flow_ref=flow_ref,
        recent_turns=recent_turns,
    )
    prompt_context = base_context
    prompt_text = render_prompt(purpose, prompt_context)
    shrink_stage = 0
    if len(prompt_text) > max_chars:
        for stage in range(1, 6):
            shrink_stage = stage
            prompt_context = shrink_state_context(base_context, stage)
            prompt_text = render_prompt(purpose, prompt_context)
            if len(prompt_text) <= max_chars:
                break
    if len(prompt_text) > max_chars:
        shrink_stage = 6
        minimal_context = {
            "active_module": active_module,
            "flow_ref": flow_ref,
            "current_intent": clip_text(base_context.get("current_intent", ""), 180),
            "stable_facts": base_context.get("stable_facts", [])[:3],
            "constraints": base_context.get("constraints", [])[:3],
            "open_questions": base_context.get("open_questions", [])[:2],
            "resume": {
                "stage": base_context.get("resume", {}).get("stage", ""),
                "status": base_context.get("resume", {}).get("status", ""),
                "pending_steps": base_context.get("resume", {}).get("pending_steps", [])[:3],
            },
        }
        prompt_text = render_prompt(purpose, minimal_context)
    if len(prompt_text) > max_chars:
        shrink_stage = 7
        minimal_context = {
            "active_module": active_module,
            "current_intent": clip_text(base_context.get("current_intent", ""), 120),
            "constraints": [clip_text(value, 120) for value in base_context.get("constraints", [])[:2]],
        }
        prompt_text = render_prompt(purpose, minimal_context)
    budget = {
        "max_chars": max_chars,
        "prompt_chars": len(prompt_text),
        "rough_tokens": rough_token_count(prompt_text),
        "shrink_stage": shrink_stage,
    }
    required_types = ["current_intent"]
    if checkpoint_doc:
        required_types.append("checkpoint")
    if base_context.get("constraints"):
        required_types.append("constraint")
    return {
        "kind": "ContextPromptPack",
        "created_at": now(),
        "purpose": purpose,
        "budget": budget,
        "quality": assess_prompt_quality(
            prompt_text=prompt_text,
            budget=budget,
            key_points=key_points,
            required_types=required_types,
        ),
        "compressed_context": base_context,
        "key_points": key_points,
        "prompt_text": prompt_text,
    }


def shrink_prompt_context(context: dict[str, Any], stage: int) -> dict[str, Any]:
    doc = json.loads(json.dumps(context, ensure_ascii=False))
    if stage >= 1:
        for feature in doc.get("features", []):
            feature["description"] = clip_text(feature.get("description", ""), 120)
        for gap in doc.get("blocking_gaps", []) + doc.get("open_gaps", []):
            gap["impact"] = clip_text(gap.get("impact", ""), 120)
            gap["default_assumption"] = clip_text(gap.get("default_assumption", ""), 120)
        for tech in doc.get("tech", []):
            tech["fit_reason"] = clip_text(tech.get("fit_reason", ""), 90)
    if stage >= 2:
        doc.pop("scope", None)
        doc.get("io", {}).pop("storage", None)
        doc["risks"] = doc.get("risks", [])[:1]
    if stage >= 3:
        doc.get("io", {}).pop("unknowns", None)
        for tech in doc.get("tech", []):
            tech.pop("fit_reason", None)
            tech.pop("score", None)
        for gap in doc.get("blocking_gaps", []) + doc.get("open_gaps", []):
            gap.pop("default_assumption", None)
    if stage >= 4:
        for feature in doc.get("features", []):
            feature.pop("description", None)
            feature.pop("inputs", None)
            feature.pop("source_type", None)
        for gap in doc.get("blocking_gaps", []) + doc.get("open_gaps", []):
            gap.pop("impact", None)
        doc.pop("risks", None)
    if stage >= 5:
        doc["raw"] = clip_text(doc.get("raw", ""), 240)
        doc["features"] = doc.get("features", [])[:2]
        doc["tech"] = doc.get("tech", [])[:2]
        doc["open_gaps"] = doc.get("open_gaps", [])[:1]
    return doc


def build_prompt_pack(
    requirement: str,
    answers: list[dict[str, str]],
    blueprint: dict[str, Any],
    *,
    purpose: str = "project_generation",
    max_chars: int = 6000,
) -> dict[str, Any]:
    feature_limit = 12
    gap_limit = 8
    tech_limit = 12
    summary = summarize_blueprint(blueprint, max_features=feature_limit, max_gaps=gap_limit, max_tech_decisions=tech_limit)
    key_points = extract_key_points(requirement, answers, blueprint)

    while True:
        prompt_context = compact_prompt_context(summary)
        prompt_text = render_prompt(purpose, prompt_context)
        if len(prompt_text) <= max_chars or (feature_limit <= 2 and gap_limit <= 2 and tech_limit <= 2):
            break
        feature_limit = max(2, feature_limit - 2)
        gap_limit = max(2, gap_limit - 1)
        tech_limit = max(2, tech_limit - 2)
        summary = summarize_blueprint(blueprint, max_features=feature_limit, max_gaps=gap_limit, max_tech_decisions=tech_limit)
        key_points = extract_key_points(requirement, answers, blueprint)

    if len(prompt_text) > max_chars:
        base_context = compact_prompt_context(summary)
        for stage in range(1, 6):
            prompt_context = shrink_prompt_context(base_context, stage)
            prompt_text = render_prompt(purpose, prompt_context)
            if len(prompt_text) <= max_chars:
                break
        if len(prompt_text) > max_chars:
            prompt_context = shrink_prompt_context(base_context, 5)
            prompt_context["raw"] = clip_text(prompt_context.get("raw", ""), 120)
            prompt_context["io"] = {
                "inputs": prompt_context.get("io", {}).get("inputs", []),
                "outputs": prompt_context.get("io", {}).get("outputs", [])[:6],
            }
            prompt_text = render_prompt(purpose, prompt_context)
    budget = {
        "max_chars": max_chars,
        "prompt_chars": len(prompt_text),
        "rough_tokens": rough_token_count(prompt_text),
        "feature_limit": feature_limit,
        "gap_limit": gap_limit,
        "tech_decision_limit": tech_limit,
    }

    return {
        "kind": "ContextPromptPack",
        "created_at": now(),
        "purpose": purpose,
        "budget": budget,
        "quality": assess_prompt_quality(
            prompt_text=prompt_text,
            budget=budget,
            key_points=key_points,
            required_types=["explicit_requirement", "project_type", "business_goal"],
        ),
        "compressed_context": summary,
        "key_points": key_points,
        "prompt_text": prompt_text,
    }


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_blueprint(path: str, requirement: str, answers: list[dict[str, str]], assume_defaults: bool) -> dict[str, Any]:
    if path:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return requirement_blueprint.build_requirement_blueprint(requirement, answers, assume_defaults=assume_defaults)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement", required=True)
    parser.add_argument("--answers-json", default="[]")
    parser.add_argument("--blueprint-json", default="")
    parser.add_argument("--purpose", default="project_generation", choices=["project_generation", "route_planning", "general"])
    parser.add_argument("--max-chars", type=int, default=6000)
    parser.add_argument("--assume-defaults", action="store_true")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    answers = json.loads(args.answers_json)
    blueprint = load_blueprint(args.blueprint_json, args.requirement, answers, args.assume_defaults)
    pack = build_prompt_pack(args.requirement, answers, blueprint, purpose=args.purpose, max_chars=args.max_chars)
    out_path = pathlib.Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    write_json(out_path, pack)
    if args.json:
        print(json.dumps(pack, ensure_ascii=False, indent=2))
    else:
        print(f"CONTEXT_PROMPT_PACK: {str(pack['quality']['status']).upper()} chars={pack['budget']['prompt_chars']} rough_tokens={pack['budget']['rough_tokens']}")
        print(f"out={out_path}")
        for issue in pack["quality"].get("issues", []):
            print(f"issue={issue}")
    return 0 if pack["quality"].get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
