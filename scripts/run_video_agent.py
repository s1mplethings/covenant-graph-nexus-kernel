from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
from typing import Any, Mapping

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLIC = pathlib.Path(r"C:\Users\sunom\VeriArbor-Preview-Release")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.agent.catalog_composer import CatalogAgentComposer
from cgkn.application.promotion import video_qab as q
from cgkn.application.promotion import video_delegation as vd
from cgkn.execution import BlockExecutionRequest, TaskContext
from cgkn.providers import CGKNModelRouting, GatewayCompletionClient, ModelRoleConfig
from cgkn.providers import completion_client_from_environment
from cgkn.providers.gateway_client import GatewayCompletionError

DEFAULT_RUN_ROOT = pathlib.Path(r"C:\Users\sunom\VeriArbor-QAB-Video-20261107\live-delegation\live-20261107-01")
SPEC = pathlib.Path(r"C:\Users\sunom\VeriArbor-QAB-Video-20261107\closeout\closeout-20261107-01\delivery\video_task_spec.json")
GOAL = pathlib.Path(r"C:\Users\sunom\VeriArbor-QAB-Video-20261107\closeout\closeout-20261107-01\delivery\VIDEO_GOAL_RESOLUTION.md")
REVIEW = pathlib.Path(r"C:\Users\sunom\Downloads\VIDEO_REVIEW.md")
ROUTING = ROOT / "config" / "provider_profiles" / "domestic_model_routing.json"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def routing_snapshot() -> dict[str, Any]:
    routing = bounded_routing()
    return {
        "kind": "VideoDelegationRoutingSnapshot",
        "path": str(ROUTING),
        "sha256": sha(ROUTING),
        "agent": {
            "provider_id": routing.agent.model,
            "model_id": routing.agent.model_id,
            "max_output_tokens": routing.agent.max_output_tokens,
            "timeout_seconds": routing.agent.timeout_seconds,
        },
        "worker": {
            "provider_id": routing.worker.model,
            "model_id": routing.worker.model_id,
            "max_output_tokens": routing.worker.max_output_tokens,
            "timeout_seconds": routing.worker.timeout_seconds,
        },
        "allowed_providers": sorted(routing.allowed_providers),
        "fallback": routing.fallback,
        "contains_credentials": False,
    }


def bounded_routing() -> CGKNModelRouting:
    from dataclasses import replace
    base = CGKNModelRouting.load(ROUTING)
    return CGKNModelRouting(
        agent=replace(base.agent, max_output_tokens=2000),
        worker=replace(base.worker, max_output_tokens=3000),
        allowed_providers=base.allowed_providers,
        fallback=base.fallback,
    )


def delegation_goal() -> str:
    return (
        "Improve the current 55.53-second Promotion Studio local demo for a first-time "
        "viewer using the supplied external review. Start with a composite root node named "
        "video (empty capability_ref, parent_id empty), then add real capabilities. Use only real GUI captures; keep the "
        "provisional 30-60 second, 1920x1080, 30fps, zh-CN specification; do not claim "
        "real social publishing. First compose and run the real GUI capture. Then add a "
        "delegated video plan worker plus the deterministic consumers and independent QAB "
        "checker from the capability catalog. The worker must write a plan that the "
        "script, design, captions and mux nodes actually consume. If the plan is invalid "
        "or a deterministic check fails, make at most one bounded repair by updating the "
        "plan config and retrying the plan node. Finish only when the independent "
        "technical-delivery checker is verified. Perceptual quality stays pending review."
    )


