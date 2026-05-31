# TEST_PLAN.md

## Overview
This document outlines the test plan for the `highlight_moment_detector` project. The tests cover functionality for importing data, scoring, sorting, filtering, manual marker addition, exporting, localStorage persistence, and console error handling.

---

## Test Cases

### 1. Import JSON Data
**Objective:** Verify that JSON data can be successfully imported and displayed in the UI.

**Steps:**
1. Open the application in a browser.
2. Use the file input or textarea to upload a sample JSON file (`data/sample_events.json`).
3. Click the "Import" button.

**Expected Result:**  
- Data is parsed correctly and displayed in the records container.
- No console errors are logged.

---

### 2. Score Calculation
**Objective:** Ensure scores are calculated correctly based on intensity, chatRate, and other factors.

**Steps:**
1. Import the sample JSON file.
2. Verify that each record has a calculated `score` field.

**Expected Result:**  
- Scores are calculated using the scoring function (`scoreRecord`) and match expected values.
- Records are sorted in descending order by score.

---

### 3. Sort Records
**Objective:** Verify that records are sorted correctly by score.

**Steps:**
1. Import the sample JSON file.
2. Check the order of records displayed in the UI.

**Expected Result:**  
- Records are sorted in descending order by score.
- Sorting logic (`sortRecords`) is applied correctly.

---

### 4. Filter Application
**Objective:** Test the functionality of filters for streamer, game, category, and score.

**Steps:**
1. Import the sample JSON file.
2. Use the filter form to apply filters (e.g., filter by streamer name, game title, category, or minimum score).
3. Submit the filter form.

**Expected Result:**  
- Records are filtered based on the applied criteria.
- Filter logic (`applyFilters`) works as expected.
- UI updates to display only the filtered records.

---

### 5. Manual Highlight Addition
**Objective:** Verify that manually added highlights are appended to the dataset and displayed in the UI.

**Steps:**
1. Import the sample JSON file.
2. Use the manual marker form to add a new highlight.
3. Submit the form.

**Expected Result:**  
- The new highlight is appended to the dataset.
- The UI updates to include the new highlight.
- Data is saved to localStorage.

---

### 6. Export Functionality
**Objective:** Ensure filtered results can be exported as a downloadable file.

**Steps:**
1. Apply filters to the dataset.
2. Click the "Export" button.

**Expected Result:**  
- A downloadable JSON file is generated containing the filtered results.
- Export logic (`exportData`) works correctly using Blob and URL.createObjectURL.

---

### 7. Local Storage Persistence
**Objective:** Verify that data persists across page reloads using localStorage.

**Steps:**
1. Import the sample JSON file.
2. Apply filters and add a manual highlight.
3. Reload the page.

**Expected Result:**  
- Data is restored from localStorage.
- Filters and manual highlights persist across reloads.

---

### 8. Console Error Handling
**Objective:** Ensure no unexpected errors are logged to the console during normal operations.

**Steps:**
1. Perform all major actions (import, filter, score, sort, manual marker, export).
2. Monitor the browser console for errors.

**Expected Result:**  
- No unexpected errors are logged to the console.

---

## Test Environment
- **Browser:** Latest versions of Chrome, Firefox, and Edge.
- **Server:** Local server using `python -m http.server`.
- **Sample Data:** `data/sample_events.json`.

---

## Acceptance Criteria
- All test cases pass without errors.
- The application meets functional requirements as outlined in the shared context.
- No critical bugs or console errors are present.

---

## Notes
- Ensure sample data covers edge cases (e.g., missing fields, extreme values).
- Test responsiveness and UI behavior across different screen sizes.