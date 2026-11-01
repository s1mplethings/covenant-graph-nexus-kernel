# ITER-090：CGNK 完整视频项目工程 DEV

本轮已经实际修改框架、运行真实 CGNK 开发、完成两版业务候选的独立 GUI/媒体/持久化验收，并运行候选自有测试和有效错误变体。**最终候选的正常视频闭环可用，但未达到完整质量交付门槛，主状态 NOT_DELIVERABLE，人工领域审查 PENDING_HUMAN。** 不是新的盲测，也没有运行 Direct 或重跑原 32 格。

产物与证据：

- 最终原始冻结候选：`F:/CGKN-ITER-090/dev-stage-04/frozen/candidate.zip`。
- 原样展开的项目：`F:/CGKN-ITER-090/deliverable/project/`，包含模型生成的 `app.py`、`test_app.py`、`README.md` 和保留的起点数据。
- 首个业务候选：`F:/CGKN-ITER-090/dev-stage-03/frozen/candidate.zip`；前两个基础设施中断检查点也保留。
- 最终 GUI 截图、操作原始记录、数据库和媒体证据：`F:/CGKN-ITER-090/acceptance-v2/`。
- 完整账目、24 项质量记录、干预、worker 来源与封板：`F:/CGKN-ITER-090/closeout/`。

## 实际结果

| 责任 | 最终独立结果 |
|---|---|
| 起点和保留行为 | 原始 Source Cabinet；归档、预览、下载和 SQLite 身份本来已有，不计新增 |
| GUI 新视频导入 | PASS，使用授权的 30 秒真实视频；新身份和文件对应 |
| 真实 ASR | PASS，实际 whisper-cli 处理；转录文本、分段时间与该素材关联 |
| 搜索与定位播放 | PASS，`permit` 命中 13.28 秒；点击后正确素材在约 13.80 秒播放 |
| 区间导出 | PASS，GUI 选择 5–15 秒；独立解码、时长、画面和音频对照通过 |
| 输入边界 | PASS，负值、相等、反向、超时长、坏视频及空上传均有拒绝 |
| 失败后的正常操作 | PASS，坏输入后普通文件导入仍正常，已有素材/结果保留 |
| 普通文件兼容 | PASS，GUI 上传 task.json、列表和下载；HTTP 下载字节与原输入一致 |
| 重开和持久化 | PASS，应用和浏览器重启前后数据库记录、文件哈希相同，GUI 可再搜索/访问 |
| 无音轨状态 | 第一版 FAIL；模型修复后 GUI 显示 `ASR: no audio track in source` |
| 自有测试 | 第一版独立运行 12 passed；最终 14 passed，31.50 秒，2 CPU 条件 |
| 测试效果 | 第一版漏检不可解码导出；最终能拒绝该变体，但仍漏检错误导出时长 |
| 重复操作副作用 | 未完整评估，不能用其他成功检查补成 PASS |
| 一般 ASR 执行错误 | 代码检查发现错误传播风险；两次故障注入均未命中，记 EVALUATOR_INVALID，不能宣称运行缺陷已确认 |
| 人工质量/可用性 | PENDING_HUMAN；自动 GUI 轨迹不冒充真人评审 |

最终 GUI 共记录 38 次操作；从可信启动记录到最后操作的时间上界约 6.6 分钟，包含中间取证时间。截图已在 Codex 请求打开；工具返回 queued，未声称已展示到用户屏幕。

## 有意义的负面证据

第一次错误变体在一次性副本中把导出替换成 19 字节不可解码内容。第一版自有导出测试仍 PASS；独立 ffprobe 失败。该原始失败及复现条件公开给 CGNK 后，worker 修改了业务和测试。最终同一变体触发 `exported clip is not decodable by ffprobe`，自有测试 FAIL，说明修复确实增加了检错能力。

但是，另一有效变体将用户选择的 0–1 秒导出替换为约 6.128 秒的可解码音视频。最终两个自有导出测试仍 PASS，独立时长核验明确超过原 1 秒容差。证据在 `test-effect-duration/trigger-verification.json`。这不是语法错误，也没有修改原候选；它证明测试仍未覆盖选段的实际终态。自有重开测试也只做数据库再次读取，没有应用/浏览器重启回归；真正重启通过来自宿主独立验收，不能算成模型测试覆盖。

