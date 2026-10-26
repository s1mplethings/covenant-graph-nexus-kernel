# ITER-057 Release Hygiene and Architecture Admission

This package records two bounded decisions:

1. CGNK is the canonical public name; `cgkn` remains the Python package
   namespace and `CGKN...` remains a legacy machine-identifier prefix where
   changing it would break compatibility or frozen evidence.
2. Architecture Router V1 is not authorized because the ITER-056 paired oracle
   adds zero successful tasks over Always Direct Cheap.

The oracle is diagnostic/development evidence because ITER-056 outcomes were
already observed. The stop gate prevents a fitted Router or fresh holdout from
being created when no theoretical benefit exists in the available paired data.

History compliance evidence is generated after the ITER-057 Source Closure and
must name that exact scope commit. No prior release tag is moved or rewritten.
