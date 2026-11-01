# ITER-076 接续：隔离通路、真实 DEV 与未完成正式评测

本报告追加到原预检报告之后；原失败记录不变。正式矩阵仍未启动。最终计数见 `F:\CGKN-ITER-076\closeout-v1\summary.json`；本报告的通路通过不能用作产品达标证据。

实际完成 8/8 次 DEV 开发尝试、49 次 Provider 请求，正式启动/完成均 0/32。当前停止新增 DEV 的硬门槛是次数上限，不是人民币预算耗尽。完整产品评测没有完成；不能把仍未完成的题包/初始快照/验收器工作伪装成环境错误。

版本：`0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`，分支 `codex/provider-gateway-integration-20261017`。本轮新增评测基础设施，未修改 kernel 或候选业务代码，未暂存、提交、推送。保留 `.api_lab_worktree/` 和 `.service_scratch/`。历史 source/evidence closure 与当前分支的关系沿用原报告，未冒充当前 HEAD 验证。

原阻塞与最小修复

原 `route-canary.json` 中的合成禁区文件是 `F:\CGKN-ITER-076\preflight-20261027\route-canary-private.txt`。它属于评测方私有探针，不是解释器或冻结依赖。原 `cgkn.executors.local.CommandExecutor` 用宿主 Python 的 `pathlib.read_text` 成功读出 `SYNTHETIC-NOT-A-SECRET`；cwd 为 `.`。问题是宿主权限下的 subprocess 没有访问边界，而非所有项目外文件都应禁止。这不证明真实秘密泄漏，也不是正式运行污染。

旧独立 docker 探针绕过路线实例、工具注册、DAG 与 LLMExecutor，因此仅独立检查通过不足以放行。本轮在 `experiments/product_eval_076` 接入以下通路：

- Direct：`runner.run_route → create_route → DirectRoute.run → ContainerBoundary.execute → docker exec → 容器内 Python/subprocess`。
- CGNK：同一 runner → `CGNKRoute → AgentComposer/AgentProjectLoop → CapabilityTree/ExecutionDAG → DAGRunner/ExecutorRegistry → IsolatedExecutor → ContainerBoundary`。`LLMExecutor` 仍使用原提案校验，其文件 action handler 替换为 `ContainerFileActions`，也经过同一容器。
- 宿主 Docker 控制面不注册为模型工具。没有注册宿主 CommandExecutor、宿主文件读写、个人浏览器、MCP、连接器或 Docker socket。没有增加第二规划器或语义修复器。
- Direct 是公平通用工具循环；CGNK 使用当前 canonical loop，包含其四次 Agent decision 上限与 Agent/Worker 不同模型约束。这是完整系统差异，不能将差值全部归因架构。

仅开放 command、read_file、list_files、write_file、patch_file、browser。解释器、HTTP、SQLite、应用及 worker 均在本运行容器内。Chromium 有独立临时 profile；文件上传/下载与截图不能越过同一文件系统边界。容器网络为 none，允许容器内 localhost 服务；外网与宿主管理网络不开放。依赖预装且两路线一致。未提供在线文档/任意依赖下载，结论仅适用于此冻结依赖环境；不能声称已验证外部发布集成。

镜像锁定 `sha256:1059097764b634a5b1e2ed4bf035700d6ce47dfd206044c1b9bf63300523ee20`。非 root、只读根、无 capabilities、no-new-privileges、无 Docker socket、无共享 .git；仅 `/input` 只读与 `/workspace` 可写，加独立 `/tmp`。审计、预算、Corpus、私有答案和兄弟目录均不挂载。模型参数通过 stdin JSON 传入，不插值宿主 shell，不可选择挂载/镜像/无沙箱后端。

新旧证据分别保存

| 记录 | 结果与证据边界 |
|---|---|
| `preflight-20261027` | 原宿主执行器越界 FAIL，保留 |
| `conformance-v2-01` | 通用探针 HTML/Python 引号错误，EVALUATOR_INVALID；保留失败审计，未计模型尝试 |
| `conformance-v2-02` | 两路线通用通路通过，非产品成绩 |
| `conformance-v3-01` | 当前镜像，两路线真实工具注册通路通过；Direct 11、CGNK 12 个工具动作，含 CGNK worker 文件适配 |
| `media-check-v3-01` | 两路线真实 ffmpeg/离线 ASR/导出解码成功；固定动作回放，不是模型交付 |
| `transport-conformance-v4` | reasoning=none 参数透传与原始响应保留检查；无付费调用 |

