# ITER-116 real-dev-01：连通恢复后的真实启动

2026-10-29（北京时间），当前插件 cgkn_probe_provider 实际返回 connected。插件两家 /models 检查和独立运行 Gateway 预检均通过；旧 DNS 阻塞已解除，不沿用旧失败结论。网络变更后相关回归 36 passed。

已通过原 AgentComposer → AgentProjectLoop → GatewayCompletionClient 启动 real-dev-01。已授权 accounting_only 生效，没有因金额、请求次数或 token 上限停止。请求 Qwen/qwen3.8-max 主规划；qwen-plus 与 deepseek-flash 只完成配置/清单核验，没有实际 Worker 调用。

原始结果：GatewayCompletionError: provider_outcome_unknown: Provider submission outcome unknown; do not retry。账本 http_status=502，duration_seconds=63.719867，response_received_at=null，status=INTERRUPTED_UNKNOWN，retry_count=0。不能仅凭耗时推断为 read timeout；Gateway serve 未启用通用 log 回调，route-diagnostics 只覆盖诊断，当前无法恢复该 POST 的精确出站故障或上游 ID。此项为关键审计缺口，不能宣称完整真实模型见证。

实际启动1次、主规划请求1次、返回可用决策0次、Worker0次。开发会话已终止、专属候选容器由 finally 关闭；冻结目录为空。独立业务验收 BLOCKED_NO_BUSINESS_CANDIDATE，未运行；不是产品通过，也不是已有证据确认业务实现错误。没有宿主业务代码修复。

费用：旧全链保守估计382.65018元；当前账本保守累计383.17886元，增加预留口径0.52868元。此笔实际 token/费用未知，不能将预留当实际账单或记零。全链1336次请求，unknown_calls=1。原未知记录未清除、未重发。

证据目录：F:/CGKN-ITER-116/real-dev-01，包括 source-manifest.json、preflight.json、role-configs.json、state/provider原始请求与error、execution-error.json、ledger-after.json、continuation-summary.json。预检成功记录另存 real-preflight-03。所有旧失败与旧报告保留。

原 PowerShell恢复脚本遭系统 ExecutionPolicy 拒绝，未更改系统策略；使用脚本内原 Python模块命令启动。不能再次用新目录掩盖同一未知请求重发。

下一恢复条件：对 ledger call_id=c4e3da17674643f98f73849fc6b1ea1b、request_identity=sha256:60a4ed33529c2e6b7440dfe89d80ecae8a91edc6afefc8d27f7c80010c748459 的请求取得可核对结果，或按明确的未知请求处置决定保留未知费用并授权新的独立尝试。当前没有供应商查询凭据/返回request_id支持自动核对；不能编造一条可完成对账的CLI。下一真实尝试前还应补齐 Gateway 生成日志与有限超时的可审计证据。金额授权无需重申。
