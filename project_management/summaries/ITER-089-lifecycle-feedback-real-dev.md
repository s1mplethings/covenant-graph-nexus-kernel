# ITER-089：生命周期、契约反馈修复与第二对真实 DEV

本轮已完成零费用修复验证、新版本冻结、一对真实视频 DEV、冻结候选独立验收及既有 Corpus 归档。**本对 0/2 自主达标、2/2 NOT_DELIVERABLE**。Direct 已形成可操作的视频流程，但测试、兼容性与音频核验仍有缺口；CGNK 未实现新增产品流程。没有重跑旧 32 格矩阵，没有代修候选业务代码。

| 项目 | Direct | CGNK |
|---|---:|---:|
| Provider 请求（含失败） | 36 | 4 |
| 返回真实模型身份的响应 | 35，qwen3.8-max | 4，qwen3.8-max |
| Worker 调用 | 0 | 0 |
| 保守计费，元 | 18.09752 | 0.26420 |
| 开发终止 | Provider 连接错误 | 4 次 Agent 决策耗尽 |
| 新业务实现 | GUI 导入、ASR、搜索定位、裁剪导出 | 无，候选与初始快照逐文件一致 |
| 独立产品结论 | NOT_DELIVERABLE | NOT_DELIVERABLE |

新增保守费用 **18.36172 元**；此前 **51.08948 元**；累计 **69.45120 元 / 89.43242 元**，剩余上限 **19.98122 元**。连续账本累计 490 次调用，本轮 40 次。失败的 Direct 第 36 次请求没有可核验的上游模型身份或 token 用量，保留 108279 输入、8192 输出的预留上界，不能当作免费，也不能把请求模型别名当实际响应身份。没有重试该付费请求。以上为保守费率核算，不是实际账单。

## 修复、权限与版本

实际 HEAD 仍为 `0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`，分支未 reset；原有修改保留。源码包含未提交补丁，不能只用 HEAD 描述实验版本。修改前保存 `F:/CGKN-ITER-089/before.zip`，新版本源码保存 `source-v1.zip`；旧 ITER-088 源码与证据 seal 未覆盖。

新增版本 `ITER089-DEV-v1`，冻结清单哈希：

`168827de8a6dcc87c62260617a641ff980f3c45d24d2bda73e06389f0520fd0f`

最小修改如下：

- `cgkn/agent/composer.py`：仅将模型响应解析/契约校验错误包装成带原始响应的反馈。Provider 传输异常不进入该处理器。
- `cgkn/agent/project_loop.py`：拒绝的编辑批次不改变原树、不执行工具；将原始错误及拒绝决策交给下一次已有决策机会。解析失败同样记录并消耗次数。仍为最多 4 次决策，没有扩大预算、补字段、代写计划或增加新调度器。
- `experiments/product_dev_089/isolation.py`：继承已有强制容器边界。工具超时仍删除整个运行容器、终止全部子进程，再按相同镜像、挂载与权限重建；工作区持久数据保留，进程、浏览器状态和临时目录丢失。返回 `TIMEOUT_ENV_RECREATED`，**不重放原命令**。重建失败即停止，无宿主 fallback。
- 新版本 runner/routes/费用适配和公共工具说明位于 `experiments/product_dev_089/`。旧 v8/088 实验源码未原地替换。原 CGNK 共同 Component/Executor/DAG/State 路线、dormant Router 和独立 Agent/worker 配置不变。

两路线均为新会话、独立工作目录与容器。只注册受限命令、文件、浏览器工具；模型没有 Docker 控制面、宿主 shell、私人连接器、其他路线产物或私有 oracle 的访问权。使用原不可变媒体镜像，非 root、只读根文件系统、公开输入只读、候选工作区可写、network=none，允许容器内部 localhost 服务互通。新生命周期源码哈希另写入审计链，不能用旧 policy hash 单独代表新行为。

## 零费用证据与范围

相关回归 **56 passed、0 skipped**，范围为 Agent、状态、增量图提交、费用策略、原始契约反馈。`no_provider` 防护开启，账本字节未变化，新增 API 调用与费用均为 0。证据见 `regression-v1.txt`、`zero-fee-check.json`。

两条真实 runner 路径的 HARNESS_CONFORMANCE_ONLY 检查完成：

- 合法公开读取、工作区写入、解释器/子进程、SQLite 持久化、媒体依赖可用；合成私有路径及只读输入不可越权。
- Direct 超时后旧子进程未留下延迟写入，已有文件与 SQLite 数据保留；后续命令能自行启动后台服务，浏览器实际读到服务内容。
- CGNK 原两条失败响应原样回放：第二次非法多节点重试被记录，第三次收到原始错误，原树未部分修改；合成基础设施纠正动作经实际 executor 执行。它是通路验证，不是模型解题成绩。
- CGNK 补充生命周期测试也经实际 Agent/DAG/工具入口完成超时、持久化保留、后续执行及浏览器访问。
- 两路线后端不可用时都在模型/工具执行前失败；重建失败不回退宿主。

