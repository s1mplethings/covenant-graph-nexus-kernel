# ITER-114 / NET-ROUTE-V1：API 显式线路与有界恢复

2026-10-27。本轮是 ITER-076/113 的基础设施续作，不是新的产品开发或正式比较。源码起点 HEAD：`0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`；存在既有工作区修改，未 reset、提交、推送或发布。最终源码哈希见 `F:/CGKN-ITER-114/source-final.json`。

已将显式 Provider 路由、独立代理进程、连接池和有界恢复接入现有调用链。相关回归 48 passed；最后小改动的网络专项复验 10 passed；API Lab 相关回归 6 passed。实际 CGNK runner 的离线通路检查通过，两家真实模型生成通过。但真实线路仍有间歇性连接失败，进程停启和物理接口独立性尚未验证，不能声称网络已完全稳定。

本轮真实生成共 3 次尝试、2 次成功逻辑请求，新增保守费用 **0.12348 元**，历史累计 **142.45222 元**，原累计上限 **187.98930 元**，余额 **45.53708 元**。没有启动新的业务开发或产品验收。

## 实际接入与范围

当前通路为 Agent/ActionComposer、LLMExecutor → NetworkClient → 既有 LiveClient → API Lab ProviderComparisonService / OpenAIChatAdapter → 请求级注入 opener → HTTPX 连接池 → 专用 Mihomo listener / 固定出站 → 官方 API。没有增加规划器、网关或第二个交付路线；候选工具环境仍保持原隔离政策。

修改包括：

- `cgkn/providers/network_transport.py`：不可变线路配置、TLS 校验、`trust_env=false`、连接池、阶段超时、整体截止、取消与脱敏 trace。当前配置 connect/read/write/pool 为 15/60/20/10 秒，整体 90 秒；等待并发槽计入截止。默认传输重试为零，由上层统一限制。
- `experiments/product_dev_113/network_client.py`：每逻辑请求最多两次尝试；只在允许的传输错误下重试或进入明确配置的备用线路。不自动换 Provider。每次尝试先独立预留预算；迟到响应不提交给 Agent，可靠 usage 只能结算原尝试一次。
- `live_provider.py` 与外部仓库 `D:/cgkn-provider-api-lab/src/cgkn_provider_lab/adapters.py`：移除进程全局 urlopen patch，改为每次调用的 adapter 注入；共享账目预留/结算加锁，网络调用在锁外执行。
- `scripts/provider_api_budget.py`：终态可靠 usage 的重复结算幂等；冲突 usage 明确失败，未知费用不擅自清零。
- `run_dev.py`：增加显式 transport、候选快照和累计资源输入；旧记录不覆盖，未指定新配置不冒称使用新线路。

活动脱敏配置：`F:/CGKN-ITER-114/transport-active.json`；早期配置保留。依赖清单为 `experiments/product_dev_113/requirements-network.txt`（HTTPX 0.28.1）。本轮使用非流式 `stream=False`；测试了分段响应、心跳式字节与不完整 JSON，不宣称启用了 SSE。

独立进程使用已安装的 `D:/Clash Verge/verge-mihomo.exe`（Mihomo Meta v1.19.21），本轮 PID 51240；专用入口 17890/17891，控制端口 17892。配置在 `C:/Users/sunom/AppData/Local/CGKN/api-route-114/config.yaml`，ACL 限当前用户与 SYSTEM，包含私密节点信息，不进入仓库或 Corpus。listener 直接绑定固定节点，不依赖日常 GLOBAL/自动策略组；没有修改日常 FlClash、系统代理、TUN 或路由。

