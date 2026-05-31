# TEST_PLAN.md

## Overview
This document outlines the test plan for verifying the functionality of the project designed to identify and manage gaming streamers' highlight moments. The tests cover import, scoring, sorting, filtering, manual marker addition, export, localStorage persistence, and console error handling.

---

## Test Cases

### 1. Import Functionality
**Objective:** Verify that the application can import live event data via JSON file or textarea input.

- **Test Steps:**
  1. Open the application in a browser.
  2. Use the import functionality to upload a valid JSON file containing event data.
  3. Alternatively, paste JSON data into the provided textarea and trigger the import.
- **Expected Results:**
  - The imported data is processed and displayed in the application.
  - Invalid JSON files or malformed data should trigger an error message.

---

### 2. Scoring Functionality
**Objective:** Ensure that the application assigns numeric scores to imported records based on predefined criteria.

- **Test Steps:**
  1. Import a dataset with various event attributes (e.g., intensity, chatRate, keywords).
  2. Verify that each record is assigned a score.
- **Expected Results:**
  - Scores are calculated and displayed for all records.
  - Scoring logic is consistent and matches the predefined algorithm.

---

### 3. Sorting Functionality
**Objective:** Verify that records are sorted in descending order based on their scores.

- **Test Steps:**
  1. Import a dataset with varying scores.
  2. Check the order of displayed records.
- **Expected Results:**
  - Records are sorted from highest to lowest score.
  - Sorting updates dynamically when scores change.

---

### 4. Filter Functionality
**Objective:** Test the ability to filter records by streamer, game, category, and score.

- **Test Steps:**
  1. Import a dataset with diverse values for streamer, game, category, and score.
  2. Apply filters for each field individually and in combination.
- **Expected Results:**
  - Only records matching the filter criteria are displayed.
  - Filters can be reset to show all records.

---

### 5. Manual Marker Functionality
**Objective:** Verify that users can manually add new records to the dataset.

- **Test Steps:**
  1. Use the manual marker form to input a new record.
  2. Submit the form and check the dataset.
- **Expected Results:**
  - The new record is appended to the dataset.
  - The dataset is re-rendered to include the new record.

---

### 6. Export Functionality
**Objective:** Ensure that the application can export the current filtered dataset.

- **Test Steps:**
  1. Apply filters to the dataset.
  2. Use the export functionality to download the filtered dataset.
- **Expected Results:**
  - The exported file contains only the filtered records.
  - The file is in JSON format and matches the displayed data.

---

### 7. LocalStorage Persistence
**Objective:** Verify that the application persists data in localStorage and restores it on page reload.

- **Test Steps:**
  1. Import a dataset and apply changes (e.g., filters, manual markers).
  2. Reload the page.
- **Expected Results:**
  - The dataset and changes are restored from localStorage.
  - No data is lost during the reload.

---

### 8. Console Error Handling
**Objective:** Ensure that the application does not produce unexpected console errors.

- **Test Steps:**
  1. Perform all major actions (import, filter, score, sort, add marker, export).
  2. Monitor the browser console for errors.
- **Expected Results:**
  - No unexpected errors appear in the console.
  - Any errors are descriptive and actionable.

---

## Test Environment
- **Browser:** Latest versions of Chrome, Firefox, and Edge.
- **Server:** Local server using `python -m http.server`.
- **Test Data:** Valid and invalid JSON datasets with diverse attributes.

---

## Acceptance Criteria
- All test cases pass without errors.
- The application meets the functional requirements outlined in the shared context.
- No critical issues are found during testing.

---

## Notes
- Additional edge cases and stress tests may be added as needed.
- Test results will be documented in a separate report.