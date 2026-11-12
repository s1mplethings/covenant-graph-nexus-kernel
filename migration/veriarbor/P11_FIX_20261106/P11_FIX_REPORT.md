# VeriArbor P11 自授权漏洞修复报告（隔离验证）

```text
IMPLEMENTATION_STATUS: IMPLEMENTED_NOT_TRUSTED
FORMAL_DELIVERY_RECOGNITION: PAUSED_PENDING_TRUST_ANCHOR
FORMAL_SOURCE_MODIFIED: NO
FROZEN_CANDIDATE: 711c051954513eab78261062f46228f7ea757a5857a5624ffd487787697d4237
FROZEN_BUNDLE: f6eb10fb8283b250c28796e0ac95308bb6135e8434f6eef742acc58fbb469f8f
NEW_PAID_PROVIDER_CALLS: 0
NEW_PROVIDER_COST: 0
```

## 1. P11 根因与真实攻击路径

修复前，`AuthorizedAgentSource` 的授权、审查和交付内容处于同一可写信任域：

1. Agent 修改 `README.md` 等交付字节。
2. Agent 重写 `agent_authorizations/*.json`，把 `authorized_by` 写成 `"user"`。
3. Agent 重写 `agent_reviews/*.json` 和 B10/B11 引用。
4. Agent 更新 `source_imports` 中的新哈希。
5. `delivery_sources` 接受新字节。

根因不是某一个字段拼写错误，而是：

- `authorized_by="user"` 只是普通字符串，没有密码学或 OS ACL 依据。
- 授权、review、B10、B11 都在 Agent 可写目录。
- B10 只校验 `source_sha256_at_verification` 对 `main.py` 的哈希，没有逐文件校验
  `relevant_section_hashes` 中的 README、TEST_PLAN、测试文件。
- 因此任何拥有 run store 写权限的执行者都能“自写授权、自写审查、自验收”。

## 2. 修改后的信任边界

新增一次性、逐交付批次的 Ed25519 签名 release authorization：

- 私钥必须由 Agent 无法读取/调用的独立主体持有。
- 验签公钥 trust anchor 必须位于 run store 和候选工作区之外。
- 签名绑定：
  - release id、logical task id、scope、nonce、有效期；
  - 每个交付文件的规范化相对路径与 SHA-256；
  - 真实 `author_type`（Worker / Agent）；
  - Agent 文件的授权 JSON、review JSON、B10、B11 精确哈希；
  - B10 对每个已认证文件的 `relevant_section_hashes["<file>#full"]`；
  - 签名者 key id 与 authority id。
- 没有 trust anchor 或没有签名授权时 fail closed：`PENDING_TRUST_ANCHOR`。
- Worker-only 交付仍保留原有 Worker receipt 要求，不因修复被删除或放宽。
- Agent 作者身份仍记录为 `agent`，不会被改写成 Worker。

## 3. 实际修改的文件与函数

| 文件 | 变更 |
|---|---|
| `cgkn/state/release_authorization.py` | 新增：canonical payload、trust anchor 加载、Ed25519 验签、manifest/artifact/时间窗/nonce 校验 |
| `cgkn/state/provenance.py` | `ProvenanceGate.__init__` 增加 trust context；新增 `verify_release_authorization`；`_authorized_agent_origin` 绑定签名、授权/review/B10/B11 哈希与 B10 逐文件 section；`delivery_sources` 在出现 Agent 来源时强制验签，并校验 Worker author_type |
| `scripts/production_candidate_provenance.py` | `configure_release_trust`；`inspect` / `_project_session_projection` / `produce_project_session` 透传 trust context |
| `scripts/final_delivery_truth.py` | `evaluate` 新增 `release_trust_anchor` / `release_authorization`，并在每次调用时重置/配置 controller trust context |
| `tools/sign_release_authorization.py` | 新增：在受保护环境运行的签名工具；验签器不导入它，也不需要私钥 |

补丁：`P11_FIX_MINIMAL.patch`，SHA-256 `3f7caed58227d25685ccd0f1792955f2420260e28020e55f10559b41696f237c`。
应用方式：`git -c core.autocrlf=false apply -p1`。已验证应用后的 5 个文件与隔离测试文件逐字节一致，反向应用可逐字节恢复原文件。
旧补丁 `87f5c845...` 保留为 `P11_FIX_MINIMAL_LEGACY_87f5.patch`；旧补丁在 `core.autocrlf=true` 下会把 `provenance.py` 和两个新文件写成 CRLF，与测试字节不一致，因此不再作为正式合入补丁。

## 4. 实际测试结果

执行：

```powershell
python security_tests/p11_p19_security_tests.py
```

