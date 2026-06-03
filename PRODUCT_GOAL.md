# CGNK Product Goal

CGNK 的目标是让用户只提供项目目标、输入、输出和约束，就能进入一个完整的自动项目交付流程。

CGNK 不是只生成代码。它是一个 **Autonomous Project Studio Kernel**：系统必须自动组织虚拟项目团队，完成产品故事、MVP 范围、技术方案、实现计划、测试证据和交付包。

CGNK 是 agent 主控、契约护航的自动项目工作室。

Lead Agent 可以按需求创建不同虚拟角色和不同管线，但必须留下 artifact、通过契约检查、产出测试证据和交付包。

## Target Workflow

```text
用户提供目标、输入、输出和约束
  -> customer_intent 固化用户意图
  -> output_contract 固化最终交付格式
  -> 自动生成 virtual_team_roster
  -> Product Lead 生成 product_story 和 mvp_scope
  -> Solution Architect 生成 technical_plan
  -> UX / Delivery 定义界面路径和视觉证据要求
  -> 本地 librarian 理解当前 CGNK 模块库
  -> agent / pipeline composer 拼接可执行管线
  -> contract compiler 检查模块、端口、artifact、policy 和 gate
  -> agent build 生成项目文件
  -> environment runner 尝试启动项目
  -> QA 生成测试数据并输出 test_report
  -> evidence capturer 输出截图，必要时输出视频或 GIF
  -> delivery manager 打包项目、README、测试结果、证据和 known_limits
  -> 用户可以继续提出修改
```

## User Rule

普通用户不需要自己设计完整产品路径，也不需要自己研究技术栈、环境配置或测试方式。

用户只需要尽量说明：

- 想做什么
- 输入是什么
- 输出是什么
- 需要什么界面或格式
- 有哪些限制

如果信息不足，CGNK 可以使用保守默认值继续，但必须把默认假设写进 artifact。

## Virtual Team Rule

CGNK 必须根据项目类型自动创建虚拟团队。

默认角色包括：

- Product Lead
- Solution Architect
- UX Designer
- Implementation Engineer
- QA Engineer
- Delivery Manager

虚拟团队不是展示文案。每个角色都必须拥有明确 artifact，例如：

- `product_story`
- `mvp_scope`
- `technical_plan`
- `build_plan`
- `test_plan`
- `test_evidence`
- `delivery_bundle`

## Generation Rule

CGNK 必须通过模块契约拼管线，不允许把所有逻辑硬连成一条不可解释的脚本。

Lead Agent 主控执行路线。Layer 是工作区和交接边界，不是替代 agent 规划的固定硬编码流程。

最终生成流程必须至少保留：

- `customer_intent`
- `output_contract`
- `virtual_team_roster`
- `product_story`
- `mvp_scope`
- `technical_plan`
- `build_plan`
- `pipeline_composition`
- `compiled_contract_bundle`
- `generated_project`
- `test_data`
- `test_report`
- `visual_evidence`
- `delivery_bundle`

## Acceptance Rule

一次交付不能只因为代码文件存在就标记成功。

PASS 交付必须至少包含：

- 可运行项目或明确的启动路径
- README 或启动说明
- 测试数据
- 测试报告
- GUI 或可视化项目的截图证据
- 项目包或源码包
- 已知限制
- 可继续修改的 revision entry

如果项目不能启动，不能标记 PASS。

如果没有测试数据，不能标记 PASS。

如果 GUI 项目没有截图或视觉证据，不能标记 PASS。

如果没有交付包，不能标记 PASS。

## Agent Rule

Agent 是主要实现者，但不能自己重新定义成功标准。

Agent 必须受以下 artifact 约束：

- `output_contract`
- `product_story`
- `mvp_scope`
- `technical_plan`
- `acceptance_matrix`
- `test_evidence`
- `delivery_bundle`

Agent 可以生成代码、修复错误、补测试、补 README 和补交付说明，但不能跳过故事层、测试证据或交付包。

## External Rule

API/provider 可以接入，但必须显式批准。默认本地生成，不隐式调用网络或 provider。
