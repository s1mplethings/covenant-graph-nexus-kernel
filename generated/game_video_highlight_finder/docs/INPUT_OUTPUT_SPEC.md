# Input Output Spec

## Inputs

The project accepts a local gameplay video through `#video-file`. The browser keeps the video local by creating an object URL for preview and metadata extraction. The current deterministic detector uses the video duration and optional event records to create explainable highlight windows. Future implementations can replace the synthetic motion/audio proxy with real canvas frame sampling, WebAudio analysis, WebCodecs, or ffmpeg.wasm.

Optional structured inputs are pasted into `#event-json`. The accepted shape is either a JSON array or an object with `records`, `events`, or `items`. Each record can include `timestampMs`, `eventType`, `value`, and `category`. Manual marks are added through `#manual-form` and converted into weighted scoring signals.

`data/industrial_input_bundle.json` is the automated fixture. It contains a synthetic duration, five source descriptors, and more than twenty event records covering kills, objectives, chat spikes, audio peaks, clutch moments, and manual marks.

## Outputs

The main output is a ranked list of highlight candidates. Every candidate contains title, start timestamp, end timestamp, peak timestamp, score, category, and scoring reasons. The export button emits a JSON cut list with clip title, startMs, endMs, and reason. `data/expected_outputs.json` defines the expected output contract for automated tests.

The project does not send video data to a server. Network and provider use are disabled by design.
