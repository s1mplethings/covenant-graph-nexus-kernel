# ITER-116 V3 — 通用反馈、任务评价与事件并发续作

本轮沿用 GOAL-STAGE-ACV-V3.0。旧视频 stage16 保持冻结，没有启动 stage17、Direct 或旧 32 格。宿主只修改框架、测试夹具和独立验收入口，没有编写候选业务实现。

## 已落地的调用链

AgentComposer → AgentProjectLoop → 原 DAGRunner → 已注册 Executor → FileRunStore 原始回执 → TaskFeedback → 下一次 Agent 请求。已有 GoalAcceptance 仍是目标验收依据；任务执行成功、模型评价和候选经验都不能自行提升为验收通过。

- 原 DAGRunner 改为完成事件驱动；A/B 并行时，依赖 A 的 C 不必等 B。受信执行器的工作区资源声明控制共享写冲突。
- 终态任务及时形成事实反馈；相关失败与已批准公共知识进入真实规划、Worker 请求。评价经 task.evaluate@1 进入原执行器注册表，保存修订和既有知识格式的候选经验，不另建知识库。
- 评价不递归评价自身；重复提交幂等，冲突修订拒绝；未知评价请求不盲目重发。候选经验仍需原知识流程认可，不能直接污染正式知识。
- 具体模型 ID 与 Provider 别名分离，Gateway 验证已取得的模型清单，记录请求和返回身份。同 Provider 两具体模型的重叠调用已通过受控上游测试；不称真实模型并行。
- run 协调锁、不可变回执和中断恢复防止盲目重复副作用；取消保留迟到结果与 usage，不把取消请求等同远端已终止。
- 已有 GoalAcceptance 与任务回执显式关联后才统计受检属性贡献。新失败覆盖旧成功贡献，迟到旧检查不能恢复为绿。

实现说明：D:/CGKN/docs/task_feedback_parallel.md。

## 环境与实际运行

Docker 29.9.2 已恢复。已运行两个隔离工作区的合法读写、只读输入拒绝、宿主合成 canary 不可见、子进程、SQLite 持久化和重开复用；4 个 DAG 节点成功，resume 无新增执行，两份审计各 10 条。此项 HARNESS_CONFORMANCE_ONLY，不是产品成绩。原 v1 探针因只捕获 PermissionError、漏掉 errno 30 而失败，保留为 EVALUATOR_INVALID；v2 修正异常类别后通过。没有 GUI 成绩。

API 状态不能简单写为全部恢复：现有默认 Gateway 的认证 models GET 曾返回 200；新启动的本轮独立 Gateway 对 Qwen/DeepSeek 返回 503/TCP_CONNECT_FAILED，submitted=false。进一步诊断：配置 DNS 119.29.29.29、182.254.116.116 的 UDP 回包触发 DNS_NON_PUBLIC_ANSWER_REFUSED，TCP 查询超时。尚未确认是哪一网络组件改写回答；没有关闭非公网地址拒绝、TLS 或物理网卡绑定。

实际入口两次 preflight 均在任何生成前终止：
`RuntimeError: REAL_NETWORK_OR_MODEL_INVENTORY_BLOCKED; no generation sent`

真实 CGNK 开发启动 0 次；主规划、Worker、真实模型评价均 0 次；没有本轮业务候选或黑盒产品通过成绩。独立订单导入验收器已准备但未运行，不能算验收器可解性或产品正确性证明。G8 未满足。

## 证据与历史保护

证据根 F:/CGKN-ITER-116：authorization.json、baseline/、resume-baseline/、ledger-start.json、ledger-end.json、container-conformance-v1/与v2/、real-preflight-01/与02/、dns-diagnostic.json、final-validation-v1/与v2/。

源码分组验证使用哈希冻结；v2 还保存完整被测 Python 文件副本。测试是两个独立 OS 进程，分别具有 tmp、缓存、日志目录；v1 默认 pytest progress 曾写共享非权威观测文件，v2 显式关闭。测试结果从各组独立日志取证，不使用共享进度作为结果。

首轮：core 102 passed/1 failed，providers 117 passed/4 failed。修复审计 requested_model 重复关键字这一框架缺陷；旧路由测试补全显式网络状态与未发送异常；UTF-8 测试读取显式指定编码；实际模型断言改为真实返回身份并检查 mismatch。保留首轮全部证据。

产品方向 gate 仍 FAIL：obsolete_active_path:benchmarks/orbit_360_workbench 与 benchmarks/project_generation_v1。未删除这些既有目录来消除门禁。不是候选业务失败。

本轮新增付费生成 0 次、账本新增估计 0 元；旧全链估计 382.65018 元、1335 条调用，actual_token_usage_complete=false，不能宣称精确实际账单。首尾账本 SHA 相同。认证 GET 无生成；宿主计算和 Codex 使用不算完全零成本。授权为本范围 accounting_only，没有金额停止门槛。

## 尚未证明与恢复

G1 现场/路线明确；G2–G6 已有通用机制与离线/本地证据，但真实学习复用与多模型产物见证仍未证明。G7 见 v2 分组结果，不能冒称全仓全量回归。G8 BLOCKED_ENV；G9 本轮归档关联见 Corpus 回执。

下一必要环境条件：在新进程、本轮保存的物理网卡与 DNS 政策下，两个获准 API 的认证 models GET 成功且返回模型清单。现有缓存进程成功不能代替。恢复不要求新增费用授权，也不改用宿主直连绕过路线。

只重启本轮 Gateway（不要停止用户默认 Gateway），随后复验：
```powershell
Set-Location D:/CGKN
python -m scripts.domestic_gateway stop --state-dir F:/CGKN-ITER-116/gateway-private
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
powershell -NoProfile -File F:/CGKN-ITER-116/resume.ps1 -PreflightOnly
exit $LASTEXITCODE
```
通过后去掉 `-PreflightOnly` 运行真实任务和独立业务检查。resume.ps1 每次使用新目录，保留所有旧记录并传播退出码；它不是已付费中断请求的盲目重放器。真实模型并发、任务评价及其影响仍需独立检查原始调用轨迹，业务检查通过不能代替这些见证。

回滚只能按 baseline/resume-baseline 对本轮明确修改逐项审查；不得覆盖后来用户修改、reset 或清理整个工作区。未推送、未提交、未购买资源或对外发布。

## 最终相关回归

v2：core 103 passed（150.10 秒）；providers 121 passed（152.22 秒），合计这两个不重叠组 224 passed，无跳过，源码哈希复验一致。两组并行运行；此前针对性测试不重复相加。保留 pathlib.is_reserved 的弃用警告，未抑制成无警告报告。

Corpus 已追加 `entry-iter116-feedback-parallel-v2`，沿用原 schema 的 `BLOCKED_ENVIRONMENT`；manifest、对象哈希及 SQLite 索引核验通过，仅证明此条归档有效。初次使用不受支持的 BLOCKED_ENV 被 schema 拒绝且未生成 manifest，纠正映射后追加成功，过程见 corpus-registration-history.txt。本轮专用 Gateway 已发送停止请求，未停止默认 Gateway。
