"""Reproducible task-only metrics, patch and report generation; never stages files."""
import ast
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT.parent / 'substrate-migration-20261101'
OUT = ROOT / 'artifacts/substrate-replacement-v2'
FILES = ['cgkn/execution/contracts.py', 'cgkn/orchestration/capability_tree.py',
         'cgkn/orchestration/execution_dag.py', 'scripts/check_connectivity.py',
         'cgkn/providers/legacy_transport.py', 'cgkn/executors/local.py']


def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8-sig'))


def write(name, value):
    (OUT / name).write_text(value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8', newline='\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(text):
    tree = ast.parse(text)
    return {'lines': len(text.splitlines()),
            'functions': sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)),
            'branches': sum(isinstance(n, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.BoolOp, ast.comprehension, ast.Match)) for n in ast.walk(tree))}


def cases(path):
    result = {}
    if not path.exists():
        return result
    for c in ET.parse(path).findall('.//testcase'):
        key = c.get('classname', '') + '::' + c.get('name', '')
        status = next((n.tag for n in c if n.tag in ('failure', 'error', 'skipped')), 'passed')
        result[key] = status
    return result


def main():
    scan = read('static-callgraph.json')
    write('entrypoint-inventory.json', {
        'scope': 'Syntactic CLI guards and dynamic registration sites; not proof every external caller or plugin target is resolved.',
        'cli_modules': [{'file': m['file'], 'imports': m['imports'], 'functions': m['functions']} for m in scan['modules'] if m['cli']],
        'dynamic_sites': scan['dynamic_entrypoints'],
        'reviewed_paths': 'entrypoint-authorities.md',
        'runtime_evidence': 'runtime-profile.json'})
    rows = []
    patch = []
    for name in FILES:
        before = (OLD / name).read_text(encoding='utf-8')
        after = (ROOT / name).read_text(encoding='utf-8')
        diff = list(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='a/' + name, tofile='b/' + name))
        patch.extend(diff)
        rows.append({'file': name, 'before': metrics(before), 'after': metrics(after),
                     'added': sum(s.startswith('+') and not s.startswith('+++') for s in diff),
                     'removed': sum(s.startswith('-') and not s.startswith('---') for s in diff),
                     'before_sha256': sha(OLD / name), 'after_sha256': sha(ROOT / name)})
    write('complexity.json', rows)
    added = sum(r['added'] for r in rows)
    removed = sum(r['removed'] for r in rows)
    branches = sum(r['after']['branches'] - r['before']['branches'] for r in rows)
    newfiles = ['tests/test_shared_contract_boundaries.py'] + [str(p.relative_to(ROOT)).replace('\\', '/') for p in sorted((ROOT / 'experiments/execution_dedup').glob('*.py'))]
    for name in newfiles:
        patch.extend(difflib.unified_diff([], (ROOT / name).read_text(encoding='utf-8').splitlines(True), fromfile='/dev/null', tofile='b/' + name))
    write('task-only.patch', ''.join(patch))
    write('change-manifest.json', {'purpose': 'review artifact, NOT canonical publication ChangeManifest/TestReceipt',
          'baseline': str(OLD), 'head': read('baseline-context.json')['head'],
          'production': rows, 'new_files': [{'path': n, 'sha256': sha(ROOT / n), 'lines': len((ROOT / n).read_text(encoding='utf-8').splitlines())} for n in newfiles],
          'patch_sha256': sha(OUT / 'task-only.patch'), 'commit': None, 'push': False})
    write('complexity-delta.md', f'''# 实际复杂度变化

比较基线是上一轮 LIMITED CHANGE 工作树，包含 psutil 修复，不能将它算成本轮收益。

生产代码 6 文件：增加 {added} 行，删除 {removed} 行，净删除 {removed-added} 行；AST 分支节点净变化 {branches}，函数定义减少 10。算法复杂度没有变化。精确逐文件哈希、计数定义见 complexity.json 与 report.py。

|责任/实际实现分支|之前|之后|默认路径证据|
|---|---:|---:|---|
|递归冻结/解冻实现对|4|1|Agent → Tree/DAG/Block；runtime-profile.json|
|domestic/legacy POST 分派|2|1|兼容 _post_json 直接别名 canonical post_json_once；共享注入计数|
|host/TLS 三类策略，每类|2|1|直接别名，保留旧导入名|
|URL opener/TLS/本地网关策略|2|1|保留薄兼容函数，legacy 在调用时解析；8 个旧/新策略组合|
|项目 Agent、Worker、兼容对话/流水线执行机制|不变|不变|未证明可以合并各自的恢复、准入和交付语义|
|DAG 调度机制、状态/预算权威|不变|不变|没有迁移调度器或存储|

减少的是默认链路可选择的重复实现，不是减少业务步骤或 HTTP 请求数。冻结实现对减少 3；Provider 分派减少 1，三种谓词各减少 1，opener 策略减少 1。不能把这些不同粒度相加后声称消除了 8 套执行引擎。

没有删除整个模块；4 个模块删除重复算法体，legacy_transport 调用绑定修正，local 命令守卫修正。生产依赖新增/删除均 0，状态权威减少 0，自定义协议减少 0；兼容 opener 增加一次函数委派，其他收敛使用直接别名，无新增永久 Adapter 类。导入周期冷启动测试通过。

新增 24 个永久边界测试，实验脚本和报告增加维护/审阅体积（逐文件行数见 change-manifest.json）；实验代码不注册到产品入口。未将实验和报告的增长冒充全仓库 LOC 减少。原有测试未删除、未修改、未新增 skip。本轮没有生产性能提升声明。
''')
    candidates = read('replacement-opportunities.json')['candidates']
    matrix = ['# 候选矩阵', '', '25 个责任簇覆盖 A–H。排名用于试验顺序，不等于采用资格；静态匹配不等于已解析全部动态运行关系。未经试验的第三方只是替代选项，不是经过认证的推荐。', '', '|编号|责任|A 保留|B 现有/标准库|C 第三方备选|得分|决定|', '|---|---|---|---|---|---:|---|']
    for r in candidates:
        matrix.append(f"|{r['id']}|{r['title']}|现有实现|{r['alternatives']['B']}|{r['alternatives']['C']}|{r['priority']}|{r['decision']}|")
    matrix.extend(['', '## 实际试验/沿用依赖', '', '|组件|版本|许可|平台/依赖|结论|', '|---|---|---|---|---|',
        '|Python types/re/graphlib|3.13.3|PSF|本机 Windows 实测；无新增依赖|types/re 复用；graphlib 未迁移|',
        '|jsonschema|4.26.0|MIT|Python >=3.10；attrs、specifications、referencing、rpds-py|已有包，整数与错误契约不等价，DEFER|',
        '|HTTPX|0.28.1|BSD-3-Clause|已有 httpcore/anyio/certifi/idna|继续沿用，不改接口绑定与重试策略|',
        '|psutil|7.0.0|BSD-3-Clause|Windows 本机已有包|保留上轮修复，watchdog 原故障未解决|',
        '|pytest|9.0.3|MIT|现有工具链|继续使用独立业务测试|', '',
        '安装元数据、Python 支持和完整声明依赖见 environment-packages.json。无新增下载/安装的第三方生产包。未完成所有备选框架的最新 release/security advisory 认证，不能声称它们无 CVE 或可立即采用；本轮没有依赖这些未验证假设迁移。冻结、正则和 graphlib 不自行网络访问/遥测/重试；Provider 原预算与请求次数边界保留。', '',
        '参考：[MappingProxyType](https://docs.python.org/3.13/library/types.html)、[graphlib](https://docs.python.org/3.13/library/graphlib.html)、[jsonschema validation](https://python-jsonschema.readthedocs.io/en/stable/validate/)。映射只读代理仍需递归复制以保持输入隔离；graphlib 的顺序/环诊断需要兼容适配。'])
    write('candidate-matrix.md', '\n'.join(matrix) + '\n')
    decisions = ['# 迁移决定', '', '保留旧公开入口；不根据缺少静态引用删除动态或兼容代码。代码变化只在隔离工作树，不合并前轮补丁。', '']
    for r in candidates:
        decisions.extend([f"## {r['id']} {r['title']} — {r['decision']}", '', r['reason'], '', '文件：' + ', '.join(r['files']), ''])
    decisions.extend(['## 删除与资格顺序', '', '初始删除清单见 deletion-plan.json。冻结/策略/POST 共享试验先于删除；随后实际回归发现命令守卫误判，command-guard-trial.json 保留旧/新 15 例。opener 扩展先完成 8 个相同输入组合对照，后删除重复策略，并加入两个晚绑定兼容测试；并非最初计划的一部分。legacy_transport 的 Any 导入补齐静态检查。', '', '未调用 canonical_repo_publish：它是唯一 commit/stage/push 权威，且自动 push；用户禁止 push，因此没有普通本地 commit，也未绕过政策。task-only.patch 是审阅补丁，不是发布回执。'])
    write('migration-decisions.md', '\n'.join(decisions) + '\n')
    write('benchmark-results.json', {
        'scope': '5 candidate boundaries plus separate watchdog investigation; no benchmark score substitutes for qualification',
        'freeze': {'decision': 'SIMPLIFY_EXISTING', 'shared': '300 nested values across four original implementations, isolation and identity boundaries', 'evidence': 'candidate-equivalence.xml', 'performance': read('primitive-benchmarks.json')['freeze'], 'performance_note': 'prototype equivalent algorithm; final uses existing component alias; no speedup claimed'},
        'provider': {'decision': 'SIMPLIFY_EXISTING', 'shared': 'host/TLS policy, one-dispatch success/failure, 8 URL opener combinations', 'failure_injection': 'no fallback or implicit retry on domestic/legacy errors', 'result': 'provider-after-convergence.xml: 132 passed, 3 historical retry-expectation failures', 'latency': 'not benchmarked: no extra external request; one compatibility delegation'},
        'graphlib': {'decision': 'KEEP', 'shared': '500 generated ordered graph cases including duplicate edges/cycles', 'performance': read('primitive-benchmarks.json'), 'reason': 'ordering/diagnostic adapter remains; 2.3-2.4x slower'},
        'schema': {'decision': 'DEFER', 'results': read('mcp-schema-trial.json'), 'reason': 'integer 1.0 and public error compatibility'},
        'command_guard': {'decision': 'MIGRATE', 'results': read('command-guard-trial.json'), 'real_execution': 'new-boundaries.xml; forced rm-containing temporary directory runs actual pytest', 'performance': 'not performance-sensitive; no throughput claim'},
        'watchdog': {'decision': 'DEFER', 'evidence': 'watchdog-analysis.json', 'original_failure_root_cause': 'UNRESOLVED', 'trials': 12, 'paid_api_posts': 0}})
    prior = cases(OUT / 'prior-round-regression.xml')
    current = cases(OUT / 'regression.xml')
    if current and (OUT / 'regression-completion.json').exists():
        bad = {'failure', 'error'}
        delta = {'prior_counts': dict(Counter(prior.values())), 'current_counts': dict(Counter(current.values())),
                 'new_failures': [k for k, v in current.items() if v in bad and prior.get(k) not in bad],
                 'persistent_failures': [k for k, v in current.items() if v in bad and prior.get(k) in bad],
                 'recovered': [k for k, v in prior.items() if v in bad and current.get(k) == 'passed'],
                 'missing': sorted(set(prior) - set(current)),
                 'newly_skipped': [k for k, v in current.items() if v == 'skipped' and prior.get(k) not in (None, 'skipped')],
                 'added_cases': sorted(set(current) - set(prior))}
        write('regression-delta.json', delta)
    else:
        delta = {'status': 'RUNNING; no final verdict'}
    write('report-status.json', {'production_net_removed': removed-added, 'regression': delta})


if __name__ == '__main__':
    main()
