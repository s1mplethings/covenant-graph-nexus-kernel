# ITER-088：批准后的一对真实产品 DEV

在本轮冻结题包、版本与预算下，两条路线都未形成自主可交付产品：**0/2 达标、2/2 NOT_DELIVERABLE**。这是新的视频 DEV 对，不是正式矩阵重跑。旧 ITER-076 的 32 次正式运行及原始证据保持不变。

| 路线 | 实际模型 | 调用 | 保守费用（元） | 开发终止 | 独立验收 |
|---|---|---:|---:|---|---|
| R_DIRECT | qwen3.8-max | 15 | 3.15574 | 模型以前台方式启动服务，指定 3 秒超时，容器按冻结规则终止 | 新增 app.py 业务实现，但首页 HTTP 500，重启后仍失败 |
| R_CGNK | qwen3.8-max | 2 | 0.10132 | 第二次决策同时 retry 三个节点，违反单次最多一个的契约 | 候选逐文件与初始快照相同；只有原始归档功能 |

本对新增保守计费 **3.25706 元**，此前 47.83242 元，累计 **51.08948 元**、450 次 Provider 调用。用户批准的是本对每路线最多 20.80 元、累计上限 89.43242 元；剩余上限 38.34294 元不自动授权新增运行。没有为验收调用付费模型。费用为忽略缓存优惠的保守费率账目，不是实际账单。历史五次缺失 token 用量继续保留上界，不能声称累计 actual usage 完整。

## 冻结起点与责任

- 当前 HEAD `0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`；本地状态契约补丁已在此前离线阶段封存，不将 HEAD 单独冒充本轮全部源码。
- 本轮配置 seal 以机器记录 `paid-closeout-v1/summary.json` 的 `source_freeze_sha256` 为准确索引；原封板及报告修正版本均保留。
- 题包 `F:/CGKN-ITER-088/dev-packet`，授权单独保存在 `authorization.json`；原 false 提案不被覆盖。
- Source Cabinet 初始实现仅含文件归档、预览、下载、SQLite 身份保存。新增责任是 GUI 导入真实视频、实际离线 ASR、检索定位播放、选择边界导出和重开持久化；不能把初始归档功能计作模型新增能力。
- 使用已冻结的 JFK 公开领域真实演讲新 30 秒区间（180–210 秒）。这是已知来源/产品家族的新场景，不是独立项目泛化。
- 两条路线实际都只调用 qwen3.8-max。CGNK 配置中允许的 worker 本次未被调用；不能声称完成了 Agent→worker 产品交付链路。

## 实际执行与失败证据

Direct 自行读题和探索、写入 app.py、自行纠正将 `cd` 当可执行程序的错误，随后成功执行 `import app`。这只是导入烟雾检查，没有覆盖真实业务终态。它最后发出 `python /workspace/app.py`，超时设为 3 秒。工具生命周期公开说明已明确要求长期服务自行后台化，并声明超时会终止整个容器。原 runner 标签是 BLOCKED_ENV；本报告保留原标签，另将原因归为模型工具生命周期误用，**不是基础设施不可用**。

冻结后按原 README 在独立受限验收副本启动服务。浏览器首页实际显示 Internal Server Error。服务日志为 `sqlite3.OperationalError: ambiguous column name: rowid`，发生在 app.py 的转录查询。重启应用和浏览器后仍相同。没有修改 SQL、绕过 GUI 调接口、手工生成转录或导出。后续媒体、检索、边界与恢复义务因入口失败未能执行；这些是 BLOCKED_DEP/UNTESTED，不伪造成功，也不全部打零。

CGNK 首次决策创建三个读取节点但缺 executor_ref；反馈后第二次决策发出三个 retry_node，且没有实际配置更新。校验器报 `one Agent decision may retry at most one node`，开发结束。新状态图增量提交修复**没有在这次真实运行得到成功路径验证**，也没有重现原节点集合不一致错误；不能以此宣称所有 Agent 状态问题已解决。

CGNK 候选逐文件与初始快照一致。独立 GUI 可上传 scenario.mp4，重启后仍列出原始文本和视频；只读数据库及文件哈希证明保存的视频与输入一致。这只验证脚手架已有归档能力。没有转录、搜索定位或裁剪导出入口与实现，没有模型新增业务代码或测试。

## 评分、门槛与未评项

