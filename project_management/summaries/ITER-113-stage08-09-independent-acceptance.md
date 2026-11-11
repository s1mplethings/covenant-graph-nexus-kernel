# ITER-113：stage06 → stage08 → stage09 续作与独立验收

2026-10-28。本轮已实际运行 CGNK 自主开发、冻结最终候选并完成本地独立验收。**完整目标未达成，主状态 NOT_DELIVERABLE，附加 PENDING_HUMAN。** 工程观察评分 **78.75/100**，D 测试效果均值 **2.75/4**；低于既定 80 分和 D≥3 门槛。不是基础设施 READY，也没有把模型自行宣称成功当作产品通过。

实际硬停止：stage09 下一请求的完整保守预留不能纳入剩余额度，返回 `RUN_BUDGET_EXHAUSTED`。本轮新增 **44.25664 元、162 次 Provider 请求**，历史累计 **186.70886 元**，累计上限仍为 **187.98930 元**，剩余 **1.28044 元**。没有超支、充值或重新计一份预算。费用为既有保守口径，供应商实际账单未查询，历史未知预留保留。独立验收零 API 费用。

## 起点、运行与实际身份

从用户指定的 stage06 候选启动 stage08，保留 stage07 的历史费用和原始记录，没有用 stage07 候选替换起点。stage08 达到 80 次 Agent 决策检查点后，按本轮持续执行授权追加 stage09，继承 stage08 候选和累计资源；只提供机械停止说明、原公开任务及模型自己的原始记录，没有提供宿主业务摘要或私有验收反馈。

| 阶段 | 真实请求 | 新增保守费用 | 结束原因 |
|---|---:|---:|---|
| stage08 | 83 | 22.39146 元 | `agent decision limit reached`；冻结成功后继续 |
| stage09 | 79 | 21.86518 元 | `RUN_BUDGET_EXHAUSTED`；冻结成功 |

本轮原始返回身份全部为 **deepseek-flash（162 次）**，没有 Grok/Qwen 真实调用，不能因为注册了其他 Provider 就声称本轮多模型协作。162 次返回均有 `ok` 传输结果；其中仍有工具/语义格式失败和无效业务检查，`ok` 不代表任务成功。未调用强模型救援。

累计连续链为 345 次请求、4,604,012 token（包括历史未知预留）、3,405.731 秒有效开发时间。本轮增加 2,125,244 token、约 1,711 秒有效开发时间。时间和 token 没有清零；剩余费用非零也不代表当前完整请求能安全准入。

源码 HEAD 为 `0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`，NET114 最终源码哈希全部未变。复用了 NetworkClient → API Lab 请求级适配 → 专用线路，以及既有 CGNK Agent/CapabilityTree/DAG/Executor/State 通路。宿主没有修改本轮执行框架或候选业务代码、测试、数据库。既有工作区修改保留，未提交、推送或发布。

最终候选：[stage09 candidate.zip](F:/CGKN-ITER-113/dev-stage-09/frozen/candidate.zip)，SHA256：

`f4a6b262ee8ceb1d8639d4682f79f7b38103a89bbdf9cbd2bcc2bc6affc8f583`

stage08 候选 SHA256 为 `567caed6a68b3955c4920002ac9575d3680dbae91aac43dbbc94ced473b58fcc`，单独保留。stage06 原候选未变；NET114 已封板的 112 个文件复核无差异。审计链分别校验 329、279 条记录，见 [stage-accounting.json](F:/CGKN-ITER-113/continuation-stage08/stage-accounting.json)。

## CGNK 实际完成的变化

CGNK 自行收紧导出时长校验及测试容差，增加搜索跳转相关测试，编写、调试 Chromium/CDP GUI 测试与重启脚本，并更新 PROJECT_STATE.md。原 README 的启动、操作和 pytest 命令仍可在规定镜像中复现。

过程中存在大量重复探索、错误下载 URL、浏览器连接/导航错误、重启命令退出异常和工具参数错误。原始失败全部保留，没有宿主代修。更新后的状态文件比起点更完整，但仍有不准确的证据引用；开发未能自行提交完整交付结论。

## 独立验收结果

