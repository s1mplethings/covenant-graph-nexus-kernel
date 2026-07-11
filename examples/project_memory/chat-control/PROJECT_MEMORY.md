---
kind: ProjectMemoryMarkdown
schema_version: 1
chat_id: chat-control
flow_ref: flow.modular_project_generation@1
policy_ref: policy.safe_modular_project_generation@1
contract_pack: agent_context.modular_project_generation.contract_pack.json
artifact_ref: artifact.project_memory_markdown@1
generated_at: 2026-06-26T17:39:55.830043+00:00
revision_count: 3
---

# Project Memory

这份文档是 Telegram 项目的长期可维护规格。后续修改必须先更新这里，再传给模块化生成后台。

## Modular Contract Binding

- Contract pack: `agent_context.modular_project_generation.contract_pack.json`
- Flow: `flow.modular_project_generation@1`
- Policy: `policy.safe_modular_project_generation@1`
- JSON artifact mirror: `D:\CGKN\examples\project_memory\chat-control\project_memory.artifact.json`

## Current Project Summary

做一个本地 VN 助手，要时间线和图片预览

## Known Facts

- 用户提出的新项目需求: 做一个本地 VN 助手，要时间线和图片预览
- 识别出的核心能力：结构化流程/关系建模；真实运行预览和证据；导入导出和格式互操作
- 做一个本地 VN 助手，要时间线和图片预览

## User Rules

- 未记录

## Default Assumptions

- 图片生成先做可替换接口，生成结果落到本地素材库
- 背景图和角色立绘使用独立任务与独立验收记录
- 占位图、纯色图或降级预览不能算真实背景/立绘验收通过
- 交付必须包含真实运行证据：截图、生成图片、视频或测试报告中至少按用户要求提供。
- 本地可运行
- 直接生成并测试
- 未回答/缺失项按默认假设推进: 图片生成我先按真实图片生成接口预留，本地保存结果，可以吗？

## First Version Plan

- 先建立项目记录；模型客服整理需求后直接启动正式 agent 生成。
- 背景和立绘分开生成、分开管理、分开验收
- 核心能力：结构化流程/关系建模
- 核心能力：真实运行预览和证据
- 核心能力：导入导出和格式互操作
- 第一版交付可直接打开和操作的界面
- 交付启动说明、测试结论和预览截图
- 前端交互
- 后端处理
- 测试与交付

## Acceptance Criteria

- 缺少真实模型、外部 API、媒体后端或数据集时，只能交付配置入口、适配层、测试框架和限制说明
- 占位图、纯色图、降级预览或模拟结果不能算真实核心能力验收通过
- 可运行
- 有测试结论
- 交付时必须直接发送图片/照片预览 artifact，不只返回路径
- 交付时必须提供可视化预览或摘要图兜底
- 交付必须包含真实运行证据：截图、生成图片、视频或测试报告中至少按用户要求提供。

## Change Requests

- 未记录

## Delivery Requirements

- 可运行项目包
- 界面截图或预览证据
- 生成素材证据
- 交付项目包和预览
- 交付时必须直接发送图片/照片预览 artifact，不只返回路径
- 交付时必须提供可视化预览或摘要图兜底

## Decision Log

- 项目输入进入后直接启动正式 agent 生成；客服回复由模型生成。
- 先识别用户显式/隐式核心能力，再为核心能力寻找成熟模型、库、API 或本地后端；明显影响产品效果的路线差异必须向用户确认。
- 项目输入到达即启动正式生成

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

1. 做一个本地 VN 助手，要时间线和图片预览
2. 开始生成

## Generation State

- Status: `rework_blocked`
- Started at: ``
- Finished at: `2026-06-26T17:39:55.809166+00:00`
- Result path: ``

## Update Rules

- 用户纠正优先写入 `Change Requests` 或 `Acceptance Criteria`。
- 长期行为要求写入 `User Rules`。
- 展示图片、视频、测试过程、真实产物的要求写入 `Delivery Requirements`。
- 模型/API/库选择原因写入 `Decision Log`。
- 生成后台必须把本 MD 和 JSON mirror 当成 `customer_request` 的上游上下文。
