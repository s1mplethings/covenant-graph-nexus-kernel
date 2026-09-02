# ITER-024 Runtime Evidence

## Outcome

`PASS_WITH_LIMITS` for the offline experiment. This is management and runtime
evidence for an isolated mock-Provider candidate, not formal Provider or public
delivery evidence.

## Frozen comparison

| Measure | Preserved failed baseline | Supervised offline candidate |
| --- | ---: | ---: |
| Concrete callable command handlers | 0 / 9 | 9 / 9 |
| Primary implementation files | 10 Backend checkpoint files | 6 source files |
| Test granularity | 19 planned test leaves | 3 behavior-focused test files |
| Executable candidate | No | Yes |
| Test result | No passing generated suite | pytest 6 / 6 and unittest 6 / 6 |
| External Provider requests | 87 in the baseline | 0 in this offline experiment |

The request-count row is not an A/B token claim. The right-hand candidate was
created by the explicitly labelled `offline_mock_provider`, so real Provider
request and token savings remain `NOT_EVALUATED`.

## Static and runtime checks

- `python -m compileall -q focusforge tests`: PASS.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`: 6 passed in 3.04s.
- `python -m unittest discover -s tests -v`: 6 passed in 3.199s.
- AST inspection: 9 expected handler functions, 9 present.
- Size bound: 6 primary source files and 3 test files.
- Source-and-test SHA-256: `7d79d30b3040c725f7c76bc7afb7918db9934c4e9951283f75c6eadde55811a4`.

The direct CLI run created `T-0001` and `B-0001`, moved the task to `done`,
returned one filtered bug, summarized two items, exported two items, reduced the
workspace to one item after deletion, restored two items with replace import,
and confirmed both the workspace and atomic backup existed.

## Demonstrated effect

The supervisor brief had a positive effect on logical structure in this bounded
offline experiment: it preserved the named product domain, made every command a
callable interface, ordered dependencies model -> repository -> service -> CLI,
and prevented test-leaf amplification. The project is directly executable.

Actual external Provider behavior, prompt-token savings, formal post-build
finalization, packaging, and public delivery remain `NOT_EVALUATED`.
