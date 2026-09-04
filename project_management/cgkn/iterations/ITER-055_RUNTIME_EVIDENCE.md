# ITER-055 Runtime Evidence

This support record cannot authorize a customer candidate, package, delivery,
or formal public PASS.

## Reproduced production failures

- Live run `production-da8cc0d22717424cba16c0c828229a5e` used
  `qwen3.7-plus`, built two real parallel foundation leaves, and reused the
  passing foundation checkpoint during affected-only backend repair.
- The canonical plan required `app/main.py`, while the browser-local static
  validator required root `main.py`; three semantic attempts therefore stopped
  with `provider static-only backend manifest must contain exactly main.py`.
- The resulting non-PASS Provider document was then sent to causal response
  consumption without materialized staging and was obscured by
  `provider causal capture requires candidate, staging and result`.
- No candidate, package, delivery manifest, or receipt was created.

## Corrective action

- Browser-local static manifest instructions and validation now derive their
  launcher path from the same canonical required-path list.
- Non-PASS Provider documents stop before causal response consumption and keep
  their first recorded blocker.
- No Provider scheduler, generation route, supervisor, fallback, or delivery
  exit was added.

## Verification to date

- Direct reproduced regressions: 3 passed.
- Focused manifest profile: 5 passed, 143 deselected.
- Provider recovery, False-Pass, and kernel contract profile: 49 passed.
- Live production rerun: pending.

## Experience usage

- `EXP-CGKN-QUALITY-001`: kept the failed generation, candidate, evidence, and
  delivery states separate and did not promote partial Provider output.
