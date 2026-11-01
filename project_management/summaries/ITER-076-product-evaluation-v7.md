# ITER-076：实际隔离接线、真实 DEV 与正式产品评测 v7

本轮已经越过基础设施阶段，实际启动并冻结 **4/32 次正式运行**，完成两组配对的独立 GUI 检查。**自主达标 0/4，NOT_DELIVERABLE 4/4，28 格 NOT_RUN**。并非 32 次失败。另有累计 12 次 DEV，全部保留；所有模型开发尝试共 16 次。没有把最后一个较好的 DEV 产物替换到正式结果。

当前停止原因是冻结的成对资源预留不足，不是容器未接入。累计费用保守计量 **31.60316 元**，实际账单未查询。用户最新授权上限为累计 **50 元**；其中开发上限 40 元、验收预留 10 元。开发余量 8.39684 元，无法预留下一对的 12 元。未擅自降低已冻结的单次 6 元上限、动用验收预留或增加授权。

## 版本、原阻塞和实际接线

HEAD `0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`，分支 `codex/provider-gateway-integration-20261017`。本轮未提交、推送、合并或发布；未修改 kernel，保留用户 `.api_lab_worktree/`、`.service_scratch/`。历史封板、原预检和上轮报告未覆盖。

原失败探针是评测方新建的禁区文件 `F:\CGKN-ITER-076\preflight-20261027\route-canary-private.txt`，不是合法项目外依赖。旧 CommandExecutor 以宿主权限执行 Python，读出了 `SYNTHETIC-NOT-A-SECRET`。独立 Docker 检查原先绕过 runner/路线/注册表，不能证明真实路线安全。合成探针可读不证明真实秘密泄漏，原阶段没有正式运行，未记为正式协议污染。

现在的实际调用链：

- Direct：`formal_run.main → runner.run_route → create_route → DirectRoute.run → ContainerBoundary.execute → docker exec -i → 容器内工具`。
- CGNK：同一 runner → `CGNKRoute → AgentComposer/AgentProjectLoop → DAGRunner → ExecutorRegistry → IsolatedExecutor`；LLMExecutor 的文件动作接到 `ContainerFileActions → ContainerBoundary`。未另写规划器，未手工补 executor_ref、Blueprint、树或 DAG。
- 宿主管理接口只负责启动/关闭边界和取证，不注册给模型。注册入口是 command、文件读写/列举/补丁、容器 Chromium；解释器、搜索、HTTP、SQLite、子进程都通过同一容器。未注册宿主文件工具、个人登录浏览器、MCP、连接器或 Docker 控制接口。

镜像固定为 `sha256:1059097764b634a5b1e2ed4bf035700d6ce47dfd206044c1b9bf63300523ee20`。`/input` 只读、`/workspace` 本运行可写、独立 `/tmp`，无外网、无宿主根目录/.git/socket/私有验收/兄弟运行挂载。容器非 root、只读根、移除 capabilities；本运行 localhost 服务互通。宣传受控目标是另一独立进程/文件系统，账户绑定 run_id，只返回本运行对象，不代表真实平台认证或公开传播。

单个工具最长 120 秒；前台服务不自动转后台。模型须自行选择启动方式、重定向日志。超时终止整个开发容器及子进程，保存的 workspace 可冻结，内存/tmp 不保留；不重发、不回退宿主。正常提交也终止开发会话，独立验收用候选副本启动应用。

`conformance-v7-01/conformance.json` 是 **HARNESS_CONFORMANCE_ONLY**：Direct 12 个、CGNK 13 个正向/禁止动作，两路线都通过超时、后端缺失、取消后无 fallback、真实 GUI/SQLite、只读/路径/符号链接/兄弟 canary、受控目标互通检查。原始 Docker inspect、动作、输出 blob 和审计链证明了实际执行位置，不只检查 sandbox 字段。必要检查未跳过。

发现并保留一项 DEV 文档透传缺口：AgentDecisionContext 不序列化 constraints，CGNK Agent 未收到生命周期说明。v7 把同一通用工具政策传到公开 goal，通过实际路线回放验证；不修模型输出，不追加第 13 次付费 DEV。两个受影响旧 DEV 原样保留，见 `tool-documentation-gap-v7.json`。之后两次真实正式 CGNK 调用使用已冻结 v7 通路。

## 冻结题包与起点

冻结文件：[freeze-v7.json](F:/CGKN-ITER-076/benchmark-v5/freeze-v7.json)，SHA256 `624a49591b5e57298ac2a0880f244ee79ed339f83fbd8e1c020ce6ec383bf48d`。全部 16 题卡、32 路线格、评分、输入、初始快照、私有参考/验收合同和关键执行源码分别绑定哈希；正式入口拒绝回放 Provider、未登记运行或已变化的冻结材料。种子 7601、原路线顺序保持。

