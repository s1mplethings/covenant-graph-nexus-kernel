import json
import subprocess
from pathlib import Path
from .capture import ROOT,OLD,save,sha
from .real_path_replay import IMAGE

def main():
    old_seals=[]
    for v in [7,8]:
        seal=json.loads((OLD/f'evidence-seal-v{v}/seal.json').read_text(encoding='utf-8'))
        checks={p:sha(Path(p))==h for p,h in seal['files'].items()}
        assert all(checks.values());old_seals.append({'version':v,'files':checks})
    save(ROOT/'original-seals-recheck.json',old_seals)
    rows=json.loads((ROOT/'budget-audit-v3/audit.json').read_text())['rows']
    table='|运行|上限|已计|余额|下次输入上界|下次总预留|可负担输出 token|\n|---|---:|---:|---:|---:|---:|---:|\n'
    for r in rows:table+=f"|{r['run_id']}|{r['run_cap']:.5f}|{r['run_used']:.5f}|{r['run_remaining']:.5f}|{r['input_upper_cny']:.5f}|{r['next_upper_cny']:.5f}|{r['affordable_output_tokens']}|\n"
    ledger=json.loads((OLD/'global-provider-budget.json').read_text());assert ledger['totals']['api_calls']==433
    plan=json.loads((ROOT/'dev-packet/cost-plan.json').read_text());freeze=ROOT/'dev-packet/freeze.json'
    summary={'iteration':'ITER-088','head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'status':'LOCAL_PREPARATION_COMPLETE_PAID_AUTHORIZATION_PENDING','new_provider_calls':0,'cumulative_calls':433,'conservative_cny':47.83242,'remaining_old_cap_cny':2.16758,'old_formal':{'started':32,'not_deliverable':32,'autonomous_deliverable':0,'not_run':0,'versions':{'v7':4,'v8':28}},'new_dev':{'planned':2,'started':0},'regression':'65 passed, 0 skipped','gate':'PASS','graph_change':'Bounded incremental commit addition; strict ordinary resume, explicit successful-node retry, atomically bound state/DAG','budget_findings':{'smaller_output_feasible':11,'input_alone_exceeds_remaining':3,'unsettled_reservations':0,'unknown_old_usage':5},'cost_plan':plan,'freeze_sha256':sha(freeze),'source_before_sha256':sha(ROOT/'source-before.zip'),'source_after_sha256':sha(ROOT/'source-after.zip'),'patch_sha256':sha(ROOT/'tracked-changes.patch'),'host_semantic_assistance_to_product_candidates':0,'private_feedback_to_candidates':0,'human_domain_review':'UNTESTED / PENDING_HUMAN','corpus_entry':'entry-iter088-state-budget-dev-preparation'}
    save(ROOT/'summary.json',summary)
    events=[{'event':'MEDIA_CAPTURE_1_EMPTY','reason':'ffmpeg input seek triggered source HTTP 429; exit code 0 but empty MP4 retained and rejected','path':str(ROOT/'media/jfk-180-210.mp4')},{'event':'BUDGET_AUDIT_INITIAL_ERROR','reason':'Historical unknown usage uses strings, not None; initial numeric sum failed; v2 omission of five rows corrected by v3 and usage-supplement. No ledger writes.'},{'event':'ACTUAL_REPLAY_REPORTING_ERROR','reason':'Used nonexistent boundary.audit after route completed/closed; fixed report path to root/audit.jsonl and retained both attempts; no paid calls.'},{'event':'REFERENCE_GUI_OPERATOR_ERROR','reason':'JS play lacked browser user gesture. First trace retained. One corrected trusted CDP userGesture replay passed; no candidate changed.'},{'event':'VERIFY_REPORT_ENCODING_ERROR','reason':'Windows default GBK failed on historical Chinese authorization. UTF-8 v2 completed; old regression/gate records retained.'},{'event':'SYNTHETIC_TRANSPORT_TEST_SETUP_ERROR','reason':'Initial synthetic budget lacked required limits; fixed fixture, not budget behavior. Production ledger untouched.'}]
    save(ROOT/'diagnostic-events.json',events)
    text=f'''# ITER-088：状态契约、预算离线核查与一对 DEV 准备

本阶段本地工作已完成，新增付费 Provider 调用 **0**。累计仍为 **433 次、保守计费 47.83242 元 / 50 元**，余额 **2.16758 元**；不是已核账发票。附件只授权零调用准备，新 DEV 尚未启动，需针对本阶段的具体付费授权。原 32 次不重跑、不改候选、不重报成功。

## 版本、历史与授权

实际 HEAD `{summary['head']}`，分支 `codex/provider-gateway-integration-20261017`。当前管理主线仍为 MVP ITER-015，本诊断不覆盖它。仓库已有 ITER-077/078 及 082–087 历史，检索确认 ITER-088 未占用，采用此标识。保留用户 `.api_lab_worktree`、`.service_scratch` 及所有旧未提交评测源码；未暂存、提交、推送、合并或发布。

实际源码不仅由 HEAD 决定：[修复前快照](F:/CGKN-ITER-088/source-before.zip)、[修复后快照](F:/CGKN-ITER-088/source-after.zip)、[tracked diff](F:/CGKN-ITER-088/tracked-changes.patch)。前后哈希分别 `{summary['source_before_sha256']}` / `{summary['source_after_sha256']}`；diff `{summary['patch_sha256']}`。旧 v7/v8 封板引用文件逐项重新核验通过，见 `original-seals-recheck.json`；旧实验代码字节未变。

阶段账本见 [stage-ledger.json](F:/CGKN-ITER-088/verification-v2/stage-ledger.json)：12 产品 DEV / 139 调用 / 21.46484 元；2 协议校准 / 7 调用 / 0.26802 元；v7 正式 4 次 / 151 调用 / 10.13832 元；v8 正式 28 次 / 136 调用 / 15.96124 元。合计 46 个付费模型尝试，正式 287 调用 / 26.09956 元。

DEV 8→12 可追溯到 `authorization-amendment-v5.json` 和会话“额外允许最多4次成对DEV校准”：当时按额外四次运行、组成两对落盘，原 8 次列表保留。之后累计费用授权降为 50 元并释放验收预留，未恢复 100 元。此次没有额外付费授权。

旧正式结果仍为 0/32 自主达标、32/32 NOT_DELIVERABLE、未运行 0；v7/v8 不同配置分层。B1/D1 已评权重共 10、待评 90、范围 0–90，不是完整总分 0。D1 的补充理由是**未证明覆盖目标流程的有效候选测试**：起点没有新流程，新增源代码副本中的 CGKN 测试不覆盖视频/宣传目标。有效复用允许，不能仅凭没有新测试文件判零。无领域输出为 `UNTESTED / NO_CANDIDATE_DOMAIN_OUTPUT`；真人待审单列，绝非只差签字。旧四次 SELF_EVOLVE 实际运行不追溯改写，其可启动父脚手架尚未证明自建产品维护性。

## 状态根因及受限修复

旧链路：v8 runner → CGNKRoute → AgentProjectLoop → apply_tree_edits / compile_tree → FeedbackDAGRunner → DAGRunner → FileRunStore。第一次缺 `config.executor_ref`，请求构造在 executor 调用前失败，v8 将原始 ValueError 保存为 FAILED。第二次原模型合法 update_config，且新增 n2/n3/n4；loop 以同一 run_id、resume=True 提交，旧 runner 比较 `set(state.nodes)` 和 `set(dag.by_id)`，从 `{{n1}}` 到 `{{n1,n2,n3,n4}}` 时拒绝。**这里没有被比较的图指纹，也不是字段排序或错误目录加载。**

原始两响应未经修正重放：[before](F:/CGKN-ITER-088/replay-before/protocol-v8-r-cgnk/replay.json)，包含每次 tree/DAG/config/dependency、存储位置、前后状态、执行次数和完整新复现栈。旧 runner 只保存错误文本，不能把新复现栈说成旧运行已记录的栈。所有 13 个正式同文本错误也逐一重放，并对照各自实际持久状态节点集合，见 `verification-v2/historical-state-comparison.json`；均在新增节点的首次提交不匹配，非仅凭错误文本归类。

当前文档和编辑器允许构图/编辑，既有 runtime 支持固定图 resume 及显式子图 retry，却没有追加节点的状态提交能力。因此本次明确是**有限增量提交能力补齐**，不是把任意原地编辑假称既有合同。改动限于 canonical `cgkn/runtime/dag_runner.py`、`cgkn/state/models.py`、`cgkn/agent/project_loop.py` 及合同文档：

- 普通 resume 比较真实定义（配置、依赖、目标），不同图仍拒绝。
- loop 显式 `accept_edits=True` 可追加未执行节点、修改未完成节点；目标改变或删除已存在节点拒绝。
- 变更已成功节点/其已成功依赖后继，必须显式 retry_node；不悄悄重跑或复用旧结果。
- 在同一个 canonical RunState 原子写入 DAG、revision 和节点记录；独立 definition 文件是可读副本。保留 attempt 历史和不受影响的成功结果。旧状态需匹配原 definition 才能加载。
- 不清空 store、不更换业务 run_id、不删一致性检查；不新增 planner/scheduler/state authority，不启用 Router 或团队 runtime。

修复后同一原始序列能继续，首次非法请求没有 executor 动作。两个实际隔离入口的 [回放审计](F:/CGKN-ITER-088/actual-route-replay-v2/results.json) 保留真实 Docker 后端和 tool 结果。CGNK 第二决策四个动作执行后因两条已录响应耗尽而停止；原模型的 `PLACEHOLDER_WILL_BE_DYNAMIC` 原样写入，**复制内容仍错误，不是模型协议或产品成功**。Direct 原五条响应可完成合成复制。回放中的 model_calls 是录制响应计数，真实 Provider 调用均 0。

`formal-006-cgnk` 单列：原模型给 retry_node 的 payload 放入 config，违反当时文本要求 `{{}}` 和 canonical TreeEdit 白名单；宽泛 JSON schema 的 payload:object 没拦住它，是结构 schema 不充分与模型语义契约违规，不是 DAG 状态错误。没有代修该 payload；修复后仍明确拒绝。

## 有限回归及隔离

[回归记录](F:/CGKN-ITER-088/verification-v2/regression.json)：**65 passed、0 skipped，18.69 秒**。覆盖 R1 保存重载执行一次；R2 缺执行器原序列与合法修正；R3 追加节点复用成功节点/依赖；R4 原子提交失败保留原状态、提交后重建 runner 继续；R5 真不匹配与无显式 retry 的成功节点变更拒绝；R6 同 node_id 不同 run_id 隔离。因新增原子图状态提交，补了一个针对提交前写失败的受控检查，无 soak。另有原 canonical runtime/agent/state/预算及新预算 adapter 检查。

首次 64 passed / 1 skipped 是 tests/test_provider_api_budget.py 的 profile-marked 账本测试，标 live_provider 但不发网络请求；显式 --run-profile-marked 后已覆盖。生产出口在回放及本次测试进程由 no_provider 阻断，意外调用会记日志并失败；合成 transport 只用临时账本和假响应。产品方向 gate PASS，git diff --check 通过。只运行相关范围，不称全量回归。

已通过的 v8 隔离没有扩建：镜像 `{IMAGE}`、只读输入、可写候选、网络 none、容器外审计及 120 秒杀整个进程树规则保持。此次两路线实际注册入口又回放验证，工具/挂载策略未改，复用旧完整 canary/lifecycle 证据；全部新容器已关闭。宿主只修框架/评测工具，不修任何候选业务代码、测试或数据库。

## Direct 14 次预算核查

[完整离线表及未发请求重构](F:/CGKN-ITER-088/budget-audit-v3/audit.json)。所有条目明确 RECONSTRUCTED_UNSENT_REQUEST；以实际最后请求、原始响应和原始工具输出构造下一轮，逐个核对已有请求 history。没有伪造已发请求。

{table}

价格均为输入 20、输出 60 元/百万 token 的保守费率；每次固定 8192 输出预留 0.49152 元，输入字节上界加 4096 token 的余量为 0.08192 元。完整表含每次全局累计、余额、输入/输出分项、未结算预留和拒绝谓词。14 次无未结算占用、重复 call_id/request_identity；旧实际请求 max_tokens 与记录完全一致，拒绝前没有创建新预留。

11 次较小输出可以容纳；008/016/020 输入上界已超过余额，降低输出无济于事。012 宣传 B+1 读入约 59 KB 解包列表，下一输入预留 1.81338 + 输出 0.49152 = 2.30490 元，超过余 2.08656 元；输出降到 4553 才能按同一规则准入。它同时属于上下文增长和固定输出限制，不是凭已花 0.41344 就断言账本错误。

五个旧 usage 不完整条目仍按其**原 reserved_input/output**计费，见 usage-supplement.json；并非新估算冒充真实 usage。新 policy 只按剩余额度选择 1024..8192 输出，并把同一个值传入 canonical 预留、请求记录、真实 transport max_tokens。合成传输回归已核验实际 body，不能只降低账面费用。输入规则、原始上下文和价格保持，没有语义摘要、静默删需求或缓存优惠。小于最低 1024 直接拒绝，无扣费重试。实际费用仍用同一本 canonical 账本，全局/单次/请求/token/时间上限继续生效。

费率依据本次核对的[Qwen 官方价格](https://help.aliyun.com/zh/model-studio/qwen3-8-max)和[DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)；20/60 高于北京 Qwen 12/36，亦高于 DeepSeek 峰时美元价按 10 元/美元保守换算，不依赖缓存或优惠。

## 新的一题两路线 DEV

[公开题与政策](F:/CGKN-ITER-088/dev-packet/public/task.json)、[独立验收规程](F:/CGKN-ITER-088/dev-packet/private/acceptance-protocol.md)、[冻结清单](F:/CGKN-ITER-088/dev-packet/freeze.json)，冻结 SHA256 `{sha(freeze)}`。已知 Source Cabinet 视频领域的新场景，非新独立项目：初始仅文件归档、预览、SQLite 身份，没有 ASR/检索定位/剪辑闭环。原始初始 zip 相同，不含参考实现、旧私有评分、历史诊断或本请求。

新 30 秒真实英文视频取公开联邦政府演讲 180–210 秒；[来源及公有领域说明](https://commons.wikimedia.org/wiki/File:John_F._Kennedy_Inauguration_Speech.ogv)，不与旧 0–75 秒片段重叠，但不声称新来源 family。首次抓取 429/空文件保留，第二次完整解码后使用。没有访问 ACFV CONSUMED_LOCKED Final。

要求 GUI 导入→实际离线 ASR→来源/时间/转录持久保存→搜索定位播放→GUI 选择边界并实际导出→重开访问，含非法输入与保留原归档。24 子项、六维权重、D>=3、领域质量与 G1–G6 不变。人工领域/可用性确认未完成时仍不得宣称最终自主达标。未来 SELF_EVOLVE 父产物需真实新增依赖流程/数据，旧四次不追溯重写。

私有参考通过真实 GUI 文件上传、离线 ASR、搜索、定位播放、导出播放、完整解码、重开持久化，12 个检查记录在 reference-validation-v2；这些不是候选得分。独立源比对音频相关度 0.99991，三帧误差约 0.80–0.93；错误时间段音频相关度 0.08623 被拒绝，坏文件解码退出非零。参考截图已查看；UI 朴素，不拿参考 UI 当真人质量通过。所有参考答案/日志留在私有区，候选只挂载 public 与独立 workspace。

顺序 Direct→CGNK，seed 8801，各一次；qwen3.8-max Agent / deepseek-flash worker，仍比较完整系统。CGNK **四次决策上限保持**，不额外加规划器。每路线默认 80 请求/100 万 token/60 分钟，先到停止；业务格式/实现失败不宿主修复、不追加尝试。最终终止开发、冻结候选后独立验收，不回流私有反馈。开发里只记有意义的业务修改/GUI闭环/有效测试里程碑，尚无新候选里程碑。

## 具体待授权方案和入口

方案每路线 **20.80 元**，一对 **41.60 元**；离线 ASR、校准与验收均零付费调用。推导不是历史平均价：旧 dev-video-direct-02 的 12 次**逐请求上界预留合计 13.39816**，加四次按该运行最大请求预留 1.85012 的允许量，共 20.79864，向上取 20.80。四次是为 GUI/重开验证、回归结果和交接预留的工作量估计，不保证能交付；任何大上下文请求仍须重新逐次准入。

拟用原余额 2.16758 元，累计上限需由 50 增至 **89.43242 元**，即增加 **39.43242 元授权**。两路线相同上限，所有内部 worker/规划/失败计费，未花金额不算消耗。cost-plan.json 的 approved=false，不是授权凭据。

零调用可复核入口（已实际执行）：

```powershell
Set-Location D:\\CGKN
python -m experiments.diagnostic_088.run_pair --packet F:\\CGKN-ITER-088\\dev-packet
```

仅在用户明确批准上述方案后，由可信宿主写入含原话引用的独立 authorization.json，再执行：

```powershell
python -m experiments.diagnostic_088.run_pair --packet F:\\CGKN-ITER-088\\dev-packet --authorization F:\\CGKN-ITER-088\\authorization.json --execute
```

缺授权会在 Provider 构造前拒绝；同一输出目录只允许创建一次防止静默重跑。该命令只执行新一对并安全冻结，随后宿主按冻结独立 GUI/媒体规程完成验收，绝不重启原 32 格。明确模型失败保留，确定性框架错误不对受影响路线重复投钱；另一已授权路线仍可一次完成。

## 归档和结论边界

沿用既有 Project Corpus，关联 `entry-iter076-closeout-v8`，本次条目 `entry-iter088-state-budget-dev-preparation`；回执另存 corpus-receipt.json，验证只证明对象/索引一致，不证明产品通过。本次基础设施和评测错误均列在 diagnostic-events.json，含预算未知 usage 字符串处理、回放报告属性名、GUI 自动播放手势和 Windows 编码，原失败文件保留。无新产品语义辅助、无强模型救援、无私有反馈泄漏；本次未创建付费开发会话。

回归通过只说明指定状态和预算路径满足有限契约。新 DEV 0/2 启动，尚无新产品能力比较证据，更无架构普遍优势结论。此时继续真实 DEV 唯一缺少的是针对上述新阶段费用方案的明确授权；最终产品达标仍需实际开发、独立验收及所规定真人审阅。
'''
    Path('project_management/summaries/ITER-088-state-budget-dev-preparation.md').write_text(text,encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