def prepare(run_root: pathlib.Path) -> dict[str, Any]:
    workspace = run_root / "workspace"
    if workspace.exists() and any(workspace.iterdir()):
        raise FileExistsError("workspace must be new or empty: " + str(workspace))
    spec = vd.prepare_workspace(workspace, SPEC, GOAL, REVIEW)
    catalog = vd.build_video_catalog(workspace, spec)
    public_catalog = {}
    for key, entry in catalog.items():
        contract = entry["config"]["leaf_contract"]
        public_catalog[key] = {
            "executor_ref": entry["executor_ref"],
            "depends_on": contract["dependencies"],
            "target_scope": contract["target_scope"],
        }
    plan = {
        "kind": "VeriArborVideoDelegationPlan",
        "schema_version": "1.0",
        "status": "PREPARED_NOT_EXECUTED",
        "goal": delegation_goal(),
        "workspace": str(workspace),
        "sources": {
            "spec": {"path": str(SPEC), "sha256": sha(SPEC)},
            "goal": {"path": str(GOAL), "sha256": sha(GOAL)},
            "review": {"path": str(REVIEW), "sha256": sha(REVIEW)},
            "routing": {"path": str(ROUTING), "sha256": sha(ROUTING)},
            "host_module": {"path": str(pathlib.Path(vd.__file__)), "sha256": sha(pathlib.Path(vd.__file__))},
            "composer": {"path": str(pathlib.Path(sys.modules[CatalogAgentComposer.__module__].__file__)),
                         "sha256": sha(pathlib.Path(sys.modules[CatalogAgentComposer.__module__].__file__))},
            "qab_module": {"path": str(pathlib.Path(q.__file__)), "sha256": sha(pathlib.Path(q.__file__))},
        },
        "routing": routing_snapshot(),
        "capabilities": public_catalog,
        "budget": {
            "currency": "CNY",
            "max_total_cost": 2.0,
            "max_api_calls": 8,
            "max_planning_calls": 4,
            "max_generation_calls": 2,
            "max_repair_calls": 1,
            "max_input_tokens": 50000,
            "max_output_tokens": 14000,
            "input_cost_per_million": 20.0,
            "output_cost_per_million": 60.0,
            "price_source": [
                "Host scripts/domestic_task_acceptance.py conservative rates",
                "https://help.aliyun.com/zh/model-studio/qwen3-8-max",
                "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
            ],
        },
        "no_paid_calls_before_explicit_authorization": True,
        "expected_calls": [
            "planner: compose spec/gui and request run",
            "planner: compose delegated plan and consumers and request run",
            "worker: produce trace/video_plan.json",
            "planner: finish after independent technical acceptance",
        ],
        "max_semantic_repairs": 1,
    }
    write_json(run_root / "DELEGATION_PLAN.json", plan)
    (run_root / "API_ROUTE_MAP.md").write_text(api_route_map(plan), encoding="utf-8")
    (run_root / "BUDGET_AUTHORIZATION.md").write_text(authorization_sheet(plan), encoding="utf-8")
    return plan


def api_route_map(plan: Mapping[str, Any]) -> str:
    return f"""# API_ROUTE_MAP

## Entry and authority

- Project goal and external review enter `cgkn.agent.ProjectSession.run` (alias `AgentProjectLoop`).
- Planner API call: `AgentComposer.decide` using `CatalogAgentComposer`.
- Host admission: existing `TreeEdit`/`CapabilityTree` validation, then `compile_tree`.
- Execution: existing `DAGRunner` -> `ExecutorRegistry` -> `FileRunStore`.
- Worker API call: existing `LLMExecutor` on the `video.plan` node.
- Worker artifact: `trace/video_plan.json`, bounded by the node `target_scope`.
- Deterministic consumers: `video.script`, `video.design`, `video.captions`, `video.mux`.
- Independent check: `promotion.video.qab@1` writes `trace/qab_report.json` and calls the existing deterministic checkers.
- Acceptance: existing `GoalAcceptance` records the independent receipt.

## Dataflow

```
user goal + VIDEO_REVIEW.md
  -> Planner (qwen) proposes TreeEdits
  -> Host validates and compiles ExecutionDAG
  -> Worker (deepseek) writes trace/video_plan.json
  -> script/design/captions/mux read that exact plan
  -> DAGRunner renders and muxes
  -> QAB checker reads final.mp4 and independent evidence
  -> GoalAcceptance records the current receipt
```

## Budget and credentials

- Budget ledger: `scripts/provider_api_budget.py`, configured only by the approved authorization.
- Credentials: existing domestic gateway session/keyring; never written into prompts, traces or delivery files.
- Fallback: deny. No automatic model escalation. No paid retry without a new authorization.

## Files

- Plan: `{plan['workspace']}\\trace\\video_plan.json`
- Final video: `{plan['workspace']}\\out\\final.mp4`
- Run state: `{plan['workspace']}\\state`
- Delegation result: `{plan['workspace']}\\trace\\delegation_result.json`
"""


