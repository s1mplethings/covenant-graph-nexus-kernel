---
kind: ProjectMemoryMarkdown
schema_version: 1
chat_id: frontdesk-b
flow_ref: flow.modular_project_generation@1
policy_ref: policy.safe_modular_project_generation@1
contract_pack: agent_context.modular_project_generation.contract_pack.json
artifact_ref: artifact.project_memory_markdown@1
generated_at: 2026-07-11T04:14:56.732703+00:00
revision_count: 4
---

# Project Memory

这份文档是 Telegram 项目的长期可维护规格。后续修改必须先更新这里，再传给模块化生成后台。

## Modular Contract Binding

- Contract pack: `agent_context.modular_project_generation.contract_pack.json`
- Flow: `flow.modular_project_generation@1`
- Policy: `policy.safe_modular_project_generation@1`
- JSON artifact mirror: `D:\CGKN\examples\project_memory\frontdesk-b\project_memory.artifact.json`

## Current Project Summary

本地 AI 文档助手，支持导入、检索、总结和界面

## Known Facts

- 用户提出的新项目需求: 我想做一个本地 AI 文档助手，可以导入文档、检索、总结，还要有界面
- 识别出的核心能力：导入导出和格式互操作；检索、搜索和知识库；产品界面和交互
- 用户补充: 项目内部需要本地模型路线
- 生成出来的项目内部按本地模型路线设计，需要模型适配层、配置入口和缺模型限制说明。
- 按用户纠正更新: 我是说项目里面用本地模型，不是让你们生成代码也走本地
- 用户补充: 我是说项目里面用本地模型，不是让你们生成代码也走本地
- 识别出的核心能力：内容生成能力；本地模型后端
- 用户补充: 那先补截图和测试
- 识别出的核心能力：真实运行预览和证据

## User Rules

- 未记录

## Default Assumptions

- 未回答/缺失项按默认假设推进: 检索/问答优先用本地向量库，外部向量服务，还是两者可配置？

## First Version Plan

- 先建立项目记录；模型客服整理需求后直接启动正式 agent 生成。

## Acceptance Criteria

- 本地模型配置入口
- 检索和总结适配层
- 缺模型时不能假装真实推理
- 生成类核心能力必须有明确模型/API/本地后端/专用引擎能力检查；占位或降级预览不能冒充真实生成。
- 用户要求本地模型时，外部模型只能作为备选说明，不能算满足本地模型验收。
- 交付时必须直接发送截图或关键帧预览
- 交付必须包含真实运行证据：截图、生成图片、视频或测试报告中至少按用户要求提供。

## Change Requests

- 用户纠正: 我是说项目里面用本地模型，不是让你们生成代码也走本地
- 我是说项目里面用本地模型，不是让你们生成代码也走本地
- 那先补截图和测试

## Delivery Requirements

- 交付时必须直接发送截图或关键帧预览

## Decision Log

- 项目输入进入后直接启动正式 agent 生成；客服回复由模型生成。
- 先识别用户显式/隐式核心能力，再为核心能力寻找成熟模型、库、API 或本地后端；明显影响产品效果的路线差异必须向用户确认。
- 用户纠正优先于此前推断，后续回复先承认修正再推进。
- 本轮由 Human Frontdesk 记录补充，agent loop 会读取同一个 agent_session 继续推进。

## Uploaded Project Inputs

- 未记录

## Open Questions

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

1. 我想做一个本地 AI 文档助手，可以导入文档、检索、总结，还要有界面
2. 走本地模型 + 开始做吧
3. 你是用 API 还是本地模型生成？
4. 我是说项目里面用本地模型，不是让你们生成代码也走本地
5. 为什么还没有截图
6. 那先补截图和测试
7. 总结一下现在做到哪了

## Generation State

- Status: `running`
- Started at: ``
- Finished at: ``
- Result path: ``

## Update Rules

- 用户纠正优先写入 `Change Requests` 或 `Acceptance Criteria`。
- 长期行为要求写入 `User Rules`。
- 展示图片、视频、测试过程、真实产物的要求写入 `Delivery Requirements`。
- 模型/API/库选择原因写入 `Decision Log`。
- 生成后台必须把本 MD 和 JSON mirror 当成 `customer_request` 的上游上下文。
