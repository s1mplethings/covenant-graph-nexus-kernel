"""Rebuild a read-only metric projection from an explicit, isolated JSON input."""
import argparse
import json
from pathlib import Path
from cgkn.telemetry.effectiveness import effectiveness, task_cost, task_time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['effectiveness', 'cost', 'time', 'trusted'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--store',type=Path)
    parser.add_argument('--project')
    parser.add_argument('--run')
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding='utf-8'))
    if args.kind=='trusted':
        if not all((args.store,args.project,args.run)):parser.error('trusted requires --store --project --run')
        from cgkn.state import FileRunStore
        from cgkn.telemetry.trusted_samples import trusted_effectiveness
        result=trusted_effectiveness(FileRunStore(args.store),args.project,args.run,data['sample_refs'])
    else:
        result = {'effectiveness':effectiveness, 'cost':task_cost, 'time':task_time}[args.kind](**data)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)


if __name__ == '__main__':
    main()
