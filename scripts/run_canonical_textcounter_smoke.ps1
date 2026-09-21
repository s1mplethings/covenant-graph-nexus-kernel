param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [Parameter(Mandatory = $true)]
    [string]$Goal
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "D:\CGKN\tools\cgkn-agent-kit\src;D:\CGKN"
$resultPath = Join-Path $ProjectRoot ".cgkn\agent-kit\generation_result.json"

$pyproject = @'
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "textcounter"
version = "0.1.0"
description = "Local UTF-8 text counting command-line tool"
requires-python = ">=3.10"
dependencies = []

[project.optional-dependencies]
test = ["pytest>=8"]

[project.scripts]
textcounter = "textcounter.__main__:main"

[tool.setuptools]
packages = ["textcounter"]

[tool.pytest.ini_options]
testpaths = ["tests"]
'@

$counter = @'
def count_text(text: str) -> dict:
    """Count characters, whitespace-delimited words, and logical lines."""
    if not text.strip():
        raise ValueError("text must not be blank")
    return {
        "characters": len(text),
        "words": len(text.split()),
        "lines": len(text.splitlines()),
    }
'@

$init = @'
from .count_text import count_text

__all__ = ["count_text"]
'@

$main = @'
import argparse
import json
from pathlib import Path

from .count_text import count_text


def main() -> None:
    parser = argparse.ArgumentParser(description="统计 UTF-8 文本的字符、单词和行数")
    parser.add_argument("path", help="UTF-8 文本文件路径")
    args = parser.parse_args()
    text = Path(args.path).read_text(encoding="utf-8")
    print(json.dumps(count_text(text), ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
'@

$tests = @'
import inspect
import json
import subprocess
import sys

import pytest

from textcounter import count_text


def test_goal_01_count_text_is_importable_with_the_frozen_signatu():
    assert str(inspect.signature(count_text)) == "(text: str) -> dict"


def test_goal_02_count_text_returns_a_value_matching_dict_for_val():
    assert count_text("one two\nthree") == {"characters": 13, "words": 3, "lines": 2}


def test_goal_03_count_text_raises_valueerror_when_the_normalized():
    with pytest.raises(ValueError):
        count_text("  \n\t")


def test_goal_04_the_cli_prints_exactly_one_json_object_derived_f(tmp_path):
    source = tmp_path / "中文 输入.txt"
    source.write_text("你好 world\n第二行", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "textcounter", str(source)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == count_text(source.read_text(encoding="utf-8"))
'@

$readme = @'
# textcounter

`textcounter` 是一个完全本地运行的 UTF-8 文本统计命令行工具。它输出字符数、按空白分隔的单词数和逻辑行数，不访问网络，也没有运行时第三方依赖。

## 环境与安装

- Windows、macOS 或 Linux
- Python 3.10+

```powershell
python -m pip install -e .
```

如需运行测试：

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

## 使用

```powershell
python -m textcounter "C:\路径\中文 文件.txt"
```

程序向标准输出写入且只写入一个 JSON 对象。文件必须是 UTF-8；文件不存在、无法读取或编码错误时会以非零状态退出并在标准错误显示 Python 错误信息。纯空白文件会触发 `ValueError`。
'@

$testPlan = @'
# Test Plan

Run `python -m pytest -q`. Tests cover the frozen callable signature, exact counting behavior, blank-input rejection, and a real subprocess CLI invocation against a Chinese UTF-8 path. Independently extract the delivery ZIP and repeat the CLI command from the extracted project root.
'@

$deliveryNotes = @'
# Delivery Notes

This release contains a Python 3.10+ standard-library runtime, editable-install metadata, a console entry point, tests, and user documentation. It requires no network, cloud service, GUI, database, or runtime dependency outside Python.
'@

$files = @{
    "pyproject.toml" = $pyproject
    "requirements.txt" = "# No runtime dependencies.`n"
    "textcounter/count_text.py" = $counter
    "textcounter/__init__.py" = $init
    "textcounter/__main__.py" = $main
    "tests/test_count_text.py" = $tests
    "README.md" = $readme
    "TEST_PLAN.md" = $testPlan
    "DELIVERY_NOTES.md" = $deliveryNotes
}

for ($step = 0; $step -lt 40; $step++) {
    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    if ($result.status -ne "WAITING_SURROGATE_RESPONSE") {
        $result | ConvertTo-Json -Depth 20
        exit 0
    }
    $pending = @($result.pending_requests | Where-Object { -not $_.responded })[0]
    if ($null -eq $pending) { throw "No unresponded request exists." }
    $contextName = "{0}.{1}.json" -f $pending.job_id, $pending.attempt_id
    $contextPath = Join-Path $result.run_dir "artifacts\provider_handshake\contexts\$contextName"
    $context = Get-Content -LiteralPath $contextPath -Raw | ConvertFrom-Json
    $system = [string]$context.messages[0].content
    $target = [string]$context.target_file

    if ($system -match "review_summary") {
        $payload = [ordered]@{
            status = "pass"
            issues = @()
            strengths = @("Implementation matches the frozen goal and uses only the standard library.")
            expected_artifacts = @("pyproject.toml", "textcounter/count_text.py", "textcounter/__main__.py", "tests/test_count_text.py", "README.md")
            review_summary = "Reviewed the generated source, tests, CLI contract, and documentation; no issue found."
        }
    }
    elseif ($system -match "summary .*decisions" -or $system -match "keys summary") {
        $payload = [ordered]@{
            summary = "A minimal local Python CLI package implementing the exact text-count contract with UTF-8 and Chinese-path support."
            decisions = @(
                "Use Python 3.10+ and the standard library at runtime.",
                "Expose count_text(text: str) -> dict and a python -m textcounter CLI.",
                "Verify the CLI through a real subprocess and Chinese file path."
            )
            risks = @("Whitespace-delimited word counting is language-neutral but does not segment Chinese words.")
        }
    }
    elseif ($system -match "files") {
        if (-not $files.ContainsKey($target)) { throw "No authored payload for target: $target" }
        $payload = [ordered]@{
            files = @([ordered]@{ path = $target; content = $files[$target] })
        }
    }
    elseif ($system -match "path" -and $system -match "content") {
        if (-not $files.ContainsKey($target)) { throw "No authored payload for target: $target" }
        $payload = [ordered]@{ path = $target; content = $files[$target] }
    }
    else {
        throw "Unrecognized Provider response schema for stage $($pending.stage): $system"
    }

    $inner = $payload | ConvertTo-Json -Depth 20 -Compress
    $outer = ConvertTo-Json -InputObject $inner -Compress
    & python -m cgkn_agent_kit.cli submit-surrogate --project $ProjectRoot --run-dir $result.run_dir --job-id $pending.job_id --attempt-id $pending.attempt_id --payload $outer --surrogate-identity codex | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "submit-surrogate failed for $($pending.job_id)" }
    & python -m cgkn_agent_kit.cli generate --project $ProjectRoot --goal $Goal --provider-mode codex_surrogate --timeout 120 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "generate resume failed after $($pending.job_id)" }
    Write-Output ("completed provider stage: {0}" -f $pending.stage)
}

throw "Surrogate smoke exceeded the bounded 40-step response loop."
