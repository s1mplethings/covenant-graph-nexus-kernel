> 当前启动方式已更新：新启动的CGKN插件自动读取保存的国内应用配置，无需手工网络变量或切换模型配置。先重启一次旧插件进程；当前操作以 [默认国内启动说明](default_domestic_startup.md) 为准。以下保留前轮配置和验收背景。

# 国内 API 路线验收（2026-10-28）

当前默认启动不保证国内 Gateway：本轮当前进程未设置 `CGKN_NETWORK_MODE`，工厂返回 `OpenAICompatibleClient`，旧凭据解析选择 `QWEN_BASE_URL(User)`；同旧传输的非生成 GET /models 观测到源 198.18.0.1、peer 198.18.0.181:443。不能把这种启动宣布为独立国内路线。

明确选择国内模式：先按 `docs/domestic_network_operations.md` 启动 Windows Gateway；只在运行任务的进程设置 `$env:CGKN_NETWORK_MODE='domestic'`，并选择 `config/provider_profiles/domestic_model_routing.json`。工厂此时选 `GatewayCompletionClient`，session 缺失失败关闭。Qwen / DeepSeek 各自 loopback Gateway -> NetworkClients 独立直连池 -> GUID 31fde520-1fc1-4a43-a5a9-8ca730ff5821 对应 WLAN，当前 ifIndex14/source192.168.1.100；不使用17890/17891。不是系统全局设置。

已有实例时不要重复启动。Gateway 正常停止后，可临时在原 serve 命令加 `--route-diagnostics`。该模式通过原 loopback HTTP server、同一本地认证及同一出站池提供 `GET /v1/network/models/qwen` 和 `/deepseek`。仅固定官方 /models，不收任意 URL，不调用生成接口。使用 `GatewayCompletionClient` 的同一 `_open_loopback` helper 请求；`complete()`、生成 Adapter.invoke、正式任务输入输出解析未执行。诊断模式所有 POST 拒绝403，防止并发生成混入记录。完成后正常停止，并不加该参数重新启动；本轮已恢复正常 serve。

同一次诊断返回 request_id、入口端口、Gateway PID、route_id、脱敏网络阶段及 Windows `GetExtendedTcpTable` OWNER_PID 表中的匹配连接，不返回凭据或上游正文。TCP 查询只输出匹配 PID/本地端口记录；查询失败降级 NOT_CAPTURED，不应改变 API 结果。它是连接归属证据，不是物理抓包或无 TUN 保证。Pktmon 本轮不执行。

接口查找保留原8秒和所有身份/Up/物理/单IPv4校验，改为 CIM 按 GUID 服务端过滤，避免枚举全部隐藏虚拟网卡触及超时；无默认路线回退。仍可能因系统查询超过8秒而安全停止。

证据见 `artifacts/route-acceptance-20261028/report.md`。真实六次 GET 通过；A/B只改变调用方进程代理变量，没有切换日常 VPN 组，也没有改变 Gateway 的上游环境，不能据此宣布真实日常组切换通过。进程内 TCP 故障注入两家各一次失败、不回退，不能等同于切断物理出口。

生产 Provider 本轮实证来自 Windows 原生进程；docker ps没有运行容器。旧 Docker probe 是临时容器证据，默认 bridge TUN 限制仍存在，未证明任何 Docker 任务正式请求路径。Grok 保持可选禁用，专用代理路线当前未执行验收。

未获付费授权，生成和真实任务保持 BLOCKED。旧 sealed v3 因接口查询源码小修已需重新 prepare/独立复核，不能直接复用旧哈希授权。三次调用及人民币两元上限仍单独等待明确授权。

回滚按本轮 baseline 和 changes.patch逐文件审核；不要覆盖其他未提交修改，不清理任务/凭据/Watchdog，不推送。若回滚诊断模块，先停止诊断模式 Gateway。原正常 serve 行为仍是默认模式。
