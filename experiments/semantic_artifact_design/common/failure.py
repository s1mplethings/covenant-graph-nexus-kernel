from __future__ import annotations

import re
from typing import Any, Mapping


CLASSES = ("SYNTAX_ERROR", "IMPORT_ERROR", "NAME_ERROR", "INTERFACE_MISMATCH", "TEST_DEFECT", "SOURCE_BEHAVIOR_DEFECT", "CLI_CONTRACT_DEFECT", "RUNTIME_DEFECT", "STATE_DEFECT", "UNKNOWN")


class FailureAttributor:
    def attribute(self, *, stdout: str, stderr: str, returncode: int, manifests: Mapping[str, Any], project_contract: Mapping[str, Any], test_contract: Mapping[str, Any], units: Mapping[str, tuple[str, ...]], phase: str = "pytest") -> dict[str, Any]:
        text = (stdout + "\n" + stderr)[-16000:]
        failure_class = self._classify(text, phase)
        paths = re.findall(r'(?:File\s+["\']([^"\']+)["\']|([\w./\\-]+\.py))', text)
        flattened = [left or right for left, right in paths]
        project_paths = [item.replace("\\", "/") for item in flattened if not item.startswith("<")]
        owner_file = next((item for item in project_paths if "/tests/" not in f"/{item}" and not item.startswith("tests/")), "")
        failed_test = next((item for item in project_paths if "/tests/" in f"/{item}" or item.startswith("tests/")), "")
        if failed_test and failure_class in {"NAME_ERROR", "IMPORT_ERROR", "SYNTAX_ERROR"} and not owner_file:
            failure_class = "TEST_DEFECT"
            owner_file = failed_test
        allowed = [unit for unit, paths_ in units.items() if any(owner_file.endswith(path) or path.endswith(owner_file) for path in paths_)]
        if not allowed:
            allowed = ["public-tests"] if failure_class == "TEST_DEFECT" and "public-tests" in units else list(units)[:1]
        module = owner_file[:-3].replace("/", ".").replace("\\", ".") if owner_file.endswith(".py") else ""
        return {"failure_class": failure_class, "owner_file": owner_file, "owner_module": module, "owner_interface": self._interface_for(module, manifests),
                "first_project_frame": project_paths[0] if project_paths else "", "failed_test": failed_test,
                "expected": "declared public contract and tests pass", "observed": self._summary(text, returncode), "allowed_repair_units": allowed}

    @staticmethod
    def _classify(text: str, phase: str) -> str:
        if "SyntaxError" in text: return "SYNTAX_ERROR"
        if "ImportError" in text or "ModuleNotFoundError" in text: return "IMPORT_ERROR"
        if "NameError" in text: return "NAME_ERROR"
        if "unexpected keyword" in text or "positional argument" in text or "has no attribute" in text: return "INTERFACE_MISMATCH"
        if phase == "runtime": return "CLI_CONTRACT_DEFECT" if "usage:" in text.lower() or "argument" in text.lower() else "RUNTIME_DEFECT"
        if "AssertionError" in text: return "SOURCE_BEHAVIOR_DEFECT"
        return "UNKNOWN"

    @staticmethod
    def _interface_for(module: str, manifests: Mapping[str, Any]) -> str:
        for item in manifests.get("modules", []):
            if item.get("module") == module:
                funcs = item.get("functions", [])
                return str(funcs[0].get("name", "")) if funcs else module
        return ""

    @staticmethod
    def _summary(text: str, returncode: int) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return f"exit={returncode}; " + (lines[-1][:500] if lines else "no diagnostic output")
