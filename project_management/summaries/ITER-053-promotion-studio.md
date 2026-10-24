# ITER-053 — Local Promotion Studio

The Promotion Studio application branch is complete with an environment limit on real public posting. It projects committed CGKN evidence into a public-safe claim ledger, detects publishable signals, creates one canonical campaign and platform variants, renders local cards and videos, binds approval to exact content/media hashes, and records restart-safe publication receipts.

Formal evaluation ran from source commit `3c5d2dc7d3eca4947ff319d0a98ac67c9436a1bd` and passed 20/20 signal cases, 10/10 campaign cases, 6/6 media assets, the fake publisher lifecycle, and offline contract probes for Mastodon, Bluesky, and YouTube. Unsupported-claim, private-leakage, unintended-duplicate, credential-exposure, and public-write counts were all zero.

Regression passed with 33 focused Promotion tests, 761 passed / 58 skipped across the combined application domains, 3,260 tests collected, and 2,903 passed / 357 skipped / 0 failed / 0 errors in both active-repository and full pytest runs.

Real public posting was not attempted: no preconfigured test account credentials or explicit content approval existed. This is recorded as `BLOCKED_ENVIRONMENT_REAL_PUBLICATION` and does not block the local-first MVP.

Durable evidence is in `project_management/summaries/ITER-053-evidence/`; the machine-readable status and receipt are `governance/promotion_status.json` and `governance/promotion_receipt.json`.

The repository publisher intentionally rejects binary commits. Rendered PNG/MP4 payloads therefore remain in local CGKN state under `.cgkn/promotion_artifacts/ITER-053/`; versioned evidence retains their hashes, dimensions, codecs, durations, generator configuration, and provenance.
