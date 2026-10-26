#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

try:
    from scripts import product_design_depth_governance
    from scripts import canonical_goal_spec_compiler
except ImportError:  # Direct script execution keeps only scripts/ on sys.path.
    import product_design_depth_governance
    import canonical_goal_spec_compiler


RISK_VALUES = {"low", "medium", "high"}
STATUS_LAYERS = [
    "requirement_decision_status",
    "product_contract_status",
    "implementation_status",
    "delivery_status",
]
REQUIREMENT_ARTIFACTS = [
    "customer_goal_brief.md",
    "goal_spec.json",
    "project_plan.json",
    "need_interpretations.json",
    "candidate_requirements.json",
    "requirement_scorecard.json",
    "selected_requirement.json",
    "rejected_requirements.md",
    "mvp_scope.md",
    "non_goals.md",
    "customer_decision_summary.md",
]
FORBIDDEN_SHORTCUTS = [
    "direct_code_without_requirement_decision",
    "single_direction_without_comparison",
    "no_mvp_scope",
    "no_non_goals",
    "fake_pass",
    "delivery_pass_without_zip_or_screenshot",
]

DELIVERY_EVIDENCE_TERMS = (
    "截图",
    "演示视频",
    "demo video",
    "screenshot",
    "测试报告",
    "test report",
    "交付清单",
    "delivery manifest",
    "delivery_manifest",
    "final_project_bundle",
    "最终 zip",
    "public delivery gate",
)

MEDIA_PRODUCT_TERMS = (
    "视频处理",
    "视频素材",
    "视频创作者",
    "素材处理",
    "音频处理",
    "视频剪辑",
    "剪辑工作台",
    "切片工作台",
    "视频切片",
    "长视频",
    "候选片段",
    "转录",
    "video processing",
    "video workbench",
    "video slicer",
    "video clip",
    "media review",
    "media production",
    "media processing",
    "media evidence",
    "media pipeline",
    "video material",
    "transcribe",
    "clip selection",
)

VISUAL_NOVEL_PRODUCT_TERMS = (
    "视觉小说",
    "剧情树",
    "剧情分支",
    "人物立绘",
    "角色立绘",
    "vn studio",
    "visual novel",
    "story tree",
    "story graph",
    "branching narrative",
    "character sprite",
)

TASK_BOARD_PRODUCT_TERMS = ("任务看板", "个人看板", "task board", "kanban", "todo board", "待办看板")

SPECIALIZED_ANALYSIS_PRODUCT_TERMS = (
    "counter-strike",
    "counter strike",
    "cs2",
    "steam",
    "faceit",
    "demo parser",
    "demo download",
    "match demo",
    "crosshair",
    "aim analysis",
    "cheat detection",
    "anti-cheat",
    "反作弊",
    "开挂",
    "准星",
)

NEGATED_CAPABILITY_MARKERS = (
    "不需要",
    "不处理",
    "不要",
    "无需",
    "排除",
    "without ",
    "no ",
    "not ",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    write_text(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", str(text or "").lower())
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:72] or "customer_requirement"


def product_domain_goal(raw_goal: str) -> str:
    """Exclude delivery-evidence clauses before inferring the product domain."""
    chunks = re.split(r"[\n。！？!?；;]+", str(raw_goal or "").lower())
    product_chunks = [
        chunk.strip()
        for chunk in chunks
        if chunk.strip() and not any(term in chunk for term in DELIVERY_EVIDENCE_TERMS)
    ]
    return "\n".join(product_chunks) or str(raw_goal or "").lower()


def goal_has_positive_term(raw_goal: str, terms: tuple[str, ...]) -> bool:
    clauses = re.split(r"[\n。！？!?；;，,]+", product_domain_goal(raw_goal))
    for clause in clauses:
        if not any(term in clause for term in terms):
            continue
        if any(marker in clause for marker in NEGATED_CAPABILITY_MARKERS):
            continue
        return True
    return False


def goal_has_media_product(raw_goal: str) -> bool:
    return goal_has_positive_term(raw_goal, MEDIA_PRODUCT_TERMS)


def goal_has_visual_novel_product(raw_goal: str) -> bool:
    domain_goal = product_domain_goal(raw_goal)
    return any(token in domain_goal for token in VISUAL_NOVEL_PRODUCT_TERMS) or bool(
        re.search(r"\bvn\b", domain_goal)
    )


def goal_has_task_board_product(raw_goal: str) -> bool:
    domain_goal = product_domain_goal(raw_goal)
    return any(token in domain_goal for token in TASK_BOARD_PRODUCT_TERMS)


def goal_has_specialized_analysis_product(raw_goal: str) -> bool:
    domain_goal = product_domain_goal(raw_goal)
    return any(token in domain_goal for token in SPECIALIZED_ANALYSIS_PRODUCT_TERMS)


def goal_interaction_modes(goal_spec: dict[str, Any]) -> list[str]:
    """Separate user interaction modes from report/artifact interface names."""
    explicit = [
        str(item).strip().lower()
        for item in goal_spec.get("interaction_modes", [])
        if str(item).strip()
    ] if isinstance(goal_spec.get("interaction_modes", []), list) else []
    if explicit:
        return list(dict.fromkeys(explicit))
    interfaces = {
        str(item).strip().lower()
        for item in goal_spec.get("interfaces", [])
        if str(item).strip()
    } if isinstance(goal_spec.get("interfaces", []), list) else set()
    modes = [mode for mode in ("cli", "web", "gui", "desktop") if mode in interfaces]
    if modes:
        return modes
    raw_goal = str(goal_spec.get("goal", "")).lower()
    declared_modes: list[str] = []
    if re.search(r"\bcli\b|命令行", raw_goal):
        declared_modes.append("cli")
    if re.search(r"\bgui\b|图形界面|桌面界面", raw_goal):
        declared_modes.append("gui")
    if re.search(r"\bweb\b|网页|浏览器界面", raw_goal):
        declared_modes.append("web")
    if declared_modes:
        return list(dict.fromkeys(declared_modes))
    if str(goal_spec.get("domain", "")) in {
        "local_task_board",
        "visual_novel_editor",
        "productivity_timer",
        "csv_cleaning_tool",
        "choreography_notation_editor",
        "local_ai_knowledge_studio",
        "local_media_workbench",
        "local_studio_operations_hub",
        "team_operations_console",
        "local_research_workspace",
    }:
        return ["web"]
    return []


def _cs2_demo_analysis_profile(raw_goal: str) -> dict[str, Any] | None:
    """Preserve an explicit CS2 demo-analysis contract instead of a generic workbench."""
    goal = product_domain_goal(raw_goal)
    if not (
        any(token in goal for token in ("cs2", "counter-strike 2", "counter strike 2"))
        and any(token in goal for token in ("demo", ".dem", "demoparser2"))
        and any(token in goal for token in ("anomaly", "aim analysis", "crosshair", "反作弊", "开挂"))
    ):
        return None
    return {
        "domain": "cs2_demo_anomaly_analysis",
        "capabilities": [
            "discover_reviewed_public_demo_candidates",
            "validate_public_source_license_and_commit",
            "resolve_git_lfs_demo_objects",
            "download_bounded_authorized_demo_inputs",
            "safely_extract_demo_archives",
            "parse_cs2_demo_ticks_players_and_events",
            "compute_spatial_view_angle_and_crosshair_features",
            "derive_information_state_only_from_explicit_evidence",
            "detect_explainable_multi_signal_anomaly_windows",
            "export_json_and_html_human_review_reports",
            "run_real_demo_self_test_without_synthetic_fallback",
        ],
        "user_flows": [
            "run one explicitly network-authorized CLI self-test",
            "discover and rank bounded public demo candidates",
            "verify provenance and safely acquire one immutable demo object",
            "parse real ticks player states and available events",
            "analyze explainable spatial aim and information-state signals",
            "review JSON and local HTML evidence reports with limitations",
        ],
        "entities": [
            "PublicDemoCatalog",
            "DemoCandidate",
            "SourceManifest",
            "DemoProvenance",
            "PlayerTickState",
            "DemoEvent",
            "InformationState",
            "AnomalyWindow",
            "PlayerReviewReport",
        ],
        "interfaces": ["cli", "json_report", "html_report"],
        "interaction_modes": ["cli"],
        "report_formats": ["json", "html"],
        "runtime_dependencies": ["demoparser2", "py7zr"],
        "constraints": [
            "authorized_public_inputs_only",
            "explicit_network_opt_in",
            "bounded_https_catalog_and_downloads",
            "safe_archive_extraction",
            "source_and_object_provenance",
            "unknown_information_disables_dependent_signals",
            "view_angles_are_not_raw_mouse_input",
            "neutral_non_punitive_language",
            "human_review_required",
            "unlabeled_demo_accuracy_not_evaluated",
            "windows_compatible",
        ],
        "acceptance_behaviors": [
            "the CLI refuses network acquisition without explicit authorization",
            "catalog candidates retain public source license commit object hash and size provenance",
            "unsafe archive paths links member counts and expansion limits are rejected",
            "a selected real demo yields non-zero tick and player-state evidence",
            "player states include identity team position yaw and pitch",
            "available weapon fire round and death events join by tick and player",
            "angle wraparound spatial bearings distance motion and crosshair error are computed correctly",
            "unknown visibility sound teammate and prior-knowledge telemetry disables dependent signals",
            "anomaly windows expose samples coverage evidence confidence and limitations",
            "reports use neutral risk language and require human review",
            "an unlabeled public regression demo never claims detection accuracy or cheating",
            "the opt-in real self-test retries bounded candidates with synthetic fallback disabled",
        ],
    }


def _contains_goal_term(goal: str, terms: tuple[str, ...]) -> bool:
    lowered = product_domain_goal(goal)
    return any(term in lowered for term in terms)


FIXED_PROFILE_WORKFLOW_SIGNALS: dict[str, tuple[str, ...]] = {
    "visual_novel_editor": (
        "visual novel", "story", "scene", "character", "dialogue", "branch", "剧情", "场景", "角色", "对白", "分支",
    ),
    "productivity_timer": (
        "pomodoro", "timer", "countdown", "work session", "break session", "pause", "reset", "番茄钟", "倒计时", "暂停", "重置",
    ),
    "csv_cleaning_tool": (
        "csv", "missing value", "cleaning rule", "cleaned result", "清洗", "缺失值",
    ),
    "choreography_notation_editor": (
        "choreography", "dance", "movement", "transition", "timing", "舞蹈", "动作", "舞谱",
    ),
    "local_studio_operations_hub": (
        "production task", "asset", "bug", "issue", "release", "制作任务", "资产", "缺陷", "发布",
    ),
    "local_ai_knowledge_studio": (
        "knowledge", "document", "source", "report", "model adapter", "知识", "资料", "文档", "报告",
    ),
    "local_task_board": (
        "task", "board", "kanban", "status", "任务", "看板", "待办", "状态",
    ),
    "local_media_workbench": (
        "media", "video", "audio", "transcript", "clip", "segment", "视频", "音频", "转录", "片段",
    ),
    "specialized_analysis_workbench": (
        "authorized source", "provenance", "evidence", "feature", "analysis", "review report", "来源", "证据", "分析",
    ),
    "team_operations_console": (
        "milestone", "team task", "decision", "risk", "release status", "里程碑", "团队任务", "决策", "风险",
    ),
    "local_research_workspace": (
        "research source", "evidence note", "topic", "brief", "source import", "研究来源", "证据笔记", "主题", "简报",
    ),
}


def _explicit_workflow_clauses(raw_goal: str) -> list[str]:
    """Return user-stated workflow clauses without turning quality prose into features."""
    goal = product_domain_goal(raw_goal).strip()
    labelled = re.search(
        r"(?:core\s+workflows?|main\s+workflows?|核心流程|主要流程)\s*[:：]\s*(.+)",
        goal,
        flags=re.I | re.S,
    )
    workflow_text = labelled.group(1).strip() if labelled else goal
    if labelled:
        workflow_text = re.split(
            r"\.\s+(?=(?:seed|the user interface|include|documentation|tests?|quality|constraints?)\b)|。\s*(?=(?:界面|文档|测试|约束))",
            workflow_text,
            maxsplit=1,
            flags=re.I,
        )[0]
    clauses = [
        re.sub(r"\s+", " ", clause).strip(" .,:：")
        for clause in re.split(r"[;；\n]+", workflow_text)
    ]
    clauses = [
        clause
        for clause in clauses
        if len(clause) >= 8
        and not any(term in clause.lower() for term in DELIVERY_EVIDENCE_TERMS)
    ]
    return list(dict.fromkeys(clauses))[:12]


def _fixed_profile_dominates_workflows(clauses: list[str]) -> bool:
    """A fixed product may win only when its signals cover most explicit workflows."""
    if len(clauses) < 4:
        return True
    lowered_clauses = [clause.lower() for clause in clauses]
    for signals in FIXED_PROFILE_WORKFLOW_SIGNALS.values():
        matched = sum(
            1 for clause in lowered_clauses if any(signal in clause for signal in signals)
        )
        if matched * 2 >= len(lowered_clauses):
            return True
    return False


def _workflow_entity_symbols(clauses: list[str]) -> list[str]:
    """Derive bounded domain nouns from explicit workflows without a product template."""
    leading = {
        "create", "add", "edit", "manage", "maintain", "schedule", "track",
        "show", "practice", "record", "import", "export", "review", "run",
        "provide", "perform", "allow", "support", "a", "an", "the", "or", "and",
        "adjustable", "hierarchical", "transparent", "user", "owned", "daily",
    }
    stop = {"from", "with", "using", "while", "when", "through", "without", "and"}
    symbols: list[str] = []
    for index, clause in enumerate(clauses, start=1):
        tokens = [token for token in slug(clause).split("_") if token]
        while tokens and tokens[0] in leading:
            tokens.pop(0)
        selected: list[str] = []
        for token in tokens:
            if selected and token in stop:
                break
            if token not in leading:
                selected.append(token)
            if len(selected) >= 4:
                break
        if not selected:
            selected = [f"workflow{index:02d}", "record"]
        last = selected[-1]
        if last.endswith("ies") and len(last) > 4:
            selected[-1] = last[:-3] + "y"
        elif last.endswith("s") and not last.endswith("ss") and len(last) > 3:
            selected[-1] = last[:-1]
        symbol = "".join(part[:1].upper() + part[1:] for part in selected)
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    if "ApplicationState" not in symbols:
        symbols.append("ApplicationState")
    return symbols[:12]


AMBIGUOUS_RECORD_DOMAINS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("customer feedback", "feedback manager", "客户反馈", "客户建议", "客户问题"), "customer_feedback", "FeedbackItem"),
    (("appointment", "booking", "预约", "预订"), "appointment_management", "Appointment"),
    (("lab sample", "laboratory sample", "实验室样品", "样品记录"), "laboratory_sample_records", "Sample"),
    (("equipment loan", "equipment checkout", "设备借用", "器材借用"), "equipment_loan_management", "EquipmentLoan"),
    (("reading manager", "reading tracker", "阅读管理", "阅读记录", "书籍管理"), "personal_reading_management", "ReadingItem"),
    (("customer contact", "contact manager", "客户联系人", "联系人管理"), "contact_management", "Contact"),
    (("photo organizer", "photo manager", "照片整理", "图片整理", "相册管理"), "photo_organization", "PhotoAsset"),
    (("knowledge base", "knowledge manager", "知识库", "知识管理"), "local_knowledge_base", "KnowledgeEntry"),
)


