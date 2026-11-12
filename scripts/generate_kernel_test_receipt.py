from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import platform
import sys
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from kernel_source_identity import ROOT, identity


def _hash_file(path: pathlib.Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: dict) -> str:
    payload = {key: item for key, item in value.items() if key != "receipt_hash"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def generate(profile_path: pathlib.Path, coverage_path: pathlib.Path, source_commit: str) -> dict:
    source = identity(source_commit)
    profiles = json.loads(profile_path.read_text(encoding="utf-8"))
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    results = list(profiles.get("results", []))
    commands = [{"argv": command.get("argv", []), "returncode": command.get("returncode")} for profile in results for command in profile.get("commands", [])]
    totals = {key: sum(int(profile.get("totals", {}).get(key, 0)) for profile in results) for key in ("passed", "failed", "errors", "skipped")}
    totals["duration_seconds"] = round(sum(float(profile.get("duration_ms", 0)) for profile in results) / 1000, 3)
    nodeids = sorted({nodeid for profile in results if profile.get("status") == "PASS" for nodeid in profile.get("test_node_ids", [])})
    required_profiles = {"static", "unit", "boundary", "fault", "security", "local-functional", "full-core", "active-repository", "live-provider"}
    profile_names = {str(profile.get("profile")) for profile in results}
    coverage_matches = all(coverage.get(key) == source.get(key) for key in ("source_commit", "source_tree_sha", "core_source_hash"))
    verdict = "PASS" if required_profiles <= profile_names and all(profile.get("status") in {"PASS", "BLOCKED_ENVIRONMENT"} for profile in results) and totals["failed"] == totals["errors"] == 0 and coverage_matches and coverage.get("pytest_result", {}).get("exit_code") == 0 else "FAIL"
    value = {
        "kind": "CGKNKernelTestReceipt", "schema_version": "1.0",
        "source_commit": source["source_commit"], "source_tree_sha": source["source_tree_sha"], "core_source_hash": source["core_source_hash"],
        "commands": commands, "totals": totals, "test_node_ids": nodeids, "profile_results": results,
        "coverage_file_hash": _hash_file(coverage_path), "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "provider_network_usage": {"live_provider_executed": any(profile.get("profile") == "live-provider" and profile.get("status") == "PASS" for profile in results), "secret_persisted": False},
        "final_verdict": verdict,
    }
    value["receipt_hash"] = _canonical_hash(value)
    return value


def main() -> int:
    if len(sys.argv)>1 and sys.argv[1]=='working-tree':
        return generate_working_tree_receipt(sys.argv[2:])
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", default="governance/kernel_test_receipt.json")
    args = parser.parse_args()
    value = generate(ROOT / args.profiles, ROOT / args.coverage, args.source_commit)
    (ROOT / args.output).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, indent=2))
    return 0 if value["final_verdict"] == "PASS" else 1


def generate_working_tree_receipt(argv):
    """Run mapped checks and offline application/experiment validation.

    This is the producer for freshness checks, not a full-closure verdict.
    The full profile subsequently tests those freshness checks themselves.
    Historical committed receipts are retained unchanged.
    """
    from source_boundaries import BOUNDARIES,boundary_identity
    from receipt_freshness import WORKTREE_RECEIPT,junit_nodeid
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-directory',type=pathlib.Path,required=True)
    args=parser.parse_args(argv)
    output=args.output_directory.resolve();output.mkdir(parents=True,exist_ok=False)
    before={name:boundary_identity(name,'WORKTREE') for name in BOUNDARIES}
    (output/'source-before.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
    manifest=json.loads((ROOT/'governance/test_coverage_manifest.json').read_text(encoding='utf-8'))
    mapped=sorted({case['nodeid'] for row in manifest['sources'].values() for case in row['test_cases']})
    junit=output/'validation.xml'
    arguments=[*mapped,'tests/application/software_project','tests/experiments',
        '--run-profile-marked','-m','not live_provider and not provider and not stress and not soak and not benchmark and not longrun and not long_journey',
        '-q','--junitxml='+str(junit)]
    argument_file=output/'pytest-arguments.json'
    argument_file.write_text(json.dumps(arguments),encoding='utf-8')
    command=[sys.executable,'-c','import json,sys,pytest;sys.exit(pytest.main(json.load(open(sys.argv[1],encoding="utf-8"))))',str(argument_file)]
    with (output/'validation.log').open('w',encoding='utf-8') as log:
        code=subprocess.call(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    after={name:boundary_identity(name,'WORKTREE') for name in BOUNDARIES}
    unchanged=before==after
    passed=set();failed=[];skipped=[]
    if junit.exists():
        for case in ET.parse(junit).iter('testcase'):
            nodeid=junit_nodeid(case)
            if case.find('failure') is not None or case.find('error') is not None:failed.append(nodeid)
            elif case.find('skipped') is not None:skipped.append(nodeid)
            else:passed.add(nodeid)
    required={'kernel':mapped,
        'application':sorted(p for p in passed if p.startswith('tests/application/software_project/')),
        'experiment':sorted(p for p in passed if p.startswith('tests/experiments/'))}
    valid=code==0 and unchanged and not failed and not skipped and set(mapped)<=passed and all(required.values())
    receipt={'kind':'CGKNWorkingTreeTestReceipt','status':'PASS' if valid else 'FAIL',
        'scope':'Host mapped source checks and offline application/experiment validation; not C01-C10 qualification',
        'boundaries':before,'required_node_ids':required,'failed_node_ids':failed,'skipped_node_ids':skipped,
        'runs':[{'command':command,'pytest_arguments':arguments,'returncode':code,'source_unchanged':unchanged,
            'junit_path':str(junit),'junit_sha256':hashlib.sha256(junit.read_bytes()).hexdigest() if junit.exists() else None}]}
    rendered=json.dumps(receipt,indent=2)+'\n'
    (output/'TestReceipt.json').write_text(rendered,encoding='utf-8')
    if valid:(ROOT/WORKTREE_RECEIPT).write_text(rendered,encoding='utf-8')
    print(json.dumps({'status':receipt['status'],'passed':len(passed),'failed':len(failed),'skipped':len(skipped),'source_unchanged':unchanged}))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