工程已确认 **71.25 分**，已评权重 **95**，待评权重 **5**，完整可能区间 **71.25–76.25**；不得归一化。D1–D4 为 2/2/2/2，D 均值 2，明确低于要求的 3。领域 Q1–Q4 未完成人工评审，不填零、不宣称达到 75。G1/G2/G5 的正常真实流程通过；G3 的有效测试义务未完全满足，G4 有待评重复副作用，G6 部分完成。详见 `closeout/quality.json`。

## 框架断点和实际修复

实际 HEAD 仍为 `0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`，保留原工作树修改，没有 reset、提交、推送或发布。本轮修改相对 `before.zip` 单独保存，不能把整个 git diff 都归成本轮成果。

已核对 ITER-089 原始第三次成功读取及第四次请求：第四次只传入失败节点结果，读出的任务正文没有进入实际 Agent 请求。

本轮核心改动：

1. `AgentDecisionContext` 和原 `AgentProjectLoop` 传递成功与失败结果；固定六条原始结果窗口，完整结果保留在自身记录中。
2. 新的确定性 `ActionComposer` 将模型选择的能力、参数、依赖转成普通树编辑，按目录绑定唯一 executor 并生成标识。模型自己的动作摘要保留，长输出机械截断并附引用/哈希；宿主没有撰写业务摘要。
3. 仍由原 CapabilityTree、compile_tree、DAGRunner、ExecutorRegistry 和 FileRunStore 执行。没有另造规划器、调度器、角色流程或启用 dormant Router。
4. 取消独立四步构造限制；Agent 和 worker 共同受 80 请求、100 万 token、3600 秒和同一费用账本约束。
5. 普通续接不再自动重放失败/超时/阻塞节点。显式重试或校验后的配置变更才重新执行；成功节点继续复用。
6. Worker 可先读取再提交写入；完成结果保留读取观察、修改路径及输出。实际成功业务 worker 节点共 3 个，其应用、测试和 README 修改进入最终候选。13 次 worker 请求不等于 13 次成功业务委派。
7. 工具超时仍终止整个开发容器及子进程、重建同一边界、保留工作区、不重放动作；无宿主 fallback。真实 DEV 中确实发生过此生命周期。

使用版本 v1→v3→v4→v5。两次框架中断都冻结候选、上下文和账目，只修通用框架，再从自己的候选续接。第一轮中断时在途请求没有可核验用量，其占用完整保留。v3 费用、调用和时间没有重置。v3 源码归档复用父包时仅新测试断言与父包有差异；实际文件哈希保存在 v3 freeze，完整修正版在 v4 源码包，详见干预记录。

最终离线 v6 另外明确了测试能力的 `config.timeout_seconds`（默认 30，最大 120），以及 context hash 标签；不冒称 v6 又跑过付费产品开发。模型此前多次误用未安装的 pytest `--timeout` 参数，并在没有传 executor timeout 时以为上限已提高，导致重复超时。最终完整测试实际需要 31.50 秒，超过默认 30 秒。说明和工具目录已经补明；这些浪费仍计入本轮。

## 验证、权限和错误账目

- 初始相关回归 56 passed、0 skipped。
- Worker 回传修复回归曾有 42 passed 加 1 个测试断言类型错误；修正后针对性测试通过。另一次不适用的 pytest CLI 参数报错也保留，未算产品失败。
- 后续相关检查 11 passed；真实 runner 的无模型 conformance 验证了成功结果进入请求、worker 读写/回收、非法动作无树提交、成功不重放和后端不可用时关闭。标 HARNESS_CONFORMANCE_ONLY，不算模型产品成绩。
- 全仓方向检查完整输出 108404 字节，FAIL，共 775 条错误：773 条来自 `.service_worktree`，2 条旧 benchmark 活跃路径；无本轮运行文件错误。没有清目录或放宽规则。检查与修改并行，不宣称它是最终精确快照的全仓 PASS。
- 开发环境始终 network=none、非 root、只读根文件系统、仅公开输入只读和自身候选可写；shell、文件、浏览器通过同一容器。没有注册宿主 shell、Docker 控制、个人 MCP 或连接器。
- 两次 ASR 注入均没有实际故障标记，且生成了正常转录。第一份临时失败判断已由追加的 invalidation 记录明确作废；两次都不计产品失败，不无限重试。
- 本机交互预览代理启动被自动审批拒绝，原理由 `blocked by policy`，没有启动，没有改用其他方式绕过。已实际验收的容器 GUI、截图和源码仍保留；不能声称宿主 5090 预览地址可访问。

