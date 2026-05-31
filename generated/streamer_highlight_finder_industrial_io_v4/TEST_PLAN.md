# TEST_PLAN.md

## Overview
This document outlines the testing strategy for the `game_stream_highlight_analyzer` project. The tests cover functionality, integration, performance, and usability to ensure the tool meets the acceptance criteria and provides a seamless user experience.

---

## Test Categories

### 1. Import Functionality
**Objective:** Verify that industrial input bundles can be successfully imported and processed.

- **Test Cases:**
  - Import valid JSON files via file input.
  - Import JSON data via textarea input.
  - Handle invalid JSON gracefully (e.g., malformed data).
  - Ensure imported data is normalized into the expected shape.

- **Expected Results:**
  - Data is parsed and displayed in the GUI.
  - Errors are logged to the console for invalid inputs.

---

### 2. Scoring Engine
**Objective:** Validate the scoring logic for ranking highlights.

- **Test Cases:**
  - Score records based on predefined criteria (e.g., intensity, chatRate, viewer spikes).
  - Ensure scores are calculated consistently across different datasets.
  - Sort records by score in descending order.

- **Expected Results:**
  - Records are scored accurately.
  - Records are sorted correctly in the results panel.

---

### 3. Filtering and Sorting
**Objective:** Ensure users can filter and sort highlights effectively.

- **Test Cases:**
  - Filter by streamer, game, category, and score range.
  - Combine multiple filters and verify results.
  - Sort filtered results by score, timestamp, or other fields.

- **Expected Results:**
  - Filters apply correctly and update the results panel.
  - Sorting logic works as expected.

---

### 4. Manual Marker
**Objective:** Test the functionality for adding manual annotations.

- **Test Cases:**
  - Add a new highlight via the manual marker form.
  - Ensure the new highlight appears in the results panel.
  - Verify that manual highlights persist in local storage.

- **Expected Results:**
  - Manual highlights are appended to the dataset.
  - Results panel updates dynamically.

---

### 5. Export Functionality
**Objective:** Validate the export process for filtered highlights.

- **Test Cases:**
  - Export filtered results as a JSON file.
  - Verify the exported file matches the current filtered dataset.
  - Ensure export functionality works across different browsers.

- **Expected Results:**
  - Exported file contains the correct data.
  - Export action triggers a download without errors.

---

### 6. Local Storage
**Objective:** Test the persistence of working data using localStorage.

- **Test Cases:**
  - Save working data to localStorage.
  - Reload the page and verify data restoration.
  - Clear localStorage and ensure the app resets correctly.

- **Expected Results:**
  - Data persists across page reloads.
  - Clearing localStorage resets the app state.

---

### 7. Industrial Input Bundle Ingestion
**Objective:** Simulate ingestion of industrial-grade input bundles.

- **Test Cases:**
  - Import simulated industrial input bundles containing platform logs, chat analytics, and manual annotations.
  - Verify the input summary and quality checks.
  - Ensure the minimum record count (20) is met.

- **Expected Results:**
  - Input bundles are processed correctly.
  - Quality checks and summaries are displayed in the GUI.

---

### 8. Expected Output Shape
**Objective:** Ensure the output matches the expected shape.

- **Test Cases:**
  - Verify the structure of ranked highlights.
  - Check the format of exported cut lists.
  - Ensure quality checks and input summaries are accurate.

- **Expected Results:**
  - Outputs conform to the documented shape.

---

### 9. Source Coverage
**Objective:** Test the integration of multiple data sources.

- **Test Cases:**
  - Import data from simulated sources (e.g., platform logs, chat analytics, manual annotations).
  - Verify that all source fields are utilized in scoring and filtering.

- **Expected Results:**
  - Data from all sources is integrated seamlessly.
  - Scoring and filtering logic accounts for all fields.

---

### 10. Console Errors
**Objective:** Ensure the app handles errors gracefully.

- **Test Cases:**
  - Trigger errors by importing invalid data.
  - Simulate runtime errors in scoring, filtering, and exporting.
  - Verify that errors are logged to the console with clear messages.

- **Expected Results:**
  - Errors are logged without crashing the app.
  - Console messages provide actionable information.

---

## Testing Tools
- **Unit Testing Framework:** Jest
- **Integration Testing Framework:** Cypress
- **Browser Compatibility Testing:** Manual testing across Chrome, Firefox, and Edge.
- **Performance Testing:** Lighthouse

---

## Acceptance Criteria
- The project must run locally from `index.html` using `python -m http.server`.
- All modules must pass unit and integration tests.
- The GUI must function as expected, with no critical usability issues.
- The app must handle large datasets without significant lag.
- Outputs must conform to the documented shape and quality standards.

---

## Test Execution
- **Unit Tests:** Run using `npm test`.
- **Integration Tests:** Execute with `npm run test:integration`.
- **Browser Tests:** Open `tests/browser_smoke_test.js` in a browser environment.
- **Industrial I/O Tests:** Run `tests/industrial_io_smoke_test.js` with simulated input bundles.

---

## Reporting
- Test results will be documented in `docs/TEST_RESULTS.md`.
- Performance metrics will be included in `docs/EFFECT_REPORT.md`.
- Any issues will be logged in the project issue tracker.

---

## Conclusion
This test plan ensures comprehensive coverage of all critical functionalities, providing confidence in the tool's reliability and usability.