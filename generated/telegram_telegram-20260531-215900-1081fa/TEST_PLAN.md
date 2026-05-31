# Test Plan

1. Load the deterministic fixture and verify candidates render.
2. Import a local gameplay video and confirm file metadata appears.
3. Analyze the video and verify frame/audio-derived candidates appear.
4. Filter by category and minimum score.
5. Export the JSON cut list.
6. Run `tests/browser_smoke_test.js` and `tests/industrial_io_smoke_test.js` through the CGNK test pipeline.