结果：**24/24 PASS，exit 0**。

| ID | 场景 | 预期 | 实际 |
|---|---|---|---|
| P01 | Agent 来源缺少有效授权 | REJECT | REJECT |
| P02 | 修改已授权 Agent 源文件 | REJECT | REJECT |
| P03 | Agent 冒充 Worker | REJECT | REJECT |
| P04 | B11 独立观测为假 | REJECT | REJECT |
| P05 | 无效 Worker receipt | REJECT | REJECT |
| P06 | 交付文件哈希不一致 | REJECT | REJECT |
| P07 | 重放旧候选哈希 | REJECT | REJECT |
| P08 | 删除 B10 证据 | REJECT | REJECT |
| P09 | 无关 `production_provenance_ref` | REJECT | REJECT |
| P10 | 合法 Agent 来源 + 有效签名 + 验收 | ACCEPT | ACCEPT |
| P11 | 改 README 后自行重写授权/review/import | REJECT | REJECT |
| P12 | 改写已签名授权字节 | REJECT | REJECT |
| P13 | 替换公钥配置/验签策略 | REJECT | REJECT |
| P14 | 改 README/TEST_PLAN/test，main.py 不变 | REJECT | REJECT |
| P15 | 改 B11 并重算普通哈希 | REJECT | REJECT |
| P16 | 重放其他 candidate 的授权 | REJECT | REJECT |
| P17 | 改 ZIP 字节，旧 manifest/授权不变 | REJECT | REJECT |
| P18 | 私钥不在 Agent 工作区/run store，验签器无私钥 | REJECT（伪造签名被拒绝） | REJECT |
| P19 | Agent 改策略/公钥/验签器 | REJECT | REJECT |
| N01 | 合法签名批次 | ACCEPT | ACCEPT |
| N02 | 无 trust anchor | REJECT | REJECT |
| N03 | 缺少签名授权 | REJECT | REJECT |
| N04 | Worker-only 兼容路径 | ACCEPT | ACCEPT |
| N05 | 正式 production provenance 路径 | ACCEPT | ACCEPT |

关键证据：

- P11 修复前旧 harness：`ACCEPT`（`P11_SELF_AUTHORIZATION_RESULT_BEFORE_FIX.json`）。
- P11 修复后旧 harness：`REJECT`，原因 `PENDING_TRUST_ANCHOR`（`P11_OLD_HARNESS_AFTER_FIX.json`）。
- P11 修复后带锚点/合法签名基线：`REJECT`，原因
  `authorization does not bind the delivered manifest`（`P11_P19_RESULTS.json`）。

既有回归测试：

```powershell
python -m pytest -q -p no:pytest-qt tests/state/test_worker_source_import.py tests/state/test_provenance_v5.py tests/state/test_provenance_read_snapshot.py tests/state/test_negative_business_provenance.py tests/state/test_current_scoped_coverage.py tests/state/test_checker_revision.py tests/test_veriarbor_substitution_provenance.py
```

结果：**112 passed**。

## 5. 私钥、授权者、验签器分别由谁控制

| 角色 | 应为 | 当前实际 |
|---|---|---|
| 授权私钥 | 用户/controller 在独立账户、HSM 或 ACL 保护目录 | 只有测试 fixture key，位于本会话临时目录，不是生产 trust anchor |
| 授权者 | 私钥持有者（用户/controller） | 本会话未签发正式用户授权 |
| 验签公钥 | 受保护 trust anchor，Agent 不可写 | 测试 anchor 在临时目录；正式环境尚未部署 |
| 验签器 | 受保护安装目录中的 `cgkn/state/release_authorization.py` 与 `ProvenanceGate` | 代码已实现；正式安装目录的 ACL 尚未验证 |
| B10/B11 | 独立执行/可信签发；签名只固定其哈希 | 仍位于 Agent 可写 run store；签名能防篡改，但不能防止 signer 盲目信任伪造的 review JSON |

## 6. 当前 Windows 环境真正生效/未部署的保护

**已生效（在隔离测试中）：**

- 没有有效 Ed25519 签名时，Agent 来源 fail closed。
- 改 README/TEST_PLAN/test/main.py 后，旧签名不再匹配 manifest。
- 改授权/review/B10/B11 后，签名固定的哈希不再匹配。
- 把 trust anchor 放进 run store 会被拒绝。
- 工作区里的伪造 `provenance.py`/`release_authorization.py` 不会被导入。
- Worker 来源仍要求真实 Worker receipt，未降级为 Agent 来源。

**未部署：**

