# CGNK Product Goal

CGNK 的目标是让用户只给出一句项目需求，就能进入一个完整的本地项目生成流程。

## Target Workflow

```text
用户在真实 Telegram 里发送一句话需求
  -> Telegram 客服模块理解需求
  -> 客服提出必要澄清问题
  -> 需求蓝图生成器分析 requirement_spec、io_contract、gap、feature、capability、tech_decision
  -> 本地 librarian 理解当前 CGNK 模块库
  -> 本地 agent 自动拼接可执行管线
  -> 对抗审查检查缺口和风险
  -> 本地执行器生成项目
  -> 输出项目文件
  -> 输出项目蓝图
  -> 输出生成过程
  -> 输出测试图
  -> 输出效果报告
```

## Customer Service Rule

客服只通过真实 Telegram 和用户交流。客服不直接暴露内部模块名给普通用户。它负责把用户需求整理成可执行信息：

- 项目类型
- 目标用户
- 核心功能
- 数据保存方式
- 交付方式
- 测试验收点

客服采用“主动形成方案”的策略：先理解目标，给出第一版产品/技术方案和默认假设，只在真正阻塞生成时提问。可默认项不阻塞生成，例如输出格式、剪辑时长、通用适配范围和预览方式。信息足够时，客服可以自然说明将开始生成第一版，不要求用户输入固定口令。

所有用户可见话术都由 API/provider 或已批准的模型生成，包括开场、澄清、状态、交付、失败说明和测试说明。代码只能提供事实、状态和约束，不写固定客服模板；如果模型不可用，流程只能返回最小技术错误，不切换成本地话术模板。

生成完成后的 Telegram 交付必须像结果展示，不像 CI 日志：说明本次生成的能力、测试结果、可检查路径、预览/截图/视频是否产出，以及下一步建议。

客服行为策略从 `config/customer_agent_policy.md` 热加载。后台每轮对话读取该文件，因此策略可以微调，例如调整主动程度、默认假设、追问严格度、自动生成门槛和交付展示方式。

## Generation Rule

CGNK 必须通过模块契约拼管线，不允许把所有逻辑硬连成一条不可解释的脚本。最终生成流程需要保留：

- `pipeline_composition`
- `requirement_blueprint`
- `project_blueprint`
- `generation_trace`
- `test_graph`
- `effect_report`
- `runtime_result`

## External Rule

项目文件必须由 API/provider 自主生成。允许联网检索、库选择、蓝图设计和测试验证；如果 provider 没有产出合格项目，流程直接失败，不切换到本地通用模板。
