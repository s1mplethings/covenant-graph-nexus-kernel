# Release 056 Reproduction Guide

Use the commands in `/REPRODUCIBILITY.md` for installation and regression.
Formal internal runs require the API Lab checkout frozen at
`999dff096afe45f058fe67016aee28a73912d5d4` and locally configured provider
credentials. Never persist gateway tokens.

For each baseline, invoke `scripts/run_release_056_eval_gateway.py` with
`--profile cross-domain-holdout`, one of the five baseline identifiers in
`main_results.csv`, an external artifact root, and an external budget-ledger
root. Analyze the five resulting `index.json` files with
`scripts/analyze_release_056.py`, the frozen pricing snapshot, and a new
external analysis directory.

Public benchmark repositories must be checked out at the commits in
`../benchmark_manifest.json`. Install and run them according to their official
instructions. If Docker, Python, credentials, data, storage, or licensing is
missing, record the exact `BLOCKED_*` status; do not substitute a smaller task
and label it as the official benchmark. Do not copy their datasets into CGNK.