**全仓 `python scripts/product_direction_gate.py` 返回 FAIL。** 范围内验证通过后开始付费时，该全仓扫描仍在运行；它后来报告 `.service_worktree/...` 中历史导入以及 `benchmarks/orbit_360_workbench`、`benchmarks/project_generation_v1` 路径等错误。这些路径未由本修复修改，也没有为了通过检查清理用户目录。工具返回的长输出被截断，保存了原始错误摘录及该限制，不能声称完整错误清单或全仓通过。见 `closeout-v1/direction-gate.json`。未合并、推送或发布。

## 新 DEV 的冻结责任与真实运行

两路线从同一 Source Cabinet 初始快照开始，未继承上一对候选、私有失败报告或宿主诊断。保留原视频题、原 24 项评分、MUST、真实媒体、私有验收与原始快照；只更新公共工具生命周期、配置版本和费用上限。

这是同一已知 DEV 场景的新版本运行，不是新的 holdout 或独立项目。输入仍为已授权公开领域 JFK 演讲的新 30 秒区间，真实离线 ASR；初始脚手架只有通用归档、预览、下载和 SQLite 身份保存。新增责任是 GUI→视频→ASR→检索定位播放→边界选择→实际导出→再次使用，不能把脚手架已有功能归功于模型。

按用户本轮授权，剩余 38.34294 元等分为每路线 19.17147 元；没有恢复验收预留，也没有提高累计上限。Direct→CGNK，种子与原顺序保留。每路线仍受 80 请求、100 万输入加输出 token、3600 秒限制，CGNK 的 4 次决策限制保持原样。公共策略、实际 API 参数、保守预留及连续账本一致。

Direct 自行处理了 `cd` 不是可执行程序、镜像没有 `bash` 等工具错误，最后自行用 Python 子进程启动应用。此次真实运行 **没有触发工具超时恢复**，因此不能把产品进展因果归于容器重建逻辑。第 36 次请求报：

`PROVIDER_TRANSPORT_FAILED: <urlopen error [WinError 10060] ...>`

这是开发终止的传输原因，不是候选产品缺陷；冻结后的产品仍接受独立验收。

CGNK 第一次创建的 4 个读取节点缺 executor_ref；第二次提出多节点 retry，被原始契约拒绝。第三次模型根据收到的错误，自行更新一个节点并实际读取 task.json；第四次再次提出多个 retry，被拒绝后耗尽 4 次决策。这验证了**真实模型确实收到反馈并完成一次自行修正**，但不证明其已能自主交付产品。没有 worker 调用，也没有业务代码修改。

## 独立验收与领域证据

开发会话均已终止，验收使用冻结候选的独立受限副本；私有 oracle、日志与评分未挂入候选，没有反馈回原 Agent。

Direct 已实际核验：

1. 按 README 启动，通过 GUI 新上传 scenario.mp4，记录新的素材身份。
2. 点击 GUI 转录，取得真实离线处理形成的分段文本；代码调用实际 whisper-cli，未发现硬编码转录。独立进程观察发生在 ASR 完成之后，不冒称抓到了运行中的 ASR 进程。
3. GUI 搜索 `permit`，结果对应 13.28 秒；点击对应新素材结果，播放器 src 指向正确素材，观察到 13.844628 秒、paused=false、readyState=4。
4. GUI 选 5–15 秒导出，浏览器实际播放；完整 ffmpeg 解码通过，时长约 10.050794 秒；三个位置的画面 MAE 约 0.845/0.910/0.803，与所选素材区间吻合。
5. 空上传、坏媒体、负起点、相等/反向边界、超过时长均有拒绝行为；失败后重新进行合法导入/导出，原已完成数据保留。
6. 重启应用与浏览器前后，数据库全部记录与文件哈希相同，GUI 中素材、转录、导出仍可访问。

**音频未获放行**：冻结音频检查的相关性为 0.15025，未达到 0.90。事后只读诊断将延迟采样网格从 10 ms 改为 1 ms 后为 0.81982，仍未达到阈值；该诊断不覆盖原失败、不放宽阈值，也不作为评分替代。音频来源/时间对齐尚需独立核查，不能直接断言文件是错误音源，也不能写成真实媒体全部通过。领域 Q1–Q4 未评，保留 PENDING_HUMAN；Direct 确有输出，不标“无输出”。

兼容性失败得到确认：原脚手架允许归档普通文件，新候选 GUI 对公开 task.json 返回“Invalid file type. Please upload a video file.”。已有 original-note.txt 保存着，不等于保留了原通用归档工作流。

CGNK 的 GUI 上传、重开归档和数据保留通过，但候选逐文件与初始快照相同，新增 ASR/检索/裁剪流程缺失。这些归档检查只证明原脚手架可用，不能计为 CGNK 新增能力。领域记录为 NO_CANDIDATE_DOMAIN_OUTPUT，并单列 PENDING_HUMAN。

自动 GUI 操作不是真人可用性评审。Direct 共 50 次 GUI 动作，含失败动作及一次操作复核，未超过 60 次/20 分钟限制。保留所有截图和原始轨迹。

## 测试专项与评分

