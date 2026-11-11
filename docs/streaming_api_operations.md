# Streaming API：调用、恢复与回滚

截至 2026-10-29，正式预算化流式路径已取得 Qwen 156.45 秒完整生成、DeepSeek 55.87 秒完整生成证据。两者均有终态、usage 和持久化结果；DeepSeek 约100秒时长与完整三阶段业务交接未宣称通过。详见 artifacts/api-duration100-20261029/report.md。

## 正式调用路径

已安装 MCP → `generation_command` → `scripts/run_codex_conversation_generation.py` → 原正式控制器 → `canonical_gateway_adapter` → `GatewayCompletionClient`（预算、UNKNOWN、缓存）→ Windows Gateway → 原 `NetworkClients` 的每 Provider 连接池和 GUID 绑定 → `StreamingBoundAdapter`。

上游采用 Chat Completions SSE；下游采用 `cgkn.model-stream.v1` SSE。下游包含 started、按请求关联的进展计数、completed 或 error。控制器仍接收经过完整性校验的最终业务结果；接收器在等待期间持续读取事件，并非等完整 JSON 才开始读。进展不包含正文或思考文本。

保存的 `config/domestic_application.json` 为固定默认配置；文件缺失或不匹配即报错，不再隐式选择 Legacy。显式 Legacy profile 只用于隔离兼容环境，不能与 domestic 环境选择混用。`config/domestic_application.json`，Agent=Qwen、Worker=DeepSeek。没有改系统代理、DNS、路由或已保存网卡 GUID。接口、配置、凭据或会话不符即拒绝，不回退旧 HTTP 客户端。

## 能力与终态

上游正文、思考计数、usage、finish_reason 和 DONE 分开处理。普通文本必须完整结束，模型身份匹配且 usage 完整，才能持久化和放行。Schema 不合格但响应完整时保存已知用量，交由原业务返工判定；断流、无终态、缺 usage 等保持未知，不补零费用。

当前正式 Provider Adapter 使用 Chat SSE；Responses 解析器有离线测试，但不宣称供应商 Responses 出站已接入。现有正式文本 Adapter 没有受控工具调用执行合同；请求工具调用参数或不支持的思考参数明确拒绝，流中工具片段不作为正文成功。不能据此宣称 Function Calling 已验收。

