"""Assemble local evidence; no Provider interaction and no historical edits."""
import difflib,json,os,platform,time,zipfile
from pathlib import Path
from experiments.api_acceptance.iter120_audit import ROOT,OUT,OLD,sha,save

CHANGED=['scripts/provider_api_budget.py','cgkn/providers/network_transport.py','cgkn/providers/domestic_gateway.py',
 'cgkn/providers/gateway_client.py','cgkn/providers/progress_clock.py','cgkn/runtime/dag_runner.py',
 'experiments/api_acceptance/iter119_pair.py','tests/providers/test_progress_clock.py',
 'tests/providers/test_iter120_budget_lock.py','tests/providers/test_iter120_formal_parallel.py',
 'experiments/api_acceptance/iter120_audit.py','experiments/api_acceptance/iter120_plan.py','experiments/api_acceptance/iter120_report.py']
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def overlap(intervals):return max(0,min(b for a,b in intervals)-max(a for a,b in intervals)) if len(intervals)==2 else 0
def eventstamp(e):return {k:e[k] for k in ('at','monotonic_ns','clock_pid','phase') if k in e}

def assemble():
    runs=sorted(p for p in OUT.glob('formal-*') if p.is_dir() and (p/'matrix.json').exists())
    full=[p for p in runs if len(read(p/'matrix.json'))==12 and all(r['status']=='PASS' for r in read(p/'matrix.json'))]
    selected=full[-1];matrix=read(selected/'matrix.json')
    timelines=[];rows=[]
    for item in matrix:
        name=item['case']['name'];p=selected/name
        events=read(p/'gateway-events.json');ledger=read(p/'budget.json');clocks=read(p/'progress-observations.json')
        dag=[json.loads(s) for f in (p/'state').rglob('events.jsonl') for s in f.read_text().splitlines()]
        intervals=[];gate_intervals=[];active=[];firsts=[];providers={}
        assert len({e['clock_pid'] for e in events})==1
        assert all(e['client_attempt_id']==item['job']['attempt_id'] for e in events)
        for provider in ('qwen','deepseek'):
            call=next((c for c in ledger['calls'] if c['provider']==provider),None)
            if not call:
                providers[provider]=dict(status='REJECTED_BEFORE_RESERVATION',events=[e for e in dag if e.get('node_id')==provider]);continue
            pe=[e for e in events if e.get('client_call_id')==call['call_id']]
            assert all(e['client_request_identity']==call['request_identity'] for e in pe)
            phase=lambda x:next((e for e in pe if e['phase']==x),None)
            start=phase('provider_submitted');end=phase('provider_stream_completed') or phase('attempt_end')
            begin=phase('gateway_request_start');slot=phase('provider_slot_acquired');gate_end=phase('gateway_request_end')
            meaningful=[];count=0
            for e in pe:
                if e['phase']=='model_progress' and e.get('meaningful_events',0)>count:
                    count=e['meaningful_events'];meaningful.append(e)
            if start and end:intervals.append((start['monotonic_ns']/1e9,end['monotonic_ns']/1e9))
            if begin and gate_end:gate_intervals.append((begin['monotonic_ns']/1e9,gate_end['monotonic_ns']/1e9))
            if meaningful:
                active.append((meaningful[0]['monotonic_ns']/1e9,meaningful[-1]['monotonic_ns']/1e9));firsts.append(meaningful[0]['monotonic_ns']/1e9)
            clock=next(c for c in clocks[-1]['calls'] if c['call_id']==call['call_id'])
            assert all(clock[k]==call[k] for k in ('job_id','attempt_id','request_identity'))
            lifecycle={k:eventstamp(e) for k in ('gateway_request_start','provider_slot_acquired','direct_dns_started','direct_dns','connection.connect_tcp.started',
                'connection.connect_tcp.complete','connection.start_tls.started','connection.start_tls.complete','provider_submitted','upstream_headers',
                'provider_stream_completed','attempt_end','gateway_response_persisted') if (e:=phase(k))}
            saved=p/(provider+'-result-saved.json')
            if saved.exists():lifecycle['witness_result_saved']=read(saved)
            lifecycle['dns_scope']='Loopback IP literal: DNS not used. Slow preparation is explicitly fixture-injected, not a measured Windows DNS operation.'
            lifecycle['connection_reused']=not bool(phase('connection.connect_tcp.started'))
            lifecycle['first_meaningful_sse']=eventstamp(meaningful[0]) if meaningful else None
            lifecycle['last_meaningful_sse']=eventstamp(meaningful[-1]) if meaningful else None
            providers[provider]=dict(call_id=call['call_id'],request_identity=call['request_identity'],job_id=call['job_id'],attempt_id=call['attempt_id'],
                ledger_status=call['status'],clock=clock,dag_events=[e for e in dag if e.get('node_id')==provider],gateway=lifecycle,
                queue_seconds=(slot['monotonic_ns']-begin['monotonic_ns'])/1e9 if slot and begin else None,
                preparation_seconds=(start['monotonic_ns']-slot['monotonic_ns'])/1e9 if start and slot else None)
        row=dict(case=name,status='PASS',http_overlap_seconds=overlap(intervals),gateway_overlap_seconds=overlap(gate_intervals),
            meaningful_output_interval_overlap_seconds=overlap(active),first_meaningful_sse_gap_seconds=abs(firsts[0]-firsts[1]) if len(firsts)==2 else None,
            submitted_unfinished_overlap_seconds=overlap(intervals),http_span_seconds=max(b for a,b in intervals)-min(a for a,b in intervals),
            wall_seconds=item['wall_seconds'],tls_posts=item['tls_posts'],progress_queries=item['progress_queries'],
            pool_reuse={k:v.get('gateway',{}).get('connection_reused') for k,v in providers.items()},source=str(p.relative_to(OUT)))
        timelines.append(dict(case=name,providers=providers,metrics=row));rows.append(row)
    assert all(rows[1]['pool_reuse'].values())
    serial=next(r for r in rows if r['case']=='measured-serial-baseline')
    parallel=next(r for r in rows if r['case']=='reuse-near-simultaneous')
    speed=serial['http_span_seconds']/parallel['http_span_seconds']
    save(OUT/'parallel-timeline.json',dict(scope='LOCAL_TLS_FAKE_PROVIDERS',clock_policy='Gateway PID-local monotonic nanoseconds only for overlap; cross-process UTC retained for association, never subtracted for subsecond claims',
        gateway_python=platform.python_version(),gateway_monotonic_resolution_seconds=time.get_clock_info('monotonic').resolution,cases=timelines,
        historical_iter119=read(OLD/'parallel-test-results.json'),historical_limitations='UTC-only original Gateway evidence; reserve begin and monotonic_ns absent; never backfilled'))
    transcript=read(selected/'mcp-transcript.json');queries=[r['seconds'] for r in transcript if r['tool']=='cgkn_get_progress']
    save(OUT/'parallel-test-results.json',dict(status='OFFLINE_PARALLEL_PASS',live_status='LIVE_PARALLEL_NOT_VERIFIED',live_blocker='BLOCKED_AUTHORIZATION',
        whole_request_serialization_confirmed=False,selected_run=str(selected),cases=rows,
        measured_serial_http_span_seconds=serial['http_span_seconds'],measured_parallel_http_span_seconds=parallel['http_span_seconds'],measured_http_span_speedup=speed,
        read_only_progress=dict(queries=len(queries),max_query_seconds=max(queries),median_query_seconds=sorted(queries)[len(queries)//2],generation_posts=0),
        prior_runs=[dict(path=str(p),cases=len(read(p/'matrix.json')),synthetic_posts=sum(r['tls_posts'] for r in read(p/'matrix.json')),
            note='Earlier ITER120 evidence retained; see timestamps and source hash in each authorization. Earlier Gateway attempt metadata was repaired later.') for p in runs if p!=selected]))
    checks=[]
    for path,before in read(OUT/'protected-before.json').items():
        p=Path(path);after=sha(p) if p.exists() else None
        checks.append(dict(path=path,before=before,after=after,unchanged=before==after))
    corpus=read(OUT/'corpus-before.json');current=[]
    for base,ds,fs in os.walk(corpus['root']):
        for f in fs:
            p=Path(base)/f;s=p.stat();current.append((str(p.relative_to(corpus['root'])),s.st_size,s.st_mtime_ns))
    corpus_same=sorted(map(tuple,corpus['files']))==sorted(current)
    assert all(c['unchanged'] for c in checks) and corpus_same
    save(OUT/'protected-files-check.json',dict(status='PASS',checks=checks,corpus=dict(root=corpus['root'],files=len(current),metadata_unchanged=corpus_same,
        limitation='Metadata inventory, not a full byte hash of 30266 Corpus files. No Corpus mutations executed. Snapshot taken during offline tests; historical baseline is not asserted.')))
    budgets=[]
    for p in runs:
        for row in read(p/'matrix.json'):
            ledger=read(p/row['case']['name']/'budget.json')
            budgets.append(dict(run=p.name,case=row['case']['name'],scope='SYNTHETIC_NO_CHARGE',tls_posts=row['tls_posts'],totals=ledger['totals']))
    save(OUT/'budget-reconciliation.json',dict(real_provider_posts_added=0,real_cost_added_cny=0,real_unknown_added=0,
        historical_live_authorization='ITER119 spent: exactly two successful POSTs, cannot replay',historical_iter119_totals=read(OLD/'budget.json')['totals'],
        historical_global_ledger_sha256=sha(Path('F:/CGKN-ITER-076/global-provider-budget.json')),original_unknown_preserved=True,
        formal_synthetic_post_count=sum(r['tls_posts'] for r in budgets),formal_synthetic_ledgers=budgets,
        note='Failure-injection UNKNOWN entries are confined to isolated fake-Provider ledgers; never cleared or labeled real billing.',
        live_plan=dict(status='BLOCKED_AUTHORIZATION',max_posts=2,shared_cap_cny=.2,reservation_upper_cny=.131072,provider_price_upper_cny=.0448512)))
    changes=[];manifest=[]
    for name in CHANGED:
        p=ROOT/name;base=OUT/'baseline'/name
        before=base.read_text(encoding='utf-8').splitlines(True) if base.exists() and 'iter120' not in name else []
        after=p.read_text(encoding='utf-8').splitlines(True)
        changes.extend(difflib.unified_diff(before,after,fromfile='a/'+name,tofile='b/'+name))
        dest=OUT/'final-source'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
        manifest.append(dict(path=name,before_sha256=sha(base) if before else None,after_sha256=sha(p)))
    (OUT/'changes.patch').write_text(''.join(changes),encoding='utf-8');save(OUT/'change-manifest.json',manifest)
    report(selected,rows,speed,len(queries),checks)
    with zipfile.ZipFile(OUT/'review-bundle.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in OUT.rglob('*'):
            rel=p.relative_to(OUT)
            if not p.is_file() or p.name=='review-bundle.zip' or '__pycache__' in rel.parts:continue
            if rel.parts[0]=='baseline' and str(Path(*rel.parts[1:])).replace('\\','/') not in CHANGED:continue
            z.write(p,str(rel))
    print(json.dumps(dict(report=str(OUT/'report.md'),bundle_bytes=(OUT/'review-bundle.zip').stat().st_size,selected=str(selected),cases=len(rows))))

def report(selected,rows,speed,queries,checks):
    good=[r for r in rows if r['case'] in ('cold-near-simultaneous','reuse-near-simultaneous','qwen-slow-prepare','deepseek-slow-prepare','qwen-long','deepseek-long')]
    minimum=min(r['http_overlap_seconds'] for r in good);maximum=max(r['http_overlap_seconds'] for r in good)
    table='\n'.join(f"| {r['case']} | {r['http_overlap_seconds']:.6f} | {r['meaningful_output_interval_overlap_seconds']:.6f} | {r['tls_posts']} | PASS |" for r in rows)
    text=f'''# ITER-120 最终工程验收

**OFFLINE_PARALLEL_PASS；LIVE_PARALLEL_NOT_VERIFIED；BLOCKED_AUTHORIZATION。** 本轮真实供应商生成 POST 0 次、真实新增费用 0 元、真实新增 UNKNOWN 0。未提交或推送。假 TLS Provider 的失败注入不计为真实供应商失败或费用。

## 十项直接回答

1. **上次具体原因：时间关系已查清，不能唯一归因。** DeepSeek 上游持续 0.664977 秒；Qwen 比 DeepSeek 晚约 0.805444 秒发送，故留下 0.140467 秒间隙。Qwen 预算记录及 Gateway 入站分别落后 1.020284 / 1.026210 秒；两家连接准备独立重叠，Qwen 准备反而约快 0.214 秒。历史没有 reserve-begin/锁等待起点及统一单调时间，因此无法证明该次延迟全由预算锁造成。未发现“必须等另一家全部完成”的证据。
2. **调度器/Gateway：未发现跨 Provider 全请求串行锁。** 原 DAGRunner 在协调线程提交两个无依赖节点，网络在线程池运行，FIRST_COMPLETED 后补位；Gateway 各自 semaphore、executor、HTTP pool。账本短事务仍需互斥，Windows 重试粒度曾放大启动延迟。不是 PARALLEL_SERIALIZATION_CONFIRMED 所定义的“只能顺序执行”。
3. **实际修改：** Windows LK_LOCK 秒级重试改为有 10 秒上限的 5 毫秒非阻塞抢锁，保留跨进程原子锁；修复锁文件每次 append 和未成功加锁仍解锁的问题；移除见证器 barrier；已完整接收 Content-Length 的 SSE 安全结束迭代，恢复连接复用（不额外等待无界流）；保留 Gateway header 的 job attempt，调用键单列 client_call_key；补齐阶段时间及 Gateway 单进程 monotonic_ns。见 changes.patch。验收入口支持独立、冻结且显式授权的目录，仍复用原 MCP/Controller/worker/DAG/预算客户端，永久 claim 防重入。
4. **本地 TLS：稳定重叠。** 最终 12 场景均通过，六个双成功并行情景重叠 {minimum:.6f}–{maximum:.6f} 秒。两个独立 TLS 端口，真实 socket/SSE；首轮冷连接，后续连接复用有零 connect_tcp.started 的证据。慢启动为测试进程中显式模拟准备延迟，不冒充真实 WLAN DNS 测量。
5. **Progress Clock：同时工作。** 最终正式 MCP 共 {queries} 次只读查询，各 job/attempt/call 与账本及 Gateway 逐项一致；多次采到两家有效事件独立增长，查询新增 POST 0。心跳案例实际等待超过 120 秒，故障方只有 1 次有效事件并进入 STALLED，另一方完整结束。接收回调只改内存，快照由各自 writer 合并写入。
6. **上游实际重叠：** 本轮只验证本地 TLS 上游，逐例见表。真实 Qwen/DeepSeek 历史重叠仍为 0 秒，本轮没有新的付费见证。HTTP、Gateway、有效输出区间分别计算，未互相代替。
7. **真实完整结果：** ITER-119 原两份完整结果仍有效且原文件未改；它们不证明本轮代码已上线通过。最终本地双成功案例通过 Schema、Qwen 原 PlanningProposal 合同、终态、usage、结果保存。假响应始终标注 synthetic，不是模型生成。
8. **新增调用/费用/UNKNOWN：** 真实为 0 / 0 元 / 0；离线故障的 UNKNOWN 单独保留在各案例假账本。原全局账本、real-dev-01 及旧长规划 UNKNOWN、ITER-119 结果和网络/默认模型配置共 {len(checks)} 个文件校验不变；Corpus 30266 文件大小/mtime 清单不变（非全量内容哈希）。
9. **能宣布：** OFFLINE_PARALLEL_PASS。不能宣布 LIVE_UPSTREAM_OVERLAP_PASS 或 LIVE_PARALLEL_FULL_PASS。真实阶段为 BLOCKED_AUTHORIZATION，不是供应商不可用的证明。
10. **剩余阻碍：** 新真实授权缺失；外部 DNS/TLS、模型响应时长仍可能影响自然重叠。生产 Gateway 未为本轮离线验证重启，未来发送前须通过保存的 GUID 路线启动最终代码、验证模型库存和代码/会话身份、重新核价。产品方向 gate 仍被两个既有 obsolete_active_path 阻断，未扩大范围处理，不宣称完整产品通过。

## 最终正式入口矩阵

| 场景 | HTTP 重叠秒 | 有效输出区间重叠秒 | 本地 TLS POST | 结果 |
|---|---:|---:|---:|---|
{table}

单侧失败场景 PASS 表示失败被正确拒绝/终止、另一家完成，**不表示两家生成成功**。预算拒绝场景只发送另一家 1 次。停滞使用真实墙钟 120 秒，不使用虚拟时间。串行对照明确用测试专属 max_parallel=1，生产仍为 2，未伪造 overlap。测得串行 HTTP 总区间与复用并行总区间之比为 {speed:.3f}；这是本地夹具数据，不预测真实模型加速比。

原始完整证据：`{selected.relative_to(OUT)}`；各案例包含正式 MCP 回执、完整 Gateway 阶段、账本、时钟、DAG 事件及结果。`parallel-timeline.json` 使用同一 Gateway PID 的单调时钟；保留纳秒数值与运行时声明精度，跨进程只用 UTC/身份关联。DNS 对 IP 字面量不适用；TCP/TLS 复用时缺少握手事件属于正常复用，不补造时间。

## 回归和证据边界

`regression.log`：83 passed、1 skipped；`final-regression.log` 为后续身份修复复测；`final-formal-tests.log` 为最终完整矩阵；`final-plan-regression.log` 验证新 0.20 元/双 2048 输出候选计划经过正式入口及既有防重入测试。不同版本运行记录均保留，最终完整矩阵优先，早期 Gateway attempt 元数据错误未回写。最初一次回归暴露测试直接读取快照与后台 replace 的 Windows 竞争，测试改为持该快照 writer 锁读取，生产只读 API 原有短重试未改。

## 一次性新授权需求（当前未授权）

候选请求和完整 Schema 已写入 `live-plan-pending/plan.json`，authorization.json 为 **authorized=false**。Qwen 一次生成 CSV 支出分析器的中等长度 PlanningProposal；DeepSeek 一次独立生成区间合并函数与六项测试设计。每家输入预留 8192、输出最多 2048 token；最多 2 次 POST、共用 **0.20 元人民币上限**，无自动重试、fallback、第三次或旧 UNKNOWN 重放。

本次核查的[Qwen 北京价格](https://help.aliyun.com/zh/model-studio/qwen3-8-flash)为每百万输入/输出 0.8/2.7 元；[DeepSeek 价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)按高峰缓存未命中 2/8 元。给定 token 上限按供应商价格合计上界 **0.0448512 元**；预算系统采用更保守的 4/16 单价，合计预留 **0.131072 元**。不依赖优惠或免费额度；授权后发送前重新核价、校验完整 wire bytes + framing ≤8192，若无法可靠满足共享预算则不发送。此方案不保证自然重叠，未重叠也不得增加第三次。
'''
    (OUT/'report.md').write_text(text,encoding='utf-8')
    (OUT/'bottleneck-analysis.md').write_text('''# 已证实缺陷与归因边界

Windows 账本锁实验：同一 60ms 持锁条件，原三次等待 1.015345、1.000781、1.016850 秒；新实现 0.064530、0.065695、0.065236 秒。原锁文件 6 字节，新 1 字节。八个独立 Windows 进程竞争两次调用额度，恰好两个预留成功，未放宽限额或去重。锁仍只覆盖 read/modify/write，不覆盖 HTTP/SSE。

连接复用：初轮正式 TLS 冷/复用尝试各有两个 connect_tcp.started；定位到 SSE DONE 后关闭尚未达到 StopIteration 的 httpx iterator。仅在 Content-Length 字节已全部下载时完成已知 EOF；未知/分块流仍保持原关闭行为，不做无界 drain。最终复用场景两个 Provider 均没有新握手。

Gateway 身份：payload cgkn_attempt_id 实际是调用键，曾覆盖 HTTP header 的 generation attempt。改为 client_call_key 保留原头部；Gateway、Clock、账本的 call_id/request_identity/job/attempt 逐项核对。历史事件原样保存。

未发现 DAG Future 顺序等待、全局单 worker、跨 Provider 长网络锁或快照共享 I/O 锁。DAG 的必要 state/result 提交由原协调线程完成，未引入第二调度器。独立 Provider 槽位、池及原依赖失败规则不变。

ITER119 历史缺失 reserve begin/lock acquired/mono 时间，不能证明预算锁是唯一实际根因。已知 Qwen 入站晚约 1.026 秒，两家连接准备独立重叠；DeepSeek 仅约 0.665 秒生成，导致未观测到上游重叠。离线修复与历史归因分别陈述。
''',encoding='utf-8')

if __name__=='__main__':assemble()