完整 24 子项、11 条公开 MUST、G1–G6、领域质量占位及逐项证据在 `paid-closeout-v1/direct-acceptance.json` 和 `cgnk-acceptance.json`。

按同一根因只在主要评分项扣分：Direct 的首页不可用主要归 F3=0；CGNK 的新增业务缺失主要归 B1=0。两者 D1=0：未交付新写或有效复用的目标业务测试；依据不是测试文件数量。无有效候选测试可供业务错误变体检验，D3 保持未评。宿主验收不是被测测试。

| 路线 | 已确认分 | 已评权重 | 待评权重 | 完整总分可能区间 |
|---|---:|---:|---:|---:|
| Direct | 0 | 7.5 | 92.5 | 0–92.5 |
| CGNK | 0 | 10 | 90 | 0–90 |

这些区间不是已完成总分。已有必要条件失败足以判两者 NOT_DELIVERABLE；其余分数没有必要靠猜测补满。G2/G3/G5 未满足；没有真实转录/导出结果供 Q1–Q4 评审，领域质量为 UNTESTED / NO_CANDIDATE_DOMAIN_OUTPUT，真人确认仍 PENDING_HUMAN。没有宣传平台测试，本次仅授权视频 DEV 对。

## 隔离与宿主行为

两路线均由正式共用 runner 注册受限工具，经同一 ContainerBoundary 在冻结媒体镜像中执行；audit.jsonl 保留真实容器 ID、挂载、镜像、原始参数、输出及哈希链。模型没有宿主 CommandExecutor、Docker 控制面、私人连接器或 oracle 权限。开发容器均已终止，候选通过只读独立快照冻结。

独立验收在新的应用/浏览器容器进行，只挂候选副本与公开输入；验收日志和私有题包不挂入候选。浏览器操作、重启、只读数据库取证和关闭轨迹均保存。截图已实际查看。宿主未代修业务代码、测试或数据库，未提供语义提示，未回传私有验收结果，未调用强模型救援。开发审计哈希链复核通过；关键审计缺口 0，语义辅助 0，污染 0。

## 历史、复现与下一步

旧正式矩阵仍为：32 计划格、32 启动、32 结束、32 NOT_DELIVERABLE、0 NOT_RUN；首次主表、CREATE、重复与 SELF_EVOLVE 的旧记录不变。此前并非“32 个未运行”；不能把新 DEV 混成正式补跑。旧 v7/v8 配置不同，仍不能合并成 32 个独立项目。本次没有新的 SELF_EVOLVE，原始脚手架不能作为已交付新流程的演进成功起点。

原开发命令已经执行，**不要原样再执行以购买额外重试**：

```powershell
python -m experiments.diagnostic_088.run_pair --packet F:\CGKN-ITER-088\dev-packet --authorization F:\CGKN-ITER-088\authorization.json --execute
```

无付费独立复核可选择一个尚不存在的目录（以下固定目录若已存在，须换新目录，不能覆盖证据）：

```powershell
python experiments/product_eval_076_v8/inspect_candidate.py --root F:\CGKN-ITER-088\recheck-direct-v1 setup --snapshot F:\CGKN-ITER-088\dev-pair-v1\dev088-video-direct\frozen\candidate.zip --public F:\CGKN-ITER-088\dev-packet\public --argv '["python","/workspace/app.py"]'
python experiments/product_eval_076_v8/inspection_action.py --root F:\CGKN-ITER-088\recheck-direct-v1 --url http://127.0.0.1:5000 --screenshot home.png
python experiments/product_eval_076_v8/inspect_candidate.py --root F:\CGKN-ITER-088\recheck-direct-v1 close
```

最小有价值的后续工作是对已有原始响应做零费用契约反馈/生命周期诊断，并验证不改变业务语义的通用行为；任何执行策略修改须另立版本、重做受影响验证，再决定是否授权新的一对 DEV。不能用现有私有失败提示让本对恢复为自主成功。本次批准的一对真实调用、冻结、独立检查和归档已完成；没有因为预算预留而停。

此前 65 passed、0 skipped 是状态/预算/隔离相关基础设施回归，本次未改运行源码，不重复消耗运行；它们不是上述产品成绩。本次另验证两条审计链、候选哈希、费用账本、GUI/重启/保存轨迹与 Corpus 记录。没有推送、合并或发布。
