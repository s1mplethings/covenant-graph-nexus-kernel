"""Source-bound authority inventory; classification is reviewed, not inferred dead code."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/execution-authority-convergence'
OLD=ROOT.parent/'execution-dedup-20261101'


def write(name,value):
    (OUT/name).write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')


def main():
    data=[
      ('project_agent','CANONICAL','scripts/run_agent_mvp.py;cgkn/application/software_project/service.py; scripts/domestic_task_acceptance.py','cgkn/agent/project_loop.py','AgentProjectLoop','AgentComposer','DAGRunner','ExecutorRegistry / bounded LLM, deterministic tools','FileRunStore + Agent checkpoint','Agent decision plus affected DAG closure','independent application acceptance + deliverable checkers','no direct public delivery; reviewed delivery gate required','product mainline; isolated application entry, not replacement of Codex provider default'),
      ('dag','CANONICAL','AgentProjectLoop;runtime callers','cgkn/runtime/dag_runner.py','DAGRunner','none: consumes compiled CapabilityTree','DAGRunner readiness/frontier/concurrency','ExecutorRegistry','FileRunStore','downstream closure, unknown-effect reconciliation, completed sibling reuse','registered independent deliverable checkers','none: node/run status only','bounded graph authority, not second project planner'),
      ('provider_generation','LEGACY_ACTIVE','Codex handle_text -> run_provider_generation_job; MCP core.generation_command -> run_codex_conversation_generation; run_local_pipeline CLI','scripts/run_local_pipeline_impl.py','execute','reviewed provider plan/contract pipeline','run_local_pipeline_impl provider job dispatch','ProviderJob/PatchSet contracts + provider_text','run directory, component checkpoints and shared paid ledger','provider/semantic repair, checkpoint materialization','provider output validation; post-build finalization and real evidence','local_packager -> public_delivery_gate -> delivery_manifest','default Codex/MCP generation route; compatibility product authority status'),
      ('dynamic_pipeline','LEGACY_ACTIVE','codex_conversation.run_agent_generation_job compatibility API; tests invoke public run_dynamic_pipeline','scripts/dynamic_pipeline_runner.py','run_dynamic_pipeline','pipeline_planner_agent supplies manifest','manifest step iteration, stage and evidence checkpoints','_run_agent_turn / local actions','session JSONL and pipeline manifest','step failure / fallback / explicit rework status','build/QA audits and user evidence checkpoints','local_packager through package_project; outer canonical delivery still required','not default Codex route; external compatibility API remains callable'),
      ('manifest_action_loop','LEGACY_ACTIVE','run_dynamic_pipeline -> _run_agent_turn','scripts/dynamic_pipeline_runner.py','_run_agent_turn','none: role/step context','BEFORE independent turn loop; AFTER shared conversation._run_action_loop','LocalAgentActionExecutor restricted by allowed_actions','same session JSONL helper','BEFORE own retry/feedback controller; AFTER shared controller with manifest policy','strict response repair + action results + pre_package_audit; not standalone business acceptance','package_project result only, no independent promotion','CONVERGED: model/action/feedback/termination control removed from this module'),
      ('conversation_action_loop','LEGACY_ACTIVE','agent_conversation_loop CLI; dynamic fallback; codex_conversation.run_agent_generation_job fallback','scripts/agent_conversation_loop.py','run_agent_loop','bounded conversation model responses','shared _run_action_loop after migration','LocalAgentActionExecutor','session JSONL','one exhausted-budget repair, persisted feedback','tool evidence; package gate remains independent','local_packager via package_project','public CLI and compatibility imports retained; not reviewed Codex default'),
      ('artifact_runtime','SPECIALIZED_APPLICATION','scripts/run_artifact_flow.py;demo_artifact_recompute.py;component runtime tests','cgkn/runtime/runner.py','ArtifactModuleRunner','none: ArtifactFlowCompiler input','typed artifact topological iteration','ModuleComponentAdapter / bounded provider_executor / local functions','ArtifactStore, cache, run manifest and checkpoints','ArtifactInvalidator, content hashes, overridden output ports','typed input/output hashes and effect counters','none: typed flow results only','distinct artifact/cache/override identity; not interchangeable with FileRunStore leaf/checker contract'),
      ('bounded_worker','ALTERNATIVE_EXECUTOR','DAGRunner -> ExecutorRegistry.resolve','cgkn/executors/llm.py','LLMExecutor','none: receives bounded TaskContext','bounded actions within one BlockExecutionRequest','BoundedFileActions / provider client','BlockExecutionResult; task state stays in FileRunStore','bounded proposal/interface repair; escalates to Agent','worker output validation; independent checks remain outside Worker','none','not counted as duplicate project execution authority'),
      ('requirements_worker','SPECIALIZED_APPLICATION','software_project service installs requirement work-unit executors','cgkn/application/requirements/execution.py','ObligationWorkUnitExecutor','none: compiled obligation unit','bounded one-node unit execution','scoped file transaction / LLM executor','formal run state and produced evidence','unit feedback; ownership and dependency policy','external Oracle / artifact-bound acceptance','none','specialized unit effect boundary, not whole-project planner'),
      ('provider_job','ALTERNATIVE_EXECUTOR','run_local_pipeline_impl job graph and patch validators','scripts/provider_jobs.py','ProviderJob','none','NONE: dataclass and graph validators only','describes job / ownership / PatchSet','no independent run-state writer','none','PatchSet validation only','none','governance provider_scheduler label points to a contract, not executable scheduler; inventory corrects interpretation without changing governance'),
      ('growth','SPECIALIZED_APPLICATION','growth executor and self-growth CLI','cgkn/growth/loop.py','GrowthLoop','capability gap only','one bounded discovery/trial/admission workflow','LocalSandbox and executor factory','CapabilityRegistry / admission receipt','failed trial does not self-modify kernel','admission evaluation','none','different capability-acquisition responsibility'),
      ('mcp','COMPATIBILITY_ADAPTER','installed stdio tools/call registry','plugins/cgkn/scripts/cgkn_mcp_server.py','CGKNPluginServer','existing preparation/brief and provider route','start_generation_job process lifecycle, not node scheduler','generation CLI','plugin session and existing job state','delegates reviewed route','tool schema + user confirmation; delivery checked elsewhere','reviewed public gate only','dynamic tool registry retained'),
      ('codex','COMPATIBILITY_ADAPTER','run_codex_conversation_generation; conversation handle_text','scripts/codex_conversation.py','run_provider_generation_job','existing provider route','delegates provider pipeline; frontdesk async lifecycle','provider_project_pipeline','session state and provider run identity','provider/finalization recovery','post-build finalization / independent evidence','local_packager and public_delivery_gate','frontdesk lifecycle not separate complete Agent loop'),
    ]
    rows=[]
    for ident,classification,caller,file,symbol,planner,scheduler,worker,state,repair,acceptance,delivery,notes in data:
        p=ROOT/file
        rows.append(dict(id=ident,classification=classification,caller=caller,file=file,symbol=symbol,
            planner=planner,scheduler=scheduler,worker=worker,provider='canonical Gateway/budget when applicable; no new transport',state=state,repair=repair,acceptance=acceptance,delivery=delivery,notes=notes,
            source_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),external_dependencies='existing platform/provider/CLI only; live providers not exercised',test_evidence='baseline-full and candidate-full; selected controller trials and functional witnesses'))
    for row in rows:
        row['default_entry_scope']='DEFAULT_CODEX_MCP_GENERATION' if row['id']=='provider_generation' else 'DEFAULT_FRONTDOOR' if row['id'] in ('mcp','codex') else 'CANONICAL_PRODUCT_APPLICATION_NOT_CODEX_GENERATION_DEFAULT' if row['id'] in ('project_agent','dag') else 'EXPLICIT_COMPATIBILITY_ENTRY' if row['id'] in ('dynamic_pipeline','manifest_action_loop','conversation_action_loop') else 'EXPLICIT_SPECIALIZED_OR_EXECUTOR_USE'
    rows.append({'id':'minimal_project_loop','symbol':'MinimalProjectLoop','classification':'UNRESOLVED','notes':'historical name absent from current tracked/nonignored Python search; not treated as an existing authority or proof of global external unreachability'})
    files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    names={r['symbol'] for r in rows};calls=[];dynamic=[];clis=[]
    for rel in sorted(set(files)):
        p=ROOT/rel
        if not rel.endswith('.py') or not p.is_file() or rel.startswith(('.service_', '.api_lab_', 'experiments/')):continue
        try:tree=ast.parse(p.read_text(encoding='utf-8-sig'))
        except (SyntaxError,UnicodeError):continue
        for n in ast.walk(tree):
            if isinstance(n,ast.Call):
                target=ast.unparse(n.func)
                if target.split('.')[-1] in names:calls.append({'file':rel,'line':n.lineno,'target':target})
                if any(x in target for x in ('register','getattr','import_module','add_parser','add_argument')):
                    dynamic.append({'file':rel,'line':n.lineno,'target':target})
        if any(isinstance(n,ast.If) and '__name__' in ast.unparse(n.test) for n in tree.body):clis.append(rel)
    write('execution-entrypoints.json',{'reviewed_paths':rows,'syntactic_callers_not_points_to_proof':calls,'cli_guards':clis,'dynamic_sites':dynamic})
    conflicts=[
      {'responsibility':'model turn -> parse -> execute actions -> feedback -> repair/termination','owners_before':['conversation.run_agent_loop','dynamic._run_agent_turn'],'owners_after':['conversation._run_action_loop'],'entrypoints':['standalone CLI','dynamic manifest steps','compatibility fallbacks'],'differences':['exception retry policy','empty/malformed JSON handling','action allowlist','package audit','package batch stop','completion status'],'scope':'entire bounded action controller, not whole project planning','decision':'CONVERGED','evidence':'36 original shared trials, 45 final boundary/trial cases; ample-budget UNKNOWN safety refinement uses existing rework_blocked; full suites pending'},
      {'responsibility':'project orchestration','owners':['AgentProjectLoop','run_local_pipeline_impl.execute','run_dynamic_pipeline'],'differences':['canonical Tree/DAG/checker contract vs provider output/finalization checkpoint identities','manifest role/stage/evidence barriers are compatibility semantics'],'decision':'DEFERRED','blocker':'routing historical generation into DAGRunner requires new leaf/checker/intent mappings and preservation of publication evidence; thin forwarding alone is not equivalent'},
      {'responsibility':'graph scheduling/recovery','owners':['DAGRunner','ArtifactModuleRunner'],'differences':['ArtifactRef hashes, cache, output overrides and effect accounting vs leaf contracts, independent checker binding and FileRunStore identities'],'decision':'KEEP_SEPARATE','blocker':'current ArtifactModuleRunner graphs cannot be accepted by DAGRunner without a semantic state migration; dropping checker admission or artifact type validation is forbidden'},
      {'responsibility':'bounded Worker loops','owners':['LLMExecutor','ObligationWorkUnitExecutor'],'differences':['general proposal/interface repair vs obligation scope/dependency transaction'],'decision':'KEEP_SEPARATE','blocker':'distinct bounded executor capabilities; no evidence of competing project authority'},
      {'responsibility':'state','owners':['FileRunStore','provider_api_budget','FrozenKnowledge','ArtifactStore'],'decision':'KEEP_SEPARATE','blocker':'different identities, ledgers and immutability duties; not duplicate state for same transaction'},
      {'responsibility':'external harness replacing Worker','owners':['existing LLMExecutor','hypothetical external harness'],'decision':'DEFERRED','blocker':'no offline-qualified executor that deletes existing ownership, tool, usage and UNKNOWN obligations; no new SDK installed or claimed tested'},
    ]
    conflicts[0]['evidence']='36 original shared trials; 45 final boundary/trial cases; final-controller-trace; full-suite status and exact deltas in regression-report.md'
    conflicts[0]['safety_refinement']='Ample-budget loopback discovery: old and initial candidate posted twice after structured UNKNOWN; final shared controller returns existing rework_blocked, preventing retry and outer fallback. Ordinary policy differences remain.'
    write('duplicate-authorities.json',conflicts);write('authority-conflicts.json',conflicts)
    write('baseline.md',f'''# 基线与约束

HEAD: `0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`。原始目录 D:/CGKN 仍为脏工作树；本轮分支 codex/execution-authority-convergence-20261101。有效源是 {OLD}，逐文件复制并验证 1401 个文件（含原有非忽略 scratch 文件），详见 baseline-source-hashes.json。原目录 1377 文件与前轮快照相同，未覆盖。

继承两轮 psutil、冻结/解冻、Provider/opener 和命令守卫修正；本轮不重复计入前轮净删除 64 行。前轮全量 3399 passed / 28 failed / 14 errors / 350 skipped，退出码在包装器日志解码前未落盘的缺陷也保留为事实。本轮运行器强制 UTF-8，先持久化原始 pytest exit，再脱敏日志；不会从摘要推测退出码。

watchdog: **UNRESOLVED_BASELINE_RISK**。前轮 12 次相同负载对照中各版本一次冷启动相关失败，原始 stop-timeout 缺少现场栈，不能宣布修复。原证据仍在前轮工作树；本轮全量的栈采样尝试未识别 python -m，缺口见 instrumentation-gap.json；owned process/thread/handle/RSS 记录有效。独立配对试验使用已修正的匹配条件，每 0.2 秒采样栈，不能将缺失的全量栈记为已采集。

Python/已安装依赖见 prior-environment-packages.json。无新依赖，无付费 API，LIVE_NOT_VERIFIED。测试使用相同显式 legacy 离线 profile，外部 socket.connect 被阻止；各国内模式测试使用自己的 loopback fixture。不修改系统网络和真实凭据。

基线命令：`python -X utf8 experiments/authority_convergence/run_tests.py --source {OLD} --label baseline-full`。
候选命令：`python -X utf8 experiments/authority_convergence/run_tests.py --label candidate-full`。
详细 pytest argv、环境说明、PID 和退出码在各 run/start.json、completion.json。

产品 Agent/Tree/DAG 是核心权威；默认 Codex/MCP 仍为 reviewed Provider generation -> validation -> post-build finalization -> local_packager -> public_delivery_gate -> delivery_manifest。不能因为目标架构图而改造出新的正式交付路线。

当前 ITER-131 为 PRODUCT_NOT_READY。采用 manage-pmp-agile-quality 的有界增量与独立验收方法，不改变产品 readiness，也不新增管理状态权威。相关经验：EXP-MVP-003 bounded context、004 functional proof、005 retain migration archive、007 repository/product evidence separation。基线工作树和哈希承担归档；旧控制器不再保留为运行分支。

Git 政策复查：canonical_repo_publish 是唯一 staging/commit/push 权威，publish 会执行 normal_push_with_retry；没有仅本地提交模式。用户禁止 push，因此不调用发布工具，不绕过为普通 commit；保留 task-only.patch。
''')
    body=['# 实际执行权威地图','',
        '计数口径：项目任务路径、嵌套控制器、替代 Executor 分开计数，不能相加后声称多套完整项目引擎。四类可调用项目路径：产品 Agent 应用、默认 Provider 生成、历史 Dynamic Pipeline、独立 conversation CLI；Artifact flow 另为专门产物流路径。四类项目路径本轮没有删除。', '',
        '七个审阅的调度/控制实现单元（不同层次）在迁移前分别为 AgentProjectLoop、DAGRunner、Provider pipeline、Dynamic 外层步骤控制、Dynamic 内层 action turn、conversation action turn、ArtifactModuleRunner。本轮内层 action turn 两处归一，共用后为六个实现单元；只认定一项重复完整责任被消除，不把 ExecutorRegistry、ProviderJob 或不同 bounded Executor 算作竞争权威。', '',
        '```mermaid','flowchart TD','  User[User / Codex / CLI / MCP] --> Intake[Intake and explicit confirmation]','  Intake --> Agent[AgentComposer / AgentProjectLoop]','  Agent --> Tree[CapabilityTree -> compile_tree -> ExecutionDAG]','  Tree --> DAG[DAGRunner -> ExecutorRegistry]','  DAG --> Work[Bounded Worker / local tool]','  Work --> Provider[Gateway + budget + UNKNOWN]','  Work --> Evidence[Artifacts / independent checker / Oracle]','  Evidence --> State[FileRunStore -> affected-subgraph repair -> Agent checkpoint]','  Intake --> Reviewed[Reviewed provider project generation]','  Reviewed --> Finalize[Output validation / post-build finalization]','  Finalize --> Gate[local_packager -> public_delivery_gate -> delivery_manifest]','  Legacy[Legacy run_agent_generation_job] --> Dynamic[Dynamic outer manifest / stage checks]','  Dynamic --> Shared[Single action-turn controller]','  Conversation[Conversation CLI / fallback] --> Shared','  Shared --> Actions[LocalAgentActionExecutor + mode-specific policy]','  Actions --> Gate','```','',
        '图中的兼容 package 动作仍受既有 local_packager 门禁；tool 成功不等于最终交付。项目级决策、独立 Oracle、消费者端口/Observer 与公共交付权威没有迁移。', '',
        '|入口/机制|分类|调用者|规划/调度|状态/恢复|验收/交付|', '|---|---|---|---|---|---|']
    for r in rows:
        if 'file' not in r:continue
        body.append(f"|{r['symbol']}|{r['classification']}|{r['caller']}|{r['planner']} / {r['scheduler']}|{r['state']} / {r['repair']}|{r['acceptance']} / {r['delivery']}|")
    body+=['','## 责任所有权','',
        '|责任|实际所有者及边界|','|---|---|',
        '|目标解释/正式计划|AgentComposer/AgentProjectLoop；兼容生成仍有 provider/manifest 计划，不能假装已合并|',
        '|DAG 编辑/执行|compile_tree、Agent tree edits、DAGRunner；artifact graph 与 provider job graph 语义另列|',
        '|Worker 调度|DAGRunner 或对应兼容 pipeline；ProviderJob 本身不调度|',
        '|工具副作用|bounded executors / scoped file transactions / LocalAgentActionExecutor；调用策略保留|',
        '|预算和 UNKNOWN|provider_api_budget + Gateway submission identity；本轮未修改|',
        '|回合重试|两个兼容回合入口统一由 _run_action_loop 执行，两种原有政策显式保留|',
        '|项目状态与恢复|FileRunStore/DAGRunner；compatibility checkpoint 与 artifact invalidation 尚不同|',
        '|业务验收|registered checker / application Oracle / Observer；Worker 报告不是权威|',
        '|公共交付|local_packager + public_delivery_gate；manifest 为既有交付依据|','',
        'MinimalProjectLoop 在当前源未发现，标 UNRESOLVED 历史线索，不虚构一个活跃权威。静态调用索引保存 CLI guard 和动态注册点，非全程序 points-to 证明；未以静态缺引用删除入口。实际控制器调用将由 shared trials、cProfile 与 full suite 交叉验证。']
    write('execution-authority-map.md','\n'.join(body)+'\n')
    print(json.dumps({'reviewed_records':len(rows),'calls':len(calls),'dynamic_sites':len(dynamic),'cli_modules':len(clis)}))


if __name__=='__main__':main()
