# Worktree Audit

## Source/test changes to keep

- Python implementation under `scripts/`, including Dynamic Agent Tree, provider transport, profile governance, and delivery guards.
- Tests under `tests/` that verify those implementations and the kernel boundary.
- `pytest.ini`, `.gitignore`, this audit, and maintained contract documentation under `docs/`.
- Current audit snapshot: 260 status entries, including 149 source/test/config entries.

## Runtime/generated outputs to ignore or clean

- `generated/`, `artifacts/`, `.pytest_cache/`, `__pycache__/`, `.service_worktree/`, and `.vs/`.
- `examples/runtime_runs/` and non-fixture files under `examples/test_results/`.
- Large benchmark ZIP files, screenshots, machine-bound reports, provider responses, and long JSONL logs.
- Current examples and runtime bucket: 109 status entries. `artifacts/pytest_progress.jsonl` alone contains test-run progress and must not be committed as source.

## Optional fixtures

- Keep only small deterministic JSON or Markdown inputs required by a named test.
- Store new test-result fixtures under `examples/test_results/fixtures/`.
- Reject fixtures containing absolute machine paths, credentials, live provider output, timestamps used as identity, or generated delivery bundles.

## Recommended commit grouping

1. Provider transport and retry tests.
2. Pytest marker/profile governance and runtime ignore rules.
3. Telegram/Dynamic Tree boundary contract and contract tests.
4. Dynamic Agent Tree source and focused tests already proven by the prior evaluation.

Before staging, select these paths explicitly. Do not use `git add -A` while runtime and example outputs remain dirty.