`conformance-v3-01/conformance.json` 绑定 runner、registry 实现、执行器、浏览器和 Dockerfile 哈希；每个 audit.jsonl 还记录 policy hash、Docker inspect 实际容器 ID/镜像/挂载、原始工具动作、stdout/stderr blob 哈希和退出状态。只读公共输入实际可读、候选文件实际可改、子进程实际执行、Flask 按钮驱动 SQLite 写入且连接重开后可读。截图已查看。禁区/兄弟合成 canary 不可读；只读输入、策略/预算/审计位置不可写；路径和符号链接探针不越界；网络访问失败。不存在全命令失败却判隔离通过的情况。

后端缺失时 runner 在调用 Provider 前失败；超时终止整个容器及延迟写入子进程；关闭后动作拒绝且宿主无 fallback-marker；逐次检查容器消失。没有宿主 fallback。该证据覆盖本轮开放入口，不是通用容器逃逸安全认证。

v3 conformance 的旧字段 `asr=NOT_YET_PROVISIONED` 保留原样；ASR 的后续实际验证在独立 media-check，不覆盖旧记录。媒体是新的公开美国联邦政府历史视频前 75 秒，Wikimedia 来源、许可说明和转换命令位于 `media-preparation-v1/capture.json`，输入 SHA256 `a82da28d24fe6ff6fddd8bcb7e8023a6fcab0b275c260b8d4cbf94e5b2aa902c`。没有使用 ACFV Final 材料。Whisper tiny.en 权重另有哈希；转录没有交给开发模型作为答案。

真实 DEV 与比较边界

真实 API 通过已有 API Lab 凭证解析与 ProviderComparisonService；凭证不进入容器或日志。请求/响应/上游 model 字段保存在各 DEV 的 provider 目录。上游返回 `qwen3.8-max` 与 `deepseek-flash`；这些是服务端返回标识，不是可验证的底层权重快照。Direct 用 Qwen，CGNK Agent 用 Qwen、worker 用 DeepSeek；不能做同模型架构因果结论。

前期读取超时从 60 秒校准为 300 秒。最后一对宣传 DEV 修复通用适配遗漏：原 API Lab 没有透传 `reasoning_effort=none`，现按两服务 API 参数发送关闭 thinking，原始发出 body 留档。未改模型文本、业务提示或候选代码。修改前结果全部保留，最后一对的任务、配置及变更预登记于 `dev-calibration-v4.json`。DEV 本来用于校准，不能把各配置样本合为冻结正式对比。

DEV 公共题分别是新合成 Meadow Club 草稿/批准/持久化应用，以及新真实视频的导入/ASR/检索/预览/裁剪导出应用。起点候选代码为空，宿主只预装通用运行依赖。没有借宿主通用探针实现候选业务；通用探针不进入 DEV 工作区。

已确认原始错误包括：

```text
PROVIDER_TRANSPORT_FAILED: The read operation timed out
ValueError: persisted run state does not match DAG
ValueError: request identity, component_ref, and executor_ref are required
```

后两者出现在真实 CGNK 路线，未由宿主补树、补 executor_ref 或修复运行状态。视频 Direct 自主产生真实 ASR 音频/JSON/log，但未形成应用。其余早期候选为空或只有 pytest 缓存。原始开发阶段的失败测试可用于后续测试效果分析，不能用测试个数直接给 D 分。

每份已结束候选通过只读检查容器冻结为 zip/manifest，宿主不跟随候选符号链接取证。开发容器终止后才进行独立验收，不把私有结果回流。新 `dev-acceptance-policy-v1.json` 只约束 DEV 草稿应用验收，不能充当正式五档 oracle。

