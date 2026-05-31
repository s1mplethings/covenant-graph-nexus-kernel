# TEST_PLAN.md

## Overview
This document outlines the test plan for the game highlight detection project. The tests cover all critical functionalities, including data import, scoring, sorting, filtering, manual marker addition, exporting, localStorage persistence, and error handling.

---

## Test Cases

### 1. Data Import Functionality
**Description:** Verify that JSON data can be imported via FileReader or textarea and is processed correctly.  
**Steps:**
1. Navigate to the data import screen.
2. Use the file input (`file-input`) to upload a valid JSON file.
3. Alternatively, paste JSON data into the textarea (`json-textarea`) and click the import button (`import-button`).
4. Verify that the imported data is displayed in the records container (`records-container`).

**Expected Result:**  
- Imported data is parsed and displayed in the application.
- Invalid JSON triggers an error message in the UI.

---

### 2. Highlight Detection Scoring
**Description:** Ensure that the scoring function calculates scores accurately and sorts items in descending order.  
**Steps:**
1. Import a dataset with varying intensity, chatRate, and other scoring factors.
2. Navigate to the highlight detection screen.
3. Verify that scores are calculated and displayed for each record.
4. Confirm that records are sorted in descending order of their scores.

**Expected Result:**  
- Scores are calculated correctly based on the scoring algorithm.
- Records are displayed in descending order of their scores.

---

### 3. Filter and Sort Controls
**Description:** Test that filter and sort controls work as expected for all fields.  
**Steps:**
1. Import a dataset with diverse values for streamer, game, category, and score.
2. Use the filter form (`filter-form`) to apply filters:
   - Streamer (`filterStreamer`)
   - Game (`filterGame`)
   - Category (`filterCategory`)
   - Minimum Score (`filterScore`)
3. Verify that the dataset is filtered and sorted correctly.

**Expected Result:**  
- Only records matching the filter criteria are displayed.
- Sorting is applied correctly based on the selected criteria.

---

### 4. Manual Marker Functionality
**Description:** Verify that users can manually add or edit highlights and see the updated dataset.  
**Steps:**
1. Navigate to the manual marker screen.
2. Fill out the manual marker form (`manual-form`) with valid data.
3. Submit the form and verify that the new record is appended to the dataset.
4. Edit an existing record and verify that changes are reflected.

**Expected Result:**  
- New records are added to the dataset and displayed.
- Edited records are updated correctly in the dataset.

---

### 5. Export Functionality
**Description:** Test that the filtered dataset can be exported as a downloadable file.  
**Steps:**
1. Apply filters to the dataset.
2. Click the export button (`export-button`).
3. Verify that a JSON file is downloaded.
4. Open the downloaded file and confirm that it matches the filtered dataset.

**Expected Result:**  
- A JSON file containing the filtered dataset is downloaded.
- The file content matches the current filtered dataset.

---

### 6. LocalStorage Persistence
**Description:** Ensure that working data is saved to localStorage and reloaded on page load.  
**Steps:**
1. Import a dataset and apply filters.
2. Reload the page.
3. Verify that the dataset and filters are restored from localStorage.

**Expected Result:**  
- Dataset and filters persist across page reloads.
- Data is correctly loaded from localStorage.

---

### 7. Console Error Handling
**Description:** Verify that no unexpected errors are logged to the browser console during normal operation.  
**Steps:**
1. Perform all major actions in the application, including import, scoring, filtering, manual marking, and exporting.
2. Monitor the browser console for errors or warnings.

**Expected Result:**  
- No unexpected errors or warnings are logged to the console.

---

## Test Environment
- **Browser:** Latest versions of Chrome, Firefox, and Edge.
- **Server:** Local server using `python -m http.server`.
- **Sample Data:** `data/sample_events.json`.

---

## Test Execution
- **Tester:** Assigned QA Engineer.
- **Timeline:** To be completed within the project testing phase.
- **Reporting:** Document all test results, including passed and failed cases, in the test report.

---

## Acceptance Criteria
1. All test cases must pass without errors.
2. The application must meet all functional requirements outlined in the shared context.
3. No critical console errors should occur during testing.

---

## Notes
- Ensure that all edge cases (e.g., invalid JSON, empty datasets, extreme filter values) are tested.
- Provide screenshots or logs for any failed test cases.