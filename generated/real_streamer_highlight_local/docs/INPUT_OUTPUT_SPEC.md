# Input/Output Specification

## Inputs

The app accepts a JSON array of livestream event records. Each record may include `streamer`, `game`, `time`, `title`, `category`, `intensity`, `chatRate`, `keywords`, `description`, `sourceId`, and `source_type`.

`data/industrial_input_bundle.json` is the deterministic industrial fixture used by automated testing. It simulates platform event logs, chat analytics, manual operations marks, and public clip metadata.

## Outputs

The UI renders ranked highlight cards, timeline rows, summary counters, filtered result sets, locally persisted input JSON, and an exported JSON cut list. `data/expected_outputs.json` defines the expected output shape for input summaries, ranked highlights, export behavior, and quality checks.

## Validation

`tests/browser_smoke_test.js` verifies the normal browser workflow. `tests/industrial_io_smoke_test.js` loads the industrial fixture, runs the real UI, checks ranking/filtering/storage/export behavior, and validates that expected outputs are visible.
