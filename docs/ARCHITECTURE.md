# CovenantGraph Nexus Kernel Design

## 0. 设计结论

正式名称：**CovenantGraph Nexus Kernel**。

简称：**CGNK**。


你的目标不是把 `cgnk-core` 做成一个 runtime，也不是做成给人读的架构文档。

目标应该是：

```text
把 cgnk-core-starter 重构成一个给 coding agent 使用的合同编译器。
```

这个合同编译器的核心职责：

```text
1. 定义模块连接协议。
2. 定义 artifact 类型系统。
3. 定义 module 的 input/output ports。
4. 定义 flow 里的 port-to-port 连接。
5. 定义 graph edit proposal，禁止 agent 直接改 flow。
6. 定义 effect/policy/compatibility 检查。
7. 输出 structured diagnostics，帮助 agent 自动修复。
8. 为 legacy project-generation 系统重构提供 MigrationSpec；CTCP 可作为首个迁移样板。
```

它不负责：

```text
1. 执行 node。
2. 调用 provider。
3. 写项目文件。
4. 管理真实 run state。
5. 做 Telegram/frontend/support bot。
```

一句话：

```text
不要让模块连接模块；让端口连接端口。
```

---

## 1. 当前项目的问题

`cgnk-core-starter` 已经有这些基础概念：

```text
Artifact
Node
Edge
Gate
Proposal
Policy
Refactor harness
CLI validation
```

这些方向是对的，但如果目标是“所有模块都能移动、替换、重组”，目前的问题是：

```text
1. Node 合同和 Flow 编排混在一起。
2. 模块连接协议还不够显式。
3. 连接还是偏 edge string，不是严格的 port object。
4. pre/post/gate 里有 stringly typed predicate。
5. proposal 还是特殊操作，不是统一 graph edit algebra。
6. validator 返回结果还不够 agent-friendly。
7. 没有完整的 normalized compiled contract。
8. 没有明确的 ModuleContract / FlowNode 分离。
9. 没有 MigrationSpec 来约束 legacy 系统重构。
```

所以重构方向不是“增加 runtime”，而是把合同层升级成更强的 machine-first contract compiler。

---

## 2. 核心抽象重命名

建议把概念升级成下面这些对象：

```text
ArtifactTypeSpec       数据类型合同
ModuleContract         可组合模块接口合同
FlowSpec               模块实例编排合同
FlowNode               ModuleContract 在某条 Flow 里的实例
PortEdge               output port -> input port 的连接
PolicySpec             权限、风险、副作用边界
GraphEditProposal      agent 唯一允许提交的 graph 修改格式
MigrationSpec          legacy project-generation 系统到 contract flow 的迁移边界
Diagnostic             编译器输出的结构化错误
CompiledContractBundle 解析、resolve、type check 后的 canonical 结果
```

旧概念映射：

```text
Node          -> FlowNode + ModuleContract
Edge          -> PortEdge
Artifact      -> ArtifactTypeSpec / ArtifactInstance reference
Proposal      -> GraphEditProposal
Policy        -> PolicySpec
FlowSpec JSON -> ContractBundle input + CompiledContractBundle output
```

---

## 3. 统一模块连接模型

每个可组合模块都必须暴露统一连接面。

最小结构：

```json
{
  "kind": "ModuleContract",
  "id": "module.xxx",
  "version": "1",
  "ports": {
    "input": {},
    "output": {}
  },
  "requires": {
    "capabilities": [],
    "context": []
  },
  "effects": {
    "fs_read": [],
    "fs_write": [],
    "network": false,
    "provider_call": false,
    "risk": 0
  },
  "compatibility": {
    "replaceable": true,
    "movable": true,
    "surface_rule": "same_or_compatible",
    "effect_rule": "subset_or_equal"
  }
}
```

模块之间不能直接互相知道。模块只知道：

```text
1. 我有哪些 input ports。
2. 我有哪些 output ports。
3. 每个 port 的 artifact_type 是什么。
4. 我需要哪些 capability。
5. 我会产生哪些 effect。
6. 我在替换/移动时要遵守什么 compatibility rule。
```