| DEV run_id | 请求 | 保守费用上界（元） | 实际终止/产物 |
|---|---:|---:|---|
| dev-promo-direct-01 | 6 | 0.95518 | Provider 超时，无应用 |
| dev-promo-cgnk-01 | 1 | 0.67476 | Provider 超时，无应用 |
| dev-promo-direct-02 | 5 | 0.91696 | Provider 超时，无应用 |
| dev-promo-cgnk-02 | 3 | 1.34482 | Provider 超时，只有测试缓存 |
| dev-video-direct-01 | 11 | 2.83868 | Provider 超时，真实 ASR 音频/转录/log，无 GUI 应用 |
| dev-video-cgnk-01 | 3 | 1.42662 | persisted run state does not match DAG，无应用 |
| dev-promo-cgnk-03 | 1 | 0.04144 | request identity, component_ref, and executor_ref are required，无应用 |
| dev-promo-direct-03 | 19 | 5.57854 | 前台运行服务器触发 120 秒工具超时，留下可启动草稿应用 |

最后一项原 runner 状态写为 BLOCKED_ENV，但底层记录是 TIMEOUT_CONTAINER_TERMINATED，不能据此认定评测方服务不可用。模型选择前台启动持续运行服务，触发预设整容器终止策略；模型工具说明没有明确解释这一生命周期后果，是正式冻结前需要补全的通用工具协议说明缺口，不作正式产品失败归因。没有让模型收到该事后诊断。

该候选 zip SHA256 为 `7b84e7afcaede199b40e173fa245c08df23b5318214583e1525107132299de24`。在独立验收副本上按 README 启动、浏览器操作创建/批准/修改、应用重启回读及刷新后内容/状态回读均有原始证据。没有后台代建草稿或修数据。候选的 12 项自写测试在同一冻结版本复跑全部通过；将“正文变更仍保留旧批准”的有效变体置于另一验收副本后，候选自写测试拒绝它（1 failed、11 passed，明确业务断言失败）。这提供部分 D2/D3 证据，不代表 D 平均达到 3。候选测试只以跨请求方式模拟持久化，未独立证明进程重启；重启证据来自宿主验收，不能计为候选测试能力。

独立浏览器与候选容器共享本运行网络命名空间，但不共享私有文件系统或进程命名空间。重启应用后浏览器留在旧网络命名空间，出现一次 ERR_CONNECTION_REFUSED；按预设一次操作恢复额度重启验收浏览器，重新回读成功。两次动作/DOM/错误轨迹保留；第一次失败截图因复用路径被第二次截图覆盖，明确记录局部 AUDIT_GAP，不声称完整视觉轨迹。未泄漏私有反馈，未修改原候选代码，未把该 DEV 记为 AUTONOMOUS_DELIVERABLE。验收结果 `dev-acceptance-v1/acceptance.json` 为 PARTIAL，领域质量未评、真人审查 PENDING_HUMAN。

API 连续总账为 `global-provider-budget.json`：49 次真实请求，已知输入 295,822 token、已知输出 62,808 token，5 个超时调用没有实际用量。账本计量 token 481,314 含这些调用的保守预留，不能冒称全部为实际 token。按冻结的保守费率/预留计人民币 **13.777 元**，不是服务商账单；未查实际账单。100 元授权按此口径剩 **86.223 元**，其中至少 20 元仍留验收，开发可用上界剩 66.223 元。没有购买/充值/提高授权。每 DEV 额外保守费用保护上限 10 元，对两路线一致。逐次 Provider 时间见 closeout 表，不把并行时间相加冒充墙钟时间；宿主会话没有独立货币计价。

回归与归档

原 skipped 为 `tests/test_provider_api_budget.py` 的预算账本用例，因 live_provider 标记默认跳过，代码本身使用模拟预算，不是必要隔离通路被跳过。加 `--run-profile-marked` 后本次相关四文件实际 **34 passed、0 skipped，19.60 秒**，原始命令和结果在 `related-regression-v3.json`。没有运行全量回归；没有将 34 个检查写入产品分数。

product_direction_gate 在排除用户 ignored 目录的当前 tracked source 加实验 Python 导出上通过，原始结果 `direction-gate-v2.json`。仓库根运行曾因遍历 ignored 目录长时间不返回而终止，仅对自己的进程操作；不将中断那次称为 PASS。

