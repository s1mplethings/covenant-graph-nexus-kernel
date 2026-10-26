# Reproducibility

## Release identity

- Version: `0.2.0-rc.6`
- Source closure: `56cba0c04abb659f53eadef406c23388fd1cc891`
- Source tree: `8104de0173ae11aa7a603cf099b1536728b8705c`
- Evidence closure: recorded in `research/release-060/evidence_closure.json`
- API Lab dependency: `7c15f2546ec007cc7e601fa62ae4d88b9ba12f80`
- Python: 3.10 or newer

## Clean installation

```bash
git clone https://github.com/s1mplethings/covenant-graph-nexus-kernel.git
cd covenant-graph-nexus-kernel
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[test]"  # Windows
python scripts/product_direction_gate.py
```

On POSIX, activate `.venv/bin/python` instead. The release-candidate clean-clone
gate used Python 3.12, an editable isolated install, compileall, the product
direction gate, focused release tests, and a 100-node offline benchmark smoke.

## Core verification

```bash
python -m compileall -q cgkn contracts scripts
python scripts/product_direction_gate.py
python scripts/kernel_architecture_gate.py
python scripts/test_architecture_gate.py
python scripts/kernel_completeness_gate.py
python scripts/verify_kernel_test_receipt.py
python scripts/receipt_freshness.py
python -m pytest --collect-only -q
python -m pytest -q
```

The exact rc.6 active-repository totals are recorded in the ITER-060 technical
report and regression receipt. Network/provider tests remain skipped unless explicitly
configured.

## ITER-060 complexity frontier

With the exact frozen API Lab checkout available locally:

```bash
python scripts/run_release_060.py preflight --artifact-root /external/iter-060
python scripts/run_release_060.py formal \
  --artifact-root /external/iter-060 \
  --api-lab-root /path/to/frozen-api-lab
python scripts/run_release_060.py analyze \
  --artifact-root /external/iter-060 \
  --source-version 56cba0c04abb659f53eadef406c23388fd1cc891
```

The formal manifest, aggregate JSON/CSV results, complexity and project-type
matrices, claim ledger, failure analysis, and report are under
`research/release-060/`. Real project snapshots and private evaluator packets
remain outside Git.

## ITER-059 Project Corpus evaluation

```bash
python scripts/run_project_corpus_evaluation.py \
  --output-root /absolute/external/iter-059-formal \
  --source-version <source-closure-sha> \
  --clean
```

The deterministic profile backfills six explicit repository example roots,
runs success/failure-repair/partial dogfoods, verifies privacy quarantine,
reconstruction, portable import/export, catalog rebuild, split isolation,
search/sampling, and evaluates 1,000 snapshots with at least 10,000 file
references. Real corpus contents stay outside the repository; only aggregate,
secret-safe evidence is retained under `research/release-059/`.

## Release hygiene and routing oracle

```bash
python scripts/release_compliance_audit.py \
  --history \
  --scope-commit 7b81a3dde5823dd9ccc31839441bffc6b6acfe98 \
  --output history-audit.json

python scripts/run_release_057_oracle.py \
  --direct /path/to/release-056/direct/index.json \
  --architecture /path/to/release-056/optimized-cgnk/index.json \
  --output oracle-analysis.json \
  --json
```

The history audit scans unique named text blobs of at most 8 MiB that are
reachable from the explicit scope commit. The routing oracle is development
evidence derived from already-observed ITER-056 outcomes; it is not a fresh
holdout.

## Offline benchmark smoke

```bash
python scripts/run_release_056_profile.py \
  --knowledge-sizes 100 \
  --capability-scales 100 \
  --repeats 1 \
  --output release-056-smoke.json \
  --json
```

## ITER-058 formal evaluation

With the exact API Lab checkout available locally:

```bash
python scripts/run_release_058.py preflight --api-lab-root /path/to/api-lab
python scripts/run_release_058.py formal \
  --api-lab-root /path/to/api-lab \
  --artifact-root artifacts/release-058-formal-runtime
python scripts/run_release_058.py analyze \
  --index artifacts/release-058-formal-runtime/<batch>/index.json
```

The formal manifest, prompt, schema, baselines, state projection, model config,
Source Closure, and API Lab commit are hash-bound. The release asset
`iter-058-formal-index.json` is the normalized, secret-safe 54-run index; its
hash is recorded in `research/release-058/formal_index_manifest.json`.

## Earlier formal evaluation

The frozen task manifest, configurations, hypotheses, and pricing snapshot live
under `research/release-056/`. Provider execution requires the separately
versioned API Lab checkout and local credentials. Run output must be written
outside the repository. See `research/release-056/report/reproduction.md` for
commands and public benchmark environment requirements.

Raw provider text and restricted public benchmark datasets are deliberately not
committed. Result hashes, aggregate metrics, task identifiers, and exact pinned
revisions are sufficient to audit the published claims without redistributing
third-party data.
