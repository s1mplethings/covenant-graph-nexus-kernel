> 当前启动方式已更新：新启动的CGKN插件自动读取保存的国内应用配置，无需手工网络变量或切换模型配置。先重启一次旧插件进程；当前操作以 [默认国内启动说明](default_domestic_startup.md) 为准。以下保留前轮配置和验收背景。

> 最终收口更新：国内 profile 现在优先按 `interface_guid` 识别物理网卡，ifIndex/source 是上次观测值；启动时重新解析。运行中若索引、地址、状态或身份变化，先拒绝请求，再由明确的 Gateway 重启重新核验，绝不回退到 VPN/默认路由。真实断开/DHCP 变更未操作，避免影响日常网络；变化路径已用隔离输入测试。完整最小真实任务准备与授权边界见 [最终验收说明](domestic_final_acceptance.md)。

# 国内 Provider 独立网络模式

2026-10-28：默认 `config/network_routes.json` 为 Qwen / DeepSeek 独立直连池，Grok 为独立可选代理池、默认 DISABLED。既有 Mihomo 与 Watchdog 保留；不负责启动或停止国内 Gateway/客户端。

## 当前真实结论

- Windows 默认 `trust_env=false` 仍被 FlClash TUN 截获：解析及连接到 198.18.0.x，源地址 198.18.0.1。
- 新路径在 DNS UDP 和 TCP SYN **之前**设置 Windows `IP_UNICAST_IF=14`，绑定 WLAN 的 192.168.1.100；DNS 使用该网卡现有服务器 119.29.29.29 / 182.254.116.116。TLS 保留官方域名 SNI、Host 和证书校验。
- 十分钟实测 Qwen 60/60、DeepSeek 60/60 到达 HTTP；带现有凭据的非生成 `/models` 两家均 200，配置模型都被列出。没有真实生成请求。
- 实际停止专用代理三个端口和 Watchdog 后，国内探针及 Gateway 检查仍成功；原代理/任务已恢复，日常 VPN 未关闭。
- 这是 Windows socket 及路由层的出站选择证据。没有物理抓包，也没有关闭日常 VPN 上游；完全没有系统级截获的强结论保持 **NOT_VERIFIED**。`pktmon status` 返回驱动访问被拒绝，未提权或改变捕获设置。
- 默认 Docker bridge 实测仍连接 198.18.0.x，不能计作独立直连。Provider 凭据与客户端应保持现有 Windows 可信进程边界，Docker 继续运行有界工具；没有改 Docker 网络或暴露代理端口。

## 启动国内 Gateway

以下命令复用 `D:/cgkn-provider-api-lab` 的原 GatewayServer 和 Provider Adapter，仅注入 CGKN 网络客户端；未修改外部 Lab 或 frozen worktree。

```powershell
cd D:/CGKN
python -X utf8 -m scripts.domestic_gateway serve --config D:/CGKN/config/network_routes.json
```

前台命令持续运行。需要后台时：

```powershell
Start-Process -FilePath (Get-Command python).Source -ArgumentList @('-X','utf8','-m','scripts.domestic_gateway','serve','--config','D:/CGKN/config/network_routes.json','--state-dir','D:/CGKN/.cgkn/domestic-gateway') -WorkingDirectory D:/CGKN -WindowStyle Hidden
```

具名状态目录内的文件锁阻止同一目录重复实例。目录 ACL 限当前用户和 SYSTEM；`session.json` 仅含临时本地 Gateway 访问令牌，不含供应商密钥，不要打印、上传或提交该文件。正常停止会移除它。

```powershell
Get-Content D:/CGKN/.cgkn/domestic-gateway/status.json
python -X utf8 -m scripts.domestic_gateway stop
```

当前已有一个国内 Gateway 实例运行。没有增加新的 Watchdog、Windows 登录任务或代理内核。

## CGKN 选择国内模式

仅在需要运行任务的当前进程/PowerShell 会话设置，不能写入全局环境：

```powershell
$env:CGKN_NETWORK_MODE = 'domestic'
```

原 `completion_client_from_environment()` 将读取 `.cgkn/domestic-gateway/session.json` 并返回带预算强制检查的 GatewayCompletionClient；会话缺失时失败关闭，不会偷偷转回默认 Provider。到 loopback Gateway 的 HTTP 客户端也不继承环境代理。

角色配置为 `config/provider_profiles/domestic_model_routing.json`：Agent 仍为 Qwen，Worker 仍为 DeepSeek，限制和契约沿用原配置，`fallback=deny`。没有更改能力评分或给 Grok 专属任务指派较弱模型。

真正模型任务必须有**本次**明确授权、预算账本和价格限制。授权后可在原任务入口指定 `--routing-config D:/CGKN/config/provider_profiles/domestic_model_routing.json`；本轮没有执行计费的 `scripts/run_agent_mvp.py`。`experiments/product_dev_113/run_dev.py` 的默认传输也已改为上述国内策略，但封存实验仍须重新核对源码冻结哈希，不能绕过 FREEZE_MISMATCH 或复用旧授权。

清除国内模式：

```powershell
Remove-Item Env:CGKN_NETWORK_MODE -ErrorAction SilentlyContinue
```