FlowSpec 负责把模块实例接起来：

```json
{
  "from": { "node": "n_plan", "port": "plan" },
  "to": { "node": "n_emit_patch", "port": "plan" }
}
```

编译器负责验证：

```text
source output port exists
source output artifact_type exists
target input port exists
target input artifact_type exists
source artifact_type is compatible with target artifact_type
input port 没有重复生产者，除非明确声明 merge
图无环
所有 required input 都已满足
policy 没有被违反
```

---

## 4. 四种连接类型

### 4.1 数据连接：Artifact Port

这是核心连接。

```text
Module A output port -> Module B input port
```

检查规则：

```text
A.output[port].artifact_type == B.input[port].artifact_type
```

或者满足版本兼容：

```text
ArtifactTypeSpec.compatibility.backward_compatible_with contains target type/version
```

---

### 4.2 能力连接：Capability Port

有些模块需要服务能力，而不是上游数据。

例如：

```text
cap.fs.read
cap.fs.write
cap.provider.call
cap.shell.run
cap.git.diff
cap.test.runner
```

ModuleContract 声明 requires：

```json
{
  "requires": {
    "capabilities": [
      { "id": "cap.fs.read", "scope": ["project/**"] },
      { "id": "cap.provider.call", "model_class": "code_generation" }
    ]
  }
}
```

PolicySpec 决定是否允许。

---

### 4.3 控制连接：Predicate / Gate

不要再用字符串：

```json
"pre": ["passed(n_plan)"]
```

改成结构化 predicate：

```json
{
  "requires": {
    "all": [
      { "node_passed": "n_plan" },
      { "artifact_exists": { "node": "n_plan", "port": "plan" } }
    ]
  }
}
```

结构化 predicate 的好处：

```text
1. agent 不容易拼错。
2. JSON Schema 可以校验。
3. compiler 可以检查引用是否存在。
4. diagnostics 可以定位到 JSON path。
5. 后续可以加入 all/any/not。
```

---

### 4.4 上下文连接：RunContext Requirement

模块可能需要：

```text
workspace_root
run_id
trace_sink
budget
retry_count
provider_profile
```

这些不要用全局变量。模块必须显式声明：

```json
{
  "requires": {
    "context": ["workspace_root", "run_id", "trace_sink"]
  }
}
```

contract compiler 不执行 context，但要检查 flow/policy 是否允许这些 context keys。

---

## 5. 合同对象设计

### 5.1 ArtifactTypeSpec

用于定义跨模块数据类型。

最小字段：

```json
{
  "kind": "ArtifactTypeSpec",
  "id": "artifact.project_snapshot",
  "version": "1",
  "type_name": "ProjectSnapshot",
  "schema_ref": "schemas/project_snapshot.v1.schema.json",
  "compatibility": {
    "backward_compatible_with": []
  },
  "identity": {
    "hash_fields": ["files", "metadata.root"]
  }
}
```

优先定义这些 CGNK sample artifact：

```text
Goal
ProjectSnapshot
ProjectGraph
RequirementSet
ImplementationPlan
PatchManifest
ValidationReport
BenchmarkReport
ProviderCallTrace
RunSummary
```

---

### 5.2 ModuleContract

这是模块之间的统一接口。

模块的实现可以是 Python class、function、agent step、script 或 adapter，但合同层只关心连接面。

必须包括：

```text
id/version
ports.input
ports.output
requires.capabilities
requires.context
effects
compatibility
policy_ref 或 inline policy constraints
```

示例：

```json
{
  "kind": "ModuleContract",
  "id": "module.project.build_graph",
  "version": "1",
  "ports": {
    "input": {
      "snapshot": {
        "artifact_type": "ProjectSnapshot",
        "required": true
      }
    },
    "output": {
      "graph": {
        "artifact_type": "ProjectGraph"
      }
    }
  },
  "requires": {
    "capabilities": [],
    "context": ["run_id", "trace_sink"]
  },
  "effects": {
    "fs_read": ["project/**"],
    "fs_write": [],
    "network": false,
    "provider_call": false,
    "risk": 1
  },
  "compatibility": {
    "replaceable": true,
    "movable": true,
    "surface_rule": "same_or_compatible",
    "effect_rule": "subset_or_equal"
  }
}
```

