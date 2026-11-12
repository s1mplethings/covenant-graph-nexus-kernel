"""Run the existing authorized acceptance under the canonical job lifecycle.

This wrapper adds no Provider call, authorization, retry or result-admission rule.
The immutable acceptance receipts and run_case remain authoritative.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def main(argv=None, *, runner=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('case_id')
    parser.add_argument('confirmation')
    parser.add_argument('--result',required=True)
    parser.add_argument('--generation-job-state',required=True)
    parser.add_argument('--generation-job-id',required=True)
    parser.add_argument('--generation-attempt-id',required=True)
    args=parser.parse_args(argv)
    root=Path(__file__).resolve().parents[3]
    sys.path.insert(0,str(root/'tools/cgkn-agent-kit/src'))
    from cgkn_agent_kit import core
    state=Path(args.generation_job_state)

    def update(**changes):
        with core.generation_job_lock(state.parent):
            current=core.read_json(state)
            if (current.get('job_id'),current.get('attempt_id')) != (args.generation_job_id,args.generation_attempt_id):
                raise RuntimeError('ACCEPTANCE_WORKER_JOB_IDENTITY_CHANGED')
            core.write_json(state,{**current,**changes,'process_id':os.getpid(),
                'updated_at':core.now(),'revision':int(current.get('revision',0))+1})

    update(state='RUNNING',run_id=args.case_id)
    try:
        if runner is None:
            if args.case_id.startswith("ITER118-"):
                from experiments.api_acceptance.archive_20261029.api_final_acceptance import run_case
            else:
                from experiments.api_acceptance.archive_20261029.streaming_live_acceptance import run_case
            runner=run_case
        # Original run_case enforces sealed authorization, consumed-attempt and
        # UNKNOWN barriers. Never substitute the wrapper's job IDs for its IDs.
        result=runner(args.case_id,args.confirmation)
        core.write_json(Path(args.result),{'job_id':args.generation_job_id,
            'attempt_id':args.generation_attempt_id,'acceptance':result})
        update(state='COMPLETE' if result.get('status')=='PASS' else 'FAILED',
            terminal_reason='ACCEPTANCE_'+str(result.get('status','UNCONFIRMED')))
        return 0
    except Exception as exc:
        update(state='FAILED',terminal_reason='ACCEPTANCE_WORKER_REFUSED',error_type=type(exc).__name__)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
