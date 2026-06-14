---
kind: ProjectMemoryMarkdown
schema_version: 1
chat_id: phase2-real-task-board-src5
flow_ref: flow.modular_project_generation@1
policy_ref: policy.safe_modular_project_generation@1
contract_pack: agent_context.modular_project_generation.contract_pack.json
artifact_ref: artifact.project_memory_markdown@1
generated_at: 2026-06-13T17:32:13.520056+00:00
revision_count: 0
---

# Project Memory

这份文档是 Telegram 项目的长期可维护规格。后续修改必须先更新这里，再传给模块化生成后台。

## Modular Contract Binding

- Contract pack: `agent_context.modular_project_generation.contract_pack.json`
- Flow: `flow.modular_project_generation@1`
- Policy: `policy.safe_modular_project_generation@1`
- JSON artifact mirror: `D:\CGKN\examples\project_memory\phase2-real-task-board-src5\project_memory.artifact.json`

## Current Project Summary

请生成一个很小但真实可运行的 Python Flask 本地任务看板 Web 工具。必须只生成项目文件，不要返回解释。

必须包含这些文件：
- app.py：Flask 入口，运行本地 Web 应用
- requirements.txt：列出 Flask 和 pytest
- src/task_store.py：任务增删改查和筛选逻辑
- templates/index.html 或 static/index.html：浏览器界面
- tests/test_app.py：pytest，至少测试首页和任务 API/核心函数
- README.md：本地运行说明
- TEST_PLAN.md 或 TEST_REPORT.md：测试证据

功能要求：任务列表、新增任务、状态切换（待办 / 进行中 / 完成）、删除任务、按状态筛选。还要有至少一个截图或 HTML 预览证据。最终必须打包成 final_project_bundle.zip。

## Known Facts

- Python Flask 本地任务看板
- 必须有 app.py
- 必须有 requirements.txt
- 必须有 src/task_store.py
- 必须有 pytest 测试

## User Rules

- 未记录

## Default Assumptions

- 未记录

## First Version Plan

- 未记录

## Acceptance Criteria

- README.md 存在
- requirements.txt 存在
- src/task_store.py 存在
- tests/test_app.py 存在
- pytest 通过并有 TEST_REPORT.md
- 截图或 HTML 预览证据存在
- final_project_bundle.zip 存在

## Change Requests

- 未记录

## Delivery Requirements

- 项目 zip 包
- 预览证据
- 真实测试报告

## Decision Log

- 未记录

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

1. 请生成一个很小但真实可运行的 Python Flask 本地任务看板 Web 工具。必须只生成项目文件，不要返回解释。

必须包含这些文件：
- app.py：Flask 入口，运行本地 Web 应用
- requirements.txt：列出 Flask 和 pytest
- src/task_store.py：任务增删改查和筛选逻辑
- templates/index.html 或 static/index.html：浏览器界面
- tests/test_app.py：pytest，至少测试首页和任务 API/核心函数
- README.md：本地运行说明
- TEST_PLAN.md 或 TEST_REPORT.md：测试证据

功能要求：任务列表、新增任务、状态切换（待办 / 进行中 / 完成）、删除任务、按状态筛选。还要有至少一个截图或 HTML 预览证据。最终必须打包成 final_project_bundle.zip。

## Generation State

- Status: `revision_planning`
- Started at: ``
- Finished at: ``
- Result path: ``

## Update Rules

- 用户纠正优先写入 `Change Requests` 或 `Acceptance Criteria`。
- 长期行为要求写入 `User Rules`。
- 展示图片、视频、测试过程、真实产物的要求写入 `Delivery Requirements`。
- 模型/API/库选择原因写入 `Decision Log`。
- 生成后台必须把本 MD 和 JSON mirror 当成 `customer_request` 的上游上下文。