def detect_understanding_signals(raw_goal: str) -> list[dict[str, str]]:
    """Detect facts that make understanding incomplete without owning interaction."""
    goal = product_domain_goal(raw_goal)
    signals: list[dict[str, str]] = []
    contradiction_pairs = (
        (("must be online", "requires internet", "必须联网"), ("must be offline", "no network", "完全离线", "禁止联网")),
        (("never store", "must not persist", "不能保存", "禁止存储"), ("must persist", "permanent history", "永久保存", "持久化保存")),
        (("irreversible delete", "永久删除", "不可恢复删除"), ("must be recoverable", "可恢复", "必须恢复")),
    )
    for positive, negative in contradiction_pairs:
        if any(term in goal for term in positive) and any(term in goal for term in negative):
            signals.append(
                {
                    "kind": "contradictory_requirements",
                    "reason": "The goal contains requirements that cannot both be satisfied.",
                    "resolution": "A later interaction authority must select the governing requirement.",
                }
            )
            break
    credential_signals = (
        "api key", "access token", "client secret", "production password", "login credential",
        "api 密钥", "访问令牌", "客户端密钥", "生产密码", "登录凭证", "账号授权",
    )
    credential_supplied = any(
        marker in goal
        for marker in ("credential is provided", "credentials are provided", "token is provided", "已提供凭证", "已提供令牌")
    )
    if any(term in goal for term in credential_signals) and not credential_supplied:
        signals.append(
            {
                "kind": "missing_required_credential",
                "reason": "The requested live integration requires a credential or authority that CGNK cannot infer.",
                "resolution": "A later interaction authority must obtain approved secret-channel authorization or remove the live integration.",
            }
        )
    external_fact_signals = (
        "exact internal policy", "our unpublished schema", "our private catalog", "company-specific legal rule",
        "精确内部规则", "未提供的内部字段", "公司私有目录", "内部合规政策",
    )
    if any(term in goal for term in external_fact_signals):
        signals.append(
            {
                "kind": "missing_critical_external_fact",
                "reason": "A critical external fact is required and was not supplied.",
                "resolution": "A later interaction authority must obtain the private rule, schema, or catalog.",
            }
        )
    irreversible_signals = (
        "charge real customers", "transfer real money", "publish to all users", "delete production records permanently",
        "permanently delete production records",
        "向真实客户扣款", "转账真实资金", "发布给所有用户", "永久删除生产数据",
    )
    if any(term in goal for term in irreversible_signals):
        signals.append(
            {
                "kind": "irreversible_user_decision_required",
                "reason": "The goal delegates a high-risk or irreversible production action without a confirmed user choice.",
                "resolution": "A later interaction authority must confirm the action and authorization boundary.",
            }
        )
    user_owned_signals = (
        "wait for me to choose", "i will decide", "leave the final choice to me", "等我选择", "由我决定", "最后我来选",
    )
    if any(term in goal for term in user_owned_signals):
        signals.append(
            {
                "kind": "explicit_user_owned_decision_pending",
                "reason": "The user explicitly retained a decision that has not yet been provided.",
                "resolution": "A later interaction authority must obtain the explicitly retained decision.",
            }
        )
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for signal in signals:
        if signal["kind"] not in seen:
            seen.add(signal["kind"])
            unique.append(signal)
    return unique


LEGACY_SIGNAL_QUESTIONS = {
    "contradictory_requirements": "Which of the conflicting requirements should govern the first version?",
    "missing_required_credential": "Provide the required credential through the approved secret channel or remove the live integration from v1.",
    "missing_critical_external_fact": "Provide the referenced private rule, schema, or catalog needed to freeze the ProjectSpec.",
    "irreversible_user_decision_required": "Confirm the exact irreversible action and its authorization boundary before implementation.",
    "explicit_user_owned_decision_pending": "Provide the decision you reserved before CGNK freezes the ProjectSpec.",
}


def goal_decision_blockers(raw_goal: str) -> list[dict[str, str]]:
    """Compatibility projection; it is not the canonical interaction authority."""
    return [
        {**signal, "question": LEGACY_SIGNAL_QUESTIONS[signal["kind"]]}
        for signal in detect_understanding_signals(raw_goal)
    ]


def _ambiguous_record_application_profile(raw_goal: str) -> dict[str, Any] | None:
    """Infer a conservative local CRUD/workflow v1 from a valid product-shaped goal."""
    goal = product_domain_goal(raw_goal)
    product_signals = (
        "tool", "app", "application", "system", "manager", "tracker", "organizer", "workspace",
        "工具", "应用", "系统", "管理", "记录", "整理", "跟踪", "工作台", "知识库",
    )
    selected: tuple[str, str] | None = None
    for signals, domain_label, entity_name in AMBIGUOUS_RECORD_DOMAINS:
        if any(signal in goal for signal in signals):
            selected = (domain_label, entity_name)
            break
    if selected is None or not any(signal in goal for signal in product_signals):
        return None
    domain_label, entity_name = selected
    human_subject = domain_label.replace("_", " ")
    return {
        "domain": "custom_local_application",
        "product_domain": domain_label,
        "capabilities": [
            "create_domain_record",
            "edit_domain_record",
            "track_domain_status",
            "search_domain_records",
            "filter_domain_records",
            "archive_domain_record",
        ],
        "user_flows": [
            f"create and edit a {human_subject} record",
            "move the record through a small explicit status workflow",
            "search and filter saved records",
            "open a record history and archive a resolved record",
        ],
        "entities": [entity_name, "StatusHistory", "SavedFilter"],
        "interfaces": ["web", "record_dashboard", "record_editor", "status_board", "search_and_archive"],
        "interaction_modes": ["web"],
        "entrypoints": ["app.main"],
        "runtime_dependencies": [],
        "constraints": ["local_first", "sqlite_persistence", "single_workspace_v1", "no_unrequested_external_service"],
        "assumptions": [
            "The first version is a local single-workspace web application.",
            "SQLite is the default persistence boundary because no database was specified.",
            "The initial status workflow is new, in_progress, resolved, and archived.",
            f"The minimum {human_subject} fields are an id, title, details, status, created_at, and updated_at.",
            "Layout and visual styling are implementation choices and do not require user confirmation before ProjectSpec freeze.",
        ],
        "acceptance_behaviors": [
            f"a valid {human_subject} record can be created and edited",
            "record status changes are persisted with history",
            "search and filters return matching saved records",
            "archived records remain retrievable and do not appear in the active default view",
            "records and status history survive an application restart",
        ],
    }


def _mixed_workflow_goal_profile(raw_goal: str) -> dict[str, Any] | None:
    """Preserve broad explicit products when one secondary feature matches a fixed profile."""
    clauses = _explicit_workflow_clauses(raw_goal)
    if len(clauses) < 4 or _fixed_profile_dominates_workflows(clauses):
        return None
    capabilities: list[str] = []
    for index, clause in enumerate(clauses, start=1):
        capability = slug(clause)[:58].rstrip("_") or f"workflow_{index:02d}"
        candidate = capability
        if candidate in capabilities:
            candidate = f"{capability[:54].rstrip('_')}_{index:02d}"
        capabilities.append(candidate)
    lowered = product_domain_goal(raw_goal)
    constraints = ["no_unrequested_external_service"]
    constraint_rules = (
        (("local-first", "local first", "本地优先"), "local_first"),
        (("sqlite",), "sqlite_persistence"),
        (("python 3.11",), "python_3_11"),
        (("without requiring a cloud", "no cloud", "无需云", "不需要云"), "no_cloud_required"),
        (("responsive", "响应式"), "responsive_interface"),
        (("keyboard accessible", "键盘可访问"), "keyboard_accessible"),
        (("mobile friendly", "移动端友好"), "mobile_friendly"),
        (("chinese", "中文"), "chinese_localization"),
        (("original", "原创"), "original_content_only"),
    )
    for signals, constraint in constraint_rules:
        if any(signal in lowered for signal in signals):
            constraints.append(constraint)
    interaction_modes: list[str] = []
    if re.search(r"\bweb\b|browser\s+ui|网页|浏览器", lowered):
        interaction_modes.append("web")
    if re.search(r"\bcli\b|command[- ]line|命令行", lowered):
        interaction_modes.append("cli")
    if re.search(r"\bgui\b|desktop\s+(?:ui|app)|图形界面|桌面界面", lowered):
        interaction_modes.append("gui")
    interfaces = [*interaction_modes, "primary_workspace", "workflow_navigation"]
    entrypoints = ["app.main"] if "web" in interaction_modes else []
    return {
        "domain": "custom_local_application",
        "capabilities": capabilities,
        "user_flows": clauses,
        "entities": _workflow_entity_symbols(clauses),
        "interfaces": list(dict.fromkeys(interfaces)),
        "interaction_modes": interaction_modes,
        "entrypoints": entrypoints,
        "runtime_dependencies": [],
        "constraints": list(dict.fromkeys(constraints)),
        "acceptance_behaviors": [f"the application supports this stated workflow: {clause}" for clause in clauses],
    }


