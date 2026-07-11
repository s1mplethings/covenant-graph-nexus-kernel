---
kind: ProjectMemoryMarkdown
schema_version: 1
chat_id: local-ai-knowledge-studio-real
flow_ref: flow.modular_project_generation@1
policy_ref: policy.safe_modular_project_generation@1
contract_pack: agent_context.modular_project_generation.contract_pack.json
artifact_ref: artifact.project_memory_markdown@1
generated_at: 2026-07-07T07:31:22.826460+00:00
revision_count: 3
---

# Project Memory

这份文档是 Telegram 项目的长期可维护规格。后续修改必须先更新这里，再传给模块化生成后台。

## Modular Contract Binding

- Contract pack: `agent_context.modular_project_generation.contract_pack.json`
- Flow: `flow.modular_project_generation@1`
- Policy: `policy.safe_modular_project_generation@1`
- JSON artifact mirror: `D:\CGKN\examples\project_memory\local-ai-knowledge-studio-real\project_memory.artifact.json`

## Current Project Summary

Local AI Knowledge Studio 做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层。 必须功能： 1. 本地资料导入：支持 markdown / txt / pdf 占位解析接口，登记资料来源、标签、状态。 2. 知识库：文档列表、标签筛选、关键词搜索、文档详情。 3. AI / 模型适配层：本地模型配置入口，模型路径或 endpoint 配置，summ

## Known Facts

- 用户提出的新项目需求: Local AI Knowledge Studio

做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层。

必须功能：
1. 本地资料导入：支持 markdown / txt / pdf 占位解析接口，登记资料来源、标签、状态。
2. 知识库：文档列表、标签筛选、关键词搜索、文档详情。
3. AI / 模型适配层：本地模型配置入口，模型路径或 endpoint 配置，summarizer / retriever adapter；缺少本地模型时不能假装真实推理通过；mock adapter 必须标为 mock。
4. 任务和项目管理：从资料生成任务，todo / doing / done，优先级，负责人或备注，简单看板或列表。
5. 报告生成：选择资料和任务，生成本地 markdown 报告，记录输入来源和限制说明。
6. UI：Dashboard、Documents、Search、Tasks、Reports、Settings / Model Config。
7. 本地数据：SQLite 或 JSON store，示例数据，可重启后保持状态，至少有持久化设计。
8. 交付：README、启动命令、测试命令、TEST_REPORT.md、screenshots、final_project_bundle.zip。
- 识别出的核心能力：内容生成能力；本地模型后端；导入导出和格式互操作；数据抽取和理解；安全、权限和数据边界；检索、搜索和知识库
- 用户项目需求: Local AI Knowledge Studio

做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层。

必须功能：
1. 本地资料导入：支持 markdown / txt / pdf 占位解析接口，登记资料来源、标签、状态。
2. 知识库：文档列表、标签筛选、关键词搜索、文档详情。
3. AI / 模型适配层：本地模型配置入口，模型路径或 endpoint 配置，summarizer / retriever adapter；缺少本地模型时不能假装真实推理通过；mock adapter 必须标为 mock。
4. 任务和项目管理：从资料生成任务，todo / doing / done，优先级，负责人或备注，简单看板或列表。
5. 报告生成：选择资料和任务，生成本地 markdown 报告，记录输入来源和限制说明。
6. UI：Dashboard、Documents、Search、Tasks、Reports、Settings / Model Config。
7. 本地数据：SQLite 或 JSON store，示例数据，可重启后保持状态，至少有持久化设计。
8. 交付：README、启动命令、测试命令、TEST_REPORT.md、screenshots、final_project_bundle.zip。

## User Rules

- 未记录

## Default Assumptions

- 生成类核心能力必须有明确模型/API/本地后端/专用引擎能力检查；占位或降级预览不能冒充真实生成。
- 用户要求本地模型时，外部模型只能作为备选说明，不能算满足本地模型验收。
- 数据抽取/识别能力必须用样例输入验证字段、置信度或错误处理，不能只做空表单。
- 涉及隐私、凭据或权限时，交付必须明确数据边界和不可静默外传的规则。
- 后端先采用本地数据存储，接口设计保持可替换
- 缺少真实 demo 或样例输入时，只能交付框架版/示例版并在限制中标记未完成真实验证
- 先按本地可运行、可测试、带结果预览的第一版推进

