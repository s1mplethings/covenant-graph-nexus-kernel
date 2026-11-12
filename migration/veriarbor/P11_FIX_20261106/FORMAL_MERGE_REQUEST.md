# P11 正式合入申请（已批准并执行）

```text
REQUEST_STATUS: APPLIED_AND_VERIFIED
FORMAL_SOURCE_MODIFIED: YES（仅 5 个 P11 文件）
PATCH_SHA256: 3f7caed58227d25685ccd0f1792955f2420260e28020e55f10559b41696f237c
PATCH_APPLY_MODE: git -c core.autocrlf=false apply -p1
EXECUTION_EVIDENCE: FORMAL_INTEGRATION_RESULT.json
```

用户已明确批准（“都批准”），补丁已应用并验证。正式交付认可仍暂停，等待真实 trust anchor 与用户签名授权。

## 1. 迁移计划

```text
SOURCE_WORKSPACE:
  C:\Users\sunom\AppData\Local\Temp\opencode\p11fix
  （隔离测试工作区；不作为正式源码）

DESTINATION_WORKSPACE:
  F:\CGKN-LeanLoop-V1-20261101
  branch: codex/leanloop-v1-20261101
  HEAD:   0bd7134ade87cb6ece13f8f7868860cd2c3ba67c

SOURCE_COMMIT:
  none（隔离副本不是 Git 仓库；以已测试文件 SHA-256 为准）

DESTINATION_COMMIT:
  0bd7134（工作树另有 525 个 tracked modified、3308 个 untracked；
  本次只修改 3 个目标文件并新增 2 个文件，不触碰其他修改）

PATCH_SHA256:
  3f7caed58227d25685ccd0f1792955f2420260e28020e55f10559b41696f237c

AFFECTED_FILES:
  M cgkn/state/provenance.py
  M scripts/final_delivery_truth.py
  M scripts/production_candidate_provenance.py
  A cgkn/state/release_authorization.py
  A tools/sign_release_authorization.py

REGRESSION_TESTS:
  security_tests/p11_p19_security_tests.py -> 24/24 PASS, exit 0
  provenance regression -> 112 passed

ROLLBACK_METHOD:
  1. 恢复 pre_apply_backup 中的 3 个文件原始字节；
  2. 删除新增的 2 个文件；
  3. 校验 3 个文件 SHA-256 回到合入前值；
  4. 不使用 git checkout/reset/clean，避免破坏其他未提交修改。

EVIDENCE_INVALIDATION:
  M12 源码/ZIP、23 个 Worker 来源、B10/B11 历史证据不因本补丁失效；
  7 个 Agent 来源的授权/review 必须在真实 trust anchor 下重新签发；
  正式 final delivery truth 必须在 trust context 下重跑；
  FINAL_DELIVERY_SECURITY_HOLD 保持 PAUSED。
```

## 2. 精确修改清单

| 文件 | 类型 | 合入前 SHA-256 | 合入后 SHA-256 |
|---|---|---|---|
| `cgkn/state/provenance.py` | 修改 | `8055c145f81b314f7bc3e2c909f2876c6dc931bb9d5a2f3213f85efe5112c859` | `55f5ee9c917d451663021d3c9ef5ad18142e9ca91c4b307272b2e459767ba837` |
| `scripts/final_delivery_truth.py` | 修改 | `a857a159bd3f6f7b316d40d7384887889775eadc6dbc45cf21320aae7dc3813e` | `02e1cfd39ec262d806669ba7519f047bd84c35c0262924bcb535024d5a1fafd7` |
| `scripts/production_candidate_provenance.py` | 修改 | `ea2fdd607b8237e5dbcd79119d4d2f3ef9862ef657f8b913d3a9ef0f11c2676a` | `ac31aad7430f28a5dbcede167f952100f41a21048f04b8b79115b0bec385d5aa` |
| `cgkn/state/release_authorization.py` | 新增 | 不存在 | `d839298f8c0cab161327377cb757e10b9bffec7af3332ffe11dde80847e6bc44` |
| `tools/sign_release_authorization.py` | 新增 | 不存在 | `3f8ff161cc9fa7282d3134c40bc9a93879f4522ffa1fc005632f76eb4c67979c` |

## 3. 已完成的只读检查

```text
git apply --check（core.autocrlf=false）: exit 0
应用后 5 个文件与隔离测试文件: 逐字节一致
反向应用后 3 个原文件: 逐字节恢复
M12 candidate main.py: 711c0519...（一致）
M12 ZIP: f6eb10fb...（一致）
ZIP/manifest: 38/38 entries（一致）
goal_acceptance.json: c3d55cfd...（未改写）
FINAL_DELIVERY_SECURITY_HOLD: PAUSED
```

## 4. 补丁行尾问题修正

旧的 `87f5c845...` 补丁是 LF 归一化补丁。当前 Git 配置 `core.autocrlf=true`，直接应用会把 `provenance.py` 和两个新文件写成 CRLF，导致实际字节与已测试文件不一致。

当前补丁 `3f7caed5...` 保留每个文件的原始行尾：

- `provenance.py`：LF
- `scripts/final_delivery_truth.py`：CRLF
- `scripts/production_candidate_provenance.py`：CRLF
- 两个新文件：LF

应用方式固定为：

```powershell
git -c core.autocrlf=false -C F:\CGKN-LeanLoop-V1-20261101 `
  apply -p1 migration\veriarbor\P11_FIX_20261106\P11_FIX_MINIMAL.patch
```

旧补丁保留为：

```text
P11_FIX_MINIMAL_LEGACY_87f5.patch
SHA-256: 87f5c845e9ce37eca7b7f64338723ebf16d2964e1843ebf27b8023ad7abfca70
```

## 5. 正式合入前的备份与回退

合入前先生成：

```text
F:\CGKN-LeanLoop-V1-20261101\migration\veriarbor\P11_FIX_20261106\pre_apply_backup\
  cgkn\state\provenance.py
  scripts\final_delivery_truth.py
  scripts\production_candidate_provenance.py
  PRE_APPLY_MANIFEST.json
```

回退：

```powershell
# 恢复 3 个文件（使用备份，不使用 git checkout/reset）
Copy-Item pre_apply_backup\cgkn\state\provenance.py cgkn\state\provenance.py -Force
Copy-Item pre_apply_backup\scripts\final_delivery_truth.py scripts\final_delivery_truth.py -Force
Copy-Item pre_apply_backup\scripts\production_candidate_provenance.py scripts\production_candidate_provenance.py -Force
Remove-Item cgkn\state\release_authorization.py -ErrorAction SilentlyContinue
Remove-Item tools\sign_release_authorization.py -ErrorAction SilentlyContinue
```

回退后校验 `PRE_APPLY_MANIFEST.json` 中的 3 个哈希。

## 6. 请求批准

请明确批准以下操作：

1. 在 `F:\CGKN-LeanLoop-V1-20261101` 建立 `pre_apply_backup`。
2. 使用 `core.autocrlf=false` 应用 `P11_FIX_MINIMAL.patch`。
3. 只在正式仓库修改上述 5 个文件。
4. 不修改冻结 candidate、ZIP、历史证书、`FINAL_DELIVERY_SECURITY_HOLD.json`。
5. 合入后运行 P01–P19 与 112 项回归，不重跑 M12 全量。

未获批准前，不执行任何正式工作区写入。
