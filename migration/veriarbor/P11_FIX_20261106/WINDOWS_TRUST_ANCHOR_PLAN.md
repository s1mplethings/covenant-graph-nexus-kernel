# Windows 可信授权环境准备方案（未部署）

```text
WINDOWS_TRUST_ANCHOR_PLAN: READY_FOR_USER_DEPLOYMENT
CURRENT_STATUS: PENDING_TRUST_ANCHOR
TRUST_ROOT: C:\ProgramData\VeriArborTrust（尚不存在）
SIGNER_USER: veriarbor-signer（尚不存在）
CURRENT_PROCESS_ELEVATED: false
FORMAL_PRIVATE_KEY_GENERATED: NO
FORMAL_AUTHORIZATION_SIGNED: NO
```

## 1. 目标与最小方案

- `test\sunom`：普通 OpenCode/开发用户，可修改开发仓库和 run store。
- `veriarbor-signer`：独立本地标准用户，持有正式 Ed25519 私钥，执行签名。
- `Administrators`/`SYSTEM`：仅用于部署和应急；管理员可绕过 ACL，这是不可避免的残余风险。
- `sunom` 只能读取公钥 anchor 和受保护验签器，不能读取私钥、不能写 anchor、不能写验签器、不能调用 signer。
- 普通开发不需要签名；只有正式交付时由用户在 signer 会话中执行一次授权。

这不是 HSM，也不是跨机器隔离；它是单机最小方案，必须如实报告 `PENDING_TRUST_ANCHOR` 直到实际部署并验证。

## 2. 需要用户手动执行的 Windows 操作

以下命令必须在**提升的 PowerShell**中执行，由用户手动完成。OpenCode 不执行。

### 2.1 创建独立标准用户

```powershell
$signerName = 'veriarbor-signer'
if (-not (Get-LocalUser -Name $signerName -ErrorAction SilentlyContinue)) {
    $pw = Read-Host -AsSecureString "Password for $signerName"
    New-LocalUser -Name $signerName -Password $pw `
        -PasswordNeverExpires -UserMayNotChangePassword -AccountNeverExpires
}
# 不要加入 Administrators
$signerSid = (Get-LocalUser -Name $signerName).SID.Value
$agentId = "$env:USERDOMAIN\$env:USERNAME"
$signerId = "$env:COMPUTERNAME\$signerName"
```

### 2.2 创建受保护目录

```powershell
$root = 'C:\ProgramData\VeriArborTrust'
New-Item -ItemType Directory -Force `
    "$root\keys", "$root\anchor", "$root\signer", "$root\app", "$root\releases" | Out-Null
```

### 2.3 设置 ACL

```powershell
# 顶层：管理员/系统/签名者完全控制；开发用户只读执行
icacls $root /inheritance:r `
  /grant:r "BUILTIN\Administrators:(OI)(CI)F" `
           "NT AUTHORITY\SYSTEM:(OI)(CI)F" `
           "*${signerSid}:(OI)(CI)F" `
           "${agentId}:(OI)(CI)RX"

# 私钥和 signer：开发用户无任何权限
icacls "$root\keys" /inheritance:r `
  /grant:r "BUILTIN\Administrators:(OI)(CI)F" "NT AUTHORITY\SYSTEM:(OI)(CI)F" "*${signerSid}:(OI)(CI)F"
icacls "$root\signer" /inheritance:r `
  /grant:r "BUILTIN\Administrators:(OI)(CI)F" "NT AUTHORITY\SYSTEM:(OI)(CI)F" "*${signerSid}:(OI)(CI)F"

# 公钥 anchor：开发用户只读
icacls "$root\anchor" /inheritance:r `
  /grant:r "BUILTIN\Administrators:(OI)(CI)F" "NT AUTHORITY\SYSTEM:(OI)(CI)F" "*${signerSid}:(OI)(CI)F" "${agentId}:(OI)(CI)R"

# 受保护验签器：开发用户只读执行，不能写
icacls "$root\app" /inheritance:r `
  /grant:r "BUILTIN\Administrators:(OI)(CI)F" "NT AUTHORITY\SYSTEM:(OI)(CI)F" "*${signerSid}:(OI)(CI)F" "${agentId}:(OI)(CI)RX"

# 已签名 release：开发用户只读
icacls "$root\releases" /inheritance:r `
  /grant:r "BUILTIN\Administrators:(OI)(CI)F" "NT AUTHORITY\SYSTEM:(OI)(CI)F" "*${signerSid}:(OI)(CI)F" "${agentId}:(OI)(CI)R"
