> 2026-10-28 国内模式更新：`config/network_routes.json` 已改为 Qwen/DeepSeek 独立物理接口直连，Grok 默认禁用。新的运行、验收与回滚入口见 [国内模式说明](domestic_network_operations.md)。下文保留已有专用代理运维方法；专用 Watchdog 状态不代表国内模式状态。

# API 专用网络运行说明

从 `D:\CGKN` 执行。专用代理、Watchdog 和 Windows 登录任务均不依赖 Docker。
现有日常 VPN、系统代理、DNS、网关和防火墙不由这些命令管理。

## 当前部署

- Mihomo Meta v1.19.21；仅监听 `127.0.0.1:17890/17891/17892`。
- 登录任务：`CGKN-API-Network-Watchdog`，当前用户 Interactive/Limited，禁止重复任务实例，失败后每分钟重启，最多三次。
- 守护配置：`D:\CGKN\.cgkn\network-watchdog\watchdog-config.json`。
- 状态、轮转日志：同目录的 `status.json`、`watchdog.jsonl`、`proxy-process.log`。
- 私密节点 YAML 留在原有私密目录；确切物理路径在守护配置中。不要复制到 Git。
- Codex MSIX 与任务计划程序对 `AppData` 的路径解析不同。必须使用已解析的物理路径；不要自行把原始 AppData 别名写回配置。

```powershell
$cfg = 'D:/CGKN/.cgkn/network-watchdog/watchdog-config.json'
python -X utf8 -m scripts.network_watchdog status --config $cfg
python -X utf8 -m scripts.network_watchdog start --config $cfg
python -X utf8 -m scripts.network_watchdog probe --config $cfg --output D:/CGKN/artifacts/network-probe.json
Get-Content D:/CGKN/.cgkn/network-watchdog/watchdog.jsonl -Tail 10
./scripts/network_watchdog_task.ps1 -Action Status
```

`start` 幂等；跨进程文件锁保证只有一个守护循环。`probe` 仅对配置中的 models 地址发无凭据 GET，不提交生成请求。401/403 表示到达 HTTP 阶段，认证状态仍是 NOT_TESTED。节点关联来自控制面 source port 匹配；NOT_CAPTURED 表示没有取得该次请求的节点证据。

## 停止、恢复、卸载

```powershell
# 正常停止守护；保留代理进程。
python -X utf8 -m scripts.network_watchdog stop --config $cfg
# 待 status 显示 watchdog_alive=false 后，正常停止专用代理。
python -X utf8 -m scripts.network_watchdog stop-proxy --config $cfg
# 恢复登录任务及守护。
./scripts/network_watchdog_task.ps1 -Action Install -Config $cfg
# 卸载登录任务并停止该任务进程；专用代理保持运行。
./scripts/network_watchdog_task.ps1 -Action Uninstall
```

安装/更新仅涉及这个具名的当前用户任务。不要使用管理员模式，也不要改动日常 VPN 任务。
真实注销/重启会打断用户会话，本轮未执行；登录触发器已安装，任务手动触发和持续运行另有证据。

## 新机器配置与回滚

可信主机所需依赖见 `requirements-network.txt`；当前环境已具备，无新增安装。

```powershell
python -X utf8 -m scripts.network_watchdog configure --config D:/CGKN/.cgkn/network-watchdog/watchdog-config.json --proxy-config '<现有专用 config.yaml 的绝对路径>' --executable '<mihomo.exe 的绝对路径>' --state-dir D:/CGKN/.cgkn/network-watchdog
```

命令拒绝覆盖已有守护配置。探针 URL 由当前 Provider 配置核对后写入；迁移时用 `--routes <已核对的路由 JSON>`，不得凭空更换 API Base URL。新配置需保留 TLS 校验、`trust_env=false` 和有界超时。

```powershell
# 专用 YAML 应用 fallback；私密目录内备份，检查成功后热加载。
python -X utf8 -m scripts.network_proxy_config apply --config $cfg --receipt D:/CGKN/artifacts/new-proxy-patch.json
# 回滚本轮专用 YAML：同时验证现有文件和备份的 SHA256。
python -X utf8 -m scripts.network_proxy_config rollback --config $cfg --receipt D:/CGKN/.cgkn/network-watchdog/rollback-receipt.json
```

不要直接 `git reset` 或 `git clean` 回滚：仓库原有大量未提交工作。网络代码应按交付清单逐文件审阅。本轮没有 staging、commit 或 push。

## 机制与边界

