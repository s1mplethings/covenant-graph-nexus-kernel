from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERIFIER_VERSION = "1.0.0"
RESULT_STATUSES = {"PASS", "BLOCK", "NEEDS_USER_REVIEW", "UNKNOWN"}


class GovernanceError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: str = "BLOCK") -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GovernanceError("GOVERNANCE_FILE_MISSING", f"Missing governance file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GovernanceError("GOVERNANCE_JSON_INVALID", f"Invalid JSON in {path}: {exc}") from exc


def git(project: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=project, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        raise GovernanceError("GIT_ERROR", result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def matches(path: str, pattern: str) -> bool:
    path = path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    if fnmatch.fnmatchcase(path, pattern):
        return True
    if pattern.endswith("/**"):
        return path == pattern[:-3] or path.startswith(pattern[:-2])
    return False


def unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def attach_dependencies(worktree: Path, dependency_root: Path) -> Path | None:
    source = dependency_root / "node_modules"
    target = worktree / "node_modules"
    if not source.is_dir() or target.exists():
        return None
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(source)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            return None
    else:
        target.symlink_to(source, target_is_directory=True)
    return target


@dataclass
class Check:
    id: str
    status: str
    code: str
    detail: str
    command: list[str] | None = None
    durationMs: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in {
            "id": self.id, "status": self.status, "code": self.code, "detail": self.detail,
            "command": self.command, "durationMs": self.durationMs,
        }.items() if value is not None}


class GovernanceEngine:
    def __init__(self, project: Path, *, tool_root: Path | None = None, strict: bool = False) -> None:
        self.project = project.resolve()
        self.root = self.project / ".cgnk" / "governance"
        self.tool_root = (tool_root or Path(__file__).resolve().parents[2]).resolve()
        self.strict = strict
        self.manifest = read_json(self.root / "manifest.json")
        self.invariants_doc = read_json(self.root / "permanent_invariants.json")
        self.capabilities_doc = read_json(self.root / "capabilities.json")
        self.ownership_doc = read_json(self.root / "path_ownership.json")
        self.lock = read_json(self.root / "governance.lock.json")
        self.migrations_doc = read_json(self.root / "migrations.json")
        self.invariants = self._index(self.invariants_doc, "invariants")
        self.capabilities = self._index(self.capabilities_doc, "capabilities")
        self.targets = self.manifest.get("verificationTargets", {})
        self._validate_declarations()

    @staticmethod
    def _index(doc: dict[str, Any], field: str) -> dict[str, dict[str, Any]]:
        values = doc.get(field)
        if not isinstance(values, list):
            raise GovernanceError("GOVERNANCE_SCHEMA_INVALID", f"{field} must be an array")
        result: dict[str, dict[str, Any]] = {}
        for item in values:
            if not isinstance(item, dict) or not item.get("id") or not isinstance(item.get("version"), int):
                raise GovernanceError("GOVERNANCE_SCHEMA_INVALID", f"Invalid {field} entry")
            key = f"{item['id']}@{item['version']}"
            if key in result:
                raise GovernanceError("DUPLICATE_CONTRACT_VERSION", key)
            result[key] = item
        return result

    def _validate_declarations(self) -> None:
        required = {"id", "version", "title", "description", "severity", "scope", "effectiveFrom", "verification", "governedCapabilities", "changePolicy"}
        for key, invariant in self.invariants.items():
            missing = sorted(required - invariant.keys())
            if missing:
                raise GovernanceError("INVARIANT_SCHEMA_INVALID", f"{key} missing {', '.join(missing)}")
            if invariant["changePolicy"] != "requires_user_review":
                raise GovernanceError("INVARIANT_CHANGE_POLICY_INVALID", f"{key} must require user review")
        ids = {value["id"] for value in self.capabilities.values()}
        for key, capability in self.capabilities.items():
            unknown = set(capability.get("dependsOn", [])) - ids
            if unknown:
                raise GovernanceError("UNKNOWN_CAPABILITY_DEPENDENCY", f"{key}: {sorted(unknown)}")
        for target_id, target in self.targets.items():
            if target.get("type") not in {"vitest", "pytest", "command", "static_policy", "artifact_lineage", "effect_boundary"}:
                raise GovernanceError("UNKNOWN_INVARIANT_CHECKER", f"{target_id}: {target.get('type')}", status="UNKNOWN")

    def current_commit(self) -> str:
        return git(self.project, "rev-parse", "HEAD")

    def tool_commit(self) -> str:
        return git(self.tool_root, "rev-parse", "HEAD")

    def changed_files(self) -> list[str]:
        baseline = self.lock.get("verifiedProjectCommit")
        if not baseline:
            raise GovernanceError("LOCK_BASELINE_MISSING", "governance.lock.json has no verifiedProjectCommit")
        git(self.project, "cat-file", "-e", f"{baseline}^{{commit}}")
        committed = git(self.project, "diff", "--name-only", f"{baseline}...HEAD", "--").splitlines()
        working = git(self.project, "diff", "--name-only", "HEAD", "--").splitlines()
        staged = git(self.project, "diff", "--cached", "--name-only", "--").splitlines()
        untracked = git(self.project, "ls-files", "--others", "--exclude-standard").splitlines()
        return sorted(unique(line.replace("\\", "/") for line in committed + working + staged + untracked if line))

    def _owned_capabilities(self, path: str) -> list[str]:
        owned: list[str] = []
        for mapping in self.ownership_doc.get("mappings", []):
            if matches(path, mapping["glob"]):
                owned.extend(mapping.get("capabilities", []))
        return unique(owned)

    def resolve_impact(self, changed: list[str]) -> tuple[list[str], list[str], list[str]]:
        governed_patterns = self.manifest.get("governedPaths", [])
        exempt_patterns = self.manifest.get("nonGovernedPaths", [])
        directly: list[str] = []
        unmapped: list[str] = []
        for path in changed:
            governed = any(matches(path, pattern) for pattern in governed_patterns)
            exempt = any(matches(path, pattern) for pattern in exempt_patterns)
            owners = self._owned_capabilities(path)
            directly.extend(owners)
            if governed and not exempt and not owners:
                unmapped.append(path)
        affected = set(directly)
        changed_flag = True
        current_caps = {item["id"]: item for item in self.capabilities.values()}
        while changed_flag:
            changed_flag = False
            for capability in current_caps.values():
                if capability["id"] not in affected and affected.intersection(capability.get("dependsOn", [])):
                    affected.add(capability["id"])
                    changed_flag = True
        affected_invariants = sorted({
            invariant["id"] for invariant in self.invariants.values()
            if affected.intersection(invariant.get("governedCapabilities", []))
        })
        return sorted(affected), affected_invariants, sorted(unmapped)

    def contract_integrity(self) -> tuple[list[Check], list[dict[str, Any]]]:
        checks: list[Check] = []
        drift: list[dict[str, Any]] = []
        groups = (("invariants", self.invariants, True), ("capabilities", self.capabilities, False))
        locked_hashes = self.lock.get("hashes", {})
        for group, current, constitutional in groups:
            for key, expected in locked_hashes.get(group, {}).items():
                item = current.get(key)
                actual = canonical_hash(item) if item is not None else None
                if actual == expected:
                    continue
                status = "NEEDS_USER_REVIEW" if constitutional else "BLOCK"
                code = "CONSTITUTIONAL_CHANGE" if constitutional else "CONTRACT_IMMUTABILITY"
                detail = "version removed" if item is None else "content changed without a new version"
                checks.append(Check(f"integrity:{key}", status, code, f"{key}: {detail}"))
                drift.append({"contract": key, "expectedHash": expected, "actualHash": actual, "code": code})
            locked_keys = set(locked_hashes.get(group, {}))
            current_by_id: dict[str, list[int]] = {}
            for item in current.values():
                current_by_id.setdefault(item["id"], []).append(item["version"])
            migrations = self.migrations_doc.get("migrations", [])
            for contract_id, versions in current_by_id.items():
                locked_versions = [int(key.rsplit("@", 1)[1]) for key in locked_keys if key.rsplit("@", 1)[0] == contract_id]
                if not locked_versions:
                    continue
                previous = max(locked_versions)
                for version in sorted(value for value in versions if value > previous):
                    source = f"{contract_id}@{previous}"
                    target = f"{contract_id}@{version}"
                    migration = next((item for item in migrations if item.get("from") == source and item.get("to") == target), None)
                    if not migration:
                        checks.append(Check(f"migration:{target}", "BLOCK", "CONTRACT_MIGRATION_MISSING", f"{source} -> {target}"))
                        drift.append({"contract": target, "code": "CONTRACT_MIGRATION_MISSING"})
                    elif constitutional and migration.get("compatibility") == "weakening":
                        checks.append(Check(f"migration:{target}", "NEEDS_USER_REVIEW", "CONSTITUTIONAL_CHANGE", f"{source} -> {target} weakens a permanent invariant"))
                        drift.append({"contract": target, "code": "CONSTITUTIONAL_CHANGE"})
                    previous = version
        return checks, drift

    def _tool_version_check(self) -> Check | None:
        expected = self.lock.get("cgnkCommit")
        if not expected:
            return Check("tool-version", "UNKNOWN", "TOOL_VERSION_UNPINNED", "No CGKN commit is pinned")
        actual = self.tool_commit()
        if actual == expected:
            return None
        status = "BLOCK" if self.strict else "PASS"
        code = "BLOCK_TOOL_VERSION_MISMATCH" if self.strict else "TOOL_VERSION_MISMATCH_WARNING"
        return Check("tool-version", status, code, f"expected {expected}, found {actual}")

    def _selected_targets(self, affected_capabilities: list[str], affected_invariants: list[str]) -> list[str]:
        if self.strict:
            invariant_values = list(self.invariants.values())
            capability_values = list(self.capabilities.values())
        else:
            invariant_values = [i for i in self.invariants.values() if i["id"] in affected_invariants]
            capability_values = [c for c in self.capabilities.values() if c["id"] in affected_capabilities]
        refs: list[str] = []
        for item in invariant_values + capability_values:
            refs.extend(item.get("verification", []))
        return unique(refs)

    def _run_target(self, target_id: str) -> Check:
        target = self.targets.get(target_id)
        if not target:
            return Check(target_id, "BLOCK", "TEST_TARGET_MISSING", "Referenced verification target is not declared")
        for rel in target.get("requiredFiles", []):
            if not (self.project / rel).exists():
                return Check(target_id, "BLOCK", "TEST_TARGET_MISSING", f"Required file is missing: {rel}")
        command = target.get("command")
        if not isinstance(command, list) or not command:
            return Check(target_id, "UNKNOWN", "UNKNOWN_INVARIANT_CHECKER", "Target has no executable command")
        started = time.monotonic()
        dependency_root = Path(os.environ.get("CGKN_CONSUMER_DEPENDENCIES", self.project))
        execution_env = {**os.environ, "CI": "1"}
        bin_dir = dependency_root / "node_modules" / ".bin"
        if bin_dir.is_dir():
            execution_env["PATH"] = str(bin_dir) + os.pathsep + execution_env.get("PATH", "")
        resolved_command = [str(part) for part in command]
        executable = shutil.which(resolved_command[0], path=execution_env.get("PATH"))
        if executable:
            resolved_command[0] = executable
        try:
            result = subprocess.run(
                resolved_command, cwd=self.project, text=True, encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=int(target.get("timeoutSeconds", 180)),
                env=execution_env,
            )
        except FileNotFoundError as exc:
            return Check(target_id, "UNKNOWN", "VERIFICATION_TOOL_MISSING", str(exc), command=command)
        except subprocess.TimeoutExpired:
            return Check(target_id, "BLOCK", "VERIFICATION_TIMEOUT", "Verification target timed out", command=command)
        duration = int((time.monotonic() - started) * 1000)
        output = result.stdout[-4000:]
        if result.returncode:
            return Check(target_id, "BLOCK", "VERIFICATION_FAILED", output.strip(), command=command, durationMs=duration)
        collection_pattern = target.get("collectionPattern")
        if collection_pattern and not re.search(collection_pattern, result.stdout, re.MULTILINE | re.IGNORECASE):
            return Check(target_id, "BLOCK", "ZERO_TESTS_COLLECTED", output.strip(), command=command, durationMs=duration)
        return Check(target_id, "PASS", "VERIFIED", output.strip(), command=command, durationMs=duration)

    def verify(self, *, execute: bool = True, skip_adversarial: bool = False, skip_positive: bool = False) -> dict[str, Any]:
        started = time.monotonic()
        changed = self.changed_files()
        capabilities, invariants, unmapped = self.resolve_impact(changed)
        checks, drift = self.contract_integrity()
        tool_check = self._tool_version_check()
        if tool_check:
            checks.append(tool_check)
        checks.extend(Check(f"ownership:{path}", "BLOCK", "UNGOVERNED_ARCHITECTURE_CHANGE", path) for path in unmapped)
        protected_tests = {rel for target in self.targets.values() for rel in target.get("requiredFiles", [])}
        changed_verifiers = sorted(set(changed).intersection(protected_tests))
        if changed_verifiers:
            checks.append(Check(
                "verifier-change", "PASS" if self.strict else "BLOCK", "VERIFIER_CHANGED",
                "Protected verification changed; strict adversarial verification is required: " + ", ".join(changed_verifiers),
            ))
        targets = self._selected_targets(capabilities, invariants)
        if execute:
            checks.extend(self._run_target(target_id) for target_id in targets)
        if self.strict and execute and not skip_adversarial:
            checks.append(self._run_experiment_suite("adversarial", expect_block=True))
        if self.strict and execute and not skip_positive:
            checks.append(self._run_experiment_suite("positive_evolution", expect_block=False))
        statuses = {check.status for check in checks}
        if "NEEDS_USER_REVIEW" in statuses:
            status = "NEEDS_USER_REVIEW"
        elif "BLOCK" in statuses:
            status = "BLOCK"
        elif "UNKNOWN" in statuses and self.strict:
            status = "UNKNOWN"
        else:
            status = "PASS"
        result = {
            "kind": "CGKNConsumerGovernanceResult",
            "schemaVersion": "1.0",
            "status": status,
            "changedFiles": changed,
            "affectedCapabilities": capabilities if not self.strict else sorted({c["id"] for c in self.capabilities.values()}),
            "affectedInvariants": invariants if not self.strict else sorted({i["id"] for i in self.invariants.values()}),
            "checks": [check.as_dict() for check in checks],
            "contractDrift": drift,
            "contractVersionValid": not drift,
            "verificationTargets": targets,
            "toolVersion": VERIFIER_VERSION,
            "toolCommit": self.tool_commit(),
            "projectCommit": self.current_commit(),
            "metrics": {
                "governedFiles": sum(any(matches(path, pattern) for pattern in self.manifest.get("governedPaths", [])) for path in changed),
                "mappedFiles": sum(bool(self._owned_capabilities(path)) for path in changed),
                "unmappedGovernedFiles": len(unmapped),
                "permanentInvariantCount": len(self.invariants),
                "capabilityCount": len(self.capabilities),
                "contractHashViolations": len(drift),
                "verificationDurationMs": int((time.monotonic() - started) * 1000),
            },
            "nextAction": self._next_action(status, checks),
        }
        if status not in RESULT_STATUSES:
            raise AssertionError(status)
        return result

    @staticmethod
    def _next_action(status: str, checks: list[Check]) -> str:
        if status == "PASS":
            return "No governance repair is required. Use record explicitly only for a reviewed clean baseline."
        failed = next((check for check in checks if check.status != "PASS"), None)
        if failed:
            return f"Resolve {failed.code}: {failed.detail[:500]}"
        return "Inspect governance declarations and evidence."

    def _run_experiment_suite(self, name: str, *, expect_block: bool) -> Check:
        config_path = self.root / f"{name}.json"
        if not config_path.exists():
            return Check(name, "BLOCK", "EXPERIMENT_SUITE_MISSING", str(config_path))
        config = read_json(config_path)
        cases = config.get("cases", [])
        if not cases:
            return Check(name, "BLOCK", "ZERO_EXPERIMENT_CASES", "No experiment cases declared")
        failures: list[str] = []
        results: list[dict[str, Any]] = []
        for case in cases:
            outcome = self._run_mutation_case(case, expect_block=expect_block)
            results.append(outcome)
            if not outcome["passed"]:
                failures.append(f"{case.get('id')}: {outcome['reason']}")
        status = "PASS" if not failures else "BLOCK"
        code = "EXPERIMENTS_VERIFIED" if not failures else "EXPERIMENT_SUITE_FAILED"
        detail = json.dumps({"passed": len(cases) - len(failures), "total": len(cases), "cases": results}, ensure_ascii=True)
        return Check(name, status, code, detail)

    def _run_mutation_case(self, case: dict[str, Any], *, expect_block: bool) -> dict[str, Any]:
        case_id = str(case.get("id", "unnamed"))
        with tempfile.TemporaryDirectory(prefix="cgkn-governance-") as temp_root:
            worktree = Path(temp_root) / "project"
            add = subprocess.run(
                ["git", "worktree", "add", "--detach", str(worktree), "HEAD"], cwd=self.project,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            if add.returncode:
                return {"id": case_id, "mutationApplied": False, "passed": False, "reason": "MUTATION_WORKTREE_FAILED"}
            try:
                dependency_link = attach_dependencies(worktree, self.project)
                if (self.project / "node_modules").is_dir() and dependency_link is None:
                    return {"id": case_id, "mutationApplied": False, "passed": False, "reason": "MUTATION_DEPENDENCY_LINK_FAILED"}
                experiment_lock_path = worktree / ".cgnk" / "governance" / "governance.lock.json"
                experiment_lock = read_json(experiment_lock_path)
                experiment_lock["verifiedProjectCommit"] = git(worktree, "rev-parse", "HEAD")
                experiment_lock_path.write_text(json.dumps(experiment_lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                operations = case.get("operations") or [{"type": "replace", "file": case.get("file"), "search": case.get("search"), "replace": case.get("replace")}]
                for operation in operations:
                    op_type = operation.get("type")
                    if op_type == "replace":
                        path = worktree / str(operation.get("file", ""))
                        if not path.is_file():
                            return {"id": case_id, "mutationApplied": False, "passed": False, "reason": "MUTATION_FIXTURE_STALE:file"}
                        content = path.read_text(encoding="utf-8")
                        search = str(operation.get("search", ""))
                        replacement = str(operation.get("replace", ""))
                        count = content.count(search)
                        if not search or count != 1:
                            return {"id": case_id, "mutationApplied": False, "passed": False, "reason": f"MUTATION_FIXTURE_STALE:matches={count}"}
                        path.write_text(content.replace(search, replacement, 1), encoding="utf-8")
                    elif op_type == "move":
                        source = worktree / str(operation.get("from", ""))
                        target = worktree / str(operation.get("to", ""))
                        if not source.is_file() or target.exists():
                            return {"id": case_id, "mutationApplied": False, "passed": False, "reason": "MUTATION_FIXTURE_STALE:move"}
                        target.parent.mkdir(parents=True, exist_ok=True)
                        source.replace(target)
                    else:
                        return {"id": case_id, "mutationApplied": False, "passed": False, "reason": f"MUTATION_FIXTURE_STALE:operation={op_type}"}
                command = [sys.executable, str(self.tool_root / "scripts" / "consumer_governance.py"), "verify", "--project", str(worktree), "--json"]
                result = subprocess.run(command, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=int(case.get("timeoutSeconds", 240)), env={**os.environ, "CGKN_CONSUMER_DEPENDENCIES": str(self.project)})
                try:
                    payload = json.loads(result.stdout)
                    decision = payload.get("status", "UNKNOWN")
                except json.JSONDecodeError:
                    decision = "UNKNOWN"
                passed = decision in {"BLOCK", "NEEDS_USER_REVIEW"} if expect_block else decision == "PASS"
                failed_checks = [item for item in payload.get("checks", []) if item.get("status") != "PASS"] if isinstance(payload, dict) else []
                failed_codes = [item.get("code") for item in failed_checks]
                reason = decision if passed else f"expected {'BLOCK' if expect_block else 'PASS'}, got {decision}: {', '.join(str(code) for code in failed_codes)}"
                return {"id": case_id, "mutationApplied": True, "verifyResult": decision, "passed": passed, "reason": reason, "failedCodes": failed_codes, "failedDetails": [str(item.get("detail", ""))[-1000:] for item in failed_checks], "expectedInvariant": case.get("expectedInvariant")}
            except subprocess.TimeoutExpired:
                return {"id": case_id, "mutationApplied": True, "passed": False, "reason": "MUTATION_VERIFY_TIMEOUT"}
            finally:
                dependency_path = worktree / "node_modules"
                if dependency_path.exists():
                    try:
                        dependency_path.rmdir()
                    except OSError:
                        pass
                subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=self.project, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def record(self) -> dict[str, Any]:
        if git(self.project, "status", "--porcelain"):
            raise GovernanceError("RECORD_REQUIRES_CLEAN_WORKTREE", "Commit or discard project changes before recording")
        result = self.verify(execute=True)
        if result["status"] != "PASS":
            raise GovernanceError("RECORD_REQUIRES_STRICT_PASS", f"Strict verification returned {result['status']}")
        lock = dict(self.lock)
        lock.update({
            "cgnkVersion": (self.tool_root / "VERSION").read_text(encoding="utf-8").strip(),
            "cgnkCommit": self.tool_commit(),
            "verifiedProjectCommit": self.current_commit(),
            "verificationVersion": VERIFIER_VERSION,
            "verifiedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "hashes": {
                "invariants": {key: canonical_hash(value) for key, value in sorted(self.invariants.items())},
                "capabilities": {key: canonical_hash(value) for key, value in sorted(self.capabilities.items())},
            },
        })
        (self.root / "governance.lock.json").write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "PASS", "recorded": True, "verifiedProjectCommit": lock["verifiedProjectCommit"], "lock": ".cgnk/governance/governance.lock.json"}

    def history(self) -> dict[str, Any]:
        config = read_json(self.root / "history.json")
        commits = config.get("commits", [])
        if not commits:
            raise GovernanceError("HISTORY_COMMITS_MISSING", "No historical commits are declared")
        resolved: list[dict[str, str]] = []
        timeline: dict[str, dict[str, str]] = {item["id"]: {} for item in self.invariants.values()}
        details: list[dict[str, Any]] = []
        for requested in commits:
            sha = git(self.project, "rev-parse", f"{requested}^{{commit}}")
            label = str(requested)[:8]
            resolved.append({"requested": str(requested), "commit": sha, "label": label})
            with tempfile.TemporaryDirectory(prefix="cgkn-history-") as temp_root:
                worktree = Path(temp_root) / "project"
                add = subprocess.run(["git", "worktree", "add", "--detach", str(worktree), sha], cwd=self.project, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if add.returncode:
                    for invariant_id in timeline:
                        timeline[invariant_id][label] = "UNKNOWN"
                    details.append({"commit": sha, "status": "UNKNOWN", "reason": "HISTORY_WORKTREE_FAILED"})
                    continue
                try:
                    dependency_link = attach_dependencies(worktree, self.project)
                    target_status_cache: dict[str, str] = {}
                    for invariant in self.invariants.values():
                        invariant_id = invariant["id"]
                        effective = invariant.get("effectiveFrom", {}).get("commit")
                        if effective:
                            effective_sha = git(self.project, "rev-parse", f"{effective}^{{commit}}", check=False)
                            if not effective_sha or subprocess.run(["git", "merge-base", "--is-ancestor", effective_sha, sha], cwd=self.project).returncode:
                                timeline[invariant_id][label] = "NOT_APPLICABLE"
                                continue
                        target_ids = invariant.get("verification", [])
                        statuses: list[str] = []
                        for target_id in target_ids:
                            if target_id in target_status_cache:
                                statuses.append(target_status_cache[target_id])
                                continue
                            target = self.targets.get(target_id)
                            if not target or not all((worktree / rel).exists() for rel in target.get("requiredFiles", [])):
                                target_status_cache[target_id] = "UNKNOWN"
                                statuses.append("UNKNOWN")
                                continue
                            command = target.get("command")
                            if not isinstance(command, list) or not command:
                                target_status_cache[target_id] = "UNKNOWN"
                                statuses.append("UNKNOWN")
                                continue
                            try:
                                history_env = {**os.environ, "CI": "1", "CGKN_CONSUMER_DEPENDENCIES": str(self.project)}
                                bin_dir = self.project / "node_modules" / ".bin"
                                if bin_dir.is_dir():
                                    history_env["PATH"] = str(bin_dir) + os.pathsep + history_env.get("PATH", "")
                                resolved_command = [str(part) for part in command]
                                executable = shutil.which(resolved_command[0], path=history_env.get("PATH"))
                                if executable:
                                    resolved_command[0] = executable
                                result = subprocess.run(resolved_command, cwd=worktree, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=int(target.get("timeoutSeconds", 180)), env=history_env)
                                collected = not target.get("collectionPattern") or re.search(target["collectionPattern"], result.stdout, re.MULTILINE | re.IGNORECASE)
                                target_status_cache[target_id] = "PASS" if result.returncode == 0 and collected else "FAIL"
                                statuses.append(target_status_cache[target_id])
                            except (FileNotFoundError, subprocess.TimeoutExpired):
                                target_status_cache[target_id] = "UNKNOWN"
                                statuses.append("UNKNOWN")
                        if not statuses or "UNKNOWN" in statuses:
                            timeline[invariant_id][label] = "UNKNOWN"
                        elif "FAIL" in statuses:
                            timeline[invariant_id][label] = "FAIL"
                        else:
                            timeline[invariant_id][label] = "PASS"
                finally:
                    dependency_path = worktree / "node_modules"
                    if dependency_path.exists():
                        try:
                            dependency_path.rmdir()
                        except OSError:
                            pass
                    subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=self.project, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return {
            "kind": "CGKNLongitudinalGovernanceTimeline", "schemaVersion": "1.0", "status": "PASS",
            "commits": resolved, "timeline": timeline, "details": details,
            "metrics": {"historicalCommitsChecked": len(resolved), "permanentInvariantCount": len(self.invariants)},
        }


def find_tool_root() -> Path:
    return Path(__file__).resolve().parents[2]


def render_human(result: dict[str, Any]) -> str:
    lines = [result["status"], "", "Changed:"]
    lines.extend(f"  {value}" for value in result.get("changedFiles", []))
    lines.append("\nCapabilities:")
    lines.extend(f"  {value}" for value in result.get("affectedCapabilities", []))
    lines.append("\nInvariants:")
    lines.extend(f"  {value}" for value in result.get("affectedInvariants", []))
    failed = [c for c in result.get("checks", []) if c["status"] != "PASS"]
    if failed:
        lines.append("\nFailed evidence:")
        lines.extend(f"  {c['code']}: {c['detail'][:800]}" for c in failed)
    lines.append("\nAction:\n  " + result.get("nextAction", ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="CGKN consumer-project longitudinal governance")
    sub = parser.add_subparsers(dest="mode", required=True)
    for name in ("verify", "explain", "record", "history"):
        command = sub.add_parser(name)
        command.add_argument("--project", required=True)
        command.add_argument("--strict", action="store_true")
        command.add_argument("--json", action="store_true")
        command.add_argument("--skip-adversarial", action="store_true", help=argparse.SUPPRESS)
        command.add_argument("--skip-positive", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        engine = GovernanceEngine(Path(args.project), tool_root=find_tool_root(), strict=args.strict or args.mode == "record")
        if args.mode == "record":
            result = engine.record()
        elif args.mode == "history":
            result = engine.history()
        else:
            result = engine.verify(execute=args.mode == "verify", skip_adversarial=args.skip_adversarial, skip_positive=args.skip_positive)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_human(result))
        if args.mode == "explain":
            return 0
        return 0 if result["status"] == "PASS" else 2
    except GovernanceError as exc:
        result = {"status": exc.status, "code": exc.code, "message": str(exc), "toolVersion": VERIFIER_VERSION}
        print(json.dumps(result, ensure_ascii=False, indent=2) if getattr(args, "json", False) else f"{exc.status}\n{exc.code}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
