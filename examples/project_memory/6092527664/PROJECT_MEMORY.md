---
kind: ProjectMemoryMarkdown
schema_version: 1
chat_id: 6092527664
flow_ref: flow.modular_project_generation@1
policy_ref: policy.safe_modular_project_generation@1
contract_pack: agent_context.modular_project_generation.contract_pack.json
artifact_ref: artifact.project_memory_markdown@1
generated_at: 2026-06-04T16:30:23.880944+00:00
revision_count: 1
---

# Project Memory

这份文档是 Telegram 项目的长期可维护规格。后续修改必须先更新这里，再传给模块化生成后台。

## Modular Contract Binding

- Contract pack: `agent_context.modular_project_generation.contract_pack.json`
- Flow: `flow.modular_project_generation@1`
- Policy: `policy.safe_modular_project_generation@1`
- JSON artifact mirror: `D:\CGKN\examples\project_memory\6092527664\project_memory.artifact.json`

## Current Project Summary

你帮我做一个本地可运行的 VN 项目助手，可以梳理故事逻辑的时间线，可以生成背景，立绘，是正经直接生成图片的

## Known Facts

- 用户提出的新项目需求: 你帮我做一个本地可运行的 VN 项目助手，可以梳理故事逻辑的时间线，可以生成背景，立绘，是正经直接生成图片的

## User Rules

- 任何生成项目、代码、背景、立绘、图片或可运行结果，必须使用已配置的 API/provider 或已配置的本地模型后端。
- 不允许用本地规则、deterministic simulator、模板、占位图或假进度冒充生成结果。
- 客户提出需求时后端必须同步看到并开始找库、定方法、生成和验证；客服同时继续确认。
- 流程不允许线性等待固定开始口令；前台和后台必须并行开工。

## Default Assumptions

- 未记录

## First Version Plan

- 客户提出项目需求后，后台立即并行进入 API/provider 生成队列；前台继续确认细节并把补充写入修订控制。

## Acceptance Criteria

- 交付时必须直接发送图片/照片预览 artifact，不只返回路径

## Change Requests

- 未记录

## Delivery Requirements

- 交付时必须直接发送图片/照片预览 artifact，不只返回路径

## Decision Log

- 生成执行源已强制限定为 API/provider 或已配置的本地模型后端；本地规则和 simulator 不得作为生成结果。
- 前台确认和后台生成改为并行关系：新项目需求进入后自动写入 start_generation 控制命令。
- 生成执行源仍强制限定为 API/provider 或已配置本地模型；本地规则和 simulator 不得冒充生成结果。
- 已移除线性等待确认规则；当前流程是前台确认和后台生成并行。

## Uploaded Project Inputs

- 未记录

## Open Questions

- 未记录

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

1. 你好
2. 你帮我做一个本地可运行的 VN 项目助手，可以梳理故事逻辑的时间线，可以生成背景，立绘，是正经直接生成图片的
3. 你好

## Generation State

- Status: `running`
- Started at: `2026-06-04T16:28:22.682103+00:00`
- Finished at: ``
- Result path: ``

## Update Rules

- 用户纠正优先写入 `Change Requests` 或 `Acceptance Criteria`。
- 长期行为要求写入 `User Rules`。
- 展示图片、视频、测试过程、真实产物的要求写入 `Delivery Requirements`。
- 模型/API/库选择原因写入 `Decision Log`。
- 生成后台必须把本 MD 和 JSON mirror 当成 `customer_request` 的上游上下文。
