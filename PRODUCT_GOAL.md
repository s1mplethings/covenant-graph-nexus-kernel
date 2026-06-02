# CGNK Product Goal

CGNK 的目标是让用户只给出一句项目需求，就能进入一个完整的本地项目生成流程。

## Target Workflow

```text
用户一句话需求
  -> 客服模块理解需求
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

客服不直接暴露内部模块名给普通用户。它负责把用户需求整理成可执行信息：

- 项目类型
- 目标用户
- 核心功能
- 数据保存方式
- 交付方式
- 测试验收点

如果信息不足，客服先问真正阻塞的问题；如果运行在非交互模式，可以使用保守默认值继续生成，并把默认值写进报告。

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

API/provider 可以接入，但必须显式批准。默认本地生成，不隐式调用网络或 provider。
