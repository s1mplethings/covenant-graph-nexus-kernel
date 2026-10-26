from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time
from dataclasses import asdict
from typing import Any, Mapping

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.learning import FileLessonStore, ProductionGenerationClient, StoreLessonReader
from cgkn.application.project_campaign.matrix import _existing_cases
from cgkn.application.project_campaign.service import (_compile, _contract, _evaluate, _obligations,
                                                       _package, _pytest, _render_tests, _snapshot)
from cgkn.application.repository_codegen import ChangeKind, ChangeRequest, RepositoryCodegenService
from cgkn.application.software_project.greenfield import GenerationManifestCompiler, GreenfieldBundleProductionService, canonical_hash
from cgkn.providers import (ConnectorCompletionClient, DeepSeekConnector, GrokConnector, ModelRoleConfig,
                            ProviderConnectorRegistry, QwenConnector)
from cgkn.providers.supervision import ProviderLatencyProfileStore, SupervisedHttpTransport
from scripts.run_adaptive_project_validation import cases as greenfield_cases


def write_json(path: pathlib.Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def native_client(lab_root: pathlib.Path, output: pathlib.Path) -> ConnectorCompletionClient:
    sys.path.insert(0, str(lab_root.resolve() / "src"))
    from cgkn_provider_lab.secrets import SecretManager
    from cgkn_provider_lab.storage import ProviderConfigStore

    configs = {item.provider_id: item for item in ProviderConfigStore().load_or_create_defaults()}
    secrets = SecretManager.create_default()
    root = pathlib.Path(__file__).resolve().parents[1]
    profiles = {name: json.loads((root / "config" / "provider_connections" / f"{name}.json").read_text(encoding="utf-8")) for name in ("qwen", "deepseek", "grok")}
    environment: dict[str, dict[str, str]] = {}
    for name, env_name in (("qwen", "CGKN_QWEN_API_KEY"), ("deepseek", "CGKN_DEEPSEEK_API_KEY"), ("grok", "CGKN_GROK_API_KEY")):
        config = configs[name]
        profiles[name].update({"base_url": config.base_url, "preferred_models": [config.model], "allowed_models": [config.model]})
        if name == "qwen":
            profiles[name].update({"catalog_base_url": config.base_url, "workspace_id": "", "region": "cn-beijing"})
        environment[name] = {env_name: secrets.resolve(config)}
    latency = ProviderLatencyProfileStore(output / "provider_latency_profiles.json")
    connectors = (
        QwenConnector(profiles["qwen"], environment=environment["qwen"], transport=SupervisedHttpTransport(latency_store=latency)),
        DeepSeekConnector(profiles["deepseek"], environment=environment["deepseek"], transport=SupervisedHttpTransport(latency_store=latency)),
        GrokConnector(profiles["grok"], environment=environment["grok"], transport=SupervisedHttpTransport(latency_store=latency)),
    )
    return ConnectorCompletionClient(ProviderConnectorRegistry(connectors), enforce_budget=False, case_id="iter-029")


def greenfield(case, root: pathlib.Path, client: ConnectorCompletionClient, provider: str, *, allow_repair: bool, package: bool) -> dict[str, Any]:
    started = time.monotonic(); workspace = root / "workspace"; workspace.mkdir(parents=True, exist_ok=True)
    contract = {**_contract(case), "cli_contract": case.cli_contract}
    manifest = GenerationManifestCompiler().compile(project_id=case.project_id, project_type=case.project_type,
        package_name=case.package_name, project_contract=contract, obligations=_obligations(case),
        interface_contract=case.interface_contract, target_paths=case.target_paths, cli_contract=case.cli_contract)
    store = FileLessonStore(root / "lessons")
    generation = ProductionGenerationClient(client, StoreLessonReader(store), store=store, max_provider_calls=2 if allow_repair else 1)
    service = GreenfieldBundleProductionService(generation, ModelRoleConfig("worker", provider, 180, 7000, 0.0, "low"),
        root / "production", provider_id=provider,
        route_snapshot_hash=canonical_hash({"project": case.project_id, "provider": provider, "fallback": "frozen-only"}))
    _render_tests(workspace, case)
    outcome = service.run_initial(manifest, contract, workspace, repair_candidate=allow_repair, retry_transport=False)
    row: dict[str, Any] = {"project_id": case.project_id, "project_type": case.project_type, "provider": provider,
                           "provider_calls": generation.provider_call_count, "cli_provider_calls": 0, "outcome": outcome,
                           "candidate_revision_ids": list(outcome.get("revision_ids", {}).values()), "status": "FAIL"}
    if outcome["status"] != "SUCCEEDED":
        row["failure_domain"] = "PROVIDER_OR_CANDIDATE_FAILURE"; row["wall_time_seconds"] = round(time.monotonic()-started, 3); return row
    try:
        row.update(compile=_compile(workspace, case), tests=_pytest(workspace), oracle=_evaluate(workspace, case.package_name, case.public_cases, "oracle"),
                   hidden=_evaluate(workspace, case.package_name, case.hidden_cases, "hidden"), snapshot=_snapshot(workspace))
        if package:
            packaged = _package(pathlib.Path(__file__).resolve().parents[1], workspace, root, case, "ITER-029")
            row.update(package=packaged, runtime_smoke=packaged["runtime_smoke"])
        row["status"] = "PASS"
    except Exception as exc:
        row.update(failure_domain="VERIFICATION_FAILURE", failure=f"{type(exc).__name__}:{str(exc)[-1800:]}")
    row["supervision"] = [attempt.get("usage", {}) for attempt in outcome.get("attempts", [])]
    row["wall_time_seconds"] = round(time.monotonic()-started, 3); row["manual_candidate_edits"] = 0; row["whole_replans"] = 0
    return row


def existing_repo(case, root: pathlib.Path, client: ConnectorCompletionClient, provider: str, *, allow_repair: bool) -> dict[str, Any]:
    started=time.monotonic(); workspace=root/"workspace"; workspace.mkdir(parents=True,exist_ok=True)
    for relative, content in case.initial_files.items():
        target=workspace/relative; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(content,encoding="utf-8")
    store=FileLessonStore(root/"lessons"); generation=ProductionGenerationClient(client,StoreLessonReader(store),store=store,max_provider_calls=2 if allow_repair else 1)
    service=RepositoryCodegenService(generation,ModelRoleConfig("worker",provider,180,6000,0.0,"low"),provider_id=provider,mode="SELECTED",max_attempts=2 if allow_repair else 1)
    request=ChangeRequest(case.project_id,case.public_goal,ChangeKind.FEATURE,tuple(str(v) for v in case.behavior_contract.values()),("fixture_cli.render(value) unchanged","text output unchanged"),("tests","configuration","fixture_cli/core.py"),("existing tests pass","--json emits canonical object"),case.allowed_paths)
    try:
        receipt=service.run(workspace,request); row={"project_id":case.project_id,"project_type":case.project_type,"provider":provider,"provider_calls":receipt.calls,"cli_provider_calls":0,"receipt":receipt.as_dict(),"status":"FAIL"}
        row.update(tests=_pytest(workspace),oracle=_evaluate(workspace,case.package_name,case.public_cases,"oracle"),hidden=_evaluate(workspace,case.package_name,case.hidden_cases,"hidden"))
        row["status"]="PASS" if receipt.status=="PASS" else "FAIL"
    except Exception as exc:
        row={"project_id":case.project_id,"project_type":case.project_type,"provider":provider,"provider_calls":generation.provider_call_count,"cli_provider_calls":0,"status":"FAIL","failure_domain":"REPOSITORY_PATCH_FAILURE","failure":f"{type(exc).__name__}:{str(exc)[-1800:]}"}
    row.update(wall_time_seconds=round(time.monotonic()-started,3),manual_candidate_edits=0,whole_replans=0); return row


def run_phase(output: pathlib.Path, client: ConnectorCompletionClient, phase: str) -> dict[str, Any]:
    phase_root=output/phase; phase_root.mkdir(parents=True,exist_ok=True)
    result_path=phase_root/"results.json"
    prior_rows=json.loads(result_path.read_text(encoding="utf-8")).get("results",[]) if result_path.is_file() else []
    existing={row["project_id"]:row for row in prior_rows
              if not (row.get("failure_domain")=="PROVIDER_OR_CANDIDATE_FAILURE" and not row.get("candidate_revision_ids"))}
    green=list(greenfield_cases()); patch=_existing_cases()[0]
    routes={green[0].project_id:"qwen",green[1].project_id:"grok",green[2].project_id:"qwen",patch.project_id:"qwen"}
    all_cases=[*green,patch]; rows=[]
    for case in all_cases:
        if case.project_id in existing: rows.append(existing[case.project_id]); continue
        root=phase_root/case.project_id
        if root.exists(): shutil.rmtree(root)
        row=existing_repo(case,root,client,routes[case.project_id],allow_repair=phase=="projects") if case.existing_repo else greenfield(case,root,client,routes[case.project_id],allow_repair=phase=="projects",package=phase=="projects")
        rows.append(row); write_json(result_path,{"kind":"SupervisedMultitypePhase","schema_version":"1.0","phase":phase,"results":rows,"contains_credentials":False})
    passed=sum(row["status"]=="PASS" for row in rows); mandatory=all(next(r for r in rows if r["project_id"]==pid)["status"]=="PASS" for pid in ("line_select_cli","existing_repo_json_feature"))
    value={"kind":"SupervisedMultitypePhase","schema_version":"1.0","phase":phase,"passed":passed,"total":4,"gate_pass":passed>=3 and mandatory,"provider_calls":sum(int(row.get("provider_calls",0)) for row in rows),"results":rows,"contains_credentials":False}; write_json(result_path,value); return value


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--provider-lab-root",type=pathlib.Path,required=True); parser.add_argument("--output-root",type=pathlib.Path,required=True); parser.add_argument("--phase",choices=("canaries","projects","all"),default="all"); args=parser.parse_args()
    output=args.output_root.resolve(); output.mkdir(parents=True,exist_ok=True); client=native_client(args.provider_lab_root,output)
    canaries=run_phase(output,client,"canaries") if args.phase in {"canaries","all"} else json.loads((output/"canaries/results.json").read_text(encoding="utf-8"))
    projects={}
    if args.phase in {"projects","all"} and canaries.get("gate_pass"): projects=run_phase(output,client,"projects")
    total=int(canaries.get("provider_calls",0))+int(projects.get("provider_calls",0)); status="NEEDS_REWORK"
    if projects:
        passed=int(projects.get("passed",0)); status="PASS" if passed==4 else ("PASS_WITH_LIMITS" if passed>=3 and next(r for r in projects["results"] if r["project_id"]=="existing_repo_json_feature")["status"]=="PASS" else "NEEDS_REWORK")
    summary={"kind":"SupervisedMultitypeValidation","schema_version":"1.0","status":status,"canaries":canaries,"projects":projects,"provider_calls":total,"provider_call_limit":14,"manual_candidate_edits":0,"whole_replans":0,"contains_credentials":False}; write_json(output/"summary.json",summary); print(json.dumps(summary,ensure_ascii=False)); return 0 if status in {"PASS","PASS_WITH_LIMITS"} else 2


if __name__=="__main__": raise SystemExit(main())
