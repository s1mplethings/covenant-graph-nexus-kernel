from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts import product_design_depth_governance as contract

SCHEMA_PATH = ROOT / "contracts" / contract.SCHEMA_FILE
HASH_FIELDS = ("contract_hash", "artifact_hash")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_hash(document: dict[str, Any], field: str) -> str:
    payload = dict(document)
    payload[field] = ""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _seal(document: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(document)
    result[field] = ""
    result[field] = _json_hash(result, field)
    return result


def write_json(path: pathlib.Path, document: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def validate_artifact(document: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        import jsonschema

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(document)
    except Exception as exc:
        errors.append(f"schema:{type(exc).__name__}:{exc}")
    hash_field = "contract_hash" if "contract_hash" in document else "artifact_hash"
    if document.get(hash_field) != _json_hash(document, hash_field):
        errors.append(f"{hash_field}_mismatch")
    return {"status": "PASS" if not errors else "NEEDS_REWORK", "errors": errors}


def _combined_text(raw_goal: str, goal_spec: dict[str, Any], project_plan: dict[str, Any]) -> str:
    return "\n".join(
        [
            raw_goal,
            json.dumps(goal_spec, ensure_ascii=False),
            json.dumps(project_plan, ensure_ascii=False),
        ]
    ).lower()


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _signals(raw_goal: str, goal_spec: dict[str, Any], project_plan: dict[str, Any]) -> dict[str, Any]:
    text = _combined_text(raw_goal, goal_spec, project_plan)
    capabilities = goal_spec.get("capabilities", []) if isinstance(goal_spec.get("capabilities"), list) else []
    flows = goal_spec.get("user_flows", []) if isinstance(goal_spec.get("user_flows"), list) else []
    workstreams = project_plan.get("workstreams", []) if isinstance(project_plan.get("workstreams"), list) else []
    identity = _contains(text, ("人物身份", "同一人物", "角色识别", "identity recognition", "identity match", "face recognition", "person re-identification"))
    video = _contains(text, ("视频", "剧集", "电视剧", "video", "episode", "clip"))
    semantic_recognition = identity or _contains(text, ("识别", "检测", "recognition", "classification", "matching"))
    csv_tool = _contains(text, ("csv", "表格清洗", "数据清洗"))
    calculator = _contains(text, ("计算器", "calculator")) and not _contains(text, ("历史记录", "云", "database", "协作"))
    destructive = _contains(text, ("删除原始", "覆盖原始", "不可逆", "数据丢失", "erase", "overwrite source", "irreversible", "data loss"))
    background = _contains(text, ("后台", "长任务", "暂停", "恢复", "队列", "background job", "long-running", "concurrency"))
    persistence = _contains(text, ("持久化", "重启", "保存", "数据库", "state", "persist", "resume"))
    privacy = _contains(text, ("隐私", "本地", "不能上传", "敏感", "privacy", "local-only", "personal data"))
    external_tools = _contains(text, ("ffmpeg", "模型", "onnx", "gpu", "外部工具", "external tool")) or video
    export = _contains(text, ("导出", "输出文件", "export", "render"))
    ui = len(flows) >= 3 or _contains(text, ("界面", "窗口", "人工复核", "gui", "review"))
    return {
        "text": text,
        "capability_count": len(capabilities),
        "flow_count": len(flows),
        "workstream_count": len(workstreams),
        "identity": identity,
        "video": video,
        "semantic_recognition": semantic_recognition,
        "csv_tool": csv_tool,
        "calculator": calculator,
        "destructive": destructive,
        "background": background,
        "persistence": persistence,
        "privacy": privacy,
        "external_tools": external_tools,
        "export": export,
        "ui": ui,
        "real_world_variability": identity or (video and semantic_recognition),
    }


def _dimension(level: int, reason: str) -> dict[str, Any]:
    return {"score": max(0, min(3, int(level))), "reason": reason}


def build_complexity_profile(
    raw_goal: str,
    goal_spec: dict[str, Any],
    project_plan: dict[str, Any],
    *,
    frozen_at: str,
) -> dict[str, Any]:
    signal = _signals(raw_goal, goal_spec, project_plan)
    dimensions = {
        "domain_complexity": _dimension(0 if signal["calculator"] else (1 if signal["csv_tool"] else min(3, 1 + signal["capability_count"] // 4)), "semantic domain and capability breadth"),
        "algorithmic_uncertainty": _dimension(3 if signal["identity"] else (2 if signal["semantic_recognition"] else 0), "uncertainty of the core transformation or recognition algorithm"),
        "data_dependency": _dimension(2 if signal["video"] else (1 if signal["csv_tool"] else 0), "dependence on representative user data"),
        "external_tool_dependency": _dimension(2 if signal["external_tools"] else 0, "runtime dependency on local tools or models"),
        "UI_workflow_complexity": _dimension(2 if signal["ui"] else 0, "number of user-visible states and review actions"),
        "persistence_requirements": _dimension(2 if signal["persistence"] else (1 if signal["csv_tool"] else 0), "durable state and restart requirements"),
        "concurrency_or_background_work": _dimension(2 if signal["background"] or signal["video"] else 0, "long-running or background work"),
        "performance_risk": _dimension(2 if signal["video"] else 0, "input-scale-sensitive processing"),
        "platform_risk": _dimension(2 if signal["external_tools"] else 0, "platform and dependency variability"),
        "privacy_or_security_risk": _dimension(2 if signal["privacy"] else 0, "privacy, local-only, or sensitive-data constraints"),
        "packaging_complexity": _dimension(1 if signal["external_tools"] or signal["export"] else 0, "runtime and export packaging"),
        "real_world_variability": _dimension(3 if signal["real_world_variability"] else (1 if signal["csv_tool"] else 0), "variation not controlled by the implementation"),
        "failure_cost": _dimension(3 if signal["destructive"] else (1 if signal["csv_tool"] else 0), "user impact of incorrect or destructive behavior"),
        "core_capability_uncertainty": _dimension(3 if signal["identity"] else (2 if signal["semantic_recognition"] else 0), "confidence that the core outcome can be achieved"),
    }
    score = sum(item["score"] for item in dimensions.values())
    if signal["destructive"]:
        level = "HIGH_RISK"
    elif signal["identity"] and signal["video"]:
        level = "COMPLEX"
    elif signal["calculator"] and score <= 6:
        level = "SIMPLE"
    elif score <= 8:
        level = "SIMPLE"
    elif score <= 18:
        level = "STANDARD"
    elif score <= 31:
        level = "COMPLEX"
    else:
        level = "HIGH_RISK"
    depth = {
        "SIMPLE": ("one direct design with observable behavior", "direct behavior tests", ["builder"]),
        "STANDARD": ("primary design, core flow, risks, and failure path", "real behavior plus negative controls", ["builder", "quality_reviewer"]),
        "COMPLEX": ("two viable alternatives, tradeoffs, data/state/long-task/performance/dependency/failure design", "variation, negative controls, adversarial cases, and independent holdout", ["builder", "independent_product_challenger", "evidence_verifier"]),
        "HIGH_RISK": ("COMPLEX depth plus recovery, safety, security, rollback, and failure-cost controls", "representative holdout, destructive-safety and recovery evidence", ["builder", "independent_product_challenger", "safety_reviewer", "evidence_verifier"]),
    }[level]
    reasons = [f"{name}:{item['score']} {item['reason']}" for name, item in dimensions.items() if item["score"]]
    if signal["identity"] and signal["video"]:
        reasons.insert(0, "Real-person identity matching in variable video is a core semantic difficulty, independent of request length.")
    return _seal(
        {
            "kind": "CGKNProjectComplexityProfile",
            "schema_version": contract.SCHEMA_VERSION,
            **dimensions,
            "complexity_score": score,
            "complexity_level": level,
            "classification_reasons": reasons,
            "required_design_depth": depth[0],
            "required_test_depth": depth[1],
            "required_review_roles": depth[2],
            "required_real_world_evidence": level in {"COMPLEX", "HIGH_RISK"} or bool(signal["real_world_variability"]),
            "prohibited_shortcuts": [
                "replace a core semantic capability with an easier proxy while preserving the product claim",
                "use builder-generated synthetic evidence as the only target-validation authority",
                "add architecture or future features without a requirement or measured risk",
            ],
            "classification_inputs": {
                "structured_capability_count": signal["capability_count"],
                "structured_user_flow_count": signal["flow_count"],
                "structured_workstream_count": signal["workstream_count"],
                "semantic_risk_flags": {key: value for key, value in signal.items() if isinstance(value, bool)},
            },
            "contract_frozen_at": frozen_at,
            "contract_hash": "",
        },
        "contract_hash",
    )


def _core_capabilities(raw_goal: str, goal_spec: dict[str, Any], signal: dict[str, Any]) -> list[dict[str, Any]]:
    if signal["identity"] and signal["video"]:
        return [{"capability_id": "real_person_identity_matching", "description": "Match the same real person from reference information across variable video frames", "non_negotiable": True}]
    declared = [str(item).strip() for item in goal_spec.get("capabilities", []) if str(item).strip()]
    if signal["csv_tool"]:
        return [{"capability_id": "faithful_csv_transformation", "description": "Transform user CSV data according to explicit cleaning rules without corrupting the source", "non_negotiable": True}]
    if signal["calculator"]:
        return [{"capability_id": "correct_calculation", "description": "Evaluate supported calculations correctly", "non_negotiable": True}]
    return [
        {
            "capability_id": re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_") or f"core_capability_{index}",
            "description": item,
            "non_negotiable": True,
        }
        for index, item in enumerate(declared[:4], 1)
    ] or [{"capability_id": "declared_core_outcome", "description": raw_goal.strip(), "non_negotiable": True}]


def build_goal_fidelity_contract(
    raw_goal: str,
    goal_spec: dict[str, Any],
    complexity: dict[str, Any],
    *,
    frozen_at: str,
) -> dict[str, Any]:
    signal = _signals(raw_goal, goal_spec, {})
    core = _core_capabilities(raw_goal, goal_spec, signal)
    identity = signal["identity"] and signal["video"]
    allowed = ["defer polish and non-core integrations", "bound input size and platform support while preserving the core outcome"]
    forbidden = ["hard-coded outputs or test file names", "tests tailored only to implementation-specific fixtures"]
    risks = ["implementation and test author can optimize for the same easy evidence"]
    if identity:
        allowed.extend(["defer back-view and long-occlusion recovery", "defer voice identification", "require human review for uncertain candidate boundaries"])
        forbidden.extend(["use clothing or dominant color as person identity", "use background color, fixed timestamps, or fixture names as identity", "claim real-person success from synthetic color characters only"])
        risks.extend(["appearance heuristic can correlate with a synthetic role without identifying a person", "human review can hide failure of the automatic core capability"])
    if signal["destructive"]:
        allowed.extend(["require an explicit dry run before committing destructive changes", "limit the first version to inputs with verified backup and recovery"])
        forbidden.extend(["irreversibly overwrite or delete the only source copy without verified recovery", "treat a successful transformation as proof that rollback works"])
        risks.extend(["partial failure can corrupt or delete user data", "a nominal success path does not demonstrate interruption recovery"])
    return _seal(
        {
            "kind": "CGKNGoalFidelityContract",
            "schema_version": contract.SCHEMA_VERSION,
            "original_user_goal": raw_goal.strip(),
            "intended_user": list(goal_spec.get("target_users", [])) or ["the user described by the original request"],
            "real_world_success_scenario": "A representative user supplies real input not designed around the implementation, completes the core workflow, and receives the intended usable result.",
            "core_user_outcome": raw_goal.strip(),
            "core_capabilities": core,
            "core_difficulties": [item["capability_id"] for item in core if complexity["complexity_level"] != "SIMPLE"],
            "non_negotiable_capabilities": [item["capability_id"] for item in core if item["non_negotiable"]],
            "allowed_scope_reductions": allowed,
            "forbidden_simplifications": forbidden,
            "proxy_or_heuristic_risks": risks,
            "real_world_evidence_required": bool(complexity["required_real_world_evidence"]),
            "acceptance_authority": "independent_product_challenge_review_plus_canonical_product_maturity_evaluator",
            "change_policy": "frozen before implementation; only an explicit replan decision may replace this contract",
            "contract_frozen_at": frozen_at,
            "contract_hash": "",
        },
        "contract_hash",
    )


def build_core_difficulty_lock(
    fidelity: dict[str, Any],
    complexity: dict[str, Any],
    signal: dict[str, Any],
    *,
    frozen_at: str,
) -> dict[str, Any]:
    difficulties: list[dict[str, Any]] = []
    for capability in fidelity["core_capabilities"]:
        capability_id = capability["capability_id"]
        if complexity["complexity_level"] == "SIMPLE":
            continue
        identity = capability_id == "real_person_identity_matching"
        difficulties.append(
            {
                "difficulty_id": f"difficulty:{capability_id}",
                "description": capability["description"],
                "why_it_is_core": "Removing or replacing it would leave a runnable artifact that does not deliver the original user outcome.",
                "evidence_needed_to_claim_success": [
                    "observable core behavior",
                    "challenge cases that can break the simplest proxy",
                    "independent holdout evidence" if complexity["complexity_level"] in {"COMPLEX", "HIGH_RISK"} else "real behavior evidence",
                ],
                "invalid_proxy_solutions": fidelity["forbidden_simplifications"],
                "minimum_realistic_scenario": "same real person under changed clothing, angle, scale, lighting and multi-person scenes" if identity else "representative user input plus a negative control",
                "current_solution_strategy": "local face detection, identity embeddings and temporal track aggregation; appearance cues may rank but cannot define identity" if identity else "direct domain transformation with observable validation and failure handling",
                "unresolved_risks": ["representative data coverage", "false positive and false negative behavior"],
                "status": "LOCKED",
            }
        )
    if complexity["complexity_level"] != "SIMPLE" and not difficulties:
        difficulties.append(
            {
                "difficulty_id": "difficulty:declared_core_outcome",
                "description": fidelity["core_user_outcome"],
                "why_it_is_core": "The project has no valid target outcome without this behavior.",
                "evidence_needed_to_claim_success": ["representative real behavior evidence"],
                "invalid_proxy_solutions": fidelity["forbidden_simplifications"],
                "minimum_realistic_scenario": "representative input and a negative control",
                "current_solution_strategy": "direct implementation aligned to the frozen goal",
                "unresolved_risks": ["core outcome uncertainty"],
                "status": "LOCKED",
            }
        )
    return _seal(
        {
            "kind": "CGKNCoreDifficultyLock",
            "schema_version": contract.SCHEMA_VERSION,
            "complexity_level": complexity["complexity_level"],
            "difficulties": difficulties,
            "replan_required_if_proxy_remains": True,
            "contract_frozen_at": frozen_at,
            "contract_hash": "",
        },
        "contract_hash",
    )


def _challenge_rows(signal: dict[str, Any], level: str) -> list[dict[str, Any]]:
    if signal["destructive"]:
        values = [
            ("source_backup_preserved", "原始数据备份可验证", "prevent irreversible source loss", "negative_control"),
            ("interrupted_write_atomicity", "写入中断后数据保持一致", "break success-path-only implementations", "adversarial"),
            ("rollback_recovery", "提交后按恢复点回滚", "prove recovery rather than transformation only", "real_world_variation"),
            ("independent_recovery_holdout", "独立数据集恢复留出验证", "prevent fixture-specific recovery", "holdout"),
        ]
    elif signal["identity"] and signal["video"]:
        values = [
            ("same_person_different_clothing", "同一人物不同服装", "break clothing/color identity proxies", "real_world_variation"),
            ("different_person_same_color", "不同人物相同服装颜色", "break dominant-color identity proxies", "adversarial"),
            ("multi_person_frame", "多人同框", "measure identity confusion", "adversarial"),
            ("lighting_angle_scale", "光照、角度和尺寸变化", "measure real-world invariance", "variation"),
            ("target_absent", "无目标人物", "measure false positives", "negative_control"),
            ("nonidentical_reference_frame", "参考图与测试视频不是同一帧", "prevent exact-frame matching", "holdout"),
        ]
    elif signal["csv_tool"]:
        values = [
            ("encoding_and_delimiter", "不同编码和分隔符", "verify parser boundaries", "variation"),
            ("malformed_row", "损坏行", "verify explainable failure", "adversarial"),
            ("source_unchanged", "源文件保持不变", "prevent destructive overwrite", "negative_control"),
            ("independent_csv", "独立 CSV holdout", "prevent fixture-specific cleaning", "holdout"),
        ]
    elif signal["calculator"]:
        values = [
            ("supported_operations", "支持的运算", "verify direct correctness", "baseline"),
            ("invalid_expression", "非法表达式", "verify failure behavior", "negative_control"),
        ]
    else:
        values = [
            ("representative_input", "代表性输入", "verify the intended outcome", "real_world_variation"),
            ("negative_control", "负对照", "measure false success", "negative_control"),
        ]
        if level in {"COMPLEX", "HIGH_RISK"}:
            values.append(("independent_holdout", "独立留出输入", "prevent implementation-tailored acceptance", "holdout"))
    return [
        {"challenge_id": item[0], "scenario": item[1], "proxy_defeated": item[2], "resource_type": item[3], "required": True}
        for item in values
    ]


def build_test_realism_and_challenges(
    signal: dict[str, Any],
    complexity: dict[str, Any],
    *,
    frozen_at: str,
    frozen_resource_hashes: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    level = complexity["complexity_level"]
    challenges = _challenge_rows(signal, level)
    realism = _seal(
        {
            "kind": "CGKNTestRealismContract",
            "schema_version": contract.SCHEMA_VERSION,
            "required_resource_types": sorted({row["resource_type"] for row in challenges}),
            "synthetic_resources_allowed": True,
            "synthetic_only_acceptance_allowed": level == "SIMPLE" and not signal["real_world_variability"],
            "real_world_resources_required": bool(complexity["required_real_world_evidence"]),
            "domain_variations": [row["challenge_id"] for row in challenges if row["resource_type"] in {"variation", "real_world_variation"}],
            "adversarial_cases": [row["challenge_id"] for row in challenges if row["resource_type"] == "adversarial"],
            "negative_controls": [row["challenge_id"] for row in challenges if row["resource_type"] == "negative_control"],
            "holdout_required": level in {"COMPLEX", "HIGH_RISK"},
            "holdout_independence_rule": "builder and repair agents receive only pass/fail evidence, not holdout ground-truth details",
            "ground_truth_source": "independent reviewer, licensed dataset annotation, or pre-implementation frozen user-provided truth",
            "acceptance_metrics": ["core capability outcome", "false-positive control", "false-negative control", "challenge coverage"],
            "frozen_resource_hashes": sorted(set(str(item) for item in (frozen_resource_hashes or []) if str(item).startswith("sha256:"))),
            "resource_freeze_policy": "challenge requirements freeze now; concrete hashes must be frozen before main implementation and independently bound before target validation",
            "contract_frozen_at": frozen_at,
            "contract_hash": "",
        },
        "contract_hash",
    )
    matrix = _seal(
        {
            "kind": "CGKNChallengeMatrix",
            "schema_version": contract.SCHEMA_VERSION,
            "domain": "real_person_video_identity" if signal["identity"] and signal["video"] else ("csv_cleaning" if signal["csv_tool"] else ("calculator" if signal["calculator"] else "goal_derived")),
            "challenges": challenges,
            "generated_from_domain_and_risk_analysis": True,
            "contract_frozen_at": frozen_at,
            "contract_hash": "",
        },
        "contract_hash",
    )
    return realism, matrix


def build_design_adequacy(
    complexity: dict[str, Any],
    difficulty_lock: dict[str, Any],
    signal: dict[str, Any],
    project_plan: dict[str, Any],
) -> dict[str, Any]:
    level = complexity["complexity_level"]
    if signal["identity"] and signal["video"]:
        alternatives = [
            {"id": "face_embedding_tracking", "approach": "local face detection + identity embeddings + temporal track aggregation", "strength": "identity-aligned and CPU/GPU deployable", "cost": "model dependency and profile/occlusion limits"},
            {"id": "person_reid_multicue", "approach": "local person re-identification with face/appearance/motion fusion", "strength": "covers non-frontal scenes", "cost": "higher data, compute and calibration risk"},
        ]
        selected = "face_embedding_tracking with explicit uncertain/manual-review path; color is never identity authority"
    elif level in {"COMPLEX", "HIGH_RISK"}:
        alternatives = [
            {"id": "modular_single_process", "approach": "bounded modular local pipeline", "strength": "simple deployment", "cost": "limited isolation"},
            {"id": "isolated_worker", "approach": "persistent controller with isolated background worker", "strength": "failure isolation and resume", "cost": "more operational complexity"},
        ]
        selected = "the smallest alternative that satisfies the locked core difficulty and recovery risk"
    else:
        alternatives = [{"id": "direct_solution", "approach": "single direct implementation", "strength": "proportionate and testable", "cost": "no speculative extensibility"}]
        selected = "direct_solution"
    required_alternatives = 2 if level in {"COMPLEX", "HIGH_RISK"} else 1
    adequate = len(alternatives) >= required_alternatives and (level == "SIMPLE" or bool(difficulty_lock["difficulties"]))
    return _seal(
        {
            "kind": "CGKNDesignAdequacyReport",
            "schema_version": contract.SCHEMA_VERSION,
            "complexity_level": level,
            "technical_alternatives": alternatives,
            "tradeoffs": [f"{row['id']}: {row['strength']} versus {row['cost']}" for row in alternatives],
            "selected_strategy": selected,
            "selection_reason": "preserves the locked core capability with the least unjustified complexity",
            "core_data_flow": "user input -> validated local representation -> core capability -> reviewable result -> durable export",
            "state_and_persistence": "atomic state writes and restart-safe ownership only when the goal requires state",
            "long_task_control": (
                "progress, cancel/pause, resumable checkpoints, recovery/rollback and per-input failure isolation for long-running work"
                if level == "HIGH_RISK"
                else (
                    "progress, cancel/pause, resumable checkpoints and per-input failure isolation for long-running work"
                    if level == "COMPLEX"
                    else "not imposed unless execution duration requires it"
                )
            ),
            "performance_budget": "measure representative input latency and memory; provide CPU baseline and bounded concurrency" if level in {"COMPLEX", "HIGH_RISK"} else "complete direct user action without unnecessary background infrastructure",
            "dependencies_and_licenses": "record every required runtime/model, version, local availability and license before target validation",
            "platform_degradation": "CPU/local fallback must preserve honest capability claims; unavailable target models lower maturity rather than silently switching semantics",
            "failure_modes": ["invalid input", "dependency unavailable", "partial processing", "false positive", "false negative", "restart during work"],
            "test_resource_strategy": "freeze challenge requirements before implementation; synthetic data proves plumbing only when real-world semantics are required",
            "proxy_upgrade_boundary": "replace the proxy at the locked core capability and pass independent real-world challenge holdout; UI/export components may be reused",
            "required_alternatives": required_alternatives,
            "adequate": adequate,
            "artifact_hash": "",
        },
        "artifact_hash",
    )


def build_overengineering_check(
    complexity: dict[str, Any],
    signal: dict[str, Any],
    project_plan: dict[str, Any],
    proposed_components: list[str] | None = None,
) -> dict[str, Any]:
    components = [str(item) for item in (proposed_components or [])]
    if not components:
        components = [
            str(item.get("id") or item.get("workstream_id") or item)
            if isinstance(item, dict)
            else str(item)
            for item in project_plan.get("workstreams", [])
            if isinstance(item, (dict, str))
        ]
    lowered = " ".join(components).lower()
    unnecessary: list[str] = []
    if complexity["complexity_level"] == "SIMPLE":
        for token in ("microservice", "kubernetes", "message queue", "machine learning", "distributed database"):
            if token in lowered:
                unnecessary.append(token)
    if signal["csv_tool"]:
        for token in ("machine learning", "kubernetes", "message queue", "distributed database"):
            if token in lowered:
                unnecessary.append(token)
    return _seal(
        {
            "kind": "CGKNOverengineeringCheck",
            "schema_version": contract.SCHEMA_VERSION,
            "unnecessary_components": sorted(set(unnecessary)),
            "unsupported_future_features": [],
            "complexity_without_requirement": sorted(set(unnecessary)),
            "simpler_valid_solution_available": bool(unnecessary),
            "verdict": "REPLAN_SIMPLER" if unnecessary else "PROPORTIONATE",
            "principle": "component count and document length are not design-depth measures",
            "artifact_hash": "",
        },
        "artifact_hash",
    )


def build_product_challenge_review(
    fidelity: dict[str, Any],
    complexity: dict[str, Any],
    difficulty_lock: dict[str, Any],
    realism: dict[str, Any],
    matrix: dict[str, Any],
    adequacy: dict[str, Any],
    overengineering: dict[str, Any],
    *,
    declared_proxy: bool = False,
) -> dict[str, Any]:
    if declared_proxy:
        verdict = "DESIGN_READY_WITH_DECLARED_PROXY"
        ceiling = "PROTOTYPE"
    elif not adequacy["adequate"] or (complexity["complexity_level"] != "SIMPLE" and not difficulty_lock["difficulties"]):
        verdict = "REPLAN_CORE_CAPABILITY"
        ceiling = "DEMO"
    elif overengineering["verdict"] != "PROPORTIONATE":
        verdict = "REPLAN_CORE_CAPABILITY"
        ceiling = "PROTOTYPE"
    elif realism["holdout_required"] and not any(row["resource_type"] == "holdout" for row in matrix["challenges"]):
        verdict = "BLOCKED_MISSING_EVIDENCE"
        ceiling = "PROTOTYPE"
    else:
        verdict = "DESIGN_READY"
        ceiling = "PRODUCTION_READY"
    return _seal(
        {
            "kind": "CGKNProductChallengeReview",
            "schema_version": contract.SCHEMA_VERSION,
            "review_role": "independent_product_challenger",
            "builder_independent": True,
            "original_goal_hash": "sha256:" + hashlib.sha256(fidelity["original_user_goal"].encode("utf-8")).hexdigest(),
            "counterexamples": [row["scenario"] for row in matrix["challenges"] if row["resource_type"] in {"adversarial", "negative_control", "holdout"}],
            "core_capability_findings": ["core difficulty remains present in the selected strategy" if difficulty_lock["difficulties"] else "simple direct capability needs no artificial difficulty lock"],
            "test_realism_findings": ["synthetic evidence is developmental, not target-validation evidence"] if not realism["synthetic_only_acceptance_allowed"] else ["direct generated cases are proportionate for this simple deterministic goal"],
            "architecture_findings": ["design depth matches risk" if adequacy["adequate"] else "design does not yet cover required risk"],
            "verdict": verdict,
            "maturity_ceiling": ceiling,
            "implementation_entry_allowed": verdict in {"DESIGN_READY", "DESIGN_READY_WITH_DECLARED_PROXY"},
            "artifact_hash": "",
        },
        "artifact_hash",
    )


def freeze_preimplementation_governance(
    raw_goal: str,
    goal_spec: dict[str, Any],
    project_plan: dict[str, Any],
    output_dir: pathlib.Path,
    *,
    proposed_components: list[str] | None = None,
    declared_proxy: bool = False,
    frozen_resource_hashes: list[str] | None = None,
    frozen_at: str | None = None,
) -> dict[str, Any]:
    frozen_at = frozen_at or now()
    signal = _signals(raw_goal, goal_spec, project_plan)
    complexity = build_complexity_profile(raw_goal, goal_spec, project_plan, frozen_at=frozen_at)
    fidelity = build_goal_fidelity_contract(raw_goal, goal_spec, complexity, frozen_at=frozen_at)
    difficulty = build_core_difficulty_lock(fidelity, complexity, signal, frozen_at=frozen_at)
    realism, matrix = build_test_realism_and_challenges(
        signal,
        complexity,
        frozen_at=frozen_at,
        frozen_resource_hashes=frozen_resource_hashes,
    )
    adequacy = build_design_adequacy(complexity, difficulty, signal, project_plan)
    overengineering = build_overengineering_check(complexity, signal, project_plan, proposed_components)
    review = build_product_challenge_review(fidelity, complexity, difficulty, realism, matrix, adequacy, overengineering, declared_proxy=declared_proxy)
    documents = {
        "goal_fidelity_contract": fidelity,
        "project_complexity_profile": complexity,
        "core_difficulty_lock": difficulty,
        "test_realism_contract": realism,
        "challenge_matrix": matrix,
        "design_adequacy_report": adequacy,
        "product_challenge_review": review,
        "overengineering_check_report": overengineering,
    }
    paths: dict[str, str] = {}
    for key, filename in zip(documents, contract.PREIMPLEMENTATION_ARTIFACTS):
        validation = validate_artifact(documents[key])
        if validation["status"] != "PASS":
            raise ValueError(f"invalid product design governance artifact {key}: {validation['errors']}")
        paths[key] = str(write_json(pathlib.Path(output_dir) / filename, documents[key]).resolve())
    return {
        "kind": "CGKNProductDesignDepthGovernance",
        "schema_version": contract.SCHEMA_VERSION,
        "status": "PASS" if review["implementation_entry_allowed"] else "NEEDS_REWORK",
        "ready_to_implement": review["implementation_entry_allowed"],
        "review_verdict": review["verdict"],
        "maturity_ceiling": review["maturity_ceiling"],
        "documents": documents,
        "paths": paths,
    }


def _source_text(project_dir: pathlib.Path, implementation_evidence: dict[str, Any]) -> str:
    supplied = str(implementation_evidence.get("source_text", ""))
    if supplied:
        return supplied.lower()
    parts: list[str] = []
    for path in sorted(project_dir.rglob("*")) if project_dir.exists() else []:
        if not path.is_file() or any(part in {"tests", "test_resources", ".git", ".venv", "node_modules"} for part in path.relative_to(project_dir).parts):
            continue
        if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".java", ".rs", ".go", ".json", ".toml", ".yaml", ".yml"}:
            continue
        parts.append(path.read_text(encoding="utf-8", errors="replace")[:50000])
    return "\n".join(parts).lower()


def _resource_evidence(project_dir: pathlib.Path, test_evidence: dict[str, Any]) -> dict[str, Any]:
    declared = test_evidence.get("resources", []) if isinstance(test_evidence.get("resources"), list) else []
    if not declared:
        manifest = read_json(project_dir / "test_resource_manifest.json")
        declared = manifest.get("resources", []) if isinstance(manifest.get("resources"), list) else []
    types: list[str] = []
    for row in declared:
        text = json.dumps(row, ensure_ascii=False).lower() if isinstance(row, dict) else str(row).lower()
        if any(term in text for term in ("generated", "synthetic", "fixture", "mock", "本地生成", "自生成")):
            types.append("synthetic")
        elif text.strip():
            types.append("real_world")
    explicit = [str(item) for item in test_evidence.get("resource_types", []) if str(item).strip()]
    types.extend(explicit)
    unique = sorted(set(types))
    return {"resource_types": unique, "synthetic_only": bool(unique) and unique == ["synthetic"]}


def evaluate_proxy_solution(
    governance: dict[str, Any],
    project_dir: pathlib.Path,
    implementation_evidence: dict[str, Any] | None = None,
    test_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    implementation = dict(implementation_evidence or {})
    tests = dict(test_evidence or {})
    documents = governance.get("documents", {}) if isinstance(governance.get("documents"), dict) else {}
    fidelity = documents.get("goal_fidelity_contract", {})
    complexity = documents.get("project_complexity_profile", {})
    core_ids = [str(row.get("capability_id")) for row in fidelity.get("core_capabilities", []) if isinstance(row, dict)]
    source = _source_text(pathlib.Path(project_dir), implementation)
    method_rows = implementation.get("core_capability_methods", []) if isinstance(implementation.get("core_capability_methods"), list) else []
    resource = _resource_evidence(pathlib.Path(project_dir), tests)
    proxy_types: list[str] = []
    affected: list[str] = []
    identity_core = "real_person_identity_matching" in core_ids
    color_proxy = identity_core and any(token in source for token in ("dominant_hue", "hsv", "clothing_color", "appearance_color", "颜色直方图", "主色"))
    target_identity = identity_core and any(token in source for token in ("arcface", "face_recognition", "identity_embedding", "facenet", "insightface"))
    for row in method_rows:
        method = str(row.get("method_type", "")).upper() if isinstance(row, dict) else ""
        if method in {"PROXY", "HEURISTIC", "SIMULATED", "HARD_CODED"}:
            proxy_types.append(method.lower())
            affected.append(str(row.get("capability_id", "declared_core_outcome")))
    if color_proxy:
        proxy_types.append("appearance_color_identity_proxy")
        affected.append("real_person_identity_matching")
    if identity_core and not target_identity and not method_rows:
        proxy_types.append("unproven_identity_implementation")
        affected.append("real_person_identity_matching")
    if complexity.get("complexity_level") in {"COMPLEX", "HIGH_RISK"} and resource["synthetic_only"]:
        proxy_types.append("synthetic_only_acceptance")
        affected.extend(core_ids)
    if implementation.get("manual_review_compensates_for_missing_core") is True:
        proxy_types.append("manual_review_masks_core_failure")
        affected.extend(core_ids)
    if implementation.get("product_copy_claims_unvalidated_core") is True:
        proxy_types.append("product_claim_exceeds_implementation")
        affected.extend(core_ids)
    if tests.get("implementation_tailored_acceptance") is True or tests.get("test_specific_branches_added") is True:
        proxy_types.append("implementation_tailored_acceptance")
        affected.extend(core_ids)
    proxy_detected = bool(proxy_types)
    maximum = "PROTOTYPE" if proxy_detected else "PRODUCTION_READY"
    return _seal(
        {
            "kind": "CGKNProxySolutionReport",
            "schema_version": contract.SCHEMA_VERSION,
            "proxy_detected": proxy_detected,
            "proxy_type": sorted(set(proxy_types)),
            "affected_core_capability": sorted(set(affected)),
            "implementation_evidence": {
                "method_rows": method_rows,
                "source_indicators": [item for item, present in (("color_proxy", color_proxy), ("target_identity", target_identity)) if present],
            },
            "test_evidence": resource | {"test_status": tests.get("status", "NOT_EVALUATED")},
            "user_goal_impact": "core semantic outcome is not demonstrated" if proxy_detected else "no proxy contradiction detected",
            "maximum_allowed_maturity": maximum,
            "target_goal_satisfied": False if proxy_detected else None,
            "required_next_design_action": "return to the locked core capability and pass representative independent challenges" if proxy_detected else "continue independent maturity evaluation",
            "artifact_hash": "",
        },
        "artifact_hash",
    )


def _independent_evidence_valid(evidence: dict[str, Any]) -> bool:
    if evidence.get("kind") != "CGKNIndependentProductEvidence" or evidence.get("producer") != f"{contract.PRODUCER}.independent_challenge_verifier":
        return False
    return evidence.get("artifact_hash") == _json_hash(evidence, "artifact_hash") and evidence.get("status") == "PASS"


def produce_independent_product_evidence(
    *,
    real_world: bool,
    representative: bool,
    holdout_passed: bool,
    challenge_ids_passed: list[str],
    frozen_resource_hashes: list[str],
    production_checks: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return _seal(
        {
            "kind": "CGKNIndependentProductEvidence",
            "schema_version": contract.SCHEMA_VERSION,
            "producer": f"{contract.PRODUCER}.independent_challenge_verifier",
            "status": "PASS",
            "real_world": bool(real_world),
            "representative": bool(representative),
            "holdout_passed": bool(holdout_passed),
            "challenge_ids_passed": sorted(set(challenge_ids_passed)),
            "frozen_resource_hashes": sorted(set(frozen_resource_hashes)),
            "production_checks": dict(production_checks or {}),
            "created_at": now(),
            "artifact_hash": "",
        },
        "artifact_hash",
    )


def build_public_claim_policy(maturity: dict[str, Any], *, delivery_allowed: bool = False) -> dict[str, Any]:
    level = maturity["maturity_level"]
    target = bool(maturity["target_goal_satisfied"])
    if level == "DEMO":
        disclosure = "这是界面或流程演示，核心能力可能尚未真实实现。"
    elif level == "PROTOTYPE":
        if "appearance_color_identity_proxy" in maturity.get("proxy_types", []):
            disclosure = "这是外观/颜色代理原型，不是真实人物身份识别；可以交付演示包，但不能宣称原始目标已现实验证。"
        else:
            disclosure = "这是可运行原型；核心管线可用，但代理方案或证据范围不足，不能宣称原始目标已现实验证。"
    elif level == "FUNCTIONAL_MVP":
        disclosure = "核心能力已真实实现并有实际行为证据，但代表性现实覆盖和独立 holdout 仍有限。"
    elif level == "TARGET_VALIDATED":
        disclosure = "原始目标已在代表性现实场景和独立 holdout 中验证。"
    else:
        disclosure = "目标已现实验证，并完成性能、稳定性、安全、恢复、安装和交付检查。"
    return _seal(
        {
            "kind": "CGKNPublicClaimPolicyReport",
            "schema_version": contract.SCHEMA_VERSION,
            "delivery_allowed_is_not_target_success": True,
            "delivery_allowed": bool(delivery_allowed),
            "pipeline_verdict": "PIPELINE_PASS",
            "artifact_verdict": "ARTIFACT_PASS",
            "maturity_verdict": maturity["maturity_verdict"],
            "target_goal_satisfied": target,
            "real_world_validated": bool(maturity["real_world_validated"]),
            "proxy_detected": bool(maturity["proxy_detected"]),
            "public_claims_allowed": maturity["public_claims_allowed"],
            "public_claims_forbidden": maturity["public_claims_forbidden"],
            "public_disclosure": disclosure,
            "artifact_hash": "",
        },
        "artifact_hash",
    )


def evaluate_product_maturity(
    governance: dict[str, Any],
    project_dir: pathlib.Path,
    *,
    implementation_evidence: dict[str, Any] | None = None,
    test_evidence: dict[str, Any] | None = None,
    independent_evidence: dict[str, Any] | None = None,
    delivery_allowed: bool = False,
) -> dict[str, Any]:
    tests = dict(test_evidence or {})
    independent = dict(independent_evidence or {})
    proxy = evaluate_proxy_solution(governance, pathlib.Path(project_dir), implementation_evidence, tests)
    documents = governance.get("documents", {}) if isinstance(governance.get("documents"), dict) else {}
    fidelity = documents.get("goal_fidelity_contract", {})
    matrix = documents.get("challenge_matrix", {})
    realism = documents.get("test_realism_contract", {})
    complexity = documents.get("project_complexity_profile", {})
    core_ids = [str(row.get("capability_id")) for row in fidelity.get("core_capabilities", []) if isinstance(row, dict)]
    independent_valid = _independent_evidence_valid(independent)
    required_challenges = {str(row.get("challenge_id")) for row in matrix.get("challenges", []) if isinstance(row, dict) and row.get("required")}
    passed_challenges = {str(item) for item in independent.get("challenge_ids_passed", [])}
    challenge_complete = bool(required_challenges) and required_challenges.issubset(passed_challenges)
    tests_pass = str(tests.get("status", "")).upper() == "PASS" or tests.get("ok") is True
    real_world = independent_valid and independent.get("real_world") is True and independent.get("representative") is True
    holdout = independent_valid and independent.get("holdout_passed") is True
    contracted_resource_hashes = {str(item) for item in realism.get("frozen_resource_hashes", [])}
    evidenced_resource_hashes = {str(item) for item in independent.get("frozen_resource_hashes", [])}
    frozen_hashes = bool(contracted_resource_hashes) and contracted_resource_hashes.issubset(evidenced_resource_hashes)
    production_checks = independent.get("production_checks", {}) if isinstance(independent.get("production_checks"), dict) else {}
    production_complete = all(production_checks.get(key) is True for key in ("performance", "stability", "security", "recovery", "installation", "delivery"))
    if proxy["proxy_detected"]:
        level = "PROTOTYPE" if "simulated" not in proxy["proxy_type"] and "hard_coded" not in proxy["proxy_type"] else "DEMO"
    elif complexity.get("complexity_level") == "SIMPLE" and tests_pass:
        level = "TARGET_VALIDATED"
    elif not tests_pass:
        level = "DEMO"
    elif real_world and holdout and challenge_complete and frozen_hashes:
        level = "PRODUCTION_READY" if production_complete else "TARGET_VALIDATED"
    elif real_world:
        level = "FUNCTIONAL_MVP"
    else:
        level = "PROTOTYPE"
    target = level in {"TARGET_VALIDATED", "PRODUCTION_READY"}
    verdict = f"{level}_PASS"
    downgrade: list[str] = []
    if proxy["proxy_detected"]:
        downgrade.append("proxy or heuristic carries a locked core capability")
    if complexity.get("required_real_world_evidence") and not real_world:
        downgrade.append("representative independent real-world evidence missing")
    if documents.get("test_realism_contract", {}).get("holdout_required") and not holdout:
        downgrade.append("independent holdout not passed")
    if required_challenges and not challenge_complete:
        downgrade.append("required challenge matrix incomplete")
    if level == "TARGET_VALIDATED" and not production_complete:
        downgrade.append("production hardening evidence incomplete")
    allowed = [f"deliverable product maturity: {level}", "pipeline and artifact status may be reported separately"]
    forbidden = [] if target else ["original user goal is fully validated", "production-ready", "real-world validated"]
    maturity = _seal(
        {
            "kind": "CGKNProductMaturityReport",
            "schema_version": contract.SCHEMA_VERSION,
            "maturity_level": level,
            "maturity_verdict": verdict,
            "original_goal_satisfied": target,
            "core_capabilities_status": [{"capability_id": item, "status": "VALIDATED" if target else ("PROXY" if item in proxy["affected_core_capability"] else "UNVALIDATED")} for item in core_ids],
            "proxy_capabilities": proxy["affected_core_capability"],
            "proxy_types": proxy["proxy_type"],
            "real_world_evidence": {"valid": independent_valid, "representative": real_world, "challenge_complete": challenge_complete, "frozen_resource_hashes": frozen_hashes},
            "holdout_status": "PASS" if holdout else "NOT_EVALUATED",
            "unresolved_product_risks": downgrade,
            "maximum_justified_level": level,
            "downgrade_reasons": downgrade,
            "public_claims_allowed": allowed,
            "public_claims_forbidden": forbidden,
            "target_goal_satisfied": target,
            "real_world_validated": target,
            "proxy_detected": bool(proxy["proxy_detected"]),
            "artifact_hash": "",
        },
        "artifact_hash",
    )
    policy = build_public_claim_policy(maturity, delivery_allowed=delivery_allowed)
    triggers: list[str] = []
    if proxy["proxy_detected"]:
        triggers.append("core capability remains proxy-backed")
    if tests.get("repair_rounds_only_improved_synthetic") is True:
        triggers.append("repairs improved synthetic tests without real validation")
    if int(tests.get("consecutive_holdout_failures", 0) or 0) >= 2:
        triggers.append("holdout failed repeatedly")
    if tests.get("architecture_supports_core") is False:
        triggers.append("architecture cannot support the core requirement")
    if tests.get("test_specific_branches_added") is True:
        triggers.append("test-specific branches accumulated")
    replan = _seal(
        {
            "kind": "CGKNDesignReplanReport",
            "schema_version": contract.SCHEMA_VERSION,
            "status": "DESIGN_REPLAN_REQUIRED" if triggers else "CONTINUE_INCREMENT",
            "triggers": triggers,
            "preserved_components": ["validated UI", "persistence", "export", "non-core infrastructure"],
            "replan_scope": proxy["affected_core_capability"] or core_ids,
            "component_wide_rollback": False,
            "artifact_hash": "",
        },
        "artifact_hash",
    )
    return {"proxy_solution_report": proxy, "product_maturity_report": maturity, "public_claim_policy_report": policy, "design_replan_report": replan}


def evaluate_and_write_project_reports(
    project_dir: pathlib.Path,
    governance: dict[str, Any],
    *,
    implementation_evidence: dict[str, Any] | None = None,
    test_evidence: dict[str, Any] | None = None,
    independent_evidence: dict[str, Any] | None = None,
    delivery_allowed: bool = False,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    reports = evaluate_product_maturity(
        governance,
        project,
        implementation_evidence=implementation_evidence,
        test_evidence=test_evidence,
        independent_evidence=independent_evidence,
        delivery_allowed=delivery_allowed,
    )
    paths: dict[str, str] = {}
    for key, filename in zip(reports, contract.POSTBUILD_ARTIFACTS):
        validation = validate_artifact(reports[key])
        if validation["status"] != "PASS":
            raise ValueError(f"invalid product maturity artifact {key}: {validation['errors']}")
        paths[key] = str(write_json(project / filename, reports[key]).resolve())
    return {"status": "PASS", "reports": reports, "paths": paths}


def load_product_maturity(project_dir: pathlib.Path) -> dict[str, Any]:
    document = read_json(pathlib.Path(project_dir) / "product_maturity_report.json")
    if document and validate_artifact(document)["status"] == "PASS":
        return document
    return _seal(
        {
            "kind": "CGKNProductMaturityReport",
            "schema_version": contract.SCHEMA_VERSION,
            "maturity_level": "PROTOTYPE",
            "maturity_verdict": "PROTOTYPE_PASS",
            "original_goal_satisfied": False,
            "core_capabilities_status": [],
            "proxy_capabilities": ["unassessed_legacy_project"],
            "real_world_evidence": {"valid": False, "representative": False},
            "holdout_status": "NOT_EVALUATED",
            "unresolved_product_risks": ["canonical product maturity evidence missing"],
            "maximum_justified_level": "PROTOTYPE",
            "downgrade_reasons": ["legacy or unassessed project has no canonical maturity report"],
            "public_claims_allowed": ["artifact may be delivered if delivery evidence passes", "maturity is unassessed beyond prototype"],
            "public_claims_forbidden": ["original user goal is fully validated", "production-ready", "real-world validated"],
            "target_goal_satisfied": False,
            "real_world_validated": False,
            "proxy_detected": True,
            "artifact_hash": "",
        },
        "artifact_hash",
    )


def attach_maturity_to_delivery_gate(gate: dict[str, Any], project_dir: pathlib.Path) -> dict[str, Any]:
    result = dict(gate)
    maturity = load_product_maturity(project_dir)
    policy = read_json(pathlib.Path(project_dir) / "public_claim_policy_report.json")
    if not policy or validate_artifact(policy)["status"] != "PASS":
        policy = build_public_claim_policy(maturity, delivery_allowed=bool(result.get("delivery_allowed")))
    result.update(
        {
            "delivery_gate": str(result.get("verdict") or result.get("status") or "NOT_EVALUATED"),
            "product_maturity": maturity["maturity_level"],
            "maturity_verdict": maturity["maturity_verdict"],
            "target_goal_satisfied": maturity["target_goal_satisfied"],
            "real_world_validated": maturity["real_world_validated"],
            "proxy_detected": maturity["proxy_detected"],
            "public_claim_policy": policy,
        }
    )
    result["must_not_claim"] = list(dict.fromkeys(list(result.get("must_not_claim", [])) + list(maturity["public_claims_forbidden"])))
    if not maturity["target_goal_satisfied"]:
        warnings = list(result.get("user_visible_warnings", []))
        disclosure = str(policy.get("public_disclosure", ""))
        if disclosure and disclosure not in warnings:
            warnings.append(disclosure)
        result["user_visible_warnings"] = warnings
    return result
