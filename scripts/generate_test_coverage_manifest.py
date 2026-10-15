from __future__ import annotations

import json
import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


def metadata() -> list[dict[str, object]]:
    completed = subprocess.run([sys.executable, "scripts/collect_kernel_test_metadata.py"], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout)
    return list(json.loads(completed.stdout)["tests"])


def generate() -> dict[str, object]:
    current = json.loads((ROOT / "governance/test_coverage_manifest.json").read_text(encoding="utf-8"))
    tests = metadata()
    sources: dict[str, object] = {}
    for source, entry in sorted(current["sources"].items()):
        package = source.split("/")[1]
        prefixes = [f"tests/{package}/"]
        prefixes.extend({
            "artifacts": ["tests/test_artifact_driven_kernel.py"],
            "compiler": ["tests/test_artifact_driven_kernel.py"],
            "governance": ["tests/test_consumer_governance.py"],
            "providers": ["tests/test_provider_transport.py"],
            "runtime": ["tests/test_artifact_driven_kernel.py"],
        }.get(package, []))
        candidates = [item for item in tests if any(str(item["nodeid"]).startswith(prefix) for prefix in prefixes)]
        required = list(entry.get("required_classes", []))
        for flagged, test_class in ((entry.get("state"), "roundtrip"), (entry.get("security"), "security"), (entry.get("provider"), "fault_injection"), (entry.get("network"), "live_provider")):
            if flagged and test_class not in required:
                required.append(test_class)
        selected: dict[str, set[str]] = {}
        missing: list[str] = []
        for test_class in required:
            match = next((item for item in candidates if test_class in item["markers"]), None)
            if match is None:
                missing.append(test_class)
                continue
            selected.setdefault(str(match["nodeid"]), set()).add(test_class)
        if missing:
            raise RuntimeError(f"{source} has no marked test for: {','.join(missing)}")
        sources[source] = {
            "criticality": entry["criticality"],
            "required_classes": required,
            "test_cases": [{"nodeid": nodeid, "classes": sorted(classes)} for nodeid, classes in sorted(selected.items())],
            "state": bool(entry.get("state")), "security": bool(entry.get("security")), "provider": bool(entry.get("provider")), "network": bool(entry.get("network")),
        }
    return {"kind": "CGKNTestCoverageManifest", "schema_version": "2.0", "required_core_packages": current["required_core_packages"], "sources": sources}


def main() -> int:
    value = generate()
    path = ROOT / "governance/test_coverage_manifest.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(value['sources'])} source mappings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
