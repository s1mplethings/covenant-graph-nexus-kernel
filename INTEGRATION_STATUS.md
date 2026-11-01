# 未通过回归 / REGRESSION FAILED — DO NOT MERGE

本分支仅用于保存和审阅 2026-11-01 的 LeanLoop/main 合并候选，**不是可部署版本，不要合并 main**。

- 主线基线：`1f8425dbba7c7b44d4273e25b2db20be6f8bd4f5`。
- 原特性分支：`codex/leanloop-selfcheck-20261101`，`61f525520273cf45ea833bcce01656313c2aaed5`。
- 同一组 178 项测试：主线 177 通过、0 失败、1 跳过；候选 156 通过、21 失败、1 跳过。
- 候选较广定向回归：312 通过、21 失败、1 跳过；完整回归未完成。
- 19 个失败来自 Blueprint 与强制 ExecutionLeafContract/独立检查器不兼容；2 个来自 Provider 截断错误与 request_id 证据兼容性。

[完整测试报告](evidence/leanloop-main-integration-20261101/REPORT.md) · [机器可读失败清单](evidence/leanloop-main-integration-20261101/regression-verdict.json)

报告中的“未提交、未推送”描述的是之前拒绝合入 main 时的历史状态。本次按用户后续指示只发布独立审阅分支；原始失败证据原样保留。发布用 TestReceipt 的 PASS 仅代表文件/证据完整性、发布器测试及版本/产品方向检查通过，**绝不代表功能回归通过**。不更改失败用例、不放宽校验、不向 main 推送。

候选源代码直接包含在本分支。原本地补丁与 zip 覆盖包不重复提交；原 artifacts 缓存、字节码和本地发布回执不上传。各定向测试的 JUnit、输出及执行元数据已归档到 evidence；全量基线中止原因也保留。
