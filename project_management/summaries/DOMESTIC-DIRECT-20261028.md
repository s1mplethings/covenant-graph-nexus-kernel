# ITER-NEXT：国内直连隔离增量

范围：在上一轮可靠性底座上，将国内 Provider 与可选 Grok 代理解耦。复用 NetworkClients、熔断、预算、Provider Adapter、GatewayServer、CompletionClient、DAG 和任务状态。没有重复实现 Watchdog、Mihomo fallback 或新的规划/调度系统。

接受条件：两家独立池、环境代理隔离、实际出口证据、专用代理断开后的非生成连通性、按任务能力准入的安全替代、10 分钟分 Provider 稳定性和相关回归。网络、认证、生成、CGKN 任务及 Grok 分开判定。

已确认：普通无应用代理连接仍通过 TUN fake-IP。HTTP 库默认在 connect 后设置 socket_options，首个进程隔离实验因此失败；已经保留并排除该轮证据。现使用 SYN 前接口绑定及同接口 DNS，拒绝 fake-IP，不修改系统网络。实际关闭专用代理和 Watchdog 后，国内探针及 Gateway 仍工作，已恢复原代理/任务，日常 VPN PID 不变。

真实结果：600.001 秒内 Qwen 60/60、DeepSeek 60/60 到达 HTTP；各自 100%。现有凭据的 /models 均 200，配置模型在列表中。模型生成 0 次。默认 Docker bridge 仍经过 fake-IP，不计独立直连。物理抓包权限不足、没有关闭日常 VPN 上游，严格的完全无系统级 TUN 截获仍 NOT_VERIFIED。

状态：DOMESTIC_NETWORK_STATUS=NOT_VERIFIED（socket/接口层和连通性通过，强隔离证据不完整）；DOMESTIC_PROVIDER_STATUS=PASS（非生成认证范围）；DOMESTIC_CGNK_STATUS=BLOCKED（真实生成缺本轮授权/预算）；GROK_NETWORK_STATUS=BLOCKED（DISABLED，可选）；FULL_CGNK_STATUS=BLOCKED。Grok 不决定国内模式结果。

回归：109 passed（早一版综合）；新增模式/任务边界后 100 passed、40 passed；最后发布专项 88 passed / 5 subtests。集合重叠，不相加。方向门禁仍由两个已有 obsolete benchmark 目录阻塞。上一轮 1022 个证据文件哈希均未改变。

复盘与改进：配置 DIRECT 和 socket 选项读回都不足以证明连接前选路；下次应先用测试进程拒绝未绑定接口的 connect，再做真实稳定性实验。按任务能力准入的替代默认关闭，未知提交不可重发。未把合成任务接管测试或非生成 HTTP 验证升级为真实模型任务 PASS。

运行与回滚：[国内模式说明](../../docs/domestic_network_operations.md)。完整命令、决策、失败历史及证据：[验收报告](../../artifacts/domestic-direct-20261028/report.md)。未修改已关闭主迭代或发布权威，未进行 Git staging/commit/push。
