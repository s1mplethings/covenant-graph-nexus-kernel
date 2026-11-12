# ITER-076 — 真实产品评测预检：隔离失败，尚未开展产品评测

日期：2026-10-27。状态：`BLOCKED_POLICY / PROTOCOL_INTEGRITY`。
本轮没有完成用户要求的真实产品评测。只有环境预检、无敏感 canary、已有网关回归与 Corpus 归档实际执行；不能把这些结果解释为 DEV 或正式产品交付。

## 实际版本与保护范围

- 当前分支：`codex/provider-gateway-integration-20261017`。
- 当前 HEAD：`0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`。
- 历史源码：`56cba0c04abb659f53eadef406c23388fd1cc891`，历史证据及 `v0.2.0-rc.6`：`feaf6c10ccac1a6f54175040e8c25f38d7ded40e`，均本地可访问。
- 当前分支与历史证据的 merge-base：`3df1110d31d33f14ab2a07ba3b6dc966f656d348`。不能把历史封板视为当前 HEAD 验证。
- 历史管理文件中 ITER-061–075 已占用，选择下一空号 076。
- 用户原有 `.api_lab_worktree/`、`.service_scratch/` 保留；没有 reset、stage、commit、push、merge 或发布。
- 没有访问 ACFV Final 私有材料、答案、生产数据库或原始媒体。仅检查已知历史 Corpus 根目录标记，并写入本轮自己的新记录。

## 实际执行及原始证据

本地证据目录：`F:\CGKN-ITER-076\preflight-20261027`。

| 检查 | 实际结果 | 结论边界 |
|---|---|---|
| CGKN 插件 doctor | provider mainline available，插件可用 | 不证明实际模型或自主开发可用 |
| Docker 恢复 | 初始 named pipe 不存在；启动 Desktop 后曾返回 HTTP 500；随后 28.3.3 正常响应 | 恢复环境，不是产品修复 |
| 容器 canary | 9 个布尔检查均 true，退出 0 | 仅独立容器 shell；未接入两条完整开发路线 |
| 现有 CommandExecutor canary | `SUCCEEDED`，stdout=`SYNTHETIC-NOT-A-SECRET` | **隔离 FAIL**：项目外合成文件可读 |
| 相关回归 | 33 passed，1 skipped；保存的一次耗时 19.52 秒 | HTTP mock、预算与运行时回归，不是产品 DEV |
| 凭证状态 | API Lab 的 deepseek、qwen、grok 均 available | 只使用受限解析器返回状态；未输出密钥，未验证远端授权 |
| Corpus | 新记录写入 PASS，本记录两个对象、manifest hash 和派生索引验证通过 | 没有扫描或验证整个历史库 |

初始 Docker 原始错误：

```text
open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
request returned 500 Internal Server Error ... /v1.51/info
```

完整 argv、stdout、stderr、退出码保存在 `checks.json`；实际 canonical executor 请求及结果保存在 `route-canary.json`。canary 只包含新建无敏感字符串，不尝试读取真实秘密。

Python 3.13、Node、ffmpeg 均在 PATH。Docker 镜像锁定为：
`python@sha256:37ed081dbe77115b843b3d139801105e110f43005a2df4e80af94777cfd807f5`。
未校准 ASR、真实视频、浏览器自动化或发布目标；不声称具备产品验收条件。

## 协议阻塞与未完成准备

`ISO-001` 是实际观察到的阻塞，不是推测：`cgkn/executors/local.py` 中的 CommandExecutor 在宿主进程权限下运行子进程；约束 cwd 并不约束子进程文件访问。现有路线未保证候选测试、worker、应用子进程与验收资料隔离。单独的容器配置不能修复尚未接入的执行路线。

当前浏览器、MCP、连接器权限隔离均为 UNTESTED。没有将这些宿主能力暴露给被测系统。正式冻结必须等待完整工具边界验证；不得以本报告替代该验证。本轮没有实现完整容器执行适配，不能声称所有可能的工程修复均已尝试。

另发现三个具体适配缺口：

1. 当前分支没有历史 Project Corpus 和 ITER-060 模块。归档使用历史提交的原始 `contracts.py` 与 `store.py`，只供评测基础设施使用，未替换当前 kernel。
2. 历史 ITER-060 runner 使用预定文件范围、FileBundle、禁止网络/shell 的 CLI 任务，不能直接作为本轮公平工具型 Direct，也不能把其人工 Blueprint 直接传给 CGNK。
3. 当前 API Lab adapter 把请求配置 `provider.model` 填入结果，未保留上游 `decoded.model`。实际模型身份 UNVERIFIED。现有 AgentProjectLoop 还要求 Agent/Worker 模型不同，若沿用须按完整系统比较披露，不能归因于架构。

未实现：正式产品 runner、GUI 验收器、参考行为及错误变体验证、两领域已有产品初始快照、真实媒体许可/哈希、五档增量题卡、24 项逐题义务映射、私有 oracle、正式冻结、DEV 与正式执行。这些是未完成工作，不是假定已通过的条件。