Corpus 仍是 `F:\CGKN-ITER-060\project-corpus`。当前分支缺少该历史组件，使用已核实哈希的历史原始 contracts/store 写入；未建第二历史库。新条目均关联 `entry-iter076-preflight-20261027`。只校验本轮条目的对象、manifest 和 catalog 索引，不扫描完整私有 Corpus。首次追加归档遇到 Windows 候选链接 stat 错误，保留 archive-v2-01；改为不在宿主进入候选目录，候选改由容器冻结后，archive-v2-02 成功。最终追加回执见 archive-v3-01。

本次 archive-v3-01 校验 14 条本轮追加/既有记录，包含全部 8 次 DEV、3 轮 conformance、媒体检查、DEV 独立验收与 closeout。closeout manifest 为 `sha256:dd5e51d04e67430f98f2deafb64c69e4390622792a26d5c08e07c4c4e22158f2`，DEV 验收 manifest 为 `sha256:52de42b7faa689ddc3c4ba3001e70b747d72d866bd77e8eb618a115e3e8bead8`。写入回执 PASS 仅表示归档成功，条目内部完整保留 TIMEOUT/PARTIAL 等实际结果。

正式矩阵与剩余工作

| 分表 | 计划格 | 正式启动 | 正式完成 | NOT_RUN |
|---|---:|---:|---:|---:|
| TAKEOVER | 20 | 0 | 0 | 20 |
| CREATE | 4 | 0 | 0 | 4 |
| B0 重复 | 4 | 0 | 0 | 4 |
| SELF_EVOLVE | 4 | 0 | 0 | 4 |

正式自主达标/失败/污染的已执行分母为 0；不报告 0% 成功率，不把 32 格当 32 次失败。24 个子项、领域分、门槛未评，不归一化；待评权重 100，可能区间 0–100 不是评分结果。完整量表已落盘 scoring_contract.json，逐正式题映射仍未完成。

正式尚缺可启动且相同的 TAKEOVER 基础快照、五档真实增量题卡/逐项义务、独立 oracle 与错误变体验证、完整 DEV 校准、正式封板与 admission。runner 对 FORMAL 明确拒绝 `FORMAL_FREEZE_NOT_YET_AVAILABLE`，DEV/FORMAL 拒绝回放 Provider。不能仅修改模式字符串将未冻结题当正式样本。

无真实发布目标授权，发布 G5 未验证；没有真人可用性或领域质量审查。没有关于流量/增长、B0 重复、自身演进或 CGNK 成本收益的证据。没有正式配对质量差与交付成本可计算。

宿主仅修通用适配、准备公共依赖/输入、执行模型动作与独立取证，未改候选业务代码、给语义提示、启用强模型救援或反馈私有诊断；实际 DEV 有原始请求/工具审计支持零语义辅助记录。未运行格保持 null。早期基础设施故障与未知用量保留，不能用零辅助代替协议完整性检查。

恢复与复现（不覆盖旧目录）

```powershell
Set-Location D:\CGKN
python experiments/product_eval_076/conformance.py --output F:\CGKN-ITER-076\conformance-recheck-04 --image sha256:1059097764b634a5b1e2ed4bf035700d6ce47dfd206044c1b9bf63300523ee20
python experiments/product_eval_076/archive_continuation.py --root F:\CGKN-ITER-076 --corpus F:\CGKN-ITER-060\project-corpus --output F:\CGKN-ITER-076\archive-recheck-04
```

以上只复验隔离/归档，不新增付费模型运行。DEV admission 已累计到合同上限 8，不因新会话重置。若还需真实 DEV 校准，必须先获得明确的新增 DEV 次数授权，并保留原 8 次；这不自动增加人民币 100 元总预算，也不修复 CGNK 的已观察运行时错误。不存在一条已经准备好的“运行正式 32 次”命令；声称只需加额度就能完成将不真实。最小下一步是明确是否允许一个额外、成对、预登记的 DEV 校准额度；之后仍须完成上述正式冻结前工作。