所有检查绑定最终 stage09 哈希。先结束开发容器，再在隔离副本运行应用和测试；候选不能读取私有检查材料、宿主日志或其他路线。验收变体只在可丢弃副本中实施，原候选保持不变。

- **候选自己的 pytest：16 passed，27.40 秒。** 其中真实重开测试启动应用进程，经 HTTP 上传/导出，终止进程后再启动并检查保存状态。
- **真实 GUI 与媒体：通过已测主流程。** 新 `alternate.mp4` 经文件选择器上传、实际离线 ASR、检索 permit、明确选择该新素材、跳转播放，再选择 7–12.5 秒导出。实际用户手势复核后视频处于播放状态，来源正确。
- **输出：通过。** 独立解码，GUI 打开导出显示时长约 5.506 秒；来源三帧 MAE 为 0.965/0.791/0.773，音频包络相关性 0.999991，时间偏移 0。不是只检查文件存在或 ffmpeg 退出码。
- **边界及恢复：通过已测范围。** 负值、相等、倒置、超过时长的区间被拒绝；坏视频、空文件被拒绝；修正参数后 GUI 再导出成功。保留初次尚未完成时的 UI 观察和后来成功的终态，不将异步未完成判为成功。
- **归档兼容与持久化：通过。** 普通文件两次上传具有独立对象；原始 note 可由 GUI 打开；应用及浏览器真实重启前后数据库、文件、下载哈希一致，素材、转录和片段仍可访问。
- **ASR 状态：通过已测协议分支。** 正常语音实际调用 whisper；无音轨正确显示；独立执行失败/畸形 JSON 注入均有命中记录，失败素材无转录，恢复依赖并重传后新素材成功，旧失败记录保留。合法空响应显示 empty，无转录。后三者的故障/空响应是受控协议检查，不是内容质量评分。
- **测试效果的正例：** 数据丢失、错误时长、错误来源、不可解码四类有效变体被测试拒绝。后三种分别 3 failed / 13 passed，触发产物经 ffprobe/画面检查证实；重开丢失数据在第二进程启动前触发，并在资产仍应存在的断言失败。

主 GUI 目录包含 60 条浏览器相关原始记录（包含启动和只读观察），截图时间跨度约 801 秒；一次带实际用户手势的播放复核保留。故障检查另列，不能把截图数当样本数或真人可用性证据。

### 阻止完整交付的有效反例

候选 `gui_e2e.py` 上传后只等待任一既有 article，取第一个素材 ID；ASR、视频、搜索及导出检查又使用旧对象。模型的 n0051 记录里，`upload_submitted` 是 `original-note`，随后使用旧视频 `846bd9...`，仍输出 `ok: true`。PROJECT_STATE 还把失败的 n0038 与后续 n0051 一并写为全部通过。

为排除仅是文字记录错误，独立副本令 upload 不保存任何新素材并跳回首页，候选自己的 GUI 测试保持原样：**故障命中，上传前后素材列表完全一致，测试仍 exit 0 / ok true。** 因而该测试不能证明新上传 → 新 ASR → 对应导出的闭环。这是候选测试缺陷 `S09-TEST-IDENTITY-01`，主要归 D3；不据此把独立验证过的产品主流程重复扣成失败，也不伪装成宿主验收器故障。

证据：[gui-falsepass-result.json](F:/CGKN-ITER-113/continuation-stage08/gui-falsepass-result.json)。该发现未回流给任何开发 Agent，宿主没有修正测试。

### 验收器自己的错误

首次新增合法空 ASR 探针因 Windows CRLF shebang 未运行，转而发生真实转录；未命中记录记 EVALUATOR_INVALID。原材料保留，新 LF 版本在独立目录复验，命中 `valid_empty`，素材状态 empty、转录为零。另一次诊断命令有 shell 引号错误，也不计产品失败或通过。未修改候选业务实现或放宽断言。

## 评分与结论边界

| 维度 | 平均等级 | 得分 |
|---|---:|---:|
| A 理解与分解 | 2.75 | 10.3125 |
| B 功能与细节 | 3 | 15 |
| C 连接一致性 | 3.75 | 23.4375 |
| D 测试效果 | 2.75 | 13.75 |
| E GUI 使用 | 3.25 | 8.125 |
| F 恢复与交付 | 3.25 | 8.125 |

