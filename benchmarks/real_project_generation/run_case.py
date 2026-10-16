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
    parser.add_argument("--case", required=True)
    parser.add_argument("--artifact-root", type=pathlib.Path, default=ROOT / "artifacts" / "project_generation")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    config = json.loads((ROOT / "config" / "software_project_generation.json").read_text(encoding="utf-8"))
    result = SoftwareProjectGenerationService(ROOT, args.artifact_root, config=config).run_case(args.case, max_repair_rounds=int(config["max_application_repair_rounds"]))
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2) if args.json else result.status.value)
    return 0 if result.status.value == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
