# Commercial Readiness Gate

`scripts/run_commercial_readiness.py` aggregates environment checks, provider preflight, sandbox scan, focused tests, anti-fake checks, product acceptance, warning classification, customer status samples, and Telegram delivery split metadata.

Verdicts:

- `COMMERCIAL_READY`: provider OK, tests pass, security pass, anti-fake pass, formal project PASS_FINAL, product acceptance commercial-ready, and no critical warnings.
- `COMMERCIAL_BETA`: local safety checks pass, but provider quota is blocked, live regression is incomplete, or product acceptance is not yet commercial-ready.
- `COMMERCIAL_BLOCKED`: final truth bypass exists, security fails, fake artifacts are accepted, candidate-as-final is accepted, or corrupt evidence is accepted.

Provider quota blocked is reported as beta/provider-blocked, not as a project generation failure. The readiness report may recommend a release label, but it is not a delivery manifest and cannot authorize public delivery by itself.
