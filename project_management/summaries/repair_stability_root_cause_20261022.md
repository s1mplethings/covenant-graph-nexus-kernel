# ITER-CGNK-REPAIR-STABILITY-ROOT-CAUSE-AND-CAPABILITY-041

## Outcome

The previously unstable blank-row repair case is qualified on the frozen Source Closure `dc640cd9426616663a613f540a6d4e1e5a7898e7`:

- Qwen `qwen3.8-max`: 3/3 fresh repairs passed.
- DeepSeek `deepseek-flash`: 3/3 fresh repairs passed and is `QUALIFIED_ON_CASE`.
- Every formal run used one logical repair call and one transport attempt.
- Target reproduction, targeted pytest, interface validation, candidate commit, and baseline isolation passed in every run.
- No manual candidate edit, hidden-source disclosure, Provider fallback, model upgrade, or call-budget increase was used.

This closes the isolated repair-stability blocker. It does not establish general repair capability and does not replace current-source CSV Single, Seeded Repair, or CSV repeatability evaluation.

## Causal finding

The old evidence packet was complete enough to expose the correct file, function, dependencies, public expected value, and public actual value. All six historical candidates edited `csv_cleaner/__main__.py:_print_preview`, and both historical successful patches replayed independently on pristine baselines. Localization and action-space size were therefore not the main cause.

The missing fact was lower-level but still public: raw stdout transport/newline behavior. The previous packet normalized stdout into parsed CSV rows and described an extra empty record, which hid the Windows newline translation mechanism. Generic failure-slice plus contrast evidence did not fix this (E2 0/2); localizing the same action space did not fix it (E3 0/2). Adding deterministic raw-byte/newline contrast without disclosing the answer produced E4 3/3 in discovery and 3/3 for each formal Provider route.

Primary classification: `EVIDENCE_OBSERVABLE_TRANSPORT_PRECISION`.

Secondary observation: identical evidence and sampling produced different historical Qwen semantic patches, so model semantic variability existed, but temperature was already `0.0` and was held fixed. No unsupported `top_p`, `top_k`, or `seed` control was claimed.

## Experiment summary

| Variant | Evidence | Scope | Result | Input tokens/run |
|---|---|---|---:|---:|
| E0 | historical current packet | normal | Qwen 2/3; DeepSeek 0/3 | historical |
| E1 | current packet, temperature 0 | normal | Qwen 4/5 | 1,097 |
| E2 | failure slice + public contrast | normal | Qwen 0/2, early stop | 1,837 |
| E3 | E2 | localized | Qwen 0/2, early stop | 1,838 |
| E4 | failure slice + raw transport contrast | normal | Qwen 3/3 discovery | 1,923 |

E4 increased input tokens by about 75% versus E1, remaining below the 2x rejection threshold. The observed success changed from 4/5 to 3/3, which is directional small-sample evidence, not a claim of statistical significance.

## Formal qualification

Qwen run IDs:

- `worker-repair-e4-qwen-1-840c360108`
- `worker-repair-e4-qwen-2-c190fc0fb0`
- `worker-repair-e4-qwen-3-3dd73c4e34`

Each used 1,923 input tokens and 161 output tokens. Durations were 13,309 ms, 10,116 ms, and 10,058 ms.

DeepSeek run IDs:

- `worker-repair-e4-deepseek-1-ded64e68f4`
- `worker-repair-e4-deepseek-2-0f00695a75`
- `worker-repair-e4-deepseek-3-c0a76b9290`

Each used 2,370 input tokens and 152 output tokens. Durations were 7,908 ms, 6,584 ms, and 7,285 ms.

Provider request identity is now recorded above the frozen Kernel boundary using the canonical system/user/schema/model-config projection. It is stable within each formal group and differs by Provider configuration.

## Source and evidence

- Base: `28b32cdb1143272d4ae3b361b9d0a61504e3f6c0`
- Source Closure: `dc640cd9426616663a613f540a6d4e1e5a7898e7`
- Source tree: `66056cf6432227681a117b1f5df9c3e6999475cd`
- API Lab: `7c15f2546ec007cc7e601fa62ae4d88b9ba12f80`, unchanged, clean, remote verified
- Offline forensic evidence: `D:/CGKN/.service_evidence/repair-stability-root-cause-v1/offline/repair_stability_forensics.json`
- Qwen qualification: `D:/CGKN/.service_evidence/repair-stability-root-cause-v1/qualification-final/strong-qwen/worker_repair_probe/qwen_e4_qualification_index.json`
- DeepSeek qualification: `D:/CGKN/.service_evidence/repair-stability-root-cause-v1/qualification-final/cheap-deepseek/worker_repair_probe/deepseek_e4_qualification_index.json`

## Remaining gate

`minimal_blueprint_status` remains `PARTIAL` and `efficiency_experiment_ready` remains `false`. The next authorized step is a fresh current-source CSV Single, then Seeded Repair and CSV repeatability within the unchanged eight-call project budget. Multi-Agent remains blocked by the efficiency experiment gate.
