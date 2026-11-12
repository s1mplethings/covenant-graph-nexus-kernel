# 开发工作区切换方案（未执行切换）

```text
CURRENT_WORKSPACE: D:\VeriArbor_（当前 OpenCode 副本，无 .git）
FORMAL_HOST_WORKSPACE: F:\CGKN-LeanLoop-V1-20261101（P11 正式 host worktree）
FORMAL_LIBRARY_REPOSITORY: D:\VeriArbor（新 VeriArbor 库仓库）
ISOLATED_EXPERIMENT_COPY: D:\VeriArbor_
RECOMMENDED_NOW: F:\CGKN-LeanLoop-V1-20261101（P11 收尾）
RECOMMENDED_LATER: D:\VeriArbor（完成 baseline 提交与状态核对后）
```

## 1. 三个目录的真实身份

### `F:\CGKN-LeanLoop-V1-20261101`

- Git 链接工作树；common dir `D:/CGKN/.git`。
- branch `codex/leanloop-v1-20261101`，HEAD `0bd7134`。
- 当前有 525 个 tracked modified、3308 个 untracked。
- P11 五个文件已合入工作树，但尚未 commit。
- M12/交付证据在 `migration/veriarbor/` 和 `F:\CGKN-ITER-132`。
- 这是 **P11 正式收尾目录**。

### `D:\VeriArbor`

- 独立 Git 仓库，branch `main`，HEAD `4d2f45f`（Initial commit）。
- remote `https://github.com/s1mplethings/VeriArbor.git`。
- README 已修改；`src/`、`tests/`、`docs/`、`tools/`、`governance/`、`reports/` 等约 389 个文件未跟踪。
- `MIGRATION_RECEIPT.json` 仍为：

```text
product_status = PRODUCT_NOT_READY
M8-M11 = VERIFIED
M12 = FAILED
```

- `REGRESSION.json` 为 `PASS_FOR_RECORDED_SCOPE`，只代表记录范围，不等于产品验收。
- 这是 **新的 VeriArbor 库仓库**，不是当前 P11 host 的替代品，也不是 M12 已验收仓库。

### `D:\VeriArbor_`

- 无 `.git`。
- 与 `D:\VeriArbor` 比较：386 个文件哈希一致；缺少 9 个 M12 acceptance tools；没有其他差异。
- 是当前 OpenCode 的 **隔离实验副本**，不是正式仓库。

## 2. 切换原则

1. 不删除、不 reset、不 clean 任何工作树。
2. 不把 `D:\VeriArbor` 的 `.venv`、build、dist、缓存、run store、证据目录、私钥或临时授权复制到正式源码。
3. 不通过修改 `MIGRATION_RECEIPT.json` 来“完成”迁移；状态必须由证据支持。
4. P11 收尾期间继续使用 `F:\CGKN-LeanLoop-V1-20261101`。
5. 新库开发切换前，必须先给 `D:\VeriArbor` 建立受控 baseline，而不是把 389 个未跟踪文件直接当成已验收源码。

## 3. 推荐的切换顺序

### 阶段 1：P11 收尾（当前）

- 在 F: 完成 P11 五文件 commit（需用户批准）。
- 保留证据目录在 `migration/veriarbor/P11_FIX_20261106`，不加入 Git。
- 建立受保护 verifier 快照和 Windows trust anchor。
- 完成正式 release authorization 后，才讨论解除安全暂停。

### 阶段 2：新库 baseline（P11 收尾后）

在 `D:\VeriArbor` 新建分支，例如：

```powershell
git -C D:\VeriArbor switch -c codex/veriarbor-baseline-20261106
```

然后分批审查并提交未跟踪内容：

```text
1. src/veriarbor + pyproject.toml + README.md
2. tests/
3. docs/
4. tools/（排除 acceptance 临时输出）
5. governance/、reports/（先确认是否属于证据而非源码）
6. FINAL_REPORT.md、WORK_LOG.md、MIGRATION_RECEIPT.json、REGRESSION.json
```

要求：

- 不 `git add .`；每批审查后单独 commit。
- 不提交 `.venv/`、`build/`、`dist/`、`__pycache__/`、`.pytest_cache/`。
- 不提交私钥、token、run store、临时授权。
- 每批提交后运行对应测试；保留 `REGRESSION.json` 的 recorded scope 语义。
- 只有实际证据支持后，才更新 `MIGRATION_RECEIPT.json`；不能仅改状态 JSON。

### 阶段 3：OpenCode 工作目录切换

```text
现在：F:\CGKN-LeanLoop-V1-20261101
P11 收尾完成后：F: 继续 host 维护；D:\VeriArbor 用于新库开发
D:\VeriArbor_：保留为隔离实验副本，不再作为主开发目录
```

切换 OpenCode 到 `D:\VeriArbor` 的条件：

1. `D:\VeriArbor` 的 baseline 已按逻辑分批 commit。
2. 工作树不再有大量未审查的 untracked 源码。
3. `M12=FAILED` 与 host `M12=VERIFIED` 的差异已核对并记录。
4. 关键测试在该仓库上实际通过。
5. 没有敏感文件被带入 Git。

## 4. 未提交工作保护

- F: 已有 `pre_apply_backup`、P11 证据和状态快照；不要删除。
- D:\VeriArbor 的未跟踪文件在 baseline 前不要移动或覆盖。
- 如需实验，优先创建新的 Git worktree 或临时副本，不要在原目录执行 reset/clean。
- 当前 F: 工作树包含大量历史修改；任何操作都应只针对明确文件清单。

## 5. 当前建议

```text
RECOMMENDED_DEVELOPMENT_DIRECTORY: F:\CGKN-LeanLoop-V1-20261101
REASON: P11 尚未 commit，trust anchor 尚未部署，正式交付仍暂停。
DO_NOT_SWITCH_YET: D:\VeriArbor（M12=FAILED，389 个 untracked，baseline 未建立）
KEEP_COPY: D:\VeriArbor_（实验与对比材料）
```
