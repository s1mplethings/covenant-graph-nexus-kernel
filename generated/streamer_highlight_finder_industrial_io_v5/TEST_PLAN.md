# TEST_PLAN.md

## Overview
This document outlines the testing strategy for the `game_stream_highlight_identifier` project. The tests cover functionality, integration, performance, accuracy, and usability to ensure the system meets the defined acceptance criteria and quality standards.

---

## Test Categories

### 1. Import Functionality
**Objective:** Verify the system can successfully import industrial input bundles via file upload or textarea input.

**Checks:**
- File input (`file-input`) correctly reads and parses JSON files.
- Textarea input (`json-textarea`) correctly parses JSON text.
- Imported data is validated and normalized using `src/core/importer.js`.
- Invalid input triggers appropriate error messages in the UI (`status-summary`).

---

### 2. Scoring Engine
**Objective:** Ensure the scoring engine assigns accurate scores to imported records based on engagement metrics and metadata.

**Checks:**
- `scoreRecord` function correctly calculates scores for individual records.
- `sortRecords` function sorts records in descending order by score.
- Scored highlights are displayed in the UI (`records-container`) in the correct order.

---

### 3. Sorting and Filtering
**Objective:** Validate the filtering and sorting functionality for highlights based on user-selected criteria.

**Checks:**
- Filters for streamer (`filterStreamer`), game (`filterGame`), category (`filterCategory`), and minimum score (`filterScore`) are functional.
- `applyFilters` function correctly filters records based on selected criteria.
- Filtered results are displayed in the UI (`records-container`) and match user expectations.

---

### 4. Manual Marker
**Objective:** Test the manual tagging functionality for adding new highlights or adjusting scores.

**Checks:**
- Manual marker form (`manual-form`) correctly appends new records to the dataset.
- Newly added records are processed and displayed in the UI (`records-container`).
- Adjusted scores are reflected in the sorted results.

---

### 5. Export Functionality
**Objective:** Ensure the system can export filtered highlights as JSON or CSV files.

**Checks:**
- Export button (`export-button`) triggers the export process.
- `exportData` function generates a downloadable file using Blob and URL.createObjectURL.
- Exported files contain the correct filtered dataset.

---

### 6. LocalStorage Persistence
**Objective:** Verify the system can save and load records using localStorage.

**Checks:**
- `saveToLocalStorage` function correctly saves the current dataset.
- `loadFromLocalStorage` function correctly loads saved data.
- Data persists across page reloads.

---

### 7. Industrial Input Bundle Ingestion
**Objective:** Test the ingestion of simulated industrial input bundles.

**Checks:**
- `data/industrial_input_bundle.json` is correctly parsed and processed.
- Input summary is displayed in the UI (`status-summary`).
- Minimum record count (20) is met.
- Source manifest fields are correctly mapped and validated.

---

### 8. Expected Output Shape
**Objective:** Validate the structure and content of generated outputs.

**Checks:**
- Outputs match the expected shape defined in `data/expected_outputs.json`.
- Fields such as `ranked_highlights`, `export_cut_list`, `quality_checks`, and `input_summary` are correctly populated.

---

### 9. Source Coverage
**Objective:** Ensure all input sources are processed and represented in the dataset.

**Checks:**
- Platform event logs, chat analytics, manual marks, public clip metadata, and moderation annotations are correctly ingested.
- Source manifest fields (`source_id`, `source_type`, `origin`, etc.) are correctly mapped.

---

### 10. Console Errors
**Objective:** Verify the system runs without errors in the browser console.

**Checks:**
- No uncaught exceptions or runtime errors occur during normal operation.
- Warnings and errors are logged appropriately for debugging.

---

## Test Execution

### Unit Testing
**Scope:** Test individual modules for correct functionality.
- `src/core/scoring.js`: Test `scoreRecord` and `sortRecords`.
- `src/core/filtering.js`: Test `applyFilters`.
- `src/core/importer.js`: Test `parseRecordsFromText`, `normalizeRecord`, and `importData`.
- `src/core/exporter.js`: Test `downloadJson` and `exportData`.

---

### Integration Testing
**Scope:** Ensure modules work together seamlessly.
- Verify data flows correctly from import to scoring, filtering, manual tagging, and export.
- Test interactions between `src/state/store.js` and UI components.

---

### Performance Testing
**Scope:** Evaluate system scalability and processing speed.
- Test with large input bundles (e.g., 100+ records).
- Measure processing time for scoring, filtering, and exporting.

---

### Accuracy Testing
**Scope:** Validate automated scoring results.
- Compare scores against manual reviews for validation.
- Ensure filtered results match user-selected criteria.

---

### User Testing
**Scope:** Gather feedback from target users.
- Test usability of the GUI (`index.html`).
- Evaluate clarity and efficiency of workflows.

---

## Test Data

### Sample Input
- `data/sample_events.json`: Small dataset for initial testing.
- `data/industrial_input_bundle.json`: Simulated industrial input bundle.

### Expected Outputs
- `data/expected_outputs.json`: Defines the expected structure and content of outputs.

---

## Acceptance Criteria
- The project runs locally using `python -m http.server`.
- Users can import industrial input bundles via FileReader or textarea.
- Imported data is processed and displayed as scored highlights.
- Filter controls are visible and functional.
- Manual marker form appends new records and rerenders results.
- Export functionality generates downloadable files.
- LocalStorage persistence works as expected.

---

## Test Scripts

### Browser Smoke Test
**Path:** `tests/browser_smoke_test.js`
**Objective:** Verify basic functionality in the browser.

---

### Industrial I/O Smoke Test
**Path:** `tests/industrial_io_smoke_test.js`
**Objective:** Test ingestion and processing of industrial input bundles.

---

## Reporting
**Effectiveness:** Generate a report summarizing test results and identifying areas for improvement.
**Tools:** Use browser developer tools and automated testing frameworks.

---