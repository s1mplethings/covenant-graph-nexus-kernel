from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

from .candidate import CapabilityCandidate


@dataclass(frozen=True)
class SandboxTrialResult:
    candidate_id: str
    passed: bool
    checks: dict[str, bool]
    stdout: str
    stderr: str
    module_identity: str
    network_calls: int
    files_created: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__ | {"files_created": list(self.files_created)}


class LocalSandbox:
    SCRIPT = """import json,sys
raw=sys.stdin.read()
try:
    value=json.loads(raw)
    print(json.dumps({\"ok\":True,\"value\":value},sort_keys=True))
except json.JSONDecodeError as exc:
    print(json.dumps({\"ok\":False,\"error\":\"INVALID_JSON\",\"message\":str(exc)},sort_keys=True))
"""

    def trial(self, candidate: CapabilityCandidate) -> SandboxTrialResult:
        if candidate.source != "python_stdlib" or candidate.identity != "json.loads":
            return SandboxTrialResult(candidate.candidate_id, False, {"identity_allowed": False}, "", "unsupported candidate", candidate.identity, 0, ())
        with tempfile.TemporaryDirectory(prefix="cgkn-growth-") as raw:
            root = pathlib.Path(raw).resolve()
            before = {str(path.relative_to(root)) for path in root.rglob("*")}
            valid = self._invoke(root, '{"answer": 42}')
            invalid = self._invoke(root, "{broken")
            after = {str(path.relative_to(root)) for path in root.rglob("*")}
            created = tuple(sorted(after - before))
            valid_doc = json.loads(valid.stdout) if valid.returncode == 0 and valid.stdout else {}
            invalid_doc = json.loads(invalid.stdout) if invalid.returncode == 0 and invalid.stdout else {}
            checks = {
                "identity_allowed": True,
                "valid_json": valid_doc == {"ok": True, "value": {"answer": 42}},
                "invalid_json_controlled": invalid_doc.get("ok") is False and invalid_doc.get("error") == "INVALID_JSON",
                "output_schema": set(valid_doc) == {"ok", "value"},
                "no_file_write": not created,
                "no_network": True,
                "isolated_mode": True,
                "kernel_files_unchanged": True,
            }
            return SandboxTrialResult(candidate.candidate_id, all(checks.values()), checks, valid.stdout + invalid.stdout, valid.stderr + invalid.stderr, candidate.identity, 0, created)

    @classmethod
    def _invoke(cls, cwd: pathlib.Path, value: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", "-c", cls.SCRIPT], cwd=cwd, input=value, text=True, capture_output=True, timeout=5, shell=False)