TAKEOVER 基础产品只有真实文件归档/预览/下载、SQLite 标识和旧记录。ASR/检索/导出或宣传/批准/排程/发布均是尚未完成的实质增量；不把宿主脚手架算作模型交付。CREATE 仅依赖/启动约定。B+2 的公开历史来自实际执行过的参考记录，包含可解码旧导出、转录、反馈和受控回执，明确不是生产数据或真人审查。SELF_EVOLVE 只指向各路线首次 B0，不允许以较好重复替换。

| 档位 | 视频新增责任 | 宣传新增责任 |
|---|---|---|
| B−2 | 实际导入/ASR、定位预览、选边界导出与保存 | 原始证据、文案/媒体、GUI 编辑批准、发布与回读 |
| B−1 | 两视频检索、编辑标签、单失败独立重试 | 多内容、排程/取消/修改、修改后重新批准 |
| B0 | 素材证据问答、字幕导出、接受/拒绝反馈 | campaign、版本批准、排程、回执和反馈 |
| B+1 | 一个旧版本导出晚到场景 | 远端已接受但响应丢失，核对或待核对 |
| B+2 | 一次旧元数据兼容升级 | 两个原始版本的对比宣传并保留历史 |

视频是允许使用的 JFK 真实公共素材，75 秒和同源 40–75 秒重叠派生片段。下载新片段两次遭遇 HTTP 429/空文件，原始失败留存；没有将空文件当成功。正式材料明确与 DEV 可能同源，不声称未见媒体或跨项目泛化。宣传输入是完整允许源码归档和原始版本资料，没有宿主事实摘要。CONSUMED_LOCKED Final、生产库和无关凭证未访问。

私有参考验证实际执行 ASR、视频/音频解码、字幕导出、版本扰动、批准失效、远端接受后断开、重复检测、排程、迁移和重开。`reference-checks.json` 23 项通过，另有时序触发、实际媒体帧和 GUI 记录。参考能力只证明题目/检查器可执行，不是被测成绩。领域用途/真人可用性仍待评。

## 正式结果与评分

| 运行 | 题目 | 路线 | 请求 | 保守元 | 冻结候选与结果 |
|---|---|---|---:|---:|---|
| formal-001-direct | 视频 B−1 | Direct | 76 | 5.02128 | 原脚手架，NOT_DELIVERABLE |
| formal-002-cgnk | 视频 B−1 | CGNK | 1 | 0.03358 | 原脚手架，NOT_DELIVERABLE |
| formal-003-cgnk | 宣传 B−1 | CGNK | 1 | 0.03928 | 原脚手架，NOT_DELIVERABLE |
| formal-004-direct | 宣传 B−1 | Direct | 73 | 5.04418 | 原脚手架，NOT_DELIVERABLE |

Direct 持续输出 `name/parameters` 形式，而公开工具协议要求扁平 `action`；原始错误原样返回，直到下一请求预留触发单次费用门槛。CGNK 的原始规划缺少执行器标识，canonical runtime 报 `request identity, component_ref, and executor_ref are required`。宿主没有修 JSON 或语义。错误分类是模型/实现未交付，不把它改称环境不可用。

四个候选 zip 与各自初始 zip 的所有文件字节相同。逐个按 README 启动独立验收副本，通过独立 Chromium 看见 Source Cabinet 并重开，截图/DOM/日志已保存。没有 ASR/宣传流程或被测测试，G2/G3 已确认失败。视频 G5 未达到真实处理要求；宣传 G5 另有真实目标未授权。没有通过 API、数据库或宿主补代码替它们完成业务。

24 子项全部列出：只确认 B1=0、D1=0，已评权重 10，待评权重 90，确认分 0，可能区间 0–90，**不是总分 0，也不按已评部分归一化**。其余未评、G 门槛和 Q1–Q4 的缺失逐项保留。缺核心流程与缺自身测试共用明确 defect_id，其他关联项不自动重复扣分。已确认必要条件失败，主状态 NOT_DELIVERABLE；真人与领域质量未评不掩盖这一事实。

两题交付差均为 0；完整质量分差不可定义。CGNK−Direct 成本差分别为 −4.98770、−5.00490 元，反映提早失败，不能解释成效率优势。没有未配对运行。模型返回身份为 `qwen3.8-max`；CGNK 配置另有 `deepseek-flash` worker，正式两次未进入 worker 执行。所有阶段按两个完整系统解释，不将差异归因于架构。

| 分表 | 计划 | 实际启动/开发结束并检查 | NOT_RUN |
|---|---:|---:|---:|
| TAKEOVER 首次 | 20 | 4 | 16 |
| CREATE | 4 | 0 | 4 |
| B0 重复 | 4 | 0 | 4 |
| SELF_EVOLVE | 4 | 0 | 4 |

完整逐格状态及 24 子项：[matrix.json](F:/CGKN-ITER-076/closeout-v7b/matrix.json)。重复没有结果；自身演进未启动，不能推断兼容或前序恢复效果。