依据已核对的 [Mihomo listener 文档](https://wiki.metacubex.one/config/inbound/listeners/) 使用直接 proxy 绑定；HTTP 客户端传输与重试边界参照 [HTTPX transport 文档](https://www.python-httpx.org/advanced/transports/)。文档和配置本身不代替实际线路证据。

## 真实网络与生成证据

| Provider | 活动路线 | 实际检查 | 真实生成 |
|---|---|---|---|
| DeepSeek | api_backup / 17891 | 备用 `/v1/models` 返回 401；主入口连接失败 | `deepseek-flash`，一次 ConnectError 后有界重试成功 |
| Grok | api_primary / 17890 | 主/备 `/v1/models` 均曾返回 401 | `grok-4.7` 成功，与 DeepSeek 请求时间重叠 |
| Qwen | api_primary / 17890 | 配置和离线适配检查；未发真实探针 | 未执行 |

两家结果均完整解析为 `{"ok":true}`。实际 request_id、模型、usage、时间与尝试关联见 `smoke-result.json`、`smoke-provider/`；代理控制面观察到对应 API host 和 primary/backup 节点链，见 `network-reachability-v2.json`。401 仅证明对应端点可达，不代表生成；生成结论仅来自上述付费烟测。

共执行 7 次无鉴权、非生成 HTTPS 探针（2 次根路径、4 次 models、1 次接口取证）。最后接口取证探针仍失败，未捕获可证明出口接口的已建立连接，见 `interface-proof.json`。这保留了线路间歇性失败的反例。

隔离程度分别为：专用入口/固定节点已配置并有代理链证据；独立进程已启动，但退出日常客户端后的独立性、改变日常选路后的不变性均未实测；WLAN 绑定只是配置，实际接口证据不足；未实现第二条物理接入网。没有将这些未验证项计作 PASS。

## 离线正确性、生命周期与限制

专项覆盖并发路由/凭证不串用、环境代理污染不生效、配置失败关闭、连接/读取失败的有限尝试、鉴权和语义错误不重试、部分响应不提交、费用竞争、取消与截止、迟到 usage 幂等结算、字节持续到达仍受总截止约束。DAG 已完成工具节点在后续模型网络失败与恢复后不重放，副作用计数保持 1。

取消/整体截止阻止响应提交；底层在有限连接/读取超时内退出，关闭客户端等待这些有限操作并释放连接池，不宣称能即时杀死任意底层线程。断线后不把原工具动作当模型重试重新执行。

实际 `run_route`、Coordinator、Worker、工具注册与 Docker 执行路径使用 7 次可控假响应完成 conformance，标记 **HARNESS_CONFORMANCE_ONLY**，零付费，不属于模型解题或正式实验。证据在 `route-conformance/`。真实并发烟测复用同一 NetworkClient 的角色绑定；未验证多个不同预算客户端同时运行的场景。

相关命令（仓库根目录执行）：

```powershell
python -X utf8 -m pytest experiments/product_dev_113/test_network.py experiments/product_dev_113/test_transport.py experiments/product_dev_113/test_continuation_limits.py tests/test_provider_api_budget.py tests/test_provider_api_transport.py tests/runtime/test_graph_commit.py tests/agent/test_project_loop_boundaries.py -q -rs -p no:cacheprovider --run-profile-marked --tb=short
python -X utf8 -m experiments.product_dev_113.network_diagnose --config F:/CGKN-ITER-114/transport-active.json
```

第一条实际执行 48 passed；最后错误状态/尝试次数小改后专项 10 passed。API Lab adapter/service 范围 6 passed（关闭无关 pytest 插件自动加载）；首次自动加载 pytestqt 的 QtCore 导入失败记验证无效，之后有效重跑。早先 profile 标记跳过的用例已用 `--run-profile-marked` 实际执行，没有将 skipped 当通过。未跑全仓回归或整套 GUI/ASR 业务验收。

诊断默认只显示配置，不发请求；增加 `--check --output <新的输出路径>` 才执行两次非生成端点检查。普通专用进程启动方式为下面命令，仅在确认实例未运行时使用，不能重复启动：

```powershell
Start-Process -FilePath 'D:/Clash Verge/verge-mihomo.exe' -ArgumentList @('-d','C:/Users/sunom/AppData/Local/CGKN/api-route-114','-f','C:/Users/sunom/AppData/Local/CGKN/api-route-114/config.yaml') -WindowStyle Hidden
```

自动审批拒绝了“停止本轮专用代理、验证入口不可用、再启动”的组合操作，原始错误为 **`blocked by policy`**，命令未执行；没有换命令或控制接口绕过。故实际停止/重启故障注入保持未验证，专用进程保留。记录：`blocked-action.json`。日常网络未被中断。

代码回滚入口先校验四个修改文件与备份哈希，默认不写入：

```powershell
python -X utf8 -m experiments.product_dev_113.network_rollback --manifest F:/CGKN-ITER-114/code-rollback-manifest.json
```

实际 dry run 返回 `HASHES_VALID`。显式 `--apply` 才恢复该清单的四个文件；不删除新增可选模块，不操作代理进程。未执行回滚。代理停启测试仍受上述拒绝限制。

## 账目与审计差异

用户提供的 v7 数字是历史检查点。续读真实 stage07 后：网络任务前账目为累计 142.32874 元、余额 45.66056 元；stage07 已在此前授权下执行并结束，不能忽略或重复启动。本轮 0.12348 元中，成功调用按保守单价计 0.03020 元，失败 usage 未知保留 0.09328 元上界；实际账单未查询。网络子上限 2 元/6 次，实际 0.12348 元/3 次。

累计连续链请求 183、token 2,478,768（含未知预留），链内保守费用 54.46292 元，累计有效开发计时 1694.734494 秒；这不是本轮纯网络墙钟耗时。旧未知预留均保留。权威账目：`F:/CGKN-ITER-076/global-provider-budget.json`。

原始 smoke 授权/派生 billing 文档保留了继承的历史 `max_inflight=1`、串行原因、旧余额/50 元模板字段，这些描述不符合此次新客户端并发实测，不能作为新配置证据。没有重写原始文件以掩盖差异。有效费用/次数限制由 smoke 的数值 cap、全局账本和逐尝试预留验证；实际并发 2 由生产 NetworkClient 和重叠 trace 验证。此为元数据不一致，明确披露，不影响未知费用保守保留；本轮不作正式自主比较。

## 旧产品、恢复入口与归档

旧 v7 封板 709 个文件校验无差异，stage06 候选 SHA256：`7e882d5ead6f215203c8bc9dd275e51586f5e03a42d0908d5dec2fd01aa89480`。证据 `prior-integrity.json`。没有业务代码代修、私有验收反馈回流或本轮业务 GUI 操作；旧 stage06 的未完整交付/PENDING_HUMAN 结论保留。stage07 保留为此前开发记录，未在本轮独立验收。

本轮新增正式运行 0、产品 DEV 0；不把合成回放或两个极小生成算产品实验。原 32 格不因本轮网络测试变为通过。已有业务能力成绩不在本轮重评分。

以下恢复入口已不带 `--execute` 运行，返回 `LOCAL_CONFIG_VALID; no paid calls`。从指定 stage06 候选追加 stage08，携带最新累计账目；不会覆盖 stage07。真正付费恢复需显式追加 `--execute`，本轮按用户网络专用指令未执行：

```powershell
python -X utf8 -m experiments.product_dev_113.run_dev --stage 8 --freeze freeze-net114-recovery-v2.json --authorization F:/CGKN-ITER-114/product-recovery-authorization.json --feedback F:/CGKN-ITER-114/product-recovery-feedback.json --transport-config F:/CGKN-ITER-114/transport-active.json --initial-snapshot F:/CGKN-ITER-113/dev-stage-06/frozen/candidate.zip --resources F:/CGKN-ITER-114/cumulative-resources.json
```

继续使用当前余额 45.53708 元，未产生新预算。若线路/源码变化，需重新核对对应哈希和受影响检查。当前不需再消耗付费请求证明重复的成功；待验证项是实际停启权限、日常客户端生命周期独立性和真实出口接口，而不是业务代码补丁。

本报告、摘要、脱敏配置追加到既有 `F:/CGKN-ITER-060/project-corpus`，entry 为 `entry-iter114-api-network-routing`，关联 `entry-iter113-cgnk-continuation-v7`；按 NON_ADDITIVE_INFRASTRUCTURE / PARTIAL 记录。验证收据 `F:/CGKN-ITER-114/corpus-receipts.json`；最终证据清单 `F:/CGKN-ITER-114/evidence-seal.json`。不复制私密代理配置、真实凭证或受保护 Final 材料。
