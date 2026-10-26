from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from cgkn.application.software_project import SoftwareProjectGenerationService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="+", required=True)
    parser.add_argument("--artifact-root", type=pathlib.Path, default=ROOT / "artifacts" / "project_generation")
    args = parser.parse_args(argv)
    config = json.loads((ROOT / "config" / "software_project_generation.json").read_text(encoding="utf-8"))
    service = SoftwareProjectGenerationService(ROOT, args.artifact_root, config=config)
    results = [service.run_case(case, max_repair_rounds=int(config["max_application_repair_rounds"])).as_dict() for case in args.cases]
    report = {"kind": "CGKNSoftwareProjectGenerationSuite", "schema_version": "1.0", "results": results, "status": "PASS" if all(row["status"] == "PASS" for row in results) else "FAIL"}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
