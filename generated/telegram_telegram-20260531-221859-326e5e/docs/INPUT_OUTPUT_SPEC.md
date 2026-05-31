# Input Output Spec

## Inputs

The project accepts exactly one required runtime input: a local gameplay video through `#video-file`. The browser keeps the video local by creating an object URL for preview and metadata extraction. The current deterministic detector derives frame samples, audio peaks, signal windows, and highlight candidates from the video metadata. Future implementations can replace the deterministic frame/audio proxy with real canvas frame sampling, WebAudio analysis, WebCodecs, or ffmpeg.wasm.

`data/industrial_input_bundle.json` is the automated fixture. It contains one synthetic video descriptor and a source manifest. It does not add event JSON, chat, telemetry, or manual marks because those are not part of the MVP input contract.

## Outputs

The main output is a ranked list of highlight candidates. Every candidate contains title, start timestamp, end timestamp, peak timestamp, score, category, and scoring reasons. The export button emits a JSON cut list with startMs, endMs, score, and reason. `data/expected_outputs.json` defines the expected output contract for automated tests.

The project does not send video data to a server. Network and provider use are disabled by design.
