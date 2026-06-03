---
kind: ProjectMemoryMarkdown
schema_version: 1
chat_id: 6092527664
flow_ref: flow.modular_project_generation@1
policy_ref: policy.safe_modular_project_generation@1
contract_pack: agent_context.modular_project_generation.contract_pack.json
artifact_ref: artifact.project_memory_markdown@1
generated_at: 2026-06-03T06:56:48.861731+00:00
revision_count: 5
---

# Project Memory

这份文档是 Telegram 项目的长期可维护规格。后续修改必须先更新这里，再传给模块化生成后台。

## Modular Contract Binding

- Contract pack: `agent_context.modular_project_generation.contract_pack.json`
- Flow: `flow.modular_project_generation@1`
- Policy: `policy.safe_modular_project_generation@1`
- JSON artifact mirror: `D:\CGKN\examples\project_memory\6092527664\project_memory.artifact.json`

## Current Project Summary

本地可运行的 VN 项目助手，支持梳理故事逻辑时间线（流程图/节点编辑），集成 AI 生成背景和立绘图片，图片生成为真实 AI 产出，可本地保存和预览，适用于 VN 项目开发。

## Known Facts

- 用户需要本地可运行的工具
- 必须支持故事逻辑时间线梳理
- 必须能生成背景和立绘图片
- 图片生成要求为真正的 AI 生成图
- 图片生成模型必须本地部署
- 背景和立绘生成要分开处理

## User Rules

- 未记录

## Default Assumptions

- 操作系统默认 Windows
- 图片生成模型默认 Stable Diffusion 本地部署
- 风格默认通用二次元风
- 故事逻辑编辑采用节点/流程图方式
- 图片输出格式为 PNG/JPG
- 生成图片后可本地预览和保存
- 背景和立绘生成入口分开

## First Version Plan

- 实现本地桌面或 Web 应用，支持故事逻辑时间线梳理（节点/流程图）
- 集成本地 AI 图像生成（背景、立绘），支持基础 prompt 输入
- 支持图片预览和本地导出
- 集成本地 AI 图像生成（背景、立绘），分别提供生成入口，支持基础 prompt 输入

## Acceptance Criteria

- 工具可在本地运行，无需联网
- 支持梳理和编辑故事逻辑时间线
- 生成的背景和立绘为真实 AI 生成图片
- 生成图片可本地预览和保存
- 交付时必须直接发送图片/照片预览 artifact，不只返回路径
- 背景和立绘生成入口必须分开

## Change Requests

- 图片生成模型必须本地部署
- 背景和立绘生成要分开处理

## Delivery Requirements

- 生成图片需直接展示预览
- 交付时需有截图或图片产物
- 交付时必须直接发送图片/照片预览 artifact，不只返回路径

## Decision Log

- 采用 Stable Diffusion 本地部署作为默认 AI 图片生成模型，因其支持本地运行和二次元风格。
- 故事逻辑编辑采用节点/流程图方式，便于梳理分支和时间线。
- 背景和立绘生成入口分开，分别调用本地 AI 模型。

## Uploaded Project Inputs

- 未记录

## Open Questions

- 是否有特定的 VN 脚本格式需要支持？
- 图片分辨率有无特殊要求？
- 是否需要导出完整 VN 项目脚本？
- 是否需要支持 Mac/Linux？

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
3. 我主要的要求就是用本地的图片生成模型，然后背景和立绘是要分开的
4. 开始做吧
5. 重新开始吧

## Generation State

- Status: `stopped_by_user`
- Started at: ``
- Finished at: `2026-06-03T06:56:48.861199+00:00`
- Result path: ``

## Update Rules

- 用户纠正优先写入 `Change Requests` 或 `Acceptance Criteria`。
- 长期行为要求写入 `User Rules`。
- 展示图片、视频、测试过程、真实产物的要求写入 `Delivery Requirements`。
- 模型/API/库选择原因写入 `Decision Log`。
- 生成后台必须把本 MD 和 JSON mirror 当成 `customer_request` 的上游上下文。