## First Version Plan

- 先建立项目记录；模型客服整理需求后直接启动正式 agent 生成。
- 核心能力：内容生成能力
- 核心能力：本地模型后端
- 核心能力：导入导出和格式互操作
- 核心能力：数据抽取和理解
- 交付启动说明、测试结论和预览截图
- 第一版先做框架版/示例版分析流程，缺少真实输入时不宣称完成真实验证
- 整理输入解析
- 生成核心分析流程
- 提供可视化摘要和测试结论

## Acceptance Criteria

- 缺少真实模型、外部 API、媒体后端或数据集时，只能交付配置入口、适配层、测试框架和限制说明
- 占位图、纯色图、降级预览或模拟结果不能算真实核心能力验收通过
- 项目必须能运行，并输出测试结论和可视化/预览结果
- 交付时必须直接发送截图或关键帧预览
- 生成类核心能力必须有明确模型/API/本地后端/专用引擎能力检查；占位或降级预览不能冒充真实生成。
- 用户要求本地模型时，外部模型只能作为备选说明，不能算满足本地模型验收。
- 数据抽取/识别能力必须用样例输入验证字段、置信度或错误处理，不能只做空表单。
- 涉及隐私、凭据或权限时，交付必须明确数据边界和不可静默外传的规则。

## Change Requests

- Local AI Knowledge Studio

做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层。

必须功能：
1. 本地资料导入：支持 markdown / txt / pdf 占位解析接口，登记资料来源、标签、状态。
2. 知识库：文档列表、标签筛选、关键词搜索、文档详情。
3. AI / 模型适配层：本地模型配置入口，模型路径或 endpoint 配置，summarizer / retriever adapter；缺少本地模型时不能假装真实推理通过；mock adapter 必须标为 mock。
4. 任务和项目管理：从资料生成任务，todo / doing / done，优先级，负责人或备注，简单看板或列表。
5. 报告生成：选择资料和任务，生成本地 markdown 报告，记录输入来源和限制说明。
6. UI：Dashboard、Documents、Search、Tasks、Reports、Settings / Model Config。
7. 本地数据：SQLite 或 JSON store，示例数据，可重启后保持状态，至少有持久化设计。
8. 交付：README、启动命令、测试命令、TEST_REPORT.md、screenshots、final_project_bundle.zip。

## Delivery Requirements

- 可运行项目包
- 生成素材证据
- 导出结果或报告
- 测试报告
- 交付可运行项目文件、效果预览和测试结论
- 交付时必须直接发送截图或关键帧预览

## Decision Log

- 项目输入进入后直接启动正式 agent 生成；客服回复由模型生成。
- 先识别用户显式/隐式核心能力，再为核心能力寻找成熟模型、库、API 或本地后端；明显影响产品效果的路线差异必须向用户确认。
- 模型前台返回结构化内容解析失败，本地兜底保留用户需求并继续正式生成主线。

## Uploaded Project Inputs

- 未记录

## Open Questions

- 数据抽取/识别结果需要自动通过，还是必须带置信度和人工确认流程？
- 涉及资料和凭据时，是否要求严格本地处理，还是允许配置外部服务？
- 检索/问答优先用本地向量库，外部向量服务，还是两者可配置？
- 如果指定的本地模型/服务暂时不可用，要不要允许外部高质量模型服务作为临时备选，还是严格只接受本地能力？

## Blocking Questions

- 未记录

## Module Map