## 无生成费用检查

```powershell
python -X utf8 -m scripts.domestic_network probe --isolate --output D:/CGKN/artifacts/domestic-check.json
python -X utf8 -m scripts.domestic_gateway check --output D:/CGKN/artifacts/domestic-gateway-check.json
python -X utf8 -m scripts.domestic_network soak --isolate --duration 600 --interval 10 --output D:/CGKN/artifacts/domestic-soak.json
```

探针只 GET 当前 Provider Base URL 的 `/models`，没有生成请求或 Authorization。401 仅说明链路到达 HTTP。`--isolate` 仅在独立测试进程内设置错误环境代理，拒绝未绑定所选网卡的连接、私网 HTTPS 和应用层代理入口；不是系统防火墙，也不等于已切断其他进程的 VPN 上游。

探针报告 `DOMESTIC_READY / DOMESTIC_DEGRADED / DOMESTIC_UNAVAILABLE`，范围是两家 HTTP 连通性。认证、生成、任务完成及完全不经系统 TUN 必须分开验收。Grok 状态单独报告，不改变国内模式状态。

## 能力准入和请求安全

原全局模型路由继续 `fallback=deny`。若 Agent 已针对**当前任务**证明替代 Provider 能力足够，可通过现有 CompletionClient 注入点使用 `DomesticFailoverClient`，传入 `SubstitutionAdmission`。准入必须指定 role、schema_name、primary、backup、required_capabilities、proven_capabilities 和 evidence_ref；默认没有准入，不启用自动跨模型接管。该类不生成能力评分，不自行批准证据；示例测试中的 SYNTHETIC_TEST_ADMISSION_ONLY 不可用于真实任务。

仅 `network_unavailable_before_send` 且 outcome_unknown=false 时，允许一次经过准入的国内替代；两者都失败即返回。Grok 不在国内互相接管的候选中。逻辑请求 ID 保持一致，attempt ID 分开；取消、语义错误、认证错误、证书错误及未知提交不自动重发。

任务执行器对网络类 Gateway 错误返回 BLOCKED / NetworkUnavailable，附带 category、outcome_unknown，retryable=false，交给原 Agent checkpoint 决策；不将其当作业务输出错误，也不自动重放已完成工具节点。原 DAG、FileRunStore、预算和 JSON Schema 契约保持。

## 主机绑定与迁移

当前配置记录本机 WLAN 的 ifIndex=14、源 IPv4=192.168.1.100 和该接口原 DNS。换机器、换网卡或 DHCP 地址改变时应重新从 `Get-NetIPConfiguration`、`Get-DnsClientServerAddress` 核对并修改这两个直连 profile。错误配置会失败关闭，**不能**把国内 Provider 临时接回代理来掩盖问题。

每个国内 Provider 必须有不同的 route ID、无 proxy_url、无代理 fallback、具有明确 interface_index/source/DNS/域名白名单。国内策略加载器拒绝共享池或代理回退。Grok 仍使用单独代理池；仅经明确配置移除 disabled_providers 中的 grok 后才启用，不影响国内池。

DNS 解析器为有界 IPv4 A 查询，只向配置的服务器发包、拒绝私网及 fake-IP 回答、最多缓存 60 秒；不静默调用系统 DNS。HTTPX 0.28.1 + httpcore 1.0.9 已在主机安装，已补齐版本锁定。HTTPX 默认 backend 在 connect 后才设置 socket_options，故这里仅替换 pre-connect backend，并复用原 HTTP/TLS/连接池实现。升级版本必须重新验证该兼容边界。

Qwen 工作空间专属端点未使用：本轮不需要替换可用的原生产 Base URL，且没有核实账号地域/工作空间的新增端点授权。

## 回滚

不回滚上一轮 Watchdog/Mihomo 建设，不使用 git reset/clean，不覆盖用户其他未提交工作。

```powershell
python -X utf8 -m scripts.domestic_gateway stop
Remove-Item Env:CGKN_NETWORK_MODE -ErrorAction SilentlyContinue
# 先验证所有当前文件及备份哈希，默认不写入。
python -X utf8 -m scripts.domestic_network rollback --manifest D:/CGKN/artifacts/domestic-direct-20261028/rollback-manifest.json
# 确认后显式恢复本轮修改过的既有文件。
python -X utf8 -m scripts.domestic_network rollback --manifest D:/CGKN/artifacts/domestic-direct-20261028/rollback-manifest.json --apply
```

新增模块保留在工作区，恢复旧入口后不被加载。哈希不一致时停止，防止覆盖后续修改。回滚 dry run 已执行；未实际回滚。

完整本轮证据：`D:/CGKN/artifacts/domestic-direct-20261028/report.md`。旧证据目录保持原状。

依据：[Windows IP_UNICAST_IF](https://learn.microsoft.com/en-us/windows/win32/winsock/ipproto-ip-socket-options)、[HTTPX 环境代理策略](https://www.python-httpx.org/environment_variables/)、[HTTPX transport](https://www.python-httpx.org/advanced/transports/)。配置和文档不能代替本轮真实出站及稳定性证据。