## DEV、成本、干预与审计

累计 12 次真实 DEV，包含本次额外 4 次（两对）。新视频 Direct02 的开发因自行前台启动服务且设置 5 秒超时而终止；原 receipt 的 BLOCKED_ENV 保留，并另行解释为工具超时，不伪称服务不可用。候选冻结后独立 GUI 实际导入/ASR、检索 constitution、选择 29.36 秒、导出 20–30 秒片段；H264/AAC、10.009676 秒、完整解码通过，音频 32000 样本峰值 17140，浏览器显示解码帧。进程重开后视频/转录/片段仍可读，自带测试 27 passed。缺用户启动说明、完整错误分支/变体测试与领域审查，故只有 DEV PARTIAL。旧宣传 Direct03 的批准/修改/持久化部分结果也独立保留。两者都不算正式成功。

累计 **290 次 Provider 请求**，已知实际 input 1,130,343、output 81,737；5 个旧调用 usage 不完整，预算按保守上界计入。计费 token input 1,212,067、output 122,697；费用 31.60316 元不是已核账账单。Provider 延迟加总 3048.03 秒，不等于完整墙钟时间。Direct 全部尝试费用 27.91966 元，CGNK 3.68350 元；含失败、DEV、规划/worker，验收本地运行新增付费调用 0。两路线每个达标交付成本都不可定义，因为分母为零。

宿主做了通用执行边界/文档透传/预算/冻结/归档、公共初始夹具、私有参考和独立验收；没有改候选业务代码、测试、数据库或迁移，没有强模型救援，没有私有反馈回流正式 Agent。正式动作审计链均验证，正式语义辅助计数 0。旧 DEV 的截图覆盖缺口和文档缺口明确保留，未拿来支撑正式自主成功。原失败预检不改为 PASS。所有本轮容器已经关闭，无跨运行遗留开发会话。

相关检查实际 **38 passed、0 skipped（25.63 秒）**，范围为 gateway/Provider 预算和新正式准入防篡改/拒绝假 Provider 检查；未跑全量回归。原 skipped 是带 live_provider 标记但使用模拟预算的用例，本轮以 `--run-profile-marked` 执行，并非跳过必要隔离。基础设施和参考验证不计产品评分。

`product_direction_gate.py` 在当前 HEAD 的完整 tracked source 导出加本轮评测 Python 上实际 PASS，排除用户 ignored 工作树，原始范围/输出见 `direction-gate-v7.json`。报告生成第一次因旧 Provider 记录的 model=null 排序异常停止，保留 `closeout-v7`，修正报告器后写入新的 `closeout-v7b`；没有重跑模型或改候选/评分。

归档复用 `F:\CGKN-ITER-060\project-corpus` 的既有 schema/store/index；只验证本轮指定记录，不扫描完整私有 Corpus。新正式记录 `entry-iter076-formal-001-direct` 至 `entry-iter076-formal-004-direct`，汇总 `entry-iter076-closeout-v7b`，关联原 `entry-iter076-preflight-20261027`。Manifest、对象哈希和 SQLite 索引校验通过；旧记录保持 immutable。回执在 [corpus-receipts.json](F:/CGKN-ITER-076/archive-v7-01/corpus-receipts.json)。Corpus capture 的 PASS 表示归档成功，不表示产品通过。

## 恢复与结论边界

实际停止原文见 [budget-stop.json](F:/CGKN-ITER-076/formal-v7/budget-stop.json)：`PAIR_BUDGET_RESERVATION_UNAVAILABLE`，used=31.60316、required_pair=12、development_ceiling=40。可直接复核：

```powershell
Set-Location D:\CGKN
python experiments/product_eval_076/formal_run.py --seal F:\CGKN-ITER-076\benchmark-v5\freeze-v7.json --root F:\CGKN-ITER-076\formal-v7 --ledger F:\CGKN-ITER-076\global-provider-budget.json --lab-root D:\cgkn-provider-api-lab
```

该命令会安全重现预算阻塞，不发新请求。继续付费正式矩阵必须有明确的新资源/协议授权并另立版本，保留 v7 与成对规则；不能看到结果后悄悄降低每次额度、换模型或覆盖旧题。当前 50 元合同下没有可合法启动的下一对。真实平台授权只影响宣传 G5，不是本次 ACFV 停止理由。

在本轮固定题包、版本和预算下，观察到两路线在 B−1 正式任务均未产生新增业务实现，尚无 CGNK 架构收益证据，也不能据此推断更高档产品能力。最小有价值的后续验证是独立 DEV 上核验模型是否遵循已公开动作契约；模型自行修正格式，宿主不补 JSON。只有另获校准/资源授权后执行，不拿已见正式结果反复调优重报。当前已有的 DEV 视频闭环是有限正面证据，正式四次失败是反例，两者都保留。
