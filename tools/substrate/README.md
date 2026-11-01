# Candidate reproducible trusted-host checks

Status: DEFERRED. This environment is not the default CI environment. The full
Windows trial exposed a test that assumes Popen.pid is the Gateway worker PID;
Windows virtual-environment launchers violate that assumption. Keep that failure
visible; do not weaken its identity assertion. Core contracts passed (367).
The original host interpreter remains the full regression reference.

The kernel remains source-imported. This lock describes the host test/network
tools, not generated applications or optional candidate frameworks. This full host test profile requires Python 3.11+, matching existing CI and
metrics dependencies. The standalone Agent kit retains its Python 3.10 support.
Resolution includes platform and Python markers.

Use uv 0.13.6 in a dedicated environment. Do not sync a shared environment.

```powershell
uv venv .venv-substrate-check --python python --no-python-downloads
uv pip sync --python .venv-substrate-check/Scripts/python.exe --require-hashes tools/substrate/requirements.lock
.venv-substrate-check/Scripts/python.exe -m pytest -q
.venv-substrate-check/Scripts/ruff.exe check --config tools/substrate/ruff.toml experiments/substrate_migration
```

On Linux the interpreter and executable paths use `bin/` instead of `Scripts/`.
Regenerate deliberately with:

```text
uv pip compile tools/substrate/requirements.in --universal --python-version 3.11 --no-python-downloads --generate-hashes -o tools/substrate/requirements.lock
```

Ruff is applied only to changed Python files. No whole-repository formatting or
new production runtime dependency is implied. Optional SDK, Agent, evaluation,
and tracing experiments use their own isolated environment.
