# CGNK main 安全合并资格报告

结论：REJECTED_FOR_MAIN_PUBLICATION。合并工作尚未完成；候选未达到回归门禁，未暂存、未提交、未推送，GitHub main 未改变。此报告不是成功合并凭证。

## 输入与隔离

- 主线基线：`1f8425dbba7c7b44d4273e25b2db20be6f8bd4f5`。
- 待合并分支：`codex/leanloop-selfcheck-20261101`，提交 `61f525520273cf45ea833bcce01656313c2aaed5`。
- 特性提交父版本：`0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`。
- 独立候选工作树：`F:/CGKN-LeanLoop-Main-Integration-20261101`，分支 `codex/leanloop-main-integration-20261101`。
- 独立主线基线：`F:/CGKN-Main-Baseline-20261101`。
- 原工作树 `D:/CGKN` 与既有特性工作树未被覆盖。

真正共同祖先合并涉及 974 个文件、101 个冲突，并带入特性分支继承的旧历史。为避免旧实现倒灌，调查采用特性提交实际 269 文件差异，使用显式父版本执行三方 squash 候选构造。`git merge-tree --write-tree` 仅生成 Git 对象，候选文件写入工作区，没有使用 Git staging/commit/push 绕过 canonical publisher。

## 已做的冲突处理

主线 rc.5 产品权威、当前架构与项目管理状态保持主线版本。主线已拆分的知识 store/persistence/projection 实现保留，没有用旧单体 store 覆盖。ProjectBlueprint、MinimalProjectLoop、Project Corpus 源码保留，文件核对见 `protected-main-files.json`。

Provider 配置兼容 thinking/deadline、模型身份等字段；保留 GenerationRequest/GenerationClient 与主线结构化选择器；合并 MCP Conversation 和 streaming 工具入口；发布分类保留主线 research/root-doc/package 支持。候选 Python 语法解析通过，冲突标记已消除。这些只是文本和接口层面的工作，不能证明功能合并成功。

## 完成的离线实验

所有实验使用同一 Python、禁用第三方 pytest 自动插件、离线 legacy 配置与 Python 非本机 socket 拦截；无真实付费 API 请求。此拦截不是操作系统网络沙箱。

| 实验 | 通过 | 失败 | 跳过 |
| --- | ---: | ---: | ---: |
| 主线定向基线 | 177 | 0 | 1 |
| 候选中完全相同的 178 个测试 ID | 156 | 21 | 1 |
| 候选较广定向回归 | 312 | 21 | 1 |
| 候选关键子集复核 | 88 | 2 | 1 |

21 个新增失败全部在主线相同测试 ID 上通过。详见 `regression-verdict.json` 和各目录 JUnit XML、日志、start/completion JSON。Project Corpus 独立模块和知识持久化子集通过，但 Blueprint 驱动的 Corpus 捕获集成随主流程失败，不能据此宣称完整 Corpus 链路无回归。

全量主线回归启动后，在取得明确的同测试对照新增回归证据时主动终止；完整回归没有完成。终止不计为主线测试失败。只终止了记录 PID、创建时间、工作目录均匹配的本任务 pytest 进程；清理记录见 `baseline-full/cancellation.json`。此前 watchdog 问题在本轮没有形成新的结论。

## 阻止发布的实际问题

1. **19 个 Blueprint 主流程回归**：分支的 `compile_tree` 强制校验 ExecutionLeafContract；主线 `compile_blueprint` 生成的节点并不提供该契约，主线 `MinimalProjectLoop` 注册的 DAGRunner 也没有分支新要求的 deliverable checkers。首次调用就报 `INVALID_CONTRACT:core:ExecutionLeafContract required`。新建项目、定向修复、验收归因、Corpus 失败修复捕获均受影响。
2. **2 个 Provider 兼容回归**：截断响应错误类别从主线 `PROVIDER_OUTPUT_TRUNCATED` 变为 `truncated_response`；失败证据遗漏主线要求的 `request_id`。文本合并保留的选择器尚未完成与 streaming 错误/证据语义的一致整合。

这不是可通过选择 ours/theirs 消除的冲突。继续合并需要显式迁移 Blueprint 到共同叶节点/独立验收契约，并验证修复时的下游复用、稳定快照、无写入增量复用、检查器证据和失败归因。不能关闭契约校验、引入第二个运行器、删除主线测试或把执行成功当验收通过来消除失败。Provider 必须保持既有错误证据语义，同时保留 UNKNOWN、预算和不自动重放的约束。

## 可审阅产物与发布状态

- `resolution-inventory.json`：269 文件逐项处置和候选 SHA-256。
- `tracked-candidate.patch`：相对当前 main 的已跟踪文件候选补丁。
- `candidate-overlay-NOT-QUALIFIED.zip`：包含新增文件的完整候选覆盖包，未通过资格，不应直接用于主线部署。
- `protected-main-files.json`：主线核心文件保留核对。
- `regression-verdict.json`：精确匹配测试结果、新增失败 ID、远端 main SHA、空 staging 验证。
- `evidence-hashes.json`：本轮产物哈希。

未生成 PASS TestReceipt，也未调用 canonical publisher 发布。远端 main SHA 再次读取仍为输入主线基线。保留候选用于后续语义迁移；不得把这份候选称作已经安全合并或已完成架构瘦身。
