# Game Video Highlight Finder

Local-first browser project for finding candidate highlights in game videos.

## Use

Open `index.html`, choose a gameplay video, optionally paste event JSON, and click `Analyze Video`. Use `Load Fixture` for deterministic test data. Export creates a JSON cut list with timestamps and reasons.

## Current Detection Basis

The MVP uses duration-aware signal windows plus optional telemetry and manual marks. It is built so real frame sampling, WebAudio, WebCodecs, or ffmpeg.wasm can replace the proxy detector without changing the output contract.

## Files

- `index.html`
- `app.js`
- `styles.css`
- `data/industrial_input_bundle.json`
- `data/expected_outputs.json`
- `docs/INPUT_OUTPUT_SPEC.md`
- `tests/browser_smoke_test.js`
- `tests/industrial_io_smoke_test.js`
