"""Read-only source verification, task-only patch, regression delta and evidence hashes."""
from __future__ import annotations

import ast
from collections import Counter
import difflib
import hashlib
import json
import re
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
BASE=Path('F:/CGKN-LeanLoop-Baseline-20261101')
PRIOR=Path('D:/CGKN/.service_worktree/execution-authority-convergence-20261101')
ORIGINAL=Path('D:/CGKN')
OUT=ROOT/'artifacts/leanloop-v1'


def read(name): return json.loads((OUT/name).read_text(encoding='utf-8'))
def write(name,value): (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2) if not isinstance(value,str) else value,encoding='utf-8',newline='\n')
def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def cases(label):
    rows={}
    for case in ET.parse(OUT/label/'results.xml').iter('testcase'):
        key=case.get('classname','')+'::'+case.get('name','')
        status=next((tag for tag in ('error','failure','skipped') if case.find(tag) is not None),'passed')
        rows[key]=status
    return rows


def metrics(text):
    tree=ast.parse(text)
    return {'physical_lines':len(text.splitlines()),
        'nonblank_lines':sum(bool(line.strip()) for line in text.splitlines()),
        'functions':sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) for n in ast.walk(tree)),
        'branch_nodes':sum(isinstance(n,(ast.If,ast.For,ast.While,ast.Try,ast.IfExp,ast.Match)) for n in ast.walk(tree))}


def failures(label):
    rows={}
    for case in ET.parse(OUT/label/'results.xml').iter('testcase'):
        for tag in ('failure','error'):
            node=case.find(tag)
            if node is None: continue
            message=node.get('message','')
            normalized=re.sub(r'0x[0-9A-Fa-f]+','<address>',message)
            normalized=re.sub(r'pytest-\d+','pytest-<id>',normalized)
            normalized=normalized.replace(str(ROOT),'<source>').replace(str(BASE),'<source>')
            rows[case.get('classname','')+'::'+case.get('name','')]={'kind':tag,'message':message,'normalized_message':normalized}
    return rows