def authorization_sheet(plan: Mapping[str, Any]) -> str:
    budget = plan["budget"]
    return f"""# BUDGET_AUTHORIZATION

Status: **AWAITING_USER_CONFIRMATION**  
Plan SHA-256: `{sha(pathlib.Path(plan['workspace']).parent / 'DELEGATION_PLAN.json')}`

## Exact scope

- Application: VeriArbor Host video delegation, one bounded improvement.
- Provider/model:
  - Planner: `qwen` / `{plan['routing']['agent']['model_id']}`
  - Worker: `deepseek` / `{plan['routing']['worker']['model_id']}`
- Data sent: the provisional spec, `VIDEO_GOAL_RESOLUTION.md`, `VIDEO_REVIEW.md`, capability catalog, current tree/check results and observation summaries. No credentials, cookies, private keys or unrelated user data.
- First paid request: the actual video planning decision, not a hello/benchmark.
- Expected calls: {len(plan['expected_calls'])}; hard maximum: {budget['max_api_calls']} (including retries, review and one repair).
- Maximum one semantic repair round.
- Per-request output bounds: Planner {plan['routing']['agent']['max_output_tokens']} tokens; Worker {plan['routing']['worker']['max_output_tokens']} tokens.
- Total budget: **{budget['max_total_cost']:.2f} CNY**.
- Conservative rates: {budget['input_cost_per_million']:.2f} CNY / 1M input, {budget['output_cost_per_million']:.2f} CNY / 1M output.
- Rate source: {", ".join(budget['price_source'])}. Exact provider-billed cost may be lower; billed cost is recorded as UNKNOWN unless the provider returns it.
- User authorization reference: required in `AUTHORIZATION.json`.
- No authorization reuse from earlier runs.

## Hard stops

- No push, tag, Release or social posting.
- No real social account authentication.
- No formal signing or P11 unhold.
- No change to the original `out\\final.mp4` or historical evidence.
- No spending above the approved total.

To approve, create `AUTHORIZATION.json` with:

```json
{{
  "kind": "VeriArborVideoDelegationAuthorization",
  "approved": true,
  "user_authorization_reference": "<your reference>",
  "max_cost_cny": {budget['max_total_cost']},
  "max_api_calls": {budget['max_api_calls']},
  "plan_sha256": "<plan sha above>"
}}
```

The live command validates this file before setting any budget environment or creating a Provider client.
"""


def configure_budget(auth: Mapping[str, Any], run_root: pathlib.Path) -> None:
    limits = {
        "CGKN_PROVIDER_BUDGET_LEDGER": str(run_root / "budget-ledger.json"),
        "CGKN_PROVIDER_MAX_API_CALLS": str(int(auth["max_api_calls"])),
        "CGKN_PROVIDER_MAX_PLANNING_CALLS": str(int(auth.get("max_planning_calls", 4))),
        "CGKN_PROVIDER_MAX_GENERATION_CALLS": str(int(auth.get("max_generation_calls", 2))),
        "CGKN_PROVIDER_MAX_REPAIR_CALLS": str(int(auth.get("max_repair_calls", 1))),
        "CGKN_PROVIDER_MAX_INPUT_TOKENS": str(int(auth.get("max_input_tokens", 50000))),
        "CGKN_PROVIDER_MAX_OUTPUT_TOKENS": str(int(auth.get("max_output_tokens", 14000))),
        "CGKN_PROVIDER_MAX_ESTIMATED_COST": str(float(auth["max_cost_cny"])),
        "CGKN_PROVIDER_INPUT_COST_PER_MILLION": "20",
        "CGKN_PROVIDER_OUTPUT_COST_PER_MILLION": "60",
        "CGKN_PROVIDER_CACHE_MODE": "read_write",
        "CGKN_PROVIDER_RESPONSE_CACHE_DIR": str(run_root / "responses"),
    }
    os.environ.update(limits)


