"""Summarize completed evidence, preserving failures instead of manufacturing PASS."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/substrate-replacement-v2'


def load(name):
    return json.loads((OUT / name).read_text(encoding='utf-8-sig'))


def write(name, value):
    (OUT / name).write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')


def main():
    if not (OUT / 'regression-completion.json').exists() or not (OUT / 'regression.xml').exists():
        raise SystemExit('Full regression incomplete; refusing final report')
    # Credential alignment assertions can embed locally configured values. Keep
    # test identities/statuses and hashes, but never publish those tracebacks.
    xml = OUT / 'regression.xml'
    tree = ET.parse(xml)
    names = []
    for case in tree.findall('.//testcase'):
        if any(k in case.get('classname', '') for k in ('test_provider_credentials', 'test_qwen_provider_alignment')):
            for node in case:
                if node.tag in ('failure', 'error'):
                    names.append(case.get('name', '').split('[')[0])
                    node.set('message', 'Credential alignment assertion details redacted')
                    node.text = 'Credential alignment assertion details redacted; original content hash retained.'
    if names and not (OUT / 'credential-redaction.json').exists():
        log = OUT / 'regression.log'
        before = {'xml_sha256': hashlib.sha256(xml.read_bytes()).hexdigest(), 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
        text = log.read_text(encoding='utf-8')
        chunks = re.split(r'(?m)^(?=_{3,} .* _{3,}\s*$)', text)
        for index, chunk in enumerate(chunks):
            header = chunk.splitlines()[0] if chunk else ''
            if header.startswith('___') and any(name in header for name in names):
                # Retain subsequent warnings/summary even for the last failure.
                tail = re.search(r'(?m)^={3,} ', chunk)
                chunks[index] = header + '\n[Credential assertion traceback redacted]\n' + (chunk[tail.start():] if tail else '')
        log.write_text(''.join(chunks), encoding='utf-8', newline='\n')
        tree.write(xml, encoding='utf-8', xml_declaration=True)
        write('credential-redaction.json', {'before': before, 'test_names': names, 'scope': 'credential alignment tracebacks only; statuses unchanged'})
    subprocess.run([sys.executable, str(ROOT / 'experiments/execution_dedup/report.py')], cwd=ROOT, check=True)
    delta = load('regression-delta.json')
    counts = delta['current_counts']
    prior = delta['prior_counts']
    receipts = []
    for path in sorted(OUT.glob('*.xml')):
        cases = ET.parse(path).findall('.//testcase')
        statuses = Counter(next((n.tag for n in c if n.tag in ('failure', 'error', 'skipped')), 'passed') for c in cases)
        receipts.append({'file': path.name, 'counts': dict(statuses)})
    write('test-receipts.json', receipts)
    preservation = {}
    for key, root, manifest in [('original', Path('D:/CGKN'), 'original-snapshot.json'),
                                ('prior_task', ROOT.parent / 'substrate-migration-20261101', 'inherited-changes.json')]:
        rows = load(manifest)
        changed = [r['path'] for r in rows if not (root / r['path']).is_file() or hashlib.sha256((root / r['path']).read_bytes()).hexdigest() != r['sha256']]
        preservation[key] = {'files_checked': len(rows), 'changed': changed}
    preservation['checked_epoch'] = time.time()
    write('preservation-check.json', preservation)
    checked = subprocess.run(['git', 'apply', '--reverse', '--check', str(OUT / 'task-only.patch')], cwd=ROOT, capture_output=True, text=True)
    write('patch-check.json', {'command': 'git apply --reverse --check task-only.patch', 'exit_code': checked.returncode, 'stderr': checked.stderr})
    if checked.returncode or any(preservation[k]['changed'] for k in ('original', 'prior_task')):
        raise SystemExit('Patch or original-tree preservation check failed')
    rows = load('complexity.json')
    added = sum(r['added'] for r in rows)
    removed = sum(r['removed'] for r in rows)
    new_bad = delta['new_failures']
    notes = load('failure-attribution-final.json') if (OUT / 'failure-attribution-final.json').exists() else {'status': 'pending' if new_bad else 'no new failure IDs'}
    lines = ['# 完整回归与基线差异', '',
             f'最终完整执行：{counts}。前轮完整基线：{prior}。pytest 在 1981.15 秒后输出完整结果与 JUnit；包装脚本随后因混合编码解码失败，退出 1。原始子进程退出码未及时写盘，记为未知，不从摘要伪造；日志整理已恢复，见 regression-completion.json。', '',
             f"按 classname::name 比较：持续失败/错误 {len(delta['persistent_failures'])}，新增失败/错误 {len(new_bad)}，此前失败转通过 {len(delta['recovered'])}，缺失测试 {len(delta['missing'])}，新增 skip {len(delta['newly_skipped'])}。案例清单见 regression-delta.json。", '',
             '本轮默认使用显式 legacy 离线 profile，加 socket audit hook 拦截外部地址；国内模式测试继续使用自己的 fixture。这和前轮全量环境不完全相同，失败变化不能全部归因于代码。没有把 skip、环境阻塞、退出异常写成 PASS。', '',
             '## 定向证据', '',
             '|回执|结果/用途|', '|---|---|',
             '|baseline-targeted.xml|405 PASS；契约、Agent、DAG、runtime、state 等原行为|',
             '|baseline-provider.xml|92 PASS / 5 FAIL；相同显式离线 profile|',
             '|candidate-equivalence.xml|38 PASS；旧/新共享输入与异常注入|',
             '|provider-after-convergence.xml|132 PASS / 3 历史 FAIL；含共享试验，重试预期冲突保留|',
             '|new-boundaries.xml|24 PASS；新增永久测试|',
             '|guard-and-agent-confirmation.xml|33 PASS；真实 pytest 与 Agent 修复恢复|',
             '|runtime-witnesses.xml|6 PASS；真实文件修改、pytest、失败后受影响节点恢复、Worker 拒绝越权、budgeted 兼容调用|',
             '|product-direction-gate.json / ruff.log|PASS；最终生产代码范围|', '',
             '首次修改后组合测试 targeted-after.xml 为 525 PASS / 7 FAIL。新增 Agent 失败已归因到 rm 子串误判并有真实 pytest 回归；Provider timing 失败曾在前轮全量失败中出现，opener 晚绑定后修复。保留失败日志和中断执行回执，不用后续成功覆盖历史。', '',
             '## watchdog', '',
             '同主机、同负载、同插桩交替对照 12 次：两个版本各 1 次冷启动相关失败，其余 10 次通过。原版曾卡在 CreateProcess 并留下 2 个已由专属 fixture 清理的子进程；LIMITED CHANGE 版本有 recovery deadline 超时；负载线程均回收。两者都不同于前轮 final stop-timeout。原始临时状态已消失，缺少原始栈，根因仍 UNRESOLVED。不能用此次通过数宣布无回归。', '',
             '## 新增失败归因', '', '```json', json.dumps(notes, ensure_ascii=False, indent=2), '```', '',
             '原有测试没有删除/改断言/加 skip；24 个永久边界测试新增。跨端口、独立验收、预算、UNKNOWN、知识复用等使用全量原有测试标准；历史失败不转成当前成功证明。LIVE_NOT_VERIFIED；没有真实付费 POST。']
    write('regression-report.md', '\n'.join(lines) + '\n')
    decisions = Counter(r['decision'] for r in load('replacement-opportunities.json')['candidates'])
    final = f'''# CGKN 底层收敛最终报告

结果：完成有边界的内部实现收敛，尚不能宣布整个架构瘦身完成、全仓库通过或生产就绪。前轮仍是 LIMITED CHANGE；watchdog 原始 stop-timeout 原因仍未解决，不合并前轮补丁到原工作树。

独立工作树：`{ROOT}`；分支 `codex/execution-dedup-20261101`；原始 HEAD `{load('baseline-context.json')['head']}`。

1. **发现数量**：836 个模块的初始扫描归纳 25 个 A–H 责任簇。不是 25 个都可立即替换；动态入口仍有未解析部分。最终扫描见 final-scan，新增测试导致总模块数量增加。
2. **实际试验**：5 个候选边界（冻结、Provider 分派/opener、拓扑排序、schema、命令守卫），另有 watchdog 12 次配对调查。没有机械重装上轮大型框架。
3. **第三方更好？** 本轮没有新第三方组件完成采用资格。复用既有 Python stdlib 与内部实现；不把候选名称或安装成功当证据。
4. **原生足够好**：保留拓扑排序（graphlib 适配后慢约 2.3–2.4 倍）、当前 Gateway/HTTPX、pytest、预算和独立验收。jsonschema 因准入/错误契约差异 DEFER。
5. **实际修改清理**：6 个生产文件，增加 {added} 行、删除 {removed} 行，净删除 {removed-added} 行；10 个函数定义删除。没有删除整个模块。
6. **维护责任**：冻结/解冻实现对 4→1，Provider POST 分派 2→1，三类 host/TLS 策略各 2→1，opener 策略 2→1。默认链路的重复实现减少；Agent/Worker/兼容执行机制、DAG 与状态权威数量未变。
7. **可靠性/性能**：真实 pytest 临时路径子串误拦截修复；legacy opener 导入时固化导致的替换失效修复。危险命令 12 例仍被拦截，守卫不是安全沙箱。不宣称生产性能提升。
8. **未采用选项**：决策分布 {dict(decisions)}。SQLite、Agent/MCP/遥测框架等仍需明确兼容与净删除收益；详见 candidate-matrix.md、migration-decisions.md。
9. **全量回归**：{counts}；相对前轮新增失败/错误 {len(new_bad)}，持续失败/错误 {len(delta['persistent_failures'])}，旧失败转通过 {len(delta['recovered'])}。未观察到本轮新增 P0/P1 回归；这不是对所有未覆盖动态路径的无缺陷证明。20 个恢复案例不能全部归功于代码，离线 profile 和时序不同。逐例归因见 regression-report.md / regression-delta.json；不能声称全库全绿或 watchdog 已修复。测试结束后的日志解码错误已修复整理，原始子进程退出码未及时写盘，明确记为未知。
10. **API**：新增真实付费 POST 0，CGKN API 费用 ¥0.00，LIVE_NOT_VERIFIED。Codex 订阅调用不计入 CGKN Provider 花费。
11. **剩余机制**：项目 Agent、bounded Worker、历史 dynamic/conversation/provider pipeline、ArtifactModuleRunner 仍需维护；语义差异尚不足以支持整体删除。预算、run state、知识/产物存储承担不同权威，不按文件数量硬合并。
12. **应自维护**：项目决策边界、Component/Block 契约、受影响子图恢复、预算/UNKNOWN、独立业务验收与唯一交付路线；通用递归转换/传输策略应继续维持本轮单一实现。

## 交付与限制

原工作树 1377 文件和前轮 16 任务文件哈希检查均未改变；具体以 preservation-check.json 为准。无 push、merge、tag、release。仓库唯一提交工具会自动 push，故未调用且未用普通 git commit 绕过政策。

审阅补丁 task-only.patch 相对上一轮工作树，只包含本轮生产变更、新边界测试和实验脚本；不混入原工作树既有脏修改。反向应用检查通过，前后源文件哈希见 change-manifest.json，证据哈希见 evidence-hashes.json。报告和原始证据单独留在 artifacts/substrate-replacement-v2。

已使用仓库 [manage-pmp-agile-quality](../../skills/manage-pmp-agile-quality/SKILL.md) 方法记录资格与结果；没有新增项目状态权威。完整调用关系与未解析范围见 entrypoint-authorities.md。没有新增生产依赖、调度器、公开交付路线或自动重试。
'''
    write('final-report.md', final)
    manifest = []
    for p in sorted(OUT.rglob('*')):
        if p.is_file() and p.name != 'evidence-hashes.json' and '__pycache__' not in p.parts:
            manifest.append({'path': p.relative_to(OUT).as_posix(), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    write('evidence-hashes.json', manifest)
    print(json.dumps({'counts': counts, 'new_failures': len(new_bad), 'net_removed': removed-added, 'evidence_files': len(manifest)}))


if __name__ == '__main__':
    main()