def main():
    baseline=read('baseline-source-hashes.json'); expected={row['path']:row['sha256'] for row in baseline}
    preservation={}
    for name,root,manifest in [('original',ORIGINAL,read('prior-original-root-hashes.json')),
                                ('qualified_prior',PRIOR,baseline),('fresh_baseline',BASE,baseline),
                                ('tested_candidate_python',ROOT,read('candidate-test-source-hashes.json'))]:
        mismatches=[r['path'] for r in manifest if not (root/r['path']).is_file() or sha(root/r['path'])!=r['sha256']]
        preservation[name]={'root':str(root),'checked_files':len(manifest),'mismatches':mismatches}
    changed=[name for name,digest in expected.items() if not (ROOT/name).is_file() or sha(ROOT/name)!=digest]
    allowed={'cgkn/agent/project_loop.py','cgkn/application/software_project/service.py',
        'cgkn/application/verification/executor.py','cgkn/runtime/dag_runner.py','cgkn/runtime/runner.py',
        'scripts/agent_conversation_loop.py','scripts/codex_conversation.py','scripts/dynamic_pipeline_runner.py',
        'scripts/run_agent_mvp.py','scripts/run_artifact_flow.py','scripts/run_local_pipeline.py','scripts/run_local_pipeline_impl.py'}
    unexpected=sorted(set(changed)-allowed)
    if unexpected: raise RuntimeError('Unexpected inherited source modifications: '+repr(unexpected))
    added=['cgkn/telemetry/lean.py','cgkn/telemetry/lean_policy.py','tests/test_leanloop.py','tests/leanloop_support.py']
    added += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'experiments/leanloop_v1').glob('*.py'))]
    patch=[];changes=[];complexity=[]
    for name in sorted(set(changed+added)):
        before=(BASE/name).read_text(encoding='utf-8') if name in expected else ''
        after=(ROOT/name).read_text(encoding='utf-8') if (ROOT/name).is_file() else ''
        patch.append('diff --git a/'+name+' b/'+name+'\n')
        if name not in expected: patch.append('new file mode 100644\n')
        patch.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
            fromfile='a/'+name if before else '/dev/null',tofile='b/'+name if after else '/dev/null'))
        changes.append({'path':name,'before_sha256':expected.get(name),'after_sha256':sha(ROOT/name) if after else None})
        if name.endswith('.py') and not name.startswith(('tests/','experiments/')):
            a=metrics(before);b=metrics(after)
            complexity.append({'path':name,'before':a,'after':b,'delta':{k:b[k]-a[k] for k in a}})
    write('task-only.patch',''.join(patch))
    checks={}
    for name,root,args in [('forward',BASE,[]),('reverse',ROOT,['--reverse'])]:
        completed=subprocess.run(['git','apply',*args,'--check',str(OUT/'task-only.patch')],cwd=root,capture_output=True,text=True)
        checks[name]={'exit_code':completed.returncode,'output':completed.stdout+completed.stderr}
    write('source-preservation.json',preservation)
    totals={key:sum(row['delta'][key] for row in complexity) for key in ('physical_lines','nonblank_lines','functions','branch_nodes')}
    write('complexity.json',{'files':complexity,'production_delta':totals,'new_production_modules':2,
        'new_planners':0,'new_agent_loops':0,'new_DAGs':0,'new_schedulers':0,'new_result_caches':0,
        'default_execution_steps_removed':0,'qualified_example_component_calls':[2,1],
        'interpretation':'Additive feedback feature, not net structural slimming; default OBSERVE. V3 not qualified.'})
    write('change-manifest.json',{'base_head':'0bd7134ade87cb6ece13f8f7868860cd2c3ba67c',
        'baseline_manifest_sha256':sha(OUT/'baseline-source-hashes.json'),'changes':changes,
        'patch_sha256':sha(OUT/'task-only.patch'),'patch_checks':checks,'commit':None,'push':False,
        'publication':'Not attempted: sole canonical publisher couples staging/commit/push; no bypass.'})
    if not (OUT/'candidate-full/results.xml').exists() or not (OUT/'candidate-full/completion.json').exists():
        print(json.dumps({'phase':'prepared; full regression pending','production_delta':totals,'checks':checks,'preservation':preservation}))
        return
    if read('candidate-full/completion.json')['postprocessing']!='complete':
        raise RuntimeError('Final regression postprocessing is not complete')
    old=cases('baseline-full');new=cases('candidate-full')
    delta={'baseline':dict(Counter(old.values())),'candidate':dict(Counter(new.values())),
        'new_failures':sorted(k for k,v in new.items() if v in {'error','failure'} and old.get(k) not in {'error','failure'}),
        'persistent_failures':sorted(k for k,v in new.items() if v in {'error','failure'} and old.get(k) in {'error','failure'}),
        'recovered':sorted(k for k,v in old.items() if v in {'error','failure'} and new.get(k)=='passed'),
        'missing':sorted(set(old)-set(new)), 'added':sorted(set(new)-set(old)),
        'new_skips':sorted(k for k,v in new.items() if v=='skipped' and old.get(k)!='skipped')}
    write('regression-delta.json',delta)
    old_fail=failures('baseline-full');new_fail=failures('candidate-full')
    write('persistent-failure-comparison.json',[{'test':key,'baseline':old_fail[key],'candidate':new_fail[key],
        'same_normalized_message':old_fail[key]['normalized_message']==new_fail[key]['normalized_message']}
        for key in delta['persistent_failures']])
    write('regression-report.md','# Fresh paired full regression\n\n'+json.dumps(delta,indent=2)+'\n\n'
        'Both full runs used the same Python, F: drive, offline legacy profile, disabled plugin autoload, external socket denial and watchdog stack capture. Suites ran serially. Each suite includes its original controlled local HTTP/SSE and subprocess loads; OS scheduling and elapsed time are not identical. This is a functional comparison, not a suite-speed benchmark. Raw exit codes are retained before redaction. Credential assertion text was redacted with raw content hashes preserved.\n\n'
        'Resource-completion files record observed process identities after completion; one-second sampling cannot prove absence of unseen short-lived processes. Watchdog remains UNRESOLVED. Baseline itself differs from historical results; all classification uses this fresh baseline. No timeout, assertion or required gate was weakened.\n')
    write('final-verification.json',{'source_preservation_pass':not any(r['mismatches'] for r in preservation.values()),
        'patch_checks_pass':all(r['exit_code']==0 for r in checks.values()),
        'no_new_regression':not delta['new_failures'] and not delta['missing'] and not delta['new_skips'],
        'watchdog':'UNRESOLVED','paid_api_posts':0,'default_mode':'OBSERVE'})
    overhead=read('self-overhead.json')
    benchmark=overhead['summary_medians']
    paired=read('self-overhead-paired.json')
    cost=read('experiment-total-cost.json')
    retained={}
    for folder in OUT.glob('qualification*'):
        if not folder.is_dir():continue
        for path in folder.rglob('*.json'):
            if not re.fullmatch('[0-9a-f]{64}',path.stem):continue
            try:receipt=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            if isinstance(receipt,dict) and 'experiment_duration_ms' in receipt and 'receipt_hash' in receipt:
                retained[receipt['receipt_hash']]={'path':str(path.relative_to(OUT)),
                    'wall_ms':receipt['experiment_duration_ms'],'cpu_ms':receipt['experiment_cpu_ms'],
                    'trials':len(receipt['trials']),'status':receipt['status']}
    write('retained-experiment-costs.json',{'completed_receipts':list(retained.values()),
        'recorded_wall_ms':sum(r['wall_ms'] for r in retained.values()),
        'recorded_cpu_ms':sum(r['cpu_ms'] for r in retained.values()),
        'recorded_trials':sum(r['trials'] for r in retained.values()),
        'limitation':'Lower bound over persisted offline qualification receipts, deduplicated by receipt hash. Earlier unfinished evaluations, pytest and research are not counted as per-run optimizer costs; their logs/completion receipts remain separate.'})
    sample_count=overhead['samples_per_mode']
    exclusions='按运行时间排除与独立调用审计重叠的整组，原始记录保留。' if overhead.get('excluded_pair_indices') else '无样本排除。'
    interval=paired['bootstrap_mean_95_percent_interval_ms']
    timing_verdict='本次测量 AUTO 更慢，经济性推广拒绝。' if interval[0]>0 else '未确认可推广的净收益。'
    table=['# LeanLoop 自身开销\n',f'每种模式 2 次预热、{sample_count} 次有效正式样本；按配对顺序轮换。{exclusions}下表为中位数。\n',
        '| 模式 | Run + Oracle 毫秒 | 父进程 CPU 毫秒 | 父进程 Python 峰值字节 | 记录的优化器毫秒 | 实际转换调用 |',
        '|---|---:|---:|---:|---:|---:|']
    for mode in ('OFF','OBSERVE','AUTO_QUALIFIED'):
        row=benchmark[mode]
        table.append(f"| {mode} | {row['whole_task_oracle_ms']:.2f} | {row['parent_cpu_ms']:.2f} | {row['parent_python_peak_bytes']:.0f} | {row['optimization_overhead_ms']:.2f} | {row['component_calls']:.0f} |")
    table.extend(['',f"配对 AUTO 减 OFF 均值 {paired['paired_mean_ms']:.2f} ms；探索性 bootstrap 95% 区间 {interval} ms，10,000 次重采样、固定种子 20261101。{timing_verdict}",
        '',f"最终资格和负对照共 {cost['paired_trial_runs']} 次试验运行，累计实验墙钟 {cost['sum_experiment_wall_ms']:.2f} ms、父进程 CPU {cost['sum_parent_cpu_ms']:.2f} ms。没有已确认的正净收益，因此不计算回本次数。",'',
        '边界：计时包括既有 runner、项目文件、派生报告和独立 Oracle 子进程；不含父 Python 启动/import 时间。CPU 和 tracemalloc 只覆盖父进程，内存不是全进程 RSS。冷预热样本保留在 self-overhead.json，不把热运行推广为所有 CLI 冷启动表现。',
        '', 'OFF 仍写最小停用报告外壳；它不做候选身份分析或改变原执行。优化器自身模型调用/Token/API 费用为 0；未知业务金额保持 null，不按 CPU 任意折算人民币。最终指标的再次持久化未包含在报告自身计时中。',
        '', '更早的完整消融凭据也按哈希去重汇总在 retained-experiment-costs.json；它是已留存实验成本的下界，不隐去失败候选，也不把开发回归费用混成每次业务 Run 的费用。',
        '', '测量专用策略已停用；默认仍为 OBSERVE。100 ms 普通开销上限和超限恢复已测试。1,000 ms 仅用于限额离线测量，不构成生产默认放宽。实际调用数另由 actual-function-call-evidence.json 中的代码对象追踪确认；DAG 节点仍为两个。'])
    write('self-overhead-report.md','\n'.join(table)+'\n')
    qualified=not delta['new_failures'] and not delta['missing'] and not delta['new_skips'] and all(r['exit_code']==0 for r in checks.values()) and not any(r['mismatches'] for r in preservation.values())
    final=f'''# CGKN LeanLoop V1 实施报告

结论：{'V0/V1 与限定范围 V2 功能通过；V2 经济性推广拒绝，策略暂停；V3 仅候选。' if qualified else '资格未完成：存在回归或补丁检查问题，禁止扩大启用。'}

本轮继承前轮 PARTIAL_CONVERGENCE：消息/动作控制器二合一、净删除 33 行和 UNKNOWN 单次 POST 修复仍在。它们不是本轮新增成果，也不代表架构瘦身已完成。本轮新增反馈能力，默认 OBSERVE，没有减少默认执行路径。

## 已实际完成

1. **自动报告（V0）**：在审计到的 AgentProjectLoop、DAGRunner、软件项目轮次、ArtifactModuleRunner、正式 Provider/Conversation 和兼容会话入口接入最终报告。成功、可控失败、UNKNOWN、预算终止、取消和异常都有覆盖；真正进程退出后在下一次进入相同 Run 时由原 checkpoint 补偿。文件系统不可写时记录显式错误并保留原任务行为；不存在“任何崩溃都能立即生成报告”的保证。
2. **自动发现与消融（V1）**：从实际 Component 执行记录识别重复输入转换，运行 4 个固定案例 × 原版/候选版 = 8 次共享独立 CSV Oracle 对照。正例通过、错误输出和缺文件负例拒绝，确定性产物哈希一致。高风险模型、必需验收、UNKNOWN/预算等候选不获准自动裁剪。评价是显式离线操作，普通业务 Run 不暗中重放工作。
3. **限定运行时复用（V2）**：现有 CSV 软件项目案例经两个真实 AST 转换，后续显式批准的 Run 从 2 次组件函数调用降到 1 次，独立 Oracle 仍通过。复用现有 ArtifactCache/ArtifactStore，两个节点仍各有自己的产物及生产者身份。这个重复转换由资格案例构造，并非声称在默认生产项目中发现了普遍重复。没有全局开启 AUTO。
4. **恢复**：原独立 Oracle 检出人工制造的退化后撤销匹配策略，下一次 Run 完整执行 2 次并通过验收。源代码、环境、任务类型、契约、时效、证据、缓存身份变化都会阻止复用。损坏快照降为观察；旧 Run 的撤销不能覆盖新策略。不可逆副作用没有被假装撤回。
5. **结构性减法（V3）**：只输出带缺失证明的源代码候选。没有为了删行而删除动态入口、公开兼容行为、状态或执行权威。

## 新鲜完整回归

| 结果 | 修改前 | 修改后 |
|---|---:|---:|
| passed | {delta['baseline'].get('passed',0)} | {delta['candidate'].get('passed',0)} |
| failed | {delta['baseline'].get('failure',0)} | {delta['candidate'].get('failure',0)} |
| errors | {delta['baseline'].get('error',0)} | {delta['candidate'].get('error',0)} |
| skipped | {delta['baseline'].get('skipped',0)} | {delta['candidate'].get('skipped',0)} |

逐测试 ID：新增失败 {len(delta['new_failures'])}；旧失败恢复 {len(delta['recovered'])}；缺失 {len(delta['missing'])}；新增 skip {len(delta['new_skips'])}；新增测试 {len(delta['added'])}。完整列表、命令、退出码、资源监测和环境限制见 regression-report.md、regression-delta.json 与两个 full 目录。本仓库仍有既有失败，不能宣称全仓库全绿或 PRODUCT_READY。watchdog 原始问题仍为 UNRESOLVED；本次基线多次采样落在 Windows CreateProcess 内，尚无已证明根因。

## 实际成本与复杂度

每种模式 2 次预热、{sample_count} 次有效交错顺序样本，包含真实文件写入和独立 Oracle 子进程；{exclusions}总耗时中位数 OFF={benchmark['OFF']['whole_task_oracle_ms']:.2f} ms、OBSERVE={benchmark['OBSERVE']['whole_task_oracle_ms']:.2f} ms、AUTO={benchmark['AUTO_QUALIFIED']['whole_task_oracle_ms']:.2f} ms。AUTO 减 OFF 的配对均值差 {paired['paired_mean_ms']:.2f} ms，探索性 95% 区间 [{paired['bootstrap_mean_95_percent_interval_ms'][0]:.2f},{paired['bootstrap_mean_95_percent_interval_ms'][1]:.2f}] ms。父进程 CPU 中位数 OFF={benchmark['OFF']['parent_cpu_ms']:.2f} ms、AUTO={benchmark['AUTO_QUALIFIED']['parent_cpu_ms']:.2f} ms。**{timing_verdict}** 不能把组件次数减半说成任务提速一半。

优化器日常额外模型调用/Token/API 费用为 0；任务真实费用为未知，保留 null。内存报告为父进程 tracemalloc 峰值，不冒充全进程 RSS；子进程资源由整套回归采样另记。消融耗时独立记账。一次默认 100 ms 上限实验在约 105.6 ms 处正确撤销策略；后续 1,000 ms 限额只用于离线测量，测量结束后已停用，不能据此提高生产默认限额。

额外故障注入发现并修复三个实际缺陷：OFF 模式可选身份分析错误会误伤组件执行；同目录嵌套观测包装器会误捕获业务异常并再次调用业务函数；批准时旧环境消融凭据可被绑定至新环境，现已在批准和运行时双重拒绝。嵌套包装器缺陷用真实文件副作用证明修复前写入 2 次、修复后 1 次，并测试三种模式下 UNKNOWN 异常和受控返回均不重复执行。新增源文件与已加载函数代码身份、核心运行环境哈希、原生缓存保守复用、策略冻结和不可写元数据测试。三次修复前中止的全量运行分别保存，绝不计作完整通过；此处表格仅使用最终冻结源代码全量结果。详见 optional-analysis-recovery.json、nested-once-recovery.json。

生产代码净增加 {totals['physical_lines']} 行（非空 {totals['nonblank_lines']} 行）、函数增加 {totals['functions']}、分支节点增加 {totals['branch_nodes']}；新增生产模块 2 个。新增 Planner、Agent Loop、DAG、Scheduler、结果缓存、项目状态权威均为 0。精确文件对比在 complexity.json。此次是有成本的反馈机制建设，**不是结构性架构瘦身达标**。

## 保护、限制和下一步

永久保护 Gateway 预算、UNKNOWN 防重发、权限/外部副作用审批、必要业务 Oracle、交付门禁、核心证据、强制策略及安全取消恢复。原正式交付链仍是 Provider 生成 → 输出校验 → finalization → local_packager → public_delivery_gate → delivery_manifest。Worker 成功声明不作独立验收依据。

跨运行聚合读取最多 100 个调用者选择的已有报告，没有第二套数据库。随机审计没有被虚构为已实现；本轮使用固定正负对照、保留集及策略到期检查。纯函数标记需要可信代码审计，不能证明任意 Python 无副作用。消融时间预算在既有调用之间检查，调用者仍须提供自身有界的 runner；没有新建抢占调度器。

后续优先在既有 Project Corpus 中积累真实默认任务的候选，计入源代码哈希、缓存和报告成本，只有端到端收益及质量证据充分时再按任务启用。减少投影/持久化开销优先于新增优化 Agent。ArtifactFlow 与规范 DAG、Provider 会话生命周期等结构候选必须先补齐动态调用、兼容和故障证据，不凭低调用量删除。

## 交付与治理

隔离工作树 F:/CGKN-LeanLoop-V1-20261101；分支 codex/leanloop-v1-20261101；继承基准和所有修改哈希在 change-manifest.json。原项目 1,377 个清单文件、前轮 1,412 个文件、新鲜基线 1,412 个文件均按原清单核验，详见 source-preservation.json。task-only.patch 相对本轮有效基线，正反应用检查结果在 manifest。未 commit、push、merge 或 release；仓库唯一发布工具拥有提交和推送，不绕过它。新增真实付费 API POST=0；未安装新框架，未改全局代理或密钥。

主要证据：architecture.md、step-observation-schema.json、candidate-discovery.json、ablation-results.json、policy-state-machine.md、lean-policy.example.json、sample-run/、runtime-pruning-evidence.json、actual-function-call-evidence.json、nested-once-recovery.json、negative-controls.json、self-overhead-report.md、regression-report.md、task-only.patch、evidence-hashes.json。
'''
    write('final-report.md',final)
    write('acceptance-answers.md',f'''# 十二项最终问题

| 问题 | 实证回答 |
|---|---|
| 1. 每次真实运行自动报告？ | 已审计正式入口接入；成功、可控失败、UNKNOWN、取消及异常有测试。硬退出由下一次进入补偿；无写权限或标记前崩溃不能保证生成。实际入口样本见 entrypoint-reports/。 |
| 2. 主动发现未指定冗余？ | 对实际记录自动按输入、契约、源码和环境识别；没有指定节点对。但资格案例的人为重复转换不代表发现了既有默认生产路径冗余。 |
| 3. 独立判断步骤价值？ | 使用原 OracleSpec、正负例、保留集及组合消融；Worker 声明不作判据。未证明任意高风险模型步骤可删。 |
| 4. 真正跳过或复用？ | 精确代码对象追踪为 2→1 次调用；原 DAG 仍为 2 个节点，产物身份独立。 |
| 5. 降低完整成本？ | 否。本次 AUTO 减 OFF 配对平均 {paired['paired_mean_ms']:.2f} ms；策略暂停，经济性推广拒绝。未知金额不视为零。 |
| 6. 未损害必要验收？ | 限定案例沿用原独立 Oracle，正例通过、负例拒绝；全量新增失败 {len(delta['new_failures'])}。有限证据不等于所有任务无风险。 |
| 7. 错误裁剪与恢复？ | 注入退化使独立 Oracle 失败并撤销匹配策略，随后恢复 2 次执行；无权写策略时仅能保护当前执行并显式报告，不能承诺持久撤销。 |
| 8. 自身复杂度？ | 生产净增 {totals['physical_lines']} 行、{totals['functions']} 个函数、{totals['branch_nodes']} 个分支节点、2 个模块；默认路径减少 0。 |
| 9. 重复执行或状态权威？ | 新增 Planner、Agent Loop、DAG、Scheduler、结果缓存和项目状态权威均为 0；报告是派生物，策略是配置。 |
| 10. 永不自动裁剪？ | 预算、UNKNOWN、权限、外部副作用审批、必需业务 Oracle、交付门禁、核心证据、强制策略、安全取消恢复。 |
| 11. 未来结构删除候选？ | ArtifactFlow 与规范 DAG 的兼容执行表面、Provider 会话生命周期投影；动态入口、契约和故障等价证据不足，未删除。 |
| 12. 如何保持轻量？ | 先积累既有 Corpus 的真实重复证据，减少投影和持久化成本，继续复用现有缓存与 Oracle；不增加优化 Agent，不以步数下降代替净成本测量。 |

三类实施缺陷已保留修复前证据：可选分析误伤原执行、同目录嵌套异常重复执行、旧环境资格误批准。中止批次不计入最终全量结果。watchdog 仍为 UNRESOLVED。
''')
    write('evidence-hashes.json',[{'path':p.relative_to(OUT).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size}
        for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='evidence-hashes.json' and '__pycache__' not in p.parts])
    print(json.dumps({'production_delta':totals,'regression':{k:v for k,v in delta.items() if k not in {'persistent_failures','added'}},'checks':checks}))


if __name__=='__main__':main()
