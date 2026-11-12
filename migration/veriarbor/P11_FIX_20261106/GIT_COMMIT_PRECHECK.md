# P11 Git 提交预检报告（未 stage，未 commit）

```text
GIT_COMMIT_READINESS: CONDITIONAL
STAGED_DIFF_STATUS: NOT_STAGED / INDEX_EMPTY
HEAD: 0bd7134ade87cb6ece13f8f7868860cd2c3ba67c
BRANCH: codex/leanloop-v1-20261101
INDEX_STAGED_FILES: 0
GIT_ADD_EXECUTED: NO
GIT_COMMIT_EXECUTED: NO
GIT_PUSH_EXECUTED: NO
```

## 1. 待提交文件清单

```text
cgkn/state/provenance.py                       (当前 untracked)
cgkn/state/release_authorization.py            (新文件)
scripts/final_delivery_truth.py                (M)
scripts/production_candidate_provenance.py     (M)
tools/sign_release_authorization.py            (新文件)
```

当前 `git status --porcelain`：

```text
 M scripts/final_delivery_truth.py
 M scripts/production_candidate_provenance.py
?? cgkn/state/provenance.py
?? cgkn/state/release_authorization.py
?? tools/sign_release_authorization.py
```

Index 中没有任何其他文件：

```text
git diff --cached --name-status -> 空
staged_count = 0
```

## 2. 为什么 `provenance.py` 原本是 untracked

- 当前分支 `HEAD` 中没有 `cgkn/state/provenance.py`。
- `git log HEAD -- cgkn/state/provenance.py` 为空：当前分支从未提交过该文件。
- `git log --all` 显示它曾在其他分支被加入：
  - `168b537`（codex/leanloop-main-integration-20261101）
  - `61f5255`（codex/leanloop-selfcheck-20261101）
- 上述历史版本只有 183 行、12,245 字节。
- 当前工作树版本为 617 行、42,469 字节。
- 与历史版本相比新增 436 行、删除 2 行；与 `rollback/step-33` 版本相比新增 153 行、删除 4 行。
- 结论：当前文件**不是从当前 HEAD 继承的简单修改**，而是包含此前未提交的 M12 provenance 实现（Worker import、AuthorizedAgentSource、delivery_sources 等）加上 P11 加固。

因此：

```text
EXISTING_UNTRACKED_SOURCE_RISKS: HIGH
```

提交 `provenance.py` 不是“只提交 P11 diff”；它会第一次把完整的 provenance 实现加入当前分支。

## 3. 五个文件的差异范围

| 文件 | 类型 | 当前行数 | 相对 HEAD | 说明 |
|---|---|---:|---|---|
| `cgkn/state/provenance.py` | 当前分支新文件 | 617 | 新增 617 | 包含 M12 provenance + P11；P11 相对合入前 530 行为 +95/-8 |
| `cgkn/state/release_authorization.py` | 新文件 | 230 | 新增 230 | 纯 P11 |
| `scripts/final_delivery_truth.py` | 修改 | 83 | +9/-2 | 包含此前 `production_provenance_ref` 透传 + P11 trust context |
| `scripts/production_candidate_provenance.py` | 修改 | 711 | +166/-0 | 包含此前 project-session provenance + P11 trust context |
| `tools/sign_release_authorization.py` | 新文件 | 178 | 新增 178 | 纯 P11 |

单次提交总规模：

```text
+1200 行 / -2 行，5 个文件
```

### 混合范围说明

- `provenance.py`：当前分支首次加入完整 provenance 实现。
- `production_candidate_provenance.py`：包含 `_project_session_projection`、`produce_project_session`、`_inspect_project_session` 等此前未提交的 M12 project-session 代码。
- `final_delivery_truth.py`：包含此前未提交的 `production_provenance_ref` 透传。

因此：

```text
不能把单次五文件提交描述为“仅 P11 变更”。
```

## 4. 敏感信息与调试代码检查

对五个文件执行了以下扫描：

```text
BEGIN PRIVATE KEY / api_key / gateway_token / sk-... / password= / secret=
print( / breakpoint / pdb.set_trace / TODO / FIXME / localhost / 127.0.0.1
绝对路径 / Temp / fixture / p11fix / CGKN-ITER / iter132-promotion
```

结果：

- 未发现真实私钥、API Key、Gateway Token 或凭据。
- 未发现调试断点、临时打印或 TODO/FIXME。
- `tools/sign_release_authorization.py` 中的 `password=None` 只是读取未加密 PEM 的 API 参数；`print` 是正常 CLI 输出。
- 未发现硬编码测试路径或 fixture 路径。

## 5. 与已测试版本的一致性

五个文件与 `P11_FIX_20261106/files/` 中的已测试副本：

```text
cgkn/state/provenance.py                    MATCH
cgkn/state/release_authorization.py         MATCH
scripts/final_delivery_truth.py             MATCH
scripts/production_candidate_provenance.py  MATCH
tools/sign_release_authorization.py         MATCH
```

正式集成后：

```text
P01–P19: 24/24 PASS
112 项回归: passed
```

证据：

```text
P11_P19_RESULTS_FORMAL.json
REGRESSION_FORMAL.txt
FORMAL_INTEGRATION_RESULT.json
```

## 6. M12 冻结内容检查

```text
candidate main.py = 711c051954513eab78261062f46228f7ea757a5857a5624ffd487787697d4237
bundle             = f6eb10fb8283b250c28796e0ac95308bb6135e8434f6eef742acc58fbb469f8f
goal_acceptance    = c3d55cfd3cb335948728f1153c7dbb675204760574e46c3ad3fdaf83dbd635aa
FINAL_DELIVERY_SECURITY_HOLD = PAUSED
```

提交这五个文件不会改变 candidate 或 ZIP。

## 7. 建议的提交策略

### 方案 A（推荐，便于审计）

两个提交，仍然只涉及这五个文件：

1. **baseline commit**
   - 保存 P11 之前的现状：`provenance.py` 530 行版本、两个脚本的 P11 前版本。
   - 明确说明这是此前未提交的 M12 provenance 实现基线，不是 P11 安全修复。
2. **P11 commit**
   - 应用 P11 patch，提交 3 个修改 + 2 个新文件。
   - 这个提交的 diff 才是纯 P11。

优点：P11 的安全变更可以被单独审查、单独回退。
代价：需要先创建一个 baseline commit，且 baseline 仍包含此前未跟踪的 M12 代码。

### 方案 B（单次提交，但必须明确范围）

一次提交五个最终文件，但 commit message 必须明确：

```text
This commit both:
1. adds the previously untracked M12 provenance implementation; and
2. applies the P11 signed-release authorization hardening.
P11-specific diff is P11_FIX_MINIMAL.patch.
```

不要让审查者误以为这是纯 P11 提交。

### 不推荐

- `git add .` / `git add -A`
- 把 `migration/veriarbor/` 证据目录整体加入 Git
- 提交 `D:\VeriArbor` 的 `.venv`、build、dist、run store 或临时授权
- 在没有 baseline 的情况下声称单次提交是 P11-only

## 8. 当前结论

```text
GIT_COMMIT_READINESS: CONDITIONAL
原因: 五个文件与测试版本一致，但 provenance.py 及两个脚本包含此前未提交的 M12 provenance 代码；
      需要用户选择“两提交基线+P11”或“单次提交并明确混合范围”。
INDEX: 空
STAGED: 否
```

等待用户批准后才能执行 `git add` 和 `git commit`；不得 push。