Direct 实际做了临时 HTTP/字符串检查，不能说“完全没测试”；但未交付可复现测试套件或有效复用套件。独立有效变体只在一次性验收副本中禁止搜索结果生成，保留查询输入回显与素材列表，未修改原候选。

独立触发证据：原版搜索结果数为 1，变体为 0。原模型的**同一条原始检查命令**在两者上均输出 `True / True`、exit 0。它检测了查询文本和素材文件名，不能拒绝实际搜索结果缺失。记录在 `test-effect-v1/`，这是测试效果的负面证据，不是宿主代写测试后给模型加分。

| 路线 | 已确认分 | 已评权重 | 待评权重 | 完整总分可能区间 |
|---|---:|---:|---:|---:|
| Direct | 45.0 | 80.0 | 20.0 | 45.0–65.0 |
| CGNK | 0.0 | 10.0 | 90.0 | 0.0–90.0 |

不得按已评部分归一化，也不得把未评项当 0。两路线评估完整度不同，不据此计算完整工程分差。Direct 的 D1–D4 为 1/1/0/1，平均 0.75，明确不满足 D≥3；F2 有已确认 MUST 失败。CGNK 核心流程及有效测试缺失。已有必要条件失败，因此两者主状态均为 NOT_DELIVERABLE，即使另有未评项。

Direct G1 通过；G2 部分完成、G3 失败、G4 未评、G5 未验证、G6 失败。没有用成功播放抵消音频/测试/兼容性缺口。完整 24 子项、11 个 MUST、G1–G6、证据哈希与根因在 `closeout-v1/*-acceptance.json`。

## 宿主、验收器错误与历史

宿主只修改上述通用框架、机械执行模型动作、在提交后独立验收和归档。未修改候选业务代码/测试/数据库、未进行强模型救援、未回传私有失败信息。两条开发审计哈希链验证通过，关键开发审计缺口 0，语义辅助 0，协议污染 0。

验收器问题同样保留：媒体比较第一次用了错误 CLI 参数，保留原错误并按正确参数复核；边界测试批次遇到浏览器顶层 `let` 名称重复，保留三次错误动作，并在原候选上复核该批一次；另有未发出业务动作的字符串构造错误、报告 UTF-8 读取错误。详见 `evaluator-events.json`。它们不是产品失败，也没有通过修改候选修复。音频 checker 结果仍有未解疑点，不当作已确认产品根因。

旧 ITER-076 正式矩阵仍为 32 计划格、32 启动、32 结束、32 NOT_DELIVERABLE、0 NOT_RUN。旧 v7 首 4 次与 v8 后 28 次分别保留；本轮新增正式运行 0，不增加 CREATE/重复/SELF_EVOLVE。新旧已知题变体不能称为独立项目。两条路线均无达标交付，“每个达标交付成本”不可定义。

本次单对中 Direct 多花 17.83332 元，取得了更多可操作功能；CGNK 的一次契约自纠正没有转化为产品交付。它比较的是不同编排与固定决策限制下的完整系统；不能由一次结果宣称普遍架构优劣，也不能将 Direct 的进展完全归因于本轮生命周期修改。

Corpus 已沿用 `F:/CGKN-ITER-060/project-corpus`：离线记录 `entry-iter089-offline-lifecycle-feedback`，付费对及两条候选分别追加 `entry-iter089-real-dev-pair`、`entry-iter089-real-dev-direct`、`entry-iter089-real-dev-cgnk`。配对汇总不是第三次尝试；对应清单、对象哈希和当前记录索引单独校验，未另建历史库。

## 复核与后续边界

已执行命令如下，不应再次执行购买额外重试：

```powershell
python -m experiments.product_dev_089.run_pair --packet F:\CGKN-ITER-089\dev-packet --authorization F:\CGKN-ITER-089\authorization.json --execute
```

零费用配置复核入口：

```powershell
python -m experiments.product_dev_089.run_pair --packet F:\CGKN-ITER-089\dev-packet
```

如需重看冻结候选，使用尚不存在的验收目录；以下命令不会调用 Provider：

```powershell
python experiments/product_eval_076_v8/inspect_candidate.py --root F:\CGKN-ITER-089\recheck-direct-v1 setup --snapshot F:\CGKN-ITER-089\dev-pair-v1\dev089-video-direct\frozen\candidate.zip --public F:\CGKN-ITER-089\dev-packet\public --argv '["python","/workspace/app.py"]'
python experiments/product_eval_076_v8/inspection_action.py --root F:\CGKN-ITER-089\recheck-direct-v1 --url http://127.0.0.1:5000 --screenshot home.png
python experiments/product_eval_076_v8/inspect_candidate.py --root F:\CGKN-ITER-089\recheck-direct-v1 close
```

本轮批准的一对已完成，不因仍有余额追加运行。下一步最小有价值验证是离线核查音频 oracle 的对齐敏感性，以及 CGNK 成功工具结果进入 Agent 检查点的现有行为；不向原运行泄露私有反馈，不补候选业务实现。任何新付费对需新的明确授权和相应版本。