```

## 3. 生成正式私钥（只在 signer 会话中）

先以 signer 身份登录：

```powershell
runas /user:veriarbor-signer "powershell.exe -NoProfile"
```

在 signer PowerShell 中执行：

```powershell
$py = @'
import os, pathlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

p = pathlib.Path(os.environ["LOCALAPPDATA"]) / "VeriArbor" / "keys" / "release-private.pem"
p.parent.mkdir(parents=True, exist_ok=True)
key = Ed25519PrivateKey.generate()
p.write_bytes(key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
))
print(p)
'@
$py | D:\anaconda\python.exe -X utf8 -
```

要求：

- 私钥只保存在 signer 用户 profile 下；不要放到仓库、run store、F:、D:\VeriArbor 或环境变量。
- 不要在当前 OpenCode 会话生成、读取或保存正式私钥。
- 不要把私钥内容打印到终端或日志。

## 4. 复制 signer 与受保护验签器

由管理员执行：

```powershell
$root = 'C:\ProgramData\VeriArborTrust'
Copy-Item 'F:\CGKN-LeanLoop-V1-20261101\tools\sign_release_authorization.py' "$root\signer\" -Force
```

`$root\signer` 的 ACL 已禁止 `sunom` 读取/执行。

受保护验签器需要在 P11 commit 后制作只读快照。最小范围：

```powershell
$app = "$root\app"
robocopy 'F:\CGKN-LeanLoop-V1-20261101\cgkn' "$app\cgkn" /E /XD __pycache__ .pytest_cache
robocopy 'F:\CGKN-LeanLoop-V1-20261101\scripts' "$app\scripts" /E /XD __pycache__ .pytest_cache
robocopy 'F:\CGKN-LeanLoop-V1-20261101\contracts' "$app\contracts" /E /XD __pycache__
robocopy 'F:\CGKN-LeanLoop-V1-20261101\config' "$app\config" /E /XD __pycache__
robocopy 'F:\CGKN-LeanLoop-V1-20261101\tools' "$app\tools" /E /XD __pycache__
robocopy 'D:\VeriArbor\src\veriarbor' "$app\veriarbor" /E /XD __pycache__
```

不要复制：

```text
.git、migration/、artifacts/、evidence/、run store、candidate、DELIVERY_EVIDENCE、
.venv、build、dist、pytest cache、任何私钥或临时授权
```

复制后由 signer 运行一次受保护 gate，确认运行闭合；`sunom` 只能读，不能写。

## 5. 验证 Agent 实际无法访问私钥

在普通 `sunom` 非提升 PowerShell 中执行：

```powershell
whoami
icacls C:\ProgramData\VeriArborTrust\keys
Get-Content C:\ProgramData\VeriArborTrust\keys\release-private.pem   # 必须 Access Denied
Get-ChildItem C:\ProgramData\VeriArborTrust\signer                  # 必须 Access Denied
```

在 signer 会话中执行：

```powershell
whoami
Get-Content "$env:LOCALAPPDATA\VeriArbor\keys\release-private.pem" | Select-Object -First 1
```

另外验证：

```powershell
# sunom 不能通过 runas 无密码调用 signer
runas /user:veriarbor-signer "cmd /c whoami"
# 必须提示输入密码；Agent 不知道密码
```

## 6. 验证 Agent 不能修改公钥和验签器

在 `sunom` 普通会话中：

```powershell
# 必须 Access Denied
Set-Content C:\ProgramData\VeriArborTrust\anchor\release-trust-anchor.json 'tamper'
Set-Content C:\ProgramData\VeriArborTrust\app\cgkn\state\provenance.py 'tamper'
Set-Content C:\ProgramData\VeriArborTrust\app\cgkn\state\release_authorization.py 'tamper'