Mihomo 的两个入口分别绑定主优先和备优先 fallback 组，候选仍是原有两个节点；每 60 秒非生成健康检查，超时 8 秒，失败阈值 2。没有添加来源不明节点。两条入口可能实际选择相同节点；配置的故障域均标记为 `WLAN-shared`，不宣称双物理网络。

Watchdog 每 15 秒检查进程、监听及控制面，每两轮检查 Provider × Route；L3 失败只记录和熔断观察，不重启整个代理。连续两次 L1 失败才重启经过可执行文件及配置路径匹配的专用实例；重启指数退避、上限 300 秒，最多 5 次/小时。端口被其他进程占用时拒绝启动。日志文件设定 2 MiB 轮转上限；进程原始日志在守护循环中截断轮转，私密日志不要上传。

传输层默认按 Provider × Route 熔断：两次失败、30 秒冷却、恢复需要两次成功，恢复期间只放行一个试探请求。Mihomo 原生 fallback 的节点恢复依赖其单次健康检查，没有额外多轮节点恢复防抖；高频抖动线路仍需继续观察。

`NetworkClient` 保持既有预算入口及两次尝试上限，第二次尝试仅允许请求明确未发送、没有部分响应且错误可重试的情况；使用 150–350 ms 有界抖动。读取失败、未知提交结果、HTTP 错误、证书错误、取消和截止均不自动重发。模型/角色能力、费用预留、迟到 usage 和 DAG 已完成节点复用沿用原实现。

后续运行可显式使用 `--transport-config D:/CGKN/config/network_routes.json`。历史 F 盘已封存配置与证据未被改写。旧 `GatewayCompletionClient` 是 loopback API Lab 服务的兼容入口；其服务内部不由这个适配器注入专用传输，本轮没有改写外部 API Lab 或 frozen worktree。不要把这条兼容路径算作完整接入验证。

`NetworkHealthExecutor`/`network.health@1.0` 提供可选的通用 Block 输入输出边界，失败返回 NetworkUnavailable/BLOCKED；未新增规划器、DAG 或项目状态权威。

容器中的 127.0.0.1 是容器自身。当前未发现运行中的 Provider 容器；本轮入口是 Windows 可信 Provider 进程。`host.docker.internal` 也不能自动访问仅绑定 Windows 回环的监听；未为此扩大监听范围或改防火墙。需要容器接入时应另行设计明确的主机入口。

## 诊断顺序

1. `status` 的 current.ok=false：查进程、占用端口、控制面和 `fatal.json`；配置无效不要靠反复重启修复。
2. TCP=true、CONNECT=false：代理隧道或上游连接阶段，结合节点日志；不能仅凭客户端错误认定 API Key 问题。
   本轮发现系统 DNS 与 Mihomo 自身 DNS 对两个节点返回不同地址：系统解析后的直接 TCP 探针超时，Mihomo 解析地址绑定 WLAN 的 TCP 探针成功。必须按代理实际 DNS 路径诊断，不能把系统 DNS 探针失败直接记作节点死亡。原配置已有专用 proxy-server-nameserver，本轮未修改系统 DNS。
3. CONNECT=true、TLS=false：TLS/上游路径问题；证书失败与握手超时分别记录，不关闭证书校验。
4. HTTP 401/403：确认是无凭据探针还是已授权请求；401 不证明真实密钥失效。
5. HTTP 429/5xx：Provider 服务状态单独记录；已提交生成请求不自动换路再发。
6. 所有路由不可用：停止盲目重试，保留任务与预算未知预留。网络恢复后只重试受影响节点。

```powershell
# 独立进程中运行 10 分钟，不需要 Codex 保持交互。
python -X utf8 -m scripts.network_watchdog soak --config $cfg --duration 600 --output D:/CGKN/artifacts/network-soak.json
# 故障注入全部使用隔离本地监听和独立 Mihomo 测试实例。
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -X utf8 -m pytest tests/providers/test_network_reliability.py -q --run-profile-marked
```

测试中的本地 HTTP 响应仅是故障注入证据，不属于真实模型验收。L4 需要单独明确的当次测试授权与预算，本轮未发计费模型请求。

依据：[Mihomo fallback](https://wiki.metacubex.one/config/proxy-groups/fallback/)、[listener 绑定](https://wiki.metacubex.one/config/inbound/listeners/)、[配置 API](https://github.com/MetaCubeX/Meta-Docs/blob/main/docs/api/index.md)、[HTTPX transport](https://www.python-httpx.org/advanced/transports/)。官方支持的能力仍需以本轮运行证据判断。