宿主业务代码/测试/数据库修复为 0；宿主框架中断修复 2 次；允许的公开验收反馈续接 1 次。没有引入强模型救援或把 Direct 代码/私有诊断交给 CGNK。此过程有显式框架干预和已暴露测试，**不能称无人干预首次成功或未见题自主达标**。

## 连续资源与停止原因

| 项目 | 实际 |
|---|---:|
| Agent 请求 | 67 |
| Worker 请求 | 13 |
| 合计请求 | 80 / 80 |
| 可核验返回模型 | qwen3.8-max 66 次；deepseek-flash 11 次 |
| 新的未知用量请求 | 3 次，保留各自上界，没有重复预留旧请求 |
| 已知真实 input/output | 707788 / 28204 tokens |
| 含未知占用的保守 token | 829537 / 1000000 |
| 累计实际开发墙钟 | 815.56 秒 / 3600 |
| 本轮新增保守费用 | 18.53810 元 |
| 历史累计保守费用 | 87.98930 元 / 89.43242 |
| 剩余金额 | 1.44312 元 |
| 新传输重试 | 1 次，已用完，另计请求和费用 |

费用是保守费率账目，不是已查询的实际账单。原 ITER-089 的未知费用占用没有释放或重复扣减。最后第 80 次 Agent 请求提出委派，但 worker 在发送前被共享请求上限拒绝；未偷偷再发第 81 次。停止原因是**请求硬上限**，不是验收预留，也不是只完成基础设施。独立验收和归档新增付费调用 0。

本轮为一个连续工程 DEV 链，4 个阶段、2 个有业务修改的候选；并非 4 个独立项目/实验。原正式 32 格没有变化，新正式运行 0，Direct 新运行 0。没有新的架构比较或普遍泛化结论。

## 使用与复现

模型生成的 README 位于 `F:/CGKN-ITER-090/deliverable/project/README.md`。在声明的 Linux 媒体环境内，实际应用启动入口为：

```text
cd /workspace
python app.py
```

GUI 是该环境内的 `http://localhost:5000`。这不是已经映射到宿主桌面的地址。实际依赖镜像为：

```text
sha256:1059097764b634a5b1e2ed4bf035700d6ce47dfd206044c1b9bf63300523ee20
```

使用全新目录恢复独立隔离副本（不调用 Provider）：

```powershell
python experiments/product_eval_076_v8/inspect_candidate.py --root F:/CGKN-ITER-090/review-copy-01 setup --snapshot F:/CGKN-ITER-090/dev-stage-04/frozen/candidate.zip --public F:/CGKN-ITER-090/packet-v5/public --argv '["python","/workspace/app.py"]'
python experiments/product_eval_076_v8/inspection_action.py --root F:/CGKN-ITER-090/review-copy-01 --url http://127.0.0.1:5000 --screenshot home.png
python experiments/product_eval_076_v8/inspect_candidate.py --root F:/CGKN-ITER-090/review-copy-01 command --argv '["python","-m","pytest","test_app.py","-v","-p","no:cacheprovider"]'
python experiments/product_eval_076_v8/inspect_candidate.py --root F:/CGKN-ITER-090/review-copy-01 close
```

这类独立验收命令上限 120 秒；不要将它的测试成功回填成开发阶段曾完成的测试。重新评测应绑定同一个冻结候选。

继续付费开发首先需要明确调整共享请求上限；现有 1.44312 元余额不能自动越过 80 次限制，任何请求还必须满足累计费用保护。本轮不擅自续开新尝试。最小有价值的后续目标是由 CGNK 补上真实选段时长/来源及重开回归，再验证一般 ASR 错误状态；不能由宿主补业务实现。

Corpus 沿用 `F:/CGKN-ITER-060/project-corpus`，追加本轮基础设施、连续 DEV、首个和最终业务候选记录；各条目类型区分阶段与链路汇总，避免重复计样本。对应清单/对象/索引校验收据保存在 `closeout/corpus-receipts.json`。旧 ITER-089 的全部封板文件复核结果另存，没有覆盖历史。
