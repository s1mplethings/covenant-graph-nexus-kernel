# ITER-113 v6：提高 token 上限后的真实续跑与验收

本次沿用 ITER-076 → ITER-113 的同一工程 DEV 链，不是新的正式样本。最终候选仍为 **NOT_DELIVERABLE / PENDING_HUMAN**：错误来源检查和 ASR 错误分类已修复，自有真实进程重开测试仍缺失。宿主没有修改候选业务代码或测试。

## 预算与停止

追加授权保留累计费用上限 187.98930 元，将 token 上限从 100 万提高至 600 万；不重置请求、费用或时间。续跑开始余额 79.20282 元，新增 15 次请求、保守费用 4.90212 元，余额 **74.30070 元**。账本累计 113.68860 元，实际供应商账单未查询，未知用量保留上界。

当前链累计 80 次请求、1,162,483 token（含未知预留）、795.999 秒开发时间。停止原始错误为 `RUN_RESOURCE_LIMIT`，本次命中仍有效的 80 次累计请求保护；不是 token 限制或预算预留。用户本次仅提高 token 上限，未擅自重置请求计数。

实际返回身份包括 `deepseek-flash`、`grok-4.7`；一次 DeepSeek 连接失败保留费用预留，按既定有限规则切换 Grok。模型的一次工作器输出格式失败没有被宿主改写；模型随后自行通过隔离命令修改业务文件。业务变更仅 `app.py`，测试与 README 没有修改。

## 独立验收

- 正常候选：14 项自有测试通过，24.26 秒。
- GUI 真实导入、ASR、检索定位、播放、7–12.5 秒裁剪、实际导出通过；独立解码、来源画面与声音对齐通过。三帧 MAE 为 0.965、0.791、0.773；声音包络相关性 0.999991。
- 错误来源变体：有效红色视频、正确 1 秒时长，被新增来源检查拒绝；两个导出测试失败，另 12 项通过。错误时长和不可解码变体同样被拒绝。
- 真实 ASR 执行退出 23、畸形 JSON 均证明注入命中，分别持久化 `exec_failure`、`parse_failure`，GUI 显示不同原因；解除依赖故障后新上传成功，原失败记录保留。
- 独立实际关闭并重开应用和浏览器后，数据库、文件及下载哈希一致，GUI 可再次检索。**这不能代替被测系统自己交付真实重开测试**；其测试文件与前序逐字节相同，该 MUST 仍失败。
- 空输入、损坏视频、非法裁剪、同名归档与无音轨输入已通过 GUI 复验。人类领域质量审查仍未完成。

24 项评分见 `F:/CGKN-ITER-113/continuation-v6/quality.json`：工程 74.0625 分，D 均值 2.25，未达到门槛；G3 失败、G6 部分完成。领域质量未评，不归一化或冒充人工完成。本次反馈已明确公开，修复属于已知缺陷回归，不能宣称新的盲测成功。

验收首轮错误变体装配缺少可写运行数据目录，14 项均在导入阶段报只读错误。该轮标 `EVALUATOR_INVALID`，原记录保留在 `mutations-v6`。仅修正隔离验收副本挂载后，在 `mutations-v6b` 重跑正常控制和全部变体；未修改原候选。

## 版本与证据

- 新授权：`F:/CGKN-ITER-113/continuation-v6/authorization.json`
- 冻结配置：`F:/CGKN-ITER-113/packet-v1/freeze-v6.json`
- 原始开发：`F:/CGKN-ITER-113/dev-stage-05/`
- 冻结候选：`F:/CGKN-ITER-113/dev-stage-05/frozen/candidate.zip`
- GUI/重开/媒体：`F:/CGKN-ITER-113/acceptance-v6/`
- ASR 故障：`F:/CGKN-ITER-113/asr-exit-v6/`、`asr-parse-v6/`
- 汇总、逐项记录、干预账目和 Corpus 回执：`F:/CGKN-ITER-113/continuation-v6/`

旧封板 2,421 个文件核验无变化。新框架相关回归 19 passed，无付费测试。新配置只增加通用授权参数和可配置 token 上限，不改隔离工具权限、调度架构或交付路线。验收在开发终止并冻结候选之后运行，新私有结果未回流给该运行。验收容器均已关闭。

正式启动/完成均为 0；原 32 格仍 NOT_RUN，不记为 32 次失败。本次没有 Direct 对照或架构胜负证据。

## 恢复

零费用复核已有记录无需新授权。若继续付费开发，唯一当前资源门槛是明确提高这条连续 DEV 的累计请求上限，保留当前 80 次计数和 74.30070 元余额；不能靠另起 run_id 清零。之后建立新授权/配置版本，再由 CGNK 自己补齐真实重开测试。当前恢复 CLI 支持 `--authorization`，下一阶段为 `--stage 6`，初始候选自动取 stage 05；新版本冻结及公开反馈必须先落盘，不能直接重用 v6 启动额外调用。

本次实际执行命令：

```powershell
python -X utf8 -m experiments.product_dev_113.run_dev --execute --stage 5 --freeze freeze-v6.json --authorization F:/CGKN-ITER-113/continuation-v6/authorization.json --feedback F:/CGKN-ITER-113/continuation-v6/public-feedback.json
python -X utf8 F:/CGKN-ITER-113/continuation-v6/mutation_checks_v6b.py
```

第一条是历史复现记录，已有目录会拒绝覆盖；第二条会写验收结果，复跑需先分配新的输出版本，不覆盖现有证据。
