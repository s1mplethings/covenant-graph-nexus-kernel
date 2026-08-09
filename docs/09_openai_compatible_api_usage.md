# OpenAI Compatible API 统一调用方法

## 概述

CGNK 已实现统一的 OpenAI 兼容 API 调用层，自动适配两种端点类型：
- **Chat Completions** (`/chat/completions`)：用于 GPTsAPI（`api.gptsapi.net`）
- **Responses** (`/responses`)：用于其他兼容服务

## Python 调用（推荐）

### 导入统一 Helper

```python
import scripts.check_connectivity as check

# 自动探测端点和转换 payload
base_url = "https://api.gptsapi.net/v1"  # 或其他兼容 base URL
endpoint = check._openai_compatible_endpoint(base_url)
payload = check._build_openai_compatible_payload(
    base_url,
    {
        "model": "gpt-5.4-nano",
        "messages": [{"role": "user", "content": "你好"}],
        "max_tokens": 1000,
    }
)
token = "sk-YOUR_API_KEY"
doc, error = check._post_json(endpoint, payload, token, timeout=45)
```

### 返回值

- `doc`：API 响应字典（成功时）
- `error`：错误信息字符串（失败时）

提取文本：
```python
text = check._extract_text(doc)  # 从 doc 中提取 content
```

## 命令行调用

### Windows PowerShell / CMD

使用 JSON 文件避免 shell 引号处理问题：

```batch
curl.exe --include https://api.gptsapi.net/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer YOUR_API_KEY" ^
  --data-binary "@body.json"
```

body.json：
```json
{
  "model": "gpt-5.4-nano",
  "messages": [
    {
      "role": "user",
      "content": "你好"
    }
  ],
  "max_tokens": 1000
}
```

### Linux / macOS

```bash
curl https://api.gptsapi.net/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "gpt-5.4-nano",
    "messages": [
      {
        "role": "user",
        "content": "你好"
      }
    ],
    "max_tokens": 1000
  }'
```

## API 配置优先级

credentialsResolver 按以下顺序查找 API key 和 base URL。持久配置只保留一个 User 级 `CGKN_*` 来源；其他名称仅用于兼容读取和冲突诊断。

### API Key 查找顺序
1. 一次性覆盖：`CGKN_OPENAI_API_KEY_OVERRIDE`（进程）
2. 规范持久值：`CGKN_OPENAI_API_KEY`（用户级 User）
3. 环境变量：`CGKN_OPENAI_API_KEY`（机器级 Machine）
4. 兼容环境变量：`CGKN_OPENAI_API_KEY`（进程）
5. 兼容环境变量：`OPENAI_API_KEY`（用户级）
6. 兼容环境变量：`OPENAI_API_KEY`（机器级）
7. 兼容环境变量：`OPENAI_API_KEY`（进程）

`.agent_private/NOTES.md` 不再作为 API key 来源，避免旧密钥在换码后重新生效。

### Base URL 查找顺序
1. 一次性覆盖：`CGKN_OPENAI_BASE_URL_OVERRIDE`（进程）
2. 规范持久值：`CGKN_OPENAI_BASE_URL`（用户级）
3. 环境变量：`CGKN_OPENAI_BASE_URL`（机器级）
4. 兼容环境变量：`CGKN_OPENAI_BASE_URL`（进程）
5. 环境变量：`OPENAI_BASE_URL`（用户级）
6. 环境变量：`OPENAI_BASE_URL`（机器级）
7. 环境变量：`OPENAI_BASE_URL`（进程）
8. 本地笔记中的 URL（只允许 URL，不读取密钥）
9. 嵌入默认值：`https://api.gptsapi.net/v1`

## 端点自动判别

### GPTsAPI（`api.gptsapi.net`）
- 自动选择：`/chat/completions`
- payload 格式：使用 `messages` 数组
- 参数对应：`max_tokens` ↔ `max_tokens`

### 其他兼容服务
- 自动选择：`/responses`
- payload 格式：使用 `input` 字符串（`messages` 会被自动转换）
- 参数对应：`max_tokens` ↔ `max_output_tokens`

## 错误处理

### 重试分类

```python
is_retryable = check._error_is_retryable(error_text)
error_type = check._provider_error_type(error_text)
```

