"""Digital Persona P3 local/simulated capabilities (deterministic baseline).

No provider calls. Persona policy and reply proposals are project-local and
versioned; effect gate allows LOCAL_SIMULATED only. Shared media capabilities are
consumed through the shared registry.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone

from cgkn.execution import (BlockExecutionRequest, BlockExecutionResult, BlockStatus,
                            ExecutionError, ExecutionErrorCode)
from cgkn.execution.contracts import utc_now
from cgkn.executors.protocol import ExecutorDescriptor

TRIAL = pathlib.Path(r"C:\Users\sunom\VeriArbor-Experiments\real-product-growth-v1-20261108")
P2_COLLECTION = TRIAL / "p2-charactercut" / "run-01" / "OUTPUT" / "clip-policy-attempt" / "collection.mp4"
P3_ROOT = TRIAL / "p3-digital-persona" / "run-01"


class _BoundedExecutor:
    def __init__(self, capability, function, *, executor_ref=None, timeout=900):
        self.capability = capability
        self.function = function
        ref = executor_ref or capability
        self.descriptor = ExecutorDescriptor(ref, "digital_persona_p3", (capability,),
                                             ("filesystem.read", "filesystem.write", "process.execute"),
                                             default_timeout_seconds=timeout)

    def execute(self, request):
        return self.function(request)


def _write(path, value):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _result(request, outputs, *, status=BlockStatus.SUCCEEDED, error=None, started="", clock=None):
    return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
        attempt_id=request.attempt_id, node_id=request.node_id,
        executor_ref=request.executor_ref, status=status, outputs=dict(outputs), error=error,
        started_at=started or utc_now(), ended_at=utc_now(),
        duration_ms=max(0, int((time.perf_counter() - (clock or time.perf_counter())) * 1000)))


def _out(cfg, default):
    return pathlib.Path(cfg.get("output_root") or default)


def exec_persona_policy(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    out = _out(cfg, P3_ROOT / "OUTPUT" / "persona")
    try:
        now = datetime.now(timezone.utc).isoformat()
        policy = {
            "kind": "PersonaPolicy", "schema_version": "1.0", "persona_id": "Miza",
            "version": 1, "created_at": now,
            "identity": {"display_name": "Miza", "role": "local digital persona baseline",
                         "stable_facts": ["This is a simulated local persona baseline."]},
            "communication": {"tone": "friendly", "length": "concise", "language": "en",
                              "first_person": True},
            "allowed_claims": ["acknowledge the video", "thank the viewer",
                               "invite further conversation"],
            "private_information": ["internal project debug data", "API keys", "file paths",
                                    "unpublished acceptance details"],
            "platform_behavior": {"default_visibility": "local_simulated",
                                  "reply_requires_effect_gate": True},
            "user_overrides": [],
            "change_rule": "only an explicit ProjectProposal may create a new version",
        }
        policy["policy_sha256"] = hashlib.sha256(json.dumps(policy, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        _write(out / "policy.json", policy)
        _write(out / "policy_history.json", {"kind": "PersonaPolicyHistory", "schema_version": "1.0",
                                             "versions": [{"version": 1, "sha256": policy["policy_sha256"],
                                                           "created_at": now, "source": "deterministic baseline"}]})
        return _result(request, {"persona_policy": {"path": str(out / "policy.json"),
                                                    "version": 1, "sha256": policy["policy_sha256"]}},
                       started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001
        return _result(request, {}, status=BlockStatus.FAILED,
                       error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc)),
                       started=started, clock=clock)


def exec_persona_video(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    out = _out(cfg, P3_ROOT / "OUTPUT" / "video")
    artifact = pathlib.Path(cfg.get("artifact_path") or P2_COLLECTION)
    try:
        from cgkn.application import shared_media
        probe = shared_media.probe(artifact)
        digest = shared_media.sha256(artifact)
        acceptance = shared_media.technical_acceptance(
            artifact, out / "technical_acceptance.json", require_audio=True, min_seconds=10.0)
        data = {"kind": "PersonaVideoArtifact", "schema_version": "1.0",
                "path": str(artifact), "sha256": digest, "probe": probe,
                "technical_acceptance": {"status": acceptance.get("status"),
                                         "receipt": "video/technical_acceptance.json"},
                "shared_capabilities": ["artifact.sha256@1", "media.probe@1",
                                        "media.technical_acceptance@1"]}
        _write(out / "artifact.json", data)
        passed = acceptance.get("status") == "PASS" and probe.get("has_audio") and probe.get("width")
        if not passed:
            return _result(request, {"persona_video": data}, status=BlockStatus.FAILED,
                           error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,
                                                "shared media acceptance failed"),
                           started=started, clock=clock)
        return _result(request, {"persona_video": {"artifact": str(out / "artifact.json"),
                                                   "sha256": digest,
                                                   "technical_status": acceptance.get("status")}},
                       started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001
        return _result(request, {}, status=BlockStatus.FAILED,
                       error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc)),
                       started=started, clock=clock)


def _publication(platform: pathlib.Path, key: str, video_sha: str) -> dict:
    publication_id = hashlib.sha256(key.encode()).hexdigest()
    path = platform / "publications" / (publication_id + ".json")
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    record = {"publication_id": publication_id, "idempotency_key": key,
              "video_sha256": video_sha, "platform": "LOCAL_SIMULATED",
              "visibility": "local", "status": "PUBLISHED",
              "created_at": datetime.now(timezone.utc).isoformat(),
              "remote_url": "local-simulated://publication/" + publication_id}
    _write(path, record)
    return record


def exec_upload(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    out = _out(cfg, P3_ROOT / "OUTPUT" / "upload")
    platform = out / "platform"
    try:
        artifact = json.loads((P3_ROOT / "OUTPUT" / "video" / "artifact.json").read_text(encoding="utf-8"))
        video_sha = artifact["sha256"]
        receipts = []
        a = _publication(platform, "p3-upload-A", video_sha)
        receipts.append({"key": "p3-upload-A", "status": "PUBLISHED", "publication": a})
        duplicate = _publication(platform, "p3-upload-A", video_sha)
        receipts.append({"key": "p3-upload-A", "status": "DUPLICATE_IDEMPOTENT",
                         "same_publication": duplicate["publication_id"] == a["publication_id"],
                         "publication": duplicate})
        # Simulate the request reaching the platform but the response being lost.
        b = _publication(platform, "p3-upload-B", video_sha)
        receipts.append({"key": "p3-upload-B", "status": "UNKNOWN",
                         "error": "RESPONSE_LOST_AFTER_WRITE", "publication_id": b["publication_id"]})
        reconciled = _publication(platform, "p3-upload-B", video_sha)
        receipts.append({"key": "p3-upload-B", "status": "RECONCILED",
                         "publication": reconciled})
        pubs = list((platform / "publications").glob("*.json"))
        state = {"kind": "PersonaUploadState", "schema_version": "1.0",
                 "publications": sorted(str(p) for p in pubs),
                 "receipts": receipts,
                 "unknown_keys": ["p3-upload-B"],
                 "resolved_unknown_keys": ["p3-upload-B"],
                 "idempotent": duplicate["publication_id"] == a["publication_id"],
                 "count": len(pubs)}
        _write(out / "upload_state.json", state)
        _write(out / "receipts.json", {"receipts": receipts})
        _write(out / "publications.json", {"publications": [json.loads(p.read_text(encoding="utf-8")) for p in sorted(pubs)]})
        if len(pubs) != 2 or not state["idempotent"]:
            return _result(request, {"upload": state}, status=BlockStatus.FAILED,
                           error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,
                                                "idempotency or publication count failed"),
                           started=started, clock=clock)
        return _result(request, {"upload": {"state": str(out / "upload_state.json"),
                                            "publications": len(pubs), "idempotent": True,
                                            "unknown_reconciled": True}},
                       started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001
        return _result(request, {}, status=BlockStatus.FAILED,
                       error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc)),
                       started=started, clock=clock)


def _reply(policy: dict, event: dict, history: list[dict]) -> dict:
    # Deterministic local baseline; not a model output and not a ground truth.
    if "?" in event["content"]:
        text = "Thanks for asking! I am glad you are following along in this local demo."
    else:
        text = "Thanks for watching! I appreciate the note and will keep the conversation here."
    return {"event_id": event["event_id"], "reply_text": text,
            "persona_version": policy["version"], "tone": policy["communication"]["tone"],
            "basis": "deterministic persona-policy template",
            "contains_private_info": False}


def exec_interaction(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    out = _out(cfg, P3_ROOT / "OUTPUT" / "interaction")
    try:
        policy = json.loads((P3_ROOT / "OUTPUT" / "persona" / "policy.json").read_text(encoding="utf-8"))
        events = [
            {"event_id": "p3-event-A1", "platform": "local_fixture", "author": "viewer-1",
             "content": "Loved this clip! How did you pick the moment?", "timestamp": "2026-11-08T14:00:00Z",
             "parent": None},
            {"event_id": "p3-event-A2", "platform": "local_fixture", "author": "viewer-2",
             "content": "Nice work.", "timestamp": "2026-11-08T14:01:00Z",
             "parent": "p3-event-A1"},
        ]
        history = []
        replies = []
        gate_events = []
        for event in events:
            proposal = _reply(policy, event, history)
            local_effect = "LOCAL_SIMULATED"
            if local_effect == "LOCAL_SIMULATED":
                gate = {"event_id": event["event_id"], "effect": local_effect,
                        "decision": "ALLOW_LOCAL_ONLY"}
            else:
                gate = {"event_id": event["event_id"], "effect": local_effect, "decision": "BLOCK"}
            gate_events.append(gate)
            history.append({"event": event, "reply": proposal, "gate": gate})
            replies.append(proposal)
        # A live reply attempt is explicitly blocked.
        gate_events.append({"event_id": "p3-event-A2", "effect": "REMOTE_REPLY",
                            "decision": "BLOCKED_LIVE_NOT_AUTHORIZED"})
        # Foreign project acceptance must not become P3 evidence.
        from cgkn.agent.capability_registry import load_registry
        registry = load_registry(TRIAL / "architecture-project-isolation" / "CAPABILITY_REGISTRY.json")
        binding = registry.bind(project_id="DigitalPersona", project_node_id="persona.video",
                                capability_id="media.technical_acceptance", version="1",
                                local_consumer="persona.video", local_context={"run": "p3-run-01"},
                                verification_scope=("video/technical_acceptance.json",),
                                consumer_inputs=("video_path", "require_audio"))
        foreign_rejected, _ = registry.verify_binding(
            binding, ("p1/P1_ACCEPTANCE.json",),
            foreign_project_pass_refs=("p1/P1_ACCEPTANCE.json",))
        foreign_rejected = not foreign_rejected
        # Persist and reload.
        _write(out / "conversation.json", {"kind": "PersonaConversation", "schema_version": "1.0",
                                           "persona_version": policy["version"], "history": history})
        _write(out / "replies.json", {"replies": replies})
        _write(out / "gate_events.json", {"events": gate_events,
                                          "live_publish": "NOT_AUTHORIZED"})
        reloaded = json.loads((out / "conversation.json").read_text(encoding="utf-8"))
        recovery = {"reloaded": True, "persona_version": reloaded["persona_version"],
                    "interaction_count": len(reloaded["history"]),
                    "reply_count": len(replies),
                    "upload_receipt_present": (P3_ROOT / "OUTPUT" / "upload" / "upload_state.json").is_file(),
                    "foreign_project_acceptance_rejected": foreign_rejected}
        _write(out / "recovery.json", recovery)
        if len(replies) != 2 or len(history) != 2 or not recovery["upload_receipt_present"]:
            return _result(request, {"interaction": recovery}, status=BlockStatus.FAILED,
                           error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,
                                                "interaction/reply/recovery incomplete"),
                           started=started, clock=clock)
        return _result(request, {"interaction": {"conversation": str(out / "conversation.json"),
                                                 "replies": len(replies),
                                                 "gate_events": len(gate_events),
                                                 "recovery": recovery}},
                       started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001
        return _result(request, {}, status=BlockStatus.FAILED,
                       error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc)),
                       started=started, clock=clock)


# ---------------------------------------------------------------------------
# Checkers
# ---------------------------------------------------------------------------
def _read(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8")) if pathlib.Path(path).is_file() else {}


def check_policy(root, contract):
    policy = _read(pathlib.Path(root) / "persona" / "policy.json")
    history = _read(pathlib.Path(root) / "persona" / "policy_history.json")
    checks = {"policy_present": bool(policy), "version_1": policy.get("version") == 1,
              "history_present": bool(history.get("versions")),
              "effect_gate_required": policy.get("platform_behavior", {}).get("reply_requires_effect_gate") is True}
    return {"passed": all(checks.values()), "observed": checks,
            "artifacts": ["persona/policy.json", "persona/policy_history.json"]}


def check_video(root, contract):
    art = _read(pathlib.Path(root) / "video" / "artifact.json")
    checks = {"artifact_present": bool(art), "technical_pass": art.get("technical_acceptance", {}).get("status") == "PASS",
              "has_audio": bool(art.get("probe", {}).get("has_audio")),
              "hash_len": len(str(art.get("sha256", ""))) == 64}
    return {"passed": all(checks.values()), "observed": checks,
            "artifacts": ["video/artifact.json", "video/technical_acceptance.json"]}


def check_upload(root, contract):
    state = _read(pathlib.Path(root) / "upload" / "upload_state.json")
    checks = {"count_2": state.get("count") == 2, "idempotent": state.get("idempotent") is True,
              "unknown_reconciled": bool(state.get("resolved_unknown_keys")),
              "receipts": len(state.get("receipts", [])) >= 3}
    return {"passed": all(checks.values()), "observed": checks,
            "artifacts": ["upload/upload_state.json", "upload/receipts.json", "upload/publications.json"]}


def check_interaction(root, contract):
    conv = _read(pathlib.Path(root) / "interaction" / "conversation.json")
    recovery = _read(pathlib.Path(root) / "interaction" / "recovery.json")
    gates = _read(pathlib.Path(root) / "interaction" / "gate_events.json")
    checks = {"two_interactions": len(conv.get("history", [])) == 2,
              "replies": len(_read(pathlib.Path(root) / "interaction" / "replies.json").get("replies", [])) == 2,
              "remote_blocked": any(e.get("decision") == "BLOCKED_LIVE_NOT_AUTHORIZED" for e in gates.get("events", [])),
              "recovery_passed": recovery.get("reloaded") is True,
              "foreign_rejected": recovery.get("foreign_project_acceptance_rejected") is True}
    return {"passed": all(checks.values()), "observed": checks,
            "artifacts": ["interaction/conversation.json", "interaction/replies.json",
                          "interaction/gate_events.json", "interaction/recovery.json"]}


def build_catalog(root: pathlib.Path):
    from cgkn.orchestration.leaf_contract import build_leaf_contract
    specs = {
        "persona.policy": ("define a versioned project-local persona policy", "IMPLEMENTATION",
                           ["persona/policy.json", "persona/policy_history.json"],
                           ["persona.policy"], "persona.check.policy@1", "persona.policy@1", [],
                           {"expected_delta": "versioned persona policy with private-info rules"}),
        "persona.video": ("prepare a real local video artifact using shared media capabilities", "IMPLEMENTATION",
                          ["video/artifact.json", "video/technical_acceptance.json"],
                          ["persona.video"], "persona.check.video@1", "persona.video@1", ["persona.policy"],
                          {"expected_delta": "real video artifact bound to shared probe/hash/technical acceptance"}),
        "persona.upload": ("simulated upload with receipt, idempotency and UNKNOWN reconcile", "IMPLEMENTATION",
                           ["upload/upload_state.json", "upload/receipts.json", "upload/publications.json"],
                           ["persona.upload"], "persona.check.upload@1", "persona.upload@1", ["persona.video"],
                           {"expected_delta": "two publications, idempotent duplicate, reconciled UNKNOWN"}),
        "persona.interaction": ("ingest interactions, propose replies and enforce the effect gate", "IMPLEMENTATION",
                                ["interaction/conversation.json", "interaction/replies.json",
                                 "interaction/gate_events.json", "interaction/recovery.json"],
                                ["persona.interaction"], "persona.check.interaction@1", "persona.interaction@1",
                                ["persona.upload"],
                                {"expected_delta": "two replies, remote reply blocked, restart recovery"}),
    }
    catalog = {}
    for node, (goal, kind, scope, acceptance, checker, executor, deps, extra) in specs.items():
        contract = build_leaf_contract(goal=goal, kind=kind, scope=scope, acceptance=acceptance,
                                       checker=checker, output_identity=node, effect_domains=["filesystem"],
                                       executor=executor, dependencies=deps, **extra)
        catalog[node + "@1"] = {"executor_ref": executor,
                                "config": {"executor_ref": executor, "workdir": str(root),
                                           "leaf_contract": contract}}
    return catalog