def _explicit_local_cli_profile(
    raw_goal: str, planning_contract: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Derive a domain-preserving plan for an explicit record-oriented CLI."""
    lowered = product_domain_goal(raw_goal)
    if not re.search(r"\bcli\b|command[- ]line|命令行", lowered):
        return None
    action_rules = (
        ("add", (r"\badd\b", r"\bcreate\b", "新增", "添加")),
        ("list", (r"\blist\b", "列表", "列出")),
        ("show", (r"\bshow\b", r"\bget\b", "查看")),
        ("search", (r"\bsearch\b", r"\bfind\b", "搜索", "查找")),
        ("update", (r"\bupdate\b", r"\bedit\b", "更新", "编辑")),
        ("delete", (r"\bdelete\b", r"\bremove\b", "删除")),
        ("complete", (r"\bcomplete\b", r"\bcompleted\b", "完成")),
        ("summary", (r"\bsummary\b", r"\bstats?\b", "汇总", "统计")),
        ("import", (r"\bimport\b", "导入")),
        ("export", (r"\bexport\b", "导出")),
    )
    actions = [
        action
        for action, patterns in action_rules
        if any(re.search(pattern, lowered) for pattern in patterns)
    ]
    if len(actions) < 3:
        return None
    noun_match = re.search(
        r"\b([a-z][a-z0-9_-]*)\s+(?:command[- ]line(?:\s+(?:application|app|tool))?|cli)\b",
        lowered,
    )
    noun = str(noun_match.group(1) if noun_match else "record").strip("_-")
    if noun in {"and", "python", "offline", "local", "compact", "simple"}:
        noun = "record"
    singular = noun[:-1] if noun.endswith("s") and len(noun) > 3 else noun
    entity_id = slug(singular)
    entity_name = "".join(part.capitalize() for part in re.split(r"[_-]+", entity_id)) or "Record"
    behaviors: list[str] = []
    behavior_templates = {
        "add": f"add creates and persists one valid {entity_id}",
        "list": f"list returns persisted {entity_id} records in stable order",
        "show": f"show returns the requested {entity_id} or a stable not-found error",
        "search": f"search returns matching persisted {entity_id} records",
        "update": f"update changes only the requested {entity_id} fields and persists them",
        "delete": f"delete removes an existing {entity_id} and reports a stable not-found error when absent",
        "complete": f"complete changes an existing {entity_id} to completed and reports a stable not-found error when absent",
        "summary": f"summary reports total completed and open {entity_id} counts",
        "import": f"import validates and persists supported {entity_id} records",
        "export": f"export emits the current {entity_id} records without changing them",
    }
    behaviors.extend(behavior_templates[action] for action in actions)
    constraints = ["local_first", "cli_only", "no_unrequested_external_service"]
    if "atomic" in lowered or "原子" in lowered:
        constraints.append("atomic_persistence")
        behaviors.append("persistence replaces the data file atomically without leaving partial state")
    if "json" in lowered:
        constraints.extend(["versioned_json_storage", "stable_json_cli_output"])
    if "argparse" in lowered or "no framework" in lowered or "without a framework" in lowered:
        constraints.append("standard_library_runtime")
    if "case-insensitive" in lowered or "case insensitive" in lowered or "不区分大小写" in lowered:
        constraints.append("case_insensitive_search")
        behaviors.append("search matches declared text fields case-insensitively")
    if "corrupt" in lowered or "损坏" in lowered:
        constraints.append("corrupt_storage_fails_safe")
        behaviors.append("corrupt storage fails safely without overwriting the original data")
    if any(term in lowered for term in ("never execute", "arbitrary command", "eval", "exec")):
        constraints.append("no_dynamic_execution")
    if "secret" in lowered or "credential" in lowered:
        constraints.extend(["no_secret_storage", "no_credential_literals"])
    if "standard library" in lowered or "no runtime dependencies" in lowered:
        constraints.extend(["standard_library_runtime", "no_network_dependency"])

    contract = planning_contract if isinstance(planning_contract, dict) else {}
    required_symbols = [str(item) for item in contract.get("required_symbols", []) if str(item).strip()]
    explicit_entity = next(
        (item for item in required_symbols if not item.endswith(("Repository", "Service"))),
        "",
    )
    repository_symbol = next((item for item in required_symbols if item.endswith("Repository")), "")
    service_symbol = next((item for item in required_symbols if item.endswith("Service")), "")
    if explicit_entity:
        entity_name = explicit_entity
        entity_id = slug(explicit_entity)
        behaviors = [re.sub(r"\brecord\b", entity_id, behavior) for behavior in behaviors]
    package_name = ""
    required_paths = [str(item).replace("\\", "/") for item in contract.get("required_paths", [])]
    package_candidates = [path.split("/", 1)[0] for path in required_paths if "/" in path and path.endswith(".py")]
    required_entrypoints = [str(item) for item in contract.get("required_entrypoints", []) if str(item).strip()]
    if required_entrypoints:
        package_name = required_entrypoints[0].split(".", 1)[0]
    elif package_candidates and len(set(package_candidates)) == 1:
        package_name = package_candidates[0]
    if "list" in actions and (
        "status filtering" in lowered
        or "status filter" in lowered
        or ("status" in lowered and "filter" in lowered)
    ):
        behaviors.append(
            f"list status filtering returns only open or completed {entity_id} records"
        )
    if "duplicate identifier" in lowered or "duplicate id" in lowered:
        behaviors.append(
            f"duplicate {entity_id} identifiers are rejected without replacing persisted data"
        )
    merge_replace_requested = bool(
        "import" in actions
        and "merge" in lowered
        and "replace" in lowered
        and ("mode" in lowered or "merge/replace" in lowered)
    )
    if merge_replace_requested:
        behaviors.extend(
            [
                f"import merge adds non-conflicting {entity_id} records and rejects duplicate identifiers",
                f"import replace replaces all existing {entity_id} records with validated imported records",
            ]
        )
    if "exit code" in lowered:
        behaviors.append(
            "CLI returns exit code 0 on success and exit code 2 for invalid input or data errors"
        )
    module_match = re.search(r"python\s+-m\s+([a-z][a-z0-9_.-]*)", lowered)
    if module_match and "console entry" in lowered:
        module_name = module_match.group(1)
        console_name = required_entrypoints[0] if required_entrypoints else (package_name or module_name)
        behaviors.append(
            f"python -m {module_name} and the {console_name} console entry invoke the same CLI"
        )
    profile = {
        "domain": "local_record_cli",
        "capabilities": [f"{action}_{entity_id}" for action in actions],
        "user_flows": [f"run the {action} command for {entity_id} records" for action in actions],
        "entities": [
            entity_name,
            repository_symbol or f"{entity_name}Repository",
            service_symbol or f"{entity_name}Service",
        ],
        "interfaces": ["cli", "json_store"] if "json" in lowered else ["cli", "local_store"],
        "interaction_modes": ["cli"],
        "constraints": list(dict.fromkeys(constraints)),
        "acceptance_behaviors": list(dict.fromkeys(behaviors)),
    }
    if package_name:
        profile.update(
            {
                "package_name": package_name,
                "required_project_paths": required_paths,
                "entrypoints": required_entrypoints,
                "expected_symbols": required_symbols,
            }
        )
    return profile


def _feature_unit_negative_scope(lowered: str) -> list[str]:
    """Return explicit short-task exclusions without inventing product scope."""
    rules = (
        (("no persistence", "without persistence", "do not add persistence", "不要持久化", "不需要持久化"), "no_persistence"),
        (("no networking", "without networking", "do not add networking", "不要网络", "不需要网络"), "no_network"),
        (("no framework", "without a framework", "do not add frameworks", "不要框架", "不需要框架"), "no_frameworks"),
        (("no gui", "without a gui", "do not add a gui", "不要图形界面", "不需要图形界面"), "no_gui"),
        (("no unrelated features", "without unrelated features", "do not add unrelated features", "不要额外功能", "不需要额外功能"), "no_unrelated_features"),
    )
    selected = [value for phrases, value in rules if any(phrase in lowered for phrase in phrases)]
    negative_clauses = re.findall(
        r"(?:do not add|without|no)\s+([^.;\n]{1,220})",
        lowered,
        flags=re.I,
    )
    negative_text = " ".join(negative_clauses)
    grouped_terms = (
        (r"\bpersistence\b", "no_persistence"),
        (r"\bnetwork(?:ing)?\b", "no_network"),
        (r"\bframeworks?\b", "no_frameworks"),
        (r"\bgui\b", "no_gui"),
        (r"\bunrelated\s+features?\b", "no_unrelated_features"),
    )
    for pattern, value in grouped_terms:
        if re.search(pattern, negative_text, flags=re.I) and value not in selected:
            selected.append(value)
    return selected


def _feature_signature_inputs(raw_parameters: str) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for raw_parameter in str(raw_parameters or "").split(","):
        parameter = raw_parameter.strip()
        if not parameter or parameter in {"/", "*", "self", "cls"}:
            continue
        required = "=" not in parameter
        declaration = parameter.split("=", 1)[0].strip().lstrip("*")
        if ":" in declaration:
            name, annotation = declaration.split(":", 1)
        else:
            name, annotation = declaration, "Any"
        normalized_name = str(name).strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized_name):
            continue
        inputs.append(
            {
                "name": normalized_name,
                "type": str(annotation).strip() or "Any",
                "required": required,
            }
        )
    return inputs[:8]


def _explicit_feature_unit_profile(
    raw_goal: str, planning_contract: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Recognize explicit typed operations before generic application expansion."""
    goal = str(raw_goal or "").strip()
    lowered = product_domain_goal(goal)
    type_atom = (
        r"[A-Za-z_][A-Za-z0-9_.]*"
        r"(?:\s*\[(?:[^\[\]\n]|\[[^\[\]\n]*\])+\])?"
    )
    pattern = re.compile(
        rf"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(([^()\n]{{0,320}})\)\s*->\s*"
        rf"({type_atom}(?:\s*\|\s*{type_atom})*)",
        flags=re.I,
    )
    signatures: list[tuple[str, str, str]] = []
    for match in pattern.finditer(goal):
        name = str(match.group(1)).strip()
        output_type = str(match.group(3)).strip().rstrip(".,")
        if name.startswith("__") or not output_type:
            continue
        candidate = (name, str(match.group(2)).strip(), output_type)
        if candidate not in signatures:
            signatures.append(candidate)
    if not signatures or len(signatures) > 8:
        return None

    contract = planning_contract if isinstance(planning_contract, dict) else {}
    package_match = re.search(
        r"\b(?:project|package|application|app|tool)\s+(?:named\s+)?([A-Za-z][A-Za-z0-9_-]{1,63})\b",
        goal,
        flags=re.I,
    )
    package_name = slug(package_match.group(1)) if package_match else ""
    required_entrypoints = [
        str(item).strip()
        for item in contract.get("required_entrypoints", [])
        if str(item).strip()
    ]
    if required_entrypoints:
        package_name = slug(required_entrypoints[0].split(".", 1)[0])
    if not package_name or package_name in {"python", "minimal", "local", "command_line"}:
        package_name = slug(f"{signatures[0][0]}_tool")

    errors = list(dict.fromkeys(re.findall(r"\b([A-Z][A-Za-z0-9_]*Error)\b", goal)))
    negative_scope = _feature_unit_negative_scope(lowered)
    cli_requested = bool(re.search(r"\bcli\b|command[- ]line|命令行", lowered))
    feature_contracts: list[dict[str, Any]] = []
    for name, raw_parameters, output_type in signatures:
        inputs = _feature_signature_inputs(raw_parameters)
        acceptance = [
            f"{name} is importable with the frozen signature {name}({raw_parameters}) -> {output_type}",
            f"{name} returns a value matching {output_type} for valid declared inputs",
        ]
        if "strip" in lowered and "whitespace" in lowered:
            acceptance.append(f"{name} strips surrounding whitespace from its string input")
        if "blank" in lowered and "ValueError" in errors:
            acceptance.append(f"{name} raises ValueError when the normalized input is blank")
        if cli_requested and "json" in lowered:
            acceptance.append("the CLI prints exactly one JSON object derived from this feature result")
        feature = {
            "kind": "CGKNFeatureContract",
            "schema_version": 1,
            "feature_id": slug(name),
            "public_entrypoint": {
                "name": name,
                "signature": f"{name}({raw_parameters}) -> {output_type}",
                "inputs": inputs,
                "output": {"type": output_type},
            },
            "errors": [
                {
                    "type": error,
                    "condition": (
                        "normalized input is blank"
                        if error == "ValueError" and "blank" in lowered
                        else "declared invalid input"
                    ),
                }
                for error in errors
            ],
            "side_effects": [],
            "dependencies": [],
            "owned_paths": [f"{package_name}/{slug(name)}.py"],
            "acceptance_checks": list(dict.fromkeys(acceptance)),
        }
        canonical = json.dumps(feature, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        feature["interface_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        feature_contracts.append(feature)

    ownership = {
        path: feature["feature_id"]
        for feature in feature_contracts
        for path in feature["owned_paths"]
    }
    freeze = {
        "kind": "CGKNFeatureInterfaceFreeze",
        "schema_version": 1,
        "frozen": True,
        "feature_ids": [feature["feature_id"] for feature in feature_contracts],
        "owned_path_index": ownership,
        "conflicts": [],
    }
    freeze_canonical = json.dumps(freeze, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    freeze["freeze_sha256"] = hashlib.sha256(freeze_canonical.encode("utf-8")).hexdigest()
    constraints = [
        "one_public_operation_per_feature",
        "frozen_feature_interfaces_before_generation",
        "conflict_free_file_ownership",
        *negative_scope,
    ]
    if "standard library" in lowered:
        constraints.extend(["standard_library_runtime", "no_third_party_runtime_dependencies"])
    return {
        "domain": "feature_unit_application",
        "package_name": package_name,
        "capabilities": [feature["feature_id"] for feature in feature_contracts],
        "user_flows": [
            f"provide the declared inputs to {feature['feature_id']} and receive its declared output"
            for feature in feature_contracts
        ],
        "entities": [],
        "interfaces": ["python_api", *( ["cli"] if cli_requested else [] )],
        "interaction_modes": ["cli"] if cli_requested else [],
        "entrypoints": [
            f"{package_name}.{feature['public_entrypoint']['name']}"
            for feature in feature_contracts
        ] + ([f"{package_name}.__main__"] if cli_requested else []),
        "runtime_dependencies": [],
        "constraints": list(dict.fromkeys(constraints)),
        "acceptance_behaviors": list(
            dict.fromkeys(
                check
                for feature in feature_contracts
                for check in feature["acceptance_checks"]
            )
        ),
        "feature_contracts": feature_contracts,
        "feature_interface_freeze": freeze,
    }


def _goal_profile(
    raw_goal: str, planning_contract: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    goal = str(raw_goal or "").strip()
    lowered = product_domain_goal(goal)
    if not goal:
        return None
    cs2_profile = _cs2_demo_analysis_profile(goal)
    if cs2_profile is not None:
        return cs2_profile
    explicit_cli_profile = _explicit_local_cli_profile(goal, planning_contract)
    if explicit_cli_profile is not None:
        return explicit_cli_profile
    feature_unit_profile = _explicit_feature_unit_profile(goal, planning_contract)
    if feature_unit_profile is not None:
        return feature_unit_profile
    mixed_workflow_profile = _mixed_workflow_goal_profile(goal)
    if mixed_workflow_profile is not None:
        return mixed_workflow_profile
    if goal_has_visual_novel_product(goal):
        return {
            "domain": "visual_novel_editor",
            "capabilities": ["create_scenes", "manage_characters", "link_story_branches", "edit_dialogue", "generate_background_images", "generate_character_sprites", "bind_visual_assets", "preview_story_flow", "export_story_project"],
            "user_flows": ["create scenes and characters", "edit dialogue and connect story branches", "generate separate background and character-sprite assets", "bind generated assets to story nodes", "preview alternate story flow", "export and reload the story project"],
            "entities": ["StoryProject", "Scene", "Character", "Dialogue", "StoryBranch", "VisualAsset", "GenerationJob"],
            "interfaces": ["story_tree", "scene_editor", "character_editor", "branch_editor", "background_generator", "sprite_generator", "asset_library", "story_preview", "project_export"],
            "constraints": ["local_first", "persistent_project_state", "honest_image_generation", "separate_background_sprite_evidence"],
            "acceptance_behaviors": ["a scene can be created and edited", "a character can be created and assigned dialogue", "a branch can be linked to another scene", "background generation creates a decoder-valid image through the configured image backend or reports the missing capability", "sprite generation creates a decoder-valid transparent image through the configured image backend or reports the missing capability", "generated visual assets can be bound to story nodes", "edited dialogue survives save and export", "the user can preview and export the story flow"],
        }
    if _contains_goal_term(goal, ("pomodoro", "番茄钟", "work and break", "work/break")):
        return {
            "domain": "productivity_timer",
            "capabilities": ["start_timer", "pause_resume_timer", "reset_timer", "switch_work_break_cycle", "show_remaining_time"],
            "user_flows": ["start a configured work timer", "pause and resume the countdown", "reset the current session", "reach zero and switch between work and break phases"],
            "entities": ["TimerSession", "TimerSettings", "TimerPhase"],
            "interfaces": ["timer_view", "timer_controls", "phase_indicator", "timer_settings"],
            "constraints": ["local_first", "no_cloud_required", "countdown_state_is_deterministic"],
            "acceptance_behaviors": ["starting the timer decreases remaining time", "pausing the timer freezes the countdown", "resuming continues from the paused value", "reset restores the configured duration", "reaching zero switches the work or break phase"],
        }
    if "csv" in lowered and _contains_goal_term(goal, ("clean", "cleaning", "missing", "清洗", "缺失")):
        return {
            "domain": "csv_cleaning_tool",
            "capabilities": ["import_csv", "detect_missing_values", "configure_cleaning_rules", "apply_cleaning_rules", "preview_cleaned_result", "export_cleaned_csv"],
            "user_flows": ["import a local CSV file", "inspect missing values and choose cleaning rules", "preview the cleaned result", "export a new CSV file"],
            "entities": ["CsvDataset", "CsvColumn", "MissingValueFinding", "CleaningRule", "CleaningResult"],
            "interfaces": ["csv_import", "cleaning_rule_editor", "result_preview", "csv_export"],
            "constraints": ["local_first", "preserve_source_file", "no_cloud_required"],
            "acceptance_behaviors": ["a valid CSV parses into rows and columns", "missing values are detected", "selected cleaning rules transform matching values", "the preview reflects the cleaned result", "the cleaned dataset exports as a new CSV"],
        }
    if _contains_goal_term(goal, ("choreography", "dance sequence", "舞蹈编排", "舞谱")):
        return {
            "domain": "choreography_notation_editor",
            "capabilities": ["create_dance_sequence", "add_movement_notation", "arrange_sequence_timing", "edit_transition", "preview_choreography", "export_notation_project"],
            "user_flows": ["create a dance sequence", "add movements and timing", "edit transitions between movements", "preview and export the notation plan"],
            "entities": ["ChoreographyProject", "DanceSequence", "Movement", "Transition", "TimingCue"],
            "interfaces": ["sequence_editor", "movement_palette", "timing_track", "choreography_preview", "project_export"],
            "constraints": ["local_first", "editable_sequence_order", "no_cloud_required"],
            "acceptance_behaviors": ["a movement can be added to a sequence", "movement timing can be changed", "transitions preserve their linked movements", "the sequence can be previewed and exported"],
        }
    studio_operations_requested = (
        _contains_goal_term(goal, ("studio operations", "studio hub"))
        and _contains_goal_term(goal, ("asset", "production task", "bug", "release"))
    )
    if studio_operations_requested:
        return {
            "domain": "local_studio_operations_hub",
            "capabilities": ["show_project_dashboard", "track_production_tasks", "manage_asset_library", "track_bugs_and_issues", "record_build_and_release_history", "manage_release_checklist", "manage_team_roles", "search_operational_records", "import_export_workspace"],
            "user_flows": ["review project and production progress", "update tasks, assets, bugs, and release state", "search operational records", "import or export the local workspace"],
            "entities": ["StudioProject", "ProductionTask", "Asset", "Issue", "Build", "ReleaseChecklist", "TeamMember"],
            "interfaces": ["project_dashboard", "production_board", "asset_library", "issue_tracker", "release_view", "team_roles", "workspace_import_export"],
            "constraints": ["local_first", "no_external_saas_required"],
            "acceptance_behaviors": ["production progress is visible", "tasks, assets, issues, and releases retain their state", "operational records can be searched", "the workspace can be imported and exported"],
        }
    knowledge_requested = (
        _contains_goal_term(goal, ("knowledge studio", "knowledge workspace", "知识工作台", "知识库"))
        and _contains_goal_term(goal, ("document", "资料", "文档", "knowledge", "知识"))
    )
    if knowledge_requested:
        return {
            "domain": "local_ai_knowledge_studio",
            "capabilities": ["import_documents", "search_knowledge_base", "track_knowledge_tasks", "generate_reports", "configure_local_model_adapter"],
            "user_flows": ["import local documents", "search the indexed knowledge base", "create tasks from findings", "generate a report", "configure or inspect the local model adapter"],
            "entities": ["Document", "KnowledgeEntry", "KnowledgeTask", "Report", "ModelConfiguration"],
            "interfaces": ["document_import", "knowledge_search", "task_workspace", "report_view", "model_settings"],
            "constraints": ["local_first", "honest_model_capability", "no_cloud_required"],
            "acceptance_behaviors": ["an imported document becomes searchable", "knowledge search returns matching source content", "a task can be created from knowledge work", "a report summarizes selected sources and tasks", "missing model configuration is reported without claiming inference"],
        }
    if goal_has_task_board_product(goal):
        return {
            "domain": "local_task_board",
            "capabilities": ["create_task", "move_task_status", "delete_task", "filter_tasks", "persist_board_state"],
            "user_flows": ["create a task", "move it between board states", "filter visible tasks", "reload persisted board state", "delete a task"],
            "entities": ["Task", "TaskStatus", "BoardFilter"],
            "interfaces": ["task_board", "task_editor", "board_filters"],
            "constraints": ["local_first", "no_cloud_required"],
            "acceptance_behaviors": ["a task can be created", "task status can be changed", "filters change the visible task set", "board state survives reload", "a task can be deleted"],
        }
    if goal_has_media_product(goal):
        return {
            "domain": "local_media_workbench",
            "capabilities": ["import_media", "process_media_pipeline", "review_segments", "select_clips", "export_media_artifacts"],
            "user_flows": ["import local media", "run the processing stages", "review segments", "select clips", "export traceable artifacts"],
            "entities": ["MediaAsset", "PipelineRun", "Segment", "ClipSelection", "ExportManifest"],
            "interfaces": ["media_import", "pipeline_run", "segment_review", "clip_export"],
            "constraints": ["local_first", "honest_degraded_mode"],
            "acceptance_behaviors": ["imported media enters a traceable run", "stage results remain linked to the run", "segments can be reviewed and selected", "selected clips export with a manifest"],
        }
    if goal_has_specialized_analysis_product(goal):
        return {
            "domain": "specialized_analysis_workbench",
            "capabilities": ["register_authorized_sources", "acquire_authorized_input", "validate_input_provenance", "normalize_evidence", "analyze_explainable_features", "export_review_report"],
            "user_flows": ["register a reviewed source", "acquire authorized input", "validate and normalize evidence", "analyze explainable features", "export a human-review report"],
            "entities": ["SourceRegistry", "AcquisitionRecord", "EvidenceRecord", "FeatureFinding", "ReviewReport"],
            "interfaces": ["source_registry", "analysis_runs", "evidence_review", "report_export"],
            "constraints": ["authorized_inputs_only", "source_traceability", "no_automatic_punitive_decision"],
            "acceptance_behaviors": ["input provenance is retained", "invalid input is rejected", "analysis findings cite normalized evidence", "the exported report states limitations"],
        }
    if _contains_goal_term(goal, ("studio operations", "team operating", "团队管理", "indie team")):
        return {
            "domain": "team_operations_console",
            "capabilities": ["plan_milestones", "track_team_tasks", "link_project_assets", "record_decisions", "assess_risks", "export_release_status"],
            "user_flows": ["create a milestone", "assign and track work", "link assets and decisions", "review risks", "export release status"],
            "entities": ["Milestone", "TeamTask", "ProjectAsset", "Decision", "Risk", "ReleaseStatus"],
            "interfaces": ["team_dashboard", "milestone_board", "asset_links", "decision_log", "risk_review", "release_export"],
            "constraints": ["local_first", "traceable_status_changes"],
            "acceptance_behaviors": ["milestones retain linked tasks", "assets remain linked to work", "decisions and risks are reviewable", "release status can be exported"],
        }
    if _contains_goal_term(goal, ("research", "资料整理", "研究工作台")):
        return {
            "domain": "local_research_workspace",
            "capabilities": ["import_sources", "extract_source_metadata", "create_evidence_notes", "cluster_topics", "draft_traceable_brief", "export_evidence_pack"],
            "user_flows": ["import research sources", "create source-linked notes", "organize topics", "draft a brief", "export an evidence pack"],
            "entities": ["Source", "EvidenceNote", "TopicCluster", "ResearchBrief"],
            "interfaces": ["source_import", "notes_workspace", "topic_board", "brief_editor", "evidence_export"],
            "constraints": ["local_first", "source_traceability"],
            "acceptance_behaviors": ["an imported source retains provenance", "notes remain linked to sources", "topics group related notes", "the exported brief cites its evidence"],
        }
    inferred_record_profile = _ambiguous_record_application_profile(goal)
    if inferred_record_profile is not None:
        return inferred_record_profile
    words = re.findall(r"[a-z][a-z0-9_-]+|[\u4e00-\u9fff]{2,}", lowered)
    capability_rules = (
        ("create", "create_domain_record"), ("edit", "edit_domain_record"),
        ("plan", "plan_domain_workflow"), ("manage", "manage_domain_state"),
        ("track", "track_domain_state"), ("import", "import_domain_data"),
        ("export", "export_domain_result"), ("preview", "preview_domain_result"),
        ("analy", "analyze_domain_data"),
    )
    capabilities = [capability for marker, capability in capability_rules if marker in lowered]
    capabilities = list(dict.fromkeys(capabilities))
    if len(words) < 4 or len(capabilities) < 2:
        return None
    return {
        "domain": "custom_local_application",
        "capabilities": capabilities,
        "user_flows": ["provide domain input", "perform the requested domain workflow", "review and save the domain result"],
        "entities": ["DomainRecord", "ProjectState"],
        "interfaces": ["primary_workspace", "domain_editor", "result_view"],
        "constraints": ["local_first", "no_unrequested_external_service"],
        "acceptance_behaviors": [capability.replace("_", " ") + " behaves on user-provided data" for capability in capabilities],
    }


def build_goal_spec(
    raw_goal: str,
    planning_contract: dict[str, Any] | None = None,
    *,
    planning_artifact: dict[str, Any] | None = None,
    conversation_context: dict[str, Any] | None = None,
    system_constraints: list[str] | None = None,
) -> dict[str, Any]:
    signals = detect_understanding_signals(raw_goal)
    if signals:
        blockers = goal_decision_blockers(raw_goal)
        return {
            "kind": "GoalSpec",
            "status": "NEEDS_REWORK",
            "reason": "USER_DECISION_REQUIRED",
            "goal": str(raw_goal or "").strip(),
            "domain": "generic_custom",
            "capabilities": [],
            "user_flows": [],
            "entities": [],
            "interfaces": [],
            "constraints": [],
            "assumptions": [],
            "understanding_signals": signals,
            "interaction_authority": "unassigned_pending_clarification_layer",
            # Legacy projections retained for downstream compatibility only.
            "decision_blockers": blockers,
            "blocking_questions": [item["question"] for item in blockers],
            "ready_to_generate": False,
            "acceptance_behaviors": [],
        }
    profile = _goal_profile(raw_goal, planning_contract)
    if planning_artifact:
        return canonical_goal_spec_compiler.compile_goal_spec(
            raw_goal=raw_goal,
            planning_artifact=planning_artifact,
            fast_path_profile=profile,
            conversation_context=conversation_context,
            system_constraints=system_constraints,
        )
    if profile is None:
        return {
            "kind": "GoalSpec",
            "status": "NEEDS_REWORK",
            "reason": "INSUFFICIENT_GOAL_PLAN",
            "goal": str(raw_goal or "").strip(),
            "domain": "generic_custom",
            "capabilities": [],
            "user_flows": [],
            "entities": [],
            "interfaces": [],
            "constraints": [],
            "assumptions": [],
            "understanding_signals": [],
            "interaction_authority": "unassigned_pending_clarification_layer",
            "decision_blockers": [],
            "blocking_questions": [],
            "ready_to_generate": False,
            "acceptance_behaviors": [],
        }
    return {
        "kind": "GoalSpec",
        "status": "PASS",
        "goal": str(raw_goal or "").strip(),
        "assumptions": canonical_goal_spec_compiler.canonicalize_assumptions(
            profile.get("assumptions", []),
            [
                "Unspecified implementation details use conservative local-first defaults.",
                "Unspecified layout, storage fields, and first-version scope remain revisable implementation choices.",
            ] if not profile.get("assumptions") else [],
        ),
        "understanding_signals": [],
        "interaction_authority": "unassigned_pending_clarification_layer",
        "decision_blockers": [],
        "blocking_questions": [],
        "ready_to_generate": True,
        **profile,
    }


DOMAIN_WORKSTREAMS: dict[str, list[tuple[str, str]]] = {
    "local_record_cli": [
        ("record_model_repository", "Model the declared record and implement safe local persistence behind one repository contract."),
        ("record_service_cli", "Implement the declared record behaviors and bind every named command to a concrete CLI handler."),
        ("record_behavior_tests", "Verify every declared CLI, service, persistence, and error behavior."),
    ],
    "productivity_timer": [
        ("timer_domain", "Model timer sessions, settings, phases, and valid transitions."),
        ("timer_state", "Implement start, pause, resume, reset, countdown, and work/break state changes."),
        ("timer_ui", "Expose remaining time, phase state, controls, and settings in the local interface."),
        ("timer_behavior_tests", "Verify countdown, pause, reset, and phase-switch behavior."),
    ],
    "csv_cleaning_tool": [
        ("csv_import", "Parse local CSV input and preserve source data and column shape."),
        ("cleaning_engine", "Detect missing values and apply explicit cleaning rules."),
        ("result_preview", "Present findings and the cleaned row/column result before export."),
        ("csv_export", "Write a new CSV without overwriting the source file."),
        ("cleaning_tests", "Verify parsing, missing-value transformation, preview, and export."),
    ],
    "visual_novel_editor": [
        ("story_model", "Model scenes, characters, dialogue, links, and branching story state."),
        ("scene_editor", "Create and edit scenes and dialogue."),
        ("character_editor", "Create characters and assign character dialogue and metadata."),
        ("branch_editor", "Connect scenes into validated branches and alternate paths."),
        ("background_generator", "Generate decoder-valid background assets through the configured image backend and report missing capability honestly."),
        ("sprite_generator", "Generate decoder-valid transparent character sprites through the configured image backend and report missing capability honestly."),
        ("asset_library", "Store generated visual assets and bind them to the shared story-project model."),
        ("preview_export", "Preview story flow and save or export the project."),
        ("story_behavior_tests", "Verify scene, character, branch, image generation, asset binding, dialogue persistence, preview, and export behavior."),
    ],
    "choreography_notation_editor": [
        ("sequence_model", "Model dance sequences, movements, transitions, and timing cues."),
        ("notation_editor", "Create and edit movement notation."),
        ("movement_timeline", "Arrange movement order, timing, and transitions."),
        ("sequence_preview_export", "Preview choreography and export the notation project."),
        ("choreography_tests", "Verify movement editing, timing, transition integrity, preview, and export."),
    ],
    "local_ai_knowledge_studio": [
        ("document_import", "Import local documents and retain source metadata."),
        ("knowledge_search", "Index and search imported knowledge content."),
        ("task_reporting", "Create knowledge-work tasks and generate source-linked reports."),
        ("model_adapter", "Configure a local model adapter and report missing capability honestly."),
        ("knowledge_behavior_tests", "Verify import, search, task, report, and adapter-limit behavior."),
    ],
    "local_media_workbench": [
        ("ingest_video", "Import local media and record a traceable media manifest."),
        ("extract_audio", "Extract usable audio or record an honest degraded result."),
        ("build_audio_chunk_manifest", "Split audio into traceable chunks for transcription."),
        ("transcribe_chunks", "Transcribe available chunks through the configured capability."),
        ("merge_transcript", "Merge chunk transcripts while retaining source timing."),
        ("optional_analysis", "Analyze and score reviewable media segments."),
        ("select_segments", "Select candidate segments using explicit review criteria."),
        ("build_clip_manifest", "Build a clip manifest linked to selected segments."),
        ("render_clips_batch", "Render or honestly degrade the selected clip batch."),
        ("export_results", "Export reports, manifests, and selected media artifacts."),
        ("media_behavior_tests", "Verify import, traceability, review, selection, degraded-mode, and export behavior."),
    ],
    "specialized_analysis_workbench": [
        ("research_platform_sources", "Research and record reviewed official source capabilities and limitations."),
        ("acquire_authorized_input", "Acquire only authorized input while retaining provenance."),
        ("validate_and_normalize_evidence", "Validate input integrity and normalize traceable evidence records."),
        ("analyze_explainable_features", "Compute explainable features without making automatic punitive decisions."),
        ("render_evidence_report", "Export a human-review report that cites evidence and limitations."),
        ("specialized_analysis_tests", "Verify authorization, provenance, normalization, explainability, and report behavior."),
    ],
    "cs2_demo_anomaly_analysis": [
        ("catalog_and_provenance", "Discover reviewed public demo candidates and retain license, commit, object, hash, size, and attempt provenance."),
        ("bounded_acquisition", "Resolve Git LFS objects, download within explicit HTTPS/resource bounds, fail over candidates, and safely extract archives."),
        ("demo_parser", "Parse real CS2 demo ticks, player identity/team/position/view angles, weapon fire, round, and death events through demoparser2."),
        ("geometry_and_information", "Compute wrapped angles, spatial bearings, distance, relative motion, crosshair error, and evidence-bounded information state."),
        ("explainable_anomaly_analysis", "Produce sample-bounded snap, alignment, tracking, switching, and pre-aim/prefire windows without punitive classification."),
        ("human_review_reporting", "Write machine-readable JSON and local HTML reports with coverage, evidence, confidence, unknowns, limitations, and human-review wording."),
        ("real_demo_self_test", "Run the complete opt-in public-demo workflow with candidate retry and synthetic fallback disabled."),
        ("cs2_demo_behavior_tests", "Verify catalog, LFS, network bounds, extraction security, parser proof, geometry, information unknowns, signal samples, reporting, and optional live integration."),
    ],
}

DOMAIN_RUNTIME_ARTIFACTS: dict[str, list[str]] = {
    "local_media_workbench": [
        "stage_plan.json",
        "media_manifest.json",
        "audio_chunk_manifest.json",
        "transcript_merged.json",
        "segment_analysis.json",
        "selected_segments.json",
        "clip_manifest.json",
        "export_results.json",
    ],
}


def _workstream_output(workstream_id: str, domain: str) -> str:
    if workstream_id.endswith("_tests") or "behavior_tests" in workstream_id:
        return f"tests/test_{workstream_id}.py"
    if domain in {"cs2_demo_anomaly_analysis", "local_record_cli"}:
        return f"backend/{workstream_id}.py"
    return f"src/{workstream_id}.py"


def goal_acceptance_test_contract(acceptance_behaviors: list[Any]) -> list[dict[str, str]]:
    """Assign an exact executable test identity to every canonical behavior."""
    contract: list[dict[str, str]] = []
    for index, raw_behavior in enumerate(acceptance_behaviors, start=1):
        behavior = str(raw_behavior).strip()
        if not behavior:
            continue
        contract.append(
            {
                "intent": behavior,
                "test_symbol": f"test_goal_{index:02d}_{slug(behavior)[:48].rstrip('_')}",
            }
        )
    return contract


def feature_contract_ready_batches(feature_contracts: list[dict[str, Any]]) -> list[list[str]]:
    """Return deterministic dependency-ready, conflict-free feature batches."""
    by_id = {
        str(feature.get("feature_id", "")).strip(): feature
        for feature in feature_contracts
        if isinstance(feature, dict) and str(feature.get("feature_id", "")).strip()
    }
    remaining = dict(by_id)
    completed: set[str] = set()
    batches: list[list[str]] = []
    while remaining:
        ready_ids = [
            feature_id
            for feature_id, feature in remaining.items()
            if all(str(item) in completed for item in feature.get("dependencies", []))
        ]
        if not ready_ids:
            ready_ids = [next(iter(remaining))]
        batch: list[str] = []
        owned: set[str] = set()
        for feature_id in ready_ids:
            paths = {
                str(path).replace("\\", "/").strip()
                for path in remaining[feature_id].get("owned_paths", [])
                if str(path).strip()
            }
            if paths.intersection(owned):
                continue
            batch.append(feature_id)
            owned.update(paths)
        if not batch:
            batch = [ready_ids[0]]
        batches.append(batch)
        for feature_id in batch:
            completed.add(feature_id)
            remaining.pop(feature_id, None)
    return batches


def build_feature_unit_project_plan(goal_spec: dict[str, Any]) -> dict[str, Any]:
    """Build only the files needed for frozen, independently owned feature contracts."""
    package_name = str(goal_spec.get("package_name", "feature_tool")).strip() or "feature_tool"
    features = [
        feature
        for feature in goal_spec.get("feature_contracts", [])
        if isinstance(feature, dict) and str(feature.get("feature_id", "")).strip()
    ]
    acceptance_behaviors = [
        str(item) for item in goal_spec.get("acceptance_behaviors", [])
    ]
    goal_tests = goal_acceptance_test_contract(acceptance_behaviors)
    goal_test_symbol_by_intent = {
        str(item.get("intent", "")): str(item.get("test_symbol", ""))
        for item in goal_tests
        if str(item.get("intent", "")).strip()
        and str(item.get("test_symbol", "")).strip()
    }
    workstreams: list[dict[str, Any]] = [
        {
            "id": "foundation",
            "scope": (
                f"Declare the minimal Python project {package_name} and test metadata "
                "without adding runtime architecture."
            ),
            "depends_on": [],
            "expected_outputs": ["pyproject.toml", "requirements.txt"],
            "owned_paths": ["pyproject.toml", "requirements.txt"],
            "expected_symbols": [],
            "test_intents": [
                f"pyproject.toml declares project.name as {package_name}"
            ],
        }
    ]
    feature_workstream_ids: list[str] = []
    for feature in features:
        feature_id = str(feature["feature_id"])
        workstream_id = f"feature_{feature_id}"
        feature_workstream_ids.append(workstream_id)
        workstreams.append(
            {
                "id": workstream_id,
                "scope": f"Implement only the frozen {feature_id} feature contract.",
                "depends_on": [
                    "foundation",
                    *[
                        f"feature_{dependency}"
                        for dependency in feature.get("dependencies", [])
                    ],
                ],
                "expected_outputs": list(feature.get("owned_paths", [])),
                "owned_paths": list(feature.get("owned_paths", [])),
                "expected_symbols": [
                    str(feature.get("public_entrypoint", {}).get("name", ""))
                ],
                "test_intents": [],
                "feature_contracts": [feature],
            }
        )
    workstreams.append(
        {
            "id": "package_interface",
            "scope": "Publish only the frozen public feature entrypoints from the package boundary.",
            "depends_on": list(feature_workstream_ids),
            "expected_outputs": [f"{package_name}/__init__.py"],
            "owned_paths": [f"{package_name}/__init__.py"],
            "expected_symbols": [
                str(feature.get("public_entrypoint", {}).get("name", ""))
                for feature in features
            ],
            "test_intents": [],
            "feature_contracts": features,
        }
    )
    cli_requested = "cli" in goal_interaction_modes(goal_spec)
    if cli_requested:
        workstreams.append(
            {
                "id": "application_entry",
                "scope": "Adapt the frozen feature interfaces to the requested CLI without adding business behavior.",
                "depends_on": ["package_interface"],
                "expected_outputs": [f"{package_name}/__main__.py"],
                "owned_paths": [f"{package_name}/__main__.py"],
                "expected_symbols": ["main"],
                "test_intents": [],
                "feature_contracts": features,
            }
        )
    test_dependency = "application_entry" if cli_requested else "package_interface"
    test_workstream_ids: list[str] = []
    for feature in features:
        feature_id = str(feature["feature_id"])
        workstream_id = f"feature_{feature_id}_tests"
        test_workstream_ids.append(workstream_id)
        workstreams.append(
            {
                "id": workstream_id,
                "scope": f"Verify only the frozen {feature_id} behavior and its requested adapter behavior.",
                "depends_on": [f"feature_{feature_id}", test_dependency],
                "expected_outputs": [f"tests/test_{feature_id}.py"],
                "owned_paths": [f"tests/test_{feature_id}.py"],
                "expected_symbols": [
                    goal_test_symbol_by_intent[str(intent)]
                    for intent in feature.get("acceptance_checks", [])
                    if str(intent) in goal_test_symbol_by_intent
                ],
                "test_intents": [
                    *list(feature.get("acceptance_checks", [])),
                    *(
                        [
                            f'Invoke the CLI only as [sys.executable, "-m", "{package_name}", title]; '
                            f"do not invent a {package_name}.cli module."
                        ]
                        if cli_requested
                        else []
                    ),
                ],
                "feature_contracts": [feature],
            }
        )
    delivery_outputs = ["README.md", "TEST_PLAN.md", "DELIVERY_NOTES.md"]
    workstreams.append(
        {
            "id": "delivery",
            "scope": "Document only installation, the frozen feature interfaces, tests, and delivery limits.",
            "depends_on": test_workstream_ids or [test_dependency],
            "expected_outputs": delivery_outputs,
            "owned_paths": delivery_outputs,
            "expected_symbols": [],
            "test_intents": [],
        }
    )
    leaves = [
        {
            "leaf_id": f"{workstream['id']}_leaf",
            "workstream_id": workstream["id"],
            "scope": workstream["scope"],
            "depends_on": [f"{item}_leaf" for item in workstream["depends_on"]],
            "expected_outputs": list(workstream["expected_outputs"]),
            "owned_paths": list(workstream.get("owned_paths", workstream["expected_outputs"])),
            "expected_symbols": list(workstream.get("expected_symbols", [])),
            "test_intents": list(workstream.get("test_intents", [])),
            "feature_contracts": list(workstream.get("feature_contracts", [])),
        }
        for workstream in workstreams
    ]
    expected_structure = list(
        dict.fromkeys(path for row in workstreams for path in row["expected_outputs"])
    )
    feature_batches = feature_contract_ready_batches(features)
    return {
        "kind": "GoalDrivenProjectPlan",
        "status": "PASS",
        "goal": goal_spec.get("goal", ""),
        "domain": "feature_unit_application",
        "workstreams": workstreams,
        "leaves": leaves,
        "dependencies": [
            {"from": dependency, "to": row["id"]}
            for row in workstreams
            for dependency in row["depends_on"]
        ],
        "expected_project_structure": expected_structure,
        "business_outputs": [
            path
            for path in expected_structure
            if path.endswith(".py") and not path.startswith("tests/")
        ],
        "runtime_artifacts": [
            path
            for path in expected_structure
            if path.startswith(package_name + "/") and path.endswith(".py")
        ],
        "interaction_modes": goal_interaction_modes(goal_spec),
        "report_formats": [],
        "runtime_dependencies": [],
        "entrypoints": list(goal_spec.get("entrypoints", [])),
        "test_intents": acceptance_behaviors,
        "goal_acceptance_tests": goal_tests,
        "feature_contracts": features,
        "feature_interface_freeze": goal_spec.get("feature_interface_freeze", {}),
        "feature_parallel_batches": feature_batches,
        "parallelism_policy": {
            "interfaces_frozen_before_generation": True,
            "dependency_ready_only": True,
            "owned_path_conflicts_forbidden": True,
            "failed_feature_repairs_are_isolated": True,
        },
    }


def understanding_readiness(goal_spec: dict[str, Any]) -> dict[str, Any]:
    """The single seam between canonical Task Understanding and Planning."""
    signals = goal_spec.get("understanding_signals", [])
    ready = bool(
        goal_spec.get("kind") == "GoalSpec"
        and goal_spec.get("status") == "PASS"
        and goal_spec.get("ready_to_generate", True)
        and not signals
    )
    return {
        "kind": "CGKNUnderstandingReadiness",
        "ready": ready,
        "reason": "" if ready else str(goal_spec.get("reason") or "UNDERSTANDING_NOT_READY"),
        "goal_spec_authority": str(goal_spec.get("authority") or "compatibility_fast_path"),
        "signals": list(signals) if isinstance(signals, list) else [],
        "planning_authorized": ready,
    }


def build_goal_project_plan(goal_spec: dict[str, Any]) -> dict[str, Any]:
    readiness = understanding_readiness(goal_spec)
    if not readiness["planning_authorized"]:
        return {
            "kind": "GoalDrivenProjectPlan",
            "status": "NEEDS_REWORK",
            "reason": readiness["reason"],
            "understanding_readiness": readiness,
            "workstreams": [],
            "leaves": [],
            "dependencies": [],
            "expected_project_structure": [],
            "business_outputs": [],
            "runtime_artifacts": [],
            "test_intents": [],
            "goal_acceptance_tests": [],
        }
    domain = str(goal_spec.get("domain", "custom_local_application"))
    if domain == "feature_unit_application":
        return build_feature_unit_project_plan(goal_spec)
    definitions = DOMAIN_WORKSTREAMS.get(domain)
    compiled_open_domain_workstreams = (
        domain == "custom_local_application"
        and bool(goal_spec.get("compiler_version"))
        and isinstance(goal_spec.get("workstreams"), list)
        and bool(goal_spec.get("workstreams"))
    )
    if compiled_open_domain_workstreams:
        definitions = [
            (
                str(item.get("id", "")),
                str(item.get("scope", "")),
            )
            for item in goal_spec["workstreams"]
            if isinstance(item, dict)
            and str(item.get("id", "")).strip()
            and str(item.get("scope", "")).strip()
        ]
        definitions.append(
            ("goal_behavior_tests", "Verify every acceptance anchor from the grounded canonical GoalSpec.")
        )
    package_name = str(goal_spec.get("package_name", "")).strip()
    entities = [str(item) for item in (goal_spec.get("entities") or []) if str(item).strip()]
    entity_name = entities[0] if entities else "Record"
    repository_symbol = entities[1] if len(entities) >= 2 else f"{entity_name}Repository"
    service_symbol = entities[2] if len(entities) >= 3 else f"{entity_name}Service"
    if domain == "local_record_cli" and package_name:
        definitions = [
            ("record_model", "Define the validated record and its domain invariants.", f"{package_name}/model.py", [entity_name]),
            ("record_repository", "Implement safe atomic JSON persistence behind one repository contract.", f"{package_name}/repository.py", [repository_symbol]),
            ("record_service", "Own every declared record behavior without duplicating persistence or CLI concerns.", f"{package_name}/service.py", [service_symbol]),
            ("record_cli", "Bind every named command and stable exit code to the service contract.", f"{package_name}/cli.py", ["build_parser", "main"]),
            ("record_behavior_tests", "Verify every declared CLI, service, persistence, and error behavior.", f"tests/test_{slug(package_name)}.py", []),
        ]
    if not definitions:
        capability_flows = [str(item) for item in goal_spec.get("user_flows", [])]
        workflow_definitions = [
            (
                str(capability),
                "Implement and verify the user-stated workflow: "
                + (
                    capability_flows[index]
                    if index < len(capability_flows)
                    else str(capability).replace("_", " ")
                ),
                _workstream_output(str(capability), domain),
                [str(capability)],
            )
            for index, capability in enumerate(goal_spec.get("capabilities", []))
        ]
        if domain == "custom_local_application":
            definitions = [
                (
                    "domain_models",
                    "Define the canonical domain records and validation invariants shared by every workflow.",
                    "src/domain_models.py",
                    entities,
                ),
                (
                    "persistence_repository",
                    "Implement one shared local persistence boundary for all domain records.",
                    "src/repository.py",
                    [
                        "SQLiteRepository"
                        if "sqlite_persistence" in goal_spec.get("constraints", [])
                        else "LocalRepository"
                    ],
                ),
                (
                    "application_service",
                    "Coordinate domain validation, persistence, and cross-workflow behavior through one service boundary.",
                    "src/service.py",
                    ["ApplicationService"],
                ),
                *workflow_definitions,
            ]
        else:
            definitions = workflow_definitions
        definitions.append(("goal_behavior_tests", "Verify every acceptance behavior from the GoalSpec."))
    workstreams: list[dict[str, Any]] = []
    prior_ids: list[str] = []
    foundation_outputs = ["pyproject.toml", "requirements.txt"]
    if package_name:
        foundation_outputs.append(f"{package_name}/__init__.py")
    foundation = {
        "id": "foundation",
        "scope": "Create the runnable local project shell, dependency metadata, and shared domain contracts.",
        "depends_on": [],
        "expected_outputs": foundation_outputs,
        "expected_symbols": [],
        "test_intents": [],
    }
    workstreams.append(foundation)
    prior_ids.append("foundation")
    application_entry = (
        f"{package_name}/__main__.py"
        if domain == "local_record_cli" and package_name
        else "main.py" if domain in {"cs2_demo_anomaly_analysis", "local_record_cli"} else "app/main.py"
    )
    workstreams.append(
        {
            "id": "application_entry",
            "scope": "Expose the declared interaction modes through one runnable local entrypoint without adding an unrequested interface.",
            "depends_on": ["foundation"],
            "expected_outputs": [application_entry],
            "expected_symbols": ["main"] if package_name else [],
            "test_intents": [],
        }
    )
    prior_ids.append("application_entry")
    acceptance_behaviors = [str(item) for item in goal_spec.get("acceptance_behaviors", [])]
    goal_tests = goal_acceptance_test_contract(acceptance_behaviors)
    interaction_modes = goal_interaction_modes(goal_spec)
    visual_interface_required = bool({"web", "gui", "desktop"}.intersection(interaction_modes))
    user_interface_added = False
    for definition in definitions:
        workstream_id, scope = definition[:2]
        is_test = workstream_id.endswith("_tests") or "behavior_tests" in workstream_id
        if is_test and visual_interface_required and not user_interface_added:
            workstreams.append(
                {
                    "id": "user_interface",
                    "scope": "Implement the declared visual interaction modes with owned markup, styling, behavior, responsive layout, and accessible focus feedback.",
                    "depends_on": list(prior_ids),
                    "expected_outputs": [
                        "frontend/index.html",
                        "frontend/styles.css",
                        "frontend/app.js",
                    ],
                    "expected_symbols": [],
                    "test_intents": [],
                }
            )
            prior_ids.append("user_interface")
            user_interface_added = True
        if domain == "custom_local_application" and not is_test and not compiled_open_domain_workstreams:
            if workstream_id == "domain_models":
                dependencies = ["foundation"]
            elif workstream_id == "persistence_repository":
                dependencies = ["foundation", "domain_models"]
            elif workstream_id == "application_service":
                dependencies = ["domain_models", "persistence_repository"]
            else:
                dependencies = ["application_service"]
        elif compiled_open_domain_workstreams and not is_test:
            business_ids = [
                row["id"]
                for row in workstreams
                if row["id"] not in {"foundation", "application_entry"}
            ]
            dependencies = [business_ids[-1]] if business_ids else ["foundation"]
        else:
            dependencies = list(prior_ids if is_test else ["foundation"])
        test_intents = acceptance_behaviors if is_test else []
        workstream = {
            "id": workstream_id,
            "scope": scope,
            "depends_on": dependencies,
            "expected_outputs": [
                str(definition[2]) if len(definition) >= 3 else _workstream_output(workstream_id, domain)
            ],
            "expected_symbols": list(definition[3]) if len(definition) >= 4 else [],
            "test_intents": test_intents,
        }
        workstreams.append(workstream)
        prior_ids.append(workstream_id)
    if domain == "custom_local_application":
        application_entry_workstream = next(
            row for row in workstreams if row["id"] == "application_entry"
        )
        if compiled_open_domain_workstreams:
            business_ids = [
                row["id"]
                for row in workstreams
                if row["id"] not in {"foundation", "application_entry"}
                and not (row["id"].endswith("_tests") or "behavior_tests" in row["id"])
            ]
            application_entry_workstream["depends_on"] = [
                "foundation",
                *business_ids[-1:],
            ]
        else:
            application_entry_workstream["depends_on"] = [
                "foundation",
                "application_service",
            ]
        application_entry_workstream["expected_symbols"] = ["main"]
    delivery_dependencies = [workstreams[-1]["id"]] if workstreams else ["foundation"]
    delivery_outputs = ["README.md", "TEST_PLAN.md", "DELIVERY_NOTES.md"]
    workstreams.append({
        "id": "delivery",
        "scope": "Document local startup, known constraints, and expected project contents for the existing delivery path.",
        "depends_on": delivery_dependencies,
        "expected_outputs": delivery_outputs,
        "expected_symbols": [],
        "test_intents": [],
    })
    leaves = [
        {
            "leaf_id": f"{workstream['id']}_leaf",
            "workstream_id": workstream["id"],
            "scope": workstream["scope"],
            "depends_on": [f"{item}_leaf" for item in workstream["depends_on"]],
            "expected_outputs": list(workstream["expected_outputs"]),
            "expected_symbols": list(workstream.get("expected_symbols", [])),
            "test_intents": list(workstream["test_intents"]),
        }
        for workstream in workstreams
    ]
    expected_structure = list(dict.fromkeys(path for row in workstreams for path in row["expected_outputs"]))
    business_outputs = [path for path in expected_structure if path not in {"README.md", "pyproject.toml", "requirements.txt", application_entry, "TEST_PLAN.md", "DELIVERY_NOTES.md"}]
    return {
        "kind": "GoalDrivenProjectPlan",
        "status": "PASS",
        "goal": goal_spec.get("goal", ""),
        "domain": domain,
        "workstreams": workstreams,
        "leaves": leaves,
        "dependencies": [{"from": dependency, "to": row["id"]} for row in workstreams for dependency in row["depends_on"]],
        "expected_project_structure": expected_structure,
        "business_outputs": business_outputs,
        "runtime_artifacts": list(DOMAIN_RUNTIME_ARTIFACTS.get(domain, business_outputs)),
        "interaction_modes": interaction_modes,
        "report_formats": list(goal_spec.get("report_formats", [])),
        "runtime_dependencies": list(goal_spec.get("runtime_dependencies", [])),
        "entrypoints": list(goal_spec.get("entrypoints", [])),
        "test_intents": acceptance_behaviors,
        "goal_acceptance_tests": goal_tests,
    }


def _goal_candidate_id(domain: str) -> str:
    return {
        "local_media_workbench": "local_video_material_workbench_requirement",
        "local_task_board": "local_task_board_requirement",
        "visual_novel_editor": "local_visual_novel_studio_requirement",
        "local_research_workspace": "local_research_workspace_requirement",
        "local_ai_knowledge_studio": "local_ai_knowledge_studio_requirement",
        "specialized_analysis_workbench": "goal_derived_specialized_analysis_requirement",
        "team_operations_console": "indie_team_operating_console_requirement",
    }.get(domain, f"goal_derived_{slug(domain)}_requirement")


def candidate_from_goal_spec(goal_spec: dict[str, Any], project_plan: dict[str, Any]) -> dict[str, Any]:
    domain = str(goal_spec.get("domain", "custom_local_application"))
    title = domain.replace("_", " ").title()
    return _candidate(
        candidate_id=_goal_candidate_id(domain),
        name=title,
        summary=f"Goal-derived local product plan for: {goal_spec.get('goal', '')}",
        target_user="The user described by the current goal.",
        core_problem=f"Implement the requested {title} behavior without substituting an unrelated product template.",
        product_shape="Local-first application shaped by the declared interfaces and constraints.",
        mvp_features=[str(item).replace("_", " ") for item in goal_spec.get("capabilities", [])],
        non_goals=["Unrequested external services", "Unrelated product-domain capabilities"],
        core_workflow=[str(item) for item in goal_spec.get("user_flows", [])],
        pages=[str(item).replace("_", " ") for item in goal_spec.get("interfaces", [])],
        modules=[str(item.get("id", "")) for item in project_plan.get("workstreams", []) if item.get("id") not in {"foundation", "delivery"}],
        stages=[str(item.get("id", "")) for item in project_plan.get("workstreams", [])],
        artifacts=[str(item) for item in project_plan.get("business_outputs", [])],
        match="It is derived directly from the canonical GoalSpec for the current user goal.",
        wrong="The plan requires revision if the user changes the stated capabilities, flows, entities, or constraints.",
        complexity_level="complex",
        customer_value_score=99,
        clarity_score=98,
        local_first_feasibility=96,
        delivery_feasibility=94,
        testability_score=98,
        implementation_risk="low",
        demo_degradation_risk="low",
        fake_pass_risk="low",
        acceptance_summary="; ".join(str(item) for item in goal_spec.get("acceptance_behaviors", [])),
        degraded_mode=False,
    ) | {"goal_spec": goal_spec, "project_plan": project_plan}


def goal_is_complex(raw_goal: str, context: dict[str, Any] | None = None) -> bool:
    lowered = raw_goal.lower()
    if context and str(context.get("reference_complexity_target", "")).strip():
        return True
    return any(token in lowered for token in ("complex", "production", "workbench", "pipeline", "gui", "cli", "artifact", "复杂", "工作台", "流程", "本地", "团队", "研究"))


def risk_penalty(value: str) -> int:
    return {"low": 0, "medium": 8, "high": 28}.get(str(value), 28)


def generate_need_interpretations(raw_goal: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    goal = str(raw_goal or "").strip()
    lowered = goal.lower()
    interpreted: list[dict[str, Any]] = []
    if goal_has_visual_novel_product(goal):
        interpreted.append(
            {
                "id": "visual_novel_authoring_need",
                "need": "A local visual-novel authoring studio for branching story editing, generated backgrounds and transparent character sprites, asset binding, preview, and export.",
                "customer_problem": "The creator needs story structure and visual assets to remain editable and connected instead of becoming unrelated generated files.",
                "target_user": "Visual-novel writers and small creative teams.",
                "evidence_from_goal": product_domain_goal(goal)[:600],
                "interpretation_notes": ["Offline procedural illustration may be an honestly labelled fallback when no diffusion model is configured."],
                "risk_if_wrong": "low",
            }
        )
    if goal_has_task_board_product(goal):
        interpreted.append(
            {
                "id": "task_board_need",
                "need": "A local task board for creating, moving, filtering, and persisting work items.",
                "customer_problem": "The customer needs a usable board workflow, while screenshots and demo video are delivery evidence rather than the product domain.",
                "target_user": "Individuals or small teams managing local tasks.",
                "evidence_from_goal": product_domain_goal(goal)[:600],
                "interpretation_notes": ["Local browser persistence is sufficient for the first version."],
                "risk_if_wrong": "low",
            }
        )
    if goal_has_media_product(goal):
        interpreted.append(
            {
                "id": "media_workflow_need",
                "need": "A local-first media workflow that turns raw files into traceable review/export artifacts.",
                "customer_problem": "The customer likely needs repeatable processing and review, not just a video player or static demo.",
                "target_user": "Editors, operators, or solo creators managing local media material.",
                "evidence_from_goal": goal[:600],
                "interpretation_notes": ["Local operation matters unless the customer explicitly asks for cloud processing."],
                "risk_if_wrong": "medium",
            }
        )
    if any(token in lowered for token in ("game", "studio", "team", "indie", "独立游戏", "团队", "项目管理")):
        interpreted.append(
            {
                "id": "team_management_need",
                "need": "A team operating system for planning work, tracking assets, decisions, risks, and release readiness.",
                "customer_problem": "The customer likely wants coordination and decision clarity, not a generic task board.",
                "target_user": "Small creative or engineering teams.",
                "evidence_from_goal": goal[:600],
                "interpretation_notes": ["The first version should focus on project coordination rather than full enterprise governance."],
                "risk_if_wrong": "medium",
            }
        )
    if any(token in lowered for token in ("research", "资料", "整理", "knowledge", "study", "文档", "工作台")):
        interpreted.append(
            {
                "id": "research_workspace_need",
                "need": "A local research workspace that imports materials, extracts notes, links evidence, and produces reviewable briefs.",
                "customer_problem": "The customer likely needs structured knowledge work with traceability.",
                "target_user": "Researchers, analysts, founders, or operators handling local documents.",
                "evidence_from_goal": goal[:600],
                "interpretation_notes": ["The first version can use deterministic local extraction and honest degraded mode."],
                "risk_if_wrong": "low",
            }
        )
    interpreted.append(
        {
            "id": "decision_clarity_need",
            "need": "A product that first clarifies the customer problem, scope, and acceptance criteria before implementation.",
            "customer_problem": "The raw goal may be underspecified and could otherwise collapse into a small demo.",
            "target_user": "The customer or internal operator who needs a clear first version.",
            "evidence_from_goal": goal[:600],
            "interpretation_notes": ["CGNK should choose a deliverable MVP and expose non-goals."],
            "risk_if_wrong": "low",
        }
    )
    return {"raw_goal": goal, "interpreted_needs": interpreted[:4]}


def _candidate(
    *,
    candidate_id: str,
    name: str,
    summary: str,
    target_user: str,
    core_problem: str,
    product_shape: str,
    mvp_features: list[str],
    non_goals: list[str],
    core_workflow: list[str],
    pages: list[str],
    modules: list[str],
    stages: list[str],
    artifacts: list[str],
    match: str,
    wrong: str,
    complexity_level: str,
    customer_value_score: int,
    clarity_score: int,
    local_first_feasibility: int,
    delivery_feasibility: int,
    testability_score: int,
    implementation_risk: str,
    demo_degradation_risk: str,
    fake_pass_risk: str,
    acceptance_summary: str,
    degraded_mode: bool = True,
) -> dict[str, Any]:
    return {
        "id": candidate_id,
        "name": name,
        "requirement_summary": summary,
        "target_user": target_user,
        "core_problem": core_problem,
        "product_shape": product_shape,
        "mvp_features": mvp_features,
        "non_goals": non_goals,
        "core_workflow": core_workflow,
        "likely_pages": pages,
        "likely_modules": modules,
        "pipeline_stages": stages,
        "expected_artifacts": artifacts,
        "why_it_matches_customer_goal": match,
        "why_it_might_be_wrong": wrong,
        "complexity_level": complexity_level,
        "customer_value_score": customer_value_score,
        "clarity_score": clarity_score,
        "local_first_feasibility": local_first_feasibility,
        "delivery_feasibility": delivery_feasibility,
        "testability_score": testability_score,
        "implementation_risk": implementation_risk,
        "demo_degradation_risk": demo_degradation_risk,
        "fake_pass_risk": fake_pass_risk,
        "acceptance_summary": acceptance_summary,
        "honest_degraded_mode_available": degraded_mode,
    }


def _small_demo_requirement() -> dict[str, Any]:
    return _candidate(
        candidate_id="single_static_page_demo_requirement",
        name="Single static page demo",
        summary="A one-page mockup with a few static cards.",
        target_user="A viewer of a prototype.",
        core_problem="Shows a rough visual idea but does not solve the operating workflow.",
        product_shape="Static preview only.",
        mvp_features=["Static cards"],
        non_goals=["Real workflow", "Artifacts", "Shared GUI/CLI core"],
        core_workflow=["open preview"],
        pages=["Home"],
        modules=["static_page"],
        stages=[],
        artifacts=[],
        match="It is fast and local.",
        wrong="It is too small and likely hides the real requirement.",
        complexity_level="small",
        customer_value_score=35,
        clarity_score=45,
        local_first_feasibility=98,
        delivery_feasibility=96,
        testability_score=30,
        implementation_risk="low",
        demo_degradation_risk="high",
        fake_pass_risk="high",
        acceptance_summary="A screenshot would exist, but it cannot validate the real customer workflow.",
    )


def _cloud_requirement() -> dict[str, Any]:
    return _candidate(
        candidate_id="cloud_ai_autopilot_requirement",
        name="Cloud AI autopilot requirement",
        summary="A fully automated cloud AI product using live model APIs, remote queues, and managed storage.",
        target_user="Teams with provisioned cloud AI infrastructure.",
        core_problem="Automation is attractive but risky when credentials and services are unknown.",
        product_shape="Cloud service dashboard.",
        mvp_features=["Cloud account setup", "Remote model jobs", "Remote storage", "Job monitor"],
        non_goals=[],
        core_workflow=["connect cloud", "submit remote job", "poll result"],
        pages=["Accounts", "Jobs", "Results"],
        modules=["cloud_client", "remote_jobs", "gui"],
        stages=["authenticate_cloud", "submit_model_jobs", "poll_remote_results"],
        artifacts=["remote_job_log.json"],
        match="It could fit an automation-heavy interpretation.",
        wrong="It depends on external accounts and is not safely deliverable as the first local version.",
        complexity_level="complex",
        customer_value_score=68,
        clarity_score=55,
        local_first_feasibility=30,
        delivery_feasibility=35,
        testability_score=40,
        implementation_risk="high",
        demo_degradation_risk="high",
        fake_pass_risk="high",
        acceptance_summary="Would require live external credentials and therefore cannot be honestly accepted by default.",
        degraded_mode=False,
    )


def generate_candidate_requirements(
    raw_goal: str,
    interpretations: dict[str, Any],
    context: dict[str, Any] | None = None,
    *,
    canonical_goal_spec: dict[str, Any] | None = None,
    canonical_project_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    goal_spec = dict(canonical_goal_spec or build_goal_spec(raw_goal))
    project_plan = dict(canonical_project_plan or build_goal_project_plan(goal_spec))
    if goal_spec.get("status") == "PASS" and project_plan.get("status") == "PASS":
        candidates.append(candidate_from_goal_spec(goal_spec, project_plan))
    # Keep only domain-neutral rejected alternatives. Domain-specific fixed candidates
    # must never leak into a different user's planning output.
    for candidate in (_cloud_requirement(), _small_demo_requirement()):
        if not any(existing["id"] == candidate["id"] for existing in candidates):
            candidates.append(candidate)
    unique_candidates: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    for candidate in candidates:
        candidate_id = str(candidate.get("id", ""))
        if not candidate_id or candidate_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(candidate_id)
        unique_candidates.append(candidate)
    return {
        "customer_goal": raw_goal,
        "generated_at": now(),
        "goal_spec": goal_spec,
        "project_plan": project_plan,
        "candidates": unique_candidates[:5],
    }


def rejection_reasons(candidate: dict[str, Any], *, complex_goal: bool = False) -> list[str]:
    reasons: list[str] = []
    if int(candidate.get("customer_value_score", 0)) < 50:
        reasons.append("customer_value_score_lt_50")
    if int(candidate.get("clarity_score", 0)) < 50:
        reasons.append("clarity_score_lt_50")
    if complex_goal and candidate.get("complexity_level") == "small":
        reasons.append("small_demo_for_complex_goal")
    if candidate.get("demo_degradation_risk") == "high":
        reasons.append("demo_degradation_risk_high")
    if candidate.get("fake_pass_risk") == "high":
        reasons.append("fake_pass_risk_high")
    if candidate.get("implementation_risk") == "high" and not candidate.get("honest_degraded_mode_available") and not candidate.get("non_goals"):
        reasons.append("high_implementation_risk_without_mvp_control")
    if not candidate.get("core_workflow"):
        reasons.append("core_workflow_missing")
    if not str(candidate.get("acceptance_summary", "")).strip():
        reasons.append("acceptance_summary_missing")
    return reasons


def score_total(candidate: dict[str, Any]) -> int:
    risk_control = 100 - min(70, risk_penalty(str(candidate.get("implementation_risk", "high"))) + risk_penalty(str(candidate.get("demo_degradation_risk", "high"))) + risk_penalty(str(candidate.get("fake_pass_risk", "high"))))
    complexity_fit = {"small": 35, "medium": 65, "complex": 85, "production_scale": 90}.get(str(candidate.get("complexity_level", "")), 50)
    mvp_focus = 80 if candidate.get("mvp_features") and candidate.get("non_goals") else 45
    score = (
        int(candidate.get("customer_value_score", 0)) * 0.22
        + int(candidate.get("clarity_score", 0)) * 0.16
        + complexity_fit * 0.14
        + int(candidate.get("local_first_feasibility", 0)) * 0.12
        + int(candidate.get("delivery_feasibility", 0)) * 0.14
        + int(candidate.get("testability_score", 0)) * 0.1
        + mvp_focus * 0.07
        + risk_control * 0.05
    )
    return max(0, min(100, round(score)))


def score_candidate_requirements(candidates: dict[str, Any] | list[dict[str, Any]], context: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_candidates = candidates.get("candidates", []) if isinstance(candidates, dict) else candidates
    complex_goal = bool((context or {}).get("complex_goal"))
    scores = []
    for candidate in raw_candidates if isinstance(raw_candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        reasons = rejection_reasons(candidate, complex_goal=complex_goal)
        total = score_total(candidate)
        selectable = (
            not reasons
            and int(candidate.get("customer_value_score", 0)) >= 70
            and int(candidate.get("clarity_score", 0)) >= 70
            and int(candidate.get("delivery_feasibility", 0)) >= 65
            and int(candidate.get("testability_score", 0)) >= 65
        )
        scores.append(
            {
                "candidate_id": candidate.get("id", ""),
                "candidate_name": candidate.get("name", ""),
                "total_score": total,
                "decision": "select" if selectable else "reject",
                "reason": "eligible_requirement_direction" if selectable else ", ".join(reasons or ["lower_score_or_weaker_fit"]),
                "customer_value_score": candidate.get("customer_value_score", 0),
                "clarity_score": candidate.get("clarity_score", 0),
                "complexity_fit": {"small": 35, "medium": 65, "complex": 85, "production_scale": 90}.get(str(candidate.get("complexity_level", "")), 50),
                "local_first_feasibility": candidate.get("local_first_feasibility", 0),
                "delivery_feasibility": candidate.get("delivery_feasibility", 0),
                "testability_score": candidate.get("testability_score", 0),
                "mvp_focus": 80 if candidate.get("mvp_features") and candidate.get("non_goals") else 45,
                "risk_control": 100 - min(70, risk_penalty(str(candidate.get("implementation_risk", "high"))) + risk_penalty(str(candidate.get("demo_degradation_risk", "high"))) + risk_penalty(str(candidate.get("fake_pass_risk", "high")))),
            }
        )
    return {
        "scoring_dimensions": [
            "customer_value_score",
            "clarity_score",
            "complexity_fit",
            "local_first_feasibility",
            "delivery_feasibility",
            "testability_score",
            "mvp_focus",
            "risk_control",
        ],
        "scores": scores,
    }


def select_requirement(candidates: dict[str, Any] | list[dict[str, Any]], scorecard: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_candidates = candidates.get("candidates", []) if isinstance(candidates, dict) else candidates
    by_id = {str(candidate.get("id", "")): candidate for candidate in raw_candidates if isinstance(candidate, dict)}
    eligible = [score for score in scorecard.get("scores", []) if isinstance(score, dict) and score.get("decision") == "select"]
    if not eligible:
        return {
            "status": "NEEDS_REWORK",
            "selected_requirement_id": "",
            "selected_requirement_name": "",
            "reason": "No candidate requirement satisfied value, clarity, feasibility, testability, and risk thresholds.",
        }
    best = sorted(eligible, key=lambda item: int(item.get("total_score", 0)), reverse=True)[0]
    candidate = by_id[str(best.get("candidate_id", ""))]
    rejected = [score for score in scorecard.get("scores", []) if isinstance(score, dict) and score.get("candidate_id") != candidate.get("id")]
    return {
        "selected_requirement_id": candidate["id"],
        "selected_requirement_name": candidate["name"],
        "customer_goal": candidates.get("customer_goal", "") if isinstance(candidates, dict) else "",
        "interpreted_need": candidate["requirement_summary"],
        "target_user": candidate["target_user"],
        "core_problem": candidate["core_problem"],
        "selected_product_shape": candidate["product_shape"],
        "why_this_requirement": [
            candidate["why_it_matches_customer_goal"],
            "It has enough value, clarity, delivery feasibility, testability, MVP boundaries, and risk control for a first build.",
        ],
        "why_not_other_requirements": [f"{item.get('candidate_id')}: {item.get('reason')}" for item in rejected],
        "mvp_scope": candidate["mvp_features"],
        "non_goals": candidate["non_goals"],
        "acceptance_summary": candidate["acceptance_summary"],
        "known_assumptions": list((candidate.get("goal_spec", {}) or {}).get("assumptions", [])),
        "open_questions_not_blocking": list((candidate.get("goal_spec", {}) or {}).get("open_questions", [])),
        "decision_confidence": "high" if int(best.get("total_score", 0)) >= 80 else "medium",
        "goal_spec": candidate.get("goal_spec", {}),
        "project_plan": candidate.get("project_plan", {}),
    }


def build_acceptance_contract(selected: dict[str, Any]) -> dict[str, Any]:
    goal_spec = selected.get("goal_spec", {}) if isinstance(selected.get("goal_spec"), dict) else {}
    project_plan = selected.get("project_plan", {}) if isinstance(selected.get("project_plan"), dict) else {}
    return {
        "contract_id": "requirement_acceptance_contract_v1",
        "selected_requirement_id": selected.get("selected_requirement_id", ""),
        "success_definition": selected.get("acceptance_summary", ""),
        "required_planning_docs": ["product_brief.md", "technical_plan.md", "interaction_design.md", "acceptance_matrix.md"],
        "required_requirement_artifacts": REQUIREMENT_ARTIFACTS,
        "required_product_outputs": [],
        "required_delivery_evidence": ["README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md", "run_dir"],
        "implementation_delivery_evidence": ["final_project_bundle.zip", "screenshot"],
        "acceptance_behaviors": list(goal_spec.get("acceptance_behaviors", [])),
        "test_intents": list(project_plan.get("test_intents", [])),
        "status_layers": STATUS_LAYERS,
        "forbidden_shortcuts": FORBIDDEN_SHORTCUTS,
    }


def customer_goal_brief(raw_goal: str, interpretations: dict[str, Any]) -> str:
    needs = interpretations.get("interpreted_needs", []) if isinstance(interpretations, dict) else []
    primary = needs[0] if needs else {}
    unknowns = interpretations.get("unknowns", []) if isinstance(interpretations, dict) else []
    lines = [
            "# Customer Goal Brief",
            "",
            f"Raw customer goal: {raw_goal}",
            "",
            f"CGNK interpretation: {primary.get('need', 'The customer needs a clearer product requirement before implementation.')}",
            "",
            "Known constraints:",
            "- Requirement decision must precede implementation.",
            "- Delivery success still requires evidence, not only a decision summary.",
            "",
            "Do not directly assume:",
            "- That a static demo is enough.",
            "- That cloud APIs or live models are available.",
            "- That generated code can pass without requirement alignment.",
            "",
            "CGNK autonomous decisions needed:",
            "- Choose the best first product requirement.",
            "- Freeze MVP scope, non-goals, and acceptance criteria.",
        ]
    if unknowns:
        lines[6:6] = ["Key uncertainties:", *[f"- {item}" for item in unknowns], ""]
    return "\n".join(lines) + "\n"


def rejected_markdown(candidates: list[dict[str, Any]], scorecard: dict[str, Any], selected_id: str) -> str:
    scores = {str(item.get("candidate_id", "")): item for item in scorecard.get("scores", []) if isinstance(item, dict)}
    lines = ["# Rejected Requirements", ""]
    for candidate in candidates:
        if candidate.get("id") == selected_id:
            continue
        score = scores.get(str(candidate.get("id", "")), {})
        lines.extend(
            [
                f"## {candidate.get('name', '')}",
                "",
                f"- id: `{candidate.get('id', '')}`",
                f"- reason: {score.get('reason', 'not selected')}",
                f"- risk type: implementation={candidate.get('implementation_risk')}, demo={candidate.get('demo_degradation_risk')}, fake_pass={candidate.get('fake_pass_risk')}",
                f"- future version: {'yes' if candidate.get('demo_degradation_risk') != 'high' and candidate.get('fake_pass_risk') != 'high' else 'no, unless reframed'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def mvp_scope_markdown(selected: dict[str, Any]) -> str:
    must = selected.get("mvp_scope", []) if isinstance(selected.get("mvp_scope"), list) else []
    return "\n".join(
        [
            "# MVP Scope",
            "",
            "## Must Do This Round",
            *[f"- {item}" for item in must[:4]],
            "",
            "## Should Do This Round",
            *[f"- {item}" for item in must[4:]],
            "",
            "## Not This Round",
            *[f"- {item}" for item in selected.get("non_goals", [])],
            "",
            "## Later Versions",
            "- Customer-specific integrations after the first requirement is validated.",
            "- Larger automation or cloud workflows after credentials and acceptance evidence are agreed.",
            "",
            "## Scope Rationale",
            "This scope preserves the selected requirement while keeping the first version testable and deliverable.",
        ]
    ) + "\n"


def non_goals_markdown(selected: dict[str, Any]) -> str:
    lines = ["# Non-Goals", ""]
    for item in selected.get("non_goals", []) if isinstance(selected.get("non_goals"), list) else []:
        lines.extend([f"## {item}", "", "- Reason: outside the selected MVP or too risky for first delivery.", "- Risk if forced now: larger dependency surface, weaker testing, and higher fake-pass risk.", ""])
    if len(lines) == 2:
        lines.extend(["- No explicit non-goals were selected; this should be reworked before implementation.", ""])
    return "\n".join(lines).rstrip() + "\n"


def customer_summary_markdown(selected: dict[str, Any], scorecard: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Customer Decision Summary",
            "",
            f"I understand your goal as: {selected.get('interpreted_need', '')}",
            "",
            "I compared multiple directions and selected:",
            f"- {selected.get('selected_requirement_name', '')}",
            "",
            "Why this requirement:",
            *[f"- {item}" for item in selected.get("why_this_requirement", [])],
            "",
            "MVP for this round:",
            *[f"- {item}" for item in selected.get("mvp_scope", [])],
            "",
            "Not doing this round:",
            *[f"- {item}" for item in selected.get("non_goals", [])],
            "",
            "Next step:",
            "- Use the selected requirement, MVP scope, non-goals, and acceptance contract as input to product design and implementation.",
            "",
            "If you disagree, the adjustable points are target user, workflow scope, non-goals, and acceptance criteria.",
        ]
    ) + "\n"


def write_requirement_decision_artifacts(result: dict[str, Any], run_dir: pathlib.Path) -> dict[str, str]:
    base = pathlib.Path(run_dir) / "requirement_decision"
    interpretations = result.get("need_interpretations", {})
    candidate_doc = result.get("candidate_requirements", {})
    candidates = candidate_doc.get("candidates", []) if isinstance(candidate_doc, dict) else []
    scorecard = result.get("requirement_scorecard", {})
    selected = result.get("selected_requirement", {})
    contract = result.get("acceptance_contract", {})
    goal_spec = result.get("goal_spec", {})
    project_plan = result.get("project_plan", {})
    paths = {
        "customer_goal_brief": str(base / "customer_goal_brief.md"),
        "goal_spec": str(base / "goal_spec.json"),
        "project_plan": str(base / "project_plan.json"),
        "need_interpretations": str(base / "need_interpretations.json"),
        "candidate_requirements": str(base / "candidate_requirements.json"),
        "requirement_scorecard": str(base / "requirement_scorecard.json"),
        "selected_requirement": str(base / "selected_requirement.json"),
        "rejected_requirements": str(base / "rejected_requirements.md"),
        "mvp_scope": str(base / "mvp_scope.md"),
        "non_goals": str(base / "non_goals.md"),
        "acceptance_contract": str(base / "acceptance_contract.json"),
        "customer_decision_summary": str(base / "customer_decision_summary.md"),
    }
    write_text(pathlib.Path(paths["customer_goal_brief"]), customer_goal_brief(str(result.get("raw_goal", "")), interpretations))
    write_json(pathlib.Path(paths["goal_spec"]), goal_spec)
    write_json(pathlib.Path(paths["project_plan"]), project_plan)
    write_json(pathlib.Path(paths["need_interpretations"]), interpretations)
    write_json(pathlib.Path(paths["candidate_requirements"]), candidate_doc)
    write_json(pathlib.Path(paths["requirement_scorecard"]), scorecard)
    write_json(pathlib.Path(paths["selected_requirement"]), selected)
    write_text(pathlib.Path(paths["rejected_requirements"]), rejected_markdown(candidates, scorecard, str(selected.get("selected_requirement_id", ""))))
    write_text(pathlib.Path(paths["mvp_scope"]), mvp_scope_markdown(selected))
    write_text(pathlib.Path(paths["non_goals"]), non_goals_markdown(selected))
    write_json(pathlib.Path(paths["acceptance_contract"]), contract)
    write_text(pathlib.Path(paths["customer_decision_summary"]), customer_summary_markdown(selected, scorecard))
    return paths


def load_requirement_acceptance_contract(run_dir: pathlib.Path) -> dict[str, Any]:
    return read_json(pathlib.Path(run_dir) / "requirement_decision" / "acceptance_contract.json")


def run_requirement_decision(raw_goal: str, run_dir: pathlib.Path, context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = dict(context or {})
    context.setdefault("complex_goal", goal_is_complex(raw_goal, context))
    planning_contract = (
        context.get("codex_capability_plan_contract", {})
        if isinstance(context.get("codex_capability_plan_contract", {}), dict)
        else {}
    )
    planning_artifact = (
        context.get("planning_artifact", {})
        if isinstance(context.get("planning_artifact", {}), dict)
        else {}
    )
    goal_spec = build_goal_spec(
        raw_goal,
        planning_contract,
        planning_artifact=planning_artifact or None,
        conversation_context=(
            context.get("conversation_context", {})
            if isinstance(context.get("conversation_context", {}), dict)
            else {}
        ),
        system_constraints=(
            [str(item) for item in context.get("system_constraints", [])]
            if isinstance(context.get("system_constraints", []), list)
            else []
        ) or None,
    )
    project_plan = build_goal_project_plan(goal_spec)
    interpretations = generate_need_interpretations(raw_goal, context)
    candidates = generate_candidate_requirements(
        raw_goal,
        interpretations,
        context,
        canonical_goal_spec=goal_spec,
        canonical_project_plan=project_plan,
    )
    if goal_spec.get("status") == "PASS" and project_plan.get("status") == "PASS":
        scorecard = score_candidate_requirements(candidates, context)
        selected = select_requirement(candidates, scorecard, context)
    else:
        scorecard = {"scores": [], "status": "NEEDS_REWORK", "reason": "INSUFFICIENT_GOAL_PLAN"}
        selected = {
            "status": "NEEDS_REWORK",
            "selected_requirement_id": "",
            "selected_requirement_name": "",
            "reason": "INSUFFICIENT_GOAL_PLAN",
            "goal_spec": goal_spec,
            "project_plan": project_plan,
        }
    status = "PASS" if selected.get("selected_requirement_id") else "NEEDS_REWORK"
    contract = build_acceptance_contract(selected) if status == "PASS" else {
        "contract_id": "requirement_acceptance_contract_v1",
        "status": "NEEDS_REWORK",
        "reason": selected.get("reason", "No selected requirement."),
        "status_layers": STATUS_LAYERS,
        "forbidden_shortcuts": FORBIDDEN_SHORTCUTS,
    }
    product_design_governance: dict[str, Any] = {}
    if status == "PASS":
        product_design_governance = product_design_depth_governance.freeze_preimplementation_governance(
            raw_goal,
            goal_spec,
            project_plan,
            pathlib.Path(run_dir) / "requirement_decision" / "product_design_governance",
            proposed_components=[
                str(item.get("name") or item.get("id") or item)
                if isinstance(item, dict)
                else str(item)
                for item in project_plan.get("workstreams", [])
            ],
            declared_proxy=bool(context.get("declared_proxy_solution", False)),
            frozen_resource_hashes=(
                [str(item) for item in context.get("preimplementation_test_resource_hashes", [])]
                if isinstance(context.get("preimplementation_test_resource_hashes"), list)
                else []
            ),
        )
        contract["product_design_depth_governance"] = {
            "schema_version": product_design_governance["schema_version"],
            "review_verdict": product_design_governance["review_verdict"],
            "maturity_ceiling": product_design_governance["maturity_ceiling"],
            "artifact_paths": product_design_governance["paths"],
            "frozen_before_implementation": True,
        }
        if not product_design_governance["ready_to_implement"]:
            status = "NEEDS_REWORK"
    result = {
        "status": status,
        "ready_to_generate": status == "PASS" and bool(goal_spec.get("ready_to_generate", True)),
        "raw_goal": raw_goal,
        "goal_spec": goal_spec,
        "project_plan": project_plan,
        "need_interpretations": interpretations,
        "candidate_requirements": candidates,
        "requirement_scorecard": scorecard,
        "selected_requirement": selected,
        "acceptance_contract": contract,
        "product_design_governance": product_design_governance,
    }
    if goal_spec.get("status") != "PASS" and goal_spec.get("compiler_version"):
        result["requirement_replan"] = canonical_goal_spec_compiler.requirement_replan_feedback(goal_spec)
    result["paths"] = write_requirement_decision_artifacts(result, pathlib.Path(run_dir))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_requirement_decision(args.goal, pathlib.Path(args.run_dir))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"REQUIREMENT_DECISION: {result['status']}")
        print(f"requirement_decision_dir={pathlib.Path(args.run_dir).resolve() / 'requirement_decision'}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
