# Reproducibility

## Release identity

- Version: `0.2.0-rc.2`
- Source closure: `c495738556ac1ee288df232a2b372a8294968051`
- Evidence base: `2ad4c6508fd0ce2b4074770cd2b857925dc2ffd2`
- API Lab dependency: `999dff096afe45f058fe67016aee28a73912d5d4`
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

The final active-repository result was 3,001 passed, 363 skipped, 0 failed, and
0 errors. Network/provider tests remain skipped unless explicitly configured.

## Offline benchmark smoke

```bash
python scripts/run_release_056_profile.py \
  --knowledge-sizes 100 \
  --capability-scales 100 \
  --repeats 1 \
  --output release-056-smoke.json \
  --json
```

## Formal evaluation

The frozen task manifest, configurations, hypotheses, and pricing snapshot live
under `research/release-056/`. Provider execution requires the separately
versioned API Lab checkout and local credentials. Run output must be written
outside the repository. See `research/release-056/report/reproduction.md` for
commands and public benchmark environment requirements.

Raw provider text and restricted public benchmark datasets are deliberately not
committed. Result hashes, aggregate metrics, task identifiers, and exact pinned
revisions are sufficient to audit the published claims without redistributing
third-party data.
