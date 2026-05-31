# TEST_PLAN.md

## Overview
This document outlines the test plan for the game stream highlight tool. The tests cover core functionalities such as importing data, scoring, sorting, filtering, manual marker addition, exporting, localStorage persistence, and error handling. Each feature will be tested for correctness, usability, and performance.

---

## Test Cases

### 1. Import Functionality
**Objective:** Verify that stream data can be imported correctly via file input or JSON textarea.

- **Test Steps:**
  1. Provide a valid JSON file through the file input.
  2. Paste valid JSON data into the textarea.
  3. Click the "Import" button.
- **Expected Results:**
  - Data is parsed and displayed in the records container.
  - Invalid JSON triggers an error message in the status summary.
- **Edge Cases:**
  - Empty file or textarea.
  - Malformed JSON.

---

### 2. Scoring System
**Objective:** Ensure that records are scored accurately based on the scoring algorithm.

- **Test Steps:**
  1. Import a dataset with known values for scoring fields.
  2. Verify that each record's score matches the expected value.
- **Expected Results:**
  - Scores are calculated and displayed correctly.
- **Edge Cases:**
  - Records with missing or zero values for scoring fields.

---

### 3. Sorting Functionality
**Objective:** Verify that records are sorted in descending order of scores.

- **Test Steps:**
  1. Import a dataset with varying scores.
  2. Check the order of records in the records container.
- **Expected Results:**
  - Records are displayed in descending order of scores.
- **Edge Cases:**
  - Records with identical scores.

---

### 4. Filtering Functionality
**Objective:** Test the filtering of records by streamer, game, category, and score.

- **Test Steps:**
  1. Import a dataset with diverse values for filtering fields.
  2. Apply filters using the filter form.
  3. Verify that only matching records are displayed.
- **Expected Results:**
  - Filters are applied correctly, and results update dynamically.
- **Edge Cases:**
  - Filters with no matching records.
  - Combination of multiple filters.

---

### 5. Manual Marker
**Objective:** Verify that users can manually add new records.

- **Test Steps:**
  1. Fill out the manual marker form with valid data.
  2. Submit the form.
  3. Verify that the new record appears in the records container.
- **Expected Results:**
  - New records are appended and displayed correctly.
- **Edge Cases:**
  - Missing or invalid form fields.

---

### 6. Export Functionality
**Objective:** Ensure that filtered results can be exported as a JSON file.

- **Test Steps:**
  1. Apply filters to the dataset.
  2. Click the "Export" button.
  3. Verify that the downloaded file contains the filtered records.
- **Expected Results:**
  - Exported file matches the current filtered dataset.
- **Edge Cases:**
  - Export with no records (empty dataset).

---

### 7. LocalStorage Persistence
**Objective:** Test that data is saved to and restored from localStorage.

- **Test Steps:**
  1. Import a dataset and make changes (e.g., add a manual marker).
  2. Refresh the page.
  3. Verify that the data is restored correctly.
- **Expected Results:**
  - Data persists across page reloads.
- **Edge Cases:**
  - Clearing localStorage and reloading the page.

---

### 8. Console Error Handling
**Objective:** Ensure that no uncaught errors occur during normal usage.

- **Test Steps:**
  1. Perform all major actions (import, filter, score, sort, export, etc.).
  2. Monitor the browser console for errors.
- **Expected Results:**
  - No uncaught errors or warnings in the console.
- **Edge Cases:**
  - Invalid user inputs or unexpected data formats.

---

## Tools and Frameworks
- **Unit Testing:** Jest, Mocha
- **Integration Testing:** Cypress, Postman
- **Performance Testing:** Lighthouse, WebPageTest
- **Browser Testing:** Chrome, Firefox, Edge

---

## Acceptance Criteria
- All tests must pass with no critical issues.
- The application must meet the functional requirements outlined in the project plan.
- Performance must remain acceptable for datasets up to 4 hours of stream data.

---

## Test Execution
- **Environment:** Local development server (`python -m http.server`).
- **Test Data:** Use `data/sample_events.json` and edge case datasets.
- **Frequency:** Tests will be executed after each major feature implementation and before release.

---

## Reporting
- Test results will be documented in a test report, including:
  - Passed/failed test cases.
  - Identified bugs and their severity.
  - Suggestions for improvement.

--- 

## Conclusion
This test plan ensures that the game stream highlight tool is robust, user-friendly, and performs well under various conditions. All core functionalities will be thoroughly validated to meet user needs and project goals.