def validate_authorization(path: pathlib.Path, plan_path: pathlib.Path) -> dict[str, Any]:
    auth = json.loads(path.read_text(encoding="utf-8"))
    if auth.get("kind") != "VeriArborVideoDelegationAuthorization" or auth.get("approved") is not True:
        raise ValueError("explicit approved video delegation authorization required")
    if not auth.get("user_authorization_reference"):
        raise ValueError("user authorization reference required")
    if auth.get("plan_sha256") != sha(plan_path):
        raise ValueError("authorization does not match the current delegation plan")
    amount = auth.get("max_cost_cny")
    if type(amount) not in (int, float) or isinstance(amount, bool) or not 0 < amount <= 2.0:
        raise ValueError("authorized amount must be positive and at most 2 CNY")
    calls = auth.get("max_api_calls")
    if type(calls) is not int or not 1 <= calls <= 8:
        raise ValueError("authorized API calls must be an integer between 1 and 8")
    return auth


def check_only(run_root: pathlib.Path) -> dict[str, Any]:
    workspace = run_root / "workspace"
    spec = q.ensure_spec(workspace)
    catalog = vd.build_video_catalog(workspace, spec)
    routing = bounded_routing()
    checks = []

    def add(label: str, passed: bool, detail: Any = "") -> None:
        checks.append({"check": label, "passed": bool(passed), "detail": detail})

    add("routing agent/worker distinct models",
        bool(routing.agent.model_id and routing.worker.model_id
             and routing.agent.model_id != routing.worker.model_id),
        [routing.agent.model_id, routing.worker.model_id])
    add("routing fallback denied", routing.fallback == "deny", routing.fallback)
    add("catalog has planner and qab",
        "video.plan@1" in catalog and "video.qab@1" in catalog,
        sorted(catalog))
    add("planner config requires read-only review/spec",
        set(catalog["video.plan@1"]["config"]["leaf_contract"]["read_scope"]) ==
        {"video_task_spec.json", "VIDEO_GOAL_RESOLUTION.md", "VIDEO_REVIEW.md"},
        catalog["video.plan@1"]["config"]["leaf_contract"]["read_scope"])
    add("worker target is bounded",
        catalog["video.plan@1"]["config"]["leaf_contract"]["target_scope"] == ["trace/video_plan.json"],
        catalog["video.plan@1"]["config"]["leaf_contract"]["target_scope"])
    add("qab acceptance checker identity",
        catalog["video.qab@1"]["config"]["leaf_contract"]["executor_ref"] == "promotion.video.qab@1",
        catalog["video.qab@1"]["config"]["executor_ref"])

    # Catalog composer fills the leaf contract but rejects unknown capability.
    class Context:
        capability_catalog = catalog
        tree = type("T", (), {"by_id": {}})()

    composer_check = object.__new__(CatalogAgentComposer)
    composer_check.root_config = {"acceptance_goal_id": "video.technical_delivery"}
    normalized = composer_check._normalize_decision({
        "edits": [{"edit_id": "e1", "operation": "add_node", "node_id": "video.plan",
                   "payload": {"capability_ref": "video.plan@1", "parent_id": "video",
                               "depends_on": ["video.spec", "video.gui"],
                               "config": {"editorial_brief": "result-first"}},
                   "provenance": {}}],
        "schema_version": "1.0", "decision_id": "d", "summary": "s", "reason": "r",
        "request_run": True, "finish": False, "needs_escalation": False,
        "escalation_reason": "",
    }, Context())
    payload = normalized["edits"][0]["payload"]
    add("catalog composer injects leaf contract",
        payload["config"]["leaf_contract"]["executor_ref"] == "llm.cheap@1"
        and payload["config"]["executor_ref"] == "llm.cheap@1",
        payload["config"]["executor_ref"])
    try:
        composer_check._normalize_decision({
            "edits": [{"edit_id": "e2", "operation": "add_node", "node_id": "x",
                       "payload": {"capability_ref": "video.unknown@1", "parent_id": "video",
                                   "depends_on": [], "config": {}}, "provenance": {}}],
            "schema_version": "1.0", "decision_id": "d", "summary": "s", "reason": "r",
            "request_run": True, "finish": False, "needs_escalation": False,
            "escalation_reason": "",
        }, Context())
        unknown_rejected = False
    except ValueError:
        unknown_rejected = True
    add("unknown capability rejected", unknown_rejected)

    # Budget refusal happens before transport when a ledger is configured but
    # the run-level limits are incomplete.
    import tempfile
    from scripts import provider_api_budget as budget
    os.environ["CGKN_PROVIDER_BUDGET_LEDGER"] = str(
        pathlib.Path(tempfile.mkdtemp(prefix="video-budget-check-")) / "ledger.json")
    os.environ.pop("CGKN_PROVIDER_MAX_API_CALLS", None)
    os.environ.pop("CGKN_PROVIDER_MAX_ESTIMATED_COST", None)
    try:
        budget.reserve_call(
            case_id="offline-check", purpose="PLANNING", model="qwen3.8-flash",
            request_identity="offline-check", estimated_input_tokens=10,
            requested_output_tokens=10, retry_count=0, execution_policy="limited")
        budget_rejected = False
        budget_detail = "unexpected"
    except Exception as exc:  # noqa: BLE001 - classify exact refusal
        budget_rejected = isinstance(exc, budget.ProviderBudgetExhausted)
        budget_detail = type(exc).__name__ + ": " + str(exc)[:200]
    add("no budget -> refusal before transport", budget_rejected, budget_detail)

    # Valid plan fixture is consumed by the deterministic script adapter.
    import tempfile
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="video-plan-check-"))
    (tmp / "trace").mkdir(parents=True)
    (tmp / "video_task_spec.json").write_bytes((workspace / "video_task_spec.json").read_bytes())
    (tmp / "VIDEO_GOAL_RESOLUTION.md").write_bytes((workspace / "VIDEO_GOAL_RESOLUTION.md").read_bytes())
    (tmp / "VIDEO_REVIEW.md").write_bytes((workspace / "VIDEO_REVIEW.md").read_bytes())
    fixture_plan = {
        "schema_version": "1.0",
        "strategy": "Fixture-only schema check; this is not a business plan or a delivery artifact.",
        "review_refs": ["V01", "V03"],
        "scenes": [
            {"id": "intro", "source": None, "title": "t", "kicker": "k",
             "narration": "这是一个用于离线模式校验的固定测试文本。", "on_screen": "o",
             "focus": None, "highlight": None, "cards": None},
            {"id": "projects", "source": "02_campaigns.png", "title": "t", "kicker": "k",
             "narration": "这是一个用于离线模式校验的固定测试文本。", "on_screen": "o",
             "focus": {"x": 0.1, "y": 0.1, "w": 0.6, "h": 0.6}, "highlight": None, "cards": None},
            {"id": "content", "source": "04_approved.png", "title": "t", "kicker": "k",
             "narration": "这是一个用于离线模式校验的固定测试文本。", "on_screen": "o",
             "focus": None, "highlight": None, "cards": None},
            {"id": "publish", "source": "06_receipts.png", "title": "t", "kicker": "k",
             "narration": "本地模拟发布，不连接真实平台。", "on_screen": "o",
             "focus": None, "highlight": None, "cards": None},
            {"id": "recording", "source": "recording", "title": "t", "kicker": "k",
             "narration": "这是一个用于离线模式校验的固定测试文本。", "on_screen": "o",
             "focus": None, "highlight": None, "cards": None},
            {"id": "qab", "source": None, "title": "t", "kicker": "k",
             "narration": "这是一个用于离线模式校验的固定测试文本。", "on_screen": "o",
             "focus": None, "highlight": None, "cards": [["a", "b"]]},
            {"id": "closing", "source": None, "title": "t", "kicker": "k",
             "narration": "这是一个用于离线模式校验的固定测试文本。", "on_screen": "o",
             "focus": None, "highlight": None, "cards": None},
        ],
        "subtitle": {"position": "top", "margin_v": 64, "font_size": 18},
    }
    write_json(tmp / "trace" / "video_plan.json", fixture_plan)
    fake_gui = {"screenshots": [
        {"name": n, "path": str(workspace / "evidence" / "gui" / n), "sha256": "x"}
        for n in ("02_campaigns.png", "04_approved.png", "06_receipts.png")
    ]}
    request = BlockExecutionRequest(
        project_id="check", run_id="check", attempt_id="a", node_id="video.script",
        component_ref="video.script@1", executor_ref="promotion.video.script.plan@1",
        task_context=TaskContext(node_goal="consume plan",
                                 node_config={"workdir": str(tmp)},
                                 dependency_results={"gui": {"gui": fake_gui}}),
    )
    result = vd.exec_script_from_plan(request)
    add("valid plan consumed by script adapter", result.status.value == "SUCCEEDED",
        result.error.message if result.error else str(tmp / "trace" / "scenes.json"))
    add("consumed scenes match plan",
        result.status.value == "SUCCEEDED" and
        json.loads((tmp / "trace" / "scenes.json").read_text(encoding="utf-8"))["scenes"][4]["scene"] == "recording",
        "scenes.json")

    bad = dict(fixture_plan)
    bad["scenes"] = fixture_plan["scenes"][:3]
    write_json(tmp / "trace" / "video_plan.json", bad)
    bad_result = vd.exec_script_from_plan(request)
    add("invalid plan rejected", bad_result.status.value == "FAILED",
        bad_result.error.message if bad_result.error else "")

    # Existing LLMExecutor boundary: a worker cannot write outside target_scope,
    # cannot apply truncated JSON, and a valid in-scope write is materialized.
    from cgkn.execution import BlockExecutionRequest as BER, TaskContext as TC
    from cgkn.executors import LLMExecutor
    from cgkn.orchestration.leaf_contract import build_leaf_contract
    from cgkn.providers import ModelRoleConfig, ProviderCompletion

    worker_root = pathlib.Path(tempfile.mkdtemp(prefix="video-worker-check-"))
    (worker_root / "trace").mkdir(parents=True)
    worker_contract = build_leaf_contract(
        goal="produce one bounded plan", kind="IMPLEMENTATION",
        scope=["trace/video_plan.json"], acceptance=["plan"], checker="plan.check",
        output_identity="video.plan", effect_domains=["filesystem"],
        executor="llm.cheap@1", dependencies=["video.spec"],
        expected_delta="one plan file")
    worker_config = ModelRoleConfig("worker", "deepseek", 30, 1200, 0.0, "none", "deepseek-flash")
    worker_request = BER(
        project_id="check", run_id="check", attempt_id="a", node_id="video.plan",
        component_ref="video.plan@1", executor_ref="llm.cheap@1",
        dependency_result_refs=("video.spec",),
        task_context=TC(node_goal="produce one bounded plan",
                        node_config={"leaf_contract": worker_contract,
                                     "executor_ref": "llm.cheap@1"}))

    class FakeClient:
        def __init__(self, text):
            self.text = text
            self.calls = 0
        def complete(self, **kwargs):
            self.calls += 1
            return ProviderCompletion(self.text, "deepseek-flash", "fake-request", {"input_tokens": 10, "output_tokens": 10}, 1)

    escape = json.dumps({
        "schema_version": "1.0", "node_id": "video.plan", "summary": "escape",
        "actions": [{"action": "write_file", "path": "../escape.txt", "content": "x"}],
        "expected_outputs": ["trace/video_plan.json"], "confidence": 1,
        "needs_escalation": False, "escalation_reason": ""})
    escape_result = LLMExecutor(worker_root, FakeClient(escape), worker_config).execute(worker_request)
    add("worker path escape rejected", escape_result.status.value == "FAILED",
        escape_result.error.message if escape_result.error else "")
    add("worker escape did not write outside root",
        not (worker_root.parent / "escape.txt").is_file(), "parent file absent")

    truncated = LLMExecutor(worker_root, FakeClient("{"), worker_config).execute(worker_request)
    add("truncated worker JSON rejected", truncated.status.value == "FAILED",
        truncated.error.message if truncated.error else "")

    valid_worker = json.dumps({
        "schema_version": "1.0", "node_id": "video.plan", "summary": "fixture",
        "actions": [{"action": "write_file", "path": "trace/video_plan.json",
                     "content": json.dumps(fixture_plan, ensure_ascii=False)}],
        "expected_outputs": ["trace/video_plan.json"], "confidence": 1,
        "needs_escalation": False, "escalation_reason": ""})
    valid_result = LLMExecutor(worker_root, FakeClient(valid_worker), worker_config).execute(worker_request)
    add("valid worker proposal materialized",
        valid_result.status.value == "SUCCEEDED" and (worker_root / "trace" / "video_plan.json").is_file(),
        valid_result.status.value)

    failed = [c for c in checks if not c["passed"]]
    payload = {"kind": "VideoDelegationOfflinePrecheck", "ok": not failed,
               "checked": len(checks), "failed": len(failed), "checks": checks}
    write_json(run_root / "OFFLINE_PRECHECK.json", payload)
    return payload


