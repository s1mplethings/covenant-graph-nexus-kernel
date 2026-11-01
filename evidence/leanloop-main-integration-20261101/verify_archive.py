"""Archive publication checks only. Functional regression remains FAILED."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def cases(label):
    result = {}
    for case in ET.parse(ARCHIVE / label / "results.xml").findall(".//testcase"):
        key = case.get("classname") + "::" + case.get("name")
        assert key not in result, key
        result[key] = ("FAIL" if case.find("failure") is not None or case.find("error") is not None
                       else "SKIP" if case.find("skipped") is not None else "PASS")
    return result

def main():
    for row in json.loads((ARCHIVE / "archive-hashes.json").read_text(encoding="utf-8")):
        assert sha(ARCHIVE / row["path"]) == row["sha256"], row["path"]
    for row in json.loads((ARCHIVE / "resolution-inventory.json").read_text(encoding="utf-8")):
        assert sha(ROOT / row["path"]) == row["candidate_sha256"], row["path"]
    baseline, candidate = cases("baseline-critical"), cases("integration-smoke")
    assert len(baseline) == 178 and sum(v == "PASS" for v in baseline.values()) == 177
    assert baseline.keys() <= candidate.keys()
    new = sorted(k for k in baseline if baseline[k] == "PASS" and candidate[k] == "FAIL")
    verdict = json.loads((ARCHIVE / "regression-verdict.json").read_text(encoding="utf-8"))
    assert new == sorted(row["id"] for row in verdict["new_failures"])
    assert len(new) == 21 and verdict["verdict"] == "REJECTED_FOR_MAIN_PUBLICATION"
    assert sum(v == "PASS" for v in candidate.values()) == 312
    assert "REGRESSION FAILED" in (ROOT / "INTEGRATION_STATUS.md").read_text(encoding="utf-8")
    print(json.dumps({"archive_integrity": "PASS", "functional_regression": "FAIL",
                      "new_failures": 21, "main_merge_authorized": False}))

if __name__ == "__main__":
    main()
