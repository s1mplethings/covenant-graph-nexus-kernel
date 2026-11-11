"""Task-only patch, comparable regression delta and evidence-bound final reports."""
import ast
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
OLD=ROOT.parent/'execution-dedup-20261101'
OUT=ROOT/'artifacts/execution-authority-convergence'
PRODUCTION=['scripts/agent_conversation_loop.py','scripts/dynamic_pipeline_runner.py']


def write(name,value):
    (OUT/name).write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')


def load(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def cases(path):
    result={};rank={'passed':0,'skipped':1,'failure':2,'error':3}
    for case in ET.parse(path).findall('.//testcase'):
        key=case.get('classname','')+'::'+case.get('name','')
        status=next((n.tag for n in case if n.tag in ('failure','error','skipped')),'passed')
        if rank[status]>=rank.get(result.get(key),-1):result[key]=status
    return result


def metric(text):
    tree=ast.parse(text)
    return {'lines':len(text.splitlines()),'functions':sum(isinstance(n,ast.FunctionDef) for n in ast.walk(tree)),
            'branches':sum(isinstance(n,(ast.If,ast.IfExp,ast.For,ast.While,ast.ExceptHandler,ast.BoolOp,ast.comprehension)) for n in ast.walk(tree))}


def main():
    for label in ('baseline-full','candidate-full'):
        if not (OUT/label/'completion.json').exists():raise SystemExit(label+' still incomplete')
    baseline=cases(OUT/'baseline-full/results.xml');current=cases(OUT/'candidate-full/results.xml');bad={'error','failure'}
    delta={'baseline_counts':dict(Counter(baseline.values())),'candidate_counts':dict(Counter(current.values())),
           'new_failures':[k for k,v in current.items() if v in bad and baseline.get(k) not in bad],
           'persistent_failures':[k for k,v in current.items() if v in bad and baseline.get(k) in bad],
           'recovered':[k for k,v in baseline.items() if v in bad and current.get(k)=='passed'],
           'missing':sorted(set(baseline)-set(current)),
           'newly_skipped':[k for k,v in current.items() if v=='skipped' and baseline.get(k) not in (None,'skipped')],
           'added':sorted(set(current)-set(baseline))}
    write('regression-delta.json',delta)
    occurrences={}
    for label in ('baseline-full','candidate-full'):
        raw=ET.parse(OUT/label/'results.xml').findall('.//testcase')
        occurrences[label]=Counter(c.get('classname','')+'::'+c.get('name','') for c in raw)
    write('regression-occurrences.json',{'note':'Compare XML testcase identities and multiplicity. If an identity repeats, aggregation preserves the worst status. Pytest separately reports 26 passing subtests in both runs; suite tests attributes include those subtests.',
        'baseline_xml_cases':sum(occurrences['baseline-full'].values()),'candidate_xml_cases':sum(occurrences['candidate-full'].values()),
        'missing_occurrences':dict(occurrences['baseline-full']-occurrences['candidate-full']),
        'added_occurrences':dict(occurrences['candidate-full']-occurrences['baseline-full'])})
    if delta['new_failures'] and not (OUT/'new-failure-attribution.json').exists():
        raise SystemExit('New failures require attribution before finalizing')
    subprocess.run([sys.executable,'-X','utf8',str(ROOT/'experiments/authority_convergence/audit.py')],cwd=ROOT,check=True)
    rows=[];patch=[]
    for rel in PRODUCTION:
        before=(OLD/rel).read_text(encoding='utf-8');after=(ROOT/rel).read_text(encoding='utf-8')
        diff=list(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel));patch.extend(diff)
        rows.append({'file':rel,'before':metric(before),'after':metric(after),'before_sha256':sha(OLD/rel),'after_sha256':sha(ROOT/rel),
                     'added':sum(s.startswith('+') and not s.startswith('+++') for s in diff),'removed':sum(s.startswith('-') and not s.startswith('---') for s in diff)})
    added=sum(r['added'] for r in rows);removed=sum(r['removed'] for r in rows)
    write('production-metrics.json',rows)
    extras=['tests/test_action_loop_convergence.py']+[p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'experiments/authority_convergence').glob('*.py'))]
    for rel in extras:
        patch.extend(difflib.unified_diff([],(ROOT/rel).read_text(encoding='utf-8').splitlines(True),fromfile='/dev/null',tofile='b/'+rel))
    write('task-only.patch',''.join(patch))
    checked=subprocess.run(['git','apply','--reverse','--check',str(OUT/'task-only.patch')],cwd=ROOT,capture_output=True,text=True)
    write('patch-check.json',{'exit_code':checked.returncode,'stderr':checked.stderr})
    if checked.returncode:raise SystemExit('patch verification failed')
    preservation={}
    for key,base,manifest in [('original',Path('D:/CGKN'),'original-root-hashes.json'),('prior_worktree',OLD,'baseline-source-hashes.json')]:
        source=load(manifest);changed=[r['path'] for r in source if not (base/r['path']).is_file() or sha(base/r['path'])!=r['sha256']]
        preservation[key]={'checked':len(source),'changed':changed}
    inherited_changed=[r['path'] for r in load('baseline-source-hashes.json') if r['path'] not in PRODUCTION and (not (ROOT/r['path']).is_file() or sha(ROOT/r['path'])!=r['sha256'])]
    preservation['inherited_unexpected_changes']=inherited_changed
    write('preservation.json',preservation)
    if inherited_changed or any(preservation[k]['changed'] for k in ('original','prior_worktree')):raise SystemExit('source preservation mismatch')
    write('change-manifest.json',{'purpose':'review artifact, not canonical publication receipt','head':'0bd7134ade87cb6ece13f8f7868860cd2c3ba67c',
        'baseline':str(OLD),'worktree':str(ROOT),'production':rows,'added_files':[{'path':p,'sha256':sha(ROOT/p),'lines':len((ROOT/p).read_text(encoding='utf-8').splitlines())} for p in extras],
        'patch_sha256':sha(OUT/'task-only.patch'),'commit':None,'push':False})
    write('architecture-before-after.md',f'''# 执行责任收敛前后

|指标|之前|之后|解释|
|---|---:|---:|---|
|可调用项目路径类别|4|4|Agent 应用、默认 Provider、历史 Dynamic、独立 conversation；没有删除完整外层路径|
|通用消息/动作回合控制实现|2|1|Dynamic 内层循环退出；两个入口复用既有 conversation 模块中的共同控制器|
|审阅的控制实现单元（分层，不等于项目引擎）|7|6|Project Agent、DAG、Provider pipeline、Dynamic 外层、两处 action loop、Artifact runner|
|回合/动作迭代循环体|4|2|两个 turn loop 和两个 action loop 收敛成一对|
|独立权限/结束政策|2|2|不是为了减少数量抹去政策差异|
|项目状态、预算、DAG 调度权威|不变|不变|不同责任没有硬合并|
|兼容公开入口|2|2|原签名保留；均不再有独立回合调度体|
|入口到回合控制器委派层|0|1|明确增加一个内部函数调用层，无新 facade 类或框架|
|生产依赖新增/删除|0|0|不引入 Harness/SDK|

两文件生产代码：增加 {added} 行、删除 {removed} 行、净删除 {removed-added} 行。函数定义净增 {sum(r['after']['functions']-r['before']['functions'] for r in rows)}，AST 分支节点净增 {sum(r['after']['branches']-r['before']['branches'] for r in rows)}（含 if/ternary/boolean/comprehension/exception/loop）。不能声称所有复杂度指标下降：收益是集中一套完整控制算法，成本是显式政策分支与委派。逐文件指标和哈希见 change-manifest.json。

新增回合反馈/通用取消处理的控制修改点从两处变一处；权限、prompt 与阶段审计仍各有维护位置，不能概括为所有新功能只改一个文件。消息/动作协议和 session JSONL 结构未新增；只忽略比较中的时间戳、临时根路径和 JSON 字典键顺序，事件次序、模型输入、动作、错误和回合数仍匹配。

新增 9 个永久边界测试。实验/证据工具的代码体积单列于 change-manifest.json，不混入生产净删除。旧控制器仅从冻结的基线 AST 装载用于对照，不注册成运行分支；试验 candidate 模块已改为引用唯一生产实现，原试验源码保留为不可执行 txt 证据。
''')
    decisions=load('duplicate-authorities.json')
    text=['# 迁移决定','','A 原架构、B 复用 CGKN 内部唯一控制器、C 外部 bounded Harness 均有比较。只有 B 完成可执行资格；C 是未试验的架构选项，未安装也未声称通过。','']
    for r in decisions:
        text += ['## '+r['responsibility']+' — '+r['decision'],'',r.get('blocker',r.get('scope','')),'',json.dumps(r,ensure_ascii=False,indent=2),'']
    text += ['## 完成边界','','CONVERGED 指完整消息/动作回合控制责任 2→1；不是把第二个循环藏到 facade 后。旧 _run_agent_turn 的 retry/parse/action/return 迭代体已删除，剩余闭包只提供上下文和单次动作政策。外层 Dynamic manifest 编排及正式 Provider 路线仍保留；不宣称全系统只有一个执行引擎。', '',
             '当前 ArtifactModuleRunner 的类型化缓存/覆盖端口/副作用计数与 DAGRunner 的 leaf/checker/运行身份不等价；直接替换会要求跳过现有独立准入或迁移状态。项目 Agent 不能被角色 manifest loop 替换，反向替换也尚无可验证的目标/契约映射。没有为了 KPI 转做辅助函数去重。']
    write('migration-decisions.md','\n'.join(text)+'\n')
    perf=load('controller-performance.json')
    watchdog=load('watchdog-pairs/summary.json')
    write('convergence-benchmarks.json',{'baseline':'two original controller bodies from immutable baseline AST','candidate':'one production controller with existing policy callbacks',
        'shared_trial':'loop-trial-corrected/results.xml:36 passed; includes actual multi-file pytest repair and independent re-test',
        'independent_business_oracle':'independent-business-oracle-corrected/results.xml: both modes compare old/new with a fixed external four-case Oracle; constant-return implementation passes generated self-test but is rejected by the external Oracle',
        'promoted_boundaries':'45 passed (36 shared + 9 permanent)', 'trace':'runtime-controller-trace.json:7 manifest and 2 standalone calls enter same controller',
        'faults':['timeout','UNKNOWN-shaped generic exception (control equivalence only)','structured UNKNOWN through real loopback Gateway and budget ledger: old manifest 2 POST, candidate 1 POST, outer fallback blocked','partial JSON','empty/malformed response','failed tool','disallowed action','executor exception','cancellation','history reload','budget exhaustion boundary','package batch behavior'],
        'performance':perf,'cost':{'paid_posts':0,'api_rmb':0,'live':'LIVE_NOT_VERIFIED','tokens':'NOT_MEASURED: fixed outputs, not real models','observer_or_verification_product_overhead_added':0},
        'watchdog':{'trials':len(watchdog),'statuses':dict(Counter(r['status'] for r in watchdog)),'verdict':'WATCHDOG_UNRESOLVED','scope':'two source versions, alternating idle/eight bounded runtime loads; small sample, not statistical equivalence'},
        'complexity':rows,'regression':delta})
    receipts={}
    for label in ('baseline-full','candidate-full'):
        receipts[label]=load(label+'/completion.json')
    resources={}
    for label in ('baseline-full','candidate-full'):
        run=OUT/label
        if not (run/'resource-completion.json').exists():raise SystemExit(label+' resource monitor still incomplete')
        samples=[json.loads(line) for line in (run/'resources.jsonl').read_text(encoding='utf-8').splitlines()]
        resources[label]={'completion':load(label+'/resource-completion.json'),
            'samples':len(samples),'first_sample_epoch':samples[0]['epoch'],'last_sample_epoch':samples[-1]['epoch'],
            'peak_observed_processes':max(len(s['processes']) for s in samples),
            'peak_observed_threads':max(sum(p['threads'] for p in s['processes']) for s in samples),
            'peak_observed_handles':max(sum(p['handles'] for p in s['processes']) for s in samples),
            'peak_observed_rss_bytes':max(sum(p['rss'] for p in s['processes']) for s in samples)}
        if resources[label]['completion']['surviving_observed_identities']:
            raise SystemExit(label+' has surviving observed processes requiring investigation')
    write('resource-summary.json',{'scope':'Owned descendants only. Baseline monitoring began after suite start; candidate monitoring began at launch. Peaks are descriptive, not equal-window performance estimates. Sampling may miss short-lived children.', 'runs':resources})
    coverage={
        'real_multifile_pytest_repair':'experiments.authority_convergence.test_loop_trial::test_real_multifile_pytest_failure_then_repair',
        'dag_dependency_parallel_affected_retry':'tests.runtime.test_parallel_qualification::test_barrier_failure_isolation_retry_and_join',
        'real_file_sqlite_concurrency_conflicts':'tests.runtime.test_parallel_qualification::test_real_local_process_file_sqlite_and_conflict',
        'interrupt_completed_sibling':'tests.runtime.test_parallel_qualification::test_real_controller_process_loss_preserves_completed_sibling',
        'scope_before_write':'tests.runtime.test_execution_continuity::test_out_of_scope_write_is_rejected_before_any_write',
        'illegal_worker_output':'tests.executors.test_llm_executor',
        'independent_oracle_no_false_pass':'tests.agent.test_goal_acceptance_integration',
        'consumer_ports_observer':'tests.agent.test_observer_references',
        'knowledge_reuse':'tests.runtime.test_knowledge_feedback_qualification',
        'unknown_budget_duplicate_submission':'tests.providers.test_domestic_repair',
        'sse_partial_interrupt':'tests.providers.test_streaming_sse',
        'queue_cancel':'tests.providers.test_progress_queue_cancel',
        'stale_output_repair':'tests.runtime.test_execution_continuity::test_partial_two_files_retained_and_continued_without_rewrite',
        'public_delivery_evidence':'tests.test_canonical_delivery_receipt',
    }
    evidence=[]
    trial=cases(OUT/'loop-trial-corrected/results.xml')
    for responsibility,prefix in coverage.items():
        before={k:v for k,v in baseline.items() if k.startswith(prefix)}
        after={k:v for k,v in current.items() if k.startswith(prefix)}
        evidence.append({'responsibility':responsibility,'baseline':before,'candidate':after,'shared_old_new_trial':{k:v for k,v in trial.items() if k.startswith(prefix)},'claim':'existing canonical capabilities remain separately owned; this does not imply legacy action loop itself gained DAG oracles'})
    write('functional-evidence.json',evidence)
    write('regression-report.md',f'''# 全量回归

新鲜基线：{delta['baseline_counts']}。候选：{delta['candidate_counts']}。
新增失败/错误 {len(delta['new_failures'])}；持续失败/错误 {len(delta['persistent_failures'])}；旧失败本次通过 {len(delta['recovered'])}；缺失 {len(delta['missing'])}；新增 skip {len(delta['newly_skipped'])}。完整案例列表 regression-delta.json；相同环境配置的两次完整执行串行进行，不拿前轮不完全相同环境的报告做因果比较。

相对前轮报告，新鲜基线新增三个失败（两个 watchdog 和一个 CLI Oracle），恢复一个历史失败，净增两个；精确列表 baseline-vs-prior.json。CLI Oracle 失败来自本轮观测工具：Oracle 环境白名单保留 PYTHONPATH，却移除 CGKN_TRIAL_EVIDENCE，令 sitecustomize 写入 KeyError 到 stderr；原全量数据不改写。oracle-instrumentation 保存复现和不依赖该变量的离线守卫对照。原全量守卫在此类环境被过滤的 Oracle 子进程中未安装，不能声称对子进程网络隔离作了完整证明；相关 fixture 运行已知本地测试程序。全量运行中未切换守卫。

原始 pytest 退出与包装器退出：
```json
{json.dumps(receipts,ensure_ascii=False,indent=2)}
```

命令见 baseline.md 及各 start.json。没有删除原测试、修改断言或新增 skip。原始日志在各 pytest.log；凭据断言正文脱敏前 SHA 保留，测试名/状态不变。首次实验 34 PASS / 2 fixture setup FAIL 为重复 mkdir；修正实验夹具后 36 PASS。生产迁移后 54 PASS / 3 历史 skip，最终边界与共享试验 45 PASS。

功能证据按多节点、并发、恢复、独立验收、端口/Observer、知识、UNKNOWN、预算、SSE、取消、交付列在 functional-evidence.json。失败/跳过不会被标为能力成功；验证旧能力仍使用原有独立 Oracle，不以 Worker 报告替代。

真实小项目的加强验收在 independent-business-oracle-corrected：两种模式各执行旧/新版本，项目外固定业务 Oracle 验证正负数、零及不同输入。负对照 return 5 可以通过生成的自测，但被外部 Oracle 拒绝；修复后的产物通过。初始共享试验中重复执行生成测试的记录仍保留，不把它单独当成充分的独立业务验收。首次补充试验因 pytest ini 对 Windows 反斜线路径的解析导致两例收集错误；仅修正实验路径为正斜线后重跑，原失败记录保留。

watchdog：**WATCHDOG_UNRESOLVED**。全量 hook 未识别 -m 的采样缺口公开保留；进程监控及临时状态文件有效。补充 {len(watchdog)} 次带有效栈采样的相同负载配对，不扩大原 timeout/断言。原始 stop-timeout 没有可确认根因，即使后续通过也不宣布修复。报告恢复案例仅是观测，不能全部归因于代码。

子进程、线程、句柄、RSS 逐秒记录与退出后存活身份检查见 resource-summary.json 及两次全量的 resources.jsonl。基线监控晚于进程启动，不能用全量峰值差异宣称性能改善。八次补充配对无残留进程、无存活负载线程；Windows CreateProcess 阻塞现场见 watchdog-analysis.json。

LIVE_NOT_VERIFIED，真实付费请求 0。历史失败仍存在，未宣称全仓库全绿或 PRODUCT_READY。UNKNOWN 的宽预算发现记录旧版和初始候选各两次 POST；最终控制器使用已有 rework_blocked 交给外层，直接 step 和完整 pipeline 均只有一次 POST。provider-boundary-after-fix 保留旧版违反同一断言的失败，没有将旧版错误预期改成通过。
''')
    write('final-report.md',f'''# Execution Authority Convergence — 有边界的实际收敛

总体结论：**PARTIAL_CONVERGENCE**。完成一项有共享行为证据的完整回合控制责任收敛；未满足“减少默认项目路径”这一更广目标，不宣称全系统架构瘦身完成。

1. **多少机制**：四类可调用项目路径，另有 artifact flow；按分层控制实现审阅为 7→6。不同层的控制器不能相加解释为七套项目引擎。
2. **相同责任**：确认两套完整的模型/消息/动作/反馈/修复回合控制承担同一通用责任；权限和结束条件有差异。
3. **必须分开**：项目 Agent 与 bounded Executor；预算与项目状态；独立业务验收与 Worker；artifact typed flow 与当前 leaf/checker DAG 不能直接视作同一协议。
4. **可合并范围**：standalone conversation 和 Dynamic 内层 action loop；保留模式政策，不保留第二套调度算法。
5. **实际合并**：两个公开入口都转交 conversation._run_action_loop；动态模块旧回合循环已删除，runtime trace 记录两种调用者。
6. **是否删除权威**：是，完整消息/动作回合调度实现 2→1。外层 Dynamic Pipeline 没有退出，项目级和 DAG 权威没有减少，不能声称整个系统统一完成。
7. **维护变化**：生产增加 {added} 行、删除 {removed} 行、净删除 {removed-added} 行。回合/动作循环体 4→2；两个政策保留，委派深度 +1，条件分支净增 7。9 个新边界测试，无新增生产依赖。
8. **业务能力**：36 旧/新共享试验包括真实多文件 pytest 失败修复；补充的 independent-business-oracle-corrected 在两种模式的旧/新产物上运行项目外固定 Oracle，四次均接受修复结果、拒绝自测通过的错误实现。原有 DAG、并发、权限、恢复、Oracle、预算、UNKNOWN、交付测试完整保留。逐项证据和历史失败见 functional-evidence.json，不能把历史失败写成成功。
9. **性能/可靠性/成本**：预热后各模式 10 次交替测量见 controller-performance.json；只测控制器开销，不宣称完整项目或模型质量提升。修复发现的 manifest UNKNOWN 自动重发：宽模拟预算下旧版 POST 2→新版 1，外层 fallback 被阻止；无新增 Observer 阶段，新增真实付费 POST 0，API ¥0.00，LIVE_NOT_VERIFIED。
10. **新风险**：共用代码现在需同时保持两种政策；已覆盖错误/部分响应/动作许可/取消/修复次数/结束条件。全量候选 {delta['candidate_counts']}，相对新鲜基线新增失败 {len(delta['new_failures'])}；不将有限回归等同所有动态路径无缺陷证明。
11. **watchdog**：WATCHDOG_UNRESOLVED。新基线自身出现恢复失败，保留日志/进程证据与补充配对；不能宣称原始 stop-timeout 修复。
12. **剩余阻碍**：正式 Provider pipeline 与产品 Agent 的状态身份/规划/交付兼容迁移；artifact cache/override/typed-port 对 DAG leaf/checker 的映射；各 bounded Worker 的权限和事务差异。外部 Harness 未通过替代资格，本轮未引入。

工作树：{ROOT}。分支 codex/execution-authority-convergence-20261101。HEAD 0bd7134ade87cb6ece13f8f7868860cd2c3ba67c。
原目录和前轮基线文件哈希未改，所有前轮合格修复继承；详见 preservation.json。只改两个生产文件，未推送/合并/发布/tag。唯一提交工具自动 push，因此没有绕过治理作本地 commit。

task-only.patch 相对前轮有效工作树，包含本轮生产代码、测试、实验工具；反向检查通过。change-manifest.json 是审阅证据，不是发布回执。完整证据哈希见 evidence-hashes.json。
''')
    manifests=[{'path':p.relative_to(OUT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='evidence-hashes.json' and '__pycache__' not in p.parts]
    write('evidence-hashes.json',manifests)
    print(json.dumps({'baseline':delta['baseline_counts'],'candidate':delta['candidate_counts'],'new_failures':len(delta['new_failures']),'net_removed':removed-added,'evidence_files':len(manifests)}))


if __name__=='__main__':main()