def live(run_root: pathlib.Path, authorization: pathlib.Path,
         workspace_name: str = "workspace", run_id: str = "video-delegation-live-02",
         project_id: str = "promotion-video-delegation") -> dict[str, Any]:
    plan_path = run_root / "DELEGATION_PLAN.json"
    auth = validate_authorization(authorization, plan_path)
    configure_budget(auth, run_root)
    routing = bounded_routing()
    client = completion_client_from_environment()
    if isinstance(client, GatewayCompletionClient):
        base = getattr(client, "base_url", "")
        if not base:
            client = client.reconnect()
    client = client.bind_run(run_id, "video-delegation")
    snapshot = routing.snapshot(run_id,
                                gateway_protocol="openai-compatible-local-v1")
    snapshot.write_once(run_root / ("MODEL_ROUTING_SNAPSHOT_%s.json" % run_id))
    workspace = run_root / workspace_name
    payload = vd.run_video_delegation(
        workdir=workspace,
        project_id=project_id,
        run_id=run_id,
        client=client,
        routing=routing,
        spec_source=SPEC,
        goal_source=GOAL,
        review_source=REVIEW,
        max_decisions=4,
    )
    payload["authorization_reference"] = auth["user_authorization_reference"]
    payload["budget_ledger"] = str(run_root / "budget-ledger.json")
    write_json(run_root / ("LIVE_RESULT_%s.json" % run_id), payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Model-delegated video improvement")
    parser.add_argument("--run-root", type=pathlib.Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorization", type=pathlib.Path)
    parser.add_argument("--workspace", default="workspace-02")
    parser.add_argument("--run-id", default="video-delegation-live-02")
    parser.add_argument("--project-id", default="promotion-video-delegation")
    args = parser.parse_args(argv)
    args.run_root.mkdir(parents=True, exist_ok=True)
    if args.prepare:
        print(json.dumps(prepare(args.run_root), ensure_ascii=False, indent=2))
        return 0
    if args.check_only:
        result = check_only(args.run_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    if args.live:
        if not args.authorization:
            raise SystemExit("--live requires --authorization")
        result = live(args.run_root, args.authorization,
                      workspace_name=args.workspace, run_id=args.run_id,
                      project_id=args.project_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in {"GOALS_VERIFIED", "SUCCEEDED"} else 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
