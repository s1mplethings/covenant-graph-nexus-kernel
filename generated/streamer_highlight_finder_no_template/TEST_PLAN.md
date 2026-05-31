# Test Plan

- Open `index.html` under `python -m http.server`.
- Confirm sample data loads and records are scored descending.
- Import JSON with the same field shape and confirm results update.
- Filter by streamer, game, category, and minimum score.
- Add a manual marker and confirm it appears in the result list.
- Refresh and confirm localStorage restores current data.
- Export clips and confirm a JSON file is downloaded.
