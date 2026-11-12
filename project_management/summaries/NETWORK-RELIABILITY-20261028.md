# API 网络可靠性增量（2026-10-28）

范围：复用现有专用 Mihomo、预算入口、Provider Adapter 与 NetworkClients，修复本地守护、节点切换及不安全重试。采用有界基础设施增量；不改变已关闭主迭代、不增加规划/调度/交付权威，不恢复性能或长时压力产品门禁。

验收目标：独立登录启动与重启限流、六格真实无凭据 HTTPS、隔离故障恢复、未知提交不重发、10 分钟独立观察、既有网络及运行时回归。证据与产品正式交付状态分开。

结果：最终网络组合回归 48 passed；最终进程/节点故障专项 9 passed；既有 Provider/预算/运行时等 117 passed（5 subtests）；Gateway/应用等 37 passed（5 subtests），集合重叠不相加。方向门禁由两个既有 obsolete benchmark 目录阻塞。真实模型请求为零，L4 BLOCKED。

第二轮自主稳定性实验 608.139 秒，96 次无凭据 HTTPS，78 次到达 HTTP，18 次失败；本地 L1 零失败，代理 PID 不变，但一轮三家 API 主备均失败。**网络工程结论 NOT_READY**，不能凭最后六格 401 宣称持续可用。

关键发现：MSIX AppData 映射导致计划任务读取另一个同名配置；已固定真实物理路径，并把状态集中到 D:/CGKN/.cgkn/network-watchdog。系统 DNS 与 Mihomo DNS 对节点返回不同 IP；只有按代理实际 DNS 路径才得到有效 L2 诊断。读取超时后的未知提交不能自动重新生成，费用未知预留保持。

待办：节点/共享出口间歇性 TLS 故障、备用物理接入、原生 fallback 多轮恢复防抖、兼容外部 Gateway 专用传输接入、真实会话重启、长期内存趋势、独立授权后的 L4，以及已有方向门禁目录阻塞。

复盘：真实后台任务与真实进程故障测试发现了 Mock 无法暴露的路径与启动输出差异；初期失败和首轮实验全部保留。后续控制面空连接取证故障已修复，最终源码尚未重新完成完整 10 分钟观察，不计稳定性 PASS。后续改进实验：每次 Windows 自动启动部署必须比较交互进程与计划任务读取配置的物理路径及 SHA256，再进行稳定性观察。未将尚未复验的经验直接提升为组织规范。

运行说明：[docs/api_network_operations.md](../../docs/api_network_operations.md)。本机完整验收与证据：[report.md](../../artifacts/network-reliability-20261028/report.md)，哈希清单位于同目录 evidence-manifest.json。原 F 盘历史证据、私密节点文件和用户其他未提交修改保持独立。