---

### 5.3 FlowSpec

FlowSpec 不应该重复定义模块能力，只定义模块实例和连接。

```json
{
  "kind": "FlowSpec",
  "id": "flow.project_generation",
  "version": "1",
  "policy_ref": "policy.safe_project_generation@1",
  "inputs": {
    "goal": "Goal",
    "snapshot": "ProjectSnapshot"
  },
  "nodes": [
    { "id": "n_build_graph", "uses": "module.project.build_graph@1" },
    { "id": "n_plan", "uses": "module.plan.generate@1" }
  ],
  "edges": [
    {
      "from": { "flow_input": "snapshot" },
      "to": { "node": "n_build_graph", "port": "snapshot" }
    },
    {
      "from": { "node": "n_build_graph", "port": "graph" },
      "to": { "node": "n_plan", "port": "graph" }
    }
  ],
  "gates": [
    {
      "id": "g_done",
      "require": { "all": [{ "node_passed": "n_plan" }] },
      "on_fail": "block"
    }
  ]
}
```

---

### 5.4 GraphEditProposal

coding agent 不应直接改 FlowSpec。它只能提交 graph edit list。

统一编辑操作：

```text
add_node
remove_node
replace_node
connect
disconnect
split_edge
add_gate
remove_gate
change_policy_ref
upgrade_module_version
```

示例：

```json
{
  "kind": "GraphEditProposal",
  "id": "proposal.insert_patch_validation",
  "target_flow": "flow.project_refactor@1",
  "edits": [
    {
      "op": "add_node",
      "node": {
        "id": "n_validate_patch",
        "uses": "module.patch.validate@1"
      }
    },
    {
      "op": "disconnect",
      "from": { "node": "n_emit_patch", "port": "patch_manifest" },
      "to": { "node": "n_apply_patch", "port": "patch_manifest" }
    },
    {
      "op": "connect",
      "from": { "node": "n_emit_patch", "port": "patch_manifest" },
      "to": { "node": "n_validate_patch", "port": "patch_manifest" }
    },
    {
      "op": "connect",
      "from": { "node": "n_validate_patch", "port": "patch_manifest" },
      "to": { "node": "n_apply_patch", "port": "patch_manifest" }
    }
  ]
}
```

proposal validation 必须执行：

```text
1. schema validate proposal
2. apply proposal to cloned FlowSpec
3. compile cloned FlowSpec
4. run type/effect/policy/graph invariant checks
5. return diagnostics
```

只有 preview graph 也合法，proposal 才合法。

---

### 5.5 PolicySpec

PolicySpec 是 agent 行为边界。

```json
{
  "kind": "PolicySpec",
  "id": "policy.safe_project_refactor",
  "version": "1",
  "fs": {
    "allowed_read": ["project/**", "tests/**"],
    "allowed_write": ["project/**", "tests/**"],
    "denied_write": [".git/**", ".env", "secrets/**", "pyproject.toml"]
  },
  "network": { "allowed": false },
  "provider": { "allowed": false },
  "risk": { "max_risk": 2 },
  "agent_permissions": {
    "allowed_edits": ["add_node", "replace_node", "connect", "disconnect", "split_edge"],
    "denied_edits": ["weaken_policy", "change_artifact_schema", "remove_gate"],
    "requires_human_review": ["remove_node", "upgrade_major_version"]
  }
}
```

---

### 5.6 MigrationSpec

用于约束 legacy project-generation 系统到新合同体系的迁移。

