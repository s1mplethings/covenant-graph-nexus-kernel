# F:\CGKN-LeanLoop-V1-20261101 → D:\VeriArbor 迁移分析（只读，未执行）

```text
ANALYSIS_STATUS: COMPLETE
MIGRATION_EXECUTED: NO
D:\VeriArbor MODIFIED: NO
OLD MIGRATION_RECEIPT MODIFIED: NO
NEW PAID PROVIDER CALLS: 0
```

## 1. 两个仓库的真实关系

这不是两个完整仓库之间的整体复制，而是：

```text
D:\VeriArbor\src\veriarbor
  = 纯策略库（Block/Port/Contract/Certificate/Adapter/Verification 等）

F:\CGKN-LeanLoop-V1-20261101\cgkn\adapters\veriarbor
  = host 适配层（run store、acceptance、DAG、provenance、provider 边界）

F:\CGKN-LeanLoop-V1-20261101\requirements-veriarbor.txt
  = 明确要求：在同一个隔离环境中 editable 安装本地 VeriArbor checkout，
    “Never copy package sources.”
```

因此正确关系是：

- `D:\VeriArbor` 是库源；
- F: 是 host 集成方；
- 两者通过 editable install / `requirements-veriarbor.txt` 连接；
- 不应把 `src/veriarbor` 复制进 F:，也不应把 host 的 provenance/run store 复制进库。

## 2. 代码对应关系

### 2.1 host adapter → pure library

| F: host adapter | 引用的 D: library 模块 |
|---|---|
| `block_adapter.py` | `block`, `port`, `contract`, `effects`, `variant`, `compatibility`, `dedup`, `expansion`, `model` |
| `substitution_adapter.py` | `block`, `certificate`, `contract`, `effects`, `model`, `port`, `substitution`, `variant` |
| `certificate_adapter.py` | `lifecycle`, `model` |
| `verification_adapter.py` | `dedup`, `model` |
| `acceptance_adapter.py` | `verification` |
| `tree_adapter.py` | `verification` |
| `dag_adapter.py` | `scheduling` |
| `backtracking_adapter.py` | `learning` |
| `provider_novelty_adapter.py` | `dedup`, `model` |
| `guidance_adapter.py` | `model` |

### 2.2 host 直接引用 pure library

```text
cgkn/protocol/progress.py       -> veriarbor.learning
cgkn/protocol/repair.py         -> veriarbor.learning
cgkn/protocol/review_policy.py  -> veriarbor.review
```

### 2.3 仅 host 使用的层

以下 adapter 是 host 权威/运行边界，不是纯库，不应迁移到 `D:\VeriArbor`：

```text
acceptance_adapter.py
accounting_adapter.py
allocation_adapter.py
corpus_adapter.py
event_adapter.py
run_store_adapter.py
substitution_adapter.py 的 host 绑定部分
```

### 2.4 当前 host 未引用的 pure library 模块

```text
adapter.py
graph.py
protocols.py
search.py
```

这些属于可选/实验 API 或库内组合，不是当前 host 的 V1 集成路径。README 也明确 search/learning/global graph 是可选兼容/实验 API，不是 V1 readiness gate。

## 3. 源码同步状态

`D:\VeriArbor\REGRESSION.json` 记录了 `library_sources` 与 `host_sources` 的哈希。

### 3.1 library sources

```text
21 个库源文件
21/21 与当前 D:\VeriArbor\src\veriarbor 哈希一致
0 个缺失 / 0 个不一致
```

结论：当前 `D:\VeriArbor` 库源与已记录回归时的库源一致。

### 3.2 host sources

```text
376 个 host 源文件
373/376 与当前 F: 哈希一致
3 个不一致：
  cgkn/state/provenance.py
  scripts/final_delivery_truth.py
  scripts/production_candidate_provenance.py
```

这 3 个正是 P11 变更：

```text
provenance.py
  old regression: 4b88022f...
  current P11:    55f5ee9c...

final_delivery_truth.py
  old regression: c29d8a32...
  current P11:    02e1cfd3...

production_candidate_provenance.py
  old regression: ea2fdd60...
  current P11:    ac31aad7...
```

因此：

- 除了 P11 的三个 host 文件，F: 与已记录迁移源是同步的；
- P11 是 host 安全层变更，不是 `D:\VeriArbor` 库模块变更；
- 不需要把 P11 的 `release_authorization.py` 或 provenance 逻辑复制进库。

## 4. 已验证与未验证状态

### 4.1 已记录验证

```text
library_sources: 21/21 与记录一致
REGRESSION.json status: PASS_FOR_RECORDED_SCOPE
checks: 83 个
  PASS: 62
  FAIL: 21（历史失败保留；部分由 v2/v3 替代检查修复）
incomplete_checks: host-original-interpreter
product_acceptance: NOT_VERIFIED_BY_THESE_CHECKS
```

`MIGRATION_RECEIPT.json`：

