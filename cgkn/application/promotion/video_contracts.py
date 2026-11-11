from __future__ import annotations

"""Canonical S0 video contract and deterministic preflight.

AUTHORITY: PUBLISH_EFFECTS / PUBLISH_EFFECTS_SCHEMA in this module.
DERIVED: video_delegation.PLAN_SCHEMA, PLAN_INSTRUCTIONS and validate_plan.
COMPATIBILITY: RESULT_KEY_ALIASES maps canonical node ids to the short keys used
by legacy consumer code. Node identity itself has no alias: n_gui is never
accepted as video.gui.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from cgkn.runtime import DAGRunner

PUBLISH_EFFECTS = {
    "target": "LOCAL_SIMULATED",
    "external_network_post": False,
    "external_account_mutation": False,
    "credential_use": False,
    "side_effect_scope": "LOCAL_ONLY",
    "simulation_identity": "PROMOTION_STUDIO_LOCAL_DEMO",
}

PUBLISH_EFFECTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["target", "external_network_post", "external_account_mutation",
                 "credential_use", "side_effect_scope", "simulation_identity"],
    "properties": {
        "target": {"const": "LOCAL_SIMULATED"},
        "external_network_post": {"const": False},
        "external_account_mutation": {"const": False},
        "credential_use": {"const": False},
        "side_effect_scope": {"const": "LOCAL_ONLY"},
        "simulation_identity": {"type": "string", "minLength": 3, "maxLength": 80},
    },
}

REMOTE_EFFECTS = {"REMOTE_EXTERNAL_WRITE", "NETWORK_WRITE", "ACCOUNT_MUTATION",
                  "CREDENTIAL_USE", "PUBLISH_REMOTE"}

RESULT_KEY_ALIASES = {
    "spec": "video.spec",
    "gui": "video.gui",
    "gui_check": "video.gui_check",
    "plan": "video.plan",
    "script": "video.script",
    "design": "video.design",
    "tts": "video.tts",
    "captions": "video.captions",
    "render": "video.render",
    "mux": "video.mux",
    "qab": "video.qab",
}


class ExternalEffectBlocked(ValueError):
    pass


class PreflightRejected(RuntimeError):
    def __init__(self, report: Mapping[str, Any]):
        self.report = dict(report)
        failed = [c["check"] for c in self.report.get("checks", []) if c["status"] != "PASS"]
        super().__init__("S0_PRECHECK_FAIL:" + ",".join(failed))


def canonical_result_key(name: str) -> str:
    value = str(name or "")
    if value in RESULT_KEY_ALIASES:
        return RESULT_KEY_ALIASES[value]
    if value.startswith("video."):
        return value
    return value


def result_key_candidates(name: str) -> set[str]:
    canonical = canonical_result_key(name)
    short = {key for key, target in RESULT_KEY_ALIASES.items() if target == canonical}
    return {str(name), canonical} | short


def validate_publish_effects(plan: Mapping[str, Any]) -> dict[str, Any]:
    effects = plan.get("effects")
    if not isinstance(effects, Mapping):
        raise ValueError("PUBLISH_EFFECT_MISSING: effects object is required")
    if set(effects) != set(PUBLISH_EFFECTS):
        raise ValueError("PUBLISH_EFFECT_INVALID: effects fields must be exactly "
                         + ",".join(sorted(PUBLISH_EFFECTS)))
    target = effects.get("target")
    if target != "LOCAL_SIMULATED":
        if target == "REMOTE_EXTERNAL_WRITE":
            raise ExternalEffectBlocked("BLOCKED_EXTERNAL_EFFECT: remote external publish is not authorized")
        raise ValueError("PUBLISH_EFFECT_INVALID: target must be LOCAL_SIMULATED")
    if effects.get("external_network_post") is not False:
        raise ExternalEffectBlocked("BLOCKED_EXTERNAL_EFFECT: external_network_post must be false")
    if effects.get("external_account_mutation") is not False:
        raise ExternalEffectBlocked("BLOCKED_EXTERNAL_EFFECT: external_account_mutation must be false")
    if effects.get("credential_use") is not False:
        raise ExternalEffectBlocked("BLOCKED_EXTERNAL_EFFECT: credential_use must be false")
    if effects.get("side_effect_scope") != "LOCAL_ONLY":
        raise ExternalEffectBlocked("BLOCKED_EXTERNAL_EFFECT: side_effect_scope must be LOCAL_ONLY")
    if not isinstance(effects.get("simulation_identity"), str) or not effects["simulation_identity"].strip():
        raise ValueError("PUBLISH_EFFECT_INVALID: simulation_identity is required")
    return dict(effects)


def _contract(node) -> dict[str, Any]:
    value = node.config.get("leaf_contract") or {}
    return dict(value) if isinstance(value, Mapping) else {}


def _check(report: list[dict[str, Any]], name: str, ok: bool, evidence: str) -> None:
    report.append({"check": name, "status": "PASS" if ok else "FAIL", "evidence": evidence})


def preflight_tree(tree, catalog: Mapping[str, Any]) -> dict[str, Any]:
    nodes = {n.id: n for n in tree.nodes}
    checks: list[dict[str, Any]] = []

    duplicate_ids = len(nodes) != len(tree.nodes)
    duplicate_outputs = []
    outputs: dict[str, str] = {}
    for node in tree.nodes:
        contract = _contract(node)
        identity = str(contract.get("output_identity", ""))
        if identity:
            if identity in outputs:
                duplicate_outputs.append(identity)
            outputs[identity] = node.id
    _check(checks, "node_identity_unique", not duplicate_ids and not duplicate_outputs,
           "duplicate_ids=%s duplicate_outputs=%s" % (duplicate_ids, duplicate_outputs))

    identity_ok = True
    key_ok = True
    identity_evidence = []
    key_evidence = []
    for node in tree.nodes:
        contract = _contract(node)
        deps = list(contract.get("dependencies", ()))
        if list(node.depends_on) != deps:
            identity_ok = False
            identity_evidence.append("%s:tree_depends_on!=contract.dependencies" % node.id)
        if contract.get("executor_ref") != node.config.get("executor_ref"):
            identity_ok = False
            identity_evidence.append("%s:executor_ref_mismatch" % node.id)
        for dep in deps:
            if dep not in nodes:
                identity_ok = False
                identity_evidence.append("%s:missing_dependency:%s" % (node.id, dep))
                continue
            producer = _contract(nodes[dep])
            producer_identity = str(producer.get("output_identity", ""))
            if producer_identity != dep:
                key_ok = False
                key_evidence.append("%s expects %s but producer emits %s" % (node.id, dep, producer_identity))
    _check(checks, "node_identity", identity_ok, "; ".join(identity_evidence) or "all node ids resolve exactly")
    _check(checks, "producer_consumer_keys", key_ok, "; ".join(key_evidence) or "producer output_identity equals dependency id")

    plan_nodes = [n for n in tree.nodes if n.capability_ref == "video.plan@1"]
    plan_contract_ok = True
    plan_evidence = []
    for node in plan_nodes:
        contract = _contract(node)
        if list(contract.get("target_scope", ())) != ["trace/video_plan.json"]:
            plan_contract_ok = False
            plan_evidence.append("%s:target_scope_must_be_trace/video_plan.json" % node.id)
        entry = catalog.get(node.capability_ref, {})
        schema = (contract.get("plan_schema")
                  or ((entry.get("config") or {}).get("plan_schema"))
                  or {})
        required = list(schema.get("required", ()))
        if "effects" not in required:
            plan_contract_ok = False
            plan_evidence.append("%s:plan_schema_missing_required_effects" % node.id)
        if "effects" not in (schema.get("properties") or {}):
            plan_contract_ok = False
            plan_evidence.append("%s:plan_schema_missing_effects_definition" % node.id)
    _check(checks, "publish_contract", plan_contract_ok,
           "; ".join(plan_evidence) or ("plan schema requires effects" if plan_nodes else "no plan node"))

    consumer_caps = {"video.script@1", "video.design@1"}
    consumers = [n for n in tree.nodes if n.capability_ref in consumer_caps]
    output_ok = True
    output_evidence = []
    for node in consumers:
        deps = list(_contract(node).get("dependencies", ()))
        if "video.plan" not in deps:
            output_ok = False
            output_evidence.append("%s:does_not_depend_on_video.plan" % node.id)
        read_scope = _contract(node).get("read_scope")
        if read_scope is not None and "trace/video_plan.json" not in list(read_scope):
            output_ok = False
            output_evidence.append("%s:read_scope_misses_trace/video_plan.json" % node.id)
    _check(checks, "required_outputs", output_ok,
           "; ".join(output_evidence) or "consumers depend on video.plan")

    external_ok = True
    external_evidence = []
    for node in tree.nodes:
        domains = set(_contract(node).get("effect_domains", ()))
        if domains & REMOTE_EFFECTS:
            external_ok = False
            external_evidence.append("%s:remote_effect:%s" % (node.id, sorted(domains & REMOTE_EFFECTS)))
    _check(checks, "external_effects", external_ok,
           "; ".join(external_evidence) or "no remote external effect domain")

    failed = [c for c in checks if c["status"] != "PASS"]
    status = "PASS" if not failed else (
        "BLOCKED_EXTERNAL_EFFECT" if any("remote_effect" in c["evidence"] for c in failed) else "FAIL")
    return {
        "status": status,
        "tree_hash": hashlib.sha256(json.dumps(tree.as_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "checks": checks,
        "worker_dispatch_allowed": status == "PASS",
    }


def preflight_worker_request(request, catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(request.task_context.node_config)
    contract = dict(cfg.get("leaf_contract") or {})
    checks: list[dict[str, Any]] = []
    schema = cfg.get("plan_schema") or contract.get("plan_schema") or {}
    required = list(schema.get("required", ()))
    _check(checks, "worker_output_schema", "effects" in required and "scenes" in required,
           "required=%s" % required)
    _check(checks, "worker_target_scope", list(contract.get("target_scope", ())) == ["trace/video_plan.json"],
           "target_scope=%s" % list(contract.get("target_scope", ())))
    deps = list(contract.get("dependencies", ()))
    keys = set(request.task_context.dependency_results)
    missing = []
    for dep in deps:
        if result_key_candidates(dep) & keys:
            continue
        missing.append(dep)
    _check(checks, "producer_consumer_keys", not missing, "missing=%s" % missing)
    domains = set(contract.get("effect_domains", ()))
    external = bool(domains & REMOTE_EFFECTS)
    _check(checks, "external_effects", not external, "domains=%s" % sorted(domains))
    failed = [c for c in checks if c["status"] != "PASS"]
    return {"status": "PASS" if not failed else "FAIL",
            "checks": checks, "worker_dispatch_allowed": not failed}


def preflight_report_path(workdir: Path, report: Mapping[str, Any]) -> Path:
    return Path(workdir) / "trace" / ("preflight-%s.json" % report["tree_hash"][:16])


def write_preflight_report(workdir: Path, report: Mapping[str, Any]) -> Path:
    path = preflight_report_path(workdir, report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


class PreflightedDAGRunner(DAGRunner):
    """Run the existing DAG only after a deterministic full-tree preflight."""

    def __init__(self, *args, catalog: Mapping[str, Any], workdir: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self.catalog = dict(catalog)
        self.workdir = Path(workdir)

    def _run(self, *, project_id: str, run_id: str, tree, dag, **kwargs):
        report = preflight_tree(tree, self.catalog)
        write_preflight_report(self.workdir, report)
        if report["status"] != "PASS" or not report["worker_dispatch_allowed"]:
            raise PreflightRejected(report)
        return super()._run(project_id=project_id, run_id=run_id, tree=tree, dag=dag, **kwargs)