供应商参考：[Qwen 流式说明](https://help.aliyun.com/zh/model-studio/stream)、[DeepSeek Chat 协议](https://api-docs.deepseek.com/api/create-chat-completion/)。文档能力与当前账号的真实生成验收是不同结论。

## 超时与重复提交

国内正式流式生成不再设置总时长截止。`config/network_routes.json` 每条国内路线的 `first_response=180` 是从实际 Provider 提交起等待首次有效内容的秒数；`progress=120` 是最后一次有效模型内容后的停滞秒数。两者可分别配置，重启 Gateway 后生效。正文或有效 reasoning delta 才续期，心跳、空白、usage 和状态消息不续期。reasoning 只记录计数，不写普通日志或业务正文。

`deadline` / `read` 仍用于非流式 GET 和明确隔离的 Legacy 操作，不再约束国内生成。connect/write/pool、Provider 排队、下游连接/提交前准备和每次写入保留独立有限期限。Windows 的上游 TLS 及下游读取每 25ms 检查停滞与取消；不会重试已失效的缓冲读取。有效输出可持续超过 90 秒或数小时，但 token、SSE 字节/事件、正文大小、费用和磁盘边界仍生效。

原 MCP 生成继续返回正式后台 job ID，使用 `cgkn_status` 查询；宿主工具返回期限不终止后台生成。临时 `cgkn_accept_streaming_case` 付费启动工具已撤下；历史验收只用 `cgkn_streaming_acceptance_status(case_id)` 读取状态。历轮测试脚本已迁至 experiments/api_acceptance/archive_20261029，工作区历史计划被禁止再次执行。既有授权、结果及已消费记录不重置。国内 CLI 与正式控制器不再累计生成总时间，测试、构建等确定性工具仍各自有界。

`NO_INITIAL_MEANINGFUL_PROGRESS`、`NO_MEANINGFUL_PROGRESS`、`USER_CANCELLED`、`GATEWAY_SHUTDOWN` 与真实网络错误分开记录。Provider 已提交但终态未知时仍保留 UNKNOWN。请勿因新版本取消总时限而重发旧 UNKNOWN 请求。

Gateway、SDK 和正式发送器不自行重发 POST。超时是传输控制参数，不参与请求内容身份；改变超时不能绕过 UNKNOWN。迁移前非流式请求身份也参与预算保护。job/attempt/run 通过账本和请求头关联，不改变去重内容身份。

## 恢复

### ITER-119：在生成期间查询进展

后台生成返回 job_id 后，调用 `cgkn_get_progress(project_root=<项目目录>, job_id=<原 job_id>)`；可选 `attempt_id` 过滤同一任务的尝试。建议每 1–3 秒查询一次。该工具直接读取项目 `.cgkn/agent-kit/api-progress` 下的原子快照，不调用生成入口、不启动 worker、不改预算、不重试。没有 Clock 的历史任务返回 `NOT_OBSERVED`，不代表失败或允许重发；历史结果仍按原恢复入口检查。

每个 call_id 独立记录 Provider、请求身份、job/attempt、模型、阶段、总耗时、首次/最后有效输出时间、有效事件数、正文累计字节、reasoning 字符数、心跳数、HTTP 状态和终态。只保存计数，不保存正文、思考内容或凭据。快照约每秒更新，关键状态变化唤醒异步写入；SSE 回调不等待磁盘。事件数与 watchdog 共用同一解析结果，明确的重复 SSE event ID 不重复计数，相同正文的不同事件仍分别计数。

`GENERATING` 表示已收到有效输出；超过一秒没有新输出显示 `IDLE_WAITING`，并不立即判失败。首次有效输出仍限 180 秒，随后有效输出间隔限 120 秒。超过相应限制显示 `STALLED`；它是进展状态，费用账本仍可能是 UNKNOWN，绝不代表可重发。worker 退出、快照超过五秒未更新或 Gateway 换会话时返回诊断 `UNKNOWN`；完成状态不会随时间变成停滞。

工具已加入仓库与本机安装目录，并使用新启动的已安装 MCP 进程完成查询测试。当前聊天若仍缓存旧工具列表，需要重新连接插件或重启 Codex 才能看到新工具。传入 MCP `_meta.progressToken` 的查询会收到一次 `notifications/progress` 快照通知；这不是后台订阅，也未证明 Codex UI 自动持续显示。持续观察使用重复只读查询。

### Qwen Flash 配置与 ITER-119 真实验收

本轮已接通 role 的具体 `model_id` 到正式发送器，并为精确的 `qwen3.8-flash` 使用 `enable_thinking=false`、`max_completion_tokens` 和原 JSON Schema/SSE 合同。认证模型列表已包含该名称；离线 TLS 测试验证的是发送参数和 PlanningProposal 解析，不能证明账号的真实模型能力或规划质量。

初轮审核目录提供 `flash-routing-candidate.json` 和 `model-routing-rollback.json`，当时尚未激活。随后用户明确授权两家各一次、合计 0.50 元的真实验收；证据保存在 `artifacts/api-progress-clock-20261029/live-authorized-01/`。两家均获得正确模型身份、SSE 完整终态及 usage，Qwen 通过原 PlanningProposal Schema 和规划合同。因此默认 agent.model_id 已激活为 `qwen3.8-flash`，DeepSeek 保持 `deepseek-flash`。本轮只完成短任务能力验证，不代表与 Max 规划质量等价。

真实上游 POST 区间没有重叠：DeepSeek 完成后约 0.14 秒才开始 Qwen POST。结论是 API 生成均通过、`LIVE_PARALLEL_NOT_VERIFIED`，没有补发第三次。原 DAG 同时调度、独立连接池和本地进展时钟不等于供应商处理区间重叠。新受限 `cgkn_verify_api_pair` 入口仅接受冻结的本次授权，并有永久已尝试标记；不能拿它重试或开展新的付费任务。

共享预算账本上限 0.50 元，发送前保守合计预留 0.1024 元；完整 usage 按预算单价计 0.010128 元，按核实的供应商价格上限估算约 0.0020192 元（不等于账户账单）。所有历史 UNKNOWN 及原账本保持不变。回滚默认模型使用本次 `live-authorized-01/model-routing-before.json`，不得删除尝试标记或更换身份重放。

先用 `cgkn_doctor` 查看本地诊断，区分 Gateway ALIVE 和 Provider 健康。Gateway 服务恢复仍使用原实例锁、进程创建身份和会话匹配；恢复服务不恢复执行未知任务。

完整响应通过不可覆盖的原子文件发布。只读 `recover_cached` 不调用 `complete()`，缓存缺失或不完整时不会发送 POST。旧会话结果不接受为当前流的终态。未知调用必须保留账目，在原合同和准入机制下处理可回收结果；不得换请求身份重发。

## 应用级回滚

审核包包含变更前 baseline 与逐文件补丁。先停止应用的 worker 和 Gateway，核对回滚期间没有新修改；按补丁逐项逆向恢复本轮源代码，并重启应用。不要批量覆盖整个仓库，不删除任务、预算、缓存或 session 来“解锁”。保存的 domestic 配置保持不变，不能把 legacy 模式当作国内路线故障的回退。旧源码与新 SSE 客户端不能混用，需作为同一版本一起回滚。

模型功能、长请求时长、完整业务任务和物理无 TUN 各自独立判定；真实流式成功不证明 Windows 完全绕过 TUN。Legacy 文件仍有兼容调用引用，未删除全部历史 Provider 架构；默认国内路径不能选择它们。