```text
status = CORE_MIGRATION_CHECKPOINT
product_status = PRODUCT_NOT_READY
M1-M11 = VERIFIED
M12 = FAILED
host_switches = 55
```

### 4.2 已验证（host 侧）

```text
P11 commit: cf5c754b5e2ed3991010fb1dc91b8f3e19adb3d2
P01-P19: 24/24 PASS
112 项 provenance 回归: passed
M12 candidate/ZIP 未改变
```

### 4.3 尚未验证

```text
D:\VeriArbor 的 M12 = FAILED（旧记录，不能直接改写）
product_acceptance = NOT_VERIFIED_BY_THESE_CHECKS
21 个历史 FAIL 检查仍需保留，不得抹掉
完整 Provider/外部资产回归仍有 out-of-scope failures
正式 trust anchor / release signing 未部署
D:\VeriArbor 389 个未跟踪文件尚未形成 baseline commit
```

## 5. 最小迁移方案（建议，未执行）

### 原则

- 不覆盖 `D:\VeriArbor`。
- 不修改旧 `MIGRATION_RECEIPT.json` 的 `M12=FAILED`。
- 不把 host 的 provenance/run store/安全模块复制进库。
- 只建立库的受控 baseline，并新增独立验收记录。

### 步骤 1：D:\VeriArbor baseline

在 `D:\VeriArbor` 新建分支，按逻辑分批提交 389 个未跟踪文件：

```text
1. src/veriarbor + pyproject.toml + README.md
2. tests/
3. docs/
4. tools/
5. governance/ + reports/（先确认证据/源码属性）
6. FINAL_REPORT.md、WORK_LOG.md、MIGRATION_RECEIPT.json、REGRESSION.json
```

不提交：

```text
.venv/、build/、dist/、__pycache__/、.pytest_cache/
私钥、token、.env、run store、临时授权、候选包
```

### 步骤 2：新增版本化验收记录

不要修改旧 `MIGRATION_RECEIPT.json`。新增例如：

```text
D:\VeriArbor\MIGRATION_ACCEPTANCE_P11_20261106.json
```

内容至少包括：

```text
library_sources_match: 21/21
host_p11_commit: cf5c754b5e2ed3991010fb1dc91b8f3e19adb3d2
host_p11_files:
  - cgkn/state/provenance.py
  - scripts/final_delivery_truth.py
  - scripts/production_candidate_provenance.py
  - cgkn/state/release_authorization.py
  - tools/sign_release_authorization.py
host_source_sync: 373/376 matches; 3 intentional P11 changes
p11_tests: 24/24 PASS
provenance_regression: 112 passed
host_m12: VERIFIED (separate host evidence)
library_migration_receipt: M12=FAILED (historical, retained)
product_acceptance: NOT_VERIFIED
trust_anchor: PENDING_TRUST_ANCHOR
new_paid_provider_calls: 0
```

### 步骤 3：库 baseline 验证

在 D:\VeriArbor baseline commit 后运行一次：

```powershell
D:\VeriArbor\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

以及 host 侧最少的集成测试：

```text
tests/test_veriarbor_block_adapter.py
tests/test_veriarbor_substitution_provenance.py
P11 的 24 项安全测试
112 项 provenance 回归
```

不重跑 M12 B01–B11，不调用付费 Provider。

### 步骤 4：切换开发目录

- P11/trust anchor 收尾完成前：继续使用 F:。
- D:\VeriArbor baseline commit 完成后：切换 OpenCode 到 D:\VeriArbor 做库开发。
- F: 保留为 host 集成/P11 安全目录。
- D:\VeriArbor_ 保留为实验副本。

## 6. 迁移风险

| 风险 | 说明 |
|---|---|
| 混合状态 | D:\VeriArbor `REGRESSION.json` 是 PASS_FOR_RECORDED_SCOPE，但 `MIGRATION_RECEIPT` M12=FAILED；不能只改 JSON |
| 21 个历史 FAIL | 不得删除或改写成 PASS；只能用新版本化记录说明哪些已被 v2/v3 替代 |
| 389 个未跟踪文件 | 未形成 baseline；直接切过去会把未审查内容当正式源码 |
| host/P11 与库混淆 | P11 是 host 安全层，不是库模块；不要复制进 `src/veriarbor` |
| 依赖安装 | `requirements-veriarbor.txt` 要求 editable 安装本地 checkout，不能复制包源 |
| trust anchor | 仍未部署；不得恢复最终交付认可 |

## 7. 结论

```text
MINIMAL_MIGRATION_NEEDED:
  1. D:\VeriArbor baseline commit（分批，不覆盖）
  2. 新增版本化验收记录，不改旧 FAILED
  3. 库测试 + host 集成测试一次
  4. 之后切换开发目录

NO_CODE_COPY_REQUIRED:
  21/21 library sources already match recorded regression.
  P11 changes are host-only and already committed in F:.
```

等待用户批准实际迁移。
