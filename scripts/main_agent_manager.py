#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

try:
    from . import local_conversation_manager
    from . import local_repo_manager
    from . import model_policy
    from . import project_revision_lane
except ImportError:  # pragma: no cover - script execution path
    import local_conversation_manager  # type: ignore
    import local_repo_manager  # type: ignore
    import model_policy  # type: ignore
    import project_revision_lane  # type: ignore

try:
    from . import frontdesk_team_lead_agent
except ImportError:  # pragma: no cover - script execution path
    import frontdesk_team_lead_agent  # type: ignore


NEW_PROJECT_TERMS = ("新项目", "重新做一个不同项目", "另做一个", "开新项目", "不要沿用上次", "从零开始")
ROLLBACK_TERMS = ("回滚", "退回", "恢复到")
REPAIR_TERMS = ("修复", "重试", "再试")
POLICY_PATH = pathlib.Path(__file__).resolve().parents[1] / "config" / "customer_agent_policy.md"


def looks_like_status_query(text: str) -> bool:
    compact = re.sub(r"[\s,.!?。！？~～]+", "", str(text or "").lower())
    exact = {
        "状态",
        "当前状态",
        "现在状态",
        "进度",
        "进度怎么样",
        "现在怎么样了",
        "好了没",
        "还在做吗",
        "status",
    }
    if compact in exact:
        return True
    question_markers = ("吗", "怎么样", "怎样", "好了没", "到哪", "有没有结果")
    status_markers = ("状态", "进度", "还在做", "还在跑", "结果")
    return any(marker in compact for marker in status_markers) and any(marker in compact for marker in question_markers)