# 只读访问必须成功
Get-Content C:\ProgramData\VeriArborTrust\anchor\release-trust-anchor.json
```

如果 `sunom` 能写这些路径，信任边界未建立，必须保持 `PENDING_TRUST_ANCHOR`。

注意：`sunom` 当前属于 `BUILTIN\Administrators`，但进程是 UAC 非提升的。管理员提升后可绕过 ACL；因此 Agent 不能获得提升权限，用户也不能把管理员密码交给 Agent。

## 7. 独立核对 30 个文件与 B10/B11

在 signer 会话中：

1. 验证冻结 ZIP：
   ```powershell
   Get-FileHash 'F:\CGKN-ITER-132\production-core-convergence-v1\promotion\run-05\PROMOTION_DELIVERY_M12_FINAL_20261106\final_project_bundle.zip' -Algorithm SHA256
   # 必须等于 f6eb10fb8283b250c28796e0ac95308bb6135e8434f6eef742acc58fbb469f8f
   ```
2. 在 signer 临时目录解压 ZIP，重新计算 30 个交付文件 SHA-256，逐项与 `delivery_manifest.json` 的 `inclusion_manifest` 和 `production_candidate_provenance.json` 的 `candidate_source_manifest` 比较。
3. 独立复核 B10：
   - 重新运行 `D:\VeriArbor\tools\m12_b10_acceptance.py`，或至少逐项验证 `relevant_section_hashes["<file>#full"]` 与解压文件一致；
   - 不得仅信任 run store 中 Agent 可写的 `B10_CERTIFICATE.json`。
4. 独立复核 B11：
   - 重新运行 B11 checker（`final-gui-complete-v10.py`）或由可信方复核；
   - 不得仅信任 Agent 可写的 `B11_ACCEPTANCE.json`。
5. 确认 23 个 Worker 来源与 7 个 Agent 来源的作者身份、receipt/review 哈希、`author_type`。
6. 把独立核对结果写入 signer 自己的 review 文件，再运行签名工具。

现有 `tools/sign_release_authorization.py` 能完成签名，但不能替代独立复核：它从 run store 读取 source_imports/review 文档并计算哈希，不会自动重跑 B10/B11。因此：

```text
SIGNER_TOOL_GAP: independent B10/B11 re-execution is manual/trusted-script responsibility
```

建议后续增加 `--expected-manifest` / `--review-manifest` 输入，强制 signer 只签署独立核对后的清单；本轮未修改代码。

## 8. 正式签名与验收顺序

```text
1. P11 Git commit 已批准并创建。
2. 在受保护 app 快照中确认 verifier 代码哈希。
3. 验证 ZIP 哈希并解压；计算 30 个文件哈希。
4. 独立重跑/复核 B10/B11；记录 signer review。
5. 准备独立 review manifest 和 30 文件 manifest。
6. 在 signer 会话运行 sign_release_authorization.py：
   --private-key <signer profile key>
   --manifest <30-file manifest>
   --anchor-out C:\ProgramData\VeriArborTrust\anchor\release-trust-anchor.json
   --out C:\ProgramData\VeriArborTrust\releases\<release-id>.json
7. 在受保护 app 快照中运行 P01–P19 与 final delivery truth，
   传入 release_trust_anchor 和 release_authorization。
8. 只有全部通过后，用户批准解除 FINAL_DELIVERY_SECURITY_HOLD；
   追加新的版本化验收记录，不覆盖历史。
```

普通开发不需要执行以上步骤；只有正式交付时执行。

## 9. 密钥备份、失效与轮换

### 备份

- 在 signer 会话中导出加密备份，存离线介质（BitLocker USB 或 7z AES）。
- 备份口令与介质分开保存。
- 备份完成后在隔离环境做一次恢复测试；不要把私钥放入 Git、云盘或 Agent 可读目录。

### 轮换

1. 生成新 key id，例如 `release-2027-01`。
2. 先在新 anchor 中同时保留旧/新公钥。
3. 用新 key 签发新 release。
4. 旧 release 到期后，从 anchor 删除旧 key。
5. 记录 key id、有效期、签发 release 列表。

### 失效/泄露

1. 立即从 anchor 删除泄露 key。
2. 用新 key 重新签发 release。
3. 作废旧 release id，更新安全 hold。
4. 保留事件记录，不删除历史证据。

## 10. 当前状态

```text
C:\ProgramData\VeriArborTrust: 不存在
veriarbor-signer: 不存在
正式私钥: 未生成
正式 anchor: 未生成
正式 release authorization: 未签署
Agent ACL 隔离: 未验证
PENDING_TRUST_ANCHOR: 是
```
