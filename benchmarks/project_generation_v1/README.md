# CGKN Project Generation Benchmark v1

This directory is an evaluation layer, not a production generation path. The
runner invokes the reviewed production facade as a subprocess and forwards only
the selected case's `user_goal`. Hidden acceptance is opened only by the
independent evaluator after generation.

Typical commands:

```powershell
python benchmarks/project_generation_v1/run_benchmark.py --dry-run
python benchmarks/project_generation_v1/run_benchmark.py --case 03
python benchmarks/project_generation_v1/run_benchmark.py --level L2
python benchmarks/project_generation_v1/run_benchmark.py --pilot
python benchmarks/project_generation_v1/run_benchmark.py --all
python benchmarks/project_generation_v1/run_benchmark.py --resume --run-id <id> --all
python benchmarks/project_generation_v1/run_benchmark.py --report-only --run-id <id>
```

Live evaluation requires an independent evaluator command that writes the
identity-bound observations declared in `evaluator_input.json`. A controlled
repair command is run only after the initial black-box happy path passes. It
must inject one safe fault, call the existing CGKN recovery mechanism, and emit
the affected-job, Provider-call, evidence-invalidation, re-emission, and
recovery receipt. Missing evaluation or repair evidence remains
`NOT_EVALUATED`; Provider availability, quota, TLS, or timeout failures remain
`BLOCKED_PROVIDER`.

Dry-run fixtures exist only for CASE_01 and CASE_03. They validate harness
isolation, execution, persistence, delivery inspection, scoring, aggregation,
resume, and reporting, and can never produce `PROJECT_PASS`.
