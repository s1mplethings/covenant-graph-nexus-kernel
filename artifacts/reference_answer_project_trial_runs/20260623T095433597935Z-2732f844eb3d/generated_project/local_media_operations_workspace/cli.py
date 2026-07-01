from __future__ import annotations

import argparse
import orchestrator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="fixtures/media_fixture.json")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()
    result = orchestrator.run(input_path=args.input, output_dir=args.output_dir)
    print(result)
    return 0 if result.get("status") != "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