```json
{
  "kind": "MigrationSpec",
  "id": "migration.project_generation",
  "version": "1",
  "legacy": {
    "files": [
      "tools/providers/project_generation_contracts.py",
      "tests/concrete_project_benchmark/run_concrete_project_benchmark.py"
    ],
    "public_entrypoints": ["run_concrete_project_benchmark"]
  },
  "target": {
    "flow": "flow.project_generation@1",
    "modules": [
      "module.project.snapshot@1",
      "module.project.build_graph@1",
      "module.plan.generate@1",
      "module.patch.emit@1",
      "module.patch.validate@1"
    ]
  },
  "preserve": {
    "cli_args": true,
    "summary_json_schema": true,
    "benchmark_report_format": true,
    "provider_call_semantics": true
  },
  "proof": {
    "required_tests": ["unit", "benchmark_smoke", "contract_compile"],
    "required_artifacts": ["benchmark_summary.json", "benchmark_report.md"]
  }
}
```

---

## 6. Contract compiler pipeline

不要只有 `validate_flowspec()`。建议做成编译器管线：

```text
load bundle
  ↓
schema validate
  ↓
normalize ids and refs
  ↓
resolve artifact/module/policy refs
  ↓
build symbol table
  ↓
expand FlowNode surfaces from ModuleContract
  ↓
type check PortEdge
  ↓
check graph invariants
  ↓
check capabilities against PolicySpec
  ↓
check effects against PolicySpec
  ↓
check gates/predicates
  ↓
emit CompiledContractBundle + Diagnostics
```

输出结构：

```json
{
  "ok": true,
  "compiled": {
    "symbols": {
      "artifacts": {},
      "modules": {},
      "flows": {},
      "nodes": {},
      "ports": {}
    },
    "graphs": {}
  },
  "diagnostics": []
}
```

---

## 7. Diagnostics 设计

coding agent 最需要的是结构化错误，不是自然语言段落。

诊断格式：

```json
{
  "code": "CGNK_EDGE_TYPE_MISMATCH",
  "severity": "error",
  "path": "$.edges[2]",
  "message": "Edge type mismatch.",
  "expected": "PatchManifest",
  "actual": "ImplementationPlan",
  "source": {
    "node": "n_plan",
    "port": "plan"
  },
  "target": {
    "node": "n_validate_patch",
    "port": "patch_manifest"
  },
  "repair_hints": [
    {
      "op": "replace_edge_source",
      "from": { "node": "n_plan", "port": "plan" },
      "to": { "node": "n_emit_patch", "port": "patch_manifest" }
    }
  ]
}
```

建议错误码：

```text
CGNK_SCHEMA_INVALID
CGNK_REF_NOT_FOUND
CGNK_MODULE_NOT_FOUND
CGNK_ARTIFACT_TYPE_NOT_FOUND
CGNK_PORT_NOT_FOUND
CGNK_EDGE_TYPE_MISMATCH
CGNK_INPUT_UNBOUND
CGNK_INPUT_MULTI_PRODUCER
CGNK_GRAPH_CYCLE
CGNK_POLICY_DENIED_EDIT
CGNK_POLICY_RISK_EXCEEDED
CGNK_POLICY_EFFECT_DENIED
CGNK_CAPABILITY_DENIED
CGNK_GATE_REF_NOT_FOUND
CGNK_PREDICATE_INVALID
CGNK_REPLACE_SURFACE_INCOMPATIBLE
CGNK_REPLACE_EFFECT_EXPANDED
CGNK_PROPOSAL_PREVIEW_INVALID
CGNK_MIGRATION_PRESERVE_VIOLATED
```

---

## 8. 可移动 / 可替换检查规则

### 8.1 替换模块

替换检查：

```text
1. replacement module exists
2. target node exists
3. input surface compatible
4. output surface compatible
5. output artifact schema compatible
6. effects subset_or_equal
7. risk <= old risk 或 <= policy.max_risk
8. required capabilities 没有新增危险能力
9. downstream edge type checks pass
10. gates/predicates still valid
```

### 8.2 移动模块

移动检查：

```text
1. 新上游能提供所有 required input
2. 新下游能消费所有 output
3. 移动后图无环
4. preconditions 仍可满足
5. capabilities 在 flow policy 里允许
6. gates 没有引用失效
```

