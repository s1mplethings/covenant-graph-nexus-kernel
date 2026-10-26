# Benchmarks and Evaluation

Release 0.2.0-rc.2 uses a preregistered 72-task internal cross-domain holdout
covering twelve domains and five matched configurations. Each configuration is
run once per frozen task with fresh state, one logical call, fixed routing, and
no manual intervention. Results are directional rather than claims of broad
statistical significance.

| Configuration | Success | Total tokens | Median context chars | Estimated cost |
| --- | ---: | ---: | ---: | ---: |
| B0 Direct Cheap | 58/72 (80.56%) | 16,854 | 119 | USD 0.006833 |
| B1 Direct Strong | 46/72 (63.89%) | 29,782 known | 119 | Not evaluated: incomplete usage |
| B2 Flat Context Cheap | 15/72 (20.83%) | 164,071 | 6,861 | USD 0.007371 |
| B3 Current CGNK | 49/72 (68.06%) | 16,752 | 119 | USD 0.006731 |
| B4 Optimized CGNK | 48/72 (66.67%) | 16,716 | 119 | USD 0.006688 |

B4 reduced median context by 98.27% relative to B2 and improved paired success
by 45.83 percentage points. Against B3, B4 changed success by -1.39 percentage
points (paired bootstrap 95% interval -4.17 to 0.00 pp; exact McNemar p=1.0).
Direct Cheap was the strongest configuration on this holdout. Direct Strong
encountered a timeout and then its frozen output-token budget; its cost is null,
not zero.

Public benchmark adapters are pinned to official revisions for CRAG,
LongMemEval-V2, BFCL V4, TUA-Bench, and SWE-bench Pro V2. Formal public scores
are not claimed: the available machine lacked the required dataset/model
storage, Python 3.10/3.11 environments, and Docker daemon. These are recorded as
`ENVIRONMENT_BLOCKED`, a P1 limitation rather than a substituted smaller test.
No benchmark dataset is redistributed.

Official sources and reproduction metadata are in
`research/release-056/benchmark_manifest.json`; procedures are in
`docs/REPRODUCIBILITY.md` and `research/release-056/report/reproduction.md`.
