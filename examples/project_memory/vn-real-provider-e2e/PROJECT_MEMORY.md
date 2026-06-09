---
kind: ProjectMemoryMarkdown
schema_version: 1
chat_id: vn-real-provider-e2e
flow_ref: flow.modular_project_generation@1
policy_ref: policy.safe_modular_project_generation@1
contract_pack: agent_context.modular_project_generation.contract_pack.json
artifact_ref: artifact.project_memory_markdown@1
generated_at: 2026-06-09T03:25:31.569711+00:00
revision_count: 3
---

# Project Memory

这份文档是 Telegram 项目的长期可维护规格。后续修改必须先更新这里，再传给模块化生成后台。

## Modular Contract Binding

- Contract pack: `agent_context.modular_project_generation.contract_pack.json`
- Flow: `flow.modular_project_generation@1`
- Policy: `policy.safe_modular_project_generation@1`
- JSON artifact mirror: `D:\CGKN\examples\project_memory\vn-real-provider-e2e\project_memory.artifact.json`

## Current Project Summary

开发一个本地可运行的视觉小说（VN）项目助手，支持故事逻辑时间线梳理，背景和立绘的正经图片生成，具备桌面界面和文件导出功能。

## Known Facts

- 用户提出的新项目需求: 帮我做一个本地可运行的 VN 项目助手，可以梳理故事逻辑的时间线，可以生成背景，立绘，是正经直接生成图片的
补充：
本地模型，桌面界面，文件导出
- 识别出的核心能力：结构化流程/关系建模；内容生成能力；本地模型后端；导入导出和格式互操作；产品界面和交互
- 用户项目需求: 帮我做一个本地可运行的 VN 项目助手，可以梳理故事逻辑的时间线，可以生成背景，立绘，是正经直接生成图片的
补充：
本地模型，桌面界面，文件导出

## User Rules

- 未记录

## Default Assumptions

- 图片生成模块设计为可替换的provider接口，生成结果存储于本地素材库
- 生成能力必须基于明确的本地模型/API，不能用占位或降级预览替代
- 用户要求本地模型时，外部模型仅作为备选说明，不计入验收标准
- 先按本地可运行、可测试、带结果预览的第一版推进
- 未回答/缺失项按默认假设推进: 您是否有偏好的本地模型框架或引擎？
- 未回答/缺失项按默认假设推进: 是否需要支持多语言界面？
- 未回答/缺失项按默认假设推进: 对导出文件格式有无特殊要求（如JSON、XML、专用格式）？
- 未回答/缺失项按默认假设推进: 第一版运行形态要本地网页，还是桌面窗口？这会影响打包和测试方式。
- 未回答/缺失项按默认假设推进: 如果指定的本地模型/服务暂时不可用，是否允许使用外部高级API/模型作为临时备选，还是严格只接受本地能力？
- 未回答/缺失项按默认假设推进: 第一版运行形态是本地网页应用还是桌面窗口程序？这将影响打包和测试方式。

## First Version Plan

- 先建立项目记录；模型客服整理需求后直接启动正式 agent 生成。
- 结构化流程和关系建模，支持时间线和依赖关系管理
- 内容生成能力，基于本地模型实现背景和立绘图片生成
- 本地模型后端配置和能力探测，确保生成质量
- 导入导出功能，支持项目文件格式互操作
- 桌面界面实现，包含时间线视图、素材管理和预览
- 交付启动说明、测试结论和预览截图
- 整理输入解析
- 生成核心分析流程
- 提供可视化摘要和测试结论

## Acceptance Criteria

- 交付时必须直接发送图片/照片预览 artifact，不只返回路径
- 生成类核心能力必须有明确模型/API/本地后端/专用引擎能力检查；占位或降级预览不能冒充真实生成。
- 用户要求本地模型时，外部模型只能作为备选说明，不能算满足本地模型验收。
- 项目必须能运行，并输出测试结论和可视化/预览结果

## Change Requests

- 未记录

## Delivery Requirements

- 交付时必须直接发送图片/照片预览 artifact，不只返回路径
- 交付可运行项目文件、效果预览和测试结论

## Decision Log

- 项目输入进入后直接启动正式 agent 生成；客服回复由模型生成。
- 先识别用户显式/隐式核心能力，再为核心能力寻找成熟模型、库、API 或本地后端；明显影响产品效果的路线差异必须向用户确认。
- 模型前台返回结构化内容解析失败，本地兜底保留用户需求并继续正式生成主线。

## Uploaded Project Inputs

- 未记录

## Open Questions

- 第一版运行形态要本地网页，还是桌面窗口？这会影响打包和测试方式。
- 如果指定的本地模型/服务暂时不可用，是否允许使用外部高级API/模型作为临时备选，还是严格只接受本地能力？
- 第一版运行形态是本地网页应用还是桌面窗口程序？这将影响打包和测试方式。
- 如果指定的本地模型/服务暂时不可用，要不要允许外部高级 API/模型作为临时备选，还是严格只接受本地能力？

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

1. 帮我做一个本地可运行的 VN 项目助手，可以梳理故事逻辑的时间线，可以生成背景，立绘，是正经直接生成图片的
补充：
本地模型，桌面界面，文件导出
2. 开始生成

## Generation State

- Status: `rework_blocked`
- Started at: ``
- Finished at: `2026-06-09T03:25:31.536909+00:00`
- Result path: ``

## Update Rules

- 用户纠正优先写入 `Change Requests` 或 `Acceptance Criteria`。
- 长期行为要求写入 `User Rules`。
- 展示图片、视频、测试过程、真实产物的要求写入 `Delivery Requirements`。
- 模型/API/库选择原因写入 `Decision Log`。
- 生成后台必须把本 MD 和 JSON mirror 当成 `customer_request` 的上游上下文。
