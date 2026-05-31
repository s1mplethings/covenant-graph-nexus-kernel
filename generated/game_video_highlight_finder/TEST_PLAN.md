# Test Plan

1. Load the deterministic fixture and verify candidates render.
2. Import a local gameplay video and confirm file metadata appears.
3. Paste event JSON and verify events change scoring reasons.
4. Add a manual mark and verify manual candidates are visible.
5. Filter by category and minimum score.
6. Export the JSON cut list.
7. Run `tests/browser_smoke_test.js` and `tests/industrial_io_smoke_test.js` through the CGNK test pipeline.