### 8.3 插入模块

插入检查：

```text
1. split_edge exists
2. inserted module has at least one compatible input
3. inserted module has at least one compatible output
4. source output type == inserted input type
5. inserted output type == target input type
6. inserted effects allowed by policy
7. preview graph compile passes
```

---

## 9. 建议目录结构

```text
cgnk-core/
  src/cgnk_core/
    contracts/
      schemas.py
      loader.py
      ids.py
      diagnostics.py
      normalize.py
      resolver.py
      compiler.py
      compatibility.py
      graph_invariants.py
      predicates.py
      proposals.py
      bundle.py

    specs/
      artifact.py
      module.py
      flow.py
      policy.py
      migration.py
      proposal.py

    cli/
      contract_check.py
      contract_pack.py
      contract_proposal_preview.py
      contract_migration_check.py

  contracts/
    artifact_types/
    modules/
    policies/
    flows/
    proposals/
    migrations/
    schemas/

  examples/
  tests/
```

如果你想保留当前 `flowspec/`，也可以逐步迁移：

```text
flowspec/contracts.py      -> contracts/compiler.py + graph_invariants.py
flowspec/proposals.py      -> contracts/proposals.py
flowspec/scheduler.py      -> 暂时保留，但不要扩大 runtime 职责
runtime/effects.py         -> specs/effects.py or contracts/effects.py
runtime/policies.py        -> specs/policy.py
```

---

## 10. CLI 设计

建议新增：

```bash
python scripts/contract_check.py contracts/bundle.json
python scripts/contract_pack.py --flow flow.project_generation@1 --task refactor
python scripts/contract_proposal_preview.py --flow contracts/flows/project_generation.flow.json --proposal proposals/insert_validation.json
python scripts/contract_migration_check.py migrations/project_generation.migration.json
```

CLI 输出必须是 JSON。不要输出人类段落。

标准输出：

```json
{
  "ok": false,
  "diagnostics": [],
  "compiled": null
}
```

---

## 11. Agent Contract Pack

coding agent 不应该读整个仓库。它应该拿到裁剪后的 contract pack。

Contract Pack 包括：

```text
task
allowed_files
denied_files
flow
modules used by flow
artifact types used by modules
policy
migration spec
known diagnostics
allowed graph edits
required checks
golden examples
```

示例输出：

```json
{
  "kind": "ContractPack",
  "task": {
    "kind": "refactor",
    "target": "cgnk.project_generation"
  },
  "allowed_files": [
    "tools/providers/project_generation_contracts.py",
    "tests/concrete_project_benchmark/**"
  ],
  "denied_files": [".git/**", ".env", "secrets/**"],
  "flow": "flow.project_generation@1",
  "required_checks": ["unit", "benchmark_smoke", "contract_compile"]
}
```

---

## 12. 分阶段重构计划

### Phase 0：命名和格式冻结

目标：冻结 machine-first 合同对象名称。

任务：

```text
1. 新增 ArtifactTypeSpec / ModuleContract / FlowSpec / PolicySpec / GraphEditProposal / MigrationSpec schema 草案。
2. 保留旧 FlowSpec validator，不破坏现有测试。
3. 新增 examples/contract_v2。
4. 新增 JSON schema validation test。
```

完成标准：

```text
所有 schema example 都能 json.loads。
所有 example 都能通过基础 schema check。
旧 tests 不回归。
```

### Phase 1：Compiler skeleton

目标：实现 contract compiler 的最小闭环。

任务：

```text
1. loader: 加载 bundle。
2. resolver: resolve module/artifact/policy refs。
3. symbol table: 生成 artifacts/modules/flows/nodes/ports。
4. type checker: 检查 PortEdge 类型。
5. diagnostics: 输出 structured diagnostics。
```

完成标准：

```text
valid flow.project_generation 编译 ok。
错误 edge 返回 CGNK_EDGE_TYPE_MISMATCH。
缺失 module 返回 CGNK_MODULE_NOT_FOUND。
```