工程已评权重 100，确认分与区间均为 **78.75**，不归一化。24 子项、逐项理由、门槛及缺陷见 [quality.json](F:/CGKN-ITER-113/continuation-stage08/quality.json)；义务记录见 [obligations.json](F:/CGKN-ITER-113/continuation-stage08/obligations.json)。测试义务 PARTIAL，不能算 MUST 通过；G3 为 FAIL。G1/G2/G4/G5/G6 在本文注明的冻结环境和已测范围通过，不代表题外能力。

Q1–Q4 未做真人评分，保持 null / PENDING_HUMAN；不以媒体对齐数值填充领域质量，也不声称已完成最终真人可用性评审。[真人复核素材页](F:/CGKN-ITER-113/continuation-stage08/review/index.html) 提供原片与导出，页面只是验收材料，不是宿主替写的产品。

本轮是同一已公开反馈的工程 DEV 连续链，追加 2 个执行阶段，不是 2 个独立项目或新盲测；新增正式比较 0，新增 Direct 0，自主完整达标 0。没有可归因到 CGNK 架构的配对优势证据。每个达标交付成本不可定义，因为本轮没有达标交付。

历史计数更正：实际 `F:/CGKN-ITER-076/closeout-v8/matrix.json` 记录原 32 格已启动、开发结束，均记 NOT_DELIVERABLE（v7 4 格、v8 28 格），不是 32 格仍未运行。旧续作报告中的“0 启动/32 NOT_RUN”是过时描述；本轮保留旧文件并在此更正，未重新评审或覆盖历史成绩。该矩阵快照另存为 `continuation-stage08/historical-matrix-v8.json`。

## 停止、恢复与归档

原始停止和费用分别在 `dev-stage-08/dev-result.json`、`dev-stage-09/dev-result.json`、各自 resources.json 及既有 `F:/CGKN-ITER-076/global-provider-budget.json`。当前 1.28044 元不足以承接触发停止的完整请求保守预留；不会通过清零历史、删除未知费用或换便宜计价冒充可继续。

已准备 stage10 的本地校验入口，实际执行返回 `LOCAL_CONFIG_VALID; no paid calls`，没有启动 stage10：

```powershell
python -X utf8 -m experiments.product_dev_113.run_dev --stage 10 --freeze freeze-stage10-net114.json --authorization F:/CGKN-ITER-113/continuation-stage08/stage10-authorization.json --feedback F:/CGKN-ITER-113/continuation-stage08/stage10-feedback.json --transport-config F:/CGKN-ITER-114/transport-active.json --initial-snapshot F:/CGKN-ITER-113/dev-stage-09/frozen/candidate.zip --resources F:/CGKN-ITER-113/dev-stage-09/resources.json
```

这只是配置校验，不能解除费用准入阻塞。以后真正恢复须先有可满足请求预留的已授权预算或另版已验证预算策略，再增加 `--execute`。如果将本次验收失败用于下一轮，应明确登记为公开工程反馈；不能把接触这些结果后的续跑称为未暴露正式样本。当前恢复包没有偷偷加入私有失败分析。

本轮全部临时验收容器已关闭，工作区、原始轨迹、媒体和错误变体证据保留；NET114 专用 API 代理未操作。没有新的审批拒绝。宿主语义辅助和业务代修均为 0；机械阶段续接、只读取证、独立验收及探针修复均在 [interventions.json](F:/CGKN-ITER-113/continuation-stage08/interventions.json) 中单列。

按既有 Project Corpus 追加 `entry-iter113-cgnk-stage08-09`，关联 prior v7、NET114 和两个新阶段，类型 NON_ADDITIVE_CONTINUATION，状态 PARTIAL，不创建第二套历史库。收据与对象/索引校验在 `continuation-stage08/corpus-receipts.json`，最终哈希清单在 `continuation-stage08/evidence-seal.json`。本轮未修改框架代码，因此未重跑全仓框架回归；以上测试是最终候选及独立验收的真实执行结果。
