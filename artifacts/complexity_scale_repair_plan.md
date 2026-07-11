# Complexity Scale Repair Plan

## A. 必须立即修的 gate 问题

- 目标文件: `scripts/product_acceptance.py`
  - 修改点: 增加 同等复杂度结构检查，包括 planning 文件、orchestrator/stages、GUI/CLI shared imports、required artifact schema、traceability。
  - 为什么要改: 生成物缺关键结构时不能被判为可交付。
  - 对应测试: `tests/test_complexity_scale_benchmark.py` 或新增 focused acceptance tests。
  - 验收标准: 缺任一硬门槛时 verdict 不能 PASS。

- 目标文件: `scripts/post_build_finalize.py`
  - 修改点: requested screenshot、TEST_REPORT real command evidence、DELIVERY_NOTES、known gaps 的强制审查和记录。
  - 为什么要改: 交付证据缺失不能被包装成完成。
  - 对应测试: post-build finalization tests。
  - 验收标准: 缺截图或真实测试日志时 final promotion 被阻止或降级。

- 目标文件: `scripts/final_promotion.py` / `scripts/final_delivery_truth.py`
  - 修改点: 对用户明确要求的 `final_project_bundle.zip`、截图、run_dir、artifact contract 增加硬阻断。
  - 为什么要改: 防止 fake PASS 和候选包冒充最终交付。
  - 对应测试: final promotion/delivery truth tests。
  - 验收标准: 缺 final zip 或截图时不能 PASS。

## B. 应该加强的 product/team planning 问题

- 目标文件: `scripts/provider_generation.py`
  - 修改点: 将用户要求的 planning artifacts 和单主流程 contract 明确注入 provider prompt/checklist。
  - 为什么要改: 降低生成时退化为小 demo 的概率。
  - 对应测试: provider prompt construction regression。
  - 验收标准: prompt 中保留 product_brief、technical_plan、interaction_design、acceptance_matrix、orchestrator/stages、artifact schema。

- 目标文件: `scripts/run_local_pipeline_impl.py`
  - 修改点: 在 provider 生成后增加 bounded semantic review，针对 GUI/CLI shared core 和 stage artifact contract 给出 rework。
  - 为什么要改: 让错误在 candidate 阶段暴露，而不是等最终交付。
  - 对应测试: generated candidate semantic review tests。
  - 验收标准: 缺 shared core 或 required artifacts 时进入 rework/partial，而非 pass。

## C. 可以后置的质量提升问题

- 目标文件: `docs/04_acceptance_and_evidence.md`
  - 修改点: 增加复杂本地工作台项目的证据示例。
  - 为什么要改: 让后续 agent 更容易按证据而非声明验收。
  - 对应测试: docs contract guard if applicable。
  - 验收标准: 文档包含可执行证据清单，不引入新正式生成路线。

- 目标文件: `scripts/run_complexity_scale_workbench_benchmark.py`
  - 修改点: 后续可把人工 heuristic 提炼为更细的 structured validators。
  - 为什么要改: 提升 benchmark 诊断精度。
  - 对应测试: runner unit tests with synthetic project fixtures。
  - 验收标准: PASS/FAIL 均有路径证据且不会生成目标项目代码。