| Flow Node | Module Ref | Main Output | Responsibility |
| --- | --- | --- | --- |
| `n_customer_service` | `module.customer.service@1` | `customer_request` | 需求对话、用户纠正、验收标准、交付要求 |
| `n_requirement_blueprint` | `module.requirement_blueprint.generator@1` | `requirement_blueprint` | 需求蓝图、I/O、功能拆解、任务和 PRD |
| `n_local_librarian` | `module.local.librarian@1` | `local_library_index` | 本地库、模块、脚本和可复用能力索引 |
| `n_online_library_sources` | `module.online.library_sources@1` | `online_sources` | 市场调研、在线库/API/模型发现 |
| `n_feature_library_search` | `module.feature.library_search@1` | `candidates` | 按功能寻找可用库、API、skill 或 agent |
| `n_local_agent` | `module.local_agent.plan@1` | `agent_plan` | agent 真实使用项目的输入到输出流程计划 |
| `n_adversarial_generation` | `module.adversarial_generation@1` | `adversarial_review` | 反向检查模板化、假通过、缺产物、未满足用户纠正 |
| `n_project_generator` | `module.project.generator@1` | `project_blueprint/generation_trace` | 真实项目代码、接口、依赖和生成轨迹 |
| `n_test_graph_emit` | `module.test_graph.emit@1` | `test_graph` | 项目类型自适应测试图和步骤 |
| `n_effect_report_emit` | `module.effect_report.emit@1` | `effect_report` | 效果报告、截图、视频、可见产物 |
| `n_unified_control` | `module.unified_control@1` | `project_blueprint/generation_trace/test_graph/effect_report` | 最终统一验收与交付裁决 |

## Artifact Map

| Artifact Ref | Purpose |
| --- | --- |
| `artifact.goal@1` | 用户原始目标和补充 |
| `artifact.customer_request@1` | 规范化客户请求、约束、验收和纠正 |
| `artifact.requirement_blueprint@1` | 结构化需求蓝图 |
| `artifact.local_library_index@1` | 本地能力索引 |
| `artifact.online_library_sources@1` | 在线资料、市场调研和 API/模型发现 |
| `artifact.feature_library_candidates@1` | 按功能筛出的候选库/API/skill |
| `artifact.local_agent_plan@1` | agent 实际使用计划 |
| `artifact.adversarial_review@1` | 生成前/后的反向验收意见 |
| `artifact.project_blueprint@1` | 项目文件、模块、接口和运行方式 |
| `artifact.generation_trace@1` | 生成过程、决策和模块输出 |
| `artifact.test_graph@1` | 测试图 |
| `artifact.effect_report@1` | 效果报告和可见产物 |

## Visible User Message Log

1. Local AI Knowledge Studio

做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层。

必须功能：
1. 本地资料导入：支持 markdown / txt / pdf 占位解析接口，登记资料来源、标签、状态。
2. 知识库：文档列表、标签筛选、关键词搜索、文档详情。
3. AI / 模型适配层：本地模型配置入口，模型路径或 endpoint 配置，summarizer / retriever adapter；缺少本地模型时不能假装真实推理通过；mock adapter 必须标为 mock。
4. 任务和项目管理：从资料生成任务，todo / doing / done，优先级，负责人或备注，简单看板或列表。
5. 报告生成：选择资料和任务，生成本地 markdown 报告，记录输入来源和限制说明。
6. UI：Dashboard、Documents、Search、Tasks、Reports、Settings / Model Config。
7. 本地数据：SQLite 或 JSON store，示例数据，可重启后保持状态，至少有持久化设计。
8. 交付：README、启动命令、测试命令、TEST_REPORT.md、screenshots、final_project_bundle.zip。

## Generation State

- Status: `rework_blocked`
- Started at: ``
- Finished at: `2026-07-07T07:31:22.780079+00:00`
- Result path: ``

## Update Rules

- 用户纠正优先写入 `Change Requests` 或 `Acceptance Criteria`。
- 长期行为要求写入 `User Rules`。
- 展示图片、视频、测试过程、真实产物的要求写入 `Delivery Requirements`。
- 模型/API/库选择原因写入 `Decision Log`。
- 生成后台必须把本 MD 和 JSON mirror 当成 `customer_request` 的上游上下文。