### Phase 2：Graph invariant + Policy

目标：让 graph edit 安全。

任务：

```text
1. 检查 input unbound。
2. 检查 multi producer。
3. 检查 graph cycle。
4. 检查 effect vs policy。
5. 检查 capability vs policy。
6. 检查 gates/predicates refs。
```

完成标准：

```text
invalid examples 都能返回稳定错误码。
policy denied write 能返回 CGNK_POLICY_EFFECT_DENIED。
```

### Phase 3：GraphEditProposal

目标：agent 只能提交 graph edit proposal。

任务：

```text
1. apply_graph_edits(flow, proposal) -> preview_flow。
2. proposal schema validation。
3. allowed_edits policy check。
4. preview graph compile check。
5. repair hints。
```

完成标准：

```text
insert_validation proposal 可通过。
错误替换 proposal 被拒绝。
apply 后 FlowSpec 不直接改原文件。
```

### Phase 4：MigrationSpec + Contract Pack

目标：服务 legacy project-generation 系统重构；CTCP 可作为首个 pilot。

任务：

```text
1. migration checker。
2. preserve rule skeleton。
3. contract pack generator。
4. codex prompt generator。
```

完成标准：

```text
project_generation migration spec 可生成 agent_context.contract-pack.json。
```

---

## 13. 最小第一版范围

不要一开始设计所有 legacy 模块。先从 project_generation 做端到端样板。

第一批 ArtifactTypeSpec：

```text
Goal
ProjectSnapshot
ProjectGraph
ImplementationPlan
PatchManifest
ValidationReport
BenchmarkReport
```

第一批 ModuleContract：

```text
module.project.snapshot
module.project.build_graph
module.plan.generate
module.patch.emit
module.patch.validate
module.tests.run
module.benchmark.run
```

第一批 FlowSpec：

```text
flow.project_generation
flow.project_refactor
```

第一批 PolicySpec：

```text
policy.safe_project_generation
policy.safe_project_refactor
```

第一批 MigrationSpec：

```text
migration.project_generation
```

---

## 14. 最终判断

你的问题不是“每个模块要不要接口”。

答案是：

```text
每个可组合模块都要统一连接接口。
但接口不是模块对模块接口，而是 port/artifact/capability/effect/policy 组成的连接面。
```

最终架构应该保证：

```text
1. 模块不直接依赖上下游模块。
2. 模块只暴露 typed input/output ports。
3. FlowSpec 只连接 ports。
4. PolicySpec 限制 effect/capability/edit 权限。
5. GraphEditProposal 是 agent 唯一修改 flow 的入口。
6. Compiler 验证所有连接、移动、替换是否合法。
7. Diagnostics 给 agent 明确错误码和 repair hints。
8. MigrationSpec 保护 legacy 系统重构边界。
```

这就是 CovenantGraph Nexus Kernel 可重组流水线合同系统的核心设计。


## Final baseline hardening included in this bundle

This final bundle tightens the design into a compiler-ready baseline:

```text
1. Artifact and module references are canonical `id@version` refs.
2. Flow endpoints are directional: SourceEndpoint cannot be flow_output, TargetEndpoint cannot be flow_input.
3. Gate predicates are structured through `predicate.schema.json`.
4. Graph edit proposals are op-specific; each op has required fields.
5. `flow.project_refactor@1` no longer uses provider/network planning; it uses `module.plan.generate.contract_only@1`.
6. `flow.project_generation@1` keeps provider planning through `module.plan.generate.provider@1` under a policy that allows it.
7. ContractPack, CompileResult, and CompiledContractBundle schemas are included.
8. `scripts/validate_bundle.py` is a dependency-light reference semantic checker for refs, types, policy effects, required inputs, output binding, cycles, and gate node refs.
```

Minimum acceptance for using this as the CovenantGraph Nexus Kernel base:

```text
python scripts/validate_bundle.py
# flow.project_generation@1: OK errors=0
# flow.project_refactor@1: OK errors=0
```