class MainAgentManager:
    def handle_user_turn(
        self,
        conversation_id: str,
        text: str,
        source: str = "local",
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        conversation = local_conversation_manager.load_conversation(conversation_id)
        conversation["source"] = source
        local_conversation_manager.append_user_message(conversation, text, source, attachments)
        self.record_correction_if_needed(conversation, text)
        intent = self.classify_intent(conversation, text)
        result = self.route_intent(conversation, intent)
        self.attach_team_lead_reply(conversation, result, text)
        local_conversation_manager.save_conversation(conversation)
        result["conversation"] = local_conversation_manager.conversation_summary(conversation)
        return result

    def record_correction_if_needed(self, conversation: dict[str, Any], text: str) -> None:
        if not frontdesk_team_lead_agent.is_correction(text):
            return
        local_conversation_manager.update_whiteboard(
            conversation,
            {
                "change_requests": [f"用户纠正: {text}"],
                "known_facts": [f"按用户纠正更新: {text}"],
                "decision_log": ["用户纠正优先于此前推断，后续回复先承认修正再推进。"],
            },
            "user_correction",
        )

    def attach_team_lead_reply(self, conversation: dict[str, Any], result: dict[str, Any], latest_text: str) -> None:
        whiteboard = conversation.get("whiteboard", {}) if isinstance(conversation.get("whiteboard"), dict) else {}
        generation = conversation.get("generation", {}) if isinstance(conversation.get("generation"), dict) else {}
        active = local_conversation_manager.get_active_project(conversation)
        evidence = self.delivery_evidence_for_local(active, generation)
        known_limits = frontdesk_team_lead_agent.known_limits_from_context(whiteboard, generation, evidence)
        context = frontdesk_team_lead_agent.build_context(
            latest_user_message=latest_text,
            conversation_history_summary=frontdesk_team_lead_agent.conversation_history_summary(
                conversation.get("messages", []) if isinstance(conversation.get("messages"), list) else []
            ),
            whiteboard=whiteboard,
            active_run=conversation.get("active_run", {}) if isinstance(conversation.get("active_run"), dict) else {},
            generation_status=generation,
            delivery_evidence=evidence,
            known_limits=known_limits,
            customer_agent_policy=self.read_customer_agent_policy(),
            draft_reply=str(result.get("message") or result.get("status") or ""),
            event=str(result.get("intent") or ""),
        )
        structured = frontdesk_team_lead_agent.compose_reply(context)
        result["user_visible_reply"] = structured["reply"]
        result["reply_intent"] = structured["reply_intent"]
        result["visible_status"] = structured["visible_status"]
        result["next_user_options"] = structured["next_user_options"]
        local_conversation_manager.append_assistant_message(
            conversation,
            structured["reply"],
            event=str(result.get("intent") or "team_lead_reply"),
            source="frontdesk_team_lead_agent",
        )

    def delivery_evidence_for_local(self, active: dict[str, Any], generation: dict[str, Any]) -> dict[str, Any]:
        refs: dict[str, str] = {}
        for key in ("latest_project_package", "package_path"):
            value = str(active.get(key) or generation.get(key) or "").strip()
            if value:
                refs["package"] = value
        for key in ("latest_delivery_manifest", "delivery_manifest"):
            value = str(active.get(key) or generation.get(key) or "").strip()
            if value:
                refs["delivery_manifest"] = value
        delivery_ready = bool(refs.get("package") and refs.get("delivery_manifest"))
        missing: list[str] = []
        if str(generation.get("status", "")).lower() in {"ready", "ready_with_warnings", "delivered"}:
            if "package" not in refs:
                missing.append("package")
            if "delivery_manifest" not in refs:
                missing.append("delivery_manifest")
        return {"delivery_ready": delivery_ready, "refs": refs, "missing": missing}

    def read_customer_agent_policy(self) -> str:
        try:
            text = POLICY_PATH.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            return ""
        return text[:12000]

    def classify_intent(self, conversation: dict[str, Any], text: str) -> dict[str, Any]:
        stripped = str(text or "").strip()
        compact = stripped.lower().replace(" ", "")
        if any(term in stripped for term in NEW_PROJECT_TERMS):
            intent = "new_project_request"
            reason = "explicit_new_project"
        elif any(term in stripped for term in ROLLBACK_TERMS):
            intent = "rollback_request"
            reason = "rollback_terms"
        elif project_revision_lane.is_revision_request(stripped, conversation):
            intent = "project_revision_request"
            reason = "active_project_revision_terms"
        elif any(term in stripped for term in REPAIR_TERMS) and project_revision_lane.has_active_project(conversation):
            intent = "project_revision_request"
            reason = "repair_on_active_project"
        elif looks_like_status_query(stripped):
            intent = "status_query"
            reason = "status_query"
        elif not conversation.get("messages") or len([m for m in conversation.get("messages", []) if isinstance(m, dict) and m.get("role") == "user"]) <= 1:
            intent = "new_project_request"
            reason = "first_substantive_turn"
        elif "review" in compact or "检查" in stripped:
            intent = "review_request"
            reason = "review_terms"
        else:
            intent = "project_update"
            reason = "continuing_project_context"
        return {"kind": "MainAgentIntent", "intent": intent, "text": stripped, "reason": reason}

    def route_intent(self, conversation: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        name = str(intent.get("intent", ""))
        if name == "new_project_request":
            return self.start_new_project(conversation, str(intent.get("text", "")))
        if name == "project_revision_request":
            return self.start_project_revision(conversation, str(intent.get("text", "")))
        if name == "status_query":
            return self.get_status(conversation)
        if name == "review_request":
            return self.request_review(conversation)
        if name == "rollback_request":
            active = local_conversation_manager.get_active_project(conversation)
            return self.rollback_project(conversation, int(active.get("revision_index", 0)))
        if name == "repair_request":
            return self.request_repair(conversation, "user_requested_repair")
        return {"status": "recorded", "intent": name, "message": "Project update recorded for the active conversation."}

    def start_new_project(self, conversation: dict[str, Any], text: str) -> dict[str, Any]:
        local_conversation_manager.update_whiteboard(
            conversation,
            {
                "project_summary": text,
                "known_facts": [text],
                "decision_log": ["MainAgentManager accepted a new project request for the provider generation route."],
                "ready_to_generate": True,
            },
            "new_project_request",
        )
        conversation["generation"] = {
            "status": "intake_open",
            "driver": "main_agent_manager",
            "provider_route_required": True,
            "delivery_contract": ["local_packager", "public_delivery_gate", "delivery_manifest"],
        }
        local_conversation_manager.append_assistant_message(
            conversation,
            "New project request recorded; formal generation must be delegated to the reviewed provider route.",
            event="new_project_recorded",
        )
        return {
            "status": "accepted",
            "intent": "new_project_request",
            "model": self.choose_model("provider_generation"),
            "provider_route_required": True,
        }

    def start_project_revision(self, conversation: dict[str, Any], text: str) -> dict[str, Any]:
        revision_request = project_revision_lane.create_revision_request(conversation, text)
        revision_plan = project_revision_lane.create_revision_plan(conversation, revision_request)
        workspace = project_revision_lane.prepare_revision_workspace(conversation, revision_request)
        goal = project_revision_lane.build_revision_goal(conversation, revision_request, revision_plan)
        manifest = project_revision_lane.create_revision_manifest(conversation, revision_request, revision_plan, workspace)
        manifest["status"] = "workspace_ready"
        manifest["revision_goal"] = goal
        manifest_path = project_revision_lane.write_revision_manifest(manifest)
        conversation["generation"] = {
            "status": "revision_planning",
            "driver": "main_agent_manager",
            "revision_manifest": str(manifest_path),
            "provider_route_required": True,
            "delivery_contract": ["local_packager", "public_delivery_gate", "delivery_manifest"],
        }
        local_conversation_manager.append_assistant_message(
            conversation,
            "Revision request prepared; formal revision generation must use the provider route and delivery contract.",
            event="revision_prepared",
        )
        return {
            "status": "revision_prepared",
            "intent": "project_revision_request",
            "model": self.choose_model("revision"),
            "revision_manifest": str(manifest_path),
            "revision_goal": goal,
        }

    def execute_project_revision(
        self,
        conversation: dict[str, Any],
        revision_manifest_path: str,
        execution_adapters: dict[str, Any],
    ) -> dict[str, Any]:
        manifest_path = pathlib.Path(str(revision_manifest_path))
        if not manifest_path.exists():
            return {"status": "blocked", "intent": "project_revision_execute", "reason": "revision_manifest_not_found"}
        try:
            revision_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"status": "blocked", "intent": "project_revision_execute", "reason": f"revision_manifest_unreadable: {exc}"}
        if not isinstance(revision_manifest, dict):
            return {"status": "blocked", "intent": "project_revision_execute", "reason": "revision_manifest_not_object"}

        conversation["generation"] = {
            "status": "revision_generating",
            "driver": "main_agent_manager",
            "revision_manifest": str(manifest_path),
            "provider_route_required": True,
            "delivery_contract": ["provider_route", "local_packager", "public_delivery_gate", "delivery_manifest"],
        }
        result = project_revision_lane.run_provider_revision_job(
            conversation=conversation,
            revision_manifest=revision_manifest,
            provider_execute=execution_adapters.get("provider_execute"),
            post_build_finalize=execution_adapters.get("post_build_finalize"),
            package_project=execution_adapters.get("package_project"),
            evaluate_public_delivery_gate=execution_adapters.get("evaluate_public_delivery_gate"),
            model=str(execution_adapters.get("model") or self.choose_model("revision")),
            timeout=int(execution_adapters.get("timeout", 420)),
        )
        conversation["generation"].update(
            {
                "status": "revision_delivered" if result.get("status") == "ready" else "rework_blocked",
                "revision_manifest": result.get("revision_manifest", str(manifest_path)),
                "package_path": result.get("package_path", ""),
                "delivery_manifest": result.get("delivery_manifest", ""),
                "public_delivery_gate": result.get("public_delivery_gate", {}),
                "error": result.get("error", ""),
            }
        )
        local_conversation_manager.save_conversation(conversation)
        return result

    def get_status(self, conversation: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "ok",
            "intent": "status_query",
            "summary": local_conversation_manager.conversation_summary(conversation),
        }

    def request_review(self, conversation: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "review_requested",
            "intent": "review_request",
            "model": self.choose_model("review"),
            "active_project": local_conversation_manager.get_active_project(conversation),
        }

    def request_repair(self, conversation: dict[str, Any], reason: str) -> dict[str, Any]:
        conversation["generation"] = {"status": "repair_requested", "reason": reason}
        return {"status": "repair_requested", "intent": "repair_request", "model": self.choose_model("repair")}

    def rollback_project(self, conversation: dict[str, Any], revision_index: int) -> dict[str, Any]:
        active = local_conversation_manager.get_active_project(conversation)
        project_id = str(active.get("project_id", ""))
        if not project_id:
            return {"status": "blocked", "intent": "rollback_request", "reason": "active_project_required"}
        metadata = local_repo_manager.rollback_to_revision(project_id, revision_index)
        active["revision_index"] = int(metadata.get("current_revision", revision_index))
        active["current_worktree"] = str(local_repo_manager.current_worktree(project_id).resolve())
        active["status"] = "rolled_back"
        local_conversation_manager.bind_active_project(conversation, active)
        return {"status": "rolled_back", "intent": "rollback_request", "project_id": project_id, "revision_index": revision_index}

    def choose_model(self, task: str) -> str:
        return model_policy.select_model(task)


def bind_initial_project_delivery(
    conversation: dict[str, Any],
    project_dir: str,
    package_path: str = "",
    delivery_manifest: str = "",
) -> dict[str, Any]:
    return project_revision_lane.bind_initial_project_delivery(conversation, project_dir, package_path, delivery_manifest)
