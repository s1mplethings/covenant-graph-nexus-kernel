from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

from cgkn.application.learning import FileLessonStore, ProductionGenerationClient, StoreLessonReader
from cgkn.application.project_campaign.contracts import ProjectCase
from cgkn.application.project_campaign.matrix import _explicit_cli_contract
from cgkn.application.project_campaign.service import _compile, _contract, _evaluate, _obligations, _pytest, _render_tests
from cgkn.application.software_project.greenfield import GenerationManifestCompiler, GreenfieldBundleProductionService, canonical_hash
from cgkn.application.provider_evaluation import ProjectProviderPlan
from cgkn.providers import GatewayCompletionClient, ModelRoleConfig


def cases() -> tuple[ProjectCase, ...]:
    return (
        ProjectCase("line_select_cli", "A", "GREENFIELD_CLI", "line_select", "Select matching UTF-8 lines.",
                    {"entrypoint":"python -m line_select","commands":["INPUT QUERY [--ignore-case] [--json]"]},
                    {"operation":"line_select","text":"LINE_NUMBER:TEXT","json":"objects line,text","missing_or_invalid_utf8":"exit 2","empty":"success"},
                    ("line_select/__init__.py","line_select/__main__.py","line_select/core.py"),
                    ({"files":{"x.txt":"Alpha\nbeta\nalpha\n"},"steps":[{"argv":["x.txt","alpha","--ignore-case","--json"],"code":0,"json":[{"line":1,"text":"Alpha"},{"line":3,"text":"alpha"}]}]},),
                    ({"steps":[{"argv":["missing.txt","x"],"code":2,"stderr_nonempty":True}]},), cli_contract=_explicit_cli_contract("line_select_cli","line_select")),
        ProjectCase("bookmark_store_cli", "A", "PERSISTENT_CRUD", "bookmark_store", "Maintain a JSON bookmark store.",
                    {"entrypoint":"python -m bookmark_store","commands":["--store FILE add URL [--title TITLE] [--tag TAG]","--store FILE list [--tag TAG]","--store FILE show ID","--store FILE remove ID"]},
                    {"store":"JSON object next_id/items","ids":"monotonic","order":"ID","tag":"exact","invalid":"exit 2 no overwrite"},
                    ("bookmark_store/__init__.py","bookmark_store/__main__.py","bookmark_store/core.py"),
                    ({"steps":[{"argv":["--store","b.json","add","https://a","--title","A","--tag","x"],"code":0,"stdout_contains":"1"},{"argv":["--store","b.json","list","--tag","x"],"code":0,"stdout_contains":"https://a"},{"argv":["--store","b.json","show","1"],"code":0,"stdout_contains":"https://a"}]},),
                    ({"steps":[{"argv":["--store","b.json","show","999"],"code":2,"stderr_nonempty":True}]},), cli_contract=_explicit_cli_contract("bookmark_store_cli","bookmark_store")),
        ProjectCase("mapping_overlay_library", "A", "LIBRARY", "mapping_overlay", "Merge mapping layers without mutation.",
                    {"entrypoint":"python -m mapping_overlay","commands":["OUTPUT INPUT1 INPUT2 ..."],"public_api":"mapping_overlay.merge_layers(layers)"},
                    {"public_api":"mapping_overlay.merge_layers(layers)","objects":"recursive","arrays_scalars":"replace","inputs":"not mutated","output":"sorted JSON"},
                    ("mapping_overlay/__init__.py","mapping_overlay/__main__.py","mapping_overlay/core.py"),
                    ({"files":{"a.json":"{\"x\":{\"a\":1}}","b.json":"{\"x\":{\"b\":2}}"},"steps":[{"argv":["out.json","a.json","b.json"],"code":0,"file_json":{"path":"out.json","value":{"x":{"a":1,"b":2}}}}]},),
                    ({"python":"from mapping_overlay import merge_layers; a={'x':{'a':1}}; r=merge_layers([a,{'x':{'b':2}}]); assert a=={'x':{'a':1}} and r=={'x':{'a':1,'b':2}}","code":0},), cli_contract=_explicit_cli_contract("mapping_overlay_library","mapping_overlay")),
    )


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--provider-lab-root",type=pathlib.Path,required=True); parser.add_argument("--output-root",type=pathlib.Path,required=True); parser.add_argument("--resume-backup",action="store_true")
    args=parser.parse_args(); sys.path.insert(0,str(args.provider_lab_root.resolve()/"src"))
    from cgkn_provider_lab.gateway import GatewayApplication, GatewayServer
    from cgkn_provider_lab.secrets import SecretManager
    from cgkn_provider_lab.storage import ProviderConfigStore
    output=args.output_root.resolve(); output.mkdir(parents=True,exist_ok=True)
    server=GatewayServer(GatewayApplication(ProviderConfigStore().load_or_create_defaults(),secrets=SecretManager.create_default())); info=server.start()
    prior={}
    if args.resume_backup and (output/"greenfield_validation.json").is_file(): prior={row["project_id"]:row for row in json.loads((output/"greenfield_validation.json").read_text(encoding="utf-8"))["projects"]}
    rows=[]; routes={"line_select_cli":"qwen","bookmark_store_cli":"grok","mapping_overlay_library":"qwen"}; backups={"line_select_cli":"grok","bookmark_store_cli":"qwen","mapping_overlay_library":"grok"}
    try:
        for case in cases():
            root=output/case.project_id; workspace=root/"workspace"
            if root.exists() and not args.resume_backup: shutil.rmtree(root)
            workspace.mkdir(parents=True,exist_ok=True)
            provider=routes[case.project_id]; contract=_contract(case); contract={**contract,"cli_contract":case.cli_contract}
            task_class="project.domain.persistent" if case.project_type=="PERSISTENT_CRUD" else ("project.domain.library" if case.project_type=="LIBRARY" else "project.domain.simple")
            plan=ProjectProviderPlan(case.project_id,routes["line_select_cli"],routes["bookmark_store_cli"],routes["mapping_overlay_library"],"qwen","qwen","qwen",{task_class:backups[case.project_id]},{},{},{task_class:"LOW"})
            manifest=GenerationManifestCompiler().compile(project_id=case.project_id,project_type=case.project_type,package_name=case.package_name,project_contract=contract,obligations=_obligations(case),interface_contract=case.interface_contract,target_paths=case.target_paths,cli_contract=case.cli_contract)
            store=FileLessonStore(root/"lessons"); gateway=GatewayCompletionClient(info.base_url,info.access_token,"responses",enforce_budget=False)
            generation=ProductionGenerationClient(gateway,StoreLessonReader(store),store=store,max_provider_calls=2)
            config=ModelRoleConfig("worker",provider,90,4000,0.0,"none")
            service=GreenfieldBundleProductionService(generation,config,root/"production",provider_id=provider,route_snapshot_hash=canonical_hash({"project":case.project_id,"provider":provider,"fallback":"deny"}))
            _render_tests(workspace,case)
            if args.resume_backup:
                outcome=prior[case.project_id]["outcome"]; total_calls=int(prior[case.project_id].get("provider_calls",1))
            else:
                outcome=service.run_initial(manifest,contract,workspace,repair_candidate=False,retry_transport=False); total_calls=generation.provider_call_count
            backup_used=""
            if outcome["status"] != "SUCCEEDED" and not outcome.get("revision_ids"):
                backup_used=plan.authorize_backup(task_class,failure_domain="PROVIDER_TRANSPORT_FAILURE",action="RETRY_WITH_PRESELECTED_BACKUP")
                backup_generation=ProductionGenerationClient(gateway,StoreLessonReader(store),store=store,max_provider_calls=1)
                backup_service=GreenfieldBundleProductionService(backup_generation,ModelRoleConfig("worker",backup_used,90,4000,0.0,"none"),root/"production-backup",provider_id=backup_used,route_snapshot_hash=canonical_hash({"project":case.project_id,"provider":backup_used,"route_revision":2,"action":"RETRY_WITH_PRESELECTED_BACKUP"}))
                outcome=backup_service.run_initial(manifest,contract,workspace,repair_candidate=False,retry_transport=False)
                total_calls+=backup_generation.provider_call_count
            row={"project_id":case.project_id,"selected_provider":provider,"frozen_backup":backups[case.project_id],"backup_used":backup_used,"provider_calls":total_calls,"cli_provider_calls":0,"project_provider_plan_hash":plan.plan_hash,"status":"FAIL","outcome":outcome}
            try:
                if outcome["status"] != "SUCCEEDED": raise RuntimeError("GENERATION_FAILED")
                row.update(compile=_compile(workspace,case),tests=_pytest(workspace),oracle=_evaluate(workspace,case.package_name,case.public_cases,"oracle"),hidden=_evaluate(workspace,case.package_name,case.hidden_cases,"hidden"),status="PASS")
            except Exception as exc: row.update(failure_class=type(exc).__name__,failure=str(exc)[-1800:])
            rows.append(row)
    finally: server.stop()
    value={"kind":"AdaptiveProjectValidationReceipt","schema_version":"1.0","status":"PASS" if sum(r["status"]=="PASS" for r in rows)>=3 else "NEEDS_REWORK","passed":sum(r["status"]=="PASS" for r in rows),"total":3,"projects":rows,"contains_credentials":False}
    (output/"greenfield_validation.json").write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); print(json.dumps(value,ensure_ascii=False)); return 0 if value["status"]=="PASS" else 2


if __name__=="__main__": raise SystemExit(main())
