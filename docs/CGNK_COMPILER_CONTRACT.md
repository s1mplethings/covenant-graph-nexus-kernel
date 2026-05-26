# CGNK Compiler Contract

CGNK core validates and compiles contracts. It does not execute modules, call providers, generate projects, connect Telegram, create delivery zips, or manage runtime state.

The compiler pipeline is:

1. schema validation
2. ref resolution
3. semantic validation
4. policy effect and capability validation
5. artifact graph summary
6. compiled contract bundle emission
7. contract pack emission for downstream agents

All diagnostics must use stable `CGNK_*` codes.