- 没有真实的用户私钥、HSM 或独立签名账户。
- 没有 OS ACL 证明 Agent 不能读私钥、不能改公钥 anchor、不能改正式验签器。
- Agent 与 controller 实际仍可能以同一 Windows 用户运行。
- 因此不能声称生产安全机制已部署。

## 7. 可复用的既有证据

可以复用：

- 冻结 `main.py` 与 ZIP 的完整性；
- 23 个 Worker receipt 与 candidate 来源链；
- B10/B11/M12 的既有验收结果；
- `production_candidate_provenance.json` 的历史内容。

必须重新建立：

- 7 个 Agent 文件的 release authorization：由真实 signer 重新签发；
- 如果 signer 不能独立复核，B10/B11 需要重新执行或由可信方复核；
- P01–P19 在正式 trust context 下重跑；
- final delivery truth / canonical gate 重跑。

不需要：

- 重新开发 M12；
- 重跑所有 B01–B11；
- 覆盖冻结候选或 ZIP。

## 8. 当前正式交付能否被认可

**不能。** 当前正式交付仍为：

```text
DELIVER_WITH_WARNINGS (historical)
FINAL_DELIVERY_SECURITY_HOLD = PAUSED_PENDING_SECURITY_FIX
P11 fix = IMPLEMENTED_NOT_TRUSTED
```

缺少：

1. 真实外部私钥/签名环境；
2. 受保护的公钥 anchor 与验签器安装目录；
3. 由真实 signer 签发的 release authorization；
4. 正式 trust context 下的 P01–P19 与 final truth 重跑。

在完成这些之前，不得恢复 `delivery_allowed` 或把状态改成 PASS。

## 9. 最小正式部署步骤

1. 在独立账户/HSM/ACL 保护目录生成 Ed25519 密钥；私钥不进入仓库、run store、工作区或环境变量。
2. 把公钥 anchor 发布到 Agent 不可写的固定路径，并设置只读 ACL。
3. 在签名环境独立复核 B10/B11 和 30 个交付文件哈希。
4. 运行 `tools/sign_release_authorization.py` 生成签名授权。
5. 将 `P11_FIX_MINIMAL.patch` 应用到正式代码（不覆盖 candidate/ZIP）。
6. 调用 `final_delivery_truth.evaluate(..., release_trust_anchor=..., release_authorization=...)`。
7. 重跑 P01–P19、既有回归测试和 final delivery truth。
8. 只有全部通过后，才由用户决定是否解除 `FINAL_DELIVERY_SECURITY_HOLD.json`。

用户需要完成的授权动作：在受保护签名环境中确认 release id、logical task、文件清单与哈希、B10/B11 哈希、author_type、scope 和有效期，然后签名。不要仅凭 Agent 生成的 JSON 直接签名。


## 10. 正式集成结果（已批准并执行）

```text
FORMAL_INTEGRATION: APPLIED_AND_VERIFIED
DESTINATION: F:\CGKN-LeanLoop-V1-20261101
APPLY_MODE: git -c core.autocrlf=false apply -p1
PATCH_SHA256: 3f7caed58227d25685ccd0f1792955f2420260e28020e55f10559b41696f237c
5_FILE_HASHES_MATCH_TESTED: true
POST_INTEGRATION_P01_P19: 24/24 PASS, exit 0
POST_INTEGRATION_REGRESSION: 112 passed, exit 0
CANDIDATE_MAIN: 711c051954513eab78261062f46228f7ea757a5857a5624ffd487787697d4237
BUNDLE: f6eb10fb8283b250c28796e0ac95308bb6135e8434f6eef742acc58fbb469f8f
GOAL_ACCEPTANCE: c3d55cfd3cb335948728f1153c7dbb675204760574e46c3ad3fdaf83dbd635aa
FINAL_DELIVERY_RECOGNITION: PAUSED_PENDING_TRUST_ANCHOR
TRUST_ANCHOR: PENDING_TRUST_ANCHOR
AUTHORIZATION: NOT_SIGNED
COMMIT_CREATED: false
PUSH_EXECUTED: false
RESET_CLEAN_EXECUTED: false
```

正式集成证据：

```text
FORMAL_INTEGRATION_RESULT.json
P11_P19_RESULTS_FORMAL.json
REGRESSION_FORMAL.txt
pre_apply_backup/PRE_APPLY_MANIFEST.json
STATUS_BEFORE_APPLY.txt
STATUS_AFTER_APPLY.txt
STATUS_AFTER_TESTS.txt
```

本次只应用 5 个生产文件，未修改冻结候选、ZIP、历史证书或安全暂停记录。正式交付认可仍暂停，等待真实外部 trust anchor 和用户签名授权。