错误类型：
- `PROVIDER_QUOTA_EXCEEDED`：API key 超额/限流（不可重试）
- `PROVIDER_TRANSPORT_UNSTABLE`：网络/TLS 问题（可重试）
- `PROVIDER_RETRYABLE_HTTP`：HTTP 429/5xx（可重试）
- `PROVIDER_FORBIDDEN`：HTTP 403 其他原因（不可重试）

### TLS 验证

默认启用，可关闭：
```bash
$env:CGKN_API_TLS_VERIFY="0"
```

## 验证连接

```bash
python scripts/check_connectivity.py --live --json
```

输出示例（成功）：
```json
{
  "api": {
    "configured": true,
    "ok": true,
    "endpoint": "https://api.gptsapi.net/v1/chat/completions",
    "endpoint_mode": "chat",
    "status": "connected"
  }
}
```

## 内部使用者

以下脚本已迁移至统一 helper：
- `scripts/agent_conversation_loop.py`
- `scripts/pipeline_planner_agent.py`
- `scripts/dynamic_pipeline_runner.py`
- `scripts/run_local_pipeline.py`
- `scripts/backend_dialogue_loop.py`
- `scripts/telegram_live_bridge.py`
- `scripts/provider_api_smoke.py`

调用方式（示例）：
```python
endpoint = check_connectivity._openai_compatible_endpoint(root)
payload = check_connectivity._build_openai_compatible_payload(root, {...})
doc, error = check_connectivity._post_json(endpoint, payload, token, timeout)
```

## 实验记录

### 测试环境
- 日期：2026-06-10
- 端点：`https://api.gptsapi.net/v1/chat/completions`
- 模型：`gpt-5.4-nano`
- 提示：`你好`
- max_tokens：1000

### 成功调用记录

**Python smoke 脚本**
```bash
python scripts/provider_api_smoke.py --model gpt-5.4-nano --timeout 45
```
结果：HTTP 200，回复内容：`你好！有什么我可以帮你的吗？`

**Curl（Windows 推荐格式）**
```bash
curl.exe --include https://api.gptsapi.net/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer YOUR_API_KEY" ^
  --data-binary "@body.json"
```
结果：HTTP 200，token 用量：20

**Python Helper**
```python
root = "https://api.gptsapi.net/v1"
endpoint = check._openai_compatible_endpoint(root)
# 返回：https://api.gptsapi.net/v1/chat/completions
payload = check._build_openai_compatible_payload(
    root,
    {"model": "gpt-5.4-nano", "messages": [...], "max_tokens": 1000}
)
# 返回：{"model": "gpt-5.4-nano", "messages": [...], "max_tokens": 1000}
```
（自动保留 messages 格式，因为是 GPTsAPI）

## 常见问题

### Q：为什么 curl 在 PowerShell 里拼接 JSON 时返回 model not found？
A：PowerShell 的 `-d` 参数在 ConvertTo-Json 后会被 shell 处理，导致转义错误。使用 `--data-binary @file.json` 更稳定。

### Q：如何只用某一个 API key？
A：使用凭据替换器。它会隐藏输入、写入唯一的 User 级规范变量、删除 User 级旧名称，并清理本地笔记中的旧密钥：
```powershell
python scripts/provider_credentials.py replace --base-url https://api.gptsapi.net/v1 --live-test
```

只查看当前来源和冲突，不显示完整密钥：

```powershell
python scripts/provider_credentials.py status
```

临时进行一次进程级覆盖时使用 `CGKN_OPENAI_API_KEY_OVERRIDE`，不要再用普通 `CGKN_OPENAI_API_KEY` 充当临时覆盖。

### Q：如何查询当前服务可用的模型？
A：
```bash
curl https://api.gptsapi.net/v1/models \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Q：支持哪些模型？
A：取决于 base_url 所指向的服务商。例如 GPTsAPI 当前支持 `gpt-5.4-nano`、`gpt-5.5` 等。

## 下一步

- 新项目继承 `_openai_compatible_endpoint()` 和 `_build_openai_compatible_payload()` helper
- 避免重复实现 chat/responses 分支判断
- 统一错误重试分类 via `_error_is_retryable()` 和 `_provider_error_type()`
