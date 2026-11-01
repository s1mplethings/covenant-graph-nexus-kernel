# 国内模式最终收口（非计费部分）

本轮以最小真实 CGKN 任务验收为首要目标，复用原国内网络及代理恢复底座。用户明确要求付费前取得金额授权，因此当前生成调用 0，真实生成与任务保持 BLOCKED；没有推定旧授权。

已准备 v3：Qwen 规划、DeepSeek Worker、同 run/goal/账本重开后 Qwen 收尾，最多三次、两次 planning/一次 generation；预算保守上界 1.13472 元，已请求用户明确最多 2 元/3 次授权。19 项执行依赖、Provider 公共身份、fixture、独立 oracle 已封存。v1/v2 保留，源码变化后被拒绝。

独立验证端发现并推动修复规划未知提交的防重缺口：canonical budget 持久化 INTERRUPTED_UNKNOWN，usage 结算不清除未知标记；成功响应通过原身份绑定缓存重建，避免提交成功但任务决策未落盘时重发。真实本地 HTTP 跨进程与迟到 usage 两种顺序均通过。没有泛称普遍 exactly-once。

网卡按稳定 GUID 识别，启动解析当前索引/源地址；运行中发现变化安全停止、要求明确 Gateway 重启，不回退 VPN/默认接口。当前认证复测两家均200。实际 Gateway 正常停启、令牌会话轮换，338 个任务状态文件哈希未变。断开/DHCP/索引变化用隔离快照测试；没有真实改动日常网络。

独立端封存135用例语义 oracle，拒绝可骗过单项pytest的常量5。模型候选进入pytest前另有纯函数AST安全检查，该检查不判断算术正确性。v3 准备独立结论 PASS_WITH_LIMITS，真实结果仍 BLOCKED。

回归：145 passed / 5 subtests；已有网络与契约119 passed；最新验收专用10 passed，集合重叠不相加。初次组合回归的8项失败为测试进程环境/cache污染，已隔离并保留失败日志。方向门禁仍由两个既有 obsolete benchmark 目录阻塞。

管理员物理取证授权未收到，Windows 包级出站隔离仍 NOT_VERIFIED。自动审批拒绝保存具体抓包命令计划（blocked by policy），没有执行抓包命令或绕过拒绝。Docker 默认TUN与Grok可选禁用保持原独立限制。

复盘改进：先验证跨进程未知提交/成功缓存窗口，再付费；独立语义判定与候选执行安全分开；最小验收第二次Agent决策只能结束，不能悄悄增加工作。没有发布远端或改动其他未提交工作。

完整证据：[report.md](../../artifacts/domestic-final-20261028/report.md)。运行与授权说明：[domestic_final_acceptance.md](../../docs/domestic_final_acceptance.md)。