## 矩阵与评分

`matrix.json` 登记完整 32 个槽位，顺序为 TAKEOVER B−1/B0/B+1、B−2/B+2，随后 CREATE、REPEAT、SELF_EVOLVE；同题两路线顺序交替。seed 7601 是待冻结值，题包尚未冻结，不称 holdout。

| 分组 | 计划 | 实际开发运行 | 未运行 |
|---|---:|---:|---:|
| TAKEOVER 首次主表 | 20 | 0 | 20 |
| CREATE | 4 | 0 | 4 |
| 预注册重复 | 4 | 0 | 4 |
| SELF_EVOLVE | 4 | 0 | 4 |
| 正式合计 | 32 | 0 | 32 |

DEV 实际 0 次，上限 8 次。基础设施预检 1 轮，不计入产品尝试。
自主达标 0、产品失败 0、正式污染 0，正式已执行分母为 0；不能报告成功率 0%。32 个计划槽位均 NOT_RUN/UNVERIFIED，不能算作模型失败。
所有槽位 24 工程子项、4 领域项为 null，G1–G6 为 UNTESTED。已评权重 0、待评权重 100、可能工程区间 0–100；“已确认贡献 0”不是总分 0。
配对质量差、交付差、成本差、重复稳定性、演进回归全部不可计算。没有未配对的实际开发运行。没有任何 GUI、ASR、导出、远端发布或真实领域质量通过证据。真人评审未开始。

## 预算与干预

授权新增 Provider/API 预算人民币 100 元，至少预留 20 元验收；开发默认 60 分钟、80 请求、100 万 token，未修改。
本轮实际新增 Provider 请求 0、token 0、付费调用费用 0 元，剩余授权 100 元。未查询服务商账单，不把估算当实际账单。宿主会话本身未作独立计价。
已查看官方 DeepSeek 价格资料，但尚未绑定成正式计费冻结：[官方定价](https://api-docs.deepseek.com/quick_start/pricing/)。不沿用 ITER-060 历史价格作为本轮已验证配置。

宿主执行了版本/源码检查、凭证状态解析、Docker 启动和镜像拉取、合成 canary、基础设施代码、现有 mock 回归和归档。没有产品业务代码、被测模型提示、语义修复或强模型救援。没有实际模型运行可供判断零辅助，因此矩阵 `host_semantic_assistance_count=null`，不为未运行项伪填 0。
未使用子代理、未发送外部消息、未公开发布。归档脚本首次运行因 sys.path 缺少仓库根目录报 ModuleNotFoundError，修正基础设施导入后重跑成功；这不是被测产品修复。

## Corpus 与封板状态

复用既有根目录 `F:\CGKN-ITER-060\project-corpus`。
记录：`entry-iter076-preflight-20261027`，类型明确为 `EVALUATION_PREFLIGHT_NOT_PRODUCT_ATTEMPT`，状态 BLOCKED_POLICY，split DEVELOPMENT。
manifest：`sha256:0d06ca6fe12fafdfee7fd29e8fb9a331a77147c78727a9e43f3918b9c191191a`。
`corpus-receipt.json` 保存原始写入回执、历史实现源码哈希和本记录验证结果。`hashes.json` 是本地证据文件哈希清单，不是完成正式源码/证据封板的声明。
本轮新增源码未提交，未形成正式源封板；没有 candidate hash、正式模型响应或成功截图可交付。

## 精确恢复入口与判据

下列命令只复现预检，不会暗中启动付费或正式运行。每次使用新输出目录，保留旧证据：

```powershell
Set-Location D:\CGKN
python experiments/product_eval_076/preflight.py --output F:\CGKN-ITER-076\preflight-recheck-01
python experiments/product_eval_076/route_canary.py F:\CGKN-ITER-076\preflight-recheck-01
```

`route-canary.py` 当前会打印隔离 FAIL，即使底层调用退出 0。修复前不能解读为 PASS。它读取的只有该目录下新建的合成文件。

恢复真实实验须先完成通用容器/受限执行适配，让两路线全部命令、测试、应用子进程只能访问本运行允许资料；通过同一路线重跑越界读取、只读输入写入、日志篡改、网络以及浏览器/MCP/连接器 canary。保留上游实际模型字段和统一全局人民币预算账本。然后完成题包、参考验收和 DEV，之后才能正式冻结并运行全部矩阵。

公开平台目标未获授权，未来可先测本地受控传输，但真实平台 G5 必须维持未验证。不得为了补齐 G5 擅自发帖。

当前不需要用户追加费用或提供明文密钥；现有凭证可解析。当前主要缺口是评测基础设施实现及验证，不能把它推给用户用“是否继续”解决。

在本轮版本与预算下，只观察到现有宿主执行器不满足此次盲测隔离要求。无法比较 Direct 与 CGNK 自主产品交付能力，无法证明任一路收益。下一项最小有价值验证是让一个真实模型发出的无敏感工具调用通过完整隔离路线执行，并证明同路线拒绝外部 canary；该结果仍只属于 DEV 基础设施验证。